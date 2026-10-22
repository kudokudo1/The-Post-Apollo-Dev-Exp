#!/usr/bin/env python3
"""B21: fixed capability contract for the disposable synthetic PX provider.

This is NOT a probe of Codex/Hermes and is NOT a provider attestation.
No real model, native tool, credentials, gateway or host process is started.
The only admitted profile is the source-owned INT1 fake arithmetic fixture.
"""
import hashlib
import json
import os
from pathlib import Path
import stat

from px_int1_fake_guard import (
    FAKE_ID, PROFILE, require_fixture, require_profile,
)

VERSION = 1
# Deliberately *not* a general capability negotiation language. Exact keys
# and exact values are mandatory, including the false native-tool properties.
FAKE_CONTRACT = {
    "contractVersion": VERSION,
    "providerId": FAKE_ID,
    "executionProfile": PROFILE,
    "providerType": "SOURCE_OWNED_SYNTHETIC_ONLY",
    "providerBinary": "NONE",
    "nativeModelTransport": "NONE",
    "credentialMode": "NONE",
    "nativeTools": [],
    "modelOnlyCertified": False,
    "externalToolCallsAllowed": False,
    "toolProtocol": "FIXED_ARITHMETIC_SINGLE_FRAME",
    "executionOwner": "PX_SUPERVISOR",
    "cancellationOwner": "PX_TURN_SCOPED",
    "gateway": "NONE",
    "nativeResume": False,
    "crashRecovery": "MANUAL_NO_RETRY",
}
SOURCE_PATHS = (
    "/source/bin/px_int1_fake_broker.py",
    "/source/bin/px_int1_fake_dispatch.py",
    "/source/bin/px_int1_fake_capability.py",
)


def _canonical(value):
    try:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "INT1-B21 REFUSED // malformed fake capability contract"
        ) from exc


def _source_digest():
    """Observe current read-only fixture bytes, NOT a signed binary identity.

    Bind the fake contract to files exposed by the existing OS fixture mount.
    Never use a writable workspace file, provider JSON, or caller-supplied path.
    """
    try:
        mount_rows = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError as exc:
        raise RuntimeError(
            "INT1-B21 REFUSED // missing OS mount evidence"
        ) from exc
    mounts = {}
    for record in mount_rows:
        before = record.split(" - ", 1)[0].split()
        if len(before) > 5:
            mounts[before[4]] = set(before[5].split(","))
    digest = hashlib.sha256()
    for name in SOURCE_PATHS:
        file = Path(name)
        try:
            info = file.lstat()
        except OSError as exc:
            raise RuntimeError(
                "INT1-B21 REFUSED // missing trusted fake source"
            ) from exc
        if (name not in mounts or "ro" not in mounts[name] or
                not stat.S_ISREG(info.st_mode) or
                not 0 < info.st_size <= 131072):
            raise RuntimeError(
                "INT1-B21 REFUSED // fake source is not pinned read-only"
            )
        # Include boundaries and filenames so reordering never aliases.
        blob = file.read_bytes()
        if len(blob) != info.st_size:
            raise RuntimeError(
                "INT1-B21 REFUSED // fake source changed during inspection"
            )
        digest.update(name.encode("utf-8") + b"\x00")
        digest.update(len(blob).to_bytes(8, "big") + blob)
    return digest.hexdigest()


def require_fake_capability(provider_id, record, registry, *, candidate=None):
    """Allow only the exact trusted fake profile; no writable capability grant.

    A provider-proposed JSON document is explicitly *not* trusted evidence.
    A candidate is only compared to the closed source contract; it cannot
    request privileges, tools, credentials or a gateway.
    """
    require_fixture()
    require_profile(provider_id, record, registry)
    proposed = FAKE_CONTRACT if candidate is None else candidate
    if _canonical(proposed) != _canonical(FAKE_CONTRACT):
        raise RuntimeError(
            "INT1-B21 REFUSED // unsupported or escalated provider capability"
        )
    source_digest = _source_digest()
    return {
        "contractVersion": VERSION,
        "providerId": FAKE_ID,
        "executionProfile": PROFILE,
        "capabilityProfile": "FIXED_SYNTHETIC_ONLY",
        "capabilityValidatedInFixture": True,
        "sourceDigest": source_digest,
        "sourceEvidence": "READ_ONLY_FIXTURE_BYTES_NOT_SIGNED",
        "modelOnlyCertified": False,
        "realProviderCertified": False,
        "realModelCalls": 0,
        "nativeToolsAllowed": False,
        "credentialsAvailable": False,
        "gatewayActive": False,
        "productionReady": False,
    }
