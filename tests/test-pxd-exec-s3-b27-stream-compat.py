#!/usr/bin/env python3
"""B27 documented-shaped SSE fixtures and transport state: no actual HTTP."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b27_stream_compat import (
    evaluate_documented_stream, normalize_documented_stream,
    SyntheticTransportTurn,
)

BINDING = {"room": "fixture-room", "patient": "fixture-patient",
           "assignment": "fixture-assignment", "turnId": "fixture-turn",
           "generation": 1}


def text_events(text="Hello from fixture"):
    added = {"id": "msg_fixture", "type": "message",
             "status": "in_progress", "role": "assistant", "content": []}
    final = {"id": "msg_fixture", "type": "message", "status": "completed",
             "role": "assistant", "content": [
                 {"type": "output_text", "text": text, "annotations": []}]}
    return [
        {"type": "response.created", "sequence_number": 1,
         "response": {"id": "resp_fixture", "status": "in_progress"}},
        {"type": "response.in_progress", "sequence_number": 2,
         "response": {"id": "resp_fixture", "status": "in_progress"}},
        {"type": "response.output_item.added", "sequence_number": 3,
         "output_index": 0, "item": added},
        {"type": "response.content_part.added", "sequence_number": 4,
         "output_index": 0, "content_index": 0, "item_id": "msg_fixture",
         "part": {"type": "output_text", "text": "", "annotations": []}},
        {"type": "response.output_text.delta", "sequence_number": 5,
         "output_index": 0, "content_index": 0, "item_id": "msg_fixture",
         "delta": text},
        {"type": "response.output_text.done", "sequence_number": 6,
         "output_index": 0, "content_index": 0, "item_id": "msg_fixture",
         "text": text},
        {"type": "response.content_part.done", "sequence_number": 7,
         "output_index": 0, "content_index": 0, "item_id": "msg_fixture",
         "part": {"type": "output_text", "text": text, "annotations": []}},
        {"type": "response.output_item.done", "sequence_number": 8,
         "output_index": 0, "item": copy.deepcopy(final)},
        {"type": "response.completed", "sequence_number": 9,
         "response": {"id": "resp_fixture", "status": "completed",
                      "output": [copy.deepcopy(final)]}},
    ]


def function_events(raw='{"record_id":"fixture.A"}'):
    added = {"id": "fc_fixture", "type": "function_call",
             "status": "in_progress", "name": "px_fixture_read",
             "call_id": "call_fixture", "arguments": ""}
    final = dict(added, status="completed", arguments=raw)
    return [
        {"type": "response.created", "sequence_number": 1,
         "response": {"id": "resp_fixture", "status": "in_progress"}},
        {"type": "response.output_item.added", "sequence_number": 2,
         "output_index": 0, "item": added},
        {"type": "response.function_call_arguments.delta", "sequence_number": 3,
         "output_index": 0, "item_id": "fc_fixture", "delta": raw},
        {"type": "response.function_call_arguments.done", "sequence_number": 4,
         "output_index": 0, "item_id": "fc_fixture", "arguments": raw},
        {"type": "response.output_item.done", "sequence_number": 5,
         "output_index": 0, "item": copy.deepcopy(final)},
        {"type": "response.completed", "sequence_number": 6,
         "response": {"id": "resp_fixture", "status": "completed",
                      "output": [copy.deepcopy(final)]}},
    ]


class B27CompatibilityTests(unittest.TestCase):
    def secure(self, outcome, *, state=None, reason=None):
        if state:
            self.assertEqual(outcome["state"], state)
        if reason:
            self.assertEqual(outcome["reason"], reason)
        self.assertFalse(outcome["launchAuthorized"])
        self.assertFalse(outcome["productionReady"])
        self.assertFalse(outcome["retryAuthorized"])
        self.assertFalse(outcome["stopVerified"])
        self.assertEqual(outcome["toolCallsExecuted"], 0)
        self.assertEqual(outcome["hospitalWrites"], 0)
        return outcome

    def test_documented_content_lifecycle_yields_untrusted_text(self):
        result = self.secure(evaluate_documented_stream(text_events()),
                             state="COMPLETED_TEXT")
        self.assertEqual(result["text"], "Hello from fixture")
        self.assertEqual(result["proposals"], [])

    def test_documented_function_call_requires_px_authorization(self):
        result = self.secure(evaluate_documented_stream(function_events()),
                             state="UNTRUSTED_FUNCTION_PROPOSAL",
                             reason="B25_PX_AUTH_REQUIRED")
        self.assertEqual(result["proposals"][0]["arguments"],
                         {"record_id": "fixture.A"})
        self.assertFalse(result["proposals"][0]["dispatchAuthorized"])

    def test_normalized_output_still_passes_existing_b25_reducer(self):
        from px_s3_b25_responses_fixture import consume_fixture_stream
        output = normalize_documented_stream(text_events())
        self.assertEqual(consume_fixture_stream(output)["state"], "COMPLETED_TEXT")

    def test_no_terminal_is_uncertain(self):
        self.secure(evaluate_documented_stream(text_events()[:-1]),
                    state="UNCERTAIN", reason="B25_NO_COMPLETED_TERMINAL")

    def test_unfinished_content_part_is_refused(self):
        events = text_events()
        events.pop(6)
        for index in (6, 7):
            events[index]["sequence_number"] -= 1
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_MESSAGE_FINAL_MISMATCH")

    def test_missing_text_done_refused(self):
        events = text_events()
        events.pop(5)
        for index in (5, 6, 7):
            events[index]["sequence_number"] -= 1
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_CONTENT_FINAL_MISMATCH")

    def test_delta_and_text_done_must_agree(self):
        events = text_events()
        events[5]["text"] = "tampered"
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_TEXT_FINAL_MISMATCH")

    def test_part_done_matches_final_text(self):
        events = text_events()
        events[6]["part"]["text"] = "tampered"
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_CONTENT_FINAL_MISMATCH")

    def test_item_final_matches_content_part(self):
        events = text_events()
        events[7]["item"]["content"][0]["text"] = "tampered"
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_MESSAGE_FINAL_MISMATCH")

    def test_terminal_snapshot_matches_item_done(self):
        events = text_events()
        events[8]["response"]["output"][0]["content"][0]["text"] = "tampered"
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_TERMINAL_OUTPUT_DRIFT")

    def test_native_browser_shell_and_mcp_items_refused(self):
        for value in ("web_search_call", "shell_call", "mcp_call",
                      "computer_call", "file_search_call"):
            with self.subTest(value=value):
                events = text_events()
                events[2]["item"]["type"] = value
                self.secure(evaluate_documented_stream(events),
                            state="REFUSED", reason="B27_OUTPUT_ITEM")

    def test_unknown_event_kind_refused(self):
        events = text_events()
        events[4]["type"] = "response.web_search_call.in_progress"
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_UNKNOWN_EVENT")

    def test_refusal_content_not_auto_treated_as_text(self):
        events = text_events()
        events[3]["part"]["type"] = "refusal"
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_CONTENT_START")

    def test_content_index_escape_refused(self):
        events = text_events()
        events[3]["content_index"] = 1
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_CONTENT_INDEX")

    def test_item_id_swap_refused(self):
        events = text_events()
        events[4]["item_id"] = "different"
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_ITEM_ID_DRIFT")

    def test_output_sequence_reuse_refused(self):
        events = text_events()
        events[4]["sequence_number"] = 4
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_SEQUENCE")

    def test_duplicate_created_refused(self):
        events = [text_events()[0], dict(text_events()[0], sequence_number=2)]
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_DUPLICATE_CREATED")

    def test_unknown_response_id_drift_refused(self):
        events = text_events()
        events[1]["response"]["id"] = "different"
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_RESPONSE_ID_DRIFT")

    def test_events_after_terminal_refused(self):
        events = text_events()
        events.append({"sequence_number": 10, "type": "response.in_progress",
                       "response": {"id": "resp_fixture"}})
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_TRAILING_EVENT")

    def test_event_budgets_refused(self):
        events = text_events()[:1] + [
            {"sequence_number": index, "type": "response.in_progress",
             "response": {"id": "resp_fixture"}}
            for index in range(2, 68)
        ]
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_EVENT_BUDGET")

    def test_text_byte_budget_refused(self):
        events = text_events("x" * 8193)
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_TEXT_DELTA")

    def test_function_delta_mismatch_refused(self):
        events = function_events()
        events[3]["arguments"] = '{"record_id":"other"}'
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_ARGUMENT_FINAL_MISMATCH")

    def test_function_final_snapshot_mismatch_refused(self):
        events = function_events()
        events[4]["item"]["arguments"] = '{"record_id":"other"}'
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_FUNCTION_FINAL_MISMATCH")

    def test_function_unapproved_fields_still_b25_refused(self):
        events = function_events('{"record_id":"safe","command":"sh"}')
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B25_ARGUMENTS_NOT_ALLOWED")

    def test_functions_with_unknown_name_refused(self):
        events = function_events()
        events[1]["item"]["name"] = "run_shell"
        self.secure(evaluate_documented_stream(events),
                    state="REFUSED", reason="B27_UNAUTHORIZED_FUNCTION")

    def test_failed_and_incomplete_not_success(self):
        for kind in ("response.failed", "response.incomplete", "error"):
            with self.subTest(kind=kind):
                events = text_events()[:2]
                events.append({"sequence_number": 3, "type": kind,
                               "response": {"id": "resp_fixture"}})
                self.secure(evaluate_documented_stream(events),
                            state="FAILED_UNVERIFIED")

    def test_transport_generator_error_returns_uncertain(self):
        def failing():
            yield text_events()[0]
            raise OSError("fixture stream interruption")
        self.secure(evaluate_documented_stream(failing()),
                    state="UNCERTAIN", reason="B27_TRANSPORT_ITERATION_INTERRUPTED")

    def test_purity_and_input_preservation(self):
        original = text_events()
        snapshot = copy.deepcopy(original)
        with patch("subprocess.Popen", side_effect=AssertionError("process")):
            with patch("subprocess.run", side_effect=AssertionError("run")):
                with patch("builtins.open", side_effect=AssertionError("open")):
                    with patch("socket.socket", side_effect=AssertionError("socket")):
                        self.secure(evaluate_documented_stream(original),
                                    state="COMPLETED_TEXT")
        self.assertEqual(original, snapshot)


class B27TransportStateTests(unittest.TestCase):
    def fixture(self, mode="FOREGROUND_STREAM"):
        return SyntheticTransportTurn(BINDING, mode=mode)

    def safe(self, state, name):
        self.assertEqual(state["state"], name)
        self.assertFalse(state["realStopVerified"])
        self.assertFalse(state["realTransport"])
        self.assertFalse(state["replayAuthorized"])
        self.assertFalse(state["toolDispatchAuthorized"])
        self.assertEqual(state["paidCalls"], 0)

    def test_foreground_text_lifecycle_is_synthetic(self):
        turn = self.fixture()
        self.safe(turn.begin("req_fixture"), "SUBMISSION_UNCONFIRMED")
        self.safe(turn.evaluate(text_events(), current_binding=BINDING),
                  "SYNTHETIC_TEXT_READY")

    def test_function_proposal_waits_for_px(self):
        turn = self.fixture()
        turn.begin("req_fixture")
        self.safe(turn.evaluate(function_events(), current_binding=BINDING),
                  "AWAITING_PX_AUTHORIZATION")
        self.assertFalse(turn.result["proposals"][0]["dispatchAuthorized"])

    def test_connection_loss_no_auto_replay(self):
        turn = self.fixture()
        turn.begin("req_fixture")
        self.safe(turn.connection_lost(), "REMOTE_OUTCOME_UNKNOWN")
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            turn.begin("req_again")

    def test_foreground_cancel_never_claims_remote_stop(self):
        turn = self.fixture()
        turn.begin("req_fixture")
        self.safe(turn.cancel(), "CANCEL_UNVERIFIED")

    def test_background_synthetic_receipt_not_proof(self):
        turn = self.fixture("BACKGROUND_POLL")
        turn.begin("req_fixture")
        self.safe(turn.cancel(simulated_background_status="cancelled"),
                  "CANCEL_UNVERIFIED")

    def test_foreground_rejects_background_receipt(self):
        turn = self.fixture()
        turn.begin("req_fixture")
        with self.assertRaisesRegex(ValueError, "SIMULATED_CANCEL_STATUS"):
            turn.cancel(simulated_background_status="cancelled")

    def test_authority_epoch_change_fences_output(self):
        turn = self.fixture()
        turn.begin("req_fixture")
        changed = dict(BINDING, generation=2)
        self.safe(turn.evaluate(text_events(), current_binding=changed),
                  "REVOKED_STOP_UNVERIFIED")
        self.assertIsNone(turn.result)

    def test_authority_room_change_fences_output(self):
        turn = self.fixture()
        turn.begin("req_fixture")
        self.safe(turn.evaluate(function_events(),
                                current_binding=dict(BINDING, room="other")),
                  "REVOKED_STOP_UNVERIFIED")

    def test_duplicate_submission_refused(self):
        turn = self.fixture()
        turn.begin("req_fixture")
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            turn.begin("req_fixture")

    def test_invalid_binding_rejected(self):
        for bad in (dict(BINDING, generation=0), {"room": "R"},
                    dict(BINDING, patient=""), dict(BINDING, generation=True)):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    SyntheticTransportTurn(bad)

    def test_unknown_transport_mode_rejected(self):
        with self.assertRaisesRegex(ValueError, "MODE"):
            self.fixture("ACTUAL_HTTP")

    def test_connection_loss_after_completed_refused(self):
        turn = self.fixture()
        turn.begin("req_fixture")
        turn.evaluate(text_events(), current_binding=BINDING)
        with self.assertRaisesRegex(ValueError, "LOSS_NOT_ACTIVE"):
            turn.connection_lost()

    def test_cancel_after_completed_refused(self):
        turn = self.fixture()
        turn.begin("req_fixture")
        turn.evaluate(text_events(), current_binding=BINDING)
        with self.assertRaisesRegex(ValueError, "CANCEL_NOT_ACTIVE"):
            turn.cancel()

    def test_cancel_unconfirmed_function_proposal(self):
        turn = self.fixture()
        turn.begin("req_fixture")
        turn.evaluate(function_events(), current_binding=BINDING)
        self.safe(turn.cancel(), "CANCEL_UNVERIFIED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
