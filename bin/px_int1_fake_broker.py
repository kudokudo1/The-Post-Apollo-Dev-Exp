#!/usr/bin/env python3
"""INT1-B9: trusted-OS-observed, idle fake broker readiness probe.

This is NOT a model client, tool dispatcher, or accepted Doctor turn.
Run exclusively inside the accepted disposable INT1 Bubblewrap fixture.
Only an idle child is started; it inherits the existing OS mount/net isolation,
receives no Hospital DB/fixture environment or credential FD, and is always reaped.
"""
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

# -I discards script-directory imports; only reinsert the audited ro-mounted
# source directory, never cwd, PYTHONPATH, or a writable fixture path.
sys.path.insert(0, "/source/bin")

from px_int1_fake_guard import FAKE_ID, PROFILE

CHILD_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "PYTHONDONTWRITEBYTECODE": "1",
}
CHILD_EXEC = "/usr/bin/python3"
CHILD_SOURCE = "/source/bin/px_int1_fake_broker.py"
NAMESPACE_KINDS = ("mnt", "net", "pid", "ipc", "user")


def _idle_child(scenario, nonce):
    # No Hospital/database/provider APIs in this path and no tool dispatch.
    if scenario == "early-exit":
        return 17
    payload = {"phase": "READY", "nonce": nonce, "profile": PROFILE}
    if scenario == "malformed":
        payload["profile"] = "UNAPPROVED"
    if scenario != "timeout":
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        sys.stdout.flush()
    time.sleep(8)  # Parent always terminates/reaps before this expires.
    return 0


def _observe_child(pid):
    """Kernel-owned evidence: never treat the child's JSON as OS attestation."""
    if os.getsid(pid) != pid or os.getpgid(pid) != pid:
        raise RuntimeError("INT1-B9 REFUSED // child lacks isolated process group")
    for kind in NAMESPACE_KINDS:
        child = os.stat("/proc/%s/ns/%s" % (pid, kind))
        parent = os.stat("/proc/self/ns/%s" % kind)
        if (child.st_dev, child.st_ino) != (parent.st_dev, parent.st_ino):
            raise RuntimeError("INT1-B9 REFUSED // child namespace mismatch: " + kind)
    env_bytes = Path("/proc/%s/environ" % pid).read_bytes()
    parts = [x for x in env_bytes.split(b"\0") if x]
    try:
        env = dict(x.decode("utf-8").split("=", 1) for x in parts)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("INT1-B9 REFUSED // invalid child environment") from exc
    if env != CHILD_ENV or len(parts) != len(CHILD_ENV):
        raise RuntimeError("INT1-B9 REFUSED // inherited or unexpected child environment")
    fd_root = Path("/proc/%s/fd" % pid)
    fds = {int(p.name) for p in fd_root.iterdir()}
    if fds != {0, 1, 2}:
        raise RuntimeError("INT1-B9 REFUSED // unexpected child file descriptor")
    if os.readlink(fd_root / "0") != "/dev/null":
        raise RuntimeError("INT1-B9 REFUSED // broker stdin not sealed")
    if not os.readlink(fd_root / "1").startswith("pipe:["):
        raise RuntimeError("INT1-B9 REFUSED // broker stdout not isolated")
    if os.readlink(fd_root / "2") != "/dev/null":
        raise RuntimeError("INT1-B9 REFUSED // broker stderr not sealed")
    if not Path("/proc/%s/root/fixture/providers/fake.json" % pid).is_file():
        raise RuntimeError("INT1-B9 REFUSED // child fixture root not visible")
    return {
        "namespaces": list(NAMESPACE_KINDS),
        "childFds": [0, 1, 2],
        "childEnvironmentKeys": sorted(CHILD_ENV),
        "childSessionIsolated": True,
    }


def _receive_ready(child, nonce, timeout):
    selector = selectors.DefaultSelector()
    try:
        os.set_blocking(child.stdout.fileno(), False)
        selector.register(child.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        data = bytearray()
        while time.monotonic() < deadline:
            if child.poll() is not None and not data:
                raise RuntimeError("INT1-B9 REFUSED // broker exited before readiness")
            events = selector.select(min(0.05, max(0, deadline - time.monotonic())))
            if not events:
                continue
            chunk = os.read(child.stdout.fileno(), 257 - len(data))
            if not chunk:
                raise RuntimeError("INT1-B9 REFUSED // broker readiness EOF")
            data.extend(chunk)
            if len(data) > 256:
                raise RuntimeError("INT1-B9 REFUSED // oversized broker readiness")
            if b"\n" in data:
                break
        else:
            raise RuntimeError("INT1-B9 REFUSED // readiness deadline exceeded")
        if not data.endswith(b"\n") or data.count(b"\n") != 1:
            raise RuntimeError("INT1-B9 REFUSED // malformed broker readiness")
        try:
            response = json.loads(bytes(data).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("INT1-B9 REFUSED // malformed broker readiness") from exc
        if response != {"phase": "READY", "nonce": nonce, "profile": PROFILE}:
            raise RuntimeError("INT1-B9 REFUSED // broker readiness mismatch")
        # The challenge response checks the fixed child protocol only.
        # OS confinement proof comes independently from _observe_child.
        if child.poll() is not None:
            raise RuntimeError("INT1-B9 REFUSED // broker exited after readiness")
    finally:
        selector.close()


def _terminate_and_reap(child):
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        child.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=2)
    finally:
        if child.stdout is not None:
            child.stdout.close()
    if child.poll() is None:
        raise RuntimeError("INT1-B9 REFUSED // broker was not reaped")


def _eligible_snapshot(room_id, session_id):
    # The same read-only predicates as B7; no accepted messages or events.
    from px_int1_fake_atomic import connect, context_digest
    with connect() as conn:
        return context_digest(conn, room_id, session_id)


def probe(room_id, session_id, *, scenario="ready", timeout=1.5,
          test_revoke_at_readiness=False):
    from px_int1_fake_atomic import require_id
    require_id(room_id, "Room ID")
    require_id(session_id, "session ID")
    if scenario not in ("ready", "early-exit", "malformed", "timeout"):
        raise RuntimeError("INT1-B9 REFUSED // unknown test scenario")
    if not (0.1 <= timeout <= 4):
        raise RuntimeError("INT1-B9 REFUSED // invalid readiness timeout")
    before = _eligible_snapshot(room_id, session_id)
    nonce = os.urandom(16).hex()
    child = subprocess.Popen(
        (CHILD_EXEC, "-I", "-B", CHILD_SOURCE, "child",
         "--scenario", scenario, "--nonce", nonce),
        cwd="/fixture", env=CHILD_ENV,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
    )
    try:
        os_evidence = _observe_child(child.pid)
        _receive_ready(child, nonce, timeout)
        os_evidence = _observe_child(child.pid)
        if test_revoke_at_readiness:
            # Synthetic-only security regression: an authority change after
            # readiness must fail the subsequent eligibility recheck.
            from px_int1_fake_atomic import connect, revoke
            with connect() as conn:
                revoke(conn, room_id, "B9 synthetic post-readiness revocation")
        after = _eligible_snapshot(room_id, session_id)
        if (after["generation"] != before["generation"] or
                after["contextHash"] != before["contextHash"]):
            raise RuntimeError("INT1-B9 REFUSED // eligibility changed during startup")
        return {
            "state": "IDLE_BROKER_PROBED_AND_REAPED",
            "profile": PROFILE, "providerId": FAKE_ID,
            "roomId": room_id, "sessionId": session_id,
            "brokerStarted": True, "brokerReaped": True,
            "readinessObservedByOS": True, "osEvidence": os_evidence,
            "messagesAccepted": 0, "eventsAccepted": 0,
            "modelCalls": 0, "toolCalls": 0, "dispatches": 0,
            "productionReady": False,
        }
    finally:
        _terminate_and_reap(child)


def main():
    parser = argparse.ArgumentParser(description="Disposable idle broker readiness proof")
    sub = parser.add_subparsers(dest="command", required=True)
    parent = sub.add_parser("probe")
    parent.add_argument("--room-id", required=True)
    parent.add_argument("--session-id", required=True)
    parent.add_argument("--scenario", default="ready",
                        choices=("ready", "early-exit", "malformed", "timeout"))
    parent.add_argument("--timeout", type=float, default=1.5)
    parent.add_argument("--test-revoke-at-readiness", action="store_true")
    child = sub.add_parser("child")
    child.add_argument("--scenario", required=True)
    child.add_argument("--nonce", required=True)
    args = parser.parse_args()
    if args.command == "child":
        return _idle_child(args.scenario, args.nonce)
    try:
        result = probe(
            args.room_id, args.session_id, scenario=args.scenario,
            timeout=args.timeout,
            test_revoke_at_readiness=args.test_revoke_at_readiness,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print("px fake broker: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
