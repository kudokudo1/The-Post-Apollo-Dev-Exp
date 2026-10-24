#!/usr/bin/env python3
"""B30 end-to-end disposable SQLite+B27+B25 compatibility integration."""
import copy
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b30_integrated_fixture import OfflineIntegratedTurn
from px_s3_b29_transport_ledger import Refused

BIND = {"room": "roomA", "patient": "patientA", "assignment": "assignmentA",
        "bed": "bedA", "turnId": "turnA", "generation": 1}


def text_events(text="fixture response", response_id="respA"):
    added = {"id": "msgA", "type": "message", "role": "assistant",
             "status": "in_progress", "content": []}
    done = {"id": "msgA", "type": "message", "role": "assistant",
            "status": "completed", "content": [
                {"type": "output_text", "text": text, "annotations": []}]}
    return [
        {"type": "response.created", "sequence_number": 1,
         "response": {"id": response_id, "status": "in_progress"}},
        {"type": "response.in_progress", "sequence_number": 2,
         "response": {"id": response_id, "status": "in_progress"}},
        {"type": "response.output_item.added", "sequence_number": 3,
         "output_index": 0, "item": added},
        {"type": "response.content_part.added", "sequence_number": 4,
         "output_index": 0, "content_index": 0, "item_id": "msgA",
         "part": {"type": "output_text", "text": "", "annotations": []}},
        {"type": "response.output_text.delta", "sequence_number": 5,
         "output_index": 0, "content_index": 0, "item_id": "msgA",
         "delta": text},
        {"type": "response.output_text.done", "sequence_number": 6,
         "output_index": 0, "content_index": 0, "item_id": "msgA",
         "text": text},
        {"type": "response.content_part.done", "sequence_number": 7,
         "output_index": 0, "content_index": 0, "item_id": "msgA",
         "part": {"type": "output_text", "text": text, "annotations": []}},
        {"type": "response.output_item.done", "sequence_number": 8,
         "output_index": 0, "item": copy.deepcopy(done)},
        {"type": "response.completed", "sequence_number": 9,
         "response": {"id": response_id, "status": "completed",
                      "output": [copy.deepcopy(done)]}},
    ]


def function_events(raw='{"record_id":"test.A"}', response_id="respA"):
    start = {"id": "fcA", "type": "function_call", "name": "px_fixture_read",
             "call_id": "callA", "status": "in_progress", "arguments": ""}
    done = dict(start, arguments=raw, status="completed")
    return [
        {"type": "response.created", "sequence_number": 1,
         "response": {"id": response_id, "status": "in_progress"}},
        {"type": "response.output_item.added", "sequence_number": 2,
         "output_index": 0, "item": start},
        {"type": "response.function_call_arguments.delta", "sequence_number": 3,
         "output_index": 0, "item_id": "fcA", "delta": raw},
        {"type": "response.function_call_arguments.done", "sequence_number": 4,
         "output_index": 0, "item_id": "fcA", "arguments": raw},
        {"type": "response.output_item.done", "sequence_number": 5,
         "output_index": 0, "item": copy.deepcopy(done)},
        {"type": "response.completed", "sequence_number": 6,
         "response": {"id": response_id, "status": "completed",
                      "output": [copy.deepcopy(done)]}},
    ]


class B30BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="b30-offline-")
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "fixture.sqlite"
        self.conn = sqlite3.connect(self.file, isolation_level=None)
        self.addCleanup(self.conn.close)
        self.turn = OfflineIntegratedTurn(self.conn)
        self.turn.configure_mock_budget("scopeA", 100)

    def reserve(self, *, attempt="attemptA", client="clientA",
                binding=BIND, units=30, mode="FOREGROUND_STREAM"):
        return self.turn.reserve(
            attempt_id=attempt, client_request_id=client,
            scope="scopeA", binding=binding, mode=mode, units=units)

    def submitted(self, **kwargs):
        self.reserve(**kwargs)
        return self.turn.submit_simulated("attemptA", BIND)

    def assert_inert(self, snap, *, state=None):
        if state is not None:
            self.assertEqual(snap["state"], state)
        for key in ("launchAuthorized", "toolDispatchAuthorized",
                    "realStopVerified", "realSpendVerified",
                    "retryAuthorized", "productionReady"):
            self.assertIs(snap[key], False, key)
        self.assertEqual(snap["realProviderCalls"], 0)
        return snap

    def reopen(self):
        self.conn.close()
        self.conn = sqlite3.connect(self.file, isolation_level=None)
        self.addCleanup(self.conn.close)
        self.turn = OfflineIntegratedTurn(self.conn)

    def budget(self):
        return self.turn.ledger.budget("scopeA")

    def test_no_submission_without_reservation(self):
        with self.assertRaisesRegex(Refused, "ATTEMPT_MISSING"):
            self.turn.submit_simulated("attemptA", BIND)

    def test_reserved_attempt_is_durable_before_submission(self):
        self.reserve()
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.reopen()
        self.assert_inert(self.turn.snapshot("attemptA"), state="RESERVED")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_submit_reopen_then_valid_text_observation(self):
        self.submitted()
        self.reopen()
        result = self.assert_inert(self.turn.observe_simulated(
            "attemptA", BIND, text_events()
        ), state="SUBMISSION_UNCONFIRMED")
        self.assertEqual(result["validatedMockText"], "fixture response")
        self.assertEqual(result["responseId"], "respA")
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.assertEqual(self.budget()["used_units"], 0)

    def test_valid_stream_requires_separate_mock_settlement(self):
        self.submitted()
        self.turn.observe_simulated("attemptA", BIND, text_events())
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.reopen()
        result = self.assert_inert(self.turn.settle_simulated(
            "attemptA", BIND, text_events(), 12
        ), state="MOCK_COMPLETED")
        self.assertEqual(result["validatedMockText"], "fixture response")
        self.assertEqual(self.budget()["reserved_units"], 0)
        self.assertEqual(self.budget()["used_units"], 12)

    def test_duplicate_mock_settlement_not_repeatable(self):
        self.submitted()
        self.turn.settle_simulated("attemptA", BIND, text_events(), 10)
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE_OR_REVOKED"):
            self.turn.settle_simulated("attemptA", BIND, text_events(), 10)
        self.assertEqual(self.budget()["used_units"], 10)

    def test_crash_after_validation_before_settlement_retains_hold(self):
        self.submitted()
        self.turn.observe_simulated("attemptA", BIND, text_events())
        self.reopen()
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.assert_inert(self.turn.snapshot("attemptA"),
                          state="SUBMISSION_UNCONFIRMED")
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.turn.submit_simulated("attemptA", BIND)
        self.turn.settle_simulated("attemptA", BIND, text_events(), 20)
        self.assertEqual(self.budget()["used_units"], 20)

    def test_partial_stream_holds_budget_after_restart(self):
        self.submitted()
        result = self.turn.observe_simulated("attemptA", BIND,
                                             text_events()[:-1])
        self.assert_inert(result, state="REMOTE_OUTCOME_UNKNOWN")
        self.reopen()
        self.assert_inert(self.turn.snapshot("attemptA"),
                          state="REMOTE_OUTCOME_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 30)
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE_OR_REVOKED"):
            self.turn.settle_simulated("attemptA", BIND, text_events(), 5)

    def test_transport_lost_retains_identity_after_reopen(self):
        self.submitted()
        self.assert_inert(self.turn.interrupt_simulated("attemptA"),
                          state="REMOTE_OUTCOME_UNKNOWN")
        self.reopen()
        self.assertEqual(self.turn.snapshot("attemptA")["attemptId"], "attemptA")
        self.assertEqual(self.budget()["reserved_units"], 30)
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.turn.submit_simulated("attemptA", BIND)

    def test_cancel_before_submission_releases_only_unused_budget(self):
        self.reserve()
        self.assert_inert(self.turn.cancel_simulated("attemptA"),
                          state="ABORTED_PRE_SUBMISSION")
        self.reopen()
        self.assertEqual(self.budget()["reserved_units"], 0)
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.turn.submit_simulated("attemptA", BIND)

    def test_cancel_after_submission_retains_hold_after_restart(self):
        self.submitted()
        self.assert_inert(self.turn.cancel_simulated("attemptA"),
                          state="CANCEL_PENDING")
        self.reopen()
        self.assert_inert(self.turn.snapshot("attemptA"),
                          state="CANCEL_PENDING")
        self.assertEqual(self.budget()["reserved_units"], 30)
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE_OR_REVOKED"):
            self.turn.observe_simulated("attemptA", BIND, text_events())

    def test_background_mock_cancel_receipt_not_stop_proof(self):
        self.submitted(mode="BACKGROUND_POLL")
        self.turn.observe_simulated("attemptA", BIND, text_events())
        self.turn.cancel_simulated("attemptA")
        self.reopen()
        result = self.turn.background_cancel_observed(
            "attemptA", "respA", "cancelled")
        self.assert_inert(result, state="MOCK_CANCELLED_UNVERIFIED")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_cancel_unknown_delivery_keeps_spending_hold(self):
        self.submitted()
        self.turn.interrupt_simulated("attemptA")
        self.turn.cancel_simulated("attemptA")
        self.reopen()
        self.assert_inert(self.turn.snapshot("attemptA"),
                          state="CANCEL_PENDING")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_wrong_bed_fences_observation_and_is_permanent(self):
        self.submitted()
        changed = dict(BIND, bed="foreignBed")
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE_OR_REVOKED"):
            self.turn.observe_simulated("attemptA", changed, text_events())
        self.reopen()
        self.assert_inert(self.turn.snapshot("attemptA"),
                          state="REVOKED_REMOTE_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 30)
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE_OR_REVOKED"):
            self.turn.observe_simulated("attemptA", BIND, text_events())

    def test_changed_generation_fences_settlement(self):
        self.submitted()
        self.turn.observe_simulated("attemptA", BIND, text_events())
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE_OR_REVOKED"):
            self.turn.settle_simulated(
                "attemptA", dict(BIND, generation=2), text_events(), 1)
        self.reopen()
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.assert_inert(self.turn.snapshot("attemptA"),
                          state="REVOKED_REMOTE_UNKNOWN")

    def test_changed_patient_and_assignment_also_fence(self):
        for key in ("patient", "assignment", "room", "turnId"):
            with self.subTest(key=key):
                self.conn.execute("DELETE FROM b29_fixture_attempts")
                self.conn.execute("UPDATE b29_fixture_budgets SET reserved_units=0")
                self.submitted()
                with self.assertRaisesRegex(Refused, "NOT_ACTIVE_OR_REVOKED"):
                    self.turn.observe_simulated(
                        "attemptA", dict(BIND, **{key: "foreign"}), text_events())
                self.assertEqual(self.budget()["reserved_units"], 30)

    def test_function_proposal_untrusted_and_no_dispatch(self):
        self.submitted()
        r = self.assert_inert(self.turn.observe_simulated(
            "attemptA", BIND, function_events()
        ), state="SUBMISSION_UNCONFIRMED")
        self.assertEqual(r["untrustedProposalCount"], 1)
        self.assertEqual(r["validatedMockText"], "")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_function_proposal_settlement_never_executes_tool(self):
        self.submitted()
        r = self.turn.settle_simulated(
            "attemptA", BIND, function_events(), 6)
        self.assert_inert(r, state="MOCK_COMPLETED")
        self.assertEqual(r["untrustedProposalCount"], 1)
        self.assertFalse(r["toolDispatchAuthorized"])
        self.assertEqual(self.budget()["used_units"], 6)

    def test_unapproved_function_parameters_fail_closed(self):
        self.submitted()
        result = self.turn.observe_simulated(
            "attemptA", BIND, function_events('{"record_id":"A","shell":"x"}'))
        self.assert_inert(result, state="REMOTE_OUTCOME_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.assertIsNone(result["responseId"])

    def test_native_tool_stream_fails_closed(self):
        self.submitted()
        events = text_events()
        events[2]["item"]["type"] = "shell_call"
        r = self.turn.observe_simulated("attemptA", BIND, events)
        self.assert_inert(r, state="REMOTE_OUTCOME_UNKNOWN")
        self.assertEqual(r["untrustedProposalCount"], 0)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_response_id_drift_cannot_settle(self):
        self.submitted()
        self.turn.observe_simulated("attemptA", BIND, text_events())
        with self.assertRaisesRegex(Refused, "RESPONSE_ID_DRIFT"):
            self.turn.settle_simulated("attemptA", BIND,
                                       text_events(response_id="other"), 8)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_background_cursor_monotonic_and_durable(self):
        self.submitted(mode="BACKGROUND_POLL")
        self.turn.observe_simulated("attemptA", BIND, text_events())
        r = self.turn.checkpoint_simulated_cursor(
            "attemptA", BIND, text_events()[:5])
        self.assert_inert(r, state="SUBMISSION_UNCONFIRMED")
        self.assertEqual(r["cursor"], 5)
        self.reopen()
        with self.assertRaisesRegex(Refused, "CURSOR_UNBOUND_OR_REPLAY"):
            self.turn.checkpoint_simulated_cursor(
                "attemptA", BIND, text_events()[:5])
        self.assertEqual(self.turn.checkpoint_simulated_cursor(
            "attemptA", BIND, text_events()[:6])["cursor"], 6)

    def test_foreground_mode_cannot_checkpoint_cursor(self):
        self.submitted()
        self.turn.observe_simulated("attemptA", BIND, text_events())
        with self.assertRaisesRegex(Refused, "CURSOR_MODE_OR_ID"):
            self.turn.checkpoint_simulated_cursor(
                "attemptA", BIND, text_events()[:5])

    def test_background_cursor_response_binding_required(self):
        self.submitted(mode="BACKGROUND_POLL")
        self.turn.observe_simulated("attemptA", BIND, text_events())
        with self.assertRaisesRegex(Refused, "CURSOR_RESPONSE_DRIFT"):
            self.turn.checkpoint_simulated_cursor(
                "attemptA", BIND, text_events(response_id="other")[:5])
        self.assertEqual(self.turn.snapshot("attemptA")["cursor"], -1)

    def test_unverified_cursor_prefix_refused(self):
        self.submitted(mode="BACKGROUND_POLL")
        self.turn.observe_simulated("attemptA", BIND, text_events())
        partial = text_events()[:5]
        partial[4]["content_index"] = 12
        with self.assertRaisesRegex(Refused, "CURSOR_UNVALIDATED"):
            self.turn.checkpoint_simulated_cursor("attemptA", BIND, partial)

    def test_cursor_restart_does_not_promote_remote_truth(self):
        self.submitted(mode="BACKGROUND_POLL")
        self.turn.observe_simulated("attemptA", BIND, text_events())
        self.turn.checkpoint_simulated_cursor(
            "attemptA", BIND, text_events()[:5])
        self.reopen()
        r = self.assert_inert(self.turn.snapshot("attemptA"),
                              state="SUBMISSION_UNCONFIRMED")
        self.assertEqual(r["cursor"], 5)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_cross_turn_replayed_response_id_refused(self):
        self.submitted()
        self.turn.observe_simulated("attemptA", BIND, text_events())
        bindingB = dict(BIND, turnId="turnB")
        self.reserve(attempt="attemptB", client="clientB", binding=bindingB,
                     units=20)
        self.turn.submit_simulated("attemptB", bindingB)
        with self.assertRaisesRegex(Refused, "RESPONSE_REPLAY_OTHER_TURN"):
            self.turn.observe_simulated("attemptB", bindingB, text_events())
        self.assertEqual(self.budget()["reserved_units"], 50)

    def test_refused_stream_not_settled_and_holds_budget(self):
        self.submitted()
        events = text_events()
        events[5]["text"] = "tampered"
        result = self.turn.settle_simulated("attemptA", BIND, events, 1)
        self.assert_inert(result, state="REMOTE_OUTCOME_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.assertEqual(self.budget()["used_units"], 0)

    def test_settlement_over_reserved_budget_rolls_back(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "UNTRUSTED_SETTLEMENT"):
            self.turn.settle_simulated("attemptA", BIND, text_events(), 100)
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.assertEqual(self.budget()["used_units"], 0)

    def test_no_auto_replay_even_if_lost_before_response_identity(self):
        self.submitted()
        self.turn.interrupt_simulated("attemptA")
        self.reopen()
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.turn.submit_simulated("attemptA", BIND)
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE_OR_REVOKED"):
            self.turn.observe_simulated("attemptA", BIND, text_events())

    def test_budget_concurrency_survives_reopen(self):
        self.submitted()
        self.reserve(attempt="attemptB", client="clientB",
                     binding=dict(BIND, turnId="turnB"), units=25)
        self.reopen()
        with self.assertRaisesRegex(Refused, "CONCURRENCY_LIMIT"):
            self.reserve(attempt="attemptC", client="clientC",
                         binding=dict(BIND, turnId="turnC"), units=10)
        self.assertEqual(self.budget()["reserved_units"], 55)

    def test_immutable_attempt_binding_rejects_second_client_identity(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "TURN_ALREADY_BOUND"):
            self.reserve(attempt="attemptA", client="newClient")

    def test_failed_stream_after_response_created_still_uncertain(self):
        self.submitted()
        events = text_events()[:2]
        events.append({
            "type": "response.failed", "sequence_number": 3,
            "response": {"id": "respA", "status": "failed"}
        })
        r = self.assert_inert(self.turn.observe_simulated("attemptA", BIND, events),
                              state="REMOTE_OUTCOME_UNKNOWN")
        self.assertEqual(r["reservedUnits"], 30)

    def test_source_never_imports_network_or_provider_sdk(self):
        import inspect
        import px_s3_b30_integrated_fixture as module
        source = inspect.getsource(module)
        for bad in ("import requests", "import httpx", "from openai",
                    "subprocess.Popen", "OPENAI_API_KEY", "requests.post"):
            self.assertNotIn(bad, source)

    def test_no_network_or_process_creation_in_bridge(self):
        self.submitted()
        with patch("socket.socket", side_effect=AssertionError("network")):
            with patch("subprocess.Popen", side_effect=AssertionError("process")):
                r = self.turn.observe_simulated("attemptA", BIND, text_events())
        self.assert_inert(r, state="SUBMISSION_UNCONFIRMED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
