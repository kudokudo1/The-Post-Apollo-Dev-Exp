#!/usr/bin/env python3
"""B38-J: separate fake launch worker, host OS-exit observer and cancellation gate.

Offline synthetic security experiment. Does NOT provide an authenticated
remote observer, actual OS-spawn atomicity, real credentials or Hospital access.
Input is a single fixed fake-only command; no arbitrary command execution.
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
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture
from px_s3_b38i_fake_launch_claim import AtomicFakeLaunchClaim, Refused as ClaimRefused

def load_g():
    name = "b38j_existing_fake_g"
    if name in sys.modules:
        return sys.modules[name]
    path = ROOT / "tests" / "test-pxd-exec-s3-b38g-external-fake-supervisor.py"
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod

G = load_g()
PROTOCOL = "B38J_FAKE_WORKER_V1"
READY = "READY"
CANCELLED = "CANCELLED_NO_CHILD"
REFUSED = "REFUSED_NO_CHILD"
RESULT = "FAKE_RESULT_UNTRUSTED"
MAX_OUTPUT = 4096
WORKER_TIMEOUT = 35

class Refused(RuntimeError):
    pass

def deny(code):
    raise Refused("B38J_REFUSED_" + code)

def frame(stage, nonce, **extras):
    return (json.dumps(
        {"schema": PROTOCOL, "stage": stage, "nonce": nonce, **extras},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ) + "\n").encode("ascii")

def _line(stage, nonce, **extras):
    sys.stdout.buffer.write(frame(stage, nonce, **extras))
    sys.stdout.buffer.flush()

def fixture_connection(path):
    return sqlite3.connect(path, isolation_level=None, timeout=5)

def fake_worker(db, nonce):
    """Only invoked in an explicit disposable child subprocess.

    Parent must have marked and claimed B37-C/B38-I in SQLite. Worker only
    accepts LAUNCH/CANCEL/CRASH fixture commands. No imported model SDK.
    """
    if os.environ.get("B38J_FAKE_WORKER_ONLY") != "1":
        deny("TEST_ONLY_ENV_REQUIRED")
    if type(nonce) is not str or len(nonce) != 32 or any(c not in "0123456789abcdef" for c in nonce):
        deny("NONCE_INVALID")
    if not db.is_file() or db.is_symlink():
        deny("DISPOSABLE_DB_REQUIRED")
    sealed, binding = G.fixture()
    with fixture_connection(db) as conn:
        atomic = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
        claims = AtomicFakeLaunchClaim(atomic)
        _line(READY, nonce, workerPid=os.getpid())
        # One bounded, fixed test message, no arbitrary command or JSON shell.
        cmd = sys.stdin.buffer.readline(32)
        if cmd == b"CRASH\n":
            os._exit(77)
        if cmd == b"CANCEL\n":
            state = atomic.ledger.state(sealed.attempt_id)["state"]
            if state in ("RESERVED", "SUBMISSION_UNCONFIRMED",
                         "REMOTE_OUTCOME_UNKNOWN", "CANCEL_PENDING"):
                atomic.cancel_mock(sealed.attempt_id)
                _line(CANCELLED, nonce, workerPid=os.getpid())
                return 0
            _line(REFUSED, nonce, reason="CANCEL_STATE", workerPid=os.getpid())
            return 3
        if cmd != b"LAUNCH\n":
            _line(REFUSED, nonce, reason="COMMAND_INVALID", workerPid=os.getpid())
            return 3
        # The last fake-state read is still not atomic with OS process spawn.
        state = atomic.ledger.state(sealed.attempt_id)
        if (state["state"] != "SUBMISSION_UNCONFIRMED" or
            state["clientRequestId"] != sealed.client_request_id or
            state["retryAuthorized"] is not False or
            not claims.claim_recorded(sealed.attempt_id)):
            _line(REFUSED, nonce, reason="CLAIM_OR_STATE_INVALID",
                  workerPid=os.getpid())
            return 3
        # An extra fake assertion: any generation revocation is already in B29
        # state. A later racing revocation is NOT prevented by this check.
        s1 = G.load_s1()
        with tempfile.TemporaryDirectory(prefix="b38j-fake-sandbox-") as td:
            root = Path(td) / "sandbox"
            root.mkdir(mode=0o700)
            sandbox_root, secret = G.prepare_disposable_root(str(root))
            reply = G.external_supervisor_fake_exchange(
                s1, sandbox_root, secret, sealed, current_binding=binding,
            )
        if (type(reply) is not G.FakeHostSandboxReceipt or
            reply.text != G.TEXT or
            reply.request_id != sealed.client_request_id or
            reply.sandbox_local_pid != G.EXPECTED_PID or
            reply.production_ready is not False or
            reply.launch_authorized is not False or
            reply.model_calls or reply.network_calls or reply.tool_calls):
            _line(REFUSED, nonce, reason="FAKE_CHILD_INVALID", workerPid=os.getpid())
            return 4
        # The worker's own statement is UNTRUSTED. Parent separately observes
        # worker OS exit code, never issues a B33 witness from this text.
        _line(RESULT, nonce, workerPid=os.getpid(), requestId=sealed.client_request_id,
              fakeText=reply.text, bwrapPid=reply.host_bwrap_pid,
              childPid=reply.sandbox_local_pid, providerCalls=0,
              productionReady=False, independentObservation=False)
        return 0

@dataclass(frozen=True)
class HostObservation:
    worker_pid: int
    exit_code: int
    stage: str
    frame_valid: bool
    host_reaped_worker: bool
    real_provider_calls: int = 0
    independent_b33_witness: bool = False
    authenticated_unix_peer: bool = False
    production_ready: bool = False
    real_stop_verified: bool = False

def observed_fake_worker(db, command, *, timeout=WORKER_TIMEOUT):
    """Host controls a real separate worker and observes its OS exit.

    A child's framed line is not an independently authenticated B33 event.
    The worker runs in its own process group, terminated as a group on errors.
    """
    if type(db) is not Path or not db.is_file() or db.is_symlink():
        deny("DISPOSABLE_DB_INVALID")
    if command not in ("LAUNCH", "CANCEL", "CRASH", "INVALID"):
        deny("COMMAND_NOT_FAKE")
    nonce = secrets.token_hex(16)
    env = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1", "B38J_FAKE_WORKER_ONLY": "1",
    }
    cmd = [
        sys.executable, "-B", str(Path(__file__).resolve()), "--worker",
        "--db", str(db.resolve(strict=True)), "--nonce", nonce,
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True,
            close_fds=True, env=env,
        )
        payload = (command + "\n").encode("ascii")
        output = G._bounded_communicate(
            proc, payload, max_stdout=MAX_OUTPUT, timeout=timeout,
        )
        exit_code = proc.returncode
        lines = output.splitlines()
        # Require exactly one initial READY frame and one final worker
        # result; a CRASH command deliberately has only READY.
        expected = 1 if command == "CRASH" else 2
        if len(lines) != expected:
            deny("BOUNDED_WORKER_FRAMING_INVALID")
        try:
            frames = [json.loads(line) for line in lines]
        except (ValueError, UnicodeDecodeError):
            deny("WORKER_REPLY_INVALID_JSON")
        for f in frames:
            if (type(f) is not dict or f.get("schema") != PROTOCOL or
                f.get("nonce") != nonce or
                type(f.get("workerPid")) is not int or
                f["workerPid"] != proc.pid):
                deny("WORKER_REPLY_NOT_BOUND")
        if frames[0].get("stage") != READY:
            deny("WORKER_NOT_READY")
        if command == "CRASH":
            if exit_code != 77:
                deny("CRASH_EXIT_NOT_OBSERVED")
            return HostObservation(proc.pid, exit_code, READY, True, True)
        end = frames[1]
        if command == "CANCEL":
            if exit_code != 0 or end.get("stage") != CANCELLED:
                deny("CANCEL_NOT_ACKNOWLEDGED")
        elif command == "LAUNCH":
            if exit_code == 0:
                sealed, _ = G.fixture()
                if (end.get("stage") != RESULT or
                    end.get("requestId") != sealed.client_request_id or
                    end.get("fakeText") != G.TEXT or
                    end.get("childPid") != G.EXPECTED_PID or
                    type(end.get("bwrapPid")) is not int or
                    end["bwrapPid"] <= G.EXPECTED_PID or
                    end.get("providerCalls") != 0 or
                    end.get("productionReady") is not False or
                    end.get("independentObservation") is not False):
                    deny("FAKE_RESULT_UNTRUSTED_OR_INVALID")
            elif exit_code != 3 or end.get("stage") != REFUSED:
                deny("LAUNCH_FAILURE_NOT_FENCED")
        elif command == "INVALID":
            if exit_code != 3 or end.get("stage") != REFUSED:
                deny("INVALID_COMMAND_NOT_REFUSED")
        return HostObservation(
            proc.pid, exit_code, end["stage"], True, True,
        )
    except (OSError, subprocess.SubprocessError, G.Refused) as exc:
        deny("WORKER_IO_OR_TIMEOUT")
    finally:
        if proc is not None:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                deny("WORKER_REAP_UNCONFIRMED")

class FakeLaunchWorkerTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="b38j-serialized-fake-")
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.db = self.root / "fixture.sqlite3"
        self.conn = fixture_connection(self.db)
        self.addCleanup(self.conn.close)
        self.atomic = AtomicOfflineFixture(self.conn, TestOnlyEvidenceIssuer())
        self.atomic.configure_mock_budget("b38jScope", 100)
        self.claims = AtomicFakeLaunchClaim(self.atomic)
        self.sealed, self.binding = G.fixture()

    def register(self):
        self.atomic.register_mock(
            self.sealed, scope="b38jScope", units=25,
            current_binding=self.binding,
        )

    def mark_claim(self):
        self.register()
        self.atomic.begin_mock(
            self.sealed, current_binding=self.binding,
            offered_bytes=self.sealed.payload,
        )
        self.claims.claim_mock(self.sealed, current_binding=self.binding)

    def state(self):
        return self.atomic.ledger.state(self.sealed.attempt_id)["state"]

    def test_launched_worker_requires_b38i_claim(self):
        self.register()
        got = observed_fake_worker(self.db, "LAUNCH")
        self.assertEqual(got.stage, REFUSED)
        self.assertEqual(got.exit_code, 3)
        self.assertFalse(self.claims.claim_recorded(self.sealed.attempt_id))
        self.assertEqual(self.state(), "RESERVED")

    def test_claim_without_cancel_launches_one_real_fake_child(self):
        self.mark_claim()
        got = observed_fake_worker(self.db, "LAUNCH")
        self.assertEqual(got.stage, RESULT)
        self.assertEqual(got.exit_code, 0)
        self.assertTrue(got.host_reaped_worker)
        self.assertFalse(got.independent_b33_witness)
        self.assertFalse(got.authenticated_unix_peer)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        self.assertEqual(self.atomic.ledger.budget("b38jScope")["used_units"], 0)

    def test_cancel_before_worker_command_refuses_fake_child(self):
        self.mark_claim()
        self.atomic.cancel_mock(self.sealed.attempt_id)
        got = observed_fake_worker(self.db, "LAUNCH")
        self.assertEqual(got.stage, REFUSED)
        self.assertEqual(got.exit_code, 3)
        self.assertEqual(self.state(), "CANCEL_PENDING")
        self.assertEqual(self.atomic.ledger.budget("b38jScope")["reserved_units"], 25)

    def test_revoke_before_worker_command_refuses_fake_child(self):
        self.mark_claim()
        self.atomic.revoke_if_changed(
            self.sealed.attempt_id,
            {**self.binding, "generation": self.binding["generation"] + 1},
        )
        got = observed_fake_worker(self.db, "LAUNCH")
        self.assertEqual(got.stage, REFUSED)
        self.assertEqual(self.state(), "REVOKED_REMOTE_UNKNOWN")

    def test_worker_cancel_ack_has_no_child_or_b33_witness(self):
        self.mark_claim()
        got = observed_fake_worker(self.db, "CANCEL")
        self.assertEqual(got.stage, CANCELLED)
        self.assertEqual(got.exit_code, 0)
        self.assertEqual(self.state(), "CANCEL_PENDING")
        self.assertFalse(got.real_stop_verified)
        self.assertFalse(self.atomic.snapshot(
            self.sealed.attempt_id)["durableMockObservation"])

    def test_worker_crash_keeps_claim_and_no_auto_replay(self):
        self.mark_claim()
        got = observed_fake_worker(self.db, "CRASH")
        self.assertEqual(got.stage, READY)
        self.assertEqual(got.exit_code, 77)
        self.assertTrue(self.claims.claim_recorded(self.sealed.attempt_id))
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        self.conn.close()
        with fixture_connection(self.db) as newconn:
            atomic2 = AtomicOfflineFixture(newconn, TestOnlyEvidenceIssuer())
            claims2 = AtomicFakeLaunchClaim(atomic2)
            self.assertTrue(claims2.claim_recorded(self.sealed.attempt_id))
            recovered = atomic2.recover_mock(
                self.sealed, current_binding=self.binding,
            )
            self.assertEqual(recovered["state"], "REMOTE_OUTCOME_UNKNOWN")
            self.assertIs(recovered["retryAuthorized"], False)
            with self.assertRaises(ClaimRefused):
                claims2.claim_mock(self.sealed, current_binding=self.binding)

    def test_invalid_worker_command_refused_without_fake_child(self):
        self.mark_claim()
        got = observed_fake_worker(self.db, "INVALID")
        self.assertEqual(got.stage, REFUSED)
        self.assertEqual(got.exit_code, 3)
        self.assertTrue(self.claims.claim_recorded(self.sealed.attempt_id))

    def test_worker_output_does_not_settle_fake_b33(self):
        self.mark_claim()
        got = observed_fake_worker(self.db, "LAUNCH")
        self.assertEqual(got.stage, RESULT)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        self.assertFalse(self.atomic.snapshot(
            self.sealed.attempt_id)["durableMockObservation"])
        self.assertEqual(self.atomic.ledger.budget("b38jScope")["reserved_units"], 25)
        self.assertFalse(got.production_ready)

def smoke():
    """One real separate launch worker, one actual B38-G fake sandbox exchange."""
    with tempfile.TemporaryDirectory(prefix="b38j-outside-worker-") as td:
        db = Path(td) / "disposable.sqlite3"
        with fixture_connection(db) as conn:
            atomic = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
            atomic.configure_mock_budget("b38jScope", 100)
            claims = AtomicFakeLaunchClaim(atomic)
            sealed, binding = G.fixture()
            atomic.register_mock(
                sealed, scope="b38jScope", units=25,
                current_binding=binding,
            )
            atomic.begin_mock(
                sealed, current_binding=binding,
                offered_bytes=sealed.payload,
            )
            claims.claim_mock(sealed, current_binding=binding)
            receipt = observed_fake_worker(db, "LAUNCH")
            if (receipt.stage != RESULT or receipt.exit_code != 0 or
                not receipt.host_reaped_worker or
                receipt.independent_b33_witness or
                atomic.ledger.state(sealed.attempt_id)["state"] !=
                    "SUBMISSION_UNCONFIRMED"):
                deny("WORKER_OR_B37C_STATE_INVALID")
        with fixture_connection(db) as conn:
            atomic = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
            claims = AtomicFakeLaunchClaim(atomic)
            if not claims.claim_recorded(sealed.attempt_id):
                deny("FAKE_LAUNCH_CLAIM_NOT_DURABLE")
            recovery = atomic.recover_mock(
                sealed, current_binding=binding,
            )
            if (recovery["state"] != "REMOTE_OUTCOME_UNKNOWN" or
                recovery["retryAuthorized"] is not False):
                deny("RESTART_NOT_QUARANTINED")
    return {
        "state": "B38J_SEPARATE_FAKE_LAUNCH_WORKER_PASS",
        "separateWorkerProcess": True,
        "hostObservedExit": True,
        "sandboxedFakeB38E": True,
        "durableB38IClaim": True,
        "cancelBeforeWorkerLaunchDenied": True,
        "restartQuarantined": True,
        "untrustedWorkerReplyNotB33Witness": True,
        "authenticatedPeer": False,
        "physicalLaunchAtomic": False,
        "automaticRetry": False,
        "realProviderCalls": 0,
        "productionReady": False,
    }

def main():
    a = argparse.ArgumentParser()
    modes = a.add_mutually_exclusive_group(required=True)
    modes.add_argument("--unit", action="store_true")
    modes.add_argument("--smoke", action="store_true")
    modes.add_argument("--worker", action="store_true")
    a.add_argument("--db", type=Path)
    a.add_argument("--nonce")
    args = a.parse_args()
    if args.worker:
        if args.db is None or args.nonce is None:
            return 4
        try:
            return fake_worker(args.db, args.nonce)
        except (Refused, G.Refused, ClaimRefused, sqlite3.Error):
            # Never emit arbitrary exception text through a fake worker.
            return 5
    if args.unit:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FakeLaunchWorkerTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    try:
        print(json.dumps(smoke(), sort_keys=True))
        return 0
    except (Refused, G.Refused, ClaimRefused) as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
