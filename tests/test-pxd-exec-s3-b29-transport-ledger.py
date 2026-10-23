#!/usr/bin/env python3
"""B29 fixture bookkeeping security regressions: disposable SQLite only."""
import copy
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b29_transport_ledger import SyntheticLedger, Refused, PROFILE

BINDING = {"room": "ROOM_A", "patient": "PATIENT_A",
           "assignment": "ASSIGNMENT_A", "bed": "BED_A",
           "turnId": "TURN_A", "generation": 1}


class B29SyntheticLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="b29-disposable-")
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "inert-fixture.sqlite3"
        self.conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=2)
        self.addCleanup(self.conn.close)
        self.ledger = SyntheticLedger(self.conn)
        self.ledger.initialize()
        self.ledger.configure_mock_budget("scopeA", 100)

    def reserve(self, *, attempt="attemptA", client="clientA",
                binding=None, units=40, mode="FOREGROUND_STREAM",
                scope="scopeA"):
        return self.ledger.reserve(
            attempt_id=attempt, client_request_id=client, scope=scope,
            binding=BINDING if binding is None else binding,
            mode=mode, units=units,
        )

    def submitted(self, *, mode="FOREGROUND_STREAM"):
        self.reserve(mode=mode)
        return self.ledger.mark_submission("attemptA", BINDING)

    def safe(self, result, state=None):
        if state:
            self.assertEqual(result["state"], state)
        for key in ("launchAuthorized", "toolDispatchAuthorized",
                    "realStopVerified", "realSpendVerified",
                    "retryAuthorized", "productionReady"):
            self.assertIs(result[key], False)
        self.assertEqual(result["realProviderCalls"], 0)
        return result

    def test_fixture_profile_constant_and_schema_only(self):
        self.assertEqual(PROFILE, "B29_INERT_TRANSPORT_FIXTURE")
        tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertEqual(tables, {"b29_fixture_marker", "b29_fixture_budgets",
                                  "b29_fixture_attempts"})

    def test_empty_fixture_refuses_unknown_hospital_tables(self):
        self.conn.execute("CREATE TABLE rooms (id TEXT)")
        with self.assertRaisesRegex(Refused, "FOREIGN_DATABASE"):
            self.ledger.initialize()

    def test_marker_mutation_refused(self):
        self.conn.execute("DELETE FROM b29_fixture_marker")
        with self.assertRaisesRegex(Refused, "FIXTURE_MARKER"):
            self.ledger.initialize()

    def test_same_budget_config_idempotent_changed_limit_refused(self):
        self.assertEqual(self.ledger.configure_mock_budget("scopeA", 100)["limit_units"], 100)
        with self.assertRaisesRegex(Refused, "BUDGET_RECONFIGURE"):
            self.ledger.configure_mock_budget("scopeA", 10000)

    def test_reservation_durable_and_no_real_authority(self):
        state = self.safe(self.reserve(), "RESERVED")
        self.assertEqual(state["clientRequestId"], "clientA")
        self.assertIsNone(state["responseId"])
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)
        self.assertEqual(self.ledger.budget("scopeA")["used_units"], 0)

    def test_replay_same_reservation_is_not_second_bill(self):
        first = self.reserve()
        again = self.reserve()
        self.assertEqual(first, again)
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)

    def test_reused_turn_with_different_attempt_refused(self):
        self.reserve()
        with self.assertRaisesRegex(Refused, "TURN_ALREADY_BOUND"):
            self.reserve(attempt="attemptB", client="clientB")
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)

    def test_request_id_cannot_be_reused_for_another_turn(self):
        self.reserve()
        other = dict(BINDING, turnId="TURN_B")
        with self.assertRaisesRegex(Refused, "REUSED_REQUEST_ID"):
            self.reserve(attempt="attemptB", client="clientA",
                         binding=other, units=10)
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)

    def test_mock_budget_overcommit_refused_before_reservation(self):
        self.reserve(units=90)
        with self.assertRaisesRegex(Refused, "BUDGET_EXHAUSTED"):
            self.reserve(attempt="attemptB", client="clientB",
                         binding=dict(BINDING, turnId="TURN_B"), units=20)
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 90)

    def test_active_attempt_concurrency_limit(self):
        self.reserve(units=10)
        self.reserve(attempt="attemptB", client="clientB",
                     binding=dict(BINDING, turnId="TURN_B"), units=10)
        with self.assertRaisesRegex(Refused, "CONCURRENCY_LIMIT"):
            self.reserve(attempt="attemptC", client="clientC",
                         binding=dict(BINDING, turnId="TURN_C"), units=10)

    def test_duplicate_submission_refused_and_not_resubmitted(self):
        self.submitted()
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED_OR_CLOSED"):
            self.ledger.mark_submission("attemptA", BINDING)
        self.safe(self.ledger.state("attemptA"), "SUBMISSION_UNCONFIRMED")

    def test_changed_assignment_fences_submission(self):
        self.reserve()
        with self.assertRaisesRegex(Refused, "AUTHORITY_CHANGED"):
            self.ledger.mark_submission(
                "attemptA", dict(BINDING, assignment="OTHER")
            )
        self.safe(self.ledger.state("attemptA"), "RESERVED")

    def test_unknown_delivery_holds_cost_reservation_and_no_retry(self):
        self.submitted()
        result = self.safe(self.ledger.transport_lost("attemptA"),
                           "REMOTE_OUTCOME_UNKNOWN")
        self.assertFalse(result["retryAuthorized"])
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.ledger.mark_submission("attemptA", BINDING)

    def test_ambiguous_delivery_state_survives_reopen(self):
        self.submitted()
        self.ledger.transport_lost("attemptA")
        with sqlite3.connect(self.db_path, isolation_level=None) as reopened:
            ledger = SyntheticLedger(reopened)
            ledger.initialize()
            self.safe(ledger.state("attemptA"), "REMOTE_OUTCOME_UNKNOWN")
            self.assertEqual(ledger.budget("scopeA")["reserved_units"], 40)

    def test_other_sqlite_connection_sees_single_reserved_identity(self):
        self.reserve()
        with sqlite3.connect(self.db_path, isolation_level=None) as second:
            ledger2 = SyntheticLedger(second)
            ledger2.initialize()
            with self.assertRaisesRegex(Refused, "TURN_ALREADY_BOUND"):
                ledger2.reserve(
                    attempt_id="different", client_request_id="other",
                    scope="scopeA", binding=BINDING,
                    mode="FOREGROUND_STREAM", units=40
                )
            self.assertEqual(ledger2.budget("scopeA")["reserved_units"], 40)

    def test_foreground_cancellation_after_submission_never_remote_verified(self):
        self.submitted()
        self.safe(self.ledger.cancel("attemptA"), "CANCEL_PENDING")
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)

    def test_pre_submission_cancel_releases_unused_reservation(self):
        self.reserve()
        self.safe(self.ledger.cancel("attemptA"), "ABORTED_PRE_SUBMISSION")
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 0)
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.ledger.mark_submission("attemptA", BINDING)

    def test_pre_submission_revocation_releases_unused_reservation(self):
        self.reserve()
        self.safe(self.ledger.revoke_if_changed(
            "attemptA", dict(BINDING, generation=2)
        ), "REVOKED_PRE_SUBMISSION")
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 0)

    def test_post_submission_revocation_holds_reservation(self):
        self.submitted()
        self.safe(self.ledger.revoke_if_changed(
            "attemptA", dict(BINDING, patient="PATIENT_B")
        ), "REVOKED_REMOTE_UNKNOWN")
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)
        with self.assertRaisesRegex(Refused, "UNTRUSTED_SETTLEMENT"):
            self.ledger.reconcile_mock_completed(
                "attemptA", "respA", 10, BINDING
            )

    def test_unknown_delivery_revoke_stays_fenced(self):
        self.submitted()
        self.ledger.transport_lost("attemptA")
        self.safe(self.ledger.revoke_if_changed(
            "attemptA", dict(BINDING, generation=3)
        ), "REVOKED_REMOTE_UNKNOWN")

    def test_matching_authority_snapshot_does_not_change_state(self):
        self.submitted()
        self.safe(self.ledger.revoke_if_changed(
            "attemptA", copy.deepcopy(BINDING)
        ), "SUBMISSION_UNCONFIRMED")

    def test_response_id_binding_drift_refused(self):
        self.submitted()
        self.ledger.bind_mock_response("attemptA", "respA")
        with self.assertRaisesRegex(Refused, "RESPONSE_ID_DRIFT"):
            self.ledger.bind_mock_response("attemptA", "respB")

    def test_duplicate_response_across_turns_refused(self):
        self.submitted()
        self.ledger.bind_mock_response("attemptA", "respA")
        self.reserve(attempt="attemptB", client="clientB",
                     binding=dict(BINDING, turnId="TURN_B"), units=20)
        self.ledger.mark_submission("attemptB", dict(BINDING, turnId="TURN_B"))
        with self.assertRaisesRegex(Refused, "RESPONSE_REPLAY_OTHER_TURN"):
            self.ledger.bind_mock_response("attemptB", "respA")

    def test_mock_background_cancel_receipt_keeps_budget_held(self):
        self.submitted(mode="BACKGROUND_POLL")
        self.ledger.bind_mock_response("attemptA", "respA")
        self.ledger.cancel("attemptA")
        self.safe(self.ledger.observe_mock_background_cancel(
            "attemptA", "respA", "cancelling"
        ), "CANCEL_PENDING")
        self.safe(self.ledger.observe_mock_background_cancel(
            "attemptA", "respA", "cancelled"
        ), "MOCK_CANCELLED_UNVERIFIED")
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)

    def test_background_cancel_requires_bound_id_and_correct_mode(self):
        self.submitted()
        self.ledger.bind_mock_response("attemptA", "respA")
        self.ledger.cancel("attemptA")
        with self.assertRaisesRegex(Refused, "CANCEL_RECEIPT_UNBOUND"):
            self.ledger.observe_mock_background_cancel(
                "attemptA", "respA", "cancelled"
            )
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)

    def test_foreign_cancel_response_id_refused(self):
        self.submitted(mode="BACKGROUND_POLL")
        self.ledger.bind_mock_response("attemptA", "respA")
        self.ledger.cancel("attemptA")
        with self.assertRaisesRegex(Refused, "CANCEL_RECEIPT_UNBOUND"):
            self.ledger.observe_mock_background_cancel(
                "attemptA", "respForeign", "cancelled"
            )

    def test_background_stream_cursor_bound_and_monotonic(self):
        self.submitted(mode="BACKGROUND_POLL")
        self.ledger.bind_mock_response("attemptA", "respA")
        self.assertEqual(self.ledger.stream_cursor("attemptA", 4)["cursor"], 4)
        with self.assertRaisesRegex(Refused, "CURSOR_UNBOUND_OR_REPLAY"):
            self.ledger.stream_cursor("attemptA", 4)
        self.assertEqual(self.ledger.stream_cursor("attemptA", 5)["cursor"], 5)

    def test_foreground_cannot_claim_recovery_cursor(self):
        self.submitted()
        self.ledger.bind_mock_response("attemptA", "respA")
        with self.assertRaisesRegex(Refused, "CURSOR_UNBOUND_OR_REPLAY"):
            self.ledger.stream_cursor("attemptA", 1)

    def test_mock_usage_settlement_releases_and_records_mock_cost(self):
        self.submitted()
        self.ledger.bind_mock_response("attemptA", "respA")
        result = self.safe(self.ledger.reconcile_mock_completed(
            "attemptA", "respA", 12, BINDING
        ), "MOCK_COMPLETED")
        self.assertEqual(result["mockUsage"], 12)
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 0)
        self.assertEqual(self.ledger.budget("scopeA")["used_units"], 12)
        with self.assertRaisesRegex(Refused, "UNTRUSTED_SETTLEMENT"):
            self.ledger.reconcile_mock_completed("attemptA", "respA", 12, BINDING)

    def test_over_reserved_settlement_rolls_back(self):
        self.submitted()
        self.ledger.bind_mock_response("attemptA", "respA")
        with self.assertRaisesRegex(Refused, "UNTRUSTED_SETTLEMENT"):
            self.ledger.reconcile_mock_completed(
                "attemptA", "respA", 50, BINDING
            )
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)
        self.assertEqual(self.ledger.budget("scopeA")["used_units"], 0)

    def test_mock_settlement_after_disconnect_refused(self):
        self.submitted()
        self.ledger.bind_mock_response("attemptA", "respA")
        self.ledger.transport_lost("attemptA")
        with self.assertRaisesRegex(Refused, "UNTRUSTED_SETTLEMENT"):
            self.ledger.reconcile_mock_completed("attemptA", "respA", 1, BINDING)

    def test_mock_settlement_after_cancel_refused(self):
        self.submitted()
        self.ledger.bind_mock_response("attemptA", "respA")
        self.ledger.cancel("attemptA")
        with self.assertRaisesRegex(Refused, "UNTRUSTED_SETTLEMENT"):
            self.ledger.reconcile_mock_completed("attemptA", "respA", 1, BINDING)

    def test_unknown_attempt_and_invalid_scope_refused(self):
        with self.assertRaisesRegex(Refused, "ATTEMPT_MISSING"):
            self.ledger.state("missing")
        with self.assertRaisesRegex(Refused, "SCOPE"):
            self.ledger.budget("/home")

    def test_host_credential_canaries_not_read_or_persisted(self):
        canary = "B29_DO_NOT_LEAK_FAKE_KEY_123"
        with patch.dict(os.environ, {"OPENAI_API_KEY": canary,
                                     "HERMES_TOKEN": canary}):
            with patch("subprocess.Popen", side_effect=AssertionError("process")):
                with patch("subprocess.run", side_effect=AssertionError("run")):
                    with patch("socket.socket", side_effect=AssertionError("socket")):
                        result = self.safe(self.reserve(), "RESERVED")
        text = str(result) + str(list(self.conn.execute(
            "SELECT * FROM b29_fixture_attempts"
        )))
        self.assertNotIn(canary, text)
        self.assertNotIn("OPENAI_API_KEY", text)
        self.assertIsNone(self.conn.execute(
            "SELECT response_id FROM b29_fixture_attempts"
        ).fetchone()[0])

    def test_authority_cannot_smuggle_credentials(self):
        self.ledger.configure_mock_budget("scopeA", 100)
        bad = dict(BINDING, api_key="do-not-store")
        with self.assertRaisesRegex(Refused, "BINDING_SCHEMA"):
            self.reserve(binding=bad)
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 0)

    def test_invalid_budget_and_integer_type_refused(self):
        for bad in (0, -1, True, "100"):
            with self.subTest(value=bad):
                with self.assertRaises(Refused):
                    self.ledger.configure_mock_budget("scopeB", bad)
        with self.assertRaisesRegex(Refused, "BINDING_GENERATION"):
            self.reserve(binding=dict(BINDING, generation=True))

    def test_attempt_id_cannot_be_reused_for_new_turn(self):
        self.reserve()
        with self.assertRaisesRegex(Refused, "REUSED_REQUEST_ID"):
            self.reserve(attempt="attemptA", client="clientB",
                         binding=dict(BINDING, turnId="TURN_B"), units=15)
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)

    def test_unknown_mock_cancel_status_rejected_without_state_change(self):
        self.submitted(mode="BACKGROUND_POLL")
        self.ledger.bind_mock_response("attemptA", "respA")
        self.ledger.cancel("attemptA")
        with self.assertRaisesRegex(Refused, "CANCEL_STATUS"):
            self.ledger.observe_mock_background_cancel(
                "attemptA", "respA", "completed"
            )
        self.safe(self.ledger.state("attemptA"), "CANCEL_PENDING")
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)

    def test_cancelled_mock_receipt_does_not_authorize_settlement(self):
        self.submitted(mode="BACKGROUND_POLL")
        self.ledger.bind_mock_response("attemptA", "respA")
        self.ledger.cancel("attemptA")
        self.ledger.observe_mock_background_cancel(
            "attemptA", "respA", "cancelled"
        )
        with self.assertRaisesRegex(Refused, "UNTRUSTED_SETTLEMENT"):
            self.ledger.reconcile_mock_completed(
                "attemptA", "respA", 0, BINDING
            )
        self.assertEqual(self.ledger.budget("scopeA")["reserved_units"], 40)

    def test_no_sdk_or_network_real_transports_in_source(self):
        # Static import check supplements runtime canaries, not OS attestation.
        import inspect
        import px_s3_b29_transport_ledger as module
        text = inspect.getsource(module)
        for fragment in ("import requests", "import httpx", "from openai",
                         "OPENAI_API_KEY", "subprocess.Popen", "requests.post"):
            self.assertNotIn(fragment, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
