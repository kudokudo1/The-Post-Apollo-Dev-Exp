#!/usr/bin/env python3
"""B33 event continuity: disposable SQLite, exact pinned B30/B31/B32."""
import copy
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b33_durable_observation import DurableObservedFixture
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b29_transport_ledger import Refused

BIND = {"room": "roomA", "patient": "patientA", "assignment": "assignmentA",
        "bed": "bedA", "turnId": "turnA", "generation": 1}


def text_events(text="original answer", response_id="respA"):
    start = {"id": "msgA", "type": "message", "role": "assistant",
             "status": "in_progress", "content": []}
    end = {"id": "msgA", "type": "message", "role": "assistant",
           "status": "completed", "content": [
               {"type": "output_text", "text": text, "annotations": []}]}
    return [
        {"type": "response.created", "sequence_number": 1,
         "response": {"id": response_id, "status": "in_progress"}},
        {"type": "response.output_item.added", "sequence_number": 2,
         "output_index": 0, "item": start},
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
         "output_index": 0, "item": copy.deepcopy(end)},
        {"type": "response.completed", "sequence_number": 8,
         "response": {"id": response_id, "status": "completed",
                      "output": [copy.deepcopy(end)]}},
    ]


def function_events(response_id="respA"):
    arguments = '{"record_id":"fixture.A"}'
    start = {"id": "fcA", "type": "function_call", "name": "px_fixture_read",
             "call_id": "callA", "status": "in_progress", "arguments": ""}
    done = dict(start, status="completed", arguments=arguments)
    return [
        {"type": "response.created", "sequence_number": 1,
         "response": {"id": response_id, "status": "in_progress"}},
        {"type": "response.output_item.added", "sequence_number": 2,
         "output_index": 0, "item": start},
        {"type": "response.function_call_arguments.delta", "sequence_number": 3,
         "output_index": 0, "item_id": "fcA", "delta": arguments},
        {"type": "response.function_call_arguments.done", "sequence_number": 4,
         "output_index": 0, "item_id": "fcA", "arguments": arguments},
        {"type": "response.output_item.done", "sequence_number": 5,
         "output_index": 0, "item": copy.deepcopy(done)},
        {"type": "response.completed", "sequence_number": 6,
         "response": {"id": response_id, "status": "completed",
                      "output": [copy.deepcopy(done)]}},
    ]


class B33DurableContinuityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="b33-offline-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "test.sqlite3"
        self.conn = sqlite3.connect(self.path, isolation_level=None, timeout=2)
        self.addCleanup(self.conn.close)
        self.issuer = TestOnlyEvidenceIssuer()
        self.turn = DurableObservedFixture(self.conn, self.issuer)
        self.turn.configure_mock_budget("scopeA", 100)

    def reserve(self, *, binding=BIND, attempt="attemptA",
                client="clientA", units=30):
        return self.turn.reserve(attempt_id=attempt, client_request_id=client,
                                 scope="scopeA", binding=binding, units=units)

    def started(self):
        self.reserve()
        self.turn.submit_mock("attemptA", BIND)

    def observed(self, events=None):
        return self.turn.observe_mock("attemptA", BIND,
                                     text_events() if events is None else events)

    def witness(self, events=None, **replacements):
        if events is None:
            events = text_events()
        args = {"attempt_id": "attemptA", "client_request_id": "clientA",
                "binding": BIND, "response_id": "respA",
                "events": events, "usage_units": 11, "status": "completed"}
        args.update(replacements)
        return self.issuer.issue_test_only(**args)

    def settle(self, token, events=None, binding=BIND):
        return self.turn.settle_mock("attemptA", binding,
                                    text_events() if events is None else events,
                                    token)

    def reopen(self, *, new_issuer=True):
        self.conn.close()
        self.conn = sqlite3.connect(self.path, isolation_level=None, timeout=2)
        self.addCleanup(self.conn.close)
        if new_issuer:
            self.issuer = TestOnlyEvidenceIssuer()
        self.turn = DurableObservedFixture(self.conn, self.issuer)

    def budget(self):
        return self.turn.ledger.budget("scopeA")

    def safe(self, result):
        for key in ("launchAuthorized", "toolDispatchAuthorized",
                    "realStopVerified", "realSpendVerified",
                    "retryAuthorized", "productionReady"):
            self.assertIs(result[key], False, key)
        self.assertIs(result["realProviderObserved"], False)
        return result

    def test_fresh_fixture_has_no_digest_before_observation(self):
        self.started()
        state = self.safe(self.turn.snapshot("attemptA"))
        self.assertFalse(state["durableEventDigestBound"])
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_observation_atomically_pins_response_and_digest(self):
        self.started()
        state = self.safe(self.observed())
        self.assertTrue(state["durableEventDigestBound"])
        self.assertEqual(state["responseId"], "respA")
        self.assertEqual(state["state"], "SUBMISSION_UNCONFIRMED")
        self.assertEqual(self.budget()["used_units"], 0)

    def test_digest_persists_across_sqlite_reopen(self):
        self.started()
        self.observed()
        first = self.conn.execute(
            "SELECT b33_observed_digest FROM b29_fixture_attempts"
        ).fetchone()[0]
        self.assertEqual(len(first), 64)
        self.reopen()
        second = self.conn.execute(
            "SELECT b33_observed_digest FROM b29_fixture_attempts"
        ).fetchone()[0]
        self.assertEqual(first, second)
        self.assertTrue(self.turn.snapshot("attemptA")["durableEventDigestBound"])

    def test_same_response_different_text_new_witness_rejected(self):
        self.started()
        self.observed()
        altered = text_events("different valid answer", "respA")
        token = self.witness(altered)
        with self.assertRaisesRegex(Refused, "OBSERVED_BATCH_MISMATCH"):
            self.settle(token, altered)
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.assertEqual(self.budget()["used_units"], 0)

    def test_same_response_different_text_after_reopen_rejected(self):
        self.started()
        self.observed()
        self.reopen()
        altered = text_events("different answer after restart")
        with self.assertRaisesRegex(Refused, "OBSERVED_BATCH_MISMATCH"):
            self.settle(self.witness(altered), altered)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_identical_batch_mock_settles_after_restart(self):
        self.started()
        self.observed()
        self.reopen()
        result = self.safe(self.settle(self.witness()))
        self.assertEqual(result["state"], "MOCK_COMPLETED")
        self.assertEqual(result["validatedFixtureOutput"], "COMPLETED_TEXT")
        self.assertEqual(self.budget()["reserved_units"], 0)
        self.assertEqual(self.budget()["used_units"], 11)

    def test_settle_requires_original_observation(self):
        self.started()
        with self.assertRaisesRegex(Refused, "OBSERVATION_REQUIRED"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["used_units"], 0)

    def test_legacy_b30_observation_with_no_digest_refused(self):
        self.started()
        self.turn._joint.observe_simulated("attemptA", BIND, text_events())
        self.assertFalse(self.turn.snapshot("attemptA")["durableEventDigestBound"])
        with self.assertRaisesRegex(Refused, "OBSERVATION_REQUIRED"):
            self.settle(self.witness())
        with self.assertRaisesRegex(Refused, "LEGACY_OBSERVATION_UNBOUND"):
            self.observed()
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_duplicate_identical_observation_is_idempotent(self):
        self.started()
        self.observed()
        result = self.observed()
        self.assertEqual(result["reason"], "ALREADY_BOUND_IDENTICALLY")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_duplicate_observation_changed_content_refused(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "OBSERVATION_DRIFT"):
            self.observed(text_events("new content"))
        self.assertEqual(self.budget()["used_units"], 0)

    def test_duplicate_observation_changed_response_id_refused(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "OBSERVATION_DRIFT"):
            self.observed(text_events(response_id="respB"))

    def test_database_trigger_prevents_direct_digest_change(self):
        self.started()
        self.observed()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE b29_fixture_attempts SET b33_observed_digest=?",
                ("a" * 64,)
            )
        self.assertTrue(self.turn.snapshot("attemptA")["durableEventDigestBound"])

    def test_database_trigger_prevents_digest_clear(self):
        self.started()
        self.observed()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE b29_fixture_attempts SET b33_observed_digest=NULL"
            )

    def test_database_trigger_prevents_response_id_rewrite(self):
        self.started()
        self.observed()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE b29_fixture_attempts SET response_id='respB'"
            )
        self.assertEqual(self.turn.snapshot("attemptA")["responseId"], "respA")

    def test_invalid_stream_holds_budget_without_digest(self):
        self.started()
        bad = text_events()[:-1]
        with self.assertRaisesRegex(Refused, "STREAM_UNCERTAIN"):
            self.observed(bad)
        self.assertFalse(self.turn.snapshot("attemptA")["durableEventDigestBound"])
        self.assertEqual(self.turn.snapshot("attemptA")["state"],
                         "REMOTE_OUTCOME_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_changed_bed_at_observation_revokes(self):
        self.started()
        with self.assertRaisesRegex(Refused, "AUTHORITY_CHANGED"):
            self.turn.observe_mock("attemptA", dict(BIND, bed="foreign"),
                                   text_events())
        self.assertEqual(self.turn.snapshot("attemptA")["state"],
                         "REVOKED_REMOTE_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_changed_generation_at_settlement_revokes(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "AUTHORITY_CHANGED"):
            self.settle(self.witness(),
                        binding=dict(BIND, generation=2))
        self.reopen()
        self.assertEqual(self.turn.snapshot("attemptA")["state"],
                         "REVOKED_REMOTE_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_changed_patient_at_settlement_revokes(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "AUTHORITY_CHANGED"):
            self.settle(self.witness(), binding=dict(BIND, patient="other"))
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_changed_assignment_at_settlement_revokes(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "AUTHORITY_CHANGED"):
            self.settle(self.witness(),
                        binding=dict(BIND, assignment="other"))
        self.assertEqual(self.budget()["used_units"], 0)

    def test_cancel_after_observation_fences_settlement(self):
        self.started()
        self.observed()
        self.turn.cancel_mock("attemptA")
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_connection_loss_after_observation_holds_budget(self):
        self.started()
        self.observed()
        self.turn.interrupt_mock("attemptA")
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_settlement_after_crash_no_double_spending(self):
        self.started()
        self.observed()
        self.settle(self.witness())
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["used_units"], 11)

    def test_failed_mock_usage_rollback_keeps_digest_and_hold(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "MOCK_USAGE_EXCEEDS_HOLD"):
            self.settle(self.witness(usage_units=31))
        self.assertTrue(self.turn.snapshot("attemptA")["durableEventDigestBound"])
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.assertEqual(self.budget()["used_units"], 0)

    def test_model_usage_claim_does_not_settle(self):
        self.started()
        evt = text_events()
        evt[-1]["response"]["usage"] = {"cost_units": 99999}
        self.observed(evt)
        self.settle(self.witness(evt, usage_units=7), evt)
        self.assertEqual(self.budget()["used_units"], 7)

    def test_foreign_attempt_witness_refused(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "MOCK_EVIDENCE_MISMATCH"):
            self.settle(self.witness(attempt_id="foreign"))
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_foreign_client_witness_refused(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "MOCK_EVIDENCE_MISMATCH"):
            self.settle(self.witness(client_request_id="foreign"))

    def test_witness_status_cancelled_never_settles(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "MOCK_EVIDENCE_MISMATCH"):
            self.settle(self.witness(status="cancelled"))
        self.assertEqual(self.budget()["used_units"], 0)

    def test_fake_dict_as_evidence_refused(self):
        self.started()
        self.observed()
        with self.assertRaisesRegex(Refused, "UNTRUSTED_EVIDENCE"):
            self.settle({"verified": True, "digest": "fake"})

    def test_old_witness_after_new_issuer_refused(self):
        self.started()
        self.observed()
        old = self.witness()
        self.reopen()
        with self.assertRaisesRegex(Refused, "UNTRUSTED_OR_REPLAYED"):
            self.settle(old)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_function_proposal_is_not_tool_authority(self):
        self.started()
        events = function_events()
        result = self.safe(self.observed(events))
        self.assertTrue(result["durableEventDigestBound"])
        token = self.witness(events)
        final = self.safe(self.settle(token, events))
        self.assertEqual(final["validatedFixtureOutput"],
                         "UNTRUSTED_FUNCTION_PROPOSAL")
        self.assertEqual(final["state"], "MOCK_COMPLETED")

    def test_cross_turn_replayed_response_id_refused(self):
        self.started()
        self.observed()
        other = dict(BIND, turnId="turnB")
        self.reserve(binding=other, attempt="attemptB", client="clientB",
                     units=20)
        self.turn.submit_mock("attemptB", other)
        with self.assertRaisesRegex(Refused, "RESPONSE_ID_REPLAY"):
            self.turn.observe_mock("attemptB", other, text_events())
        self.assertEqual(self.budget()["reserved_units"], 50)

    def test_second_connection_sees_digest(self):
        self.started()
        self.observed()
        with sqlite3.connect(self.path, isolation_level=None) as other:
            duplicate = DurableObservedFixture(other, TestOnlyEvidenceIssuer())
            self.assertTrue(
                duplicate.snapshot("attemptA")["durableEventDigestBound"]
            )

    def test_independent_connection_cannot_double_settle(self):
        self.started()
        self.observed()
        with sqlite3.connect(self.path, isolation_level=None) as other:
            second_issuer = TestOnlyEvidenceIssuer()
            second = DurableObservedFixture(other, second_issuer)
            second_token = second_issuer.issue_test_only(
                attempt_id="attemptA", client_request_id="clientA",
                binding=BIND, response_id="respA",
                events=text_events(), usage_units=3
            )
            self.settle(self.witness())
            with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
                second.settle_mock("attemptA", BIND, text_events(), second_token)
            self.assertEqual(second.ledger.budget("scopeA")["used_units"], 11)

    def test_explicit_mock_budget_not_real_spend(self):
        self.started()
        self.observed()
        settled = self.safe(self.settle(self.witness()))
        self.assertFalse(settled["realProviderObserved"])
        self.assertFalse(settled["realSpendVerified"])
        self.assertFalse(settled["productionReady"])

    def test_no_network_or_tool_execution(self):
        self.started()
        with patch("socket.socket", side_effect=AssertionError("network")):
            with patch("subprocess.Popen", side_effect=AssertionError("process")):
                with patch("subprocess.run", side_effect=AssertionError("run")):
                    self.observed()
                    self.safe(self.settle(self.witness()))

    def test_b29_initialization_remains_compatible(self):
        self.started()
        self.observed()
        from px_s3_b29_transport_ledger import SyntheticLedger
        with sqlite3.connect(self.path, isolation_level=None) as conn:
            second = SyntheticLedger(conn)
            second.initialize()
            self.assertEqual(second.state("attemptA")["responseId"], "respA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
