#!/usr/bin/env python3
"""B36-H2 pure disposable Hermes owner fixture; no real owner or execution.

This module is an untrusted-data state machine. Any simulated lifecycle
progression remains distinct from kernel receipts, Hospital authority and
admission. It never starts, contacts, interrupts, or certifies Hermes.
"""
from copy import deepcopy

from px_s3_b36_hermes_recovery_fence import _scope_valid

SCHEMA = "B36_H2_HERMES_OWNER_FIXTURE_V1"
STATE_KEYS = frozenset(("schema", "scope", "ownerId", "phase", "sequence", "lastEventId"))
EVENT_KEYS = frozenset(("kind", "scope", "ownerId", "sequence", "eventId", "receipt"))
PHASES = frozenset(("UNALLOCATED", "RESERVED_FAKE", "STOP_REQUESTED_FAKE",
                    "ACK_OBSERVED_FAKE", "CLOSED_FAKE", "QUARANTINED_FAKE"))
RECEIPTS = frozenset(("NONE", "FAKE_GATEWAY_ACK", "FAKE_KERNEL_CGROUP_EMPTY"))
KINDS = frozenset(("RESERVE", "REQUEST_STOP", "ACK_STOP", "OBSERVE_EXIT",
                   "REVOKE", "CRASH_UNKNOWN", "NATIVE_AUTO_RESUME", "PLATFORM_RECONNECT"))
TERMINAL = frozenset(("CLOSED_FAKE", "QUARANTINED_FAKE"))


def _owner_valid(owner):
    return type(owner) is str and owner.startswith("fake-gateway-") and 13 < len(owner) <= 80 and owner.isascii() and all(
        char.isalnum() or char in "-_" for char in owner
    )


def _id_valid(value):
    return (type(value) is str and value.startswith("fake-event-")
            and 11 < len(value) <= 80 and value.isascii()
            and all(char.isalnum() or char in "-_" for char in value))


def _state_valid(state):
    return (type(state) is dict and set(state) == STATE_KEYS
            and state.get("schema") == SCHEMA and type(state.get("schema")) is str
            and _scope_valid(state.get("scope")) and _owner_valid(state.get("ownerId"))
            and type(state.get("phase")) is str and state["phase"] in PHASES
            and type(state.get("sequence")) is int and state["sequence"] >= 0
            and ((state["sequence"] == 0 and state["phase"] == "UNALLOCATED")
                 or (state["sequence"] > 0 and state["phase"] != "UNALLOCATED"))
            and (state.get("lastEventId") == "" if state["sequence"] == 0
                 else _id_valid(state.get("lastEventId"))))


def new_fixture(scope, owner_id):
    """Seed an inactive fake fixture; never create a process or real lease."""
    if not _scope_valid(scope) or not _owner_valid(owner_id):
        raise ValueError("B36_H2_REFUSED_FIXTURE_IDENTITY")
    return {"schema": SCHEMA, "scope": deepcopy(scope), "ownerId": owner_id,
            "phase": "UNALLOCATED", "sequence": 0, "lastEventId": ""}


def assess_transition(state, event):
    """Simulate exact-scoped lifecycle transitions, always deny real launch."""
    reasons = set()
    if not _state_valid(state):
        reasons.add("INVALID_PRIOR_FIXTURE")
    if type(event) is not dict or set(event) != EVENT_KEYS:
        reasons.add("EVENT_SCHEMA")
        event = {}  # no unexpected fields may influence a transition

    kind = event.get("kind")
    if type(kind) is not str or kind not in KINDS:
        reasons.add("EVENT_KIND")
    if not _scope_valid(event.get("scope")):
        reasons.add("EVENT_SCOPE")
    if not _owner_valid(event.get("ownerId")):
        reasons.add("EVENT_OWNER")
    if type(event.get("sequence")) is not int or event["sequence"] < 1:
        reasons.add("EVENT_SEQUENCE")
    if not _id_valid(event.get("eventId")):
        reasons.add("EVENT_ID")
    if type(event.get("receipt")) is not str or event["receipt"] not in RECEIPTS:
        reasons.add("RECEIPT_KIND")

    if _state_valid(state):
        if _scope_valid(event.get("scope")) and event["scope"] != state["scope"]:
            reasons.add("HOSPITAL_SCOPE_MISMATCH")
        if _owner_valid(event.get("ownerId")) and event["ownerId"] != state["ownerId"]:
            reasons.add("OWNER_IDENTITY_MISMATCH")
        if type(event.get("sequence")) is int and event["sequence"] != state["sequence"] + 1:
            reasons.add("SEQUENCE_REPLAY_OR_GAP")
        if _id_valid(event.get("eventId")) and event["eventId"] == state["lastEventId"]:
            reasons.add("EVENT_REPLAY")
        if state["phase"] in TERMINAL:
            reasons.add("TERMINAL_FIXTURE_NO_REENTRY")

    next_phase = None
    required = {
        "RESERVE": ("UNALLOCATED", "NONE", "RESERVED_FAKE"),
        "REQUEST_STOP": ("RESERVED_FAKE", "NONE", "STOP_REQUESTED_FAKE"),
        "ACK_STOP": ("STOP_REQUESTED_FAKE", "FAKE_GATEWAY_ACK", "ACK_OBSERVED_FAKE"),
        "OBSERVE_EXIT": ("ACK_OBSERVED_FAKE", "FAKE_KERNEL_CGROUP_EMPTY", "CLOSED_FAKE"),
    }
    if not reasons:
        if kind in required:
            phase, receipt, next_phase = required[kind]
            if state["phase"] != phase:
                reasons.add("LIFECYCLE_ORDER")
            if event["receipt"] != receipt:
                reasons.add("RECEIPT_MISMATCH")
        elif kind in ("REVOKE", "CRASH_UNKNOWN", "NATIVE_AUTO_RESUME", "PLATFORM_RECONNECT"):
            if event["receipt"] != "NONE":
                reasons.add("RECEIPT_MISMATCH")
            else:
                next_phase = "QUARANTINED_FAKE"
                if kind in ("NATIVE_AUTO_RESUME", "PLATFORM_RECONNECT"):
                    reasons.add("NATIVE_AUTOMATIC_REPLAY_FORBIDDEN")
                    # Still quarantine the fixture to model revocation of any lease.
        else:
            reasons.add("EVENT_KIND")

    # Auto-resume explicitly quarantines when the event envelope is otherwise
    # valid. Other invalid input never advances a fixture or claims teardown.
    auto_quarantine = (kind in ("NATIVE_AUTO_RESUME", "PLATFORM_RECONNECT")
                       and reasons == {"NATIVE_AUTOMATIC_REPLAY_FORBIDDEN"})
    advanced = not reasons or auto_quarantine
    out_state = deepcopy(state) if _state_valid(state) else None
    if advanced:
        out_state["phase"] = next_phase
        out_state["sequence"] = event["sequence"]
        out_state["lastEventId"] = event["eventId"]

    # Fake ACK + fake kernel observation are test symbols only, NEVER proof.
    reasons.update(("TRUSTED_HOSPITAL_OWNER_UNAVAILABLE", "REAL_PROVIDER_PRODUCTION_HOLD"))
    return {"schema": SCHEMA, "decision": "DENY", "fixtureOutcome": (
        "SIMULATED_QUARANTINE" if auto_quarantine else
        "SIMULATED_STEP" if advanced else "REFUSED"),
        "nextState": out_state, "reasons": sorted(reasons),
        "realGatewayLaunched": False, "realGatewayStopped": False,
        "terminationVerified": False, "launchAuthorized": False,
        "resumeAuthorized": False, "modelCalls": 0, "toolCalls": 0,
        "gatewayCalls": 0, "hospitalWrites": 0, "productionReady": False}


def require_real_gateway_owner(state, event):
    """No path from this fixture to real gateway execution."""
    result = assess_transition(state, event)
    raise RuntimeError("B36-H2 REFUSED // " + ",".join(result["reasons"]))
