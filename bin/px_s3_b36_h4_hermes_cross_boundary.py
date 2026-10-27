#!/usr/bin/env python3
"""B36-H4 cross-boundary negative integration, offline only.

Compose existing B36-H1 recovery, H2 fake owner, H3 untrusted supervisor,
and B24 fake provider refusal. All four remain DENY. This module neither
trusts caller-supplied "expected" authority nor creates an execution grant.
Returns only fixed reason codes and booleans, never input payloads.
"""
from px_s3_b36_hermes_recovery_fence import assess as assess_h1, _scope_valid
from px_s3_b36_h2_hermes_owner_lifecycle import assess_transition as assess_h2
from px_s3_b36_h3_hermes_supervisor import assess as assess_h3
from px_s3_provider_admission import assess as assess_b24

SCHEMA = "B36_H4_HERMES_CROSS_BOUNDARY_OFFLINE_V1"
KEYS = frozenset(("schema", "recovery", "ownerState", "ownerEvent",
                  "supervisor", "providerEvidence"))
KINDS = frozenset(("RESERVE", "REQUEST_STOP", "ACK_STOP", "OBSERVE_EXIT",
                   "REVOKE", "CRASH_UNKNOWN", "NATIVE_AUTO_RESUME",
                   "PLATFORM_RECONNECT"))
AUTO_KINDS = frozenset(("NATIVE_AUTO_RESUME", "PLATFORM_RECONNECT"))
STOP_INTENT = {
    "RESERVE": "NONE",
    "REQUEST_STOP": "CANCEL_CURRENT_TURN",
    "ACK_STOP": "CANCEL_CURRENT_TURN",
    "OBSERVE_EXIT": "CANCEL_CURRENT_TURN",
    "REVOKE": "REVOKE_OWNER",
    "CRASH_UNKNOWN": "REVOKE_OWNER",
    "NATIVE_AUTO_RESUME": "REVOKE_OWNER",
    "PLATFORM_RECONNECT": "REVOKE_OWNER",
}
H1_CANCEL = {
    "RESERVE": "NONE",
    "REQUEST_STOP": "REQUESTED",
    "ACK_STOP": "ACKNOWLEDGED",
    "OBSERVE_EXIT": "TERMINATED_VERIFIED",
    "REVOKE": "REQUESTED",
    "CRASH_UNKNOWN": "UNVERIFIED",
    "NATIVE_AUTO_RESUME": "UNVERIFIED",
    "PLATFORM_RECONNECT": "UNVERIFIED",
}


def _dict(value):
    return value if type(value) is dict else {}


def _component(fn, *args):
    """A component failure must never turn into a launch or raw-data echo."""
    try:
        result = fn(*args)
        if type(result) is dict and result.get("decision") == "DENY":
            return result, True
    except Exception:
        pass
    return {}, False


def assess(case, expected_scope, expected_generation):
    """Diagnostic evaluation of four independently untrusted fixture domains."""
    reasons = set()
    if type(case) is not dict:
        case = {}
        reasons.add("ROOT_SCHEMA")
    if set(case) != KEYS or type(case.get("schema")) is not str or case.get("schema") != SCHEMA:
        reasons.add("ROOT_SCHEMA")
    if not _scope_valid(expected_scope):
        reasons.add("EXPECTED_SCOPE_INVALID")
    if type(expected_generation) is not int or expected_generation <= 0:
        reasons.add("EXPECTED_GENERATION_INVALID")
    elif _scope_valid(expected_scope) and expected_scope["generation"] != expected_generation:
        reasons.add("EXPECTED_GENERATION_MISMATCH")

    recovery = _dict(case.get("recovery"))
    owner_state = _dict(case.get("ownerState"))
    owner_event = _dict(case.get("ownerEvent"))
    supervisor = _dict(case.get("supervisor"))

    proofs = {}
    proofs["H1"], h1_valid = _component(assess_h1, recovery, expected_scope)
    proofs["H2"], h2_valid = _component(assess_h2, owner_state, owner_event)
    proofs["H3"], h3_valid = _component(assess_h3, supervisor, expected_scope, expected_generation)
    proofs["B24"], b24_valid = _component(assess_b24, case.get("providerEvidence"))
    for label, valid in (("H1", h1_valid), ("H2", h2_valid),
                         ("H3", h3_valid), ("B24", b24_valid)):
        if not valid:
            reasons.add("COMPONENT_" + label + "_UNAVAILABLE")
    for label, source in (("RECOVERY", recovery), ("OWNER_STATE", owner_state),
                          ("OWNER_EVENT", owner_event), ("SUPERVISOR", supervisor)):
        scope = source.get("scope")
        if not _scope_valid(scope) or not _scope_valid(expected_scope) or scope != expected_scope:
            reasons.add(label + "_SCOPE_MISMATCH")

    kind = owner_event.get("kind")
    if type(kind) is not str or kind not in KINDS:
        reasons.add("OWNER_EVENT_KIND_INVALID")
    else:
        if owner_state.get("ownerId") != owner_event.get("ownerId"):
            reasons.add("OWNER_IDENTITY_MISMATCH")
        if owner_state.get("phase") in ("CLOSED_FAKE", "QUARANTINED_FAKE"):
            reasons.add("TERMINAL_OWNER_REENTRY")
        if owner_event.get("scope") != owner_state.get("scope"):
            reasons.add("OWNER_EVENT_STATE_SCOPE_MISMATCH")

        if _dict(supervisor.get("stop")).get("intent") != STOP_INTENT[kind]:
            reasons.add("STOP_INTENT_STAGE_MISMATCH")
        if recovery.get("cancellation") != H1_CANCEL[kind]:
            reasons.add("CANCELLATION_STAGE_MISMATCH")

        # An ACK must not be projected backward to REQUEST_STOP, and
        # an OS-exit claim must not be projected backward to ACK_STOP.
        stop = _dict(supervisor.get("stop"))
        ack_needed = kind in ("ACK_STOP", "OBSERVE_EXIT")
        kernel_needed = kind == "OBSERVE_EXIT"
        if ((stop.get("gatewayAck") == "STOP_ACK") != ack_needed
                or (stop.get("gatewayAckAuthenticated") is True) != ack_needed):
            reasons.add("GATEWAY_ACK_STAGE_MISMATCH")
        if ((stop.get("descendantsEmpty") is True) != kernel_needed
                or bool(stop.get("kernelEvidenceId")) != kernel_needed):
            reasons.add("KERNEL_CLAIM_STAGE_MISMATCH")

        expected_trigger = {
            "NATIVE_AUTO_RESUME": "STARTUP_AUTO_RESUME",
            "PLATFORM_RECONNECT": "PLATFORM_RECONNECT",
        }
        if kind in AUTO_KINDS:
            reasons.add("AUTOMATIC_NATIVE_REPLAY_FORBIDDEN")
            if recovery.get("trigger") != expected_trigger[kind]:
                reasons.add("RECOVERY_TRIGGER_EVENT_MISMATCH")
        elif recovery.get("trigger") in ("STARTUP_AUTO_RESUME", "PLATFORM_RECONNECT"):
            reasons.add("RECOVERY_TRIGGER_EVENT_MISMATCH")

        if kind == "OBSERVE_EXIT":
            # This is always a claim from a FAKE owner, even when H2 closed.
            reasons.add("FAKE_CGROUP_RECEIPT_NOT_KERNEL_ATTESTATION")

    if h2_valid and proofs["H2"].get("fixtureOutcome") == "REFUSED":
        reasons.add("OWNER_LIFECYCLE_REFUSED")
    if h3_valid and any(value in proofs["H3"].get("reasons", ()) for value in (
            "SUPERVISOR_GENERATION_MISMATCH", "HOSPITAL_AUTHORITY_NOT_FRESH",
            "NATIVE_TOOLS_UNVERIFIED", "CREDENTIALS_UNVERIFIED",
            "RESTART_FENCE_UNVERIFIED", "STOP_ACK_UNAUTHENTICATED")):
        reasons.add("SUPERVISOR_PRECONDITIONS_UNVERIFIED")

    # No concrete identical gateway owner is present across H1/H2/H3. H2
    # uses fake-gateway-*, H3 has only gatewayIdentityVerified: bool. There
    # is no durable Hospital authority or OS authenticated receipt source.
    reasons.update(("CROSS_GATEWAY_IDENTITY_BINDING_UNAVAILABLE",
                    "TRUSTED_HOSPITAL_AUTHORITY_UNAVAILABLE",
                    "KERNEL_ATTESTATION_UNAVAILABLE",
                    "REAL_PROVIDER_PRODUCTION_HOLD"))

    outcome = proofs["H2"].get("fixtureOutcome") if h2_valid else "REFUSED"
    if outcome not in ("SIMULATED_STEP", "SIMULATED_QUARANTINE"):
        outcome = "REFUSED"
    return {
        "schema": SCHEMA, "decision": "DENY", "reasons": sorted(reasons),
        "fakeTransition": outcome, "launchAuthorized": False,
        "resumeAuthorized": False, "terminationVerified": False,
        "gatewayAckTrusted": False, "kernelEvidenceTrusted": False,
        "toolGrants": 0, "modelCalls": 0, "gatewayCalls": 0,
        "toolCalls": 0, "hospitalWrites": 0, "productionReady": False,
    }


def require_real_hermes_execution(case, expected_scope, expected_generation):
    """No real gateway approval or model call can originate in H4."""
    outcome = assess(case, expected_scope, expected_generation)
    raise RuntimeError("B36-H4 REFUSED // " + ",".join(outcome["reasons"]))
