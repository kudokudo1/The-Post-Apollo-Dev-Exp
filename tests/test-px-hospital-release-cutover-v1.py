#!/usr/bin/env python3
"""Hospital Trash & Restore // full disposable v10→v11→v12 backup/recovery.

CI-ONLY. Refuses use outside GitHub Actions with RUNNER_TEMP. All SQLite
files are constructed beneath a temporary CI directory. There are NO
arguments and NO access to the desktop Hospital database.

Exercises the REAL PX migration source, retained Room graph records,
WAL-consistent SQLite online backup, recovery, interrupted v11 upgrade,
newer-version refusal and independent release-preflight hold semantics.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile

if not (os.environ.get("GITHUB_ACTIONS")=="true"
        and os.environ.get("CI")=="true"
        and os.environ.get("RUNNER_TEMP")
        and Path(os.environ["RUNNER_TEMP"]).is_dir()):
    raise SystemExit("HOSPITAL_RELEASE_REHEARSAL_HOLD // CI_ONLY")

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"bin"))
import px_hospital_release_preflight as gate
import px_hospital_room_lifecycle as lifecycle

store=runpy.run_path(str(ROOT/"bin"/"px-hospital-store"),
                     run_name="hospital_release_fixture_only")

def db(path: Path, *, wal=False):
    assert path.is_absolute()
    c=sqlite3.connect(str(path),isolation_level=None,timeout=5)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    if wal:
        assert c.execute("PRAGMA journal_mode=WAL").fetchone()[0]=="wal"
        c.execute("PRAGMA wal_autocheckpoint=0")
    return c

def backup(source, target: Path):
    assert not target.exists(), "NEVER_OVERWRITE_A_PREVIOUS_RECOVERY_POINT"
    # WAL-aware snapshot using SQLite's backup API, not file copying.
    with closing(db(target)) as dest:
        source.backup(dest)
        assert dest.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert dest.execute("PRAGMA foreign_key_check").fetchone() is None

def schema_version(c):
    return int(c.execute("SELECT value FROM schema_meta "
                         "WHERE key='schema_version'").fetchone()[0])

def table_columns(c):
    return {name:[str(x[1]) for x in c.execute(
        "PRAGMA table_info("+name+")")]
        for name in gate.TABLES}

def historical_witness(c, columns):
    # Preserve every original field and value, not just summary counts.
    # Data and sensitive Room content NEVER leave this disposable fixture.
    result={}
    for name,original_cols in columns.items():
        select=", ".join('"'+x.replace('"','""')+'"' for x in original_cols)
        values=[tuple(row) for row in
                c.execute("SELECT "+select+" FROM "+name+" ORDER BY rowid")]
        result[name]=values
    raw=json.dumps(result,sort_keys=True,separators=(",",":"),
                   ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

with tempfile.TemporaryDirectory(
    prefix="hospital-cutover-recovery-",
    dir=os.environ["RUNNER_TEMP"]
) as temp:
    root=Path(temp)
    original=root/"hospital-v10-original.db"
    safety=root/"hospital-v10-online-backup.db"
    candidate=root/"hospital-v12-staged.db"
    recovered=root/"hospital-v10-rollback-restored.db"
    interrupted=root/"hospital-v11-interrupted.db"
    future=root/"hospital-v13-refusal.db"
    with closing(db(original,wal=True)) as src:
        for version in range(1,11):
            src.executescript(store["SCHEMA_V"+str(version)])
        src.execute("INSERT INTO schema_meta(key,value) "
                    "VALUES('schema_version','10')")
        src.execute("INSERT INTO patients(patient_id,repository) "
                    "VALUES('patient-fixture','fixture/repo')")
        src.execute("INSERT INTO rooms(room_id,patient_id) "
                    "VALUES('room-one','patient-fixture')")
        src.execute("INSERT INTO rooms(room_id,patient_id) "
                    "VALUES('room-two','patient-fixture')")
        src.execute("INSERT INTO doctors(doctor_id,name) "
                    "VALUES('doc-fixture','Fixture Doctor')")
        src.execute("INSERT INTO sessions(session_id,room_id,status,ended_at) "
                    "VALUES('session-done','room-one','COMPLETE','2026-11-18')")
        src.execute("INSERT INTO session_events(session_id,event_type) "
                    "VALUES('session-done','turn.completed')")
        src.execute("INSERT INTO messages(room_id,session_id,author_role,"
                    "direction,body_md) VALUES("
                    "'room-one','session-done','DOCTOR','incoming','SENSITIVE_MESSAGE')")
        src.execute("INSERT INTO room_checkpoints(room_id,session_id,body_md) "
                    "VALUES('room-one','session-done','SENSITIVE_CHECKPOINT')")
        src.execute("INSERT INTO room_reports(room_id,session_id,body_md) "
                    "VALUES('room-one','session-done','SENSITIVE_REPORT')")
        src.execute("INSERT INTO chart_entries(scope_type,room_id,body_md,status) "
                    "VALUES('ROOM','room-one','SENSITIVE_CHART','ARCHIVED')")
        src.execute("INSERT INTO chart_suggestions("
                    "scope_type,room_id,body_md,status) "
                    "VALUES('ROOM','room-one','SENSITIVE_SUGGESTION','REJECTED')")
        src.execute("INSERT INTO assignments(room_id,patient_id,goal_md,status) "
                    "VALUES('room-one','patient-fixture','SENSITIVE_ASSIGNMENT','COMPLETE')")
        # Explicitly keep an uncheckpointed WAL write. A raw file copy of
        # hospital.db could miss it; SQLite online backup must include it.
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        src.execute("INSERT INTO messages(room_id,session_id,author_role,"
                    "direction,body_md) VALUES("
                    "'room-one','session-done','DOCTOR','outgoing','WAL_ONLY_MESSAGE')")
        assert Path(str(original)+"-wal").exists()
        assert Path(str(original)+"-wal").stat().st_size > 0

        report=gate.inspect_readonly(src)
        assert report["schemaVersion"]==10
        assert report["sourceQuiescenceObserved"] is True
        assert report["approvedToMigrate"] is False
        assert report["externalWritersStopped"] is False
        assert report["verifiedRecoverableBackup"] is False
        assert report["recordCounts"]["messages"]==2
        cols=table_columns(src)
        initial=historical_witness(src,cols)
        backup(src,safety)
        assert schema_version(src)==10

    with closing(db(safety)) as safe:
        assert schema_version(safe)==10
        assert historical_witness(safe,cols)==initial
        assert safe.execute("SELECT body_md FROM messages "
                            "WHERE body_md='WAL_ONLY_MESSAGE'").fetchone()[0] == "WAL_ONLY_MESSAGE"
        backup(safe,candidate)
        backup(safe,recovered)
        backup(safe,interrupted)
        backup(safe,future)

    # Actual source migration is applied ONLY to candidate, never original
    # or its recovery-point snapshot. Preserve all pre-existing values.
    with closing(db(candidate)) as stage:
        assert store["migrate"](stage)==12
        assert schema_version(stage)==12
        assert historical_witness(stage,cols)==initial
        assert stage.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert stage.execute("PRAGMA foreign_key_check").fetchone() is None
        assert gate.inspect_readonly(stage)["schemaVersion"]==12
        assert stage.execute("SELECT count(*) FROM sqlite_master "
                             "WHERE type='trigger' AND name LIKE "
                             "'room_lifecycle_hold_%'").fetchone()[0] >= 27
        room=lifecycle.review(stage,"room-one")
        assert room["state"]=="ACTIVE" and room["revision"]==0
        assert room["canTrash"] is True and room["canBurn"] is False
        assert store["migrate"](stage)==12, "migration must be idempotent"
        assert historical_witness(stage,cols)==initial
        # Source evidence cannot be silently modified after a Room is
        # trashed, even through older SQLite writers. Fixture-only state.
        stage.execute("INSERT INTO room_lifecycle("
                      "room_id,state,revision,frozen_digest)"
                      "VALUES(?,?,?,?)",
                      ("room-one","TRASHED",1,room["digest"]))
        try:
            stage.execute("UPDATE messages SET body_md='CORRUPTED' "
                          "WHERE room_id='room-one'")
            raise AssertionError("TRASHED ROOM WRITE ALLOWED")
        except sqlite3.IntegrityError:
            pass
        # A migration witness is not a live storage activation permit.
        assert gate.inspect_readonly(stage)["approvedToMigrate"] is False

    # A crash after adding the v11 display name column but before
    # advancing schema_meta must resume safely, not ADD COLUMN again.
    with closing(db(interrupted)) as mid:
        mid.execute("ALTER TABLE rooms ADD COLUMN display_name "
                    "TEXT NOT NULL DEFAULT ''")
        assert schema_version(mid)==10
        assert store["migrate"](mid)==12
        assert historical_witness(mid,cols)==initial
        assert mid.execute("PRAGMA foreign_key_check").fetchone() is None

    # Recovery is from verified v10 backup into a DISTINCT path. It
    # restores old records without applying forward migration.
    with closing(db(recovered)) as back:
        assert schema_version(back)==10
        assert historical_witness(back,cols)==initial
        assert "room_lifecycle" not in {
            r[0] for r in back.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        assert back.execute("PRAGMA integrity_check").fetchone()[0]=="ok"

    # A newer source DB must never be silently downgraded or rewritten.
    with closing(db(future)) as future_db:
        future_db.execute("UPDATE schema_meta SET value='13' "
                          "WHERE key='schema_version'")
        try:
            store["migrate"](future_db)
            raise AssertionError("UNREVIEWED_NEWER_SCHEMA_ACCEPTED")
        except RuntimeError as exc:
            assert "newer than PX supports" in str(exc)
        assert schema_version(future_db)==13

    # Read-only preflight must flag live activity without modifying state.
    with closing(db(original)) as insert:
        insert.execute("INSERT INTO sessions(session_id,room_id,status) "
                       "VALUES('session-live','room-two','ACTIVE')")
        insert.execute("INSERT INTO assignments(room_id,goal_md,status) "
                       "VALUES('room-two','in progress','ACTIVE')")
    with closing(db(original)) as check:
        blocked=gate.inspect_readonly(check)
        assert blocked["openSessions"]==1
        assert blocked["activeAssignments"]==1
        assert blocked["sourceQuiescenceObserved"] is False
        assert blocked["approvedToMigrate"] is False

    # Reject corrupt and unexpected schema artifacts before any install.
    with closing(db(future)) as not_reviewed:
        try:
            gate.inspect_readonly(not_reviewed)
            raise AssertionError("SOURCE_VERSION_13_RELEASED")
        except gate.ReleaseHold:
            pass

print("HOSPITAL TRASH/RESTORE RELEASE // PASS // WAL-consistent backup, full history, v10→11→12, interrupted migration, v10 rollback, activity/refusal holds; NO INSTALL")
