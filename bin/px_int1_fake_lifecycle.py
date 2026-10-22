#!/usr/bin/env python3
"""B14 disposable synthetic Doctor lifecycle; no model, provider or host tools.

Only the uninterrupted supervisor that returned from the B13 isolated,
reaped synthetic task may finalize a reply. Orphaned accepted turns and
durable ACKs never auto-execute or silently gain Doctor replies.
"""
import argparse
import json
import sqlite3
import sys

from px_int1_fake_atomic import connect, require_id
from px_int1_fake_dispatch import run, current_authority
from px_int1_fake_epoch import verify_hooks
from px_int1_fake_continuity import verify_b4

RESULT = "SYNTHETIC_SUM_36"
REPLY = "Synthetic Doctor: the fixed sum of integers 1 through 8 is 36."
ACK = "I_ACKNOWLEDGE_INCOMPLETE_SYNTHETIC_TURN_NO_RETRY"
REPLIES = """CREATE TABLE IF NOT EXISTS int1_fake_doctor_replies (
    turn_id TEXT PRIMARY KEY REFERENCES int1_fake_accepted_turns(turn_id),
    message_id INTEGER NOT NULL UNIQUE REFERENCES messages(message_id),
    result TEXT NOT NULL CHECK(result='SYNTHETIC_SUM_36')
)"""


def _table(conn, name):
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _turn(conn, room, session, turn):
    join = ("LEFT JOIN int1_fake_dispatch_receipts r ON r.turn_id=t.turn_id"
            if _table(conn, "int1_fake_dispatch_receipts") else "")
    fields = ("r.state AS receipt_state,r.result AS receipt_result" if join
              else "NULL AS receipt_state,NULL AS receipt_result")
    return conn.execute(
        "SELECT t.*, " + fields + " FROM int1_fake_accepted_turns t " + join +
        " WHERE t.turn_id=? AND t.room_id=? AND t.session_id=?",
        (turn, room, session),
    ).fetchone()


def _reply(conn, turn):
    if not _table(conn, "int1_fake_doctor_replies"):
        return None
    return conn.execute(
        "SELECT message_id,result FROM int1_fake_doctor_replies WHERE turn_id=?",
        (turn,),
    ).fetchone()


def inspect(conn, room, session, turn):
    # Read-only; RESERVED is ambiguous, never proof a supervisor is still alive.
    conn.execute("BEGIN")
    try:
        row = _turn(conn, room, session, turn)
        reply = _reply(conn, turn) if row else None
        cancellation = bool(row and _table(conn, "int1_fake_turn_cancellations") and
            conn.execute(
                "SELECT 1 FROM int1_fake_turn_cancellations "
                "WHERE turn_id=? AND room_id=? AND session_id=?",
                (turn, room, session),
            ).fetchone())
        if row is None:
            state = "NOT_FOUND"
        elif row["state"] == "FAILED" or row["receipt_state"] == "FAILED":
            state = "FAILED"
        elif reply and row["receipt_state"] == "ACKED":
            state = "COMPLETED"
        elif cancellation and row["receipt_state"] == "RESERVED":
            state = "CANCELLATION_REQUESTED"
        elif row["receipt_state"] == "RESERVED":
            state = "DELIVERY_UNCERTAIN"
        elif row["receipt_state"] == "ACKED":
            state = "ACKED_UNFINALIZED"
        elif row["receipt_state"] is None:
            state = "ACCEPTED_UNRESERVED"
        else:
            state = "INCONSISTENT"
        result = {
            "roomId": room, "sessionId": session, "turnId": turn,
            "state": state, "receiptState": row["receipt_state"] if row else None,
            "doctorMessageId": str(reply["message_id"]) if reply else "",
            "needsExplicitRecovery": state in (
                "DELIVERY_UNCERTAIN", "CANCELLATION_REQUESTED",
                "ACKED_UNFINALIZED", "ACCEPTED_UNRESERVED", "INCONSISTENT"),
            "cancellationRequested": cancellation,
            "syntheticSessionStatus": (
                "WAITING" if state == "COMPLETED" else
                "FAILED" if state == "FAILED" else
                "UNRESOLVED" if row else "IDLE"
            ),
            "supervisorLivenessVerified": False,
            "automaticRetryAllowed": False, "syntheticOnly": True,
        }
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise


def finalize_verified(conn, room, session, turn):
    """Only call immediately after run() fully returns and reaps its broker."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        verify_hooks(conn)
        verify_b4(conn)
        row = _turn(conn, room, session, turn)
        if (row is None or row["state"] != "ACCEPTED_UNDISPATCHED" or
                row["receipt_state"] != "ACKED" or
                row["receipt_result"] != RESULT or _reply(conn, turn)):
            raise RuntimeError("INT1-B14 REFUSED // no unfinalized verified result")
        context = conn.execute(
            "SELECT payload_json FROM session_events WHERE event_id=? "
            "AND session_id=? AND event_type='turn.context'",
            (row["context_event_id"], session),
        ).fetchone()
        if context is None:
            raise RuntimeError("INT1-B14 REFUSED // source context missing")
        meta = json.loads(context["payload_json"])
        if meta.get("turnId") != turn or meta.get("generation") != row["generation"]:
            raise RuntimeError("INT1-B14 REFUSED // context identity mismatch")
        current_authority(
            conn, room_id=room, session_id=session,
            generation=row["generation"], digest=meta.get("contextDigest"),
        )
        doctor = conn.execute(
            "SELECT doctor_id FROM sessions WHERE session_id=? AND room_id=?",
            (session, room),
        ).fetchone()
        if doctor is None or not doctor["doctor_id"]:
            raise RuntimeError("INT1-B14 REFUSED // Doctor identity missing")
        conn.execute(REPLIES)
        message = conn.execute(
            """INSERT INTO messages(room_id,session_id,author_role,author_id,
                      direction,message_type,body_md)
               VALUES(?,?,'doctor',?,'incoming','chat',?)""",
            (room, session, doctor["doctor_id"], REPLY),
        )
        conn.execute(
            "INSERT INTO int1_fake_doctor_replies(turn_id,message_id,result) "
            "VALUES(?,?,?)", (turn, message.lastrowid, RESULT),
        )
        conn.execute(
            "INSERT INTO session_events(session_id,event_type,payload_json) "
            "VALUES(?,'turn.completed',?)",
            (session, json.dumps({
                "turnId": turn, "doctorMessageId": str(message.lastrowid),
                "result": RESULT, "fakeOnly": True, "modelCalls": 0,
            }, sort_keys=True)),
        )
        # Do not update the canonical sessions row here: B2 must revoke
        # execution grants on any real session lifecycle mutation.
        # Synthetic session status is projected from the turn ledger.
        conn.commit()
        return {
            "turnId": turn, "state": "COMPLETED",
            "doctorMessageId": str(message.lastrowid), "doctorReply": REPLY,
            "result": RESULT, "syntheticSessionStatus": "WAITING",
            "productionReady": False, "syntheticOnly": True,
        }
    except BaseException:
        conn.rollback()
        raise


def resolve_incomplete(conn, room, session, turn, acknowledgment, reason):
    if acknowledgment != ACK:
        raise RuntimeError("INT1-B14 REFUSED // explicit no-retry acknowledgment required")
    if not 3 <= len(reason.strip()) <= 256:
        raise RuntimeError("INT1-B14 REFUSED // bounded reason required")
    conn.execute("BEGIN IMMEDIATE")
    try:
        verify_hooks(conn)
        verify_b4(conn)
        row = _turn(conn, room, session, turn)
        if (row is None or row["state"] != "ACCEPTED_UNDISPATCHED" or
                _reply(conn, turn) or row["receipt_state"] not in (None, "ACKED") or
                (row["receipt_state"] == "ACKED" and row["receipt_result"] != RESULT)):
            raise RuntimeError("INT1-B14 REFUSED // not an incomplete synthetic turn")
        updated = conn.execute(
            "UPDATE int1_fake_accepted_turns SET state='FAILED' "
            "WHERE turn_id=? AND state='ACCEPTED_UNDISPATCHED'", (turn,),
        )
        if updated.rowcount != 1:
            raise RuntimeError("INT1-B14 REFUSED // concurrent state change")
        conn.execute(
            "INSERT INTO session_events(session_id,event_type,payload_json) "
            "VALUES(?,'turn.lifecycle.manual-incomplete-failure',?)",
            (session, json.dumps({
                "turnId": turn, "reason": reason.strip(),
                "receiptState": row["receipt_state"],
                "automaticRetryAllowed": False,
                "workerTerminationVerified": False, "fakeOnly": True,
            }, sort_keys=True)),
        )
        # No canonical session status mutation while fake B2 authority is active.
        conn.commit()
        return {
            "turnId": turn, "state": "FAILED",
            "acceptedMessageRetained": True, "auditEventWritten": True,
            "workerTerminationVerified": False,
            "automaticRetryAllowed": False, "syntheticOnly": True,
            "syntheticSessionStatus": "FAILED",
        }
    except BaseException:
        conn.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description="B14 fixture-only synthetic Doctor")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("turn", "status", "resolve-incomplete"):
        p = sub.add_parser(name)
        p.add_argument("--room-id", required=True)
        p.add_argument("--session-id", required=True)
        p.add_argument("--turn-id", required=True)
        if name == "turn":
            p.add_argument("--body-stdin", required=True, action="store_true")
            p.add_argument("--cancel-demo", action="store_true",
                           help="B14 fixed synthetic one-child cancellation probe")
        if name == "resolve-incomplete":
            p.add_argument("--acknowledge", required=True)
            p.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        for value, label in ((args.room_id, "Room ID"),
                             (args.session_id, "session ID"),
                             (args.turn_id, "turn ID")):
            require_id(value, label)
        if args.command == "turn":
            result = run(
                args.room_id, args.session_id, args.turn_id, sys.stdin.read(),
                scenario=("gated-tree-cancel" if args.cancel_demo
                          else "gated-task"), task="SUM_1_TO_8",
            )
            with connect() as conn:
                completed = finalize_verified(
                    conn, args.room_id, args.session_id, args.turn_id,
                )
            completed["brokerReaped"] = result["brokerReaped"]
            result = completed
        else:
            with connect() as conn:
                if args.command == "status":
                    result = inspect(conn, args.room_id, args.session_id, args.turn_id)
                else:
                    result = resolve_incomplete(
                        conn, args.room_id, args.session_id, args.turn_id,
                        args.acknowledge, args.reason,
                    )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RuntimeError, OSError, ValueError, sqlite3.Error) as exc:
        print("px INT1-B14 fake Doctor: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
