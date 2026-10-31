#!/usr/bin/env python3
"""EXEC-S3 B37-B: inert, byte-sealed mock submission using B37-A + B29.

Synthetic fixture ONLY. No authenticated provider, transport, SDK, HTTP,
credentials, Hospital access, native tool or real dispatch capability.
SHA-256 binds bytes to fake attempt identity; it is NOT a signature, trusted
authority assertion, durability proof, or permission to transmit.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json

from px_s3_b29_transport_ledger import (
    ID, SyntheticLedger, canonical_binding,
)
from px_s3_b37a_tool_free_contract import (
    validate_request, validate_wire_payload,
)

DOMAIN = b"PX_EXEC_S3_B37B_SEALED_FIXTURE_V1\x00"
MAX_BYTES = 8192


class Refused(RuntimeError):
    """Sanitized mock-only rejection, never include prompt or credential bytes."""


def _deny(code):
    raise Refused("B37B_REFUSED_" + code)


def _identifier(value):
    return type(value) is str and ID.fullmatch(value) is not None


def _binding(binding):
    # B29 validates exact Room/Patient/Assignment/Bed/turn/generation keys.
    try:
        return canonical_binding(binding)
    except Exception:
        _deny("BINDING_INVALID")


def _canonical_payload(request):
    # This copies validated values into fresh JSON bytes, not an alias to the
    # mutable B37-A caller dict. No custom JSON encoder or transport hook.
    validate_request(request)
    raw = json.dumps(
        request, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("ascii")
    if not 0 < len(raw) <= MAX_BYTES:
        _deny("WIRE_SIZE")
    validate_wire_payload(raw)
    return raw


def _client_request_id(raw, binding_json, attempt_id):
    # The B29 fixture persists client_request_id uniquely. Derivation binds
    # exact bytes, full authority fixture fields and attempt ID to that row.
    digest = hashlib.sha256(
        DOMAIN + attempt_id.encode("ascii") + b"\x00" +
        binding_json.encode("ascii") + b"\x00" + raw
    ).hexdigest()
    return "b37b." + digest


@dataclass(frozen=True, slots=True)
class SealedFixture:
    """Bytes are immutable; caller data is never retained by reference."""
    payload: bytes
    payload_sha256: str
    binding_json: str
    attempt_id: str
    client_request_id: str


def seal_fixture(request, *, binding, attempt_id):
    """Return a fake-model-only, immutable byte snapshot, not a send token."""
    if not _identifier(attempt_id):
        _deny("ATTEMPT_ID")
    canonical = _binding(binding)
    raw = _canonical_payload(request)
    return SealedFixture(
        payload=raw, payload_sha256=hashlib.sha256(raw).hexdigest(),
        binding_json=canonical, attempt_id=attempt_id,
        client_request_id=_client_request_id(raw, canonical, attempt_id),
    )


def verify_fixture(sealed, *, current_binding):
    """Verify original bytes and current *supplied fixture* binding.

    This is NOT the live Hospital authority check: a trusted supervisor must
    independently obtain current Assignment and generation before any send.
    """
    if type(sealed) is not SealedFixture:
        _deny("SEAL_TYPE")
    if not _identifier(sealed.attempt_id):
        _deny("ATTEMPT_ID")
    if type(sealed.payload) is not bytes:
        _deny("PAYLOAD_TYPE")
    if type(sealed.binding_json) is not str:
        _deny("SEAL_BINDING")
    bound = _binding(current_binding)
    if not hmac.compare_digest(bound, sealed.binding_json):
        _deny("AUTHORITY_CHANGED")
    try:
        parsed = validate_wire_payload(sealed.payload)
        if _canonical_payload(parsed) != sealed.payload:
            _deny("NONCANONICAL_PAYLOAD")
    except ValueError:
        _deny("PAYLOAD_INVALID")
    if type(sealed.payload_sha256) is not str or not hmac.compare_digest(
        hashlib.sha256(sealed.payload).hexdigest(), sealed.payload_sha256
    ):
        _deny("PAYLOAD_HASH_CHANGED")
    if type(sealed.client_request_id) is not str or not hmac.compare_digest(
        _client_request_id(sealed.payload, bound, sealed.attempt_id),
        sealed.client_request_id,
    ):
        _deny("REQUEST_BINDING_CHANGED")
    return {
        "schema": "B37B_OFFLINE_SEALED_HANDOFF_V1",
        "requestShapeValid": True,
        "payloadSha256": sealed.payload_sha256,
        "clientRequestId": sealed.client_request_id,
        "launchAuthorized": False, "modelCalls": 0, "toolCalls": 0,
        "hospitalWrites": 0, "productionReady": False,
    }


def _ledger(ledger):
    if type(ledger) is not SyntheticLedger:
        _deny("SYNTHETIC_LEDGER_REQUIRED")


def reserve_mock(ledger, sealed, *, scope, units, current_binding):
    """Reserve fake B29 budget using byte-derived unique request identity."""
    _ledger(ledger)
    verify_fixture(sealed, current_binding=current_binding)
    try:
        row = ledger.reserve(
            attempt_id=sealed.attempt_id,
            client_request_id=sealed.client_request_id,
            scope=scope, binding=current_binding,
            mode="FOREGROUND_STREAM", units=units,
        )
    except Exception:
        _deny("LEDGER_RESERVE_FAILED")
    return {
        "state": row["state"], "attemptId": row["attemptId"],
        "clientRequestId": row["clientRequestId"],
        "payloadSha256": sealed.payload_sha256,
        "launchAuthorized": False, "modelCalls": 0,
        "productionReady": False,
    }


def mock_handoff(ledger, sealed, *, current_binding, observed_bytes=None):
    """Fake-only atomic B29 state transition. Absolutely no network sender.

    observed_bytes simulates what an eventual send boundary would consume.
    It MUST be identical to the immutable sealed bytes. Never rebuild from
    the original mutable request, and never trust a prior validation verdict.
    """
    _ledger(ledger)
    proof = verify_fixture(sealed, current_binding=current_binding)
    if observed_bytes is None:
        observed_bytes = sealed.payload
    if type(observed_bytes) is not bytes or not hmac.compare_digest(
        observed_bytes, sealed.payload
    ):
        _deny("FINAL_BYTES_CHANGED")
    # Validate at the last mock boundary, not merely at seal construction.
    try:
        validate_wire_payload(observed_bytes)
    except ValueError:
        _deny("FINAL_BYTES_INVALID")
    try:
        row = ledger.state(sealed.attempt_id)
        if (row["state"] != "RESERVED" or
                row["clientRequestId"] != sealed.client_request_id or
                row["turnId"] != current_binding["turnId"]):
            _deny("ATTEMPT_NOT_RESERVED_IDENTICALLY")
        # B29 holds a BEGIN IMMEDIATE transaction and independently checks
        # the stored binding and state. No sender is invoked here.
        transitioned = ledger.mark_submission(
            sealed.attempt_id, current_binding,
        )
    except Refused:
        raise
    except Exception:
        _deny("LEDGER_HANDOFF_FAILED")
    return {
        "schema": proof["schema"],
        "state": transitioned["state"],
        "payloadSha256": proof["payloadSha256"],
        "clientRequestId": transitioned["clientRequestId"],
        "transport": "MOCK_ONLY_NO_SENDER",
        "remoteDeliveryObserved": False, "remoteStopVerified": False,
        "retryAuthorized": False, "launchAuthorized": False,
        "modelCalls": 0, "toolCalls": 0, "hospitalWrites": 0,
        "productionReady": False,
    }


def require_real_dispatch(_sealed, _context=None):
    """Explicit guard: this fixture cannot be promoted into a live sender."""
    raise Refused("B37B_REFUSED_NO_REAL_TRANSPORT_OR_AUTHORITY")
