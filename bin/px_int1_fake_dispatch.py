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
import select
import selectors
from pathlib import Path
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

# B17: a synthetic turn-specific cancellation intent. The nonce hash binds
# this record to one durable dispatch reservation; Room grants are untouched.
CANCELLATIONS = """CREATE TABLE IF NOT EXISTS int1_fake_turn_cancellations (
    turn_id TEXT PRIMARY KEY REFERENCES int1_fake_dispatch_receipts(turn_id),
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    generation INTEGER NOT NULL CHECK(generation > 0),
    nonce_hash TEXT NOT NULL CHECK(length(nonce_hash) = 64)
)"""

# B18 is only a positive proof of this exact supervisor's COMPLETED
# cleanup procedure, not a proof of death after a different supervisor
# crashes. No external worker can submit or set these receipt fields.
TEARDOWN = """CREATE TABLE IF NOT EXISTS int1_fake_supervisor_teardown (
    turn_id TEXT PRIMARY KEY REFERENCES int1_fake_accepted_turns(turn_id),
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    wrapper_reaped INTEGER NOT NULL CHECK(wrapper_reaped = 1),
    known_descendant_pidfd_exit INTEGER NOT NULL
        CHECK(known_descendant_pidfd_exit IN (0,1))
)"""


def record_supervised_teardown(conn, *, room_id, session_id, turn_id,
                               descendant_pidfd_exit_verified):
    # Call only after _terminate_and_reap succeeded AND optional
    # DescendantTracker.verify_and_close returned without error.
    conn.execute("BEGIN IMMEDIATE")
    try:
        verify_hooks(conn)
        verify_b4(conn)
        row = conn.execute(
            "SELECT 1 FROM int1_fake_accepted_turns "
            "WHERE turn_id=? AND room_id=? AND session_id=?",
            (turn_id, room_id, session_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("INT1-B18 REFUSED // no matching accepted turn")
        conn.execute(TEARDOWN)
        conn.execute(
            "INSERT INTO int1_fake_supervisor_teardown"
            "(turn_id,room_id,session_id,wrapper_reaped,"
            "known_descendant_pidfd_exit) VALUES(?,?,?,1,?)",
            (turn_id, room_id, session_id,
             int(bool(descendant_pidfd_exit_verified))),
        )
        conn.execute(
            "INSERT INTO session_events(session_id,event_type,payload_json) "
            "VALUES(?,'turn.supervisor.teardown',?)",
            (session_id, json.dumps({
                "turnId": turn_id, "roomId": room_id,
                "wrapperReapedVerified": True,
                "knownDescendantPidfdExitVerified":
                    bool(descendant_pidfd_exit_verified),
                "workerTerminationVerifiedAfterCrash": False,
                "source": "SUPERVISOR_SUCCESSFUL_FINALLY",
                "automaticRetryAllowed": False, "fakeOnly": True,
            }, sort_keys=True)),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def ensure_turn_not_cancelled(conn, *, room_id, session_id, turn_id,
                              generation, nonce):
    # The table may not exist until the first explicit cancellation. Do NOT
    # create it in a polling/read transaction or write to the canonical Room.
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='int1_fake_turn_cancellations'"
    ).fetchone()
    if exists is None:
        return
    row = conn.execute(
        "SELECT room_id,session_id,generation,nonce_hash "
        "FROM int1_fake_turn_cancellations WHERE turn_id=?", (turn_id,),
    ).fetchone()
    if row is None:
        return
    if (row["room_id"] != room_id or row["session_id"] != session_id or
            row["generation"] != generation or
            row["nonce_hash"] != hashlib.sha256(nonce.encode()).hexdigest()):
        raise RuntimeError("INT1-B17 REFUSED // cancellation identity mismatch")
    raise RuntimeError("INT1-B17 REFUSED // synthetic turn cancellation requested")



class DescendantTracker:
    """Pin the one B13 test descendant using a kernel pidfd, then verify death.

    A PID number by itself is insufficient because it can be reused. Pidfds
    remain tied to the original task. This observer never trusts worker JSON.
    """
    def __init__(self, worker_pid):
        self.worker_pid = worker_pid
        self.pidfd = None
        self.readiness_wait_started = False

    def capture(self):
        self.readiness_wait_started = True
        if self.pidfd is not None:
            return
        try:
            children = Path(
                "/proc/%s/task/%s/children" %
                (self.worker_pid, self.worker_pid)
            ).read_text().split()
        except FileNotFoundError:
            return
        if len(children) > 1:
            raise RuntimeError("INT1-B13 REFUSED // unexpected synthetic process tree")
        if not children:
            return
        pid = int(children[0])
        # Reject a descendant that escaped the worker's isolated namespaces.
        for kind in ("pid", "mnt", "user", "net"):
            worker = os.stat("/proc/%s/ns/%s" % (self.worker_pid, kind))
            descendant = os.stat("/proc/%s/ns/%s" % (pid, kind))
            if (worker.st_dev, worker.st_ino) != (
                    descendant.st_dev, descendant.st_ino):
                raise RuntimeError("INT1-B13 REFUSED // descendant namespace mismatch")
        self.pidfd = os.pidfd_open(pid, 0)

    def verify_and_close(self):
        if not self.readiness_wait_started:
            # The dispatch was denied BEFORE any frame/ACK wait. No spawned
            # descendant is expected; the wrapper is still terminated.
            return
        if self.pidfd is None:
            raise RuntimeError("INT1-B13 REFUSED // descendant not observed")
        try:
            poller = select.poll()
            poller.register(self.pidfd, select.POLLIN)
            if not poller.poll(1500):
                raise RuntimeError("INT1-B13 REFUSED // descendant survived teardown")
        finally:
            os.close(self.pidfd)
            self.pidfd = None


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


def receive_ack(child, *, nonce, turn_id, expected_result="SYNTHETIC_NOOP",
                on_tick=None, timeout=1.0):
    selector = selectors.DefaultSelector()
    try:
        selector.register(child.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        data = bytearray()
        while time.monotonic() < deadline:
            if on_tick is not None:
                on_tick()
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
                            "result": expected_result}):
            raise RuntimeError("INT1-B11 REFUSED // broker ACK mismatch")
        return payload
    finally:
        selector.close()


def dispatch_barrier(conn, child, *, room_id, session_id, turn_id,
                     generation, digest, nonce, ack_timeout,
                     task="NOOP", on_tick=None, live_revocation=False,
                     crash_after_frame_with_descendant=False):
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
        operation = ("SYNTHETIC_SUM_1_TO_8" if task == "SUM_1_TO_8"
                     else "SYNTHETIC_NOOP")
        expected = ("SYNTHETIC_SUM_36" if task == "SUM_1_TO_8"
                    else "SYNTHETIC_NOOP")
        frame = json.dumps({"op": operation,
                            "nonce": nonce, "turnId": turn_id},
                           sort_keys=True).encode() + b"\n"
        if len(frame) > 256:
            raise RuntimeError("INT1-B11 REFUSED // oversized dispatch frame")
        # Stage C single fixed frame: serialize authorization and actual
        # pipe dispatch under the SQLite write lock. The B14/B17 mode releases
        # that lock AFTER transmission, allowing an independent per-turn
        # cancellation or Room revocation to commit during execution.
        ensure_turn_not_cancelled(conn, room_id=room_id, session_id=session_id,
                                  turn_id=turn_id, generation=generation,
                                  nonce=nonce)
        child.stdin.write(frame)
        child.stdin.flush()
        child.stdin.close()
        if crash_after_frame_with_descendant:
            # B18 synthetic-only crash injection: frame has already crossed
            # the dispatch pipe, but no ACK or cleanup result is durable.
            # Release the writer transaction; prove only that one B13 child
            # fork was observed before killing the SUPERVISOR with os._exit.
            # This is deliberately NOT a termination attestation.
            conn.commit()
            if on_tick is None:
                raise RuntimeError("INT1-B18 REFUSED // missing descendant tracker")
            deadline = time.monotonic() + 1.8
            while time.monotonic() < deadline:
                on_tick()
                # The caller's tracker captures a pidfd, but no PID values
                # are exported to the fixture database or treated as a grant.
                # Give the known fixed worker time to produce the child.
                if getattr(on_tick, "__self__", None) is not None and getattr(
                        on_tick.__self__, "pidfd", None) is not None:
                    os._exit(78)
                time.sleep(0.02)
            raise RuntimeError("INT1-B18 REFUSED // fork not observed in time")
        callback = on_tick
        if live_revocation:
            # No untrusted task gets a DB handle. Only the trusted supervisor
            # rechecks the source hooks, Room/Session identity and generation.
            conn.commit()
            def callback():
                if on_tick is not None:
                    on_tick()
                current_authority(conn, room_id=room_id,
                                  session_id=session_id,
                                  generation=generation, digest=digest)
                ensure_turn_not_cancelled(
                    conn, room_id=room_id, session_id=session_id,
                    turn_id=turn_id, generation=generation, nonce=nonce,
                )
        ack = receive_ack(child, nonce=nonce, turn_id=turn_id,
                          expected_result=expected, on_tick=callback,
                          timeout=ack_timeout)
        if live_revocation:
            # This barrier competes with revocation. A stale ACK cannot
            # finalize even if the child was faster than the poll loop.
            conn.execute("BEGIN IMMEDIATE")
            current_authority(conn, room_id=room_id, session_id=session_id,
                              generation=generation, digest=digest)
            ensure_turn_not_cancelled(
                conn, room_id=room_id, session_id=session_id,
                turn_id=turn_id, generation=generation, nonce=nonce,
            )
            after = conn.execute(
                "SELECT state,nonce_hash FROM int1_fake_dispatch_receipts "
                "WHERE turn_id=?", (turn_id,),
            ).fetchone()
            if (after is None or after["state"] != "RESERVED" or
                    after["nonce_hash"] != hashlib.sha256(nonce.encode()).hexdigest()):
                raise RuntimeError("INT1-B14 REFUSED // dispatch receipt changed")
        updated = conn.execute(
            "UPDATE int1_fake_dispatch_receipts SET state='ACKED', result=? "
            "WHERE turn_id=? AND state='RESERVED'",
            (ack["result"], turn_id),
        )
        if updated.rowcount != 1:
            raise RuntimeError("INT1-B14 REFUSED // receipt not uniquely ACKED")
        conn.commit()
        return ack
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
        task="NOOP", revoke_before_dispatch=False, test_crash_after_reserve=False,
        test_crash_after_frame=False, test_crash_after_cleanup=False,
        test_crash_after_teardown_commit=False):
    for value, field in ((room_id, "Room ID"), (session_id, "session ID"),
                         (turn_id, "turn ID")):
        require_id(value, field)
    noop_scenarios = ("gated", "gated-malformed-ack", "gated-timeout-ack",
                      "early-exit", "malformed", "timeout")
    task_scenarios = ("gated-task", "gated-tree", "gated-tree-timeout",
                      "gated-tree-cancel")
    if not ((task == "NOOP" and scenario in noop_scenarios)
            or (task == "SUM_1_TO_8" and scenario in task_scenarios)):
        raise RuntimeError("INT1-B13 REFUSED // task/scenario mismatch")
    if not body.strip() or len(body) > 4096:
        raise RuntimeError("INT1-B11 REFUSED // invalid synthetic prompt")
    if test_crash_after_frame and (
            test_crash_after_reserve or scenario != "gated-tree-cancel"
            or task != "SUM_1_TO_8"):
        raise RuntimeError("INT1-B18 REFUSED // crash injection requires fixed tree task")
    # B19 fault locations are mutually exclusive and source-owned. They
    # are never valid for a general provider, arbitrary task or unknown tree.
    if test_crash_after_cleanup or test_crash_after_teardown_commit:
        if (test_crash_after_reserve or test_crash_after_frame or
                test_crash_after_cleanup and test_crash_after_teardown_commit or
                scenario != "gated-tree" or task != "SUM_1_TO_8"):
            raise RuntimeError(
                "INT1-B19 REFUSED // cleanup crash needs one fixed tree task"
            )
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
        tree_tracker = None
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
                if scenario in ("gated-tree", "gated-tree-timeout",
                                "gated-tree-cancel"):
                    tree_tracker = DescendantTracker(worker)
                ack = dispatch_barrier(
                    conn, child, room_id=room_id, session_id=session_id,
                    turn_id=turn_id, generation=generation, digest=digest,
                    nonce=nonce,
                    task=task,
                    on_tick=tree_tracker.capture if tree_tracker else None,
                    live_revocation=scenario == "gated-tree-cancel",
                    crash_after_frame_with_descendant=test_crash_after_frame,
                    ack_timeout=(3.0 if scenario == "gated-tree-cancel" else
                                 0.3 if scenario in (
                                     "gated-timeout-ack", "gated-tree-timeout")
                                 else 1.5),
                )
            except BaseException:
                mark_failed(conn, turn_id)
                raise
            return {
                "state": ("SYNTHETIC_TASK_ACKED" if task == "SUM_1_TO_8"
                          else "SYNTHETIC_NOOP_ACKED"),
                "turnId": turn_id,
                "messageId": accepted_result["messageId"],
                "generation": generation,
                "profile": PROFILE, "brokerReaped": True,
                "brokerOsObserved": bool(proof),
                "syntheticFrames": 1, "modelCalls": 0, "toolCalls": 0,
                "taskResult": ack["result"],
                "descendantTerminationVerified": bool(tree_tracker),
                "productionReady": False,
            }
        finally:
            # Write B18 positive evidence ONLY after both cleanup checks.
            # os._exit(), a failed wait, or a missing pidfd bypasses evidence.
            _terminate_and_reap(child)
            verified_descendant = False
            if tree_tracker is not None:
                verified_descendant = bool(
                    tree_tracker.readiness_wait_started and
                    tree_tracker.pidfd is not None
                )
                tree_tracker.verify_and_close()
            # Deterministic crash at the *actual* cleanup-to-commit gap.
            # Although this live supervisor verified wrapper + known child
            # exit, its death before SQLite commit cannot produce evidence.
            # A restarted observer must remain uncertain about termination.
            if test_crash_after_cleanup:
                if not accepted or not verified_descendant:
                    raise RuntimeError(
                        "INT1-B19 REFUSED // cleanup proof not established"
                    )
                os._exit(79)
            if accepted:
                record_supervised_teardown(
                    conn, room_id=room_id, session_id=session_id,
                    turn_id=turn_id,
                    descendant_pidfd_exit_verified=verified_descendant,
                )
                # This fault has a committed supervised proof but deliberately
                # does not run B14 Doctor reply finalization. No restart may
                # infer a reply from teardown evidence or ACK alone.
                if test_crash_after_teardown_commit:
                    if not verified_descendant:
                        raise RuntimeError(
                            "INT1-B19 REFUSED // descendant exit unverified"
                        )
                    os._exit(80)


def main():
    parser = argparse.ArgumentParser(description="INT1-B11 fixture-only inert dispatch")
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--body-stdin", required=True, action="store_true")
    parser.add_argument("--scenario", default="gated")
    parser.add_argument("--task", choices=("NOOP", "SUM_1_TO_8"), default="NOOP")
    parser.add_argument("--test-revoke-before-dispatch", action="store_true")
    parser.add_argument("--test-crash-after-reserve", action="store_true")
    parser.add_argument("--test-crash-after-frame", action="store_true")
    parser.add_argument("--test-crash-after-cleanup", action="store_true")
    parser.add_argument("--test-crash-after-teardown-commit", action="store_true")
    args = parser.parse_args()
    try:
        result = run(
            args.room_id, args.session_id, args.turn_id, sys.stdin.read(),
            scenario=args.scenario, task=args.task,
            revoke_before_dispatch=args.test_revoke_before_dispatch,
            test_crash_after_reserve=args.test_crash_after_reserve,
            test_crash_after_frame=args.test_crash_after_frame,
            test_crash_after_cleanup=args.test_crash_after_cleanup,
            test_crash_after_teardown_commit=args.test_crash_after_teardown_commit,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RuntimeError, OSError, ValueError, sqlite3.Error) as exc:
        print("px INT1-B11 fake dispatch: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
