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
        # The child can have transient loader/import FDs between Popen and
        # readiness. Inspect the complete FD contract only AFTER its fixed
        # protocol reaches an idle state; still before any success result.
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



# B10 // Additional nested mount namespace. B9 is deliberately retained as a
# separate lifecycle-only regression. B10 does NOT expose the source Hospital
# DB, its provider registry, or writable /fixture to the isolated idle child.
# The trusted supervisor (this parent) remains in the disposable P1 fixture.
INNER_BWRAP = "/usr/bin/bwrap"
INNER_ENV = {**CHILD_ENV, "PWD": "/tmp"}
INNER_ISOLATION_NAMESPACES = ("mnt", "net", "ipc", "uts", "user", "pid")


def _trusted_nested_bwrap():
    import stat
    # P1 checks the root-owned /usr/bin/bwrap on the real CI runner before
    # the outer fixture starts. User-namespace UID remapping can show those
    # host-root files as overflow UID 65534 inside the outer sandbox; checking
    # st_uid == 0 here would incorrectly fail the already-vetted fixture.
    # Instead require the immutable /usr ro-bind and fixed nonwritable path.
    mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    usr_ro = False
    for entry in mounts:
        fields = entry.split(" - ", 1)[0].split()
        if len(fields) > 5 and fields[4] == "/usr" and "ro" in fields[5].split(","):
            usr_ro = True
    if not usr_ro:
        raise RuntimeError("INT1-B10 REFUSED // trusted readonly /usr mount absent")
    for name in ("/", "/usr", "/usr/bin"):
        info = os.lstat(name)
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise RuntimeError("INT1-B10 REFUSED // untrusted Bubblewrap directory")
    info = os.lstat(INNER_BWRAP)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
        raise RuntimeError("INT1-B10 REFUSED // fixed Bubblewrap source unsafe")
    if not os.access(INNER_BWRAP, os.X_OK):
        raise RuntimeError("INT1-B10 REFUSED // Bubblewrap not executable")


def _nested_launch(scenario, nonce):
    _trusted_nested_bwrap()
    information_r, information_w = os.pipe()
    args = [
        INNER_BWRAP,
        "--unshare-user", "--unshare-net", "--unshare-ipc", "--unshare-uts",
        "--unshare-pid", "--info-fd", str(information_w),
        "--die-with-parent", "--new-session", "--cap-drop", "ALL",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--proc", "/proc", "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--dir", "/source", "--dir", "/source/bin",
        "--ro-bind", CHILD_SOURCE, CHILD_SOURCE,
        "--ro-bind", "/source/bin/px_int1_fake_guard.py",
                     "/source/bin/px_int1_fake_guard.py",
        "--clearenv",
    ]
    for key, value in INNER_ENV.items():
        args += ["--setenv", key, value]
    args += [
        "--chdir", "/tmp",
        CHILD_EXEC, "-I", "-B", CHILD_SOURCE, "child",
        "--scenario", scenario, "--nonce", nonce,
    ]
    try:
        wrapper = subprocess.Popen(
            args, cwd="/", env={"PATH": "/usr/bin:/bin", "LANG": "C"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
            pass_fds=(information_w,),
        )
    except BaseException:
        os.close(information_r)
        raise
    finally:
        os.close(information_w)
    return wrapper, information_r


def _child_pid_from_bwrap(info_fd, wrapper_pid, timeout):
    # Bubblewrap's --info-fd is a trusted launcher interface.
    # The returned PID is in the supervisor's namespace, not a child claim.
    import select
    end = time.monotonic() + timeout
    chunks = bytearray()
    try:
        os.set_blocking(info_fd, False)
        while time.monotonic() < end:
            readable, _, _ = select.select(
                [info_fd], [], [], min(0.05, max(0, end - time.monotonic()))
            )
            if not readable:
                continue
            piece = os.read(info_fd, 2049 - len(chunks))
            if not piece:
                break
            chunks.extend(piece)
            if len(chunks) > 2048:
                raise RuntimeError("INT1-B10 REFUSED // launcher info overflow")
        try:
            proof = json.loads(chunks.decode("utf-8"))
            inner_pid = proof["child-pid"]
        except (ValueError, UnicodeDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError("INT1-B10 REFUSED // missing trusted child PID") from exc
        if (not isinstance(inner_pid, int) or isinstance(inner_pid, bool)
                or inner_pid < 2 or inner_pid == wrapper_pid):
            raise RuntimeError("INT1-B10 REFUSED // invalid trusted child PID")
        return inner_pid
    finally:
        os.close(info_fd)



def _resolve_isolated_worker(launch_pid, scenario, nonce):
    # Bubblewrap's trusted --info-fd may identify a namespace PID-1 reaper,
    # rather than the actual command. Follow exactly one direct kernel child
    # and match the immutable command identity; never accept a reported PID
    # from the worker's own stdout frame.
    expected = [
        CHILD_EXEC, "-I", "-B", CHILD_SOURCE,
        "child", "--scenario", scenario, "--nonce", nonce,
    ]
    def command(pid):
        raw = Path("/proc/%s/cmdline" % pid).read_bytes()
        return [x.decode("utf-8") for x in raw.split(b"\0") if x]
    if command(launch_pid) == expected:
        return launch_pid
    descendants = Path(
        "/proc/%s/task/%s/children" % (launch_pid, launch_pid)
    ).read_text().split()
    matches = []
    for item in descendants:
        pid = int(item)
        try:
            if command(pid) == expected:
                matches.append(pid)
        except (OSError, UnicodeDecodeError):
            continue
    if len(matches) != 1:
        raise RuntimeError(
            "INT1-B10 REFUSED // trusted isolated worker identity absent"
        )
    worker = matches[0]
    for kind in INNER_ISOLATION_NAMESPACES:
        initial = os.stat("/proc/%s/ns/%s" % (launch_pid, kind))
        final = os.stat("/proc/%s/ns/%s" % (worker, kind))
        if (initial.st_dev, initial.st_ino) != (final.st_dev, final.st_ino):
            raise RuntimeError("INT1-B10 REFUSED // worker namespace escaped")
    return worker


def _observe_nested(pid):
    """Use the kernel's process/root view, never the child READY JSON, as proof."""
    if (os.getsid(pid) == os.getsid(0) or
            os.getpgid(pid) == os.getpgid(0)):
        raise RuntimeError("INT1-B10 REFUSED // worker shares supervisor process group")
    for kind in INNER_ISOLATION_NAMESPACES:
        child = os.stat("/proc/%s/ns/%s" % (pid, kind))
        parent = os.stat("/proc/self/ns/%s" % kind)
        if (child.st_dev, child.st_ino) == (parent.st_dev, parent.st_ino):
            raise RuntimeError("INT1-B10 REFUSED // inner namespace absent: " + kind)
    root = Path("/proc/%s/root" % pid)
    if (root / "fixture").exists() or (root / "fixture/hospital/data/hospital.db").exists():
        raise RuntimeError("INT1-B10 REFUSED // Hospital fixture visible to broker")
    if (root / "source/bin/px-hospital-store").exists():
        raise RuntimeError("INT1-B10 REFUSED // Hospital writer exposed to broker")
    if not (root / "source/bin/px_int1_fake_broker.py").is_file():
        raise RuntimeError("INT1-B10 REFUSED // source mount absent")
    mounts = Path("/proc/%s/mountinfo" % pid).read_text()
    if " /fixture " in mounts or " /fixture/" in mounts:
        raise RuntimeError("INT1-B10 REFUSED // fixture mount leaked")
    status = Path("/proc/%s/status" % pid).read_text().splitlines()
    caps = next((x.split(":", 1)[1].strip() for x in status
                 if x.startswith("CapEff:")), None)
    if caps is None or int(caps, 16) != 0:
        raise RuntimeError("INT1-B10 REFUSED // ambient capabilities retained")
    env_bytes = Path("/proc/%s/environ" % pid).read_bytes()
    env_fields = [x for x in env_bytes.split(b"\0") if x]
    try:
        env = dict(x.decode("utf-8").split("=", 1) for x in env_fields)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("INT1-B10 REFUSED // unparseable environment") from exc
    if env != INNER_ENV or len(env_fields) != len(INNER_ENV):
        # Diagnostics disclose variable NAMES only, never credential values.
        raise RuntimeError("INT1-B10 REFUSED // environment not allowlisted: "
                           + ",".join(sorted(env)))
    fd_root = Path("/proc/%s/fd" % pid)
    fds = {int(x.name) for x in fd_root.iterdir()}
    if fds != {0, 1, 2}:
        raise RuntimeError("INT1-B10 REFUSED // unexpected child descriptors")
    if os.readlink(fd_root / "0") != "/dev/null" or (
            not os.readlink(fd_root / "1").startswith("pipe:[")) or (
            os.readlink(fd_root / "2") != "/dev/null"):
        raise RuntimeError("INT1-B10 REFUSED // child standard streams not sealed")
    return {
        "innerNamespaces": list(INNER_ISOLATION_NAMESPACES),
        "hospitalDbVisible": False, "fixtureRootVisible": False,
        "childFds": [0, 1, 2],
        "childEnvironmentKeys": sorted(INNER_ENV),
        "effectiveCapabilities": 0,
    }


def probe_isolated(room_id, session_id, *, scenario="ready", timeout=1.5):
    """B10 refuses when nested OS confinement is unsupported. Never fall back."""
    from px_int1_fake_atomic import require_id
    require_id(room_id, "Room ID")
    require_id(session_id, "session ID")
    if scenario not in ("ready", "early-exit", "malformed", "timeout"):
        raise RuntimeError("INT1-B10 REFUSED // unknown test scenario")
    if not (0.1 <= timeout <= 4):
        raise RuntimeError("INT1-B10 REFUSED // invalid readiness timeout")
    before = _eligible_snapshot(room_id, session_id)
    nonce = os.urandom(16).hex()
    child, info_fd = _nested_launch(scenario, nonce)
    try:
        inner_pid = _child_pid_from_bwrap(info_fd, child.pid, timeout)
        _receive_ready(child, nonce, timeout)
        worker_pid = _resolve_isolated_worker(inner_pid, scenario, nonce)
        proof = _observe_nested(worker_pid)
        after = _eligible_snapshot(room_id, session_id)
        if (before["generation"], before["contextHash"]) != (
                after["generation"], after["contextHash"]):
            raise RuntimeError("INT1-B10 REFUSED // eligibility changed during startup")
        return {
            "state": "ISOLATED_IDLE_BROKER_PROBED_AND_REAPED",
            "profile": PROFILE, "providerId": FAKE_ID,
            "roomId": room_id, "sessionId": session_id,
            "brokerStarted": True, "brokerReaped": True,
            "ready": True, "osEvidence": proof,
            "messagesAccepted": 0, "eventsAccepted": 0,
            "modelCalls": 0, "toolCalls": 0, "dispatches": 0,
            "productionReady": False,
        }
    finally:
        _terminate_and_reap(child)

def main():
    parser = argparse.ArgumentParser(description="Disposable idle broker readiness proof")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "probe-isolated"):
        parent = sub.add_parser(name)
        parent.add_argument("--room-id", required=True)
        parent.add_argument("--session-id", required=True)
        parent.add_argument("--scenario", default="ready",
                            choices=("ready", "early-exit", "malformed", "timeout"))
        parent.add_argument("--timeout", type=float, default=1.5)
        if name == "probe":
            parent.add_argument("--test-revoke-at-readiness", action="store_true")
    child = sub.add_parser("child")
    child.add_argument("--scenario", required=True)
    child.add_argument("--nonce", required=True)
    args = parser.parse_args()
    if args.command == "child":
        return _idle_child(args.scenario, args.nonce)
    try:
        if args.command == "probe-isolated":
            result = probe_isolated(
                args.room_id, args.session_id,
                scenario=args.scenario, timeout=args.timeout,
            )
        else:
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
