#!/usr/bin/env python3
"""B31 negative evidence tests. Disposable SQLite, NO authenticated API."""
import copy
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b31_evidence_boundary import (
    OfflineEvidenceBoundary, TestOnlyEvidenceIssuer, _FixtureWitness,
)
from px_s3_b29_transport_ledger import Refused

BIND = {"room": "roomA", "patient": "patientA", "assignment": "assignmentA",
        "bed": "bedA", "turnId": "turnA", "generation": 1}


def text_events(text="mock answer", response_id="respA"):
    start = {"id": "msgA", "type": "message", "role": "assistant",
             "status": "in_progress", "content": []}
    done = {"id": "msgA", "type": "message", "role": "assistant",
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
         "output_index": 0, "item": copy.deepcopy(done)},
        {"type": "response.completed", "sequence_number": 8,
         "response": {"id": response_id, "status": "completed",
                      "output": [copy.deepcopy(done)]}},
    ]


def function_events(response_id="respA"):
    raw = '{"record_id":"fixture.A"}'
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


class B31EvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="b31-offline-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "synthetic.sqlite"
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.conn.close)
        self.issuer = TestOnlyEvidenceIssuer()
        self.gate = OfflineEvidenceBoundary(self.conn, self.issuer)
        self.gate.ledger.configure_mock_budget("scopeA", 100)

    def reserve(self, binding=BIND, attempt="attemptA", client="clientA",
                units=30):
        return self.gate.reserve(
            attempt_id=attempt, client_request_id=client, scope="scopeA",
            binding=binding, units=units)

    def submitted(self):
        self.reserve()
        self.gate.submit_mock("attemptA", BIND)

    def witness(self, events=None, **updates):
        events = text_events() if events is None else events
        args = dict(attempt_id="attemptA", client_request_id="clientA",
                    binding=BIND, response_id="respA", events=events,
                    usage_units=12, status="completed")
        args.update(updates)
        return self.issuer.issue_test_only(**args)

    def settle(self, evidence, events=None, *, binding=BIND):
        return self.gate.accept_and_mock_settle(
            attempt_id="attemptA", binding=binding,
            events=text_events() if events is None else events,
            evidence=evidence,
        )

    def safe(self, result):
        for key in ("realProviderObserved", "realSpendVerified",
                    "realStopVerified", "launchAuthorized",
                    "toolDispatchAuthorized", "retryAuthorized",
                    "productionReady"):
            self.assertIs(result[key], False, key)
        self.assertEqual(result["realProviderCalls"], 0)
        return result

    def budget(self):
        return self.gate.ledger.budget("scopeA")

    def reopen(self, *, new_issuer=False):
        self.conn.close()
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.conn.close)
        if new_issuer:
            self.issuer = TestOnlyEvidenceIssuer()
        self.gate = OfflineEvidenceBoundary(self.conn, self.issuer)

    def test_completed_text_separate_mock_evidence_settles(self):
        self.submitted()
        result = self.safe(self.settle(self.witness()))
        self.assertEqual(result["state"], "MOCK_COMPLETED")
        self.assertEqual(result["validatedFixtureOutput"], "COMPLETED_TEXT")
        self.assertEqual(self.budget()["reserved_units"], 0)
        self.assertEqual(self.budget()["used_units"], 12)

    def test_function_proposal_never_dispatches(self):
        self.submitted()
        events = function_events()
        result = self.safe(self.settle(self.witness(events), events))
        self.assertEqual(result["validatedFixtureOutput"],
                         "UNTRUSTED_FUNCTION_PROPOSAL")
        self.assertEqual(self.budget()["used_units"], 12)

    def test_reservation_without_submission_cannot_settle(self):
        self.reserve()
        with self.assertRaisesRegex(Refused, "TURN_NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_dict_claiming_authentication_rejected(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "UNTRUSTED_EVIDENCE"):
            self.settle({"authenticated": True, "usage_units": 1})
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_unregistered_witness_rejected(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "UNTRUSTED_OR_REPLAYED"):
            self.settle(_FixtureWitness())
        self.assertEqual(self.budget()["used_units"], 0)

    def test_foreign_issuer_token_cannot_cross_gate(self):
        self.submitted()
        other = TestOnlyEvidenceIssuer()
        foreign = other.issue_test_only(
            attempt_id="attemptA", client_request_id="clientA",
            binding=BIND, response_id="respA", events=text_events(),
            usage_units=1)
        with self.assertRaisesRegex(Refused, "UNTRUSTED_OR_REPLAYED"):
            self.settle(foreign)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_evidence_single_use_even_after_success(self):
        self.submitted()
        evidence = self.witness()
        self.settle(evidence)
        with self.assertRaisesRegex(Refused, "TURN_NOT_ACTIVE"):
            self.settle(evidence)
        self.assertEqual(self.budget()["used_units"], 12)

    def test_evidence_single_use_after_rejected_mismatch(self):
        self.submitted()
        evidence = self.witness(client_request_id="foreign")
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(evidence)
        with self.assertRaisesRegex(Refused, "UNTRUSTED_OR_REPLAYED"):
            self.settle(evidence)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_cross_turn_attempt_id_refused(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(self.witness(attempt_id="otherAttempt"))

    def test_client_request_id_mismatch_refused(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(self.witness(client_request_id="otherClient"))

    def test_binding_digest_foreign_bed_refused(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(self.witness(binding=dict(BIND, bed="foreign")))

    def test_response_id_mismatch_refused(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "EVIDENCE_RESPONSE_MISMATCH"):
            self.settle(self.witness(response_id="respB"))

    def test_altered_events_after_observation_refused(self):
        self.submitted()
        evidence = self.witness()
        changed = text_events()
        changed[3]["delta"] = "poison"
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(evidence, changed)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_unexpected_stream_after_witness_refused(self):
        self.submitted()
        evt = text_events()
        evt[1]["item"]["type"] = "shell_call"
        witness = self.witness(evt)
        with self.assertRaisesRegex(Refused, "STREAM_INVALID"):
            self.settle(witness, evt)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_incomplete_stream_not_settled(self):
        self.submitted()
        evt = text_events()[:-1]
        witness = self.witness(evt)
        with self.assertRaisesRegex(Refused, "STREAM_UNFINISHED"):
            self.settle(witness, evt)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_wrong_terminal_status_not_settled(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(self.witness(status="failed"))
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_mock_cancel_receipt_cannot_claim_completion(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(self.witness(status="cancelled"))
        self.assertEqual(self.budget()["used_units"], 0)

    def test_cancelling_mock_not_completion(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "EVIDENCE_SCOPE"):
            self.settle(self.witness(status="cancelling"))

    def test_cancel_after_submission_fences_settlement(self):
        self.submitted()
        self.safe(self.gate.cancel_mock("attemptA"))
        with self.assertRaisesRegex(Refused, "TURN_NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_interrupted_delivery_fences_settlement_after_reopen(self):
        self.submitted()
        self.safe(self.gate.interrupt_mock("attemptA"))
        self.reopen()
        with self.assertRaisesRegex(Refused, "TURN_NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_authority_bed_drift_revokes_permanently(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "TURN_NOT_ACTIVE"):
            self.settle(self.witness(), binding=dict(BIND, bed="other"))
        self.reopen()
        self.assertEqual(self.gate.ledger.state("attemptA")["state"],
                         "REVOKED_REMOTE_UNKNOWN")
        with self.assertRaisesRegex(Refused, "TURN_NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_authority_generation_drift_fences(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "TURN_NOT_ACTIVE"):
            self.settle(self.witness(), binding=dict(BIND, generation=2))
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_authority_patient_drift_fences(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "TURN_NOT_ACTIVE"):
            self.settle(self.witness(), binding=dict(BIND, patient="other"))

    def test_budget_overspend_rolls_back(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "UNTRUSTED_SETTLEMENT"):
            self.settle(self.witness(usage_units=31))
        self.assertEqual(self.budget()["reserved_units"], 30)
        self.assertEqual(self.budget()["used_units"], 0)

    def test_spoofed_model_usage_is_ignored(self):
        self.submitted()
        evt = text_events()
        evt[-1]["response"]["usage"] = {
            "total_tokens": 999999999, "cost_units": 99}
        token = self.witness(evt, usage_units=7)
        result = self.safe(self.settle(token, evt))
        self.assertEqual(result["state"], "MOCK_COMPLETED")
        self.assertEqual(self.budget()["used_units"], 7)

    def test_boolean_mock_usage_refused_by_issuer(self):
        with self.assertRaisesRegex(Refused, "OBSERVER_USAGE"):
            self.witness(usage_units=True)

    def test_negative_mock_usage_refused(self):
        with self.assertRaisesRegex(Refused, "OBSERVER_USAGE"):
            self.witness(usage_units=-1)

    def test_unexpected_binding_extra_secret_refused(self):
        with self.assertRaisesRegex(Refused, "BINDING_SCHEMA"):
            self.witness(binding=dict(BIND, api_key="FAKE_SECRET"))

    def test_duplicate_response_id_other_turn_fails(self):
        self.submitted()
        self.settle(self.witness())
        b = dict(BIND, turnId="turnB")
        self.reserve(binding=b, attempt="attemptB", client="clientB")
        self.gate.submit_mock("attemptB", b)
        token = self.issuer.issue_test_only(
            attempt_id="attemptB", client_request_id="clientB",
            binding=b, response_id="respA", events=text_events(),
            usage_units=3)
        with self.assertRaisesRegex(Refused, "RESPONSE_REPLAY_OTHER_TURN"):
            self.gate.accept_and_mock_settle(
                attempt_id="attemptB", binding=b,
                events=text_events(), evidence=token)

    def test_successful_mock_reopen_does_not_resettle(self):
        self.submitted()
        token = self.witness()
        self.settle(token)
        self.reopen()
        with self.assertRaisesRegex(Refused, "TURN_NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["used_units"], 12)

    def test_restart_with_new_issuer_cannot_reuse_token(self):
        self.submitted()
        token = self.witness()
        self.reopen(new_issuer=True)
        with self.assertRaisesRegex(Refused, "UNTRUSTED_OR_REPLAYED"):
            self.settle(token)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_restart_with_test_observer_may_reissue_new_mock(self):
        self.submitted()
        self.reopen(new_issuer=True)
        self.safe(self.settle(self.witness()))
        self.assertEqual(self.budget()["used_units"], 12)

    def test_no_auto_resend_when_ambiguous_delivery(self):
        self.submitted()
        self.gate.interrupt_mock("attemptA")
        self.reopen()
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.gate.submit_mock("attemptA", BIND)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_evidence_does_not_prove_remote_cancellation(self):
        self.submitted()
        self.safe(self.gate.cancel_mock("attemptA"))
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_no_network_sdk_or_tool_executed(self):
        self.submitted()
        with patch("socket.socket", side_effect=AssertionError("network")):
            with patch("subprocess.Popen", side_effect=AssertionError("process")):
                with patch("subprocess.run", side_effect=AssertionError("run")):
                    result = self.settle(self.witness())
        self.safe(result)

    def test_source_explicitly_omits_real_provider(self):
        import inspect
        import px_s3_b31_evidence_boundary as module
        source = inspect.getsource(module)
        for forbidden in ("import requests", "import httpx", "from openai",
                          "OPENAI_API_KEY", "subprocess.Popen", "requests.post"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
