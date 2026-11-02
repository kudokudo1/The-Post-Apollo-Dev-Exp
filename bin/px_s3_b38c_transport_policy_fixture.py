#!/usr/bin/env python3
"""B38-C: offline credential/transport *plan* contract. Never a sender.

All fields are caller-provided fixture claims, not OS attestations.
No sockets, HTTP, environment reads, credentials, processes, or Hospital.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json

from px_s3_b37b_sealed_handoff import (
    Refused as B37BRefused, SealedFixture, verify_fixture,
)

SCHEMA = "B38C_OFFLINE_TRANSPORT_PLAN_V1"
MAX_MANIFEST_BYTES = 4096
ENV_NAMES = frozenset(("LANG", "LC_ALL", "TZ"))
PROFILE = "PX_MODEL_ONLY_FAKE_SENDER"
TARGET = "mock-model.invalid"


class Refused(RuntimeError):
    """Only fixed reason codes. Never include caller-provided details."""


def _deny(code):
    raise Refused("B38C_REFUSED_" + code)


def default_fake_manifest():
    """Produce a new, strictly inert mock topology with NO secret material."""
    return {
        "schema": SCHEMA,
        "process": {
            "profile": PROFILE,
            "executable": "NONE",
            "nativeTools": False,
            "plugins": False,
            "mcp": False,
            "delegation": False,
            "shell": False,
            "browser": False,
            "nativeResume": False,
        },
        "credentials": {
            "source": "NO_CREDENTIALS",
            "hostEnvInherited": False,
            "hostHomeMounted": False,
            "argvSecret": False,
            "stdinSecret": False,
            "toolSecret": False,
            "fdsInherited": False,
            "socketsInherited": False,
        },
        "network": {
            "mode": "IN_MEMORY_FIXTURE",
            "destination": TARGET,
            "tcpEnabled": False,
            "redirects": False,
            "proxy": False,
            "ambientDNS": False,
            "toolEgress": False,
        },
        "ipc": {
            "kind": "NONE",
            "brokerAddressVisible": False,
            "modelCanMintGrant": False,
            "toolCanSendRequest": False,
        },
        "environment": {
            "names": ["LANG", "TZ"],
            "valuesIncluded": False,
        },
        "limits": {
            "requestBytes": 8192,
            "frameBytes": 2048,
            "frames": 32,
        },
    }


def _fixed(candidate, expected):
    """Exact recursive shape with strict type equality, not bool/int coercion."""
    if type(expected) is dict:
        if type(candidate) is not dict or set(candidate) != set(expected):
            _deny("POLICY_SCHEMA")
        for key, wanted in expected.items():
            _fixed(candidate[key], wanted)
    elif type(expected) is list:
        # Environment entries are names only; not values or secrets.
        if type(candidate) is not list:
            _deny("ENV_NAMES")
        if any(type(n) is not str or n not in ENV_NAMES for n in candidate):
            _deny("ENV_NAMES")
        if len(candidate) != len(set(candidate)):
            _deny("ENV_NAMES")
        if candidate != sorted(candidate):
            _deny("ENV_ORDER")
    elif type(candidate) is not type(expected) or candidate != expected:
        _deny("POLICY_VALUE")


def _canonical_manifest(manifest):
    # Keep the profile fixed and distinguish descriptive configuration from
    # OS-observed enforcement. This only checks what the caller *claims*.
    _fixed(manifest, default_fake_manifest())
    try:
        raw = json.dumps(
            manifest, ensure_ascii=True, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("ascii")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        _deny("MANIFEST_ENCODING")
    if not 0 < len(raw) <= MAX_MANIFEST_BYTES:
        _deny("MANIFEST_SIZE")
    return raw


def _verified_seal(sealed, binding):
    if type(sealed) is not SealedFixture:
        _deny("SEAL_TYPE")
    try:
        verify_fixture(sealed, current_binding=binding)
    except (B37BRefused, ValueError, KeyError, TypeError):
        _deny("SEALED_REQUEST_INVALID")


@dataclass(frozen=True, slots=True)
class OfflinePlan:
    """Immutable bytes snapshot. This is NOT an identity or dispatch grant."""
    manifest_bytes: bytes
    manifest_sha256: str
    request_id: str
    payload_sha256: str
    binding_json: str


def prepare_fake_plan(manifest, *, sealed, current_binding):
    """Inspect a synthetic process/credential/network plan without actuating."""
    raw = _canonical_manifest(manifest)
    _verified_seal(sealed, current_binding)
    return OfflinePlan(
        manifest_bytes=raw,
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        request_id=sealed.client_request_id,
        payload_sha256=sealed.payload_sha256,
        binding_json=sealed.binding_json,
    )


def recheck_fake_plan(plan, manifest, *, sealed, current_binding):
    """Last-moment shape recheck, not real readiness/authority verification."""
    if type(plan) is not OfflinePlan:
        _deny("PLAN_TYPE")
    raw = _canonical_manifest(manifest)
    if type(plan.manifest_bytes) is not bytes or not hmac.compare_digest(
        plan.manifest_bytes, raw
    ):
        _deny("MANIFEST_CHANGED")
    if (type(plan.manifest_sha256) is not str or
            not hmac.compare_digest(
                hashlib.sha256(raw).hexdigest(), plan.manifest_sha256
            )):
        _deny("MANIFEST_HASH_CHANGED")
    _verified_seal(sealed, current_binding)
    if (type(plan.request_id) is not str or
            not hmac.compare_digest(plan.request_id, sealed.client_request_id) or
            type(plan.payload_sha256) is not str or
            not hmac.compare_digest(plan.payload_sha256, sealed.payload_sha256) or
            type(plan.binding_json) is not str or
            not hmac.compare_digest(plan.binding_json, sealed.binding_json)):
        _deny("SEALED_IDENTITY_CHANGED")
    return {
        "schema": SCHEMA,
        "decision": "OFFLINE_SHAPE_ONLY",
        "requestShapeValid": True,
        "credentialBoundaryCertified": False,
        "networkPolicyEnforced": False,
        "osIsolationVerified": False,
        "hospitalAuthorityVerified": False,
        "transportReady": False,
        "launchAuthorized": False,
        "productionReady": False,
        "modelCalls": 0,
        "networkCalls": 0,
        "toolCalls": 0,
        "hospitalWrites": 0,
    }


def require_real_transport(*_args, **_kwargs):
    """Hard fail: no sender, real network, auth, or production adapter exists."""
    _deny("NO_REAL_TRANSPORT_OR_CREDENTIAL_AUTHORITY")
