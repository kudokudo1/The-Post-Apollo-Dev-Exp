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
assert LAUNCHER.is_file() and SERVICE.is_file()
src = LAUNCHER.read_text()
service = SERVICE.read_text()
assert 'Path("/etc/post-apollo/hospital/room-writer.json")' in src
assert "stat.S_IWGRP | stat.S_IWOTH" in src
assert "getattr(os, \"O_NOFOLLOW\", 0)" in src
assert "PX_HOSPITAL_DB" in src and "PX_HOSPITAL_DATA_DIR" in src
assert "os.getuid() != os.geteuid()" in src
assert "SO_PEERCRED" in service
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

print("PX HOSPITAL WRITER HOST CONFIG HOLD // no caller paths/keys/unsigned switch")
