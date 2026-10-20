#!/usr/bin/env python3
"""INT1-B2: fake-only durable authority-mutation hook proof.

This installer runs ONLY in the accepted disposable INT1-P1 Bubblewrap mount.
It installs versioned SQLite triggers on the synthetic Hospital database so
ordinary independent 'px hospital' Room/Session/Assignment/Doctor mutations
revoke the synthetic room's epoch in that SAME SQLite transaction.

Boundaries: No installed Fedora DB, no production schema migration, no
privileged role/actor authentication, no tamper-proof same-UID DB ownership,
no real broker readiness/dispatch or process termination, and NO full INT1-B
acceptance. B1's detached accept CLI does not yet *require* hook presence;
later execution integration must enforce it at acceptance/dispatch.
"""
import argparse
import json
import sqlite3
import sys
from px_int1_fake_atomic import connect, require_id, validate_live, authority_row

# Fixed source-owned trigger definitions. No identifier is user-controlled.
# The column lists intentionally exclude updated_at-only bookkeeping.
COLUMNS = {
    "rooms": ("room_id","patient_id","team","branch","bed_path",
              "doctor_id","provider_id","current_assignment_id"),
    "sessions": ("room_id","doctor_id","provider_id","status",
                 "provider_session_id","working_directory","active_pid",
                 "turn_started_at","ended_at"),
    "assignments": ("room_id","patient_id","goal_md","constraints_md",
                    "definition_done_md","permissions_json","phase","status",
                    "source_session_id"),
    "doctors": ("doctor_id","role","status"),
}
TABLES = ("rooms","sessions","assignments","doctors")
HOOK_VERSION = 1
EXPECTED = {}

def predicate(table):
    return " OR ".join("OLD.%s IS NOT NEW.%s" % (c,c) for c in COLUMNS[table])

def invalidation(table, kind):
    # The doctor registry applies to every Room registered to this Doctor.
    if table == "doctors":
        key = ("NEW.doctor_id" if kind == "insert" else "OLD.doctor_id"
               if kind == "delete" else "OLD.doctor_id, NEW.doctor_id")
        return ("UPDATE int1_fake_authority SET generation=generation+1, "
                "revoked=1 WHERE room_id IN "
                "(SELECT room_id FROM rooms WHERE doctor_id IN ("+key+"));")
    key = ("NEW.room_id" if kind == "insert" else "OLD.room_id"
           if kind == "delete" else "OLD.room_id, NEW.room_id")
    return ("UPDATE int1_fake_authority SET generation=generation+1, "
            "revoked=1 WHERE room_id IN ("+key+");")

for table in TABLES:
    for kind in ("insert","update","delete"):
        name = "int1_b2_%s_%s_v1" % (table, kind)
        clause = ("AFTER UPDATE OF "+", ".join(COLUMNS[table]) if kind == "update"
                  else "AFTER "+kind.upper())
        when = " WHEN "+predicate(table) if kind == "update" else ""
        # sqlite_master stores the complete statement as written.
        EXPECTED[name] = (
            "CREATE TRIGGER "+name+" "+clause+" ON "+table+when+" BEGIN "
            +invalidation(table,kind)+" END"
        )

def verify_hooks(conn):
    rows=conn.execute(
        "SELECT name,sql FROM sqlite_master "
        "WHERE type='trigger' AND name LIKE 'int1_b2_%'"
    ).fetchall()
    installed={row["name"]:row["sql"] for row in rows}
    if set(installed) != set(EXPECTED):
        raise RuntimeError("INT1-B2 REFUSED // incomplete or unexpected hook set")
    if any(installed[name] != sql for name,sql in EXPECTED.items()):
        raise RuntimeError("INT1-B2 REFUSED // changed authority trigger definition")
    return True

def install(conn,room_id,session_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        validate_live(conn,room_id,session_id)
        auth=authority_row(conn,room_id)
        if auth["revoked"]:
            raise RuntimeError("INT1-B2 REFUSED // revoked room cannot rearm")
        existing=conn.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'int1_b2_%'"
        ).fetchall()
        if existing:
            verify_hooks(conn)
            raise RuntimeError("INT1-B2 REFUSED // already installed")
        for sql in EXPECTED.values():
            conn.execute(sql)
        verify_hooks(conn)
        # Invalidate ALL prior detached B1 generation snapshots at install.
        # This does not rearm a previously revoked Room.
        conn.execute(
            "UPDATE int1_fake_authority SET generation=generation+1 "
            "WHERE room_id=? AND revoked=0",(room_id,)
        )
        auth=authority_row(conn,room_id)
        conn.commit()
        return {"installed":True,"hookVersion":HOOK_VERSION,
                "hookCount":len(EXPECTED),"roomId":room_id,
                "generation":auth["generation"],"revoked":bool(auth["revoked"])}
    except BaseException:
        conn.rollback()
        raise

def inspect(conn,room_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        verify_hooks(conn)
        auth=authority_row(conn,room_id)
        conn.commit()
        return {"installed":True,"hookCount":len(EXPECTED),
                "hookVersion":HOOK_VERSION,"roomId":room_id,
                "generation":auth["generation"],"revoked":bool(auth["revoked"])}
    except BaseException:
        conn.rollback()
        raise

def main():
    p=argparse.ArgumentParser(description="INT1-B2 disposable SQL hook proof")
    p.add_argument("command",choices=("install","inspect"))
    p.add_argument("--room-id",required=True)
    p.add_argument("--session-id")
    a=p.parse_args()
    try:
        room=require_id(a.room_id,"Room ID")
        if a.command=="install" and not a.session_id:
            raise RuntimeError("INT1-B2 REFUSED // session ID required")
        session=require_id(a.session_id,"session ID") if a.session_id else ""
        with connect() as conn:
            result=(install(conn,room,session) if a.command=="install"
                    else inspect(conn,room))
        print(json.dumps(result,sort_keys=True))
        return 0
    except (RuntimeError,sqlite3.Error,OSError,ValueError) as exc:
        print("px INT1 fake epoch: "+str(exc),file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
