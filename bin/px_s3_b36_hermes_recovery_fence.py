#!/usr/bin/env python3
"""B36 offline-only Hermes replay/authority fence diagnostics.

Accepts untrusted dictionaries, never grants execution. In particular, a
Hermes gateway's own recovery state/allowlist cannot authorize a Hospital
Doctor turn. No providers, gateway, Hospital, files, credentials or network.
"""

SCHEMA = "B36_HERMES_RECOVERY_FENCE_V1"
SCOPE_KEYS = ("patient", "room", "assignment", "session", "turn", "generation")
TRIGGERS = frozenset(("STARTUP_AUTO_RESUME", "PLATFORM_RECONNECT", "NEW_MESSAGE", "MANUAL_RECOVERY"))
AUTO_TRIGGERS = frozenset(("STARTUP_AUTO_RESUME", "PLATFORM_RECONNECT"))
RECOVERY_REASONS = frozenset(("restart_timeout", "shutdown_timeout", "restart_interrupted"))
GATEWAY_KEYS = ("dedicated", "sharedGateway", "autoContinueDisabled", "nativeToolsDisabled",
                "ownerVerified", "turnStopVerified", "descendantsTerminated",
                "credentialsConfined", "revocationFenced")
EXPECTED_KEYS = {"schema", "provider", "trigger", "resumeReason", "scope", "gateway", "cancellation"}
CANCELLATION_STATES = frozenset(("NONE", "REQUESTED", "ACKNOWLEDGED", "TERMINATED_VERIFIED", "UNVERIFIED"))


def _scope_valid(scope):
    if type(scope) is not dict or set(scope) != set(SCOPE_KEYS):
        return False
    for key in SCOPE_KEYS[:-1]:
        val = scope.get(key)
        if type(val) is not str or not val.strip() or len(val) > 256:
            return False
    return type(scope.get("generation")) is int and scope["generation"] > 0


def assess(candidate, expected_scope):
    """Explain refusals. All outcomes DENY, even if asserted flags pass."""
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

    trigger = candidate.get("trigger")
    if type(trigger) is not str or trigger not in TRIGGERS:
        reasons.add("TRIGGER_INVALID")
    elif trigger in AUTO_TRIGGERS:
        reasons.add("AUTOMATIC_RESUME_FORBIDDEN")
    elif trigger == "MANUAL_RECOVERY":
        reasons.add("EXPLICIT_NEW_TURN_REQUIRED")

    reason = candidate.get("resumeReason")
    if type(reason) is not str or reason not in RECOVERY_REASONS | {"NONE"}:
        reasons.add("RECOVERY_REASON_INVALID")
    elif trigger in AUTO_TRIGGERS and reason not in RECOVERY_REASONS:
        reasons.add("RECOVERY_REASON_MISMATCH")
    elif trigger == "NEW_MESSAGE" and reason != "NONE":
        reasons.add("RESTART_RECOVERY_MASQUERADES_AS_NEW_TURN")

    scope = candidate.get("scope")
    if not _scope_valid(scope):
        reasons.add("SCOPE_INVALID")
    if not _scope_valid(expected_scope):
        reasons.add("EXPECTED_SCOPE_INVALID")
    if _scope_valid(scope) and _scope_valid(expected_scope):
        for key in SCOPE_KEYS:
            if scope[key] != expected_scope[key]:
                reasons.add("AUTHORITY_" + key.upper() + "_MISMATCH")

    gateway = candidate.get("gateway")
    if type(gateway) is not dict or set(gateway) != set(GATEWAY_KEYS):
        reasons.add("GATEWAY_SCHEMA")
    gateway = gateway if type(gateway) is dict else {}
    if gateway.get("dedicated") is not True or gateway.get("sharedGateway") is not False:
        reasons.add("DEDICATED_GATEWAY_UNVERIFIED")
    for key in GATEWAY_KEYS:
        if key in ("dedicated", "sharedGateway"):
            continue
        if gateway.get(key) is not True:
            reasons.add("GATEWAY_" + key.upper() + "_UNVERIFIED")

    cancellation = candidate.get("cancellation")
    if type(cancellation) is not str or cancellation not in CANCELLATION_STATES:
        reasons.add("CANCELLATION_STATE_INVALID")
    elif cancellation != "NONE":
        # Native ACK and textual 'terminated' claims are not OS teardown proof.
        reasons.add("CANCELLATION_RECONCILIATION_REQUIRED")

    # Neither candidate assertions nor caller-supplied expected_scope are
    # trusted Hospital authority. No integrated native Hermes adapter exists.
    reasons.add("TRUSTED_HOSPITAL_AUTHORITY_UNAVAILABLE")
    reasons.add("REAL_PROVIDER_PRODUCTION_HOLD")
    return {
        "schema": SCHEMA, "provider": "hermes", "decision": "DENY",
        "reasons": sorted(reasons), "launchAuthorized": False,
        "resumeAuthorized": False, "toolGrants": 0, "modelCalls": 0,
        "gatewayCalls": 0, "hospitalWrites": 0, "productionReady": False,
    }


def require_hermes_recovery_admission(candidate, expected_scope):
    """No native launch token, even for synthetically perfect candidates."""
    result = assess(candidate, expected_scope)
    raise RuntimeError("B36 REFUSED // " + ",".join(result["reasons"]))
