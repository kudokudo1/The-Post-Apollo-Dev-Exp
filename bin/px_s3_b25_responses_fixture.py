#!/usr/bin/env python3
"""B25 Responses-shaped fixtures, with NO provider/HTTP/SDK/credential execution.

This module builds data, consumes injected in-memory events and reports
untrusted tool proposals. It NEVER authenticates, runs a tool, sends a
request, resumes a session, or grants a dispatch capability.
"""
import json
import re

FIXTURE_MODEL = "px-fixture-not-a-real-model"
FUNCTION_NAME = "px_fixture_read"
MAX_EVENTS = 64
MAX_TEXT = 8192
MAX_ARGS = 4096
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_RECORD_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
KNOWN_EVENTS = frozenset((
    "response.created", "response.in_progress",
    "response.output_item.added", "response.output_item.done",
    "response.output_text.delta", "response.output_text.done",
    "response.function_call_arguments.delta",
    "response.function_call_arguments.done",
    "response.completed", "response.failed", "response.incomplete", "error",
))


def build_fixture_request(prompt, *, propose_function=False):
    """Build an inert Responses API-shaped dict, never a real API call."""
    if type(prompt) is not str or not prompt.strip() or len(prompt) > 2048:
        raise ValueError("B25_PROMPT_INVALID")
    if type(propose_function) is not bool:
        raise ValueError("B25_FUNCTION_MODE_INVALID")
    tools = []
    if propose_function:
        tools = [{
            "type": "function", "name": FUNCTION_NAME,
            "description": "Fixture-only lookup; no real file or network access.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"record_id": {"type": "string"}},
                "required": ["record_id"], "additionalProperties": False,
            },
        }]
    return {
        "model": FIXTURE_MODEL, "input": [{"role": "user", "content": prompt}],
        "store": False, "stream": True, "truncation": "disabled",
        "max_output_tokens": 512, "parallel_tool_calls": False,
        "tools": tools, "tool_choice": "auto" if tools else "none",
    }


def _result(state, reason, *, text="", proposals=()):
    return {
        "state": state, "reason": reason, "text": text,
        "proposals": list(proposals), "launchAuthorized": False,
        "toolCallsExecuted": 0, "hospitalWrites": 0,
        "stopVerified": False, "retryAuthorized": False,
        "productionReady": False,
    }


def _identifier(value):
    return type(value) is str and ID_RE.fullmatch(value) is not None


def _validate_terminal(response, response_id, added, args_done, text_seen):
    if type(response) is not dict or response.get("status") != "completed":
        raise ValueError("B25_TERMINAL_STATUS")
    if response.get("id") != response_id:
        raise ValueError("B25_RESPONSE_ID_MISMATCH")
    outputs = response.get("output")
    if type(outputs) is not list or not 1 <= len(outputs) <= 4:
        raise ValueError("B25_OUTPUT_CARDINALITY")

    text = []
    proposals = []
    for index, item in enumerate(outputs):
        if type(item) is not dict or item.get("type") not in (
                "message", "function_call", "reasoning"):
            raise ValueError("B25_NATIVE_OR_UNKNOWN_OUTPUT")
        if index not in added:
            raise ValueError("B25_OUTPUT_NOT_STREAMED")
        entry = added[index]
        if not _identifier(item.get("id")) or item["id"] != entry["id"]:
            raise ValueError("B25_ITEM_ID_MISMATCH")
        if item["type"] != entry["type"]:
            raise ValueError("B25_ITEM_TYPE_CHANGED")
        if item["type"] == "reasoning":
            # Reasoning is not forwarded to the tool broker.
            continue
        if item.get("status") != "completed":
            raise ValueError("B25_PARTIAL_ITEM")
        if item["type"] == "message":
            if item.get("role") != "assistant":
                raise ValueError("B25_MESSAGE_ROLE")
            content = item.get("content")
            if type(content) is not list or not content:
                raise ValueError("B25_MESSAGE_CONTENT")
            for part in content:
                if type(part) is not dict or part.get("type") != "output_text":
                    raise ValueError("B25_UNSUPPORTED_MESSAGE_CONTENT")
                value = part.get("text")
                if type(value) is not str or len(value) > MAX_TEXT:
                    raise ValueError("B25_MESSAGE_OVER_BUDGET")
                text.append(value)
        else:
            if (item.get("name") != FUNCTION_NAME or
                    item.get("name") != entry.get("name") or
                    item.get("call_id") != entry.get("call_id") or
                    not _identifier(item.get("call_id"))):
                raise ValueError("B25_UNAUTHORIZED_FUNCTION")
            raw = item.get("arguments")
            if type(raw) is not str or len(raw) > MAX_ARGS:
                raise ValueError("B25_ARGUMENTS_OVER_BUDGET")
            if args_done.get(index) != raw:
                raise ValueError("B25_ARGUMENTS_NOT_FINALIZED")
            try:
                arguments = json.loads(raw)
            except (ValueError, TypeError):
                raise ValueError("B25_ARGUMENTS_NOT_JSON") from None
            if (type(arguments) is not dict or set(arguments) != {"record_id"} or
                    type(arguments.get("record_id")) is not str or
                    _RECORD_RE.fullmatch(arguments["record_id"]) is None):
                raise ValueError("B25_ARGUMENTS_NOT_ALLOWED")
            proposals.append({
                "callId": item["call_id"], "function": FUNCTION_NAME,
                "arguments": {"record_id": arguments["record_id"]},
                "requiresPxAuthorization": True, "dispatchAuthorized": False,
            })
    if len(proposals) > 1 or (proposals and text):
        raise ValueError("B25_MIXED_OR_PARALLEL_OUTPUT")
    full_text = "".join(text)
    if len(full_text) > MAX_TEXT:
        raise ValueError("B25_TEXT_OVER_BUDGET")
    # Text deltas are diagnostic only. No partial delta can be executed.
    return _result(
        "UNTRUSTED_FUNCTION_PROPOSAL" if proposals else "COMPLETED_TEXT",
        "B25_PX_AUTH_REQUIRED" if proposals else "B25_TEXT_ONLY",
        text=full_text, proposals=proposals,
    )


def consume_fixture_stream(events, *, cancel_at_sequence=None):
    """Validate an injected event stream. All model output remains untrusted.

    Local cancellation is only an intent; no remote stop receipt exists.
    End-of-stream without response.completed is UNCERTAIN, never success.
    """
    if (cancel_at_sequence is not None and
            (type(cancel_at_sequence) is not int or cancel_at_sequence < 1)):
        raise ValueError("B25_CANCEL_SEQUENCE_INVALID")
    last = 0
    response_id = None
    added = {}
    args_buffer = {}
    args_done = {}
    text_seen = set()
    terminal = False
    try:
        for event in events:
            if terminal:
                return _result("REFUSED", "B25_EVENTS_AFTER_TERMINAL")
            if type(event) is not dict:
                return _result("REFUSED", "B25_EVENT_NOT_OBJECT")
            seq = event.get("sequence_number")
            if type(seq) is not int or seq <= last:
                return _result("REFUSED", "B25_SEQUENCE_INVALID")
            last = seq
            if cancel_at_sequence is not None and seq >= cancel_at_sequence:
                return _result("CANCEL_REQUESTED_UNVERIFIED", "B25_REMOTE_STOP_UNKNOWN")
            if last > MAX_EVENTS * 100:
                return _result("REFUSED", "B25_SEQUENCE_OVER_BUDGET")
            typ = event.get("type")
            if typ not in KNOWN_EVENTS:
                return _result("REFUSED", "B25_UNSUPPORTED_STREAM_EVENT")
            if response_id is None:
                if typ != "response.created":
                    return _result("REFUSED", "B25_CREATED_EVENT_REQUIRED")
                initial = event.get("response")
                if type(initial) is not dict or not _identifier(initial.get("id")):
                    return _result("REFUSED", "B25_RESPONSE_ID_INVALID")
                response_id = initial["id"]
                continue
            if typ == "response.created":
                return _result("REFUSED", "B25_DUPLICATE_CREATED")
            if typ in ("response.in_progress",):
                continue
            if typ == "response.output_item.added":
                i = event.get("output_index")
                item = event.get("item")
                if (type(i) is not int or not 0 <= i <= 3 or
                        i in added or type(item) is not dict or
                        item.get("type") not in ("message", "function_call", "reasoning") or
                        not _identifier(item.get("id"))):
                    return _result("REFUSED", "B25_NATIVE_OR_MALFORMED_ITEM")
                if item["type"] == "function_call" and (
                        item.get("name") != FUNCTION_NAME or
                        not _identifier(item.get("call_id"))):
                    return _result("REFUSED", "B25_UNAUTHORIZED_FUNCTION")
                added[i] = {"id": item["id"], "type": item["type"],
                            "name": item.get("name"), "call_id": item.get("call_id")}
            elif typ in ("response.function_call_arguments.delta",
                         "response.function_call_arguments.done",
                         "response.output_text.delta", "response.output_text.done",
                         "response.output_item.done"):
                i = event.get("output_index")
                entry = added.get(i) if type(i) is int else None
                if entry is None or event.get("item_id", entry["id"]) != entry["id"]:
                    return _result("REFUSED", "B25_STREAM_ITEM_UNBOUND")
                if typ.startswith("response.function_call_arguments"):
                    if entry["type"] != "function_call":
                        return _result("REFUSED", "B25_ARGUMENTS_WRONG_ITEM")
                    if typ.endswith(".delta"):
                        chunk = event.get("delta")
                        if type(chunk) is not str:
                            return _result("REFUSED", "B25_ARGUMENT_DELTA_INVALID")
                        value = args_buffer.get(i, "") + chunk
                        if len(value) > MAX_ARGS:
                            return _result("REFUSED", "B25_ARGUMENTS_OVER_BUDGET")
                        args_buffer[i] = value
                    else:
                        raw = event.get("arguments")
                        if (type(raw) is not str or len(raw) > MAX_ARGS or
                                (i in args_buffer and raw != args_buffer[i]) or
                                i in args_done):
                            return _result("REFUSED", "B25_ARGUMENT_FINAL_MISMATCH")
                        args_done[i] = raw
                elif typ.startswith("response.output_text"):
                    if entry["type"] != "message":
                        return _result("REFUSED", "B25_TEXT_WRONG_ITEM")
                    text_seen.add(i)
                else:
                    item = event.get("item")
                    if (type(item) is not dict or item.get("type") != entry["type"] or
                            item.get("id") != entry["id"]):
                        return _result("REFUSED", "B25_ITEM_FINAL_MISMATCH")
            elif typ == "response.completed":
                terminal = True
                try:
                    return _validate_terminal(
                        event.get("response"), response_id, added,
                        args_done, text_seen)
                except ValueError as exc:
                    return _result("REFUSED", str(exc))
            elif typ in ("response.failed", "response.incomplete", "error"):
                terminal = True
                return _result("FAILED_UNVERIFIED", "B25_PROVIDER_TERMINAL_ERROR")
            else:
                return _result("REFUSED", "B25_EVENT_UNEXPECTED")
    except Exception:
        return _result("UNCERTAIN", "B25_STREAM_TRANSPORT_INTERRUPTED")
    return _result("UNCERTAIN", "B25_NO_COMPLETED_TERMINAL")
