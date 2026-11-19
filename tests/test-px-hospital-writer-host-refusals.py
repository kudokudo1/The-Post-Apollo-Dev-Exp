#!/usr/bin/env python3
"""Installed writer launcher must not accept a caller-selected host config.

Source-only CI refusal contract. This does not assert installed root
permissions or independently trusted Linux service/seat identity.
"""
import os
from pathlib import Path
import subprocess
import sys

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

print("PX HOSPITAL WRITER HOST CONFIG HOLD // no caller paths/keys/unsigned switch; protected runtime never falls back to desktop SQLite")
