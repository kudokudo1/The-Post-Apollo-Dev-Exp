#!/usr/bin/env python3
"""EXEC-S3 FAKE ONLY: PX-shaped launch/resume, readiness, mediation, revocation.

Only synthetic in-memory Hospital authority and in-process fake model auth.
This module is NOT imported by bin/px-agent; it cannot run Codex/Hermes.
See MODEL/contracts/exec-s3-doctor-execution-isolation.md (draft PR #78).
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import select
import secrets
import signal
import subprocess
import threading
from dataclasses import dataclass, field

S1_NAME = "test-pxd-exec-s1-isolation.py"
S2_NAME = "test-pxd-exec-s2-credential-boundary.py"
TASK = "READ_SYNTHETIC_PATIENT_AND_WRITE_SCRATCH"
WAIT_TASK = "WAIT_THEN_WRITE_SCRATCH"
ALLOWED_TASKS = frozenset((TASK, WAIT_TASK))
FAKE_SESSION_ID = "FAKE-S3-SESSION-1"


class S3Refusal(RuntimeError):
    """A synthetic security boundary refused; no unconfined fallback."""


def accepted(name):
    if name not in (S1_NAME, S2_NAME):
        raise S3Refusal("S3: non-accepted dependency")
    path = Path(__file__).resolve().with_name(name)
    loader = importlib.machinery.SourceFileLoader("s3_fixture_" + name.replace("-", "_").replace(".", "_"), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise S3Refusal("S3: offline dependency not available")
    module = importlib.util.module_from_spec(spec)
    try:
        loader.exec_module(module)
    except (ImportError, OSError) as exc:
        raise S3Refusal("S3: accepted fixture failed") from exc
    return module


@dataclass
class FakeHospital:
    """Disposable authority, records and audit, never a real PX connection."""
    room: str = "R-A"
    patient: str = "SYNTHETIC-PATIENT"
    permissions: set = field(default_factory=lambda: {"READ", "TEST"})
    active: bool = True
    paused: bool = False
    generation: int = 1
    provider_session_id: str = ""
    audit_enabled: bool = True
    outgoing: list = field(default_factory=list)
    events: list = field(default_factory=list)
    state: str = "WAITING"
    lock: threading.RLock = field(default_factory=threading.RLock)

    def audit(self, event: str, reason: str = ""):
        if not self.audit_enabled:
            raise S3Refusal("S3: trusted audit sink unavailable")
        self.events.append({"event": event, "reason": reason,
                            "generation": self.generation})

    def revoke(self):
        with self.lock:
            self.generation += 1
            self.active = False
            self.paused = True
            self.audit("isolation.authority.revoked")


@dataclass(frozen=True)
class ToolGrant:
    nonce: str
    room: str
    patient: str
    generation: int
    task: str


# Broker is a fixed, controlled offline program. Results are untrusted data.
# Readiness is determined by the *parent* from bwrap --info-fd and /proc,
# not by claims in this child. No provider/plugin is present in the child.
BROKER_PROGRAM = r'''
import json, os, pathlib, socket, sys, time
used = set()
def respond(value):
    print(json.dumps(value, sort_keys=True), flush=True)
respond({"kind": "HELLO"})
for line in sys.stdin:
    try:
        frame = json.loads(line)
        if (not isinstance(frame, dict)
                or set(frame) != {"kind", "nonce", "room", "patient", "generation", "task"}
                or frame["kind"] != "EXEC"
                or frame["room"] != "R-A" or frame["patient"] != "SYNTHETIC-PATIENT"
                or not isinstance(frame["generation"], int)
                or frame["generation"] < 1
                or not isinstance(frame["nonce"], str) or len(frame["nonce"]) < 16
                or frame["nonce"] in used
                or frame["task"] not in (
                    "READ_SYNTHETIC_PATIENT_AND_WRITE_SCRATCH",
                    "WAIT_THEN_WRITE_SCRATCH")):
            respond({"kind": "REFUSED"})
            continue
        used.add(frame["nonce"])
        if frame["task"] == "WAIT_THEN_WRITE_SCRATCH":
            time.sleep(12)
        patient = pathlib.Path("/patient/fixture.txt").read_text()
        if patient != "S3-FAKE-PATIENT" or pathlib.Path("/private").exists():
            respond({"kind": "REFUSED"})
            continue
        if any(key in os.environ for key in (
                "OPENAI_API_KEY", "GH_TOKEN", "CODEX_HOME", "PX_HOSPITAL_DB")):
            respond({"kind": "REFUSED"})
            continue
        try:
            pathlib.Path("/patient/illegal.txt").write_text("ESCALATION")
        except OSError:
            pass
        else:
            respond({"kind": "REFUSED"})
            continue
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.4)
            if sock.connect_ex(("1.1.1.1", 443)) == 0:
                respond({"kind": "REFUSED"})
                continue
            sock.close()
        except OSError:
            pass
        pathlib.Path("/scratch/s3-result.txt").write_text("S3-FAKE-COMPLETE")
        respond({"kind": "RESULT", "nonce": frame["nonce"], "value": "UNTRUSTED-SUCCESS"})
    except Exception:
        respond({"kind": "REFUSED"})
'''


def read_line_ready(stream, timeout=6):
    try:
        fd = stream.fileno()
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            raise S3Refusal("S3: broker readiness or response timeout")
        line = stream.readline()
        if not line or len(line) > 32768:
            raise S3Refusal("S3: broker stopped or oversized response")
        return json.loads(line)
    except (OSError, ValueError, TypeError) as exc:
        raise S3Refusal("S3: malformed or unavailable broker response") from exc


class IsolatedBroker:
    """Only supervisor-owned stdin can send tools to the fixed sandbox."""
    def __init__(self, root: Path):
        self.root = root
        self.process = None
        self.child_pid = 0
        self.ready = False
        self.pending = {}
        self.used = set()

    def start(self):
        s1 = accepted(S1_NAME)
        s1.validated_fixture(self.root)
        s1.trusted_bwrap_binary()
        command = s1.build_command(self.root, BROKER_PROGRAM)
        read_fd, write_fd = os.pipe()
        try:
            # Only the temporary info FD is passed to root-owned bwrap.
            command[1:1] = ["--info-fd", str(write_fd)]
            try:
                self.process = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, bufsize=1,
                    env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                         "OPENAI_API_KEY": "FAKE-S3-PARENT-CANARY"},
                    close_fds=True, pass_fds=(write_fd,), start_new_session=True)
            except OSError as exc:
                raise S3Refusal("S3: broker launch failed") from exc
        finally:
            os.close(write_fd)
        try:
            with os.fdopen(read_fd, "rb", buffering=0) as info:
                ready, _, _ = select.select([info.fileno()], [], [], 6)
                if not ready:
                    raise S3Refusal("S3: no trusted bwrap child information")
                raw = info.read(4096)
            record = json.loads(raw)
            self.child_pid = record.get("child-pid", 0)
            if not isinstance(self.child_pid, int) or self.child_pid <= 0:
                raise S3Refusal("S3: invalid bwrap child process identity")
            # The bwrap info PID may precede mount/setup completion. Use
            # HELLO only as a synchronization barrier; it is NOT attestation.
            try:
                hello = read_line_ready(self.process.stdout)
            except S3Refusal as exc:
                detail = ""
                if self.process.poll() is not None:
                    detail = self.process.stderr.read()[-1200:]
                raise S3Refusal("S3: synthetic broker handshake refused: " + detail) from exc
            if hello != {"kind": "HELLO"} or self.process.poll() is not None:
                raise S3Refusal("S3: broker not ready")
            # Now independently inspect host-kernel facts about the child.
            for ns in ("net", "mnt"):
                if (os.readlink("/proc/%d/ns/%s" % (self.child_pid, ns))
                        == os.readlink("/proc/self/ns/%s" % ns)):
                    raise S3Refusal("S3: broker did not enter isolated " + ns)
            # /proc/<pid>/root may be inaccessible across user namespaces.
            # Host /proc/<pid>/mountinfo is kernel-generated (not broker JSON).
            mountinfo = Path("/proc/%d/mountinfo" % self.child_pid).read_text()
            mounts = {}
            for line in mountinfo.splitlines():
                fields = line.split(" - ", 1)[0].split()
                if len(fields) > 5:
                    mounts[fields[4]] = fields[5].split(",")
            if "/patient" not in mounts or "ro" not in mounts["/patient"]:
                raise S3Refusal("S3: read-only patient mount not verified")
            if "/scratch" not in mounts or "rw" not in mounts["/scratch"]:
                raise S3Refusal("S3: writable scratch mount not verified")
            if "/private" in mounts:
                raise S3Refusal("S3: fake private mount exposed")
            self.ready = True
        except (OSError, TypeError, ValueError) as exc:
            raise S3Refusal("S3: OS readiness attestation unavailable") from exc
        finally:
            if not self.ready:
                self.close()

    def grant(self, grant: ToolGrant):
        if not self.ready or self.process.poll() is not None:
            raise S3Refusal("S3: broker not ready")
        if grant.nonce in self.pending or grant.nonce in self.used:
            raise S3Refusal("S3: duplicate grant")
        self.pending[grant.nonce] = grant

    def execute(self, grant: ToolGrant, on_dispatched=None):
        if not self.ready or self.process.poll() is not None:
            raise S3Refusal("S3: isolated broker unavailable")
        if self.pending.pop(grant.nonce, None) is not grant:
            raise S3Refusal("S3: missing or replayed PX grant")
        self.used.add(grant.nonce)
        frame = {"kind": "EXEC", "nonce": grant.nonce, "room": grant.room,
                 "patient": grant.patient, "generation": grant.generation,
                 "task": grant.task}
        try:
            self.process.stdin.write(json.dumps(frame) + "\n")
            self.process.stdin.flush()
            if on_dispatched:
                on_dispatched()
            result = read_line_ready(self.process.stdout, timeout=16)
        except (OSError, ValueError) as exc:
            raise S3Refusal("S3: broker dispatch aborted") from exc
        if result != {"kind": "RESULT", "nonce": grant.nonce,
                      "value": "UNTRUSTED-SUCCESS"}:
            raise S3Refusal("S3: untrusted tool result rejected")
        # Only independent synthetic scratch observation counts here.
        if (self.root / "scratch" / "s3-result.txt").read_text() != "S3-FAKE-COMPLETE":
            raise S3Refusal("S3: independently observed scratch result missing")

    def close(self):
        self.ready = False
        proc = self.process
        if proc is None:
            return
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                raise S3Refusal("S3: broker child reap failed")
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass


class FakePXSupervisor:
    def __init__(self, hospital: FakeHospital, root: Path, service, broker_factory=IsolatedBroker):
        self.hospital, self.root, self.service = hospital, root, service
        self.broker_factory = broker_factory
        self.active_broker = None

    def check(self, resume: bool, generation=None):
        h = self.hospital
        if not h.active or h.paused or h.room != "R-A" or h.patient != "SYNTHETIC-PATIENT":
            raise S3Refusal("S3: current Room or Assignment refused")
        if not {"READ", "TEST"}.issubset(h.permissions):
            raise S3Refusal("S3: current permissions insufficient")
        if resume and h.provider_session_id != FAKE_SESSION_ID:
            raise S3Refusal("S3: native session mismatch")
        if not resume and h.provider_session_id:
            raise S3Refusal("S3: existing session requires resume")
        if generation is not None and generation != h.generation:
            raise S3Refusal("S3: stale authority generation")
        if not self.root.is_absolute() or self.root.is_symlink() or not self.root.is_dir():
            raise S3Refusal("S3: untrusted synthetic Bed")
        if (self.root / "patient" / "fixture.txt").read_text() != "S3-FAKE-PATIENT":
            raise S3Refusal("S3: wrong Patient fixture")

    def revoke(self):
        self.hospital.revoke()
        if self.active_broker is not None:
            self.active_broker.close()

    def run(self, resume=False, proposed_task=None, on_ready=None,
            before_dispatch=None, on_dispatched=None):
        h = self.hospital
        # STAGE A: no message persistence, provider launch or tools.
        with h.lock:
            self.check(resume)
            if not h.audit_enabled:
                raise S3Refusal("S3: trusted audit sink unavailable")
            generation = h.generation
            s1 = accepted(S1_NAME)
            s2 = accepted(S2_NAME)
            try:
                s1.validated_fixture(self.root)
                s1.trusted_bwrap_binary()
                s2.checked_auth_path(self.root)
            except (s1.IsolationUnavailable, s2.BoundaryRefusal) as exc:
                raise S3Refusal("S3: offline isolation prerequisite refused") from exc
            h.audit("isolation.preflight.passed")
        broker = self.broker_factory(self.root)
        try:
            # STAGE B: actual sandbox creation and OS-observed readiness.
            broker.start()
            self.active_broker = broker
            if on_ready:
                on_ready()
            with h.lock:
                self.check(resume, generation=generation)
                if not broker.ready:
                    raise S3Refusal("S3: broker no longer ready")
                h.audit("isolation.broker.ready")
                # STAGE C: first durable outgoing message AFTER readiness.
                h.outgoing.append({"kind": "operator", "resume": resume})
                h.audit("turn.started")
                h.state = "OPERATING"
            try:
                # This is S2 in-process authentication, NOT a provider process.
                task = s2.TrustedFakeClient(self.root, self.service).get_task()
                if proposed_task is not None:
                    task = proposed_task  # fake-only negative test injection
                if task not in ALLOWED_TASKS:
                    raise S3Refusal("S3: unsupported model tool request")
                if before_dispatch:
                    before_dispatch()
                with h.lock:
                    self.check(resume, generation=generation)
                    grant = ToolGrant(secrets.token_urlsafe(24), h.room, h.patient,
                                      h.generation, task)
                    broker.grant(grant)
                    h.audit("isolation.tool.allowed")
                broker.execute(grant, on_dispatched=on_dispatched)
                with h.lock:
                    self.check(resume, generation=generation)
                    h.provider_session_id = FAKE_SESSION_ID
                    h.state = "WAITING"
                    h.audit("turn.completed")
                return {"state": "PASS", "resume": resume, "toolIsolated": True,
                        "realModelCalls": 0, "realCredentialsUsed": False,
                        "liveHospitalAccess": False, "productionReady": False}
            except (S3Refusal, OSError, ValueError):
                with h.lock:
                    h.state = "FAILED"
                    if h.audit_enabled:
                        h.audit("turn.failed", "supervised-refusal")
                raise
        except (S3Refusal, OSError, ValueError):
            # Stage A/B refusal never appends outgoing messages.
            if h.audit_enabled and h.state != "FAILED":
                h.audit("isolation.preflight.refused", "startup-or-authority")
            raise
        finally:
            broker.close()
            if self.active_broker is broker:
                self.active_broker = None
