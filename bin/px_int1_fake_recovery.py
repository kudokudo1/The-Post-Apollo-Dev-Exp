#!/usr/bin/env python3
"""INT1-B12 disposable manual recovery for uncertain B11 dispatch reservations.

Never retries, requeues, impersonates a model result, or claims a killed child.
An ACKED receipt is immutable. A RESERVED receipt is ambiguous after a crash;
the only supported resolution is an explicitly acknowledged FAILED record,
paired atomically with a Hospital session event. The accepted operator message
is retained. Fixture-only; no production migration or dispatch is possible.
"""
import argparse
import json
import re
import sqlite3
import sys

from px_int1_fake_atomic import connect, require_id
from px_int1_fake_epoch import verify_hooks
from px_int1_fake_continuity import verify_b4

ACKNOWLEDGMENT = "I_ACKNOWLEDGE_UNKNOWN_DELIVERY_AND_NO_RETRY"
RECOVERY_RESULT = "MANUAL_UNCERTAIN_DELIVERY_NO_RETRY"
EVENT_KIND = "turn.dispatch.manual-uncertain-failure"


def _read(conn, turn_id, room_id, session_id):
    row = conn.execute(
        """SELECT t.turn_id,t.room_id,t.session_id,t.state AS turn_state,
                  r.state AS receipt_state,r.result,r.nonce_hash
           FROM int1_fake_accepted_turns t
           JOIN int1_fake_dispatch_receipts r ON r.turn_id=t.turn_id
           WHERE t.turn_id=? AND t.room_id=? AND t.session_id=?""",
        (turn_id, room_id, session_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("INT1-B12 REFUSED // matching durable receipt required")
    if (not re.fullmatch(r"[0-9a-f]{64}", row["nonce_hash"] or "") or
            row["turn_state"] not in ("ACCEPTED_UNDISPATCHED", "FAILED") or
            row["receipt_state"] not in ("RESERVED", "ACKED", "FAILED")):
        raise RuntimeError("INT1-B12 REFUSED // inconsistent receipt")
    return row


def inspect(conn, *, room_id, session_id, turn_id):
    # Inspection never writes or silently resolves a receipt.
    conn.execute("BEGIN")
    try:
        row = _read(conn, turn_id, room_id, session_id)
        reserved = row["receipt_state"] == "RESERVED"
        result = {
            "roomId": room_id,
            "sessionId": session_id,
            "turnId": turn_id,
            "turnState": row["turn_state"],
            "receiptState": row["receipt_state"],
            "result": row["result"],
            "requiresExplicitRecovery": reserved,
            "deliveryKnown": row["receipt_state"] == "ACKED",
            "automaticRetryAllowed": False,
            "workerTerminationVerified": False,
            "syntheticOnly": True,
        }
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise


def resolve_uncertain(conn, *, room_id, session_id, turn_id, acknowledgment,
                      reason):
    if acknowledgment != ACKNOWLEDGMENT:
        raise RuntimeError("INT1-B12 REFUSED // explicit no-retry acknowledgment required")
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 256:
        raise RuntimeError("INT1-B12 REFUSED // bounded operator reason required")
    # Do not require a *currently valid grant*: a revoked Room must still be
    # able to mark its already-accepted uncertain turn FAILED. Hook integrity
    # is mandatory to avoid writing into a visibly compromised fixture.
    conn.execute("BEGIN IMMEDIATE")
    try:
        verify_hooks(conn)
        verify_b4(conn)
        row = _read(conn, turn_id, room_id, session_id)
        if (row["receipt_state"] != "RESERVED" or
                row["turn_state"] != "ACCEPTED_UNDISPATCHED" or row["result"]):
            raise RuntimeError("INT1-B12 REFUSED // only unresolved RESERVED is recoverable")
        updated_receipt = conn.execute(
            "UPDATE int1_fake_dispatch_receipts SET state='FAILED', result=? "
            "WHERE turn_id=? AND state='RESERVED' AND result=''",
            (RECOVERY_RESULT, turn_id),
        )
        updated_turn = conn.execute(
            "UPDATE int1_fake_accepted_turns SET state='FAILED' "
            "WHERE turn_id=? AND state='ACCEPTED_UNDISPATCHED'",
            (turn_id,),
        )
        if updated_receipt.rowcount != 1 or updated_turn.rowcount != 1:
            raise RuntimeError("INT1-B12 REFUSED // recovery state changed concurrently")
        conn.execute(
            "INSERT INTO session_events(session_id,event_type,payload_json) "
            "VALUES(?,?,?)",
            (session_id, EVENT_KIND, json.dumps({
                "turnId": turn_id,
                "roomId": room_id,
                "reason": reason.strip(),
                "receiptResult": RECOVERY_RESULT,
                "deliveryKnown": False,
                "automaticRetryAllowed": False,
                "workerTerminationVerified": False,
                "fakeOnly": True,
            }, sort_keys=True)),
        )
        conn.commit()
        return {
            "turnId": turn_id, "roomId": room_id, "sessionId": session_id,
            "state": "FAILED_UNCERTAIN_DELIVERY",
            "result": RECOVERY_RESULT,
            "deliveryKnown": False,
            "automaticRetryAllowed": False,
            "workerTerminationVerified": False,
            "acceptedMessageRetained": True,
            "auditEventWritten": True,
            "syntheticOnly": True,
        }
    except BaseException:
        conn.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(
        description="B12 fixture-only manual close of unresolved synthetic dispatch"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "resolve-uncertain"):
        p = sub.add_parser(name)
        p.add_argument("--room-id", required=True)
        p.add_argument("--session-id", required=True)
        p.add_argument("--turn-id", required=True)
        if name == "resolve-uncertain":
            p.add_argument("--acknowledge", required=True)
            p.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        room_id = require_id(args.room_id, "Room ID")
        session_id = require_id(args.session_id, "session ID")
        turn_id = require_id(args.turn_id, "turn ID")
        with connect() as conn:
            if args.command == "inspect":
                result = inspect(conn, room_id=room_id,
                                 session_id=session_id, turn_id=turn_id)
            else:
                result = resolve_uncertain(
                    conn, room_id=room_id, session_id=session_id,
                    turn_id=turn_id, acknowledgment=args.acknowledge,
                    reason=args.reason,
                )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RuntimeError, OSError, ValueError, sqlite3.Error) as exc:
        print("px INT1-B12 recovery: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
