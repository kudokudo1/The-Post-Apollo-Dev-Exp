#!/usr/bin/env python3
"""B15: narrow opt-in real px-agent seam to a disposable synthetic Doctor.

The trusted px-agent performs ordinary Session/Room/Bed/context Stage A first.
No provider process is started, no shell/host tools can be requested, and the
real Hospital database is never opened by this fake execution profile.
"""
from px_int1_fake_guard import (
    PROFILE, FAKE_ID, require_fixture, require_profile,
    require_doctor_room_binding,
)
from px_int1_fake_atomic import (
    connect, context_digest, continuity_document, require_id,
)
from px_int1_fake_lifecycle import run, finalize_verified, inspect


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
                      identity):
    # require_fixture() was called by px-agent BEFORE session lock creation.
    require_fixture()
    require_id(turn_id, "turn ID")
    if prompt != "SYNTHETIC_SUM_1_TO_8":
        raise RuntimeError("INT1-B15 REFUSED // unsupported synthetic task")
    with connect() as conn:
        matched = _required_context_parity(conn, context, room_id, session_id)
    # No fake accepted-turn write happens until source continuity and Stage A
    # identity match. The B13 broker still starts before acceptance.
    ack = run(room_id, session_id, turn_id, prompt,
              scenario="gated-task", task="SUM_1_TO_8")
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
