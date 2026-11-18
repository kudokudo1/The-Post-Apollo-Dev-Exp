#!/usr/bin/env python3
"""B38-L: host-kernel pidfds for the observed disposable S1 child and wrapper.

This is a fake-only Linux experiment, not a production stop certificate.
It pins one *observed* sandbox Python child by host PID, start time, and
pidfd; it does NOT prove a complete, race-free cgroup process-tree census.
"""
import argparse
from dataclasses import dataclass
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture
from px_s3_b38i_fake_launch_claim import AtomicFakeLaunchClaim

def load_k():
    name = "b38l_existing_k"
    if name in sys.modules:
        return sys.modules[name]
    path = ROOT / "tests" / "test-pxd-exec-s3-b38k-running-fake-child-stop.py"
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module

K = load_k()
G = K.G
DISCOVERY_TIMEOUT = 4
PIDFD_STOP_TIMEOUT_MS = 3000
MAX_CENSUS_NODES = 48

class Refused(RuntimeError):
    pass

def deny(code):
    raise Refused("B38L_REFUSED_" + code)

def require_pidfd():
    if sys.platform != "linux" or not callable(getattr(os, "pidfd_open", None)):
        deny("KERNEL_PIDFD_UNAVAILABLE")
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            if "NSpid:" not in f.read(16384):
                deny("PROC_NSPID_UNAVAILABLE")
    except OSError:
        deny("PROC_STATUS_UNAVAILABLE")

def nspids(text):
    for line in text.splitlines():
        if line.startswith("NSpid:"):
            fields = line.split()[1:]
            if not fields or len(fields) > 8 or any(not x.isdecimal() for x in fields):
                deny("INVALID_KERNEL_NSPID")
            return tuple(int(x) for x in fields)
    deny("MISSING_KERNEL_NSPID")

def proc_starttime(pid):
    """Linux /proc/PID/stat field 22; close the last ')' to handle comm spaces."""
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
        tail = raw[raw.rfind(")") + 2:].split()
        if len(tail) < 20:
            deny("KERNEL_STARTTIME_UNAVAILABLE")
        start = int(tail[19])
        if start <= 0:
            deny("KERNEL_STARTTIME_UNAVAILABLE")
        return start
    except (OSError, ValueError, IndexError):
        deny("KERNEL_STARTTIME_UNAVAILABLE")

def children_of(pid):
    """Best-effort census only, NOT an atomic process-tree snapshot."""
    try:
        raw = (Path("/proc") / str(pid) / "task" / str(pid) / "children").read_text()
        fields = raw.split()
        if len(fields) > MAX_CENSUS_NODES or any(not x.isdecimal() for x in fields):
            deny("KERNEL_CHILD_LIST_INVALID")
        return [int(x) for x in fields]
    except OSError:
        deny("KERNEL_CHILD_LIST_UNAVAILABLE")

def observe_fake_child_pid(wrapper_pid, nonce):
    """Discover only the fixed K test Python child under our owned wrapper."""
    pending = [wrapper_pid]
    seen = set()
    while pending:
        pid = pending.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        if len(seen) > MAX_CENSUS_NODES:
            deny("CHILD_TREE_UNBOUNDED")
        # /proc children is not a frozen census. Fail closed when unavailable.
        pending.extend(children_of(pid))
        if pid == wrapper_pid:
            continue
        try:
            base = Path("/proc") / str(pid)
            cmd = (base / "cmdline").read_bytes()[:16384]
            ns = os.readlink(base / "ns" / "pid")
            ids = nspids((base / "status").read_text(encoding="ascii"))
        except OSError:
            continue  # transient exit during a best-effort census
        if (nonce.encode("ascii") in cmd and
            b"python3" in cmd and b"-c\x00" in cmd and
            len(ids) >= 2 and ids[-1] == 2 and
            ns != os.readlink("/proc/self/ns/pid")):
            return pid, ns
    return None

def pidfd_exited(fd, ms=0):
    poller = select.poll()
    poller.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    return bool(poller.poll(ms))

@dataclass
class PinnedFakeProcess:
    wrapper_pid: int
    child_pid: int
    child_pid_ns: str
    wrapper_start: int
    child_start: int
    wrapper_fd: int
    child_fd: int

    def close(self):
        for name in ("wrapper_fd", "child_fd"):
            fd = getattr(self, name)
            if fd >= 0:
                os.close(fd)
                setattr(self, name, -1)

def pin_fake_processes(live):
    require_pidfd()
    if (type(live) is not K.LiveFakeChild or
        live.pid != live.proc.pid or live.proc.poll() is not None or
        not live.marker.is_file() or not live.nonce.isalnum()):
        deny("UNOWNED_OR_STOPPED_WRAPPER")
    wrapper_start = proc_starttime(live.pid)
    try:
        wrapper_fd = os.pidfd_open(live.pid, 0)
    except OSError:
        deny("WRAPPER_PIDFD_UNAVAILABLE")
    child_fd = -1
    try:
        if pidfd_exited(wrapper_fd):
            deny("WRAPPER_ALREADY_EXITED")
        deadline = time.monotonic() + DISCOVERY_TIMEOUT
        found = None
        while time.monotonic() < deadline:
            if live.proc.poll() is not None or pidfd_exited(wrapper_fd):
                deny("WRAPPER_EXIT_DURING_DISCOVERY")
            found = observe_fake_child_pid(live.pid, live.nonce)
            if found is not None:
                break
            time.sleep(.02)
        if found is None:
            deny("FAKE_CHILD_NOT_KERNEL_OBSERVED")
        child_pid, child_namespace = found
        child_start = proc_starttime(child_pid)
        try:
            child_fd = os.pidfd_open(child_pid, 0)
        except OSError:
            deny("CHILD_PIDFD_UNAVAILABLE")
        if (proc_starttime(live.pid) != wrapper_start or
            proc_starttime(child_pid) != child_start or
            pidfd_exited(wrapper_fd) or pidfd_exited(child_fd)):
            deny("PID_IDENTITY_CHANGED_OR_EXITED")
        return PinnedFakeProcess(
            live.pid, child_pid, child_namespace,
            wrapper_start, child_start, wrapper_fd, child_fd,
        )
    except BaseException:
        if child_fd >= 0:
            os.close(child_fd)
        os.close(wrapper_fd)
        raise

@dataclass(frozen=True)
class KernelStopEvidence:
    wrapper_pidfd_exit: bool
    observed_child_pidfd_exit: bool
    host_child_starttime_pinned: bool
    sandbox_pid_namespace_distinct: bool
    ledger_cancel_pending: bool
    fake_budget_held: bool
    automatic_retry: bool = False
    authenticated_b33_witness: bool = False
    complete_process_tree_custody: bool = False
    cgroup_kill_certified: bool = False
    real_stop_verified: bool = False
    provider_calls: int = 0
    production_ready: bool = False

def stop_pinned_fake(atomic, live, pinned):
    if (type(pinned) is not PinnedFakeProcess or
        type(live) is not K.LiveFakeChild or
        live.pid != pinned.wrapper_pid or
        pinned.wrapper_fd < 0 or pinned.child_fd < 0):
        deny("FOREIGN_OR_CLOSED_PIDFD")
    if pidfd_exited(pinned.wrapper_fd) or pidfd_exited(pinned.child_fd):
        deny("PIDFD_ALREADY_EXITED")
    # K's existing owner-scoped group SIGTERM and durable B29 cancel.
    # This operation is NOT atomic with spawn or proof of all descendants.
    recorded = K.cancel_running_fake(atomic, live)
    if not recorded.bwrap_reaped or not recorded.ledger_cancel_pending:
        deny("LEGACY_STOP_INCOMPLETE")
    if not pidfd_exited(pinned.wrapper_fd, PIDFD_STOP_TIMEOUT_MS):
        deny("KERNEL_WRAPPER_EXIT_MISSING")
    if not pidfd_exited(pinned.child_fd, PIDFD_STOP_TIMEOUT_MS):
        deny("KERNEL_CHILD_EXIT_MISSING")
    return KernelStopEvidence(
        wrapper_pidfd_exit=True,
        observed_child_pidfd_exit=True,
        host_child_starttime_pinned=True,
        sandbox_pid_namespace_distinct=True,
        ledger_cancel_pending=True,
        fake_budget_held=recorded.fake_budget_held,
    )

def disposable_smoke():
    require_pidfd()
    with tempfile.TemporaryDirectory(prefix="b38l-pidfd-fake-") as temp:
        root = Path(temp).resolve(strict=True)
        db = root / "synthetic.sqlite3"
        with sqlite3.connect(db, isolation_level=None, timeout=5) as conn:
            atomic = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
            atomic.configure_mock_budget("b38kScope", 100)
            claimant = AtomicFakeLaunchClaim(atomic)
            sealed, binding = G.fixture()
            atomic.register_mock(sealed, scope="b38kScope", units=25,
                                 current_binding=binding)
            atomic.begin_mock(sealed, current_binding=binding,
                              offered_bytes=sealed.payload)
            claimant.claim_mock(sealed, current_binding=binding)
            container_root = root / "sandbox"
            container_root.mkdir(mode=0o700)
            sandbox, _ = G.prepare_disposable_root(str(container_root))
            live = K.launch_running_fake(
                atomic, claimant, sealed, current_binding=binding,
                s1=G.load_s1(), root=sandbox,
            )
            try:
                pinned = pin_fake_processes(live)
                try:
                    evidence = stop_pinned_fake(atomic, live, pinned)
                    if (not evidence.observed_child_pidfd_exit or
                        not evidence.wrapper_pidfd_exit or
                        evidence.complete_process_tree_custody or
                        evidence.real_stop_verified or
                        atomic.ledger.state(sealed.attempt_id)["state"] !=
                            "CANCEL_PENDING"):
                        deny("KERNEL_EVIDENCE_INVALID")
                finally:
                    pinned.close()
            finally:
                K.terminate_owned(live.proc)
        with sqlite3.connect(db, isolation_level=None, timeout=5) as conn:
            fresh = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
            claims = AtomicFakeLaunchClaim(fresh)
            if (not claims.claim_recorded(sealed.attempt_id) or
                fresh.recover_mock(sealed, current_binding=binding)["state"] !=
                    "CANCEL_PENDING" or
                fresh.ledger.budget("b38kScope")["reserved_units"] != 25):
                deny("DURABLE_CANCEL_RESTART_MISSING")
    return {
        "state": "B38L_HOST_WRAPPER_AND_OBSERVED_CHILD_PIDFD_PASS",
        "kernelWrapperPidfdExit": True,
        "kernelObservedChildPidfdExit": True,
        "sandboxPidNamespaceDistinct": True,
        "durableCancelPending": True,
        "fakeBudgetHeld": True,
        "completeTreeCertified": False,
        "cgroupKillCertified": False,
        "authenticatedB33Witness": False,
        "realStopVerified": False,
        "automaticRetry": False,
        "providerCalls": 0,
        "productionReady": False,
    }

class Tests(unittest.TestCase):
    def test_nspid_parser_refuses_missing_and_malformed(self):
        self.assertEqual(nspids("Name:\tpython\nNSpid:\t99\t2\n"), (99, 2))
        for value in ("Name:\tpython\n", "NSpid:\n", "NSpid:\tbad\t2\n"):
            with self.assertRaises(Refused):
                nspids(value)

    def test_invalid_handle_refuses_without_proc_scan(self):
        with mock.patch.object(os, "pidfd_open", create=True) as opened:
            with self.assertRaisesRegex(Refused, "UNOWNED_OR_STOPPED_WRAPPER"):
                pin_fake_processes(object())
            opened.assert_not_called()

    def test_pidfd_missing_fails_closed(self):
        with mock.patch.object(os, "pidfd_open", None, create=True):
            with self.assertRaisesRegex(Refused, "KERNEL_PIDFD_UNAVAILABLE"):
                require_pidfd()

    def test_owned_kernel_pidfd_observes_real_subprocess_exit(self):
        require_pidfd()
        proc = subprocess.Popen(
            [sys.executable, "-B", "-c", "import time;time.sleep(15)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
        )
        try:
            fd = os.pidfd_open(proc.pid, 0)
            try:
                self.assertFalse(pidfd_exited(fd))
                proc.terminate()
                proc.wait(timeout=3)
                self.assertTrue(pidfd_exited(fd, 2000))
            finally:
                os.close(fd)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=3)

    def test_stale_pidfd_handle_refuses_replay(self):
        fake = PinnedFakeProcess(1, 2, "pid:[1]", 1, 2, -1, -1)
        with self.assertRaisesRegex(Refused, "FOREIGN_OR_CLOSED_PIDFD"):
            stop_pinned_fake(None, object(), fake)

    def test_no_production_or_complete_tree_claim(self):
        receipt = KernelStopEvidence(True, True, True, True, True, True)
        self.assertFalse(receipt.complete_process_tree_custody)
        self.assertFalse(receipt.cgroup_kill_certified)
        self.assertFalse(receipt.real_stop_verified)
        self.assertFalse(receipt.authenticated_b33_witness)
        self.assertFalse(receipt.production_ready)
        self.assertEqual(receipt.provider_calls, 0)

def main():
    arg = argparse.ArgumentParser()
    group = arg.add_mutually_exclusive_group(required=True)
    group.add_argument("--unit", action="store_true")
    group.add_argument("--smoke", action="store_true")
    mode = arg.parse_args()
    if mode.unit:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    try:
        print(json.dumps(disposable_smoke(), sort_keys=True))
        return 0
    except (Refused, K.Refused) as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
