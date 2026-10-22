#!/usr/bin/env python3
"""B15/B16: narrow real px-agent seam to disposable synthetic Doctor.

The trusted px-agent performs ordinary Session/Room/Bed/context Stage A first.
No provider process is started, no shell/host tools can be requested, and the
real Hospital database is never opened by this fake execution profile.
"""
from px_int1_fake_guard import (
    PROFILE, FAKE_ID, require_fixture, require_profile,
    require_doctor_room_binding,
)
import json

from px_int1_fake_atomic import (
    connect, context_digest, continuity_document, require_id,
    authority_row, validate_live,
)
from px_int1_fake_epoch import verify_hooks
from px_int1_fake_continuity import verify_b4
from px_int1_fake_lifecycle import run, finalize_verified, inspect
from px_int1_fake_dispatch import CANCELLATIONS
from px_int1_fake_capability import require_fake_capability


def _required_context_parity(conn, context, room_id, session_id):
    """Compare actual PX required lanes with the stored B6 source selection.

    An earlier context is not a dispatch grant: B11/B14 must still revalidate
    current authority and source digest under each subsequent write barrier.
    """
    digest = context_digest(conn, room_id, session_id)
    source = continuity_document(conn, room_id, session_id)
    handoffs = source["handoffs"]
    room_chart = [r for r in source["approvedCharts"]
                  if r["scope_type"] == "ROOM"]
    patient_chart = [r for r in source["approvedCharts"]
                     if r["scope_type"] == "PATIENT"]
    for label, agent_rows, source_rows, pk in (
            ("HANDOFF", context["requiredHandoffs"], handoffs, "report_id"),
            ("ROOM_CHART", context["approvedRoomChart"], room_chart, "entry_id"),
            ("PATIENT_CHART", context["approvedPatientChart"],
             patient_chart, "entry_id")):
        if len(agent_rows) != len(source_rows):
            raise RuntimeError("INT1-B15 REFUSED // " + label + " selection mismatch")
        ordered_agent = sorted(agent_rows, key=lambda r: int(r["id"]))
        ordered_source = sorted(source_rows, key=lambda r: int(r[pk]))
        for a, s in zip(ordered_agent, ordered_source):
            if (str(a["id"]) != str(s[pk]) or
                    str(a.get("body") or "") != str(s["body_md"] or "") or
                    str(a.get("title") or "") != str(s["title"] or "")):
                raise RuntimeError("INT1-B15 REFUSED // " + label +
                                   " source body mismatch")
    return digest


def execute_fake_turn(*, context, room_id, session_id, turn_id, prompt,
                      identity, cancellation_demo=False):
    # require_fixture() was called by px-agent BEFORE session lock creation.
    require_fixture()
    require_id(turn_id, "turn ID")
    if prompt != "SYNTHETIC_SUM_1_TO_8":
        raise RuntimeError("INT1-B15 REFUSED // unsupported synthetic task")
    # Recheck before any accepted-turn action. Compare observations made
    # earlier in the real PX entry point; do not trust response metadata
    # as a transferable grant or inherit a native tool mode.
    from px_int1_fake_guard import require_profile
    from pathlib import Path
    registry = json.loads(Path("/fixture/providers/fake.json").read_text())
    record = (registry.get("providers") or {}).get(FAKE_ID)
    capability = require_fake_capability(FAKE_ID, record, registry)
    if identity.get("capability") != capability:
        raise RuntimeError("INT1-B21 REFUSED // fake capability changed")
    with connect() as conn:
        matched = _required_context_parity(conn, context, room_id, session_id)
    # No fake accepted-turn write happens until source continuity and Stage A
    # identity match. The B13 broker still starts before acceptance.
    ack = run(room_id, session_id, turn_id, prompt,
              scenario=("gated-tree-cancel" if cancellation_demo
                        else "gated-task"), task="SUM_1_TO_8")
    if ack["taskResult"] != "SYNTHETIC_SUM_36" or not ack["brokerReaped"]:
        raise RuntimeError("INT1-B15 REFUSED // verified task ACK missing")
    with connect() as conn:
        result = finalize_verified(conn, room_id, session_id, turn_id)
    return {
        **result,
        "providerId": FAKE_ID, "profile": PROFILE,
        "sessionId": session_id, "roomId": room_id,
        "operatorMessageId": ack["messageId"],
        "assistantMessageId": result["doctorMessageId"],
        "assistant": result["doctorReply"],
        "contextVersion": identity["contextVersion"],
        "requiredHandoffIds": identity["requiredHandoffIds"],
        "approvedRoomChartIds": identity["approvedRoomChartIds"],
        "approvedPatientChartIds": identity["approvedPatientChartIds"],
        "sourceDigestChecked": bool(matched["contextHash"]),
        "capability": capability,
        "syntheticFrames": ack["syntheticFrames"],
        "modelCalls": 0, "toolCalls": 0, "productionReady": False,
    }


def inspect_fake_turn(session_id, turn_id):
    # No status flag alone authorizes any mutable Doctor operation.
    require_fixture()
    require_id(session_id, "session ID")
    require_id(turn_id, "turn ID")
    # Read the actual Hospital identity before opening a separate fake ledger.
    from px_int1_fake_atomic import validate_live
    from px_int1_fake_guard import require_profile
    from px_int1_fake_atomic import FAKE_ID as FAKE
    # Strictly require only the accepted synthetic provider registry. Do not
    # assume that a session linked to this fixture authorizes native tools.
    import json
    from pathlib import Path
    registry = json.loads(Path("/fixture/providers/fake.json").read_text())
    require_profile(FAKE, registry["providers"][FAKE], registry)
    with connect() as conn:
        session = conn.execute(
            "SELECT s.room_id, s.doctor_id, r.doctor_id AS room_doctor,"
            " s.provider_id, r.provider_id AS room_provider "
            "FROM sessions s JOIN rooms r ON r.room_id=s.room_id "
            "WHERE s.session_id=?", (session_id,),
        ).fetchone()
        if (session is None or not session["room_id"] or
                not session["doctor_id"] or
                session["doctor_id"] != session["room_doctor"] or
                session["provider_id"] != FAKE or
                session["room_provider"] != FAKE):
            raise RuntimeError("INT1-B15 REFUSED // synthetic status identity mismatch")
        data = inspect(conn, session["room_id"], session_id, turn_id)
    return {**data, "profile": PROFILE, "providerId": FAKE}


def cancel_fake_turn(session_id, turn_id, reason):
    """B17: persist an exact-turn request through normal PX cancel.

    Does not alter the Room grant, signal an unverified PID or claim death.
    The live trusted supervisor checks this source-owned record and reaps
    the known nested child. If the supervisor crashed, B12 still requires
    explicit no-retry closure and termination is NOT inferred.
    """
    require_fixture()  # Before any Hospital or SQLite access.
    require_id(session_id, "session ID")
    require_id(turn_id, "turn ID")
    if (not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 256):
        raise RuntimeError("INT1-B16 REFUSED // bounded cancellation reason required")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            verify_hooks(conn)
            verify_b4(conn)
            session = conn.execute(
                """SELECT s.room_id,s.doctor_id,s.provider_id,
                          r.doctor_id AS room_doctor,
                          r.provider_id AS room_provider
                   FROM sessions s JOIN rooms r ON r.room_id=s.room_id
                   WHERE s.session_id=?""", (session_id,),
            ).fetchone()
            if (session is None or not session["room_id"] or
                    not session["doctor_id"] or
                    session["doctor_id"] != session["room_doctor"] or
                    session["provider_id"] != FAKE_ID or
                    session["room_provider"] != FAKE_ID):
                raise RuntimeError("INT1-B16 REFUSED // synthetic identity mismatch")
            room_id = session["room_id"]
            validate_live(conn, room_id, session_id)
            row = conn.execute(
                """SELECT t.generation,t.state AS turn_state,
                          d.state AS receipt_state,d.result AS receipt_result,
                          d.nonce_hash AS nonce_hash
                   FROM int1_fake_accepted_turns t
                   JOIN int1_fake_dispatch_receipts d
                     ON d.turn_id=t.turn_id
                   WHERE t.turn_id=? AND t.session_id=? AND t.room_id=?""",
                (turn_id, session_id, room_id),
            ).fetchone()
            if (row is None or row["turn_state"] != "ACCEPTED_UNDISPATCHED"
                    or row["receipt_state"] != "RESERVED"
                    or row["receipt_result"]):
                raise RuntimeError(
                    "INT1-B16 REFUSED // only an unresolved reserved synthetic "
                    "turn can request cancellation"
                )
            grant = authority_row(conn, room_id)
            if grant["revoked"] or grant["generation"] != row["generation"]:
                raise RuntimeError("INT1-B16 REFUSED // stale or revoked Room grant")
            # Receipt is immutable and source-owned; bind the cancellation
            # request to its exact generation and nonce, not only a string ID.
            if (not isinstance(row["nonce_hash"], str) or
                    len(row["nonce_hash"]) != 64 or
                    any(c not in "0123456789abcdef" for c in row["nonce_hash"])):
                raise RuntimeError("INT1-B17 REFUSED // invalid reservation nonce")
            conn.execute(CANCELLATIONS)
            if conn.execute(
                "SELECT 1 FROM int1_fake_turn_cancellations WHERE turn_id=?",
                (turn_id,),
            ).fetchone():
                raise RuntimeError("INT1-B17 REFUSED // cancellation already requested")
            conn.execute(
                "INSERT INTO int1_fake_turn_cancellations"
                "(turn_id,room_id,session_id,generation,nonce_hash)"
                "VALUES(?,?,?,?,?)",
                (turn_id, room_id, session_id, row["generation"], row["nonce_hash"]),
            )
            conn.execute(
                "INSERT INTO session_events(session_id,event_type,payload_json) "
                "VALUES(?,'turn.cancel.requested',?)",
                (session_id, json.dumps({
                    "turnId": turn_id, "roomId": room_id,
                    "reason": reason.strip(), "scope": "SINGLE_SYNTHETIC_TURN",
                    "workerTerminationVerified": False,
                    "automaticRetryAllowed": False, "fakeOnly": True,
                }, sort_keys=True)),
            )
            conn.commit()
            return {
                "roomId": room_id, "sessionId": session_id,
                "turnId": turn_id, "state": "CANCELLATION_REQUESTED",
                "cancelRequested": True, "roomAuthorityRevoked": False,
                "turnCancellationScoped": True,
                "workerTerminationVerified": False,
                "automaticRetryAllowed": False,
                "syntheticOnly": True, "productionReady": False,
            }
        except BaseException:
            conn.rollback()
            raise
