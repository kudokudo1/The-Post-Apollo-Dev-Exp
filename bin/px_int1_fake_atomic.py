#!/usr/bin/env python3
"""EXEC-S3 INT1-B1: fake-only, detached atomic Hospital storage PROOF.

This is a deliberately separate source-owned CLI, not the Doctor dispatch
path. It must execute inside the accepted, disposable INT1-P1 mount namespace.
Only the inert int1-fake provider is supported. An existing schema-v10
synthetic Hospital DB is required; there is NO live DB migration.

IMPORTANT: B1 accept requires the exact B2 (12) and B4 (6) source-owned
triggers, and a matching SHA-256 digest recomputed from synthetic Room HANDOFF
and ACTIVE operator Chart rows INSIDE the same BEGIN IMMEDIATE transaction.
This is still detached fake-only storage. The underlying author-role fields
and SQLite files are not authenticated against same-UID tampering; this is
not a production context protocol, executable broker grant or full INT1-B.
"""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

from px_int1_fake_guard import require_fixture, require_profile, FAKE_ID, PROFILE

DATABASE_URI = "file:/fixture/hospital/data/hospital.db?mode=rw"
TABLES = """
CREATE TABLE IF NOT EXISTS int1_fake_authority (
    room_id TEXT PRIMARY KEY REFERENCES rooms(room_id),
    generation INTEGER NOT NULL CHECK(generation > 0),
    revoked INTEGER NOT NULL CHECK(revoked IN (0, 1))
);
CREATE TABLE IF NOT EXISTS int1_fake_accepted_turns (
    turn_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    generation INTEGER NOT NULL,
    request_hash TEXT NOT NULL,
    message_id INTEGER NOT NULL REFERENCES messages(message_id),
    context_event_id INTEGER NOT NULL REFERENCES session_events(event_id),
    started_event_id INTEGER NOT NULL REFERENCES session_events(event_id),
    state TEXT NOT NULL CHECK(state IN ('ACCEPTED_UNDISPATCHED', 'FAILED'))
);
"""
def connect():
    # MUST run before sqlite3.connect, which otherwise can open the host DB.
    require_fixture()
    # Do not accept a fake database identity with a command-bearing or
    # unexpected provider registry. Exact inert profile only, as in Stage A.
    try:
        registry = json.loads(Path("/fixture/providers/fake.json").read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError("INT1-B1 REFUSED // unreadable synthetic provider registry") from exc
    record = registry.get("providers", {}).get(FAKE_ID) if isinstance(registry, dict) and isinstance(registry.get("providers"), dict) else None
    require_profile(FAKE_ID, record, registry)
    conn = sqlite3.connect(DATABASE_URI, uri=True, isolation_level=None, timeout=8)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 8000")
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None or row["value"] != "10":
        conn.close()
        raise RuntimeError("INT1-B1 REFUSED // expected disposable Hospital v10")
    return conn

def require_id(value, field):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", value or ""):
        raise RuntimeError("INT1-B1 REFUSED // invalid " + field)
    return value

def create_tables(conn):
    # The synthetic extension is NOT a global Hospital schema migration.
    # Never create it unless operating inside an OS-verified INT1 fixture.
    conn.executescript(TABLES)

def authority_row(conn, room_id):
    row = conn.execute(
        "SELECT * FROM int1_fake_authority WHERE room_id=?", (room_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError("INT1-B1 REFUSED // authority was not bootstrapped")
    return row

def validate_live(conn, room_id, session_id):
    row = conn.execute(
        """SELECT s.session_id, s.room_id, s.doctor_id AS session_doctor,
                  s.provider_id AS session_provider, s.status AS session_status,
                  s.working_directory, s.active_pid,
                  r.doctor_id AS room_doctor, r.provider_id AS room_provider,
                  r.bed_path, r.current_assignment_id,
                  a.room_id AS assignment_room, a.status AS assignment_status,
                  a.permissions_json
           FROM sessions s JOIN rooms r ON s.room_id = r.room_id
           LEFT JOIN assignments a
             ON CAST(a.assignment_id AS TEXT) = r.current_assignment_id
           WHERE s.session_id=? AND r.room_id=?""",
        (session_id, room_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("INT1-B1 REFUSED // session-to-Room link absent")
    # Stage A I1 invariant: whitespace-only identity is unresolved, even
    # when both stored Doctor identifiers contain identical whitespace.
    # Nonblank identities must match EXACTLY; do not silently normalize.
    session_doctor = str(row["session_doctor"] or "")
    room_doctor = str(row["room_doctor"] or "")
    if (not session_doctor.strip() or not room_doctor.strip() or
            session_doctor != room_doctor):
        raise RuntimeError("INT1-B1 REFUSED // Doctor-to-Room mismatch")
    if (row["session_provider"] != FAKE_ID or row["room_provider"] != FAKE_ID):
        raise RuntimeError("INT1-B1 REFUSED // native or changed provider")
    if (row["working_directory"] != "/fixture/bed" or
            row["bed_path"] != "/fixture/bed"):
        raise RuntimeError("INT1-B1 REFUSED // changed registered Bed")
    if row["session_status"] not in ("IDLE", "WAITING") or int(row["active_pid"] or 0):
        raise RuntimeError("INT1-B1 REFUSED // Doctor is already operating")
    if (not row["current_assignment_id"] or
            row["assignment_room"] != room_id or row["assignment_status"] != "ACTIVE"):
        raise RuntimeError("INT1-B1 REFUSED // active Room Assignment required")
    try:
        permissions = json.loads(row["permissions_json"])
    except (ValueError, TypeError) as exc:
        raise RuntimeError("INT1-B1 REFUSED // invalid permissions") from exc
    if (not isinstance(permissions, list) or "READ" not in permissions or
            "EDIT" not in permissions):
        raise RuntimeError("INT1-B1 REFUSED // Assignment EDIT not granted")
    return {"doctorId": row["room_doctor"],
            "assignmentId": row["current_assignment_id"]}

def snapshot(conn, room_id, session_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        live = validate_live(conn, room_id, session_id)
        auth = authority_row(conn, room_id)
        if auth["revoked"]:
            raise RuntimeError("INT1-B1 REFUSED // authority revoked")
        generation = auth["generation"]
        conn.commit()
        return {"roomId": room_id, "sessionId": session_id,
                "generation": generation, **live}
    except BaseException:
        conn.rollback()
        raise

def bootstrap(conn, room_id, session_id):
    create_tables(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        validate_live(conn, room_id, session_id)
        conn.execute(
            "INSERT OR IGNORE INTO int1_fake_authority(room_id,generation,revoked) "
            "VALUES(?,1,0)", (room_id,)
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return snapshot(conn, room_id, session_id)

# B5/B6 // Source-derived, deterministic synthetic continuity snapshot.
# Only substantive continuity fields captured by the source-owned B4 hooks
# are included. No LIMIT/ranking truncation, cross-Room joins or caller text.
# Scope classifications match B4 trigger semantics exactly.
def continuity_document(conn, room_id, session_id):
    from px_int1_fake_continuity import REPORT_COLUMNS, CHART_COLUMNS
    parent = conn.execute(
        "SELECT patient_id FROM rooms WHERE room_id=?", (room_id,)
    ).fetchone()
    if parent is None:
        raise RuntimeError("INT1-B6 REFUSED // missing Room for continuity")
    patient_id = parent["patient_id"]
    reports = conn.execute(
        "SELECT report_id, " + ", ".join(REPORT_COLUMNS)
        + " FROM room_reports WHERE room_id=? "
          "AND UPPER(TRIM(report_kind))='HANDOFF' ORDER BY report_id ASC",
        (room_id,)
    ).fetchall()
    charts = conn.execute(
        "SELECT entry_id, " + ", ".join(CHART_COLUMNS)
        + " FROM chart_entries WHERE "
          "UPPER(TRIM(status))='ACTIVE' "
          "AND LOWER(TRIM(author_role))='operator' AND "
          "((scope_type='ROOM' AND room_id=?) OR "
          "(scope_type='PATIENT' AND patient_id=?)) "
          "ORDER BY entry_id ASC",
        (room_id, patient_id)
    ).fetchall()
    return {
        "protocol": "INT1-B6-SYNTHETIC-CONTEXT-v1",
        "roomId": room_id, "sessionId": session_id,
        "patientId": patient_id,
        "handoffs": [dict(row) for row in reports],
        "approvedCharts": [dict(row) for row in charts],
    }

def continuity_hash(conn, room_id, session_id):
    document = continuity_document(conn, room_id, session_id)
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest(), document

def context_digest(conn, room_id, session_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        from px_int1_fake_epoch import verify_hooks
        from px_int1_fake_continuity import verify_b4
        verify_hooks(conn)
        verify_b4(conn)
        validate_live(conn, room_id, session_id)
        auth = authority_row(conn, room_id)
        if auth["revoked"]:
            raise RuntimeError("INT1-B6 REFUSED // authority revoked")
        digest, document = continuity_hash(conn, room_id, session_id)
        conn.commit()
        return {"roomId": room_id, "sessionId": session_id,
                "generation": auth["generation"],
                "contextHash": digest,
                "handoffIds": [str(r["report_id"]) for r in document["handoffs"]],
                "chartIds": [str(r["entry_id"]) for r in document["approvedCharts"]]}
    except BaseException:
        conn.rollback()
        raise

def accept(conn, *, room_id, session_id, turn_id, generation,
           context_hash, body, fail_after=""):
    require_id(turn_id, "turn ID")
    if not re.fullmatch(r"[0-9a-f]{64}", context_hash or ""):
        raise RuntimeError("INT1-B1 REFUSED // invalid context digest")
    if not body.strip():
        raise RuntimeError("INT1-B1 REFUSED // empty synthetic prompt")
    request = json.dumps(
        {"roomId":room_id, "sessionId":session_id, "turnId":turn_id,
         "generation":generation, "contextHash":context_hash,
         "body":body, "profile":PROFILE}, sort_keys=True
    ).encode()
    digest = hashlib.sha256(request).hexdigest()
    conn.execute("BEGIN IMMEDIATE")
    try:
        # B3: verify the EXACT 12 source-owned B2 triggers INSIDE the SAME
        # SQLite write transaction that accepts or replays a turn. A missing,
        # unexpected or modified authority hook fails closed before any
        # message/event/turn mutation. Another writer cannot drop the hooks
        # between this check and this transaction's commit.
        # Local import avoids module import cycles: the epoch CLI reuses B1.
        from px_int1_fake_epoch import verify_hooks
        from px_int1_fake_continuity import verify_b4
        verify_hooks(conn)
        verify_b4(conn)
        live = validate_live(conn, room_id, session_id)
        auth = authority_row(conn, room_id)
        if auth["revoked"] or auth["generation"] != generation:
            raise RuntimeError("INT1-B1 REFUSED // stale or revoked authority")
        actual_hash, _ = continuity_hash(conn, room_id, session_id)
        if context_hash != actual_hash:
            raise RuntimeError("INT1-B6 REFUSED // stale or mismatched continuity digest")
        old = conn.execute(
            "SELECT * FROM int1_fake_accepted_turns WHERE turn_id=?", (turn_id,)
        ).fetchone()
        if old is not None:
            if (old["request_hash"] != digest or old["room_id"] != room_id or
                    old["session_id"] != session_id):
                raise RuntimeError("INT1-B1 REFUSED // turn ID payload conflict")
            conn.commit()
            return {"turnId":turn_id, "generation":generation,
                    "messageId":str(old["message_id"]),
                    "state":old["state"], "replayed":True}
        message = conn.execute(
            """INSERT INTO messages(room_id,session_id,author_role,author_id,
                      direction,message_type,body_md)
               VALUES(?,?,'operator','operator','outgoing','chat',?)""",
            (room_id, session_id, body)
        )
        if fail_after == "message":
            raise RuntimeError("INT1-B1 TEST INJECT // rollback after message")
        context = conn.execute(
            "INSERT INTO session_events(session_id,event_type,payload_json) "
            "VALUES(?,'turn.context',?)",
            (session_id,json.dumps(
                {"turnId":turn_id,"generation":generation,
                 "contextDigest":context_hash,"fakeOnly":True,
                 "assignmentId":live["assignmentId"]}, sort_keys=True))
        )
        if fail_after == "context":
            raise RuntimeError("INT1-B1 TEST INJECT // rollback after context")
        started = conn.execute(
            "INSERT INTO session_events(session_id,event_type,payload_json) "
            "VALUES(?,'turn.started',?)",
            (session_id,json.dumps(
                {"turnId":turn_id,"generation":generation,
                 "operatorMessageId":str(message.lastrowid),
                 "fakeOnly":True,"state":"ACCEPTED_UNDISPATCHED"},
                sort_keys=True))
        )
        if fail_after == "started":
            raise RuntimeError("INT1-B1 TEST INJECT // rollback after started")
        conn.execute(
            """INSERT INTO int1_fake_accepted_turns
               (turn_id,room_id,session_id,generation,request_hash,
                message_id,context_event_id,started_event_id,state)
               VALUES(?,?,?,?,?,?,?,?, 'ACCEPTED_UNDISPATCHED')""",
            (turn_id,room_id,session_id,generation,digest,
             message.lastrowid,context.lastrowid,started.lastrowid)
        )
        conn.execute(
            "UPDATE rooms SET updated_at=CURRENT_TIMESTAMP WHERE room_id=?",
            (room_id,)
        )
        conn.commit()
        return {"turnId":turn_id,"generation":generation,
                "messageId":str(message.lastrowid),
                "state":"ACCEPTED_UNDISPATCHED","replayed":False}
    except BaseException:
        conn.rollback()
        raise

def revoke(conn, room_id, reason):
    if not reason.strip():
        raise RuntimeError("INT1-B1 REFUSED // missing revoke reason")
    conn.execute("BEGIN IMMEDIATE")
    try:
        authority_row(conn, room_id)
        conn.execute(
            "UPDATE int1_fake_authority "
            "SET generation=generation+1, revoked=1 WHERE room_id=?", (room_id,)
        )
        auth = authority_row(conn, room_id)
        conn.commit()
        return {"roomId":room_id,"generation":auth["generation"],
                "revoked":True,"reason":reason,
                "dispatchTerminated":False}
    except BaseException:
        conn.rollback()
        raise

def main():
    parser=argparse.ArgumentParser(description="INT1-B1 disposable atomic store proof")
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("bootstrap","snapshot","revoke","accept","context-digest"):
        p=sub.add_parser(name)
        p.add_argument("--room-id",required=True)
        if name in ("bootstrap","snapshot","accept","context-digest"):
            p.add_argument("--session-id",required=True)
        if name=="revoke":
            p.add_argument("--reason",required=True)
        if name=="accept":
            p.add_argument("--turn-id",required=True)
            p.add_argument("--generation",required=True,type=int)
            p.add_argument("--context-hash",required=True)
            p.add_argument("--body-stdin",action="store_true",required=True)
            p.add_argument("--fail-after",default="",choices=("","message","context","started"))
    args=parser.parse_args()
    try:
        room_id=require_id(args.room_id,"Room ID")
        session_id=require_id(args.session_id,"session ID") if hasattr(args,"session_id") else ""
        with connect() as conn:
            if args.command=="bootstrap":
                result=bootstrap(conn,room_id,session_id)
            elif args.command=="snapshot":
                result=snapshot(conn,room_id,session_id)
            elif args.command=="revoke":
                result=revoke(conn,room_id,args.reason)
            elif args.command=="context-digest":
                result=context_digest(conn,room_id,session_id)
            else:
                result=accept(conn,room_id=room_id,session_id=session_id,
                              turn_id=args.turn_id,generation=args.generation,
                              context_hash=args.context_hash,body=sys.stdin.read(),
                              fail_after=args.fail_after)
        print(json.dumps(result,sort_keys=True))
        return 0
    except (RuntimeError,sqlite3.Error,OSError,ValueError) as exc:
        print("px INT1 fake atomic store: "+str(exc),file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
