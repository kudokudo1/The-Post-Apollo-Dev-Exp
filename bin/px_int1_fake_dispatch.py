#!/usr/bin/env python3
"""INT1-B11: disposable one-use synthetic NOOP dispatch, never a tool broker.

Trust boundary: verified nested B10 idle worker first; B1 atomic accept second;
durable one-use reservation third; live authorization, continuity and broker
identity checked under a SQLite write barrier THROUGH the inert NOOP ACK.
No provider, real tool, network, credential, live Hospital or production path.
Crash with RESERVED receipt intentionally requires human recovery: NO auto-retry.
"""
import argparse
import hashlib
import json
import os
import re
import selectors
import sqlite3
import sys
import time

from px_int1_fake_atomic import (
    PROFILE, require_id, connect, accept, authority_row, validate_live,
    continuity_hash, validate_required_context, context_digest, revoke,
)
from px_int1_fake_epoch import verify_hooks
from px_int1_fake_continuity import verify_b4
from px_int1_fake_broker import (
    _nested_launch, _child_pid_from_bwrap, _receive_ready,
    _resolve_isolated_worker, _observe_nested, _terminate_and_reap,
)

RECEIPTS = """CREATE TABLE IF NOT EXISTS int1_fake_dispatch_receipts (
    turn_id TEXT PRIMARY KEY REFERENCES int1_fake_accepted_turns(turn_id),
    state TEXT NOT NULL CHECK(state IN ('RESERVED','ACKED','FAILED')),
    nonce_hash TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT ''
)"""


def request_hash(room_id, session_id, turn_id, generation, digest, body):
    raw = json.dumps({
        "roomId": room_id, "sessionId": session_id, "turnId": turn_id,
        "generation": generation, "contextHash": digest,
        "body": body, "profile": PROFILE,
    }, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def current_authority(conn, *, room_id, session_id, generation, digest):
    verify_hooks(conn)
    verify_b4(conn)
    validate_live(conn, room_id, session_id)
    auth = authority_row(conn, room_id)
    if auth["revoked"] or auth["generation"] != generation:
        raise RuntimeError("INT1-B11 REFUSED // stale or revoked authority")
    actual_hash, document = continuity_hash(conn, room_id, session_id)
    validate_required_context(conn, document)
    if digest != actual_hash:
        raise RuntimeError("INT1-B11 REFUSED // continuity changed at dispatch")


def reserve(conn, *, room_id, session_id, turn_id, generation, digest,
            body, nonce):
    conn.execute(RECEIPTS)
    conn.execute("BEGIN IMMEDIATE")
    try:
        current_authority(conn, room_id=room_id, session_id=session_id,
                          generation=generation, digest=digest)
        turn = conn.execute(
            "SELECT * FROM int1_fake_accepted_turns WHERE turn_id=?",
            (turn_id,),
        ).fetchone()
        expected = request_hash(room_id, session_id, turn_id, generation, digest, body)
        if (turn is None or turn["room_id"] != room_id
                or turn["session_id"] != session_id
                or turn["generation"] != generation
                or turn["request_hash"] != expected
                or turn["state"] != "ACCEPTED_UNDISPATCHED"):
            raise RuntimeError("INT1-B11 REFUSED // accepted turn identity mismatch")
        if conn.execute("SELECT 1 FROM int1_fake_dispatch_receipts WHERE turn_id=?",
                        (turn_id,)).fetchone():
            raise RuntimeError("INT1-B11 REFUSED // dispatch already reserved")
        conn.execute(
            "INSERT INTO int1_fake_dispatch_receipts(turn_id,state,nonce_hash) "
            "VALUES(?,'RESERVED',?)",
            (turn_id, hashlib.sha256(nonce.encode()).hexdigest()),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def receive_ack(child, *, nonce, turn_id, timeout=1.0):
    selector = selectors.DefaultSelector()
    try:
        selector.register(child.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        data = bytearray()
        while time.monotonic() < deadline:
            if child.poll() is not None and not data:
                raise RuntimeError("INT1-B11 REFUSED // broker exited without ACK")
            ready = selector.select(min(0.05, max(0, deadline - time.monotonic())))
            if not ready:
                continue
            chunk = os.read(child.stdout.fileno(), 257 - len(data))
            if not chunk:
                raise RuntimeError("INT1-B11 REFUSED // broker ACK EOF")
            data.extend(chunk)
            if len(data) > 256:
                raise RuntimeError("INT1-B11 REFUSED // oversized broker ACK")
            if b"\n" in data:
                break
        else:
            raise RuntimeError("INT1-B11 REFUSED // broker ACK deadline exceeded")
        try:
            payload = json.loads(data.decode())
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("INT1-B11 REFUSED // malformed broker ACK") from exc
        if (not data.endswith(b"\n") or data.count(b"\n") != 1 or
                payload != {"phase": "ACK", "nonce": nonce, "turnId": turn_id,
                            "result": "SYNTHETIC_NOOP"}):
            raise RuntimeError("INT1-B11 REFUSED // broker ACK mismatch")
        return payload
    finally:
        selector.close()


def dispatch_barrier(conn, child, *, room_id, session_id, turn_id,
                     generation, digest, nonce, ack_timeout):
    conn.execute("BEGIN IMMEDIATE")
    try:
        current_authority(conn, room_id=room_id, session_id=session_id,
                          generation=generation, digest=digest)
        receipt = conn.execute(
            "SELECT * FROM int1_fake_dispatch_receipts WHERE turn_id=?",
            (turn_id,),
        ).fetchone()
        if (receipt is None or receipt["state"] != "RESERVED" or
                receipt["nonce_hash"] != hashlib.sha256(nonce.encode()).hexdigest()):
            raise RuntimeError("INT1-B11 REFUSED // dispatch reservation missing")
        frame = json.dumps({"op": "SYNTHETIC_NOOP",
                            "nonce": nonce, "turnId": turn_id},
                           sort_keys=True).encode() + b"\n"
        if len(frame) > 256:
            raise RuntimeError("INT1-B11 REFUSED // oversized dispatch frame")
        # Explicit single inert frame; the DB write lock spans transmission
        # AND ACK, serializing ordinary Hospital authority/continuity mutations.
        child.stdin.write(frame)
        child.stdin.flush()
        child.stdin.close()
        ack = receive_ack(child, nonce=nonce, turn_id=turn_id, timeout=ack_timeout)
        conn.execute(
            "UPDATE int1_fake_dispatch_receipts SET state='ACKED', result=? "
            "WHERE turn_id=? AND state='RESERVED'",
            (ack["result"], turn_id),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def mark_failed(conn, turn_id):
    # A confirmed failed dispatch never rolls back the already accepted
    # operator message. A crash leaves RESERVED, blocking automatic retry.
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE int1_fake_dispatch_receipts SET state='FAILED' "
            "WHERE turn_id=? AND state='RESERVED'", (turn_id,),
        )
        conn.execute(
            "UPDATE int1_fake_accepted_turns SET state='FAILED' WHERE turn_id=? "
            "AND state='ACCEPTED_UNDISPATCHED'", (turn_id,),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def run(room_id, session_id, turn_id, body, *, scenario="gated",
        revoke_before_dispatch=False, test_crash_after_reserve=False):
    for value, field in ((room_id, "Room ID"), (session_id, "session ID"),
                         (turn_id, "turn ID")):
        require_id(value, field)
    if scenario not in ("gated", "gated-malformed-ack", "gated-timeout-ack",
                        "early-exit", "malformed", "timeout"):
        raise RuntimeError("INT1-B11 REFUSED // unrecognized fake broker scenario")
    if not body.strip() or len(body) > 4096:
        raise RuntimeError("INT1-B11 REFUSED // invalid synthetic prompt")
    with connect() as conn:
        before = context_digest(conn, room_id, session_id)
        already = conn.execute(
            "SELECT 1 FROM int1_fake_accepted_turns WHERE turn_id=?", (turn_id,)
        ).fetchone()
        if already:
            raise RuntimeError("INT1-B11 REFUSED // no automatic turn replay")
        generation, digest = before["generation"], before["contextHash"]
        nonce = os.urandom(16).hex()
        child, info_fd = _nested_launch(scenario, nonce, controlled_stdin=True)
        accepted = False
        try:
            pid = _child_pid_from_bwrap(info_fd, child.pid, 2.5)
            _receive_ready(child, nonce, 2.5)
            worker = _resolve_isolated_worker(pid, scenario, nonce)
            proof = _observe_nested(worker, controlled_stdin=True)
            now = context_digest(conn, room_id, session_id)
            if (now["generation"], now["contextHash"]) != (generation, digest):
                raise RuntimeError("INT1-B11 REFUSED // eligibility changed before acceptance")
            accepted_result = accept(
                conn, room_id=room_id, session_id=session_id, turn_id=turn_id,
                generation=generation, context_hash=digest, body=body,
            )
            if accepted_result["replayed"]:
                raise RuntimeError("INT1-B11 REFUSED // no automatic turn replay")
            accepted = True
            try:
                reserve(
                    conn, room_id=room_id, session_id=session_id,
                    turn_id=turn_id, generation=generation, digest=digest,
                    body=body, nonce=nonce,
                )
                if test_crash_after_reserve:
                    # B12 disposable crash test: terminate the supervisor
                    # without finally or Python cleanup, before ANY frame is
                    # written. Nested bwrap uses --die-with-parent.
                    # The durable RESERVED receipt must survive this process.
                    os._exit(77)
                if revoke_before_dispatch:
                    revoke(conn, room_id, "B11 synthetic before dispatch")
                dispatch_barrier(
                    conn, child, room_id=room_id, session_id=session_id,
                    turn_id=turn_id, generation=generation, digest=digest,
                    nonce=nonce, ack_timeout=0.3 if scenario == "gated-timeout-ack" else 1.5,
                )
            except BaseException:
                mark_failed(conn, turn_id)
                raise
            return {
                "state": "SYNTHETIC_NOOP_ACKED", "turnId": turn_id,
                "messageId": accepted_result["messageId"],
                "generation": generation,
                "profile": PROFILE, "brokerReaped": True,
                "brokerOsObserved": bool(proof),
                "syntheticFrames": 1, "modelCalls": 0, "toolCalls": 0,
                "productionReady": False,
            }
        finally:
            _terminate_and_reap(child)


def main():
    parser = argparse.ArgumentParser(description="INT1-B11 fixture-only inert dispatch")
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--body-stdin", required=True, action="store_true")
    parser.add_argument("--scenario", default="gated")
    parser.add_argument("--test-revoke-before-dispatch", action="store_true")
    parser.add_argument("--test-crash-after-reserve", action="store_true")
    args = parser.parse_args()
    try:
        result = run(
            args.room_id, args.session_id, args.turn_id, sys.stdin.read(),
            scenario=args.scenario,
            revoke_before_dispatch=args.test_revoke_before_dispatch,
            test_crash_after_reserve=args.test_crash_after_reserve,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RuntimeError, OSError, ValueError, sqlite3.Error) as exc:
        print("px INT1-B11 fake dispatch: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
