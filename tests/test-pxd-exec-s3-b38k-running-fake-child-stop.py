#!/usr/bin/env python3
"""B38-K: disposable *running* S1-sandbox fake child and OS stop observation.

This fake-only OS-process test is not provider cancellation, malicious-child
attestation, authenticated B33 observation, or an atomic cancel-vs-spawn lease.
"""
import argparse
from dataclasses import dataclass
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b29_transport_ledger import canonical_binding
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture
from px_s3_b38i_fake_launch_claim import AtomicFakeLaunchClaim, Refused as B38IRefused
from px_s3_b37b_sealed_handoff import SealedFixture

def load_g():
    name = "b38k_existing_g_fake"
    path = ROOT / "tests" / "test-pxd-exec-s3-b38g-external-fake-supervisor.py"
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module

G = load_g()
FAKE_LOOP_LIMIT = 20
START_TIMEOUT = 5
STOP_TIMEOUT = 5
HEARTBEAT_SETTLE = .30
CHILD = r"""
import pathlib,os,time
marker = pathlib.Path("/scratch/b38k-running-" + NONCE)
marker.write_text(NONCE + ":" + str(os.getpid()) + ":0")
for i in range(1,400):
    time.sleep(.05)
    marker.write_text(NONCE + ":" + str(os.getpid()) + ":" + str(i))
"""
class Refused(RuntimeError):
    pass

def deny(reason):
    raise Refused("B38K_REFUSED_" + reason)

@dataclass
class LiveFakeChild:
    proc: subprocess.Popen
    marker: Path
    nonce: str
    attempt_id: str
    pid: int

@dataclass(frozen=True)
class HostStopObservation:
    host_bwrap_pid: int
    host_wait_exit_code: int
    bwrap_reaped: bool
    child_heartbeat_quiescent: bool
    ledger_cancel_pending: bool
    fake_budget_held: bool
    automatic_retry: bool = False
    authenticated_peer: bool = False
    independent_b33_witness: bool = False
    real_stop_verified: bool = False
    provider_calls: int = 0
    production_ready: bool = False

def launch_running_fake(atomic, claimant, sealed, *, current_binding, s1, root):
    """Starts fixed fake loop inside existing S1 Bubblewrap after B38-I claim.

    Existing B38-J/B38-G code remains unchanged. This is NOT a default sender.
    """
    if (type(atomic) is not AtomicOfflineFixture or
        type(claimant) is not AtomicFakeLaunchClaim or
        claimant.atomic is not atomic or type(sealed) is not SealedFixture):
        deny("FIXTURE_TYPES_REQUIRED")
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        deny("DISPOSABLE_ROOT_INVALID")
    if not hasattr(s1, "build_command") or not hasattr(s1, "trusted_bwrap_binary"):
        deny("S1_MISSING")
    try:
        record = atomic.ledger.state(sealed.attempt_id)
        if (record["state"] != "SUBMISSION_UNCONFIRMED" or
            record["clientRequestId"] != sealed.client_request_id or
            record["retryAuthorized"] is not False or
            not claimant.claim_recorded(sealed.attempt_id) or
            record["turnId"] != current_binding["turnId"] or
            json.loads(canonical_binding(current_binding))["generation"] < 1):
            deny("CLAIM_OR_CANCEL_STATE_INVALID")
        if s1.trusted_bwrap_binary() != "/usr/bin/bwrap":
            deny("TRUSTED_S1_UNAVAILABLE")
    except (B38IRefused, sqlite3.Error, KeyError, ValueError) as exc:
        deny("FAKE_LEDGER_UNAVAILABLE")
    nonce = secrets.token_hex(16)
    script = "NONCE = " + repr(nonce) + "\n" + CHILD
    try:
        cmd = s1.build_command(root, script)
    except s1.IsolationUnavailable:
        deny("S1_PROFILE_INVALID")
    if (cmd[0] != "/usr/bin/bwrap" or "--unshare-all" not in cmd or
        "--die-with-parent" not in cmd or "--clearenv" not in cmd or
        "--new-session" not in cmd or "--ro-bind" not in cmd):
        deny("S1_PROFILE_NOT_ISOLATED")
    marker = root / "scratch" / ("b38k-running-" + nonce)
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
            env=dict(s1.ENVIRONMENT), cwd="/",
        )
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if marker.is_file() and not marker.is_symlink():
                content = marker.read_text()
                if content.startswith(nonce + ":") and content.count(":") == 2:
                    if proc.poll() is not None:
                        deny("FAKE_CHILD_EXITED_BEFORE_STOP")
                    return LiveFakeChild(proc, marker, nonce,
                                         sealed.attempt_id, proc.pid)
            if proc.poll() is not None:
                deny("FAKE_BWRAP_EARLY_EXIT")
            time.sleep(.025)
        deny("FAKE_RUNNING_MARKER_MISSING")
    except Exception:
        if proc is not None:
            terminate_owned(proc)
        raise

def terminate_owned(proc):
    """Best-effort cleanup of a Popen object the test itself created."""
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        deny("FAKE_WRAPPER_REAP_UNCONFIRMED")

def cancel_running_fake(atomic, live):
    """Commit synthetic cancel, OS signal owned wrapper group, reap and observe.

    This reports bwrap wrapper OS death and heartbeat quiescence, NOT
    independently authenticated sandbox descendant stop or provider stop.
    """
    if type(atomic) is not AtomicOfflineFixture or type(live) is not LiveFakeChild:
        deny("TEST_ONLY_HANDLE_REQUIRED")
    proc = live.proc
    if proc.pid != live.pid or proc.poll() is not None or not live.marker.is_file():
        deny("NOT_RUNNING_OWNED_WRAPPER")
    last = live.marker.read_text()
    if not last.startswith(live.nonce + ":"):
        deny("RUNNING_MARKER_MISMATCH")
    if atomic.ledger.state(live.attempt_id)["state"] != "SUBMISSION_UNCONFIRMED":
        deny("CANCEL_STATE_ALREADY_CHANGED")
    # Atomic B29 cancellation happens before OS signal. A process may run
    # during this interval. The receipt never calls this remote stop.
    recorded = atomic.cancel_mock(live.attempt_id)
    if recorded["state"] != "CANCEL_PENDING":
        deny("CANCEL_NOT_RECORDED")
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        deny("FAKE_WRAPPER_LOST_BEFORE_SIGNAL")
    try:
        code = proc.wait(timeout=STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        terminate_owned(proc)
        deny("GRACEFUL_WRAPPER_STOP_NOT_VERIFIED")
    if proc.poll() is None:
        deny("FAKE_WRAPPER_NOT_REAPED")
    try:
        snap = live.marker.read_text()
        time.sleep(HEARTBEAT_SETTLE)
        after = live.marker.read_text()
    except OSError:
        deny("FAKE_HEARTBEAT_EVIDENCE_MISSING")
    if snap != after:
        deny("FAKE_CHILD_HEARTBEAT_CONTINUED")
    if atomic.ledger.state(live.attempt_id)["state"] != "CANCEL_PENDING":
        deny("CANCEL_DURABILITY_MISSING")
    budget = atomic.ledger.budget("b38kScope")
    if budget["reserved_units"] != 25 or budget["used_units"] != 0:
        deny("FAKE_BUDGET_NOT_HELD")
    return HostStopObservation(
        host_bwrap_pid=live.pid, host_wait_exit_code=code,
        bwrap_reaped=True, child_heartbeat_quiescent=True,
        ledger_cancel_pending=True, fake_budget_held=True,
    )

class Tests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="b38k-running-fake-")
        self.addCleanup(td.cleanup)
        self.root = Path(td.name).resolve(strict=True)
        db = self.root / "b29-fixture.sqlite3"
        self.db = db
        self.conn = sqlite3.connect(db, isolation_level=None, timeout=5)
        self.addCleanup(self.conn.close)
        self.atomic = AtomicOfflineFixture(self.conn, TestOnlyEvidenceIssuer())
        self.atomic.configure_mock_budget("b38kScope", 100)
        self.claimant = AtomicFakeLaunchClaim(self.atomic)
        self.sealed, self.binding = G.fixture()
        self.s1 = G.load_s1()
        (self.root / "sandbox").mkdir(mode=0o700)
        self.sandbox, _ = G.prepare_disposable_root(str(self.root / "sandbox"))

    def registered(self):
        self.atomic.register_mock(self.sealed, scope="b38kScope", units=25,
                                  current_binding=self.binding)

    def claimed(self):
        self.registered()
        self.atomic.begin_mock(self.sealed, current_binding=self.binding,
                               offered_bytes=self.sealed.payload)
        self.claimant.claim_mock(self.sealed, current_binding=self.binding)

    def start(self):
        child = launch_running_fake(self.atomic, self.claimant, self.sealed,
                                    current_binding=self.binding,
                                    s1=self.s1, root=self.sandbox)
        self.addCleanup(lambda: terminate_owned(child.proc))
        return child

    def test_no_claim_denies_fake_spawn(self):
        self.registered()
        with mock.patch("subprocess.Popen") as spawned:
            with self.assertRaises(Refused):
                self.start()
            spawned.assert_not_called()

    def test_cancel_before_start_denies_fake_spawn(self):
        self.claimed()
        self.atomic.cancel_mock(self.sealed.attempt_id)
        with mock.patch("subprocess.Popen") as spawned:
            with self.assertRaises(Refused):
                self.start()
            spawned.assert_not_called()

    def test_revoke_before_start_denies_fake_spawn(self):
        self.claimed()
        self.atomic.revoke_if_changed(self.sealed.attempt_id,
             {**self.binding, "generation": self.binding["generation"] + 1})
        with mock.patch("subprocess.Popen") as spawned:
            with self.assertRaises(Refused):
                self.start()
            spawned.assert_not_called()

    def test_real_running_fake_child_cancel_signal_reap(self):
        self.claimed()
        live = self.start()
        self.assertIsNone(live.proc.poll())
        self.assertIn(live.nonce, live.marker.read_text())
        observation = cancel_running_fake(self.atomic, live)
        self.assertTrue(observation.bwrap_reaped)
        self.assertTrue(observation.child_heartbeat_quiescent)
        self.assertTrue(observation.fake_budget_held)
        self.assertFalse(observation.independent_b33_witness)
        self.assertFalse(observation.real_stop_verified)
        self.assertEqual(self.atomic.ledger.state(self.sealed.attempt_id)["state"],
                         "CANCEL_PENDING")
        self.assertFalse(self.atomic.snapshot(
            self.sealed.attempt_id)["durableMockObservation"])

    def test_stop_replay_denied_after_process_reaped(self):
        self.claimed()
        live = self.start()
        cancel_running_fake(self.atomic, live)
        with self.assertRaisesRegex(Refused, "NOT_RUNNING"):
            cancel_running_fake(self.atomic, live)
        with mock.patch("subprocess.Popen") as spawned:
            with self.assertRaises(Refused):
                self.start()
            spawned.assert_not_called()

    def test_running_cancel_restart_claim_remains_no_retry(self):
        self.claimed()
        live = self.start()
        cancel_running_fake(self.atomic, live)
        self.conn.close()
        with sqlite3.connect(self.db, isolation_level=None, timeout=5) as conn:
            atomic = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
            claims = AtomicFakeLaunchClaim(atomic)
            self.assertTrue(claims.claim_recorded(self.sealed.attempt_id))
            snap = atomic.recover_mock(self.sealed, current_binding=self.binding)
            self.assertEqual(snap["state"], "CANCEL_PENDING")
            self.assertIs(snap["retryAuthorized"], False)
            with self.assertRaises(B38IRefused):
                claims.claim_mock(self.sealed, current_binding=self.binding)

    def test_trusted_bwrap_missing_fails_before_spawn(self):
        self.claimed()
        with mock.patch.object(self.s1, "trusted_bwrap_binary",
                               side_effect=self.s1.IsolationUnavailable("missing")):
            with mock.patch("subprocess.Popen") as spawned:
                with self.assertRaises(self.s1.IsolationUnavailable):
                    self.start()
                spawned.assert_not_called()

    def test_no_production_provider_or_b33_witness(self):
        self.claimed()
        live = self.start()
        observed = cancel_running_fake(self.atomic, live)
        self.assertEqual(observed.provider_calls, 0)
        self.assertFalse(observed.authenticated_peer)
        self.assertFalse(observed.real_stop_verified)
        self.assertFalse(observed.production_ready)
        self.assertFalse(observed.automatic_retry)

def smoke():
    suite = unittest.TestSuite([
        Tests("test_real_running_fake_child_cancel_signal_reap"),
        Tests("test_running_cancel_restart_claim_remains_no_retry"),
    ])
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    if not outcome.wasSuccessful():
        deny("REAL_CHILD_OS_STOP_SMOKE_FAILED")
    return {
        "state": "B38K_RUNNING_FAKE_CHILD_STOP_PASS",
        "realBubblewrapProcess": True, "syntheticChildActuallyRunning": True,
        "hostSignalAndReap": True, "childHeartbeatQuiescent": True,
        "durableCancelPending": True, "budgetHeld": True,
        "replayAfterRestart": False, "authenticatedB33Observer": False,
        "realStopVerified": False, "physicalCancelSpawnAtomic": False,
        "providerCalls": 0, "productionReady": False,
    }

def main():
    arg = argparse.ArgumentParser()
    g = arg.add_mutually_exclusive_group(required=True)
    g.add_argument("--unit", action="store_true")
    g.add_argument("--smoke", action="store_true")
    a = arg.parse_args()
    if a.unit:
        test = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(test).wasSuccessful() else 1
    try:
        print(json.dumps(smoke(), sort_keys=True))
        return 0
    except Refused as e:
        print(str(e), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
