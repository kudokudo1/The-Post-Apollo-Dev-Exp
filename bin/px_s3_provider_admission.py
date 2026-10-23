#!/usr/bin/env python3
"""B24 fixture-only evidence evaluator. NO real provider can be authorized.

Pure dictionary validation: no OS inspection, credentials, files, model,
tool execution, native session or Hospital access. Input is untrusted data.
"""
import re

PROFILE = "EXEC_S3_MODEL_ONLY_V1"
KNOWN_PROVIDERS = frozenset(("codex", "hermes"))
SCHEMA = {
    "identity": ("absolutePath", "version", "binarySha256",
                 "configSha256", "argsSha256", "executorPinned"),
    "tools": ("nativeDisabled", "mcpDisabled", "hooksDisabled",
              "pluginsDisabled", "browserDisabled", "delegationDisabled"),
    "credentials": ("envAllowlisted", "noToolSecrets", "noHostHome",
                    "fdsClosed", "noAmbientSockets", "toolEgressDenied"),
    "ownership": ("kind", "sharedGateway", "turnStopVerified",
                  "descendantsReaped", "revocationFenced"),
    "resume": ("requested", "nativeStatePinned", "capabilitiesRechecked"),
    "authority": ("room", "patient", "assignment", "bed", "turnId",
                  "generation"),
    "provenance": ("origin", "kernelAttested", "realProviderObserved"),
}


def assess(candidate):
    """Diagnostic refusals only, not authentication or an allow decision."""
    deny = set()
    if type(candidate) is not dict:
        candidate = {}
        deny.add("SCHEMA_ROOT")
    expected_root = set(SCHEMA) | {"version", "providerId", "profile"}
    if set(candidate) != expected_root:
        deny.add("SCHEMA_ROOT")
    if type(candidate.get("version")) is not int or candidate["version"] != 1:
        deny.add("SCHEMA_VERSION")
    if type(candidate.get("providerId")) is not str or candidate["providerId"] not in KNOWN_PROVIDERS:
        deny.add("UNKNOWN_PROVIDER")
    if type(candidate.get("profile")) is not str or candidate["profile"] != PROFILE:
        deny.add("UNKNOWN_PROFILE")

    sections = {}
    for name, keys in SCHEMA.items():
        section = candidate.get(name)
        if type(section) is not dict or set(section) != set(keys):
            deny.add("SCHEMA_" + name.upper())
        sections[name] = section if type(section) is dict else {}

    ident = sections["identity"]
    path = ident.get("absolutePath")
    if (type(path) is not str or not path.startswith("/") or
            path == "/" or "\x00" in path or "//" in path or
            any(p in (".", "..") for p in path.split("/"))):
        deny.add("EXECUTABLE_PATH")
    version = ident.get("version")
    if type(version) is not str or re.fullmatch(r"[A-Za-z0-9][\w.+-]{0,127}", version) is None:
        deny.add("BINARY_VERSION")
    for key in ("binarySha256", "configSha256", "argsSha256"):
        value = ident.get(key)
        if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            deny.add("PIN_" + key.upper())
    if ident.get("executorPinned") is not True:
        deny.add("EXECUTOR_IDENTITY")

    for key in SCHEMA["tools"]:
        if sections["tools"].get(key) is not True:
            deny.add("NATIVE_TOOL_" + key.upper())
    for key in SCHEMA["credentials"]:
        if sections["credentials"].get(key) is not True:
            deny.add("CREDENTIAL_" + key.upper())

    owner = sections["ownership"]
    if owner.get("kind") not in ("PX_TURN_SCOPED", "PX_DEDICATED_GATEWAY"):
        deny.add("EXECUTION_OWNER")
    if owner.get("sharedGateway") is not False:
        deny.add("SHARED_GATEWAY")
    for key in ("turnStopVerified", "descendantsReaped", "revocationFenced"):
        if owner.get(key) is not True:
            deny.add("CANCEL_" + key.upper())

    resume = sections["resume"]
    if type(resume.get("requested")) is not bool:
        deny.add("RESUME_REQUEST")
    for key in ("nativeStatePinned", "capabilitiesRechecked"):
        expected = resume.get("requested") is True
        if resume.get(key) is not expected:
            deny.add("RESUME_" + key.upper())

    authority = sections["authority"]
    for key in ("room", "patient", "assignment", "bed", "turnId"):
        val = authority.get(key)
        if type(val) is not str or not val.strip() or len(val) > 256:
            deny.add("AUTHORITY_" + key.upper())
    generation = authority.get("generation")
    if type(generation) is not int or generation < 1:
        deny.add("AUTHORITY_GENERATION")

    provenance = sections["provenance"]
    if (provenance.get("origin") != "UNTRUSTED_SYNTHETIC_FIXTURE" or
            provenance.get("kernelAttested") is not False or
            provenance.get("realProviderObserved") is not False):
        deny.add("UNTRUSTED_ATTESTATION")

    # No trusted OS adapter or model-only transport exists in B24. The
    # synthetic evidence cannot ever be promoted, even if every flag passes.
    deny.add("REAL_PROVIDER_PRODUCTION_HOLD")
    return {"decision": "DENY", "reasons": sorted(deny),
            "launchAuthorized": False, "modelCalls": 0,
            "toolCalls": 0, "hospitalWrites": 0,
            "productionReady": False}


def require_secure_admission(candidate):
    """Fail closed at any attempted dispatch; never return a launch token."""
    proof = assess(candidate)
    raise RuntimeError("B24 REFUSED // " + ",".join(proof["reasons"]))
