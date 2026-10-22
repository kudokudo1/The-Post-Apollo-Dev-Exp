#!/usr/bin/env python3
"""INT1-B4: detached fake-only continuity-epoch mutation proof.

In the disposable INT1-P1 Hospital database only, add source-owned triggers
for required HANDOFF reports and ACTIVE operator-authored Room/Patient Charts.
The triggers revoke synthetic B1 Room epochs in the SAME SQLite transaction as
the underlying Hospital mutation.

NOT a trusted context digest. B3 turn acceptance does NOT yet enforce this B4
manifest. No broker, provider/tool execution, real Fedora or live Hospital.
"""
import argparse
import json
import sqlite3
from px_int1_fake_atomic import connect, require_id, validate_live, authority_row
from px_int1_fake_epoch import verify_hooks as verify_b2

PREFIX = "int1_b4_"
VERSION = 1

# Update only substantive continuity inputs, not bookkeeping timestamps.
REPORT_COLUMNS = (
    "room_id", "session_id", "checkpoint_id", "source_message_id",
    "doctor_id", "provider_id", "assignment_id", "report_kind", "title",
    "body_md", "repository", "bed_path", "branch", "head_sha",
    "git_evidence_status", "dirty", "changed_files_json",
    "changed_file_count", "insertions", "deletions",
)
CHART_COLUMNS = (
    "scope_type", "patient_id", "room_id", "entry_kind", "title",
    "body_md", "priority", "status", "author_role", "author_id",
    "source_type", "source_ref", "source_room_id", "source_session_id",
    "source_message_id", "source_checkpoint_id", "source_report_id",
    "supersedes_entry_id", "superseded_by_entry_id",
)

def handoff(alias):
    return "UPPER(TRIM(" + alias + ".report_kind))='HANDOFF'"

def approved(alias):
    return ("UPPER(TRIM(" + alias + ".status))='ACTIVE' AND "
            "LOWER(TRIM(" + alias + ".author_role))='operator'")

def changed(columns):
    return "(" + " OR ".join(
        "OLD." + key + " IS NOT NEW." + key for key in columns
    ) + ")"

def report_rooms(kind):
    if kind == "insert":
        return "room_id=NEW.room_id"
    if kind == "delete":
        return "room_id=OLD.room_id"
    # The old and new affected Rooms both revoke even if one ceases to
    # carry the HANDOFF, e.g., report kind or Room target is reassigned.
    return "room_id IN (OLD.room_id, NEW.room_id)"

def chart_rooms(kind):
    aliases = (("NEW",) if kind == "insert" else
               ("OLD",) if kind == "delete" else ("OLD", "NEW"))
    selects = []
    for alias in aliases:
        selects.append(
            "SELECT room_id FROM rooms WHERE "
            + approved(alias)
            + " AND (("
            + alias + ".scope_type='ROOM' AND room_id=" + alias + ".room_id)"
            + " OR (" + alias + ".scope_type='PATIENT' AND patient_id="
            + alias + ".patient_id))"
        )
    return "room_id IN (" + " UNION ".join(selects) + ")"

EXPECTED = {}
for kind in ("insert", "update", "delete"):
    clause = "AFTER " + kind.upper()
    name = PREFIX + "handoff_" + kind + "_v1"
    when = (
        handoff("NEW") if kind == "insert" else
        handoff("OLD") if kind == "delete" else
        "(" + handoff("OLD") + " OR " + handoff("NEW") + ") AND "
        + changed(REPORT_COLUMNS)
    )
    EXPECTED[name] = (
        "CREATE TRIGGER " + name + " " + clause
        + " ON room_reports WHEN " + when
        + " BEGIN UPDATE int1_fake_authority SET generation=generation+1,"
        + " revoked=1 WHERE " + report_rooms(kind) + "; END"
    )
    name = PREFIX + "chart_" + kind + "_v1"
    when = (
        approved("NEW") if kind == "insert" else
        approved("OLD") if kind == "delete" else
        "(" + approved("OLD") + " OR " + approved("NEW") + ") AND "
        + changed(CHART_COLUMNS)
    )
    EXPECTED[name] = (
        "CREATE TRIGGER " + name + " " + clause
        + " ON chart_entries WHEN " + when
        + " BEGIN UPDATE int1_fake_authority SET generation=generation+1,"
        + " revoked=1 WHERE " + chart_rooms(kind) + "; END"
    )

def verify_b4(conn):
    rows = conn.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
        "AND name LIKE 'int1_b4_%'"
    ).fetchall()
    installed = {row["name"]: row["sql"] for row in rows}
    if set(installed) != set(EXPECTED):
        raise RuntimeError("INT1-B4 REFUSED // missing or unexpected continuity hooks")
    if any(installed[name] != sql for name, sql in EXPECTED.items()):
        raise RuntimeError("INT1-B4 REFUSED // changed continuity hook definition")
    return True

def install(conn, room_id, session_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        verify_b2(conn)  # B4 depends on the accepted B2 manifest.
        validate_live(conn, room_id, session_id)
        auth = authority_row(conn, room_id)
        if auth["revoked"]:
            raise RuntimeError("INT1-B4 REFUSED // revoked Room cannot rearm")
        existing = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'int1_b4_%' LIMIT 1"
        ).fetchone()
        if existing:
            verify_b4(conn)
            raise RuntimeError("INT1-B4 REFUSED // already installed")
        for sql in EXPECTED.values():
            conn.execute(sql)
        verify_b4(conn)
        # All already bootstrapped, valid snapshots predate the global hooks.
        # Invalidate them atomically. Do not change revoked authority rows.
        conn.execute(
            "UPDATE int1_fake_authority SET generation=generation+1 "
            "WHERE revoked=0"
        )
        auth = authority_row(conn, room_id)
        conn.commit()
        return {"installed": True, "hookCount": len(EXPECTED),
                "hookVersion": VERSION, "roomId": room_id,
                "generation": auth["generation"], "revoked": bool(auth["revoked"])}
    except BaseException:
        conn.rollback()
        raise

def inspect(conn, room_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        verify_b2(conn)
        verify_b4(conn)
        row = authority_row(conn, room_id)
        conn.commit()
        return {"installed": True, "hookCount": len(EXPECTED),
                "hookVersion": VERSION, "roomId": room_id,
                "generation": row["generation"], "revoked": bool(row["revoked"])}
    except BaseException:
        conn.rollback()
        raise

def main():
    parser = argparse.ArgumentParser(description="INT1-B4 disposable continuity hooks")
    parser.add_argument("command", choices=("install", "inspect"))
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--session-id")
    args = parser.parse_args()
    try:
        room_id = require_id(args.room_id, "Room ID")
        if args.command == "install" and not args.session_id:
            raise RuntimeError("INT1-B4 REFUSED // session ID required")
        session_id = require_id(args.session_id, "session ID") if args.session_id else ""
        with connect() as conn:
            result = (install(conn, room_id, session_id)
                      if args.command == "install" else inspect(conn, room_id))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RuntimeError, sqlite3.Error, OSError, ValueError) as exc:
        import sys
        print("px INT1 fake continuity: " + str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
