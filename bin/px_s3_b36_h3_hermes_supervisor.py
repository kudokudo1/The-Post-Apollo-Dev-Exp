#!/usr/bin/env python3
"""B36-H3 offline trusted-supervisor adapter contract.

This module validates untrusted dictionaries only. It never contacts Hospital,
Hermes, a kernel API, credentials, sockets, files, or subprocesses. Even a
synthetically perfect envelope remains DENY until a real trusted supervisor
boundary and independently verified teardown path exist.
"""

from px_s3_b36_hermes_recovery_fence import _scope_valid

SCHEMA = "B36_H3_HERMES_SUPERVISOR_OFFLINE_V1"
SUPERVISOR_KEYS = frozenset((
    "supervisorId", "hospitalAuthorityFresh", "authorityGeneration",
    "dedicatedGateway", "gatewayIdentityVerified", "restartFenced",
    "nativeToolsDisabled", "credentialsConfined",
))
STOP_KEYS = frozenset((
    "intent", "requestId", "gatewayAck", "gatewayAckAuthenticated",
    "kernelEvidenceId", "descendantsEmpty", "observedGeneration",
))
EXPECTED_KEYS = frozenset(("schema", "provider", "scope", "supervisor", "stop"))
STOP_INTENTS = frozenset(("NONE", "CANCEL_CURRENT_TURN", "REVOKE_OWNER"))
ACK_STATES = frozenset(("NONE", "STOP_ACK"))


def _ascii_id(value, prefix):
    return (
        type(value) is str
        and value.startswith(prefix)
        and len(prefix) + 3 <= len(value) <= 96
        and value.isascii()
        and all(ch.isalnum() or ch in "-_:." for ch in value)
    )


def assess(candidate, expected_scope, expected_generation):
    """Assess an offline supervisor envelope. Every result is DENY."""
    reasons = set()
    if type(candidate) is not dict:
        candidate = {}
        reasons.add("SCHEMA_ROOT")
    if set(candidate) != EXPECTED_KEYS:
        reasons.add("SCHEMA_ROOT")
    if candidate.get("schema") != SCHEMA or type(candidate.get("schema")) is not str:
        reasons.add("SCHEMA_VERSION")
    if candidate.get("provider") != "hermes" or type(candidate.get("provider")) is not str:
        reasons.add("PROVIDER_IDENTITY")

    scope = candidate.get("scope")
    if not _scope_valid(scope):
        reasons.add("SCOPE_INVALID")
    if not _scope_valid(expected_scope):
        reasons.add("EXPECTED_SCOPE_INVALID")
    if _scope_valid(scope) and _scope_valid(expected_scope):
        for key in scope:
            if scope[key] != expected_scope[key]:
                reasons.add("AUTHORITY_" + key.upper() + "_MISMATCH")

    if type(expected_generation) is not int or expected_generation <= 0:
        reasons.add("EXPECTED_GENERATION_INVALID")

    supervisor = candidate.get("supervisor")
    if type(supervisor) is not dict or set(supervisor) != SUPERVISOR_KEYS:
        reasons.add("SUPERVISOR_SCHEMA")
        supervisor = {}
    if not _ascii_id(supervisor.get("supervisorId"), "px-supervisor-"):
        reasons.add("SUPERVISOR_IDENTITY")
    if supervisor.get("hospitalAuthorityFresh") is not True:
        reasons.add("HOSPITAL_AUTHORITY_NOT_FRESH")
    if type(supervisor.get("authorityGeneration")) is not int:
        reasons.add("SUPERVISOR_GENERATION_INVALID")
    elif type(expected_generation) is int and expected_generation > 0:
        if supervisor["authorityGeneration"] != expected_generation:
            reasons.add("SUPERVISOR_GENERATION_MISMATCH")
    for key, reason in (
        ("dedicatedGateway", "DEDICATED_GATEWAY_UNVERIFIED"),
        ("gatewayIdentityVerified", "GATEWAY_IDENTITY_UNVERIFIED"),
        ("restartFenced", "RESTART_FENCE_UNVERIFIED"),
        ("nativeToolsDisabled", "NATIVE_TOOLS_UNVERIFIED"),
        ("credentialsConfined", "CREDENTIALS_UNVERIFIED"),
    ):
        if supervisor.get(key) is not True:
            reasons.add(reason)

    stop = candidate.get("stop")
    if type(stop) is not dict or set(stop) != STOP_KEYS:
        reasons.add("STOP_SCHEMA")
        stop = {}

    intent = stop.get("intent")
    if type(intent) is not str or intent not in STOP_INTENTS:
        reasons.add("STOP_INTENT_INVALID")
    if not _ascii_id(stop.get("requestId"), "stop-"):
        reasons.add("STOP_REQUEST_ID_INVALID")

    ack = stop.get("gatewayAck")
    if type(ack) is not str or ack not in ACK_STATES:
        reasons.add("GATEWAY_ACK_INVALID")

    if intent == "NONE":
        if ack != "NONE":
            reasons.add("ACK_WITHOUT_STOP_INTENT")
        if stop.get("gatewayAckAuthenticated") is not False:
            reasons.add("ACK_AUTH_WITHOUT_STOP_INTENT")
        if stop.get("descendantsEmpty") is not False:
            reasons.add("KERNEL_EVIDENCE_WITHOUT_STOP_INTENT")
    else:
        if ack != "STOP_ACK":
            reasons.add("STOP_ACK_MISSING")
        if stop.get("gatewayAckAuthenticated") is not True:
            reasons.add("STOP_ACK_UNAUTHENTICATED")
        if not _ascii_id(stop.get("kernelEvidenceId"), "kernel-"):
            reasons.add("KERNEL_EVIDENCE_ID_INVALID")
        if stop.get("descendantsEmpty") is not True:
            reasons.add("DESCENDANTS_NOT_VERIFIED_EMPTY")

    observed_generation = stop.get("observedGeneration")
    if type(observed_generation) is not int or observed_generation <= 0:
        reasons.add("OBSERVED_GENERATION_INVALID")
    elif type(expected_generation) is int and expected_generation > 0:
        if observed_generation != expected_generation:
            reasons.add("OBSERVED_GENERATION_MISMATCH")

    # A gateway ACK is protocol evidence, not kernel teardown evidence.
    # Kernel evidence is also not trusted merely because a dict says so.
    reasons.add("TRUSTED_SUPERVISOR_RUNTIME_UNAVAILABLE")
    reasons.add("KERNEL_ATTESTATION_UNAVAILABLE")
    reasons.add("REAL_PROVIDER_PRODUCTION_HOLD")

    # Security diagnostics contain only fixed schema/status fields and reason codes.
    # Untrusted candidate data must never be copied or echoed into results.
    return {
        "schema": SCHEMA,
        "decision": "DENY",
        "reasons": sorted(reasons),
        "launchAuthorized": False,
        "resumeAuthorized": False,
        "terminationVerified": False,
        "gatewayAckTrusted": False,
        "kernelEvidenceTrusted": False,
        "modelCalls": 0,
        "toolCalls": 0,
        "gatewayCalls": 0,
        "hospitalWrites": 0,
        "productionReady": False,
    }


def require_supervisor_admission(candidate, expected_scope, expected_generation):
    result = assess(candidate, expected_scope, expected_generation)
    raise RuntimeError("B36-H3 REFUSED // " + ",".join(result["reasons"]))
