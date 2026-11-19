#!/usr/bin/env python3
"""NEGATIVE SECURITY WITNESS: demonstrates same-UID direct SQLite bypass.

Disposable database only. A passing test establishes the missing OS boundary,
NOT production security acceptance. Replace this test with a denial assertion
after native writer isolation is implemented.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

STORE = Path(__file__).resolve().parents[1] / "bin" / "px-hospital-store"


def command(env: dict[str, str], *args: str):
    p = subprocess.run(
        [sys.executable, str(STORE), *args, "--json"],
        env=env, capture_output=True, text=True, timeout=25,
    )
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return json.loads(p.stdout)


with tempfile.TemporaryDirectory(prefix="px-hospital-unprotected-writer-") as tmp:
    directory = Path(tmp) / "hospital"
    database = directory / "hospital.db"
    env = dict(os.environ, PX_HOSPITAL_DATA_DIR=str(directory))
    env.pop("PX_HOSPITAL_DB", None)
    assert command(env, "status")["schema_version"] == 12

    room_id = "disposable-boundary-witness"
    command(env, "room-bind", room_id, "--repository", "fixture/repository")
    before = command(env, "room-lifecycle-review", room_id)
    assert before["state"] == "ACTIVE" and before["revision"] == 0

    # Independent same-UID connection; the PX signed-grant CLI is not used.
    # This does NOT touch a user's Room, database, process or permissions.
    with sqlite3.connect(database) as direct:
        direct.execute("PRAGMA foreign_keys = ON")
        direct.execute(
            "INSERT INTO room_lifecycle "
            "(room_id, state, revision, frozen_digest) "
            "VALUES (?, 'TRASHED', 1, ?)",
            (room_id, before["digest"]),
        )

    assert room_id not in {x["id"] for x in command(env, "rooms")}
    assert room_id in {x["roomId"] for x in command(env, "room-lifecycle-bin")}
    with sqlite3.connect(database) as direct:
        receipts = direct.execute(
            "SELECT COUNT(*) FROM room_lifecycle_receipts WHERE room_id=?",
            (room_id,),
        ).fetchone()[0]
        approvals = direct.execute(
            "SELECT COUNT(*) FROM room_lifecycle_authorizations WHERE room_id=?",
            (room_id,),
        ).fetchone()[0]
        assert receipts == approvals == 0
        # Restore without a signature is also possible through direct SQL.
        direct.execute("DELETE FROM room_lifecycle WHERE room_id=?", (room_id,))

    assert room_id in {x["id"] for x in command(env, "rooms")}
    assert not command(env, "room-lifecycle-bin")

print(
    "RISK CONFIRMED (disposable only): a same-UID SQLite peer bypasses "
    "the signed Room lifecycle CLI; protected native writer REQUIRED"
)
