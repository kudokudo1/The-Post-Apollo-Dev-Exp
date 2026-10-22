#!/usr/bin/env python3
"""B22: exact git-blob-version pin for the known disposable synthetic files.

This policy is source-owned and self-reported, not an authenticated vendor
signature, not hostile-host tamper proof, and NOT approval for real AI.
"""
import hashlib
import json
import stat
from pathlib import Path

from px_int1_fake_guard import FAKE_ID, PROFILE, require_fixture
from px_int1_fake_capability import SOURCE_PATHS, _source_digest

PIN_VERSION = 1
SOURCE_BASELINE = "B21_SYNTHETIC_SOURCE_2026_10_22"
PINNED_GIT_BLOBS = {
    "/source/bin/px_int1_fake_broker.py": "bf1648c0efbad305d23b4c7ca1a6d225cb48bb5f",
    "/source/bin/px_int1_fake_dispatch.py": "af0275b8d3ee91865a6e56de828627648786293b",
    "/source/bin/px_int1_fake_capability.py": "fe6ceb60fef4dc2b8831069608de0f0fcd99bbc1"
}
# Git SHA-1 object names are a code-baseline integrity check, not a digital
# signature. B21 also produces an independent SHA-256 of observed source data.


def _git_blob_oid(data):
    """Compute the Git SHA-1 object ID of EXACT bytes, including blob framing."""
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") +
                        b"\x00" + data).hexdigest()


def require_source_pin(capability):
    """Reject a changed/bypassed fake source version before turn acceptance.

    Only a trusted, previously reviewed fixture baseline is admitted. Do not
    accept a caller-supplied expected hash or version as an authorization.
    """
    require_fixture()
    if (not isinstance(capability, dict) or
            capability.get("contractVersion") != 1 or
            capability.get("providerId") != FAKE_ID or
            capability.get("executionProfile") != PROFILE or
            capability.get("capabilityProfile") != "FIXED_SYNTHETIC_ONLY" or
            capability.get("modelOnlyCertified") is not False or
            capability.get("realProviderCertified") is not False or
            capability.get("nativeToolsAllowed") is not False or
            capability.get("credentialsAvailable") is not False or
            capability.get("gatewayActive") is not False or
            capability.get("productionReady") is not False or
            capability.get("capabilityValidatedInFixture") is not True):
        raise RuntimeError("INT1-B22 REFUSED // invalid synthetic capability")
    if (set(PINNED_GIT_BLOBS) != set(SOURCE_PATHS) or
            len(PINNED_GIT_BLOBS) != 3):
        raise RuntimeError("INT1-B22 REFUSED // invalid pinned source manifest")
    # B21 refuses paths outside the source-owned read-only OS mounts. Its
    # SHA-256 source digest additionally binds to these exact observed bytes.
    digest = _source_digest()
    if capability.get("sourceDigest") != digest:
        raise RuntimeError("INT1-B22 REFUSED // source changed since preflight")
    for path in SOURCE_PATHS:
        expected = PINNED_GIT_BLOBS[path]
        if (not isinstance(expected, str) or len(expected) != 40 or
                any(c not in "0123456789abcdef" for c in expected)):
            raise RuntimeError("INT1-B22 REFUSED // malformed source pin")
        # The allowed source paths were already checked in B21 against the
        # source RO mount boundaries. Re-read to enforce the approved version.
        content = Path(path).read_bytes()
        if _git_blob_oid(content) != expected:
            raise RuntimeError("INT1-B22 REFUSED // source version drift")
    manifest = json.dumps({
        "baseline": SOURCE_BASELINE, "version": PIN_VERSION,
        "pins": PINNED_GIT_BLOBS,
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    return {
        "pinVersion": PIN_VERSION,
        "baseline": SOURCE_BASELINE,
        "manifestSha256": hashlib.sha256(manifest).hexdigest(),
        "observedSourceSha256": digest,
        "versionPinnedInFixture": True,
        "provenance": "SOURCE_OWNED_GIT_BLOB_IDS_NOT_SIGNED",
        "realProviderVersionVerified": False,
        "hostBinaryInspected": False,
        "modelOnlyCertified": False,
        "productionReady": False,
    }
