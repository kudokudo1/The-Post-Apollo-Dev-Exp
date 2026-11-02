#!/usr/bin/env python3
"""B38-F: run the actual B38-E fake sender inside accepted S1 Bubblewrap.

Offline, disposable Linux kernel probe only. The synthetic supervisor is
ALSO inside this sandbox; this does not certify host-to-child authenticated
IPC or any live provider / Hospital access. No local Fedora changes.
"""
import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STAGED = (
    "px_s3_b38e_fake_process_ipc.py",
    "px_s3_b38c_transport_policy_fixture.py",
    "px_s3_b37b_sealed_handoff.py",
    "px_s3_b37a_tool_free_contract.py",
    "px_s3_b29_transport_ledger.py",
    "px_s3_b25_responses_fixture.py",
)
EXPECTED = frozenset((
    "separate_net_namespace", "separate_pid_namespace",
    "private_home", "private_host_secret_hidden",
    "no_host_sockets", "no_host_hospital", "patient_read_only",
    "scratch_writable", "direct_ipv4_denied",
    "host_openai_env_absent", "host_gh_env_absent",
    "host_hospital_env_absent", "host_runtime_env_absent",
    "child_pid_distinct", "child_pid_namespace_inherited",
    "child_net_namespace_inherited", "child_parent_pid",
    "child_exact_program", "child_close_fds",
    "child_key_pipe_inherited", "child_fd_only_expected",
    "child_no_private_fd", "child_env_no_host_credentials",
    "signed_ipc_receipt", "zero_real_operations",
    "receipt_still_production_hold",
))


class Refused(RuntimeError):
    pass


def deny(reason):
    raise Refused("B38F_REFUSED_" + reason)


def load_s1():
    path = ROOT / "tests" / "test-pxd-exec-s1-isolation.py"
    if not path.is_file():
        deny("S1_MISSING")
    loader = importlib.machinery.SourceFileLoader("b38f_accepted_s1", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PROGRAM = r'''
import json, os, pathlib, socket, subprocess, sys
sys.path.insert(0, "/patient")
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import seal_fixture
import px_s3_b38e_fake_process_ipc as ipc

p = pathlib.Path
checks = {}
checks["separate_net_namespace"] = os.readlink("/proc/self/ns/net") != HOST_NET
checks["separate_pid_namespace"] = os.readlink("/proc/self/ns/pid") != HOST_PID
checks["private_home"] = os.environ.get("HOME") == "/tmp" and os.getcwd() == "/scratch"
checks["private_host_secret_hidden"] = not p(HOST_SECRET).exists() and not p("/private/fake-provider-auth.json").exists()
checks["no_host_sockets"] = not p("/run/user").exists()
checks["no_host_hospital"] = not p("/private/fake-hospital.db").exists()
try:
    p("/patient/unauthorized.txt").write_text("NO")
except OSError:
    checks["patient_read_only"] = True
else:
    checks["patient_read_only"] = False
p("/scratch/proof.txt").write_text("SYNTHETIC-SCRATCH")
checks["scratch_writable"] = p("/scratch/proof.txt").read_text() == "SYNTHETIC-SCRATCH"
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    checks["direct_ipv4_denied"] = sock.connect_ex(("1.1.1.1", 443)) != 0
    sock.close()
except OSError:
    checks["direct_ipv4_denied"] = True
for key, name in (("OPENAI_API_KEY", "host_openai_env_absent"),
                  ("GH_TOKEN", "host_gh_env_absent"),
                  ("PX_HOSPITAL_DB", "host_hospital_env_absent"),
                  ("XDG_RUNTIME_DIR", "host_runtime_env_absent")):
    checks[name] = key not in os.environ

real_popen = subprocess.Popen
seen = []
def observe_popen(*args, **kwargs):
    child = real_popen(*args, **kwargs)
    seen.append(child.pid)
    cmd = args[0] if args else ()
    key_fd = str(cmd[-1]) if cmd else ""
    checks["child_exact_program"] = (
        isinstance(cmd, list) and len(cmd) == 6 and
        cmd[:3] == [sys.executable, "-I", "-B"] and
        cmd[3] == "/patient/px_s3_b38e_fake_process_ipc.py" and
        cmd[4] == "--child" and key_fd.isdecimal() and
        kwargs.get("env") == ipc.CHILD_ENV
    )
    checks["child_close_fds"] = (
        kwargs.get("close_fds") is True and
        kwargs.get("pass_fds") == (int(key_fd),) and
        kwargs.get("cwd") == "/" and kwargs.get("shell") is not True
    ) if key_fd.isdecimal() else False
    child_proc = p("/proc") / str(child.pid)
    checks["child_pid_distinct"] = child.pid > 1 and child.pid != os.getpid()
    try:
        checks["child_pid_namespace_inherited"] = os.readlink(str(child_proc / "ns/pid")) == os.readlink("/proc/self/ns/pid")
        checks["child_net_namespace_inherited"] = os.readlink(str(child_proc / "ns/net")) == os.readlink("/proc/self/ns/net")
        status = (child_proc / "status").read_text()
        checks["child_parent_pid"] = "PPid:\t" + str(os.getpid()) in status.splitlines()
        fd_dir = child_proc / "fd"
        fds = {entry.name: os.readlink(str(entry)) for entry in fd_dir.iterdir()}
        checks["child_key_pipe_inherited"] = key_fd in fds and fds[key_fd].startswith("pipe:[")
        checks["child_fd_only_expected"] = set(fds).issubset({"0", "1", "2", key_fd})
        checks["child_no_private_fd"] = all(HOST_SECRET not in target and "fake-provider-auth" not in target for target in fds.values())
        env = (child_proc / "environ").read_bytes()
        checks["child_env_no_host_credentials"] = all(
            (name + "=").encode("ascii") not in env
            for name in ("OPENAI_API_KEY", "GH_TOKEN", "PX_HOSPITAL_DB",
                         "XDG_RUNTIME_DIR", "CODEX_HOME")
        )
    except OSError:
        for name in ("child_pid_namespace_inherited", "child_net_namespace_inherited",
                     "child_parent_pid", "child_key_pipe_inherited",
                     "child_fd_only_expected", "child_no_private_fd",
                     "child_env_no_host_credentials"):
            checks[name] = False
    return child

# Observe the *real* B38-E subprocess before the supervisor supplies its key.
# The subprocess is blocked on the key pipe, so PID/fd observations are live.
ipc.subprocess.Popen = observe_popen
binding = {
    "room": "fakeRoom", "patient": "fakePatient",
    "assignment": "fakeAssignment", "bed": "fakeBed",
    "turnId": "fakeTurn", "generation": 2,
}
sealed = seal_fixture(build_request("FAKE_ONLY_B38F_PROMPT"),
                      binding=binding, attempt_id="fakeB38FAttempt")
receipt = ipc.exchange_in_separate_fake_process(sealed, current_binding=binding)
checks["signed_ipc_receipt"] = (
    len(seen) == 1 and receipt.child_pid == seen[0] and
    receipt.text == ipc.TEXT and receipt.request_id == sealed.client_request_id
)
checks["zero_real_operations"] = (
    receipt.model_calls == receipt.tool_calls == receipt.network_calls == 0
)
checks["receipt_still_production_hold"] = (
    receipt.sender_os_isolated is False and
    receipt.credential_isolation_certified is False and
    receipt.launch_authorized is False and receipt.production_ready is False
)
output = {"state": "B38F_FAKE_CHILD_SANDBOX_OBSERVED", "checks": checks,
          "providerCalls": 0, "realCredentialsUsed": False,
          "liveHospitalAccess": False, "productionReady": False}
print(json.dumps(output, sort_keys=True))
raise SystemExit(0 if all(value is True for value in checks.values()) else 7)
'''


def validate_evidence(out):
    if (type(out) is not dict or set(out) != {
        "state", "checks", "providerCalls", "realCredentialsUsed",
        "liveHospitalAccess", "productionReady"
    } or out["state"] != "B38F_FAKE_CHILD_SANDBOX_OBSERVED" or
        out["providerCalls"] != 0 or
        any(out[key] is not False for key in (
            "realCredentialsUsed", "liveHospitalAccess", "productionReady")) or
        type(out["checks"]) is not dict or
        set(out["checks"]) != EXPECTED or
        any(v is not True for v in out["checks"].values())):
        deny("KERNEL_EVIDENCE_INVALID")
    return out


def sandbox_command(s1, root, host_secret):
    program = (
        "HOST_NET = " + repr(os.readlink("/proc/self/ns/net")) + "\n" +
        "HOST_PID = " + repr(os.readlink("/proc/self/ns/pid")) + "\n" +
        "HOST_SECRET = " + repr(str(host_secret)) + "\n" + PROGRAM
    )
    return s1.build_command(root, program)


def smoke():
    s1 = load_s1()
    try:
        s1.trusted_bwrap_binary()
    except s1.IsolationUnavailable:
        deny("TRUSTED_BWRAP_UNAVAILABLE")
    with tempfile.TemporaryDirectory(prefix="b38f-disposable-") as temp:
        root = Path(temp).resolve(strict=True)
        root.chmod(0o700)
        for name in ("patient", "scratch", "private"):
            (root / name).mkdir(mode=0o700)
        patient = root / "patient"
        for name in STAGED:
            original = ROOT / "bin" / name
            if not original.is_file() or original.is_symlink():
                deny("PINNED_SOURCE_MISSING")
            shutil.copyfile(original, patient / name)
            if (patient / name).read_bytes() != original.read_bytes():
                deny("STAGED_SOURCE_CHANGED")
        secret = root / "private" / "fake-provider-auth.json"
        secret.write_text('{"fake":"B38F-NOT-A-CREDENTIAL"}')
        secret.chmod(0o600)
        try:
            cmd = sandbox_command(s1, root, secret)
        except s1.IsolationUnavailable:
            deny("SANDBOX_COMMAND_REFUSED")
        if cmd[0] != "/usr/bin/bwrap" or "--clearenv" not in cmd:
            deny("SANDBOX_PROFILE_REFUSED")
        env = {
            "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "FAKE-B38F-CANARY",
            "GH_TOKEN": "FAKE-GH-CANARY",
            "PX_HOSPITAL_DB": str(root / "private" / "fake-hospital.db"),
            "XDG_RUNTIME_DIR": str(root / "private"),
        }
        try:
            with secret.open("rb") as held_secret:
                if not held_secret.read(1):
                    deny("FAKE_SECRET_EMPTY")
                run = subprocess.run(
                    cmd, env=env, capture_output=True, text=True,
                    close_fds=True, timeout=30, check=False,
                )
        except (OSError, subprocess.TimeoutExpired):
            deny("SANDBOX_EXEC_FAILED")
        if run.returncode:
            deny("CHILD_OR_SANDBOX_NONZERO")
        if run.stderr.strip() or len(run.stdout) > 12000:
            deny("UNEXPECTED_CHILD_OUTPUT")
        try:
            evidence = validate_evidence(json.loads(run.stdout))
        except (ValueError, TypeError):
            deny("EVIDENCE_PARSE_FAILED")
        if (secret.read_text() != '{"fake":"B38F-NOT-A-CREDENTIAL"}' or
            (patient / "unauthorized.txt").exists() or
            (root / "scratch" / "proof.txt").read_text() != "SYNTHETIC-SCRATCH"):
            deny("POST_CHILD_INVARIANT")
        return evidence


class UnitTests(unittest.TestCase):
    def test_evidence_requires_exact_true_booleans(self):
        good = {
            "state": "B38F_FAKE_CHILD_SANDBOX_OBSERVED",
            "checks": {k: True for k in EXPECTED},
            "providerCalls": 0, "realCredentialsUsed": False,
            "liveHospitalAccess": False, "productionReady": False,
        }
        self.assertEqual(validate_evidence(good), good)
        for bad in ({**good, "checks": {}},
                    {**good, "productionReady": True},
                    {**good, "checks": {**good["checks"], "direct_ipv4_denied": False}},
                    {**good, "checks": {**good["checks"], "extra": True}},
                    {**good, "providerCalls": True}):
            with self.assertRaisesRegex(Refused, "KERNEL_EVIDENCE_INVALID"):
                validate_evidence(bad)

    def test_s1_profile_not_bypassed(self):
        s1 = load_s1()
        with tempfile.TemporaryDirectory(prefix="b38f-static-") as temp:
            root = Path(temp).resolve(strict=True)
            for name in ("patient", "scratch", "private"):
                (root / name).mkdir()
            cmd = sandbox_command(s1, root, root / "private" / "canary")
        self.assertEqual(cmd[0], "/usr/bin/bwrap")
        for flag in ("--unshare-all", "--die-with-parent", "--new-session",
                     "--cap-drop", "--clearenv", "--tmpfs"):
            self.assertIn(flag, cmd)
        self.assertNotIn("FAKE-B38F-CANARY", repr(cmd))

    def test_missing_trusted_bwrap_fails_closed(self):
        s1 = load_s1()
        with mock.patch.object(s1, "trusted_bwrap_binary",
                               side_effect=s1.IsolationUnavailable("missing")):
            with mock.patch(__name__ + ".load_s1", return_value=s1):
                with self.assertRaisesRegex(Refused, "TRUSTED_BWRAP_UNAVAILABLE"):
                    smoke()

    def test_no_runtime_provider_code_or_source_mutation(self):
        self.assertNotIn("import requests", PROGRAM)
        self.assertNotIn("import httpx", PROGRAM)
        self.assertNotIn("api.openai.com", PROGRAM)
        self.assertNotIn("hermes_cli", PROGRAM)
        self.assertIn("ipc.exchange_in_separate_fake_process(", PROGRAM)
        self.assertEqual(len(STAGED), len(set(STAGED)))


def main():
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--unit", action="store_true")
    choice.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.unit:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(UnitTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    try:
        result = smoke()
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
