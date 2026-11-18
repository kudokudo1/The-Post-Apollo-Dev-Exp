#!/usr/bin/env python3
"""PX Room v12: end-to-end recoverable soft Trash/Restore on disposable DBs.

Uses the actual px hospital CLI, never the operator's Hospital data directory.
No installation, production activation, provider launch or Burn operation.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
PX = ROOT / "bin" / "px"
STORE = ROOT / "bin" / "px-hospital-store"

def invoke(env, *args, good=True):
    result = subprocess.run(
        [str(PX), "hospital", *args, "--json"],
        env=env, capture_output=True, text=True, timeout=25,
    )
    if good:
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return json.loads(result.stdout)
    assert result.returncode != 0, (args, result.stdout, result.stderr)
    return result.stderr

def act(env, room_id, action, witness=None, good=True):
    w = witness or invoke(env, "room-lifecycle-review", room_id)
    return invoke(env, "room-lifecycle-"+action, room_id,
                  "--expected-revision", str(w["revision"]),
                  "--expected-digest", w["digest"],
                  "--confirm-room-id", room_id, good=good)

with tempfile.TemporaryDirectory(prefix="px-room-lifecycle-v12-") as tmp:
    folder = Path(tmp)
    data = folder / "hospital"
    data.mkdir(mode=0o700)
    db_path = data / "hospital.db"
    env = dict(os.environ, PX_HOSPITAL_DATA_DIR=str(data))

    # A real pre-existing v11 database must migrate without losing records.
    # The v11 code is stacked from PR #121; seed using its exact SQL.
    schema_namespace = {"__file__": str(STORE), "__name__": "px_store_test"}
    source = STORE.read_text()
    exec(compile(source.split("def hospital_data_dir()")[0],str(STORE),"exec"),
         schema_namespace)
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        for n in range(1, 11):
            db.executescript(schema_namespace["SCHEMA_V"+str(n)])
        db.execute("ALTER TABLE rooms ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        db.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','11')")
        db.execute("INSERT INTO patients(patient_id,repository) VALUES('p','example/repo')")
        for room in ("empty", "history", "busy", "contract", "cross"):
            db.execute("INSERT INTO rooms(room_id,patient_id) VALUES(?,'p')",(room,))
        db.execute(
            "INSERT INTO sessions(session_id,room_id,status,ended_at) "
            "VALUES('s-old','history','COMPLETE','2026-11-11')"
        )
        db.execute(
            "INSERT INTO messages(room_id,session_id,author_role,direction,body_md) "
            "VALUES('history','s-old','DOCTOR','incoming','SENSITIVE_MESSAGE')"
        )
        db.execute(
            "INSERT INTO room_reports(room_id,body_md) VALUES('history','SENSITIVE_REPORT')"
        )
        db.execute(
            "INSERT INTO session_events(session_id,event_type,payload_json) "
            "VALUES('s-old','turn.completed','{}')"
        )
        db.execute(
            "INSERT INTO sessions(session_id,room_id,status) "
            "VALUES('s-busy','busy','WAITING')"
        )
        db.execute(
            "INSERT INTO assignments(room_id,status,goal_md,title) "
            "VALUES('contract','ACTIVE','GOAL','IN PROGRESS')"
        )
        db.execute(
            "INSERT INTO chart_entries(scope_type,room_id,source_room_id,body_md) "
            "VALUES('ROOM','empty','cross','DEPENDENCY')"
        )
        db.commit()

    status = invoke(env,"status")
    assert status["schema_version"] == 12, status
    with sqlite3.connect(db_path) as db:
        assert db.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='trigger' AND name LIKE 'room_lifecycle_hold_%'"
        ).fetchone()[0] >= 27

    before = invoke(env,"room-lifecycle-review","history")
    assert before["canTrash"] and before["relatedCounts"]["messages"]==1, before
    assert "SENSITIVE_MESSAGE" not in json.dumps(before)
    assert act(env,"history","trash")["state"]=="TRASHED"
    assert "history" not in [r["id"] for r in invoke(env,"rooms")]
    trash_bin = invoke(env,"room-lifecycle-bin")
    assert len(trash_bin)==1 and trash_bin[0]["roomId"]=="history",trash_bin
    assert "SENSITIVE_" not in json.dumps(trash_bin),trash_bin
    assert invoke(env,"room","history")["lifecycleState"]=="TRASHED"

    # Every writer, including a legacy direct SQL connection, must refuse
    # changes to the exact trashed original. It is never physically deleted.
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        rejected = (
            "UPDATE rooms SET team='changed' WHERE room_id='history'",
            "DELETE FROM rooms WHERE room_id='history'",
            "UPDATE messages SET body_md='changed' WHERE room_id='history'",
            "INSERT INTO messages(room_id,author_role,direction,body_md) "
                "VALUES('history','operator','incoming','late')",
            "INSERT INTO session_events(session_id,event_type) "
                "VALUES('s-old','turn.started')",
            "UPDATE sessions SET status='FAILED' WHERE session_id='s-old'",
            "INSERT INTO room_reports(room_id,body_md) "
                "VALUES('history','late report')",
        )
        for sql in rejected:
            try:
                db.execute(sql)
                raise AssertionError("WRITE ALLOWED TO TRASHED ROOM "+sql)
            except sqlite3.IntegrityError as e:
                assert "TRASHED_ROOM" in str(e),str(e)
        db.rollback()

    failed = act(env,"history","restore",
                 {**before,"revision":0},good=False)
    assert "STALE_ROOM_REVISION" in failed,failed
    restored = act(env,"history","restore")
    assert restored["state"]=="ACTIVE"
    assert "history" in [r["id"] for r in invoke(env,"rooms")]
    assert invoke(env,"room-lifecycle-bin")==[]
    with sqlite3.connect(db_path) as db:
        assert db.execute(
            "SELECT body_md FROM messages WHERE room_id='history'"
        ).fetchone()[0]=="SENSITIVE_MESSAGE"
        assert db.execute(
            "SELECT count(*) FROM room_lifecycle_receipts WHERE room_id='history'"
        ).fetchone()[0]==2

    for room in ("busy","contract","cross"):
        detail=invoke(env,"room-lifecycle-review",room)
        assert detail["blockers"],room
        assert "ROOM_NOT_ELIGIBLE_FOR_TRASH" in act(
            env,room,"trash",detail,good=False
        )

    # Exact Room ID, exact revision and current Room graph are required.
    empty=invoke(env,"room-lifecycle-review","empty")
    assert empty["revision"]==0
    wrong=invoke(env,"room-lifecycle-trash","empty",
                 "--expected-revision","0",
                 "--expected-digest",empty["digest"],
                 "--confirm-room-id","history",good=False)
    assert "EXACT_ROOM_CONFIRMATION_REQUIRED" in wrong,wrong
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE rooms SET team='edited' WHERE room_id='empty'")
        db.commit()
    assert "ROOM_GRAPH_CHANGED" in act(
        env,"empty","trash",empty,good=False
    )
    empty=invoke(env,"room-lifecycle-review","empty")
    assert act(env,"empty","trash",empty)["state"]=="TRASHED"
    assert "STALE_ROOM_REVISION" in act(
        env,"empty","trash",empty,good=False
    )

    # Concurrent requests using the same revision: exactly one transitions.
    first=invoke(env,"room-lifecycle-review","empty")
    assert act(env,"empty","restore",first)["state"]=="ACTIVE"
    next_witness=invoke(env,"room-lifecycle-review","empty")
    def race(_):
        r=subprocess.run([str(PX),"hospital","room-lifecycle-trash","empty",
            "--expected-revision",str(next_witness["revision"]),
            "--expected-digest",next_witness["digest"],
            "--confirm-room-id","empty","--json"],
            env=env,capture_output=True,text=True,timeout=30)
        return r.returncode
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(race,range(2)))
    assert sorted(outcomes)==[0,1],outcomes
    assert len([r for r in invoke(env,"room-lifecycle-bin")
                if r["roomId"]=="empty"])==1

    # A dead connection before COMMIT must not leave an orphan state/receipt.
    crash_script = """
import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1],isolation_level=None)
c.execute("PRAGMA journal_mode=WAL")
c.execute("BEGIN IMMEDIATE")
c.execute("UPDATE room_lifecycle SET revision=999 WHERE room_id='empty'")
c.execute("INSERT INTO room_lifecycle_receipts(room_id,action,"
          "revision_before,revision_after,graph_digest) "
          "VALUES('empty','TRASH',2,999,?)",(sys.argv[2],))
os._exit(75)
"""
    prior=invoke(env,"room-lifecycle-review","empty")
    proc=subprocess.run([sys.executable,"-c",crash_script,
                         str(db_path),prior["digest"]],timeout=10)
    assert proc.returncode==75,proc
    again=invoke(env,"room-lifecycle-review","empty")
    assert again["revision"]==prior["revision"],again
    with sqlite3.connect(db_path) as db:
        assert db.execute(
            "SELECT count(*) FROM room_lifecycle_receipts "
            "WHERE room_id='empty' AND revision_after=999"
        ).fetchone()[0]==0

    # Permanent Burn remains absent from the CLI.
    assert "invalid choice" in invoke(env,"room-lifecycle-burn",
                                     good=False).lower()

print("PX HOSPITAL ROOM LIFECYCLE V12 // PASS // real disposable DB, restore, writer fences, stale/concurrent/crash refusal, no Burn")
