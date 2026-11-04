#!/usr/bin/env python3
"""B38-G: trusted test supervisor outside S1, B38-E fake child inside.

Disposable Ubuntu/Linux smoke only. This DOES NOT authenticate a production
Unix peer or credential-isolate a real provider. The host keeps the fake
policy/seal and HMAC verifier; only bounded fake model work enters bwrap.
"""
import argparse
from dataclasses import dataclass
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import SealedFixture, seal_fixture
from px_s3_b38c_transport_policy_fixture import (
    default_fake_manifest, prepare_fake_plan, recheck_fake_plan,
)
from px_s3_b38e_fake_process_ipc import (
    KEY_LEN, MAX_REPLY, NONCE, REPLY, TEXT, VERSION,
    build_fake_request, verify_child_reply,
)

# Byte-identical B38-E plus its dependency closure from the reviewed B38-F.
STAGED = (
    "px_s3_b38e_fake_process_ipc.py",
    "px_s3_b38c_transport_policy_fixture.py",
    "px_s3_b37b_sealed_handoff.py",
    "px_s3_b37a_tool_free_contract.py",
    "px_s3_b29_transport_ledger.py",
    "px_s3_b25_responses_fixture.py",
)
KEY_DEST = "/tmp/b38g-fake-key"
EXPECTED_PID = 2  # Standard S1 bwrap --unshare-pid installs reaper PID 1.
FRAME_TIMEOUT = 25
HOST_ENV = {
    "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin",
    "OPENAI_API_KEY": "B38G-FAKE-HOST-CANARY-NOT-A-KEY",
    "GH_TOKEN": "B38G-FAKE-GH-CANARY",
    "PX_HOSPITAL_DB": "/private/fake-hospital.db",
    "XDG_RUNTIME_DIR": "/private",
}


class Refused(RuntimeError):
    pass


def deny(reason):
    raise Refused("B38G_REFUSED_" + reason)


def load_s1():
    path = ROOT / "tests" / "test-pxd-exec-s1-isolation.py"
    if not path.is_file():
        deny("ACCEPTED_S1_MISSING")
    loader = importlib.machinery.SourceFileLoader("b38g_accepted_s1", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# Child-side negative probes. These assert in the actual isolated B38-E
# process, BEFORE calling its unchanged signed fake request/reply handler.
# They are NOT independent malicious-child attestation.
CHILD_PROGRAM = r'''
import os, pathlib, socket, sys
p = pathlib.Path
checks = {}
checks["net_namespace_differs"] = os.readlink("/proc/self/ns/net") != HOST_NET_NS
checks["pid_namespace_differs"] = os.readlink("/proc/self/ns/pid") != HOST_PID_NS
checks["sandbox_local_pid"] = os.getpid() == 2
checks["home_and_cwd_private"] = os.environ.get("HOME") == "/tmp" and os.getcwd() == "/scratch"
checks["host_fake_secret_hidden"] = not p(HOST_FAKE_SECRET).exists() and not p("/private/fake-provider-auth.json").exists()
checks["host_runtime_hidden"] = not p("/run/user").exists()
checks["no_host_hospital_db"] = not p("/private/fake-hospital.db").exists()
checks["key_is_fake_readonly_file"] = p("/tmp/b38g-fake-key").is_file() and (p("/tmp/b38g-fake-key").stat().st_mode & 0o777) == 0o400
checks["host_env_absent"] = all(k not in os.environ for k in (
    "OPENAI_API_KEY", "GH_TOKEN", "PX_HOSPITAL_DB", "XDG_RUNTIME_DIR", "CODEX_HOME"))
try:
    p("/patient/b38g-unauthorized.txt").write_text("BAD")
except OSError:
    checks["patient_readonly"] = True
else:
    checks["patient_readonly"] = False
p("/scratch/b38g-child-proof.txt").write_text("B38G-SYNTHETIC-ONLY")
checks["scratch_writable"] = p("/scratch/b38g-child-proof.txt").read_text() == "B38G-SYNTHETIC-ONLY"
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    checks["direct_ipv4_denied"] = sock.connect_ex(("1.1.1.1", 443)) != 0
    sock.close()
except OSError:
    checks["direct_ipv4_denied"] = True
# With S1's inherited-FD closure, only stdio should be present BEFORE the
# child opens its own in-sandbox fake-key file.
fds = set()
for entry in p("/proc/self/fd").iterdir():
    try:
        os.readlink(str(entry))
    except OSError:
        continue
    fds.add(entry.name)
checks["only_stdio_before_key_open"] = fds.issubset({"0", "1", "2"})
if set(checks) != {
    "net_namespace_differs", "pid_namespace_differs", "sandbox_local_pid",
    "home_and_cwd_private", "host_fake_secret_hidden", "host_runtime_hidden",
    "no_host_hospital_db", "key_is_fake_readonly_file", "host_env_absent",
    "patient_readonly", "scratch_writable", "direct_ipv4_denied",
    "only_stdio_before_key_open"
} or not all(value is True for value in checks.values()):
    raise SystemExit(9)
sys.path.insert(0, "/patient")
from px_s3_b38e_fake_process_ipc import child_main
fd = os.open("/tmp/b38g-fake-key", os.O_RDONLY | os.O_NOFOLLOW)
raise SystemExit(child_main(fd))
'''


def build_sandbox_command(s1, root, fake_key_fd, fake_secret):
    """Reuses S1 launcher unchanged; bwrap consumes the key *during setup*.

    Bubblewrap closes arbitrary passed descriptors before exec. --file FD
    transfers only this disposable key into /tmp inside the namespace; it
    must NOT be mistaken for a production credential or a retained host FD.
    """
    if type(fake_key_fd) is not int or fake_key_fd < 3:
        deny("KEY_FD_INVALID")
    program = (
        "HOST_NET_NS = " + repr(os.readlink("/proc/self/ns/net")) + "\n" +
        "HOST_PID_NS = " + repr(os.readlink("/proc/self/ns/pid")) + "\n" +
        "HOST_FAKE_SECRET = " + repr(str(fake_secret)) + "\n" +
        CHILD_PROGRAM
    )
    try:
        command = s1.build_command(root, program)
    except s1.IsolationUnavailable:
        deny("SANDBOX_PROFILE_INVALID")
    if (command[0] != "/usr/bin/bwrap" or
        "--unshare-all" not in command or "--clearenv" not in command or
        "--die-with-parent" not in command or
        "--new-session" not in command or
        "--cap-drop" not in command or
        "--ro-bind" not in command):
        deny("SANDBOX_PROFILE_INVALID")
    place = command.index("--chdir")
    command[place:place] = [
        "--perms", "0400", "--file", str(fake_key_fd), KEY_DEST,
    ]
    return command


def _run_inside_sandbox(s1, root, fake_secret, fake_key, signed_request):
    """One single-use fake request; subprocess errors never echo user data."""
    if type(fake_key) is not bytes or len(fake_key) != KEY_LEN:
        deny("FAKE_KEY_INVALID")
    if (type(signed_request) is not bytes or
        not 0 < len(signed_request) <= 15000 or b"\n" in signed_request):
        deny("FAKE_FRAME_INVALID")
    try:
        s1.trusted_bwrap_binary()
    except s1.IsolationUnavailable:
        deny("TRUSTED_BWRAP_UNAVAILABLE")
    read_fd, write_fd = os.pipe()
    proc = None
    try:
        cmd = build_sandbox_command(s1, root, read_fd, fake_secret)
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, close_fds=True, pass_fds=(read_fd,),
            env=dict(HOST_ENV), cwd="/",
        )
        os.close(read_fd)
        read_fd = -1
        # A bounded fake HMAC key is sent to Bubblewrap's --file setup FD.
        # The sandbox process opens a read-only in-sandbox copy as an FD.
        if os.write(write_fd, fake_key) != KEY_LEN:
            deny("FAKE_KEY_TRANSFER_FAILED")
        os.close(write_fd)
        write_fd = -1
        try:
            stdout, _ = proc.communicate(signed_request + b"\n", timeout=FRAME_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            deny("CHILD_TIMEOUT")
        if proc.returncode != 0:
            deny("SANDBOX_CHILD_REFUSED")
        if (len(stdout) < 2 or len(stdout) > MAX_REPLY + 1 or
            not stdout.endswith(b"\n")):
            deny("SANDBOX_REPLY_INVALID")
        return stdout[:-1], proc.pid
    except Refused:
        raise
    except (OSError, subprocess.SubprocessError):
        deny("SANDBOX_EXECUTION_FAILED")
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()


@dataclass(frozen=True, slots=True)
class FakeHostSandboxReceipt:
    text: str
    request_id: str
    sandbox_local_pid: int
    host_bwrap_pid: int
    provenance: str = "B38G_EXTERNAL_SUPERVISOR_FAKE_SANDBOX_ONLY"
    model_calls: int = 0
    tool_calls: int = 0
    network_calls: int = 0
    authenticated_unix_peer: bool = False
    credential_isolation_certified: bool = False
    launch_authorized: bool = False
    production_ready: bool = False


def external_supervisor_fake_exchange(s1, root, fake_secret, sealed, *, current_binding):
    """Explicitly external test supervisor; no B37-C admission or real sender."""
    if type(sealed) is not SealedFixture:
        deny("FAKE_SEAL_TYPE")
    try:
        manifest = default_fake_manifest()
        plan = prepare_fake_plan(
            manifest, sealed=sealed, current_binding=current_binding,
        )
        proof = recheck_fake_plan(
            plan, default_fake_manifest(),
            sealed=sealed, current_binding=current_binding,
        )
        if (proof.get("decision") != "OFFLINE_SHAPE_ONLY" or
            proof.get("transportReady") is not False or
            proof.get("productionReady") is not False):
            deny("FAKE_POLICY_REFUSED")
    except Refused:
        raise
    except Exception:
        deny("FAKE_POLICY_REFUSED")
    key = secrets.token_bytes(KEY_LEN)
    nonce = secrets.token_hex(16)
    request = build_fake_request(
        sealed, current_binding=current_binding, nonce=nonce, fake_key=key,
    )
    reply, bwrap_pid = _run_inside_sandbox(s1, root, fake_secret, key, request)
    answer = verify_child_reply(
        reply, fake_key=key, nonce=nonce,
        request_id=sealed.client_request_id, expected_pid=EXPECTED_PID,
    )
    if bwrap_pid == EXPECTED_PID:
        deny("HOST_PID_NAMESPACE_INVALID")
    return FakeHostSandboxReceipt(
        text=answer["text"], request_id=answer["request_id"],
        sandbox_local_pid=answer["pid"], host_bwrap_pid=bwrap_pid,
    )


def prepare_disposable_root(temp):
    root = Path(temp).resolve(strict=True)
    root.chmod(0o700)
    for name in ("patient", "scratch", "private"):
        (root / name).mkdir(mode=0o700)
    for name in STAGED:
        source = ROOT / "bin" / name
        if not source.is_file() or source.is_symlink():
            deny("PINNED_SOURCE_MISSING")
        dest = root / "patient" / name
        shutil.copyfile(source, dest)
        if dest.read_bytes() != source.read_bytes():
            deny("STAGED_SOURCE_CHANGED")
    secret = root / "private" / "fake-provider-auth.json"
    secret.write_text('{"kind":"B38G_FAKE_CANARY_NOT_REAL"}')
    secret.chmod(0o600)
    return root, secret


BINDING = {
    "room": "b38gRoom", "patient": "b38gPatient",
    "assignment": "b38gAssignment", "bed": "b38gBed",
    "turnId": "b38gTurn", "generation": 4,
}


def fixture():
    binding = dict(BINDING)
    return seal_fixture(
        build_request("B38G_FIXED_FAKE_ONLY_PROMPT"),
        binding=binding, attempt_id="b38gFakeAttempt",
    ), binding


def smoke():
    s1 = load_s1()
    with tempfile.TemporaryDirectory(prefix="b38g-disposable-") as temp:
        root, secret = prepare_disposable_root(temp)
        sealed, binding = fixture()
        # Hold an unrelated host fake secret descriptor through the launch:
        # close_fds/pass_fds must NOT allow this descriptor into the sandbox.
        with secret.open("rb") as held:
            if not held.read(1):
                deny("HOST_CANARY_EMPTY")
            receipt = external_supervisor_fake_exchange(
                s1, root, secret, sealed, current_binding=binding,
            )
            if (receipt.text != TEXT or
                receipt.request_id != sealed.client_request_id or
                receipt.sandbox_local_pid != EXPECTED_PID or
                receipt.host_bwrap_pid <= 2 or
                receipt.model_calls or receipt.tool_calls or receipt.network_calls or
                any(getattr(receipt, name) is not False for name in (
                    "authenticated_unix_peer", "credential_isolation_certified",
                    "launch_authorized", "production_ready"))):
                deny("SIGNED_HOST_RECEIPT_INVALID")
            key1 = b"A" * KEY_LEN
            key2 = b"B" * KEY_LEN
            nonce = "f" * 32
            signed = build_fake_request(
                sealed, current_binding=binding, nonce=nonce, fake_key=key1,
            )
            # Negative #1: child gets a different fake key; no signed reply.
            try:
                _run_inside_sandbox(s1, root, secret, key2, signed)
            except Refused as exc:
                if str(exc) != "B38G_REFUSED_SANDBOX_CHILD_REFUSED":
                    raise
            else:
                deny("WRONG_FAKE_KEY_ACCEPTED")
            # Negative #2: tampering the signed request cannot be laundered.
            modified = signed.replace(b'"kind":', b'"kind":"FORGED", "kind":', 1)
            try:
                _run_inside_sandbox(s1, root, secret, key1, modified)
            except Refused as exc:
                if str(exc) != "B38G_REFUSED_SANDBOX_CHILD_REFUSED":
                    raise
            else:
                deny("TAMPERED_FAKE_FRAME_ACCEPTED")
            if (secret.read_text() != '{"kind":"B38G_FAKE_CANARY_NOT_REAL"}' or
                (root / "patient" / "b38g-unauthorized.txt").exists() or
                (root / "scratch" / "b38g-child-proof.txt").read_text() !=
                "B38G-SYNTHETIC-ONLY"):
                deny("POST_CHILD_FIXTURE_INVARIANT")
    return {
        "state": "B38G_HOST_OUTSIDE_SANDBOX_FAKE_IPC_PASS",
        "outsideSupervisor": True,
        "actualB38EChild": True,
        "signedFakeReply": True,
        "wrongKeyRefused": True,
        "tamperedRequestRefused": True,
        "hostCanaryUnchanged": True,
        "providerCalls": 0,
        "realCredentialsUsed": False,
        "liveHospitalAccess": False,
        "b37cSubmission": False,
        "productionReady": False,
    }


def require_real_provider(*_args, **_kwargs):
    deny("REAL_PROVIDER_FORBIDDEN")


class UnitTests(unittest.TestCase):
    def test_fake_only_real_provider_denied(self):
        with self.assertRaisesRegex(Refused, "REAL_PROVIDER_FORBIDDEN"):
            require_real_provider("live-key")

    def test_reject_bad_key_before_spawn(self):
        with tempfile.TemporaryDirectory(prefix="b38g-unit-") as temp:
            root, secret = prepare_disposable_root(temp)
            with self.assertRaisesRegex(Refused, "FAKE_KEY_INVALID"):
                _run_inside_sandbox(load_s1(), root, secret, b"too short", b"{}")

    def test_exact_s1_profile_with_file_fd_no_key_argv(self):
        s1 = load_s1()
        with tempfile.TemporaryDirectory(prefix="b38g-unit-") as temp:
            root, secret = prepare_disposable_root(temp)
            cmd = build_sandbox_command(s1, root, 12, secret)
        self.assertEqual(cmd[0], "/usr/bin/bwrap")
        for flag in ("--unshare-all", "--clearenv", "--die-with-parent",
                     "--new-session", "--cap-drop", "--tmpfs"):
            self.assertIn(flag, cmd)
        self.assertEqual(
            cmd[cmd.index("--file")-2:cmd.index("--file")+3],
            ["--perms", "0400", "--file", "12", KEY_DEST],
        )
        self.assertNotIn("FAKE-HOST-CANARY-NOT-A-KEY", repr(cmd))
        self.assertNotIn("B38G_FAKE_CANARY_NOT_REAL", repr(cmd))
        self.assertNotIn("--ro-bind-try", cmd)

    def test_missing_trusted_sandbox_fails_closed(self):
        s1 = load_s1()
        with tempfile.TemporaryDirectory(prefix="b38g-unit-") as temp:
            root, secret = prepare_disposable_root(temp)
            with mock.patch.object(
                s1, "trusted_bwrap_binary",
                side_effect=s1.IsolationUnavailable("missing"),
            ):
                with self.assertRaisesRegex(Refused, "TRUSTED_BWRAP_UNAVAILABLE"):
                    _run_inside_sandbox(s1, root, secret, b"A"*KEY_LEN, b"{}")

    def test_stale_fake_binding_refused_before_bwrap(self):
        s1 = load_s1()
        with tempfile.TemporaryDirectory(prefix="b38g-unit-") as temp:
            root, secret = prepare_disposable_root(temp)
            sealed, binding = fixture()
            with mock.patch.object(s1, "trusted_bwrap_binary") as trusted:
                with self.assertRaisesRegex(Refused, "FAKE_POLICY_REFUSED"):
                    external_supervisor_fake_exchange(
                        s1, root, secret, sealed,
                        current_binding={**binding, "generation": 5},
                    )
                trusted.assert_not_called()

    def test_invalid_key_fd_and_wire_size_fail_closed(self):
        s1 = load_s1()
        with tempfile.TemporaryDirectory(prefix="b38g-unit-") as temp:
            root, secret = prepare_disposable_root(temp)
            with self.assertRaisesRegex(Refused, "KEY_FD_INVALID"):
                build_sandbox_command(s1, root, 2, secret)
            with self.assertRaisesRegex(Refused, "FAKE_FRAME_INVALID"):
                _run_inside_sandbox(s1, root, secret, b"A"*KEY_LEN, b"bad\nframe")
            with self.assertRaisesRegex(Refused, "FAKE_FRAME_INVALID"):
                _run_inside_sandbox(s1, root, secret, b"A"*KEY_LEN, b"X"*15001)

    def test_child_code_and_receipt_hold_production(self):
        self.assertIn("from px_s3_b38e_fake_process_ipc import child_main", CHILD_PROGRAM)
        self.assertNotIn("requests", CHILD_PROGRAM)
        self.assertNotIn("httpx", CHILD_PROGRAM)
        self.assertNotIn("api.openai.com", CHILD_PROGRAM)
        self.assertEqual(len(STAGED), len(set(STAGED)))
        receipt = FakeHostSandboxReceipt(
            text=TEXT, request_id="fake", sandbox_local_pid=2,
            host_bwrap_pid=123,
        )
        self.assertIs(receipt.production_ready, False)
        self.assertIs(receipt.authenticated_unix_peer, False)


def main():
    p = argparse.ArgumentParser()
    modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--unit", action="store_true")
    modes.add_argument("--smoke", action="store_true")
    args = p.parse_args()
    if args.unit:
        tests = unittest.defaultTestLoader.loadTestsFromTestCase(UnitTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(tests).wasSuccessful() else 1
    try:
        print(json.dumps(smoke(), sort_keys=True))
        return 0
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
