#!/usr/bin/env python3
"""PX v12 Room Trash/Restore signed-grant source integration, disposable DB.

The real CLI intentionally denies all unsigned requests. Test-only Ed25519
signatures are verified via the source verifier but cannot be supplied as a
CLI trust-anchor override. No user database or native host is touched.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import runpy
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
PX = ROOT / "bin" / "px"
STORE = ROOT / "bin" / "px-hospital-store"
sys.path.insert(0, str(ROOT / "bin"))
import px_hospital_room_lifecycle as life
import px_hospital_room_authority as auth

def invoke(env, *args, good=True):
    p = subprocess.run([str(PX), "hospital", *args, "--json"], env=env,
                       capture_output=True, text=True, timeout=25)
    if good:
        assert p.returncode == 0, (args, p.stdout, p.stderr)
        return json.loads(p.stdout)
    assert p.returncode != 0, (args, p.stdout, p.stderr)
    return p.stderr

def grant(priv, snap, *, room_id, action, revision=None, digest=None,
          nonce=None, approval=None, retention=True, operator="operator-test",
          now=None, patient="p", repository="example/repo"):
    now = int(time.time()) if now is None else now
    body = dict(
        schema=auth.SCHEMA, audience=auth.AUDIENCE, action=action,
        roomId=room_id, patientId=patient, repository=repository,
        expectedRevision=snap["revision"] if revision is None else revision,
        expectedDigest=snap["digest"] if digest is None else digest,
        operatorId=operator, approvalId=approval or "approval-"+secrets.token_hex(12),
        seatId="native-seat-fixture", hostId="native-host-fixture",
        retentionApproved=retention,
        nonce=nonce or auth._b64(os.urandom(32)),
        issuedAt=now, expiresAt=now+40,
    )
    # Fixture signing is ONLY in the test runner. PX has no signing API.
    signature=auth._b64(priv.sign(auth.DOMAIN+auth.canonical(body)))
    raw=auth.canonical({"body":body,"signature":signature})
    return raw

with tempfile.TemporaryDirectory(prefix="px-room-lifecycle-v12-") as tmp:
    root = Path(tmp)
    directory = root / "hospital"
    directory.mkdir(mode=0o700)
    database = directory / "hospital.db"
    env = dict(os.environ, PX_HOSPITAL_DATA_DIR=str(directory))
    # Start on v11, explicitly prove upgrade through the REAL PX command.
    schemas=runpy.run_path(str(STORE),run_name="px_store_fixture_schema")
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        for version in range(1,11):
            db.executescript(schemas["SCHEMA_V"+str(version)])
        db.execute("ALTER TABLE rooms ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        db.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','11')")
        db.execute("INSERT INTO patients(patient_id,repository) VALUES('p','example/repo')")
        for room_id in ("history","empty","busy","contract","cross","other"):
            db.execute("INSERT INTO rooms(room_id,patient_id) VALUES(?,'p')",(room_id,))
        db.execute("INSERT INTO sessions(session_id,room_id,status,ended_at) "
                   "VALUES('old','history','COMPLETE','2026-10-10')")
        db.execute("INSERT INTO messages(room_id,session_id,author_role,direction,body_md) "
                   "VALUES('history','old','DOCTOR','incoming','SENSITIVE_MESSAGE')")
        db.execute("INSERT INTO room_reports(room_id,body_md) "
                   "VALUES('history','SENSITIVE_REPORT')")
        db.execute("INSERT INTO session_events(session_id,event_type,payload_json) "
                   "VALUES('old','turn.completed','{}')")
        db.execute("INSERT INTO sessions(session_id,room_id,status) "
                   "VALUES('running','busy','WAITING')")
        db.execute("INSERT INTO assignments(room_id,status,goal_md) "
                   "VALUES('contract','ACTIVE','goal')")
        db.execute("INSERT INTO chart_entries(scope_type,room_id,source_room_id,body_md) "
                   "VALUES('ROOM','other','cross','DEPENDENCY')")
        db.commit()
    assert invoke(env,"status")["schema_version"]==12
    def conn():
        db=sqlite3.connect(database,isolation_level=None,timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        db.row_factory=sqlite3.Row
        return db
    with conn() as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE "
                          "'room_lifecycle_hold_%' AND type='trigger'").fetchone()[0]>=27
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name="
                          "'room_lifecycle_authorizations'").fetchone()[0]==1

    # CLI does not accept the former unsafe confirm-only command.
    before=invoke(env,"room-lifecycle-review","history")
    assert before["canTrash"] and before["relatedCounts"]["messages"]==1
    assert "SENSITIVE_" not in json.dumps(before)
    raw=invoke(env,"room-lifecycle-trash","history",
        "--expected-revision","0","--expected-digest",before["digest"],
        "--confirm-room-id","history",good=False)
    assert "signed-authorization-file" in raw
    dummy=root/"untrusted-envelope.json"
    dummy.write_text("{}")
    raw=invoke(env,"room-lifecycle-trash","history",
        "--expected-revision","0","--expected-digest",before["digest"],
        "--confirm-room-id","history",
        "--signed-authorization-file",str(dummy),good=False)
    assert "GRANT HOLD" in raw or "HOLD" in raw
    assert invoke(env,"room-lifecycle-bin")==[]

    private=Ed25519PrivateKey.generate()
    key=private.public_key()
    unrelated=Ed25519PrivateKey.generate()
    def authorize(room, action, **overrides):
        with conn() as db:
            snap=life.review(db,room)
        encoded=grant(private,snap,room_id=room,action=action,**overrides)
        verified=auth._verify_bytes(encoded,key)
        return snap,verified,encoded
    def perform(room,action,*,snap=None, verified=None):
        if verified is None:
            snap,verified,_=authorize(room,action)
        with conn() as db:
            return life.transition(db,room,action,snap["revision"],
                       snap["digest"],room,authorization=verified)

    snap,verified,encoded=authorize("history","TRASH")
    frame=json.loads(encoded)
    assert auth._verify_bytes(encoded,key).digest==verified.digest
    for malformed in (
        b'{"body":{},"body":{},"signature":"x"}',
        b'{"body":{},"signature":"x","extra":true}',
        encoded + b"x",
    ):
        try:
            auth._verify_bytes(malformed,key)
            raise AssertionError("MALFORMED SIGNED GRANT ACCEPTED")
        except auth.GrantRefused:
            pass
    try:
        auth._verify_bytes(encoded,unrelated.public_key())
        raise AssertionError("FORGED ISSUER ACCEPTED")
    except auth.GrantRefused:
        pass
    body=dict(frame["body"],action="RESTORE")
    tampered=auth.canonical({"body":body,"signature":frame["signature"]})
    try:
        auth._verify_bytes(tampered,key)
        raise AssertionError("TAMPERED ACTION ACCEPTED")
    except auth.GrantRefused:
        pass
    for illegal in (
        dict(room_id="history",action="TRASH",retention=False),
        dict(room_id="history",action="TRASH",now=int(time.time())-200),
    ):
        temp=grant(private,snap,**illegal)
        try:
            auth._verify_bytes(temp,key)
            raise AssertionError("EXPIRED OR UNRETAINED GRANT ACCEPTED")
        except auth.GrantRefused:
            pass
    with conn() as db:
        try:
            life.transition(db,"history","TRASH",snap["revision"],
                            snap["digest"],"history")
            raise AssertionError("UNSIGNED DIRECT TRANSITION ACCEPTED")
        except life.RoomLifecycleRefused:
            pass
        try:
            life.transition(db,"history","TRASH",snap["revision"],
                            snap["digest"],"history",authorization=True)
            raise AssertionError("UNVERIFIED BOOLEAN ACCEPTED")
        except life.RoomLifecycleRefused:
            pass
    committed=perform("history","TRASH",snap=snap,verified=verified)
    assert committed["state"]=="TRASHED" and committed["operatorAuthenticated"]
    assert "history" not in [x["id"] for x in invoke(env,"rooms")]
    bin_rows=invoke(env,"room-lifecycle-bin")
    assert len(bin_rows)==1 and bin_rows[0]["roomId"]=="history"
    assert not bin_rows[0]["burnAllowed"]
    assert "SENSITIVE_" not in json.dumps(bin_rows)
    assert invoke(env,"room","history")["lifecycleState"]=="TRASHED"
    # Old PX and direct SQLite mutations to this Room fail.
    with conn() as db:
        for sql in (
            "UPDATE rooms SET team='altered' WHERE room_id='history'",
            "DELETE FROM rooms WHERE room_id='history'",
            "UPDATE messages SET body_md='bad' WHERE room_id='history'",
            "INSERT INTO session_events(session_id,event_type) VALUES('old','turn.started')",
            "INSERT INTO room_reports(room_id,body_md) VALUES('history','bad')",
        ):
            try:
                db.execute(sql)
                raise AssertionError("TRASHED ROOM WRITER SUCCEEDED "+sql)
            except sqlite3.IntegrityError as e:
                assert "TRASHED_ROOM" in str(e)
        assert db.execute("SELECT body_md FROM messages WHERE room_id='history'").fetchone()[0]=="SENSITIVE_MESSAGE"
    restored=perform("history","RESTORE")
    assert restored["state"]=="ACTIVE"
    assert "history" in [x["id"] for x in invoke(env,"rooms")]
    assert invoke(env,"room-lifecycle-bin")==[]
    with conn() as db:
        assert db.execute("SELECT count(*) FROM room_lifecycle_receipts "
                          "WHERE room_id='history'").fetchone()[0]==2
        assert db.execute("SELECT count(*) FROM room_lifecycle_authorizations "
                          "WHERE room_id='history'").fetchone()[0]==2

    # Snapshot stale between review and transactional consumption.
    orig, signed,_=authorize("empty","TRASH")
    with conn() as db:
        db.execute("UPDATE rooms SET team='changed' WHERE room_id='empty'")
    try:
        perform("empty","TRASH",snap=orig,verified=signed)
        raise AssertionError("STALE GRAPH ACCEPTED")
    except life.RoomLifecycleRefused as e:
        assert "ROOM_GRAPH_CHANGED" in str(e)
    with conn() as db:
        assert db.execute("SELECT count(*) FROM room_lifecycle_authorizations "
                          "WHERE room_id='empty'").fetchone()[0]==0
    # Live/unclosed work and cross-Room dependencies refuse, without nonce.
    for room in ("busy","contract","cross"):
        snap,verified,_=authorize(room,"TRASH")
        assert snap["blockers"],room
        try:
            perform(room,"TRASH",snap=snap,verified=verified)
            raise AssertionError("BUSY ROOM TRASH ACCEPTED "+room)
        except life.RoomLifecycleRefused as e:
            assert "ROOM_NOT_ELIGIBLE_FOR_TRASH" in str(e)
    with conn() as db:
        assert db.execute("SELECT count(*) FROM room_lifecycle_authorizations "
                          "WHERE room_id IN ('busy','contract','cross')").fetchone()[0]==0

    # Crash/receipt failure must roll back Room state AND consumed approval.
    snap,verified,_=authorize("empty","TRASH")
    with conn() as db:
        db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON "
                   "room_lifecycle_receipts BEGIN SELECT RAISE(ABORT,'TEST_CRASH'); END")
        try:
            life.transition(db,"empty","TRASH",snap["revision"],snap["digest"],
                            "empty",authorization=verified)
            raise AssertionError("CRASH REFUSAL MISSING")
        except sqlite3.IntegrityError as e:
            assert "TEST_CRASH" in str(e)
        assert db.execute("SELECT count(*) FROM room_lifecycle_authorizations "
                          "WHERE room_id='empty'").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM room_lifecycle WHERE room_id='empty'").fetchone()[0]==0
        db.execute("DROP TRIGGER fail_receipt")
    # Same grant is now usable, since failed transaction was atomic.
    first=perform("empty","TRASH",snap=snap,verified=verified)
    assert first["revision"]==1
    with conn() as db:
        assert db.execute("SELECT count(*) FROM room_lifecycle_authorizations "
                          "WHERE room_id='empty'").fetchone()[0]==1
    perform("empty","RESTORE")
    # Reusing a nonce on a later fresh revision is refused even with a
    # different signed grant; approval consumption never forks on replay.
    snap,_,_=authorize("empty","TRASH")
    reused=grant(private,snap,room_id="empty",action="TRASH",
                 nonce=verified.body["nonce"])
    duplicate=auth._verify_bytes(reused,key)
    with conn() as db:
        try:
            life.transition(db,"empty","TRASH",snap["revision"],snap["digest"],
                            "empty",authorization=duplicate)
            raise AssertionError("REPLAYED NONCE SUCCEEDED")
        except auth.GrantRefused as e:
            assert "REPLAYED_APPROVAL" in str(e)
        assert life.review(db,"empty")["state"]=="ACTIVE"
    # A replayed approvalId with new nonce is also refused.
    duplicate=auth._verify_bytes(grant(private,snap,room_id="empty",
        action="TRASH",approval=verified.body["approvalId"]),key)
    with conn() as db:
        try:
            life.transition(db,"empty","TRASH",snap["revision"],snap["digest"],
                            "empty",authorization=duplicate)
            raise AssertionError("REPLAYED APPROVAL ID SUCCEEDED")
        except auth.GrantRefused:
            pass
    assert "invalid choice" in invoke(env,"room-lifecycle-burn",good=False).lower()

print("PX ROOM V12 SIGNED AUTH // PASS // old CLI denied, pinned-signature fixture, atomic grant+receipt, Replay, Restore, Burn hold")
