#!/usr/bin/env python3
"""B37-A: offline-only, text-only Responses-shaped request contract.

NO HTTP, SDK, credentials, real model selection, provider launch, broker,
Hospital attachment, persistent state or tool dispatch. Passing validation
proves only this fixture's JSON shape, NEVER permission to send it.
"""
import json

from px_s3_b25_responses_fixture import (
    FIXTURE_MODEL, build_fixture_request,
)

MAX_WIRE_BYTES = 8192
MAX_PROMPT_CHARS = 2048

# Fixed, narrow envelope. Extra fields (including previous_response_id,
# headers, URLs, MCP, include, instructions, or a different model) fail shut.
REQUIRED_KEYS = frozenset((
    "model", "input", "store", "stream", "background", "truncation",
    "max_output_tokens", "parallel_tool_calls", "tools", "tool_choice",
))
FIXED = {
    "model": FIXTURE_MODEL,
    "store": False,
    "stream": True,
    "background": False,
    "truncation": "disabled",
    "max_output_tokens": 512,
    "parallel_tool_calls": False,
    "tools": [],
    "tool_choice": "none",
}


def _refuse(reason):
    # Error codes only: never echo prompt, payload, header or credential text.
    raise ValueError("B37A_" + reason)


def _valid_prompt(prompt):
    if type(prompt) is not str or not prompt.strip():
        _refuse("PROMPT_INVALID")
    if len(prompt) > MAX_PROMPT_CHARS:
        _refuse("PROMPT_OVER_BUDGET")
    try:
        prompt.encode("utf-8", errors="strict")
    except UnicodeError:
        _refuse("PROMPT_ENCODING")
    return prompt


def build_request(prompt):
    """Construct inert fixture request, reusing B25's tool-free baseline."""
    _valid_prompt(prompt)
    request = build_fixture_request(prompt)
    request["background"] = False
    validate_request(request)
    return request


def validate_request(candidate):
    """Return a validated plain dict, NOT a dispatch capability."""
    if type(candidate) is not dict or set(candidate) != REQUIRED_KEYS:
        _refuse("ROOT_SCHEMA")
    for key, expected in FIXED.items():
        value = candidate[key]
        if type(value) is not type(expected) or value != expected:
            _refuse("FIXED_" + key.upper())
    items = candidate["input"]
    if type(items) is not list or len(items) != 1:
        _refuse("INPUT_CARDINALITY")
    item = items[0]
    if type(item) is not dict or set(item) != {"role", "content"}:
        _refuse("INPUT_SCHEMA")
    if type(item["role"]) is not str or item["role"] != "user":
        _refuse("INPUT_ROLE")
    _valid_prompt(item["content"])
    return candidate


def _no_duplicates(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            _refuse("DUPLICATE_KEY")
        data[key] = value
    return data


def _no_nonfinite(_value):
    _refuse("NONFINITE_NUMBER")


def validate_wire_payload(payload):
    """Decode strict JSON from memory; no files, sockets or network involved."""
    if type(payload) is bytes:
        if len(payload) > MAX_WIRE_BYTES:
            _refuse("WIRE_OVER_BUDGET")
        try:
            payload = payload.decode("utf-8", errors="strict")
        except UnicodeError:
            _refuse("WIRE_ENCODING")
    elif type(payload) is str:
        try:
            size = len(payload.encode("utf-8", errors="strict"))
        except UnicodeError:
            _refuse("WIRE_ENCODING")
        if size > MAX_WIRE_BYTES:
            _refuse("WIRE_OVER_BUDGET")
    else:
        _refuse("WIRE_TYPE")
    try:
        candidate = json.loads(
            payload, object_pairs_hook=_no_duplicates,
            parse_constant=_no_nonfinite,
        )
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        _refuse("WIRE_JSON")
    return validate_request(candidate)


def inspect_request(candidate):
    """Sanitized diagnostic only. Never returns payload or launch authority."""
    try:
        if type(candidate) is dict:
            validate_request(candidate)
        else:
            validate_wire_payload(candidate)
        valid, reason = True, "B37A_FIXTURE_SHAPE_ONLY"
    except ValueError as exc:
        valid = False
        reason = str(exc) if str(exc).startswith("B37A_") else "B37A_REFUSED"
    return {
        "schema": "B37A_OFFLINE_TOOL_FREE_REQUEST_V1",
        "decision": "OFFLINE_SHAPE_ONLY" if valid else "DENY",
        "requestShapeValid": valid,
        "reason": reason,
        "modelOnlyCertified": False,
        "launchAuthorized": False,
        "productionReady": False,
        "providerStarted": False,
        "modelCalls": 0,
        "toolCalls": 0,
        "hospitalWrites": 0,
        "stopVerified": False,
        "retryAuthorized": False,
    }


def require_launch_authority(_candidate):
    """Explicit negative guard for anyone attempting to use this as a launcher."""
    raise RuntimeError("B37A_REFUSED_NO_TRANSPORT_OR_AUTHORITY")
