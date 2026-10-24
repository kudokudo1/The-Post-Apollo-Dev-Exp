#!/usr/bin/env python3
"""B32 staged B30+B31 joint crash/restart and evidence-denial regressions."""
import copy
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b32_staged_evidence import StagedOfflineEvidenceTurn
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b29_transport_ledger import Refused

BIND = {"room": "roomA", "patient": "patientA", "assignment": "assignmentA",
        "bed": "bedA", "turnId": "turnA", "generation": 1}


def text_events(text="fixture text", response_id="respA"):
    message = {"id": "msgA", "type": "message", "role": "assistant",
               "status": "in_progress", "content": []}
    final = {"id": "msgA", "type": "message", "role": "assistant",
             "status": "completed", "content": [
                 {"type": "output_text", "text": text, "annotations": []}]}
    return [
        {"type": "response.created", "sequence_number": 1,
         "response": {"id": response_id, "status": "in_progress"}},
        {"type": "response.output_item.added", "sequence_number": 2,
         "output_index": 0, "item": message},
        {"type": "response.content_part.added", "sequence_number": 3,
         "output_index": 0, "content_index": 0, "item_id": "msgA",
         "part": {"type": "output_text", "text": "", "annotations": []}},
        {"type": "response.output_text.delta", "sequence_number": 4,
         "output_index": 0, "content_index": 0, "item_id": "msgA",
         "delta": text},
        {"type": "response.output_text.done", "sequence_number": 5,
         "output_index": 0, "content_index": 0, "item_id": "msgA",
         "text": text},
        {"type": "response.content_part.done", "sequence_number": 6,
         "output_index": 0, "content_index": 0, "item_id": "msgA",
         "part": {"type": "output_text", "text": text, "annotations": []}},
        {"type": "response.output_item.done", "sequence_number": 7,
         "output_index": 0, "item": copy.deepcopy(final)},
        {"type": "response.completed", "sequence_number": 8,
         "response": {"id": response_id, "status": "completed",
                      "output": [copy.deepcopy(final)]}},
    ]


def call_events(response_id="respA", raw='{"record_id":"fixture.A"}'):
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


class B32StagedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="b32-disposable-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "ledger.sqlite"
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.conn.close)
        self.issuer = TestOnlyEvidenceIssuer()
        self.turn = StagedOfflineEvidenceTurn(self.conn, self.issuer)
        self.turn.configure_mock_budget("scopeA", 100)

    def reserve(self, *, binding=BIND, attempt="attemptA", client="clientA",
                units=30, mode="FOREGROUND_STREAM"):
        return self.turn.reserve(
            attempt_id=attempt, client_request_id=client,
            scope="scopeA", binding=binding, units=units, mode=mode
        )

    def started(self, **kw):
        self.reserve(**kw)
        return self.turn.begin_simulated("attemptA", BIND)

    def observed(self, events=None, **kw):
        return self.turn.observe_simulated(
            "attemptA", BIND, text_events() if events is None else events)

    def witness(self, events=None, **kw):
        if events is None:
            events = text_events()
        arg = dict(attempt_id="attemptA", client_request_id="clientA",
                   binding=BIND, response_id="respA", events=events,
                   usage_units=10, status="completed")
        arg.update(kw)
        return self.issuer.issue_test_only(**arg)

    def settle(self, token, events=None, binding=BIND):
        return self.turn.settle_with_independent_mock_evidence(
            "attemptA", binding, text_events() if events is None else events,
            token)

    def reopen(self, *, new_issuer=True):
        self.conn.close()
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.conn.close)
        if new_issuer:
            self.issuer = TestOnlyEvidenceIssuer()
        self.turn = StagedOfflineEvidenceTurn(self.conn, self.issuer)

    def budget(self):
        return self.turn.ledger.budget("scopeA")

    def safe(self, result, state=None):
        if state is not None:
            self.assertEqual(result["state"], state)
        for k in ("launchAuthorized", "toolDispatchAuthorized",
                  "realStopVerified", "realSpendVerified",
                  "retryAuthorized", "productionReady"):
            self.assertIs(result[k], False, k)
        return result

    def test_reservation_persists_across_restart(self):
        self.reserve()
        self.reopen()
        r = self.safe(self.turn.snapshot("attemptA"), "RESERVED")
        self.assertIs(r["witnessPersisted"], False)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_submit_after_restart_only_once(self):
        self.reserve()
        self.reopen()
        self.turn.begin_simulated("attemptA", BIND)
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.turn.begin_simulated("attemptA", BIND)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_unobserved_turn_cannot_settle_even_with_mock_issuer(self):
        self.started()
        with self.assertRaisesRegex(Refused, "B30_OBSERVATION_REQUIRED"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["used_units"], 0)

    def test_mock_observation_does_not_settle_budget(self):
        self.started()
        r = self.safe(self.observed(), "SUBMISSION_UNCONFIRMED")
        self.assertEqual(r["responseId"], "respA")
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.assertEqual(self.budget()["used_units"], 0)

    def test_independent_mock_evidence_settles_after_observation(self):
        self.started()
        self.observed()
        r = self.safe(self.settle(self.witness()), "MOCK_COMPLETED")
        self.assertEqual(r["validatedFixtureOutput"], "COMPLETED_TEXT")
        self.assertEqual(self.budget()["used_units"], 10)
        self.assertEqual(self.budget()["reserved_units"], 0)

    def test_observe_restart_new_witness_then_mock_settle(self):
        self.started()
        self.observed()
        self.reopen()
        self.assertEqual(self.turn.snapshot("attemptA")["responseId"], "respA")
        self.safe(self.settle(self.witness()), "MOCK_COMPLETED")
        self.assertEqual(self.budget()["used_units"], 10)

    def test_old_witness_does_not_survive_new_issuer(self):
        self.started()
        self.observed()
        stale = self.witness()
        self.reopen()
        with self.assertRaisesRegex(Refused, "UNTRUSTED_OR_REPLAYED"):
            self.settle(stale)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_old_issuer_object_is_not_durable_provenance(self):
        self.started()
        self.observed()
        original = self.issuer
        self.reopen(new_issuer=True)
        self.assertIsNot(self.issuer, original)
        self.assertFalse(self.turn.snapshot("attemptA")["witnessPersisted"])
        self.assertEqual(self.budget()["used_units"], 0)

    def test_crash_after_observation_before_settlement_hold(self):
        self.started()
        self.observed()
        self.reopen()
        self.safe(self.turn.snapshot("attemptA"), "SUBMISSION_UNCONFIRMED")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_crash_after_mock_settlement_no_double_charge(self):
        self.started()
        self.observed()
        self.settle(self.witness())
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["used_units"], 10)

    def test_observer_witness_replay_refused(self):
        self.started()
        self.observed()
        token = self.witness(response_id="other")
        with self.assertRaisesRegex(Refused, "EVIDENCE_RESPONSE_MISMATCH"):
            self.settle(token)
        with self.assertRaisesRegex(Refused, "UNTRUSTED_OR_REPLAYED"):
            self.settle(token)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_forged_dict_claiming_authenticated_rejected(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "UNTRUSTED_EVIDENCE"):
            self.settle({"verified": True, "usage_units": 0})
        self.assertEqual(self.budget()["used_units"], 0)

    def test_foreign_issuer_witness_rejected(self):
        self.started()
        self.observed()
        other = TestOnlyEvidenceIssuer()
        token = other.issue_test_only(
            attempt_id="attemptA", client_request_id="clientA",
            binding=BIND, response_id="respA", events=text_events(),
            usage_units=1)
        with self.assertRaisesRegex(Refused, "UNTRUSTED_OR_REPLAYED"):
            self.settle(token)

    def test_model_usage_claim_is_not_settlement_evidence(self):
        self.started()
        evt = text_events()
        evt[-1]["response"]["usage"] = {"cost_units": 99999}
        self.observed(evt)
        token = self.witness(evt, usage_units=7)
        self.safe(self.settle(token, evt), "MOCK_COMPLETED")
        self.assertEqual(self.budget()["used_units"], 7)

    def test_issuer_status_cancelled_cannot_settle(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(self.witness(status="cancelled"))
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_mismatched_client_id_cannot_settle(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(self.witness(client_request_id="other"))

    def test_foreign_attempt_in_witness_cannot_settle(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(self.witness(attempt_id="other"))

    def test_stream_change_after_observation_refused(self):
        self.started()
        self.observed()
        evt = text_events("tampered")
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(self.witness(), evt)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_stream_end_response_id_drift_refused(self):
        self.started()
        self.observed()
        evt = text_events(response_id="different")
        token = self.witness(evt, response_id="different")
        with self.assertRaisesRegex(Refused, "RESPONSE_ID_DRIFT"):
            self.settle(token, evt)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_invalid_stream_never_creates_observed_response(self):
        self.started()
        evt = text_events()
        evt[1]["item"]["type"] = "shell_call"
        self.safe(self.observed(evt), "REMOTE_OUTCOME_UNKNOWN")
        self.assertIsNone(self.turn.snapshot("attemptA")["responseId"])
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_partial_stream_holds_budget_through_restart(self):
        self.started()
        self.safe(self.observed(text_events()[:-1]), "REMOTE_OUTCOME_UNKNOWN")
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_connection_loss_before_observation_prevents_settlement(self):
        self.started()
        self.turn.interrupted_simulated("attemptA")
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.turn.begin_simulated("attemptA", BIND)

    def test_cancel_after_observation_blocks_later_evidence(self):
        self.started()
        self.observed()
        self.turn.cancel_simulated("attemptA")
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_cancel_before_submission_releases_unused_hold(self):
        self.reserve()
        self.safe(self.turn.cancel_simulated("attemptA"), "ABORTED_PRE_SUBMISSION")
        self.reopen()
        self.assertEqual(self.budget()["reserved_units"], 0)
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.turn.begin_simulated("attemptA", BIND)

    def test_background_mock_cancel_receipt_never_remote_proof(self):
        self.started(mode="BACKGROUND_POLL")
        self.observed()
        self.turn.cancel_simulated("attemptA")
        self.reopen()
        r = self.safe(self.turn.mock_background_cancel(
            "attemptA", "respA", "cancelled"), "MOCK_CANCELLED_UNVERIFIED")
        self.assertIs(r["realStopVerified"], False)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_background_cursor_before_crash_not_usage_or_evidence(self):
        self.started(mode="BACKGROUND_POLL")
        self.observed()
        self.safe(self.turn.checkpoint_simulated_cursor(
            "attemptA", BIND, text_events()[:4]))
        self.reopen()
        snap = self.turn.snapshot("attemptA")
        self.assertEqual(snap["cursor"], 4)
        self.assertIs(snap["witnessPersisted"], False)
        self.assertEqual(self.budget()["used_units"], 0)

    def test_changed_bed_revokes_and_never_restores(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness(), binding=dict(BIND, bed="foreign"))
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness(), binding=BIND)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_changed_generation_revokes_while_budget_held(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness(), binding=dict(BIND, generation=2))
        self.reopen()
        self.assertEqual(self.turn.snapshot("attemptA")["state"],
                         "REVOKED_REMOTE_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_patient_change_before_observation_revokes(self):
        self.started()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE_OR_REVOKED"):
            self.turn.observe_simulated(
                "attemptA", dict(BIND, patient="other"), text_events())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_function_proposal_has_no_tool_authority(self):
        self.started()
        events = call_events()
        r = self.safe(self.observed(events), "SUBMISSION_UNCONFIRMED")
        self.assertEqual(r["untrustedProposalCount"], 1)
        token = self.witness(events)
        result = self.safe(self.settle(token, events), "MOCK_COMPLETED")
        self.assertEqual(result["validatedFixtureOutput"],
                         "UNTRUSTED_FUNCTION_PROPOSAL")
        self.assertIs(result["toolDispatchAuthorized"], False)

    def test_unsupported_native_tool_output_never_settles(self):
        self.started()
        events = text_events()
        events[1]["item"]["type"] = "mcp_call"
        self.safe(self.observed(events), "REMOTE_OUTCOME_UNKNOWN")
        self.assertEqual(self.budget()["used_units"], 0)

    def test_mock_usage_above_hold_cannot_settle(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "UNTRUSTED_SETTLEMENT"):
            self.settle(self.witness(usage_units=100))
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_duplicate_response_id_other_turn_refused_by_b29(self):
        self.started()
        self.observed()
        other_binding = dict(BIND, turnId="turnB")
        self.reserve(binding=other_binding, attempt="attemptB",
                     client="clientB", units=20)
        self.turn.begin_simulated("attemptB", other_binding)
        with self.assertRaisesRegex(Refused, "RESPONSE_REPLAY_OTHER_TURN"):
            self.turn.observe_simulated(
                "attemptB", other_binding, text_events())
        self.assertEqual(self.budget()["reserved_units"], 50)

    def test_second_database_connection_sees_same_persisted_state(self):
        self.started()
        self.observed()
        with sqlite3.connect(self.path, isolation_level=None) as other:
            second = StagedOfflineEvidenceTurn(other, TestOnlyEvidenceIssuer())
            snap = self.safe(second.snapshot("attemptA"),
                             "SUBMISSION_UNCONFIRMED")
            self.assertEqual(snap["responseId"], "respA")

    def test_no_real_network_process_or_sdk(self):
        self.started()
        with patch("socket.socket", side_effect=AssertionError("network")):
            with patch("subprocess.Popen", side_effect=AssertionError("process")):
                with patch("subprocess.run", side_effect=AssertionError("run")):
                    self.observed()
                    self.safe(self.settle(self.witness()), "MOCK_COMPLETED")

    def test_source_keeps_real_execution_disabled(self):
        import inspect
        import px_s3_b32_staged_evidence as module
        source = inspect.getsource(module)
        for bad in ("import requests", "from openai", "import httpx",
                    "OPENAI_API_KEY", "subprocess.Popen", "requests.post"):
            self.assertNotIn(bad, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
