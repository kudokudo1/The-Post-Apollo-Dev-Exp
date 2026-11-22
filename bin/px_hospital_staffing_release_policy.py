"""Root-controlled native staffing verifier policy (source-only release gate).

The protected writer MUST independently compare every signed staffing grant
with a currently installed, root-owned policy. A signature can outlive a
revoked release, switched operator or generation; this check refuses such
grants even if the former signer remains cryptographically valid.

This module never enrolls an issuer, verifies a release signature, provides
an operator/Polkit decision, installs a policy, or opens the Hospital DB.
The actual trusted publisher, signed release provenance, active-seat consent,
protected service and owner-approved database migration remain prerequisites.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import time

SCHEMA = "postapollo.hospital.staffing-verifier-policy.v1"
PATH = Path("/etc/post-apollo/hospital/staffing-verifier-policy.json")
MAX_POLICY = 4096
FIELDS = frozenset((
    "schema", "operatorUid", "clientExecutableSha256",
    "issuerReleaseSha256", "hostId", "policyGeneration",
    "allowedOperations", "expiresAt",
))
OPERATIONS = frozenset(("SESSION_ATTACH", "DOCTOR_SUCCEED"))
HEX = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)


class StaffingPolicyHold(RuntimeError):
    pass


def hold(reason):
    raise StaffingPolicyHold("HOSPITAL_STAFFING_POLICY_HOLD // " + reason)


def _unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            hold("DUPLICATE_POLICY_FIELD")
        obj[key] = value
    return obj


def _nonfinite(_value):
    hold("NONFINITE_POLICY_VALUE")


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def parse_policy(raw, *, now=None):
    """Parse bytes, NOT evidence of an installed root-controlled document."""
    if type(raw) is not bytes or not 2 <= len(raw) <= MAX_POLICY:
        hold("BOUNDED_POLICY_REQUIRED")
    try:
        obj = json.loads(raw.decode("ascii", "strict"),
                         object_pairs_hook=_unique,
                         parse_constant=_nonfinite)
    except (UnicodeError, ValueError, TypeError, OverflowError) as exc:
        raise StaffingPolicyHold(
            "HOSPITAL_STAFFING_POLICY_HOLD // INVALID_POLICY_JSON"
        ) from exc
    if type(obj) is not dict or set(obj) != FIELDS or obj["schema"] != SCHEMA:
        hold("UNRECOGNIZED_POLICY_FIELDS_OR_SCHEMA")
    try:
        if _canonical(obj) != raw:
            hold("NONCANONICAL_POLICY")
    except (TypeError, ValueError, OverflowError) as exc:
        raise StaffingPolicyHold(
            "HOSPITAL_STAFFING_POLICY_HOLD // INVALID_POLICY_CONTENT"
        ) from exc
    for name in ("hostId", "clientExecutableSha256", "issuerReleaseSha256"):
        if type(obj[name]) is not str or not HEX.fullmatch(obj[name]):
            hold("INVALID_POLICY_RELEASE_OR_HOST")
    if (type(obj["operatorUid"]) is not int
            or not 0 < obj["operatorUid"] < 2**31
            or type(obj["policyGeneration"]) is not int
            or not 0 < obj["policyGeneration"] < 2**63):
        hold("INVALID_OPERATOR_OR_GENERATION")
    allowed = obj["allowedOperations"]
    if (type(allowed) is not list or not 1 <= len(allowed) <= 2
            or any(type(x) is not str for x in allowed)
            or len(set(allowed)) != len(allowed)
            or not set(allowed).issubset(OPERATIONS)
            or allowed != sorted(allowed)):
        hold("UNTRUSTED_STAFFING_OPERATIONS")
    tick = int(time.time()) if now is None else int(now)
    if (type(obj["expiresAt"]) is not int
            or not tick < obj["expiresAt"] <= tick + 31*24*3600):
        hold("EXPIRED_OR_UNBOUNDED_RELEASE_POLICY")
    return obj


def _read_root_bytes():
    """No path override. Reject symlinks, hard links and unstable file reads.

    Root must also provision/verify the signed release that vouches for
    these policy hashes. POSIX file custody alone is insufficient proof.
    """
    path = PATH
    for parent in path.parents:
        try:
            st = parent.lstat()
        except OSError as exc:
            raise StaffingPolicyHold(
                "HOSPITAL_STAFFING_POLICY_HOLD // ROOT_PARENT_UNAVAILABLE"
            ) from exc
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0
                or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            hold("UNTRUSTED_POLICY_PARENT")
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or before.st_nlink != 1
                or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or not 2 <= before.st_size <= MAX_POLICY):
            hold("UNTRUSTED_POLICY_FILE")
        raw = os.read(fd, MAX_POLICY + 1)
        after = os.fstat(fd)
        if (len(raw) != before.st_size
                or (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns)):
            hold("POLICY_FILE_CHANGED")
        return raw
    except OSError as exc:
        raise StaffingPolicyHold(
            "HOSPITAL_STAFFING_POLICY_HOLD // ROOT_POLICY_NOT_INSTALLED"
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)


def read_installed_policy():
    """Fixed root path, no caller-selected policy or test-key RPC."""
    return parse_policy(_read_root_bytes())


def check_signed_grant(body, policy):
    """Writer-side anti-revocation gate; never returns native permission."""
    if type(body) is not dict or type(policy) is not dict:
        hold("EXACT_SIGNED_STAFFING_BODY_REQUIRED")
    # A policy copy from an untrusted source must not become authority.
    # The caller must use read_installed_policy() when entering native code.
    required = (
        ("hostId", "hostId"),
        ("operatorUid", "operatorUid"),
        ("clientExecutableSha256", "clientExecutableSha256"),
        ("issuerReleaseSha256", "issuerReleaseSha256"),
        ("policyGeneration", "policyGeneration"),
    )
    for claim, owner_key in required:
        if body.get(claim) != policy.get(owner_key):
            hold("SIGNED_STAFFING_POLICY_REVOKED_OR_CHANGED")
    if body.get("operation") not in policy.get("allowedOperations", ()):
        hold("STAFFING_OPERATION_NOT_ENROLLED")
    return None  # comparison is a necessary condition, not authorization
