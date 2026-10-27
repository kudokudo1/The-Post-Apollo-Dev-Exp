#!/usr/bin/env python3
"""B36-H7: assess H6's SANITIZED inventory, not the host or Hermes itself.

Pure, fail-closed read-only inference on untrusted H6 JSON. The optional
--stdin command consumes only a bounded serialized H6 report. NO /proc,
Hermes, credentials, subprocess, sockets, network or filesystem probing.
Capability indicators are never security proofs or execution grants.
"""
import json
import sys

from px_s3_b36_h6_readonly_host_inventory import (
    SCHEMA as H6_SCHEMA, REASONS as H6_REASONS,
    KNOWN_CONTROLLERS, NAMESPACE_KINDS, TOOLS,
)

SCHEMA = "B36_H7_FEDORA_FEASIBILITY_REVIEW_V1"
MAX_INPUT_BYTES = 16384
H6_FIELDS = frozenset((
    "schema", "decision", "inventoryOnly", "kernelAttested",
    "credentialBoundaryCertified", "nativeToolsDisabled",
    "networkEgressDenied", "cgroupDelegationCertified",
    "gatewayStopAuthenticated", "descendantTeardownCertified",
    "launchAuthorized", "modelCalls", "gatewayCalls", "toolCalls",
    "hospitalWrites", "productionReady", "observations", "reasons",
))
OBS_FIELDS = frozenset((
    "fedoraSilverblueReported", "cgroupV2MountedAtStandardPath",
    "selfCgroupV2Member", "visibleCgroupControllers",
    "currentProcessNoNewPrivs", "currentProcessSeccompMode",
    "unprivilegedUsernsSysctlAllows", "maxUserNamespacesPositive",
    "selinuxEnforcing", "namespaceLinksPresent",
    "toolExecutablesPresent", "userBusSocketPresent",
))
OBS_TRI_FIELDS = (
    "fedoraSilverblueReported", "cgroupV2MountedAtStandardPath",
    "selfCgroupV2Member", "currentProcessNoNewPrivs",
    "unprivilegedUsernsSysctlAllows", "maxUserNamespacesPositive",
    "selinuxEnforcing", "userBusSocketPresent",
)
SAFETY_FALSE = (
    "kernelAttested", "credentialBoundaryCertified", "nativeToolsDisabled",
    "networkEgressDenied", "cgroupDelegationCertified",
    "gatewayStopAuthenticated", "descendantTeardownCertified",
    "launchAuthorized", "productionReady",
)
ZERO_KEYS = ("modelCalls", "gatewayCalls", "toolCalls", "hospitalWrites")
FIXED_REASONS = (
    "REAL_PROVIDER_PRODUCTION_HOLD",
    "HOSPITAL_AUTHORITY_NOT_CONNECTED",
    "HERMES_NATIVE_TOOL_DENIAL_UNPROVEN",
    "HERMES_TURN_STOP_UNPROVEN",
    "KERNEL_DESCENDANT_CONTAINMENT_UNPROVEN",
    "HOST_INVENTORY_IS_NOT_OS_ATTESTATION",
)


def _tri(value):
    return value is None or type(value) is bool


def _valid_report(report):
    if type(report) is not dict or set(report) != H6_FIELDS:
        return False
    if (type(report.get("schema")) is not str or report["schema"] != H6_SCHEMA
            or report.get("decision") != "DENY"
            or report.get("inventoryOnly") is not True):
        return False
    if any(report.get(key) is not False for key in SAFETY_FALSE):
        return False
    if any(type(report.get(key)) is not int or report[key] != 0 for key in ZERO_KEYS):
        return False
    expected_reasons = sorted(set(H6_REASONS))
    if (type(report.get("reasons")) is not list
            or report["reasons"] != expected_reasons):
        # An H6 invalid/malformed snapshot is not a usable host inventory.
        return False

    obs = report.get("observations")
    if type(obs) is not dict or set(obs) != OBS_FIELDS:
        return False
    if any(not _tri(obs.get(key)) for key in OBS_TRI_FIELDS):
        return False
    if (type(obs.get("currentProcessSeccompMode")) is not int
            and obs.get("currentProcessSeccompMode") is not None):
        return False
    if obs["currentProcessSeccompMode"] not in (None, 0, 1, 2):
        return False
    ctrls = obs.get("visibleCgroupControllers")
    if (type(ctrls) is not list or len(ctrls) > len(KNOWN_CONTROLLERS)
            or any(type(x) is not str or x not in KNOWN_CONTROLLERS for x in ctrls)
            or ctrls != sorted(set(ctrls))):
        return False
    for section, keys in (("namespaceLinksPresent", NAMESPACE_KINDS),
                          ("toolExecutablesPresent", TOOLS)):
        mapping = obs.get(section)
        if (type(mapping) is not dict or set(mapping) != set(keys)
                or any(not _tri(x) for x in mapping.values())):
            return False
    return True


def _option(signals):
    """Do not infer actual execution permission or certified containment."""
    if all(value is True for value in signals):
        return "POTENTIAL_FAKE_EXPERIMENT_ONLY"
    if any(value is False for value in signals):
        return "PREREQUISITE_NOT_OBSERVED"
    return "INCOMPLETE_OBSERVATION"


def assess(report):
    """Return an allowlisted engineering direction and unconditional DENY."""
    valid = _valid_report(report)
    if valid:
        obs = report["observations"]
        tools = obs["toolExecutablesPresent"]
        links = obs["namespaceLinksPresent"]
        systemd = _option((
            obs["cgroupV2MountedAtStandardPath"],
            obs["selfCgroupV2Member"],
            True if "pids" in obs["visibleCgroupControllers"] else False,
            tools["systemdRun"],
            obs["userBusSocketPresent"],
        ))
        bwrap = _option((
            tools["bwrap"], links["user"], links["mnt"], links["net"],
            obs["maxUserNamespacesPositive"],
            obs["unprivilegedUsernsSysctlAllows"],
        ))
    else:
        systemd = bwrap = "UNTRUSTED_REPORT"

    if systemd == "POTENTIAL_FAKE_EXPERIMENT_ONLY":
        direction = "REVIEW_NON_HERMES_SYSTEMD_SCOPE_PROBE"
    elif bwrap == "POTENTIAL_FAKE_EXPERIMENT_ONLY":
        direction = "REVIEW_NON_HERMES_NAMESPACE_PROBE"
    else:
        direction = "RESOLVE_HOST_PREREQUISITES_READ_ONLY"

    reasons = set(FIXED_REASONS)
    if not valid:
        reasons.add("MALFORMED_OR_UNTRUSTED_H6_REPORT")
    return {
        "schema": SCHEMA, "decision": "DENY",
        "realHermesSupported": False, "realGatewayLaunched": False,
        "hostAttested": False, "cgroupDelegationVerified": False,
        "namespaceIsolationVerified": False, "nativeToolDenialVerified": False,
        "modelOnlyTransportVerified": False, "authenticatedStopVerified": False,
        "descendantTeardownVerified": False, "networkIsolationVerified": False,
        "credentialIsolationVerified": False, "launchAuthorized": False,
        "productionReady": False,
        "options": {"systemdUserScope": systemd, "bubblewrapNamespaces": bwrap,
                    "pidfdOrKernelLifecycle": "NOT_MEASURED",
                    "hermesNativeTools": "SOURCE_AUDIT_REQUIRED",
                    "hermesTurnStop": "SOURCE_AUDIT_REQUIRED"},
        "nextReview": direction,
        "reasons": sorted(reasons),
        "modelCalls": 0, "gatewayCalls": 0, "toolCalls": 0, "hospitalWrites": 0,
    }


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_bounded(raw):
    if type(raw) is not bytes or len(raw) > MAX_INPUT_BYTES:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="strict"),
                          object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError, RecursionError, TypeError):
        return None


def main(argv=None, input_stream=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["--stdin"]:
        print(json.dumps({
            "schema": SCHEMA, "decision": "DENY",
            "reason": "EXPLICIT_SANITIZED_H6_STDIN_REQUIRED",
            "inputReads": 0, "modelCalls": 0, "launchAuthorized": False,
        }, sort_keys=True))
        return 2
    stream = sys.stdin.buffer if input_stream is None else input_stream
    try:
        data = stream.read(MAX_INPUT_BYTES + 1)
        report = assess(_parse_bounded(data))
    except Exception:
        report = assess(None)
    print(json.dumps(report, sort_keys=True))
    return 0  # Always an engineering diagnostic, never permission to launch.


if __name__ == "__main__":
    raise SystemExit(main())
