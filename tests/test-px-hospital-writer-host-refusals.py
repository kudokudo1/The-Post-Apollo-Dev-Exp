#!/usr/bin/env python3
"""Installed writer launcher must not accept a caller-selected host config.

Source-only CI refusal contract. This does not assert installed root
permissions or independently trusted Linux service/seat identity.
"""
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "px-hospital-room-writerd"
SERVICE = ROOT / "bin" / "px_hospital_room_writer.py"
RUNTIME = ROOT / "bin" / "px-hospital-protected-runtime"
CLIENT = ROOT / "bin" / "px_hospital_protected_client.py"
assert all(x.is_file() for x in (LAUNCHER, SERVICE, RUNTIME, CLIENT))
src = LAUNCHER.read_text()
service = SERVICE.read_text()
assert 'Path("/etc/post-apollo/hospital/room-writer.json")' in src
assert "stat.S_IWGRP | stat.S_IWOTH" in src
assert "getattr(os, \"O_NOFOLLOW\", 0)" in src
assert "PX_HOSPITAL_DB" in src and "PX_HOSPITAL_DATA_DIR" in src
assert "os.getuid() != os.geteuid()" in src
assert "SO_PEERCRED" in service
assert '"runtimeUid"' in src
client = CLIENT.read_text()
runtime = RUNTIME.read_text()
assert 'Path("/etc/post-apollo/hospital/room-writer.json")' in client
assert "RUNTIME_UID_NOT_PINNED" in client
assert "SO_PEERCRED" in client
assert "SERVER_NOT_PROTECTED_WRITER_IDENTITY" in client
assert "send_command(" in runtime or "main()" in runtime
assert "authority.trusted_public_key()" in service
assert "authority.installed_host_binding()" in service
assert "mode=rw" in service
assert 'if action == "review":' in service
assert 'if action == "bin":' in service

# Even if the environment supplied an untrusted DB/issuer directory,
# the shipped entrypoint refuses any attempted argument override.
for option in (
    ("--config", "/tmp/user-issuer.json"),
    ("--db", "/tmp/user-hospital.db"),
    ("--key", "/tmp/user-key.pub"),
    ("--allow-unsigned",),
):
    env = dict(os.environ)
    env["PX_HOSPITAL_DB"] = "/tmp/untrusted-hospital.db"
    completed = subprocess.run(
        [sys.executable, str(LAUNCHER), *option],
        env=env, text=True, capture_output=True, timeout=10,
    )
    assert completed.returncode == 2, (
        option, completed.stdout, completed.stderr,
    )
    assert "NO_ARGUMENTS_ALLOWED" in completed.stderr


# The native CLI cannot run as an ordinary desktop UID, and will NEVER
# quietly reopen the user-owned Hospital database after a failed socket.
for option in (
    ("status",),
    ("room-bind", "room1", "--repository", "fixture/repo"),
    ("--socket", "/tmp/fake.sock", "rooms"),
    ("--config", "/tmp/fake.json", "rooms"),
):
    env = dict(os.environ, PX_HOSPITAL_DB="/tmp/untrusted-hospital.db")
    result = subprocess.run(
        [sys.executable, str(RUNTIME), *option],
        env=env, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 2, (option, result.stdout, result.stderr)
    assert "NATIVE_RUNTIME_IDENTITY_OR_OVERRIDE_REFUSED" in result.stderr

# The same PX host config function is imported by both native writer and
# Connections consent service. A deny-only desktop marker is not sufficient:
# the privileged native startup must refuse an absent or untrusted marker.
sys.path.insert(0, str(ROOT / "bin"))
launcher = runpy.run_path(str(LAUNCHER), run_name="h1_root_marker_source_test")
check_marker = launcher["require_native_cutover_marker"]
writer_hold = launcher["WriterHold"]
assert "require_native_cutover_marker()" in src
assert str(launcher["NATIVE_CUTOVER_MARKER"]) == (
    "/etc/post-apollo/hospital/legacy-store-cutover.v1"
)


def marker_case(*, mode=stat.S_IFREG | 0o444, owner=0, links=1,
                parent_mode=stat.S_IFDIR | 0o755, missing=False,
                expected=None):
    # Only mock lstat: synthetic root ownership cannot be created by the
    # unprivileged runner. This NEVER inspects or edits real /etc.
    marker = Path("/test-fixture/etc/post-apollo/hospital/legacy-store-cutover.v1")
    good_parent = SimpleNamespace(st_mode=parent_mode, st_uid=0)
    entry = SimpleNamespace(st_mode=mode, st_uid=owner, st_nlink=links)

    def synthetic_lstat(path):
        if path == marker:
            if missing:
                raise FileNotFoundError("synthetic fixture missing")
            return entry
        return good_parent

    with patch.dict(check_marker.__globals__, {"NATIVE_CUTOVER_MARKER": marker}):
        with patch.object(Path, "lstat", synthetic_lstat):
            if expected is None:
                assert check_marker() is None
            else:
                try:
                    check_marker()
                except writer_hold as exc:
                    assert expected in str(exc), str(exc)
                else:
                    raise AssertionError("UNTRUSTED_H1_CUTOVER_MARKER_ACCEPTED")


for secure_mode in (0o400, 0o440, 0o444):
    marker_case(mode=stat.S_IFREG | secure_mode)
marker_case(missing=True, expected="NATIVE_CUTOVER_MARKER_UNAVAILABLE")
marker_case(mode=stat.S_IFREG | 0o644,
            expected="NATIVE_CUTOVER_MARKER_UNTRUSTED")
marker_case(mode=stat.S_IFREG | 0o600,
            expected="NATIVE_CUTOVER_MARKER_UNTRUSTED")
marker_case(owner=1001, expected="NATIVE_CUTOVER_MARKER_UNTRUSTED")
marker_case(links=2, expected="NATIVE_CUTOVER_MARKER_UNTRUSTED")
marker_case(mode=stat.S_IFLNK | 0o777,
            expected="NATIVE_CUTOVER_MARKER_UNTRUSTED")
marker_case(mode=stat.S_IFDIR | 0o444,
            expected="NATIVE_CUTOVER_MARKER_UNTRUSTED")
marker_case(parent_mode=stat.S_IFDIR | 0o777,
            expected="UNTRUSTED_NATIVE_PARENT")

print("PX H1 NATIVE CUTOVER STARTUP HOLD // trusted root-owned deny-only marker required; no host mutation")

print("PX HOSPITAL WRITER HOST CONFIG HOLD // no caller paths/keys/unsigned switch; protected runtime never falls back to desktop SQLite")
