#!/usr/bin/env python3
"""B38-A: PX-owned, in-memory fake text client. No provider transport.

This is not an authenticated model client or a production launcher. Only
literal byte frames supplied as data by the tests can be consumed. It must
never import Hermes, an SDK, an HTTP library, or a native tool dispatcher.
"""
from dataclasses import dataclass
import hmac
import json

from px_s3_b37b_sealed_handoff import (
    SealedFixture, Refused as B37BRefused, verify_fixture,
)
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture, Refused as B37CRefused

MAX_FRAMES = 32
MAX_FRAME_BYTES = 2048
MAX_TEXT_CHARS = 4096
PROVENANCE = "SYNTHETIC_IN_MEMORY_TEXT_ONLY"


class Refused(RuntimeError):
    """Fixed failure codes only; never echo request or output bytes."""


def _deny(code):
    raise Refused("B38A_REFUSED_" + code)


def _unique_pairs(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            _deny("DUPLICATE_FRAME_KEY")
        result[name] = value
    return result


def _nonfinite(_):
    _deny("NONFINITE_FRAME_VALUE")


def _decode_frame(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME_BYTES:
        _deny("FRAME_TYPE_OR_SIZE")
    try:
        frame = json.loads(raw.decode("utf-8", "strict"),
                           object_pairs_hook=_unique_pairs,
                           parse_constant=_nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _deny("FRAME_ENCODING_OR_JSON")
    if type(frame) is not dict or type(frame.get("type")) is not str:
        _deny("FRAME_SCHEMA")
    event = frame["type"]
    if event == "mock.text.delta":
        if set(frame) != {"type", "seq", "text"}:
            _deny("FRAME_SCHEMA")
        if type(frame["text"]) is not str or not frame["text"]:
            _deny("TEXT_INVALID")
        try:
            frame["text"].encode("utf-8", "strict")
        except UnicodeError:
            _deny("TEXT_ENCODING")
    elif event == "mock.text.completed":
        if set(frame) != {"type", "seq"}:
            _deny("FRAME_SCHEMA")
    else:
        # Includes tool calls, reasoning, MCP, plugin, provider-control, and
        # any future event the mock client was not explicitly written to parse.
        _deny("NON_TEXT_EVENT")
    if type(frame["seq"]) is not int or frame["seq"] < 0:
        _deny("SEQUENCE_INVALID")
    return frame


@dataclass(frozen=True, slots=True)
class FakeTextStream:
    """Untrusted inert bytes; not a socket, callback, or provider adapter."""
    request_id: str
    offered_bytes: bytes
    frames: tuple


@dataclass(frozen=True, slots=True)
class FakeTextReply:
    """Explicitly fake text, not a model response or security attestation."""
    text: str
    client_request_id: str
    provenance: str = PROVENANCE
    launch_authorized: bool = False
    real_model_called: bool = False
    real_transport_used: bool = False
    production_ready: bool = False


def exchange_mock(atomic, sealed, *, current_binding, stream):
    """Validate byte-bound request and all fake text frames before mock handoff.

    This uses B37-C's atomic registered-request transition, never the
    old B37-B mock_handoff route. All data is synthetic and no network
    sender or live Hospital authority exists.
    """
    if type(atomic) is not AtomicOfflineFixture:
        _deny("B37C_ATOMIC_FIXTURE_REQUIRED")
    if type(sealed) is not SealedFixture:
        _deny("FAKE_SEAL_REQUIRED")
    if type(stream) is not FakeTextStream:
        _deny("IN_MEMORY_STREAM_REQUIRED")
    try:
        verify_fixture(sealed, current_binding=current_binding)
    except (B37BRefused, ValueError, KeyError, TypeError):
        _deny("SEALED_REQUEST_INVALID")
    if (type(stream.request_id) is not str or
            not hmac.compare_digest(stream.request_id, sealed.client_request_id)):
        _deny("REQUEST_ID_MISMATCH")
    if (type(stream.offered_bytes) is not bytes or
            not hmac.compare_digest(stream.offered_bytes, sealed.payload)):
        _deny("OFFERED_BYTES_MISMATCH")
    if (type(stream.frames) is not tuple or
            not 2 <= len(stream.frames) <= MAX_FRAMES):
        _deny("FRAME_COUNT")
    text_parts = []
    total = 0
    complete = False
    for expected_seq, raw in enumerate(stream.frames):
        frame = _decode_frame(raw)
        if frame["seq"] != expected_seq or complete:
            _deny("FRAME_ORDER")
        if frame["type"] == "mock.text.completed":
            if expected_seq != len(stream.frames) - 1 or not text_parts:
                _deny("COMPLETION_ORDER")
            complete = True
        else:
            total += len(frame["text"])
            if total > MAX_TEXT_CHARS:
                _deny("TEXT_OVER_BUDGET")
            text_parts.append(frame["text"])
    if not complete:
        _deny("COMPLETION_REQUIRED")
    try:
        receipt = atomic.begin_mock(
            sealed, current_binding=current_binding,
            offered_bytes=stream.offered_bytes,
        )
        if (type(receipt) is not dict or
                receipt.get("state") != "SUBMISSION_UNCONFIRMED" or
                receipt.get("reason") != "B37C_MOCK_TRANSITION_NOT_NETWORK_DELIVERY"):
            _deny("B37C_ATOMIC_RECEIPT_INVALID")
    except (B37CRefused, B37BRefused, ValueError, KeyError, TypeError):
        _deny("B37C_ATOMIC_HANDOFF_DENIED")
    return FakeTextReply(text="".join(text_parts),
                         client_request_id=sealed.client_request_id)


def require_real_send(*_args, **_kwargs):
    """Permanent guard: this implementation has no authenticated sender."""
    _deny("NO_REAL_TRANSPORT_OR_PROVIDER_AUTHORITY")
