#!/usr/bin/env python3
"""B36-H5 Linux CI-only FAKE process-group experiment, never Hermes.

This probes Linux kernel process/session IDs with a disposable Python sleeper.
It does NOT establish gateway confinement, no-network, cgroup ownership,
credential isolation, descendant reaping or real provider admission.
Only an explicit GitHub Actions job may arm this process-creating probe.
"""
import os
import platform
import select
import signal
import subprocess
import sys
import time

PROBE_ENV_FLAG = "PX_H5_FAKE_OS_PROBE_APPROVED_IN_CI"
_PROBE_SLEEP_SECONDS = 12

# The fake worker only starts another Python sleeper; no shell or Hermes.
_WORKER = """
import os, subprocess, sys, time
env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
       "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C"}
child = subprocess.Popen(
    [sys.executable, "-I", "-S", "-c", "import time; time.sleep(12)"],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL, close_fds=True,
    cwd="/tmp", env=env, start_new_session=(sys.argv[1] == "escape"))
print(child.pid, flush=True)
time.sleep(12)
"""


def parse_proc_stat(raw):
    """Extract PID, state, PGID, SID and birth ticks from proc(5) stat.

    The second (comm) field may contain spaces and parentheses; split after
    the LAST ') ' delimiter, not with raw whitespace split. This is still
    text parsing, not an authenticated kernel receipt.
    """
    if type(raw) is not str or len(raw) > 65536:
        raise ValueError("PROC_STAT_FORMAT")
    opening = raw.find(" (")
    closing = raw.rfind(") ")
    if opening < 1 or closing <= opening:
        raise ValueError("PROC_STAT_FORMAT")
    pid_text = raw[:opening]
    if not pid_text.isascii() or not pid_text.isdecimal():
        raise ValueError("PROC_PID")
    fields = raw[closing + 2:].split()
    if len(fields) < 20 or len(fields[0]) != 1 or fields[0] not in "RSDZTWIXKP":
        raise ValueError("PROC_FIELDS")
    try:
        pid = int(pid_text)
        ppid, pgrp, sid = (int(fields[i]) for i in (1, 2, 3))
        born = int(fields[19])
    except ValueError as exc:
        raise ValueError("PROC_FIELDS") from exc
    if pid <= 0 or min(ppid, pgrp, sid, born) < 0:
        raise ValueError("PROC_FIELDS")
    return {"pid": pid, "state": fields[0], "ppid": ppid,
            "processGroup": pgrp, "session": sid, "startTicks": born}


def _read_identity(pid):
    """Current CI fake PID only; returns None on disappearance/permission."""
    try:
        with open("/proc/%d/stat" % pid, "r", encoding="utf-8") as file:
            return parse_proc_stat(file.read())
    except (OSError, ValueError):
        return None


def _same_live_process(birth):
    if not birth:
        return False
    observed = _read_identity(birth["pid"])
    return bool(observed and observed["startTicks"] == birth["startTicks"]
                and observed["state"] not in ("Z", "X"))


def _cgroup_path(pid):
    try:
        with open("/proc/%d/cgroup" % pid, encoding="utf-8") as file:
            lines = file.read().splitlines()
    except OSError:
        return None
    unified = [line[3:] for line in lines if line.startswith("0::")]
    return unified[0] if len(unified) == 1 else None


def _armed_in_ci():
    return (platform.system() == "Linux" and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get(PROBE_ENV_FLAG) == "1"
            and os.path.isdir("/proc") and sys.platform.startswith("linux"))


def exercise_fake_group(*, escaped_descendant=False):
    """CI-only observed limitation: killpg works until a child uses setsid().

    The only processes created are a fresh-session Python fake worker and a
    short-lived Python sleeper with NO credentials propagated in env. The
    runner is not an OS network sandbox. Full descendant termination remains
    UNVERIFIED, including if same-group sleepers become unreaped zombies.
    """
    if not _armed_in_ci():
        raise RuntimeError("H5_CI_ONLY_FAKE_PROBE_NOT_AUTHORIZED")
    clean_env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
                 "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C"}
    worker = None
    child_birth = None
    worker_birth = None
    try:
        worker = subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", _WORKER,
             "escape" if escaped_descendant else "same"],
            env=clean_env, cwd="/tmp", close_fds=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True, text=True)
        worker_birth = _read_identity(worker.pid)
        if (worker_birth is None or worker_birth["processGroup"] != worker.pid
                or worker_birth["session"] != worker.pid):
            raise RuntimeError("H5_OWNER_IDENTITY_UNVERIFIED")
        ready, _, _ = select.select([worker.stdout], [], [], 5.0)
        if not ready:
            raise RuntimeError("H5_FAKE_START_TIMEOUT")
        line = worker.stdout.readline().strip()
        if not line.isascii() or not line.isdecimal():
            raise RuntimeError("H5_FAKE_CHILD_UNKNOWN")
        pid = int(line)
        child_birth = _read_identity(pid)
        if child_birth is None or not _same_live_process(child_birth):
            raise RuntimeError("H5_FAKE_CHILD_NOT_OBSERVED")

        same_group = child_birth["processGroup"] == worker_birth["processGroup"]
        if same_group == escaped_descendant:
            raise RuntimeError("H5_PROCESS_GROUP_OBSERVATION_INCONSISTENT")

        # The disposable worker is NOT in a dedicated cgroup; that's one of
        # the explicit reasons group-wide killing cannot prove isolation.
        root_cgroup = _cgroup_path(os.getpid())
        child_cgroup = _cgroup_path(pid)
        worker_cgroup = _cgroup_path(worker.pid)
        cgroup_separated = (root_cgroup is not None and worker_cgroup is not None
                            and root_cgroup != worker_cgroup)

        # Do not signal arbitrary PIDs. We observed PID + start ticks and
        # independently checked the FAKE worker owns its own session group.
        if not _same_live_process(worker_birth) or os.getpgid(worker.pid) != worker.pid:
            raise RuntimeError("H5_OWNER_IDENTITY_CHANGED")
        os.killpg(worker.pid, signal.SIGKILL)
        worker.wait(timeout=4.0)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if escaped_descendant or not _same_live_process(child_birth):
                break
            time.sleep(0.02)
        descendant_still_executing = _same_live_process(child_birth)

        return {
            "kind": "FAKE_SETSID_ESCAPE" if escaped_descendant else "FAKE_SHARED_PGID",
            "decision": "DENY", "observedSameGroup": same_group,
            "descendantSurvivedGroupKill": descendant_still_executing,
            "workerExecutionStopped": not _same_live_process(worker_birth),
            "dedicatedCgroupObserved": cgroup_separated,
            "rootAndChildShareCgroup": (
                root_cgroup is not None and child_cgroup == root_cgroup),
            "networkEgressPrevented": False, "credentialBoundaryCertified": False,
            "completeDescendantTeardownCertified": False,
            "gatewayCalls": 0, "modelCalls": 0, "toolCalls": 0,
            "hospitalWrites": 0, "realHermesLaunched": False,
            "productionReady": False,
        }
    finally:
        # Cleanup only the identified disposable child. Never kill an
        # unrelated PID after reuse. The sleeper also has a 12-second bound.
        if child_birth and _same_live_process(child_birth):
            try:
                os.kill(child_birth["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        if worker is not None:
            if worker.poll() is None and worker_birth and _same_live_process(worker_birth):
                try:
                    if os.getpgid(worker.pid) == worker.pid:
                        os.killpg(worker.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                worker.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                pass
            if worker.stdout:
                worker.stdout.close()
