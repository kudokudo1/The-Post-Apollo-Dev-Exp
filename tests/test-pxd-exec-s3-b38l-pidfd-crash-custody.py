#!/usr/bin/env python3
"""B38-L: disposable pidfd-owned fake descendants survive a supervisor crash.

Tests Linux pidfd_OPEN / pidfd_send_signal / readiness observation, not a
real sender, authenticated process tree, persistent pidfd, provider or Hospital.
No local machine install; execute only in disposable CI checkout.
"""
import argparse
import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TIMEOUT = 7.0
SCHEMA = "B38L_PIDFD_FAKE_V1"
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
       "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "B38L_FAKE_RUNNER": "1"}
PYTHON = "/usr/bin/python3"

class Refused(RuntimeError):
    pass

def deny(reason):
    raise Refused("B38L_REFUSED_" + reason)

def require_pidfd():
    if (sys.platform != "linux" or not hasattr(os, "pidfd_open") or
            not hasattr(signal, "pidfd_send_signal")):
        deny("KERNEL_PIDFD_UNAVAILABLE")
    if not Path(PYTHON).is_file():
        deny("SYSTEM_PYTHON_UNAVAILABLE")

def owned_pidfd(pid):
    if type(pid) is not int or pid <= 1:
        deny("PID_INVALID")
    try:
        fd = os.pidfd_open(pid, 0)
    except OSError:
        deny("PIDFD_OPEN_FAILED")
    return fd

def exited(fd, timeout):
    """Kernel pidfd readability indicates task exit, not a provider receipt."""
    poller = select.poll()
    poller.register(fd, select.POLLIN)
    return bool(poller.poll(int(timeout * 1000)))

def send(fd, signum):
    try:
        signal.pidfd_send_signal(fd, signum, None, 0)
    except (OSError, ValueError):
        deny("PIDFD_SIGNAL_FAILED")

def leaf(marker, nonce):
    if marker.is_symlink() or not marker.parent.is_dir() or len(nonce) != 32:
        return 6
    for n in range(240):
        marker.write_text(nonce + ":" + str(n))
        time.sleep(.05)
    return 0

def parent(marker, nonce):
    proc = subprocess.Popen([PYTHON, "-B", str(Path(__file__).resolve()),
          "--leaf", "--marker", str(marker), "--nonce", nonce],
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL, close_fds=True,
          start_new_session=True, env=ENV)
    sys.stdout.write(str(proc.pid) + "\n")
    sys.stdout.flush()
    while True:
        time.sleep(1)

def supervisor(marker, nonce):
    child = subprocess.Popen([PYTHON, "-B", str(Path(__file__).resolve()),
          "--parent", "--marker", str(marker), "--nonce", nonce],
          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
          stderr=subprocess.DEVNULL, close_fds=True,
          start_new_session=True, env=ENV, text=True)
    try:
        ready, _, _ = select.select([child.stdout], [], [], TIMEOUT)
        if not ready:
            return 7
        line = child.stdout.readline(64)
        try:
            leaf_pid = int(line.strip())
        except ValueError:
            return 8
        if leaf_pid <= 1:
            return 8
        sys.stdout.write(json.dumps({
            "schema": SCHEMA, "supervisorPid": os.getpid(),
            "parentPid": child.pid, "leafPid": leaf_pid,
            "nonce": nonce
        }, sort_keys=True) + "\n")
        sys.stdout.flush()
        line = sys.stdin.buffer.readline(32)
        if line != b"CRASH\n":
            return 9
        # Deliberate hard exit: neither fake descendant is reaped here.
        os._exit(77)
    finally:
        if child.stdout is not None:
            child.stdout.close()

def connection(path):
    c = sqlite3.connect(path, isolation_level=None, timeout=3)
    c.execute("""CREATE TABLE IF NOT EXISTS fake_stop(
        nonce TEXT PRIMARY KEY, state TEXT NOT NULL CHECK(
            state IN ('RUNNING','STOP_REQUESTED','STOP_OBSERVED')),
        parent_pid INTEGER NOT NULL, leaf_pid INTEGER NOT NULL
    )""")
    return c

def transition(c, nonce, before, after):
    c.execute("BEGIN IMMEDIATE")
    try:
        n = c.execute("UPDATE fake_stop SET state=? WHERE nonce=? AND state=?",
                      (after, nonce, before)).rowcount
        if n != 1:
            deny("DURABLE_STOP_STATE_CONFLICT")
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise

def fake_crash_stop():
    """Observe OS stop of two specifically captured fake pidfds.

    Hold both pidfds open across supervisor death. PID integer is never used
    for termination after initial pidfd capture. Not proof of unknown forks.
    """
    require_pidfd()
    with tempfile.TemporaryDirectory(prefix="b38l-pidfd-test-") as td:
        root = Path(td).resolve(strict=True)
        nonce = os.urandom(16).hex()
        marker = root / "heartbeat"
        db = root / "stop.sqlite3"
        supervisor_proc = None
        fds = []
        parent_pid = leaf_pid = None
        observed = False
        try:
            supervisor_proc = subprocess.Popen([
                PYTHON, "-B", str(Path(__file__).resolve()),
                "--supervisor", "--marker", str(marker), "--nonce", nonce],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, close_fds=True,
                start_new_session=True, env=ENV)
            fd_supervisor = owned_pidfd(supervisor_proc.pid)
            fds.append(fd_supervisor)
            ready, _, _ = select.select([supervisor_proc.stdout], [], [], TIMEOUT)
            if not ready:
                deny("SUPERVISOR_READY_TIMEOUT")
            ready_line = supervisor_proc.stdout.readline(512)
            if len(ready_line) > 511:
                deny("UNBOUNDED_READY")
            try:
                frame = json.loads(ready_line)
            except (UnicodeError, ValueError):
                deny("READY_FRAME_INVALID")
            if (type(frame) is not dict or frame.get("schema") != SCHEMA or
                frame.get("nonce") != nonce or
                frame.get("supervisorPid") != supervisor_proc.pid or
                type(frame.get("parentPid")) is not int or
                type(frame.get("leafPid")) is not int or
                frame["parentPid"] == frame["leafPid"]):
                deny("READY_IDENTITY_INVALID")
            parent_pid, leaf_pid = frame["parentPid"], frame["leafPid"]
            parent_fd, leaf_fd = owned_pidfd(parent_pid), owned_pidfd(leaf_pid)
            fds.extend([parent_fd, leaf_fd])
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and not marker.is_file():
                time.sleep(.025)
            if not marker.is_file() or marker.is_symlink():
                deny("CHILD_HEARTBEAT_MISSING")
            before = marker.read_text()
            if not before.startswith(nonce + ":"):
                deny("MARKER_NONCE_INVALID")
            if exited(parent_fd, 0) or exited(leaf_fd, 0):
                deny("DESCENDANT_PREMATURE_EXIT")
            with connection(db) as c:
                c.execute("INSERT INTO fake_stop VALUES (?,?,?,?)",
                          (nonce, "RUNNING", parent_pid, leaf_pid))
                # Stop intent is durable BEFORE causing supervisor crash.
                transition(c, nonce, "RUNNING", "STOP_REQUESTED")
            supervisor_proc.stdin.write(b"CRASH\n")
            supervisor_proc.stdin.close()
            if supervisor_proc.wait(timeout=TIMEOUT) != 77 or not exited(fd_supervisor, 0):
                deny("SUPERVISOR_CRASH_NOT_OBSERVED")
            if exited(parent_fd, 0) or exited(leaf_fd, 0):
                deny("FAKE_DESCENDANT_NOT_SURVIVING_CRASH")
            # Independently owned by controller, no kill(pid) after pidfd capture.
            send(leaf_fd, signal.SIGTERM)
            send(parent_fd, signal.SIGTERM)
            if not exited(leaf_fd, TIMEOUT) or not exited(parent_fd, TIMEOUT):
                deny("DESCENDANT_PIDFD_EXIT_NOT_OBSERVED")
            last = marker.read_text()
            time.sleep(.30)
            if marker.read_text() != last:
                deny("HEARTBEAT_NOT_QUIESCENT")
            with connection(db) as c:
                if c.execute("SELECT state FROM fake_stop WHERE nonce=?",
                             (nonce,)).fetchone()[0] != "STOP_REQUESTED":
                    deny("DURABLE_INTENT_MISSING")
                transition(c, nonce, "STOP_REQUESTED", "STOP_OBSERVED")
            with connection(db) as c:
                if c.execute("SELECT state FROM fake_stop WHERE nonce=?",
                             (nonce,)).fetchone()[0] != "STOP_OBSERVED":
                    deny("DURABLE_STOP_NOT_REOPENED")
                with unittest.TestCase().assertRaises(Refused):
                    transition(c, nonce, "STOP_REQUESTED", "STOP_OBSERVED")
            observed = True
            return {
                "schema": SCHEMA, "state": "B38L_FAKE_PIDFD_CRASH_STOP_PASS",
                "supervisorCrashObserved": True,
                "parentPidfdExitObserved": True, "leafPidfdExitObserved": True,
                "stopIntentDurable": True, "stopObservationDurable": True,
                "childHeartbeatQuiescent": True,
                "pidfdRetainedOnlyWhileControllerAlive": True,
                "cgroupTreeCertified": False, "allDescendantsCertified": False,
                "authenticatedB33": False, "productionReady": False,
                "realProviderCalls": 0,
            }
        finally:
            # Only pidfds captured in this controlled fixture are signaled.
            # No unsafe kill() against stale numeric PIDs.
            for fd in reversed(fds):
                try:
                    if not exited(fd, 0):
                        try:
                            signal.pidfd_send_signal(fd, signal.SIGKILL, None, 0)
                        except OSError:
                            pass
                except OSError:
                    pass
            for fd in fds:
                os.close(fd)
            if supervisor_proc is not None:
                if supervisor_proc.poll() is None:
                    supervisor_proc.kill()
                try:
                    supervisor_proc.wait(timeout=TIMEOUT)
                except subprocess.TimeoutExpired:
                    deny("SUPERVISOR_REAP_UNCONFIRMED")

class Tests(unittest.TestCase):
    def test_actual_kernel_pidfd_crash_stop(self):
        receipt = fake_crash_stop()
        self.assertEqual(receipt["state"], "B38L_FAKE_PIDFD_CRASH_STOP_PASS")
        self.assertTrue(receipt["parentPidfdExitObserved"])
        self.assertTrue(receipt["leafPidfdExitObserved"])
        self.assertFalse(receipt["cgroupTreeCertified"])
        self.assertFalse(receipt["authenticatedB33"])

    def test_missing_pidfd_fails_closed(self):
        with mock.patch.object(os, "pidfd_open", side_effect=OSError("blocked")):
            with self.assertRaisesRegex(Refused, "PIDFD_OPEN_FAILED"):
                owned_pidfd(123456)

    def test_bad_pid_rejected(self):
        for pid in (-1, 0, 1, "12", None, True):
            with self.subTest(pid=pid):
                with self.assertRaisesRegex(Refused, "PID_INVALID"):
                    owned_pidfd(pid)

    def test_durable_stop_intent_is_monotonic(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stop.sqlite"
            with connection(path) as c:
                c.execute("INSERT INTO fake_stop VALUES (?,?,?,?)",
                          ("fake", "RUNNING", 12, 13))
                transition(c, "fake", "RUNNING", "STOP_REQUESTED")
            with connection(path) as c:
                self.assertEqual(c.execute("SELECT state FROM fake_stop").fetchone()[0],
                                 "STOP_REQUESTED")
                with self.assertRaisesRegex(Refused, "DURABLE_STOP_STATE_CONFLICT"):
                    transition(c, "fake", "RUNNING", "STOP_REQUESTED")
                transition(c, "fake", "STOP_REQUESTED", "STOP_OBSERVED")
                with self.assertRaises(Refused):
                    transition(c, "fake", "STOP_REQUESTED", "STOP_OBSERVED")

    def test_not_a_live_hospital_or_provider_api(self):
        self.assertEqual(set(ENV), {"PATH", "LANG", "PYTHONDONTWRITEBYTECODE",
                                   "PYTHONNOUSERSITE", "B38L_FAKE_RUNNER"})
        self.assertFalse(hasattr(sys.modules[__name__], "send_provider"))

def main():
    p = argparse.ArgumentParser()
    a = p.add_mutually_exclusive_group(required=True)
    a.add_argument("--unit", action="store_true")
    a.add_argument("--smoke", action="store_true")
    a.add_argument("--supervisor", action="store_true")
    a.add_argument("--parent", action="store_true")
    a.add_argument("--leaf", action="store_true")
    p.add_argument("--marker", type=Path)
    p.add_argument("--nonce")
    opts = p.parse_args()
    if opts.supervisor or opts.parent or opts.leaf:
        if (os.environ.get("B38L_FAKE_RUNNER") != "1" or
            opts.marker is None or opts.nonce is None):
            return 12
        if opts.supervisor:
            return supervisor(opts.marker, opts.nonce)
        if opts.parent:
            return parent(opts.marker, opts.nonce)
        return leaf(opts.marker, opts.nonce)
    if opts.unit:
        return 0 if unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
        ).wasSuccessful() else 1
    try:
        print(json.dumps(fake_crash_stop(), sort_keys=True))
        return 0
    except Refused as e:
        print(str(e), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
