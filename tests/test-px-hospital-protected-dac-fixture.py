#!/usr/bin/env python3
"""Disposable Linux DAC boundary proof for the proposed PX protected writer.

This is NOT an installed daemon, secure production service or authenticated
Hospital issuer. In CI the runner UID models a future separate writer UID and
the pre-existing nobody UID models an untrusted desktop user. No accounts,
host service, live database, keys or permissions outside a temp directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "bin" / "px-hospital-store"

PEER_CHECK = r"""
import os
from pathlib import Path
import sqlite3
import sys

private, database, backup = map(Path, sys.argv[1:])
attempts = {
    "enumerate_protected_directory": lambda: list(private.iterdir()),
    "read_database": lambda: database.open("rb").read(1),
    "write_database": lambda: database.open("r+b").write(b"x"),
    "sqlite_read_only": lambda: sqlite3.connect(
        "file:" + str(database) + "?mode=ro", uri=True),
    "sqlite_read_write": lambda: sqlite3.connect(
        "file:" + str(database) + "?mode=rw", uri=True),
    "read_backup": lambda: backup.open("rb").read(1),
    "change_database_mode": lambda: os.chmod(database, 0o666),
    "remove_database": lambda: database.unlink(),
}
for name, action in attempts.items():
    try:
        result = action()
    except sqlite3.OperationalError as exc:
        if "unable to open database file" not in str(exc).lower():
            raise
    except OSError:
        pass
    else:
        if isinstance(result, sqlite3.Connection):
            result.close()
        raise AssertionError("DIRECT_ACCESS_ALLOWED: " + name)
print("DENIED: untrusted desktop UID cannot open, alter or remove the protected SQLite store")
"""


def store_command(env: dict[str, str], *args: str):
    p = subprocess.run(
        [sys.executable, str(STORE), *args, "--json"],
        env=env, capture_output=True, text=True, timeout=25,
    )
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return json.loads(p.stdout)


def main():
    assert sys.platform == "linux", "Linux UID separation is required"
    assert os.geteuid() != 0, "Run this fixture as the unprivileged CI runner"
    assert shutil.which("sudo"), "CI must have sudo for the nobody peer"
    peer = pwd.getpwnam("nobody")
    assert peer.pw_uid not in (0, os.geteuid()), "Distinct desktop UID required"

    with tempfile.TemporaryDirectory(prefix="px-hospital-dac-fixture-") as tmp:
        base = Path(tmp)
        # Root path is traversable, but only the separate writer can enter
        # its own restricted subdirectory and reach DB/WAL/SHM/backups.
        base.chmod(0o711)
        protected = base / "protected"
        protected.mkdir(mode=0o700)
        backup_dir = protected / "backups"
        backup_dir.mkdir(mode=0o700)
        database = protected / "hospital.db"
        backup = backup_dir / "hospital-backup.db"

        env = dict(os.environ, PX_HOSPITAL_DATA_DIR=str(protected))
        env.pop("PX_HOSPITAL_DB", None)
        old_umask = os.umask(0o077)
        try:
            assert store_command(env, "status")["schema_version"] == 12
            store_command(
                env, "room-bind", "fixture-secure-room",
                "--repository", "fixture/repo",
            )
            rooms = store_command(env, "rooms")
            assert {x["id"] for x in rooms} == {"fixture-secure-room"}
            # The service owner, not the UI, is the SQLite backup writer.
            with sqlite3.connect(database) as source:
                source.execute("PRAGMA wal_checkpoint(PASSIVE)")
                with sqlite3.connect(backup) as dest:
                    source.backup(dest)
                    assert dest.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            os.umask(old_umask)

        assert protected.stat().st_mode & 0o777 == 0o700
        assert database.stat().st_mode & 0o777 == 0o600
        assert backup.stat().st_mode & 0o777 == 0o600

        peer_check = subprocess.run(
            ["sudo", "-n", "-u", peer.pw_name, sys.executable, "-c",
             PEER_CHECK, str(protected), str(database), str(backup)],
            capture_output=True, text=True, timeout=20,
        )
        assert peer_check.returncode == 0, (
            peer_check.returncode, peer_check.stdout, peer_check.stderr
        )
        assert "DENIED:" in peer_check.stdout
        # Writer UID retains normal PX access, proving a usable OS boundary
        # instead of an unusable database.
        assert store_command(env, "rooms")[0]["id"] == "fixture-secure-room"
        with sqlite3.connect(database) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    print(
        "DISPOSABLE DAC PASS: separate UID cannot read/write PX v12 DB or "
        "backup; owner can read/write. NOT a native service/issuer acceptance."
    )


if __name__ == "__main__":
    main()
