"""Hospital Session / Doctor native request-frame contract, NOT installed.

This module deliberately has NO socket, listener, issuer, database opener,
operator consent shortcut or callable mutation dispatcher. It stages one
separate, exact and bounded PREPARE/COMMIT protocol for future review by the
Hospital and Connections source owners. Unknown commands, Bed registration,
Trash/Restore and arbitrary legacy store commands are not expressible.

A parsed frame is untrusted data. It grants no permission, even when a
client includes a syntactically valid signed envelope.
"""
from __future__ import annotations

import base64
import json
import re

import px_hospital_staffing_grants as grants

SCHEMA = "postapollo.hospital.native-staffing-request.v1"
MAX_FRAME = 16384
MAX_GRANT_BYTES = 8192
KIND_PREPARE = "prepare"
KIND_COMMIT = "commit"
_ALLOWED = frozenset((grants.ATTACH, grants.SUCCEED))
NONCE = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
WRITER = re.compile(r"[A-Za-z0-9_-]{12,128}\Z", re.ASCII)
PREPARE_FIELDS = frozenset((
    "schema", "kind", "action", "roomId", "intent", "requestNonce",
))
COMMIT_FIELDS = PREPARE_FIELDS | frozenset((
    "writerInstance", "signedEnvelope",
))


class NativeStaffingTransportHold(RuntimeError):
    pass


def _hold(message):
    raise NativeStaffingTransportHold(
        "HOSPITAL_STAFFING_TRANSPORT_HOLD // " + message
    )


def _unique(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            _hold("DUPLICATE_REQUEST_FIELD")
        out[k] = v
    return out


def _nonfinite(_value):
    _hold("NONFINITE_REQUEST_VALUE")


def canonical(frame):
    return json.dumps(
        frame, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("ascii")


def _decode_b64(value, *, expected_length=None, max_length=None):
    if type(value) is not str or not value:
        _hold("INVALID_CANONICAL_BINARY")
    try:
        blob = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (TypeError, ValueError) as exc:
        raise NativeStaffingTransportHold(
            "HOSPITAL_STAFFING_TRANSPORT_HOLD // INVALID_CANONICAL_BINARY"
        ) from exc
    if (expected_length is not None and len(blob) != expected_length
            or max_length is not None and len(blob) > max_length
            or base64.urlsafe_b64encode(blob).rstrip(b"=").decode("ascii") != value):
        _hold("NONCANONICAL_BINARY")
    return blob


def parse_request(raw: bytes):
    """Only parses exact request bytes. Never verifies authority or writes."""
    if type(raw) is not bytes or not 2 <= len(raw) <= MAX_FRAME:
        _hold("BOUNDED_REQUEST_REQUIRED")
    try:
        frame = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=_unique,
            parse_constant=_nonfinite,
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise NativeStaffingTransportHold(
            "HOSPITAL_STAFFING_TRANSPORT_HOLD // INVALID_JSON"
        ) from exc
    if type(frame) is not dict or canonical(frame) != raw:
        _hold("NONCANONICAL_FRAME")
    if frame.get("schema") != SCHEMA:
        _hold("WRONG_PROTOCOL_DOMAIN")
    op = frame.get("action")
    if type(op) is not str or op not in _ALLOWED:
        _hold("UNKNOWN_OR_CROSS_SYSTEM_OPERATION")
    kind = frame.get("kind")
    if kind == KIND_PREPARE:
        if set(frame) != PREPARE_FIELDS:
            _hold("EXACT_PREPARE_FIELDS_REQUIRED")
    elif kind == KIND_COMMIT:
        if set(frame) != COMMIT_FIELDS:
            _hold("EXACT_COMMIT_FIELDS_REQUIRED")
    else:
        _hold("UNSUPPORTED_PHASE")
    if type(frame.get("roomId")) is not str:
        _hold("INVALID_ROOM_ID")
    try:
        grants.lifecycle._identity(frame["roomId"])
        # Validation only; does NOT create a grant or trust this client intent.
        grants._scope(op, frame.get("intent"))
    except (grants.StaffingGrantHold,
            grants.lifecycle.RoomLifecycleRefused) as exc:
        raise NativeStaffingTransportHold(
            "HOSPITAL_STAFFING_TRANSPORT_HOLD // INVALID_INTENT"
        ) from exc
    if frame["intent"]["roomId"] != frame["roomId"]:
        _hold("CONFLICTING_ROOM_IDS")
    nonce = frame.get("requestNonce")
    if type(nonce) is not str or NONCE.fullmatch(nonce) is None:
        _hold("INVALID_REQUEST_NONCE")
    _decode_b64(nonce, expected_length=32)
    if kind == KIND_COMMIT:
        if (type(frame.get("writerInstance")) is not str
                or WRITER.fullmatch(frame["writerInstance"]) is None):
            _hold("INVALID_WRITER_INSTANCE")
        blob = _decode_b64(
            frame["signedEnvelope"], max_length=MAX_GRANT_BYTES,
        )
        # A syntactically valid grant is not an approved grant. The future
        # trusted handler must check the root-pinned signature AND bind it
        # to a durable PREPARE snapshot + fresh verified operator consent.
        if not blob.startswith(b"{"):
            _hold("INVALID_ENVELOPE_BYTES")
    return frame


def dispatch_native_request(*_args, **_kwargs):
    """Non-optional release gate until a trusted native host is reviewed."""
    _hold("NATIVE_STAFFING_SERVICE_NOT_INSTALLED")
