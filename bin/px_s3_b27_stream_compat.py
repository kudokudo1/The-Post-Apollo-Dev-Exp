#!/usr/bin/env python3
"""B27 offline-only Responses SSE compatibility and transport-state fixtures.

This module accepts only in-memory event dictionaries. It makes no network
requests, does no authentication, owns no credentials, and cannot run tools.
A synthetic terminal event is not a trusted provider receipt.
"""
import re

from px_s3_b25_responses_fixture import consume_fixture_stream

MAX_EVENTS = 64
MAX_TEXT = 8192
MAX_ARGUMENTS = 4096
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
SUPPORTED = frozenset((
    "response.created", "response.in_progress",
    "response.output_item.added", "response.output_item.done",
    "response.content_part.added", "response.content_part.done",
    "response.output_text.delta", "response.output_text.done",
    "response.function_call_arguments.delta",
    "response.function_call_arguments.done", "response.completed",
    "response.failed", "response.incomplete", "error",
))
TERMINAL = frozenset(("response.completed", "response.failed",
                      "response.incomplete", "error"))
VALID_ITEM = frozenset(("message", "function_call"))


class FixtureRefusal(Exception):
    """Non-sensitive reason for refusing untrusted, malformed synthetic input."""


def _refuse(reason):
    raise FixtureRefusal("B27_" + reason)


def _id(value):
    return type(value) is str and IDENTIFIER.fullmatch(value) is not None


def _index(value, maximum):
    return type(value) is int and 0 <= value < maximum


def _denied(state, reason):
    return {
        "state": state, "reason": reason, "text": "", "proposals": [],
        "launchAuthorized": False, "toolCallsExecuted": 0,
        "hospitalWrites": 0, "stopVerified": False,
        "retryAuthorized": False, "productionReady": False,
    }


def normalize_documented_stream(events):
    """Translate a narrow *documented* event subset to B25's inert reducer.

    Content-part and text-delta lifecycles must match their finalized
    content. No partial text or function arguments are forwarded as tool
    authority. Unknown new API events are refused until separately reviewed.
    """
    output = []
    seen = {}
    parts = {}
    arguments = {}
    last_seq = 0
    response_id = None
    terminal = False
    count = 0

    def emit(evt):
        item = dict(evt)
        item["sequence_number"] = len(output) + 1
        output.append(item)

    try:
        for evt in events:
            count += 1
            if count > MAX_EVENTS:
                _refuse("EVENT_BUDGET")
            if terminal:
                _refuse("TRAILING_EVENT")
            if type(evt) is not dict:
                _refuse("EVENT_TYPE")
            seq = evt.get("sequence_number")
            if type(seq) is not int or seq <= last_seq:
                _refuse("SEQUENCE")
            last_seq = seq
            typ = evt.get("type")
            if typ not in SUPPORTED:
                _refuse("UNKNOWN_EVENT")
            if response_id is None:
                if typ != "response.created" or type(evt.get("response")) is not dict:
                    _refuse("CREATED_REQUIRED")
                response_id = evt["response"].get("id")
                if not _id(response_id):
                    _refuse("RESPONSE_ID")
                emit(evt)
                continue
            if typ == "response.created":
                _refuse("DUPLICATE_CREATED")
            if typ == "response.in_progress":
                r = evt.get("response")
                if type(r) is not dict or r.get("id") != response_id:
                    _refuse("RESPONSE_ID_DRIFT")
                emit(evt)
            elif typ == "response.output_item.added":
                ix, item = evt.get("output_index"), evt.get("item")
                if (not _index(ix, 4) or ix in seen or type(item) is not dict or
                        item.get("type") not in VALID_ITEM or not _id(item.get("id"))):
                    _refuse("OUTPUT_ITEM")
                if item["type"] == "function_call" and (
                        item.get("name") != "px_fixture_read" or
                        not _id(item.get("call_id"))):
                    _refuse("UNAUTHORIZED_FUNCTION")
                if item["type"] == "message" and item.get("role") != "assistant":
                    _refuse("MESSAGE_ROLE")
                seen[ix] = {"id": item["id"], "type": item["type"],
                            "name": item.get("name"), "call_id": item.get("call_id"),
                            "done": False, "snapshot": None}
                emit(evt)
            elif typ in (
                    "response.content_part.added", "response.content_part.done",
                    "response.output_text.delta", "response.output_text.done",
                    "response.function_call_arguments.delta",
                    "response.function_call_arguments.done",
                    "response.output_item.done"):
                ix = evt.get("output_index")
                item = seen.get(ix) if type(ix) is int else None
                if item is None or item["done"]:
                    _refuse("UNBOUND_OR_FINALIZED_ITEM")
                if evt.get("item_id", item["id"]) != item["id"]:
                    _refuse("ITEM_ID_DRIFT")
                if typ.startswith("response.content_part") or typ.startswith("response.output_text"):
                    if item["type"] != "message" or not _index(evt.get("content_index"), 1):
                        _refuse("CONTENT_INDEX")
                    key = (ix, 0)
                    if typ == "response.content_part.added":
                        part = evt.get("part")
                        if (key in parts or type(part) is not dict or
                                part.get("type") != "output_text" or
                                part.get("text") != ""):
                            _refuse("CONTENT_START")
                        parts[key] = {"text": "", "textDone": False, "partDone": False}
                    elif key not in parts:
                        _refuse("CONTENT_UNBOUND")
                    elif typ == "response.output_text.delta":
                        p = parts[key]
                        chunk = evt.get("delta")
                        if (p["textDone"] or type(chunk) is not str or
                                len(p["text"]) + len(chunk) > MAX_TEXT):
                            _refuse("TEXT_DELTA")
                        p["text"] += chunk
                    elif typ == "response.output_text.done":
                        p = parts[key]
                        if p["textDone"] or evt.get("text") != p["text"]:
                            _refuse("TEXT_FINAL_MISMATCH")
                        p["textDone"] = True
                    else:
                        p = parts[key]
                        part = evt.get("part")
                        if (not p["textDone"] or p["partDone"] or type(part) is not dict or
                                part.get("type") != "output_text" or
                                part.get("text") != p["text"]):
                            _refuse("CONTENT_FINAL_MISMATCH")
                        p["partDone"] = True
                    # B25 validates final item and response, not partial deltas.
                elif typ.startswith("response.function_call_arguments"):
                    if item["type"] != "function_call":
                        _refuse("ARGUMENTS_WRONG_ITEM")
                    arg = arguments.setdefault(ix, {"buffer": "", "done": False})
                    if typ.endswith(".delta"):
                        chunk = evt.get("delta")
                        if (arg["done"] or type(chunk) is not str or
                                len(arg["buffer"]) + len(chunk) > MAX_ARGUMENTS):
                            _refuse("ARGUMENT_DELTA")
                        arg["buffer"] += chunk
                    else:
                        if arg["done"] or evt.get("arguments") != arg["buffer"]:
                            _refuse("ARGUMENT_FINAL_MISMATCH")
                        arg["done"] = True
                    emit(evt)
                else:
                    final = evt.get("item")
                    if (type(final) is not dict or final.get("id") != item["id"] or
                            final.get("type") != item["type"] or
                            final.get("status") != "completed"):
                        _refuse("ITEM_FINAL_MISMATCH")
                    if item["type"] == "message":
                        p = parts.get((ix, 0))
                        content = final.get("content")
                        if (p is None or not p["partDone"] or type(content) is not list or
                                len(content) != 1 or type(content[0]) is not dict or
                                content[0].get("type") != "output_text" or
                                content[0].get("text") != p["text"]):
                            _refuse("MESSAGE_FINAL_MISMATCH")
                    else:
                        arg = arguments.get(ix)
                        if (arg is None or not arg["done"] or
                                final.get("arguments") != arg["buffer"] or
                                final.get("name") != item["name"] or
                                final.get("call_id") != item["call_id"]):
                            _refuse("FUNCTION_FINAL_MISMATCH")
                    item["done"] = True
                    item["snapshot"] = final
                    emit(evt)
            elif typ in TERMINAL:
                terminal = True
                if typ == "response.completed":
                    response = evt.get("response")
                    if (type(response) is not dict or response.get("id") != response_id or
                            response.get("status") != "completed" or
                            type(response.get("output")) is not list or
                            len(response["output"]) != len(seen) or
                            set(seen) != set(range(len(seen)))):
                        _refuse("TERMINAL_SCOPE")
                    for ix, final in enumerate(response["output"]):
                        if not seen[ix]["done"] or final != seen[ix]["snapshot"]:
                            _refuse("TERMINAL_OUTPUT_DRIFT")
                elif typ != "error":
                    response = evt.get("response")
                    if type(response) is not dict or response.get("id") != response_id:
                        _refuse("TERMINAL_RESPONSE_ID")
                emit(evt)
    except FixtureRefusal:
        raise
    except Exception:
        _refuse("TRANSPORT_ITERATION_INTERRUPTED")
    return output


def evaluate_documented_stream(events):
    """All successful results are *synthetic* and all tool calls untrusted."""
    try:
        normalized = normalize_documented_stream(events)
    except FixtureRefusal as err:
        reason = str(err)
        return _denied("UNCERTAIN" if reason == "B27_TRANSPORT_ITERATION_INTERRUPTED"
                       else "REFUSED", reason)
    return consume_fixture_stream(normalized)


class SyntheticTransportTurn:
    """No-network state machine. Never acknowledges real remote cancellation."""

    def __init__(self, binding, *, mode="FOREGROUND_STREAM"):
        expected = {"room", "patient", "assignment", "turnId", "generation"}
        if (type(binding) is not dict or set(binding) != expected or
                any(type(binding[k]) is not str or not binding[k].strip() or
                    len(binding[k]) > 128 for k in expected - {"generation"}) or
                type(binding["generation"]) is not int or binding["generation"] < 1):
            raise ValueError("B27_AUTHORITY_BINDING")
        if mode not in ("FOREGROUND_STREAM", "BACKGROUND_POLL"):
            raise ValueError("B27_MODE")
        self.binding = dict(binding)
        self.mode = mode
        self.state = "PREPARED"
        self.request_id = None
        self.result = None

    def _snapshot(self, reason):
        return {"state": self.state, "reason": reason, "mode": self.mode,
                "requestId": self.request_id, "realTransport": False,
                "realStopVerified": False, "replayAuthorized": False,
                "toolDispatchAuthorized": False, "paidCalls": 0}

    def begin(self, request_id):
        if self.state != "PREPARED":
            raise ValueError("B27_DUPLICATE_OR_UNSAFE_SUBMISSION")
        if not _id(request_id):
            raise ValueError("B27_REQUEST_ID")
        self.request_id = request_id
        self.state = "SUBMISSION_UNCONFIRMED"
        return self._snapshot("B27_NO_NETWORK_REQUEST")

    def evaluate(self, events, *, current_binding):
        if self.state != "SUBMISSION_UNCONFIRMED":
            raise ValueError("B27_EVALUATION_NOT_ACTIVE")
        if type(current_binding) is not dict or current_binding != self.binding:
            self.state = "REVOKED_STOP_UNVERIFIED"
            return self._snapshot("B27_AUTHORITY_CHANGED")
        self.result = evaluate_documented_stream(events)
        states = {
            "COMPLETED_TEXT": "SYNTHETIC_TEXT_READY",
            "UNTRUSTED_FUNCTION_PROPOSAL": "AWAITING_PX_AUTHORIZATION",
            "REFUSED": "REFUSED",
            "UNCERTAIN": "REMOTE_OUTCOME_UNKNOWN",
            "FAILED_UNVERIFIED": "FAILED_UNVERIFIED",
        }
        self.state = states.get(self.result["state"], "REMOTE_OUTCOME_UNKNOWN")
        return self._snapshot(self.result["reason"])

    def connection_lost(self):
        if self.state != "SUBMISSION_UNCONFIRMED":
            raise ValueError("B27_LOSS_NOT_ACTIVE")
        self.state = "REMOTE_OUTCOME_UNKNOWN"
        return self._snapshot("B27_UNKNOWN_REMOTE_DELIVERY")

    def cancel(self, *, simulated_background_status=None):
        if self.state not in ("SUBMISSION_UNCONFIRMED", "AWAITING_PX_AUTHORIZATION"):
            raise ValueError("B27_CANCEL_NOT_ACTIVE")
        if simulated_background_status is not None and (
                self.mode != "BACKGROUND_POLL" or
                simulated_background_status not in ("cancelled", "cancelling")):
            raise ValueError("B27_SIMULATED_CANCEL_STATUS")
        self.state = "CANCEL_UNVERIFIED"
        return self._snapshot("B27_MOCK_CANCEL_NOT_REAL_STOP")
