#!/usr/bin/env python3
"""Hospital Room naming: v10 migration, identity invariance, and reset.

Uses temporary SQLite storage and subprocesses only. Never accesses the
operator's Hospital database or any provider session.
"""
import json
import os
from pathlib import Path
import runpy
import sqlite3
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "bin" / "px-hospital-store"
PX = ROOT / "bin" / "px"
spec = runpy.run_path(str(STORE))


def invoke(env, *args, successful=True):
    result = subprocess.run(
        [str(PX), "hospital", *args, "--json"],
        text=True, capture_output=True, env=env, timeout=30,
    )
    if successful:
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return json.loads(result.stdout)
    assert result.returncode != 0, (args, result.stdout)
    return result.stderr


with tempfile.TemporaryDirectory(prefix="px-room-name-test-") as tmp:
    home = Path(tmp)
    data_dir = home / "hospital"
    data_dir.mkdir(mode=0o700)
    db_path = data_dir / "hospital.db"
    env = dict(os.environ, PX_HOSPITAL_DATA_DIR=str(data_dir))

    # Seed an actual v10 schema before allowing the v11 binary to open it.
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        for version in range(1, 11):
            conn.executescript(spec[f"SCHEMA_V{version}"])
        conn.execute(
            "INSERT INTO schema_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("schema_version", "10"),
        )
        conn.execute(
            "INSERT INTO rooms(room_id, team, branch, bed_path, doctor_id) "
            "VALUES(?, ?, ?, ?, ?)",
            ("room-one", "T1", "feature/one", "/tmp/isolated-bed", "doctor-one"),
        )
        conn.commit()

    status = invoke(env, "status")
    assert status["schema_version"] == 11, status
    # Keep Assignment title projection bound to the Room's real active contract.
    with sqlite3.connect(db_path) as conn:
        assignment_id = conn.execute(
            "INSERT INTO assignments(room_id, title, goal_md, status) "
            "VALUES(?, ?, ?, ?)",
            ("room-one", "Integrate Company Map", "Map work", "ACTIVE"),
        ).lastrowid
        conn.execute(
            "UPDATE rooms SET current_assignment_id=? WHERE room_id=?",
            (str(assignment_id), "room-one"),
        )
        conn.commit()
    before = invoke(env, "room", "room-one")
    assert before["assignmentTitle"] == "Integrate Company Map", before
    assert before["assignmentStatus"] == "ACTIVE", before
    assert before["assignmentId"] == str(assignment_id), before
    assert before["displayName"] == "", before
    assert before["displayNameInProfile"] == "T1", before
    assert before["doctorId"] == "doctor-one", before

    named = invoke(env, "room-name-set", "room-one", "--name", "Company // Vector Map")
    assert named["displayName"] == "Company // Vector Map", named
    assert named["displayNameInProfile"] == "Company // Vector Map", named
    for key in ("id", "patientId", "team", "branch", "bedPath",
                "doctorId", "providerId", "assignmentId"):
        assert named[key] == before[key], (key, before, named)

    # Normal Room binding must never reset the operator's chosen display name.
    rebound = invoke(env, "room-bind", "room-one",
                     "--repository", "example/company",
                     "--team", "T1", "--branch", "feature/one",
                     "--bed-path", "/tmp/isolated-bed",
                     "--doctor-id", "doctor-one")
    assert rebound["displayName"] == "Company // Vector Map", rebound
    listed = invoke(env, "rooms")
    assert len(listed) == 1 and listed[0]["displayName"] == "Company // Vector Map"
    assert listed[0]["assignmentTitle"] == "Integrate Company Map", listed

    for bad in ("N" * 97, "one\ntwo", "one\tother", "one\x7fother"):
        stderr = invoke(env, "room-name-set", "room-one", "--name", bad,
                        successful=False)
        assert "Room display name" in stderr, stderr
        assert invoke(env, "room", "room-one")["displayName"] == "Company // Vector Map"

    stderr = invoke(env, "room-name-set", "unknown", "--name", "Ghost",
                    successful=False)
    assert "unknown Hospital room" in stderr, stderr
    assert len(invoke(env, "rooms")) == 1

    named96 = invoke(env, "room-name-set", "room-one", "--name", "X" * 96)
    assert len(named96["displayName"]) == 96
    cleared = invoke(env, "room-name-set", "room-one", "--name", "")
    assert cleared["displayName"] == "", cleared
    assert cleared["displayNameInProfile"] == "T1", cleared
    assert cleared["doctorId"] == "doctor-one"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("PRAGMA table_info(rooms)").fetchall()
        assert sum(col[1] == "display_name" for col in row) == 1

print("HOSPITAL ROOM NAME V11 // PASS // legacy migration, identity, persistence, reset, invalid names")
