#!/usr/bin/env python3
"""B25 offline Responses fixtures: no SDK, real credentials or network calls."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b25_responses_fixture import (
    build_fixture_request, consume_fixture_stream, FIXTURE_MODEL, FUNCTION_NAME,
)


def created():
    return {"sequence_number": 1, "type": "response.created",
            "response": {"id": "resp_fixture"}}


def message_events(text="fixture answer"):
    item = {"id": "msg_fixture", "type": "message", "role": "assistant"}
    return [
        created(),
        {"sequence_number": 2, "type": "response.output_item.added",
         "output_index": 0, "item": copy.deepcopy(item)},
        {"sequence_number": 3, "type": "response.output_text.delta",
         "output_index": 0, "item_id": item["id"], "delta": text},
        {"sequence_number": 4, "type": "response.output_item.done",
         "output_index": 0, "item": copy.deepcopy(item)},
        {"sequence_number": 5, "type": "response.completed",
         "response": {"id": "resp_fixture", "status": "completed",
                      "output": [{
                          "id": item["id"], "type": "message",
                          "role": "assistant", "status": "completed",
                          "content": [{"type": "output_text", "text": text}],
                      }]}},
    ]


def function_events(raw='{"record_id":"fixture.A"}'):
    item = {"id": "fc_fixture", "type": "function_call",
            "name": FUNCTION_NAME, "call_id": "call_fixture", "arguments": ""}
    done_item = copy.deepcopy(item)
    done_item["arguments"] = raw
    done_item["status"] = "completed"
    return [
        created(),
        {"sequence_number": 2, "type": "response.output_item.added",
         "output_index": 0, "item": item},
        {"sequence_number": 3, "type": "response.function_call_arguments.delta",
         "output_index": 0, "item_id": "fc_fixture", "delta": raw[:8]},
        {"sequence_number": 4, "type": "response.function_call_arguments.delta",
         "output_index": 0, "item_id": "fc_fixture", "delta": raw[8:]},
        {"sequence_number": 5, "type": "response.function_call_arguments.done",
         "output_index": 0, "item_id": "fc_fixture", "arguments": raw},
        {"sequence_number": 6, "type": "response.output_item.done",
         "output_index": 0, "item": done_item},
        {"sequence_number": 7, "type": "response.completed",
         "response": {"id": "resp_fixture", "status": "completed",
                      "output": [done_item]}},
    ]


class B25OfflineResponsesTests(unittest.TestCase):
    def assert_safe(self, result, *, state=None, reason=None):
        if state is not None:
            self.assertEqual(result["state"], state)
        if reason is not None:
            self.assertEqual(result["reason"], reason)
        self.assertFalse(result["launchAuthorized"])
        self.assertFalse(result["productionReady"])
        self.assertFalse(result["stopVerified"])
        self.assertFalse(result["retryAuthorized"])
        self.assertEqual(result["toolCallsExecuted"], 0)
        self.assertEqual(result["hospitalWrites"], 0)

    def test_text_request_has_no_tools_or_server_storage(self):
        req = build_fixture_request("hello")
        self.assertEqual(req["model"], FIXTURE_MODEL)
        self.assertEqual(req["tools"], [])
        self.assertEqual(req["tool_choice"], "none")
        self.assertIs(req["store"], False)
        self.assertIs(req["stream"], True)
        self.assertIs(req["parallel_tool_calls"], False)
        self.assertEqual(req["truncation"], "disabled")
        self.assertNotIn("previous_response_id", req)
        self.assertNotIn("api_key", str(req).lower())

    def test_function_request_only_explicit_strict_px_fixture_tool(self):
        req = build_fixture_request("read fixture", propose_function=True)
        self.assertEqual(req["tool_choice"], "auto")
        self.assertEqual(len(req["tools"]), 1)
        tool = req["tools"][0]
        self.assertEqual(tool["type"], "function")
        self.assertEqual(tool["name"], FUNCTION_NAME)
        self.assertIs(tool["strict"], True)
        self.assertEqual(tool["parameters"]["required"], ["record_id"])
        self.assertIs(tool["parameters"]["additionalProperties"], False)
        self.assertIs(req["parallel_tool_calls"], False)

    def test_prompt_and_mode_validation(self):
        for invalid in (None, "", " ", "x"*2049, 123):
            with self.subTest(invalid=str(invalid)[:20]):
                with self.assertRaises(ValueError):
                    build_fixture_request(invalid)
        with self.assertRaises(ValueError):
            build_fixture_request("hello", propose_function=1)

    def test_text_completed_no_external_action(self):
        result = consume_fixture_stream(message_events())
        self.assert_safe(result, state="COMPLETED_TEXT")
        self.assertEqual(result["text"], "fixture answer")
        self.assertEqual(result["proposals"], [])

    def test_function_only_untrusted_proposal_never_dispatch(self):
        result = consume_fixture_stream(function_events())
        self.assert_safe(result, state="UNTRUSTED_FUNCTION_PROPOSAL",
                         reason="B25_PX_AUTH_REQUIRED")
        self.assertEqual(len(result["proposals"]), 1)
        call = result["proposals"][0]
        self.assertEqual(call["arguments"], {"record_id": "fixture.A"})
        self.assertTrue(call["requiresPxAuthorization"])
        self.assertFalse(call["dispatchAuthorized"])

    def test_stream_ends_without_terminal_remains_uncertain(self):
        result = consume_fixture_stream(message_events()[:-1])
        self.assert_safe(result, state="UNCERTAIN",
                         reason="B25_NO_COMPLETED_TERMINAL")
        self.assertEqual(result["text"], "")

    def test_cancelled_before_completion_is_not_verified_remote_stop(self):
        result = consume_fixture_stream(function_events(), cancel_at_sequence=4)
        self.assert_safe(result, state="CANCEL_REQUESTED_UNVERIFIED",
                         reason="B25_REMOTE_STOP_UNKNOWN")
        self.assertEqual(result["proposals"], [])

    def test_bad_cancel_sequence_rejected(self):
        for sequence in ("3", 0, True, -1):
            with self.subTest(sequence=sequence):
                with self.assertRaises(ValueError):
                    consume_fixture_stream(function_events(),
                                           cancel_at_sequence=sequence)

    def test_provider_failure_incomplete_and_error_do_not_succeed(self):
        for typ in ("response.failed", "response.incomplete", "error"):
            with self.subTest(typ=typ):
                events = message_events()[:-1]
                events.append({"sequence_number": 5, "type": typ,
                               "response": {"id": "resp_fixture"}})
                self.assert_safe(consume_fixture_stream(events),
                                 state="FAILED_UNVERIFIED")

    def test_unknown_built_in_and_remote_tool_items_refused(self):
        for typ in ("shell_call", "mcp_call", "web_search_call",
                    "computer_call", "custom_tool_call", "file_search_call"):
            with self.subTest(typ=typ):
                events = function_events()
                events[1]["item"]["type"] = typ
                self.assert_safe(consume_fixture_stream(events),
                                 state="REFUSED",
                                 reason="B25_NATIVE_OR_MALFORMED_ITEM")

    def test_unknown_stream_event_refused(self):
        events = message_events()
        events[2]["type"] = "response.mcp_call_arguments.delta"
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_UNSUPPORTED_STREAM_EVENT")

    def test_sequence_reuse_and_out_of_order_refused(self):
        for number in (1, 0, -1):
            events = message_events()
            events[2]["sequence_number"] = number
            self.assert_safe(consume_fixture_stream(events),
                             state="REFUSED", reason="B25_SEQUENCE_INVALID")

    def test_response_id_changed_at_terminal_refused(self):
        events = message_events()
        events[-1]["response"]["id"] = "resp_other"
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_RESPONSE_ID_MISMATCH")

    def test_terminal_not_completed_refused(self):
        events = message_events()
        events[-1]["response"]["status"] = "in_progress"
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_TERMINAL_STATUS")

    def test_completed_without_created_is_refused(self):
        events = message_events()[1:]
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_CREATED_EVENT_REQUIRED")

    def test_duplicate_created_refused(self):
        events = [created(), {**created(), "sequence_number": 2}]
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_DUPLICATE_CREATED")

    def test_foreign_or_unexpected_function_name_refused(self):
        events = function_events()
        events[1]["item"]["name"] = "run_shell"
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_UNAUTHORIZED_FUNCTION")

    def test_missing_final_function_arguments_refused(self):
        events = function_events()
        events.pop(4)
        events[4]["sequence_number"] = 5
        events[5]["sequence_number"] = 6
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_ARGUMENTS_NOT_FINALIZED")

    def test_tampered_function_delta_vs_done_refused(self):
        events = function_events()
        events[4]["arguments"] = '{"record_id":"changed"}'
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_ARGUMENT_FINAL_MISMATCH")

    def test_tampered_function_final_snapshot_refused(self):
        events = function_events()
        events[-1]["response"]["output"][0]["arguments"] = '{"record_id":"altered"}'
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_ARGUMENTS_NOT_FINALIZED")

    def test_function_json_invalid_or_more_fields_refused(self):
        for raw,reason in (("{broken","B25_ARGUMENTS_NOT_JSON"),
                           ('{"record_id":"A","command":"rm"}',
                            "B25_ARGUMENTS_NOT_ALLOWED"),
                           ('{"record_id":"../../secrets"}',
                            "B25_ARGUMENTS_NOT_ALLOWED")):
            with self.subTest(raw=raw):
                self.assert_safe(consume_fixture_stream(function_events(raw)),
                                 state="REFUSED", reason=reason)

    def test_missing_scope_or_non_text_output_refused(self):
        events = message_events()
        events[-1]["response"]["output"][0]["content"] = [
            {"type": "output_image", "image": "fake"}
        ]
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_UNSUPPORTED_MESSAGE_CONTENT")

    def test_bad_output_type_at_terminal_refused(self):
        events = message_events()
        events[-1]["response"]["output"][0]["type"] = "web_search_call"
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_NATIVE_OR_UNKNOWN_OUTPUT")

    def test_unbound_output_item_rejected(self):
        events = function_events()
        events[3]["item_id"] = "foreign"
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_STREAM_ITEM_UNBOUND")

    def test_stream_iteration_error_is_uncertain_not_retryable(self):
        def broken():
            yield created()
            raise OSError("mock transport interrupted")
        self.assert_safe(consume_fixture_stream(broken()),
                         state="UNCERTAIN",
                         reason="B25_STREAM_TRANSPORT_INTERRUPTED")

    def test_late_event_after_completed_is_refused(self):
        events = message_events()
        events.append({"sequence_number": 6, "type": "response.in_progress",
                       "response": {"id": "resp_fixture"}})
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_EVENTS_AFTER_TERMINAL")

    def test_event_count_is_bounded(self):
        events = [created()]
        events += [
            {"sequence_number": i, "type": "response.in_progress",
             "response": {"id": "resp_fixture"}}
            for i in range(2, 68)
        ]
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED",
                         reason="B25_EVENT_COUNT_OVER_BUDGET")

    def test_unfinalized_output_is_refused(self):
        events = function_events()
        events.pop(5)
        events[-1]["sequence_number"] = 6
        self.assert_safe(consume_fixture_stream(events),
                         state="REFUSED", reason="B25_OUTPUT_NOT_FINALIZED")

    def test_no_ambient_io_or_persistent_mutation(self):
        events = message_events()
        original = copy.deepcopy(events)
        with patch("subprocess.Popen", side_effect=AssertionError("process")):
            with patch("subprocess.run", side_effect=AssertionError("run")):
                with patch("builtins.open", side_effect=AssertionError("open")):
                    with patch("socket.socket", side_effect=AssertionError("socket")):
                        req = build_fixture_request("hello")
                        result = consume_fixture_stream(events)
        self.assertEqual(req["model"], FIXTURE_MODEL)
        self.assert_safe(result, state="COMPLETED_TEXT")
        self.assertEqual(events, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
