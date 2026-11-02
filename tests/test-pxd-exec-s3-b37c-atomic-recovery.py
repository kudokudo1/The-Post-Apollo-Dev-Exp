#!/usr/bin/env python3
"""B37-C: executable fixture tests ONLY, disposable SQLite; zero provider IO."""
from dataclasses import replace
import copy
import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b29_transport_ledger import Refused as LedgerRefused
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import reserve_mock, seal_fixture
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture, Refused

BIND = {
    "room": "roomA", "patient": "patientA", "assignment": "assignmentA",
    "bed": "bedA", "turnId": "turnA", "generation": 7,
}


def text_events(text="mock answer", response_id="respA"):
    start = {
        "id": "msgA", "type": "message", "role": "assistant",
        "status": "in_progress", "content": [],
    }
    end = {
        "id": "msgA", "type": "message", "role": "assistant",
        "status": "completed", "content": [
            {"type": "output_text", "text": text, "annotations": []}
        ],
    }
    return [
        {"type": "response.created", "sequence_number": 1,
         "response": {"id": response_id, "status": "in_progress"}},
        {"type": "response.output_item.added", "sequence_number": 2,
         "output_index": 0, "item": copy.deepcopy(start)},
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


class AtomicRecoveryTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="b37c-offline-")
        self.addCleanup(td.cleanup)
        self.db = Path(td.name) / "disposable.sqlite3"
        self.conn = sqlite3.connect(self.db, isolation_level=None, timeout=3)
        self.addCleanup(self.conn.close)
        self.issuer = TestOnlyEvidenceIssuer()
        self.fx = AtomicOfflineFixture(self.conn, self.issuer)
        self.fx.configure_mock_budget("scopeA", 100)
        self.binding = dict(BIND)
        self.request = build_request("fixture prompt")
        self.sealed = seal_fixture(
            self.request, binding=self.binding, attempt_id="attemptA",
        )

    def register(self):
        return self.fx.register_mock(
            self.sealed, scope="scopeA", units=25,
            current_binding=self.binding,
        )

    def begin(self, **kw):
        return self.fx.begin_mock(
            self.sealed, current_binding=self.binding, **kw,
        )

    def recover(self):
        return self.fx.recover_mock(
            self.sealed, current_binding=self.binding,
        )

    def reopen(self):
        self.conn.close()
        self.conn = sqlite3.connect(self.db, isolation_level=None, timeout=3)
        self.addCleanup(self.conn.close)
        self.issuer = TestOnlyEvidenceIssuer()
        self.fx = AtomicOfflineFixture(self.conn, self.issuer)

    def state(self):
        return self.fx.ledger.state("attemptA")["state"]

    def budget(self):
        return self.fx.ledger.budget("scopeA")

    def safe(self, result):
        for key in (
            "launchAuthorized", "toolDispatchAuthorized", "retryAuthorized",
            "productionReady", "providerStarted", "remoteDeliveryObserved",
            "realStopVerified", "realSpendVerified",
        ):
            self.assertIs(result[key], False, key)
        for key in ("modelCalls", "toolCalls", "hospitalWrites"):
            self.assertEqual(result[key], 0)
        self.assertNotIn("fixture prompt", json.dumps(result))
        return result

    def refuse(self, action, expected=None):
        with self.assertRaises((Refused, LedgerRefused)) as error:
            action()
        if expected:
            self.assertIn(expected, str(error.exception))
        self.assertNotIn("fixture prompt", str(error.exception))

    def witness(self, events=None, **overrides):
        kw = {
            "attempt_id": "attemptA",
            "client_request_id": self.sealed.client_request_id,
            "binding": self.binding, "response_id": "respA",
            "events": text_events() if events is None else events,
            "usage_units": 11, "status": "completed",
        }
        kw.update(overrides)
        return self.issuer.issue_test_only(**kw)

    def test_registration_binds_hash_and_unique_request_id(self):
        self.safe(self.register())
        row = self.fx.ledger._attempt("attemptA")
        self.assertEqual(row["client_request_id"], self.sealed.client_request_id)
        self.assertEqual(row["b37c_payload_sha256"], self.sealed.payload_sha256)
        self.assertEqual(len(row["b37c_payload_sha256"]), 64)

    def test_registration_does_not_submit_or_spend(self):
        self.safe(self.register())
        self.assertEqual(self.state(), "RESERVED")
        self.assertEqual(self.budget()["reserved_units"], 25)
        self.assertEqual(self.budget()["used_units"], 0)

    def test_double_registration_is_idempotent_before_handoff(self):
        self.register()
        self.safe(self.register())
        self.assertEqual(self.budget()["reserved_units"], 25)

    def test_atomic_mock_transition_is_never_remote_delivery(self):
        self.register()
        v = self.safe(self.begin(offered_bytes=self.sealed.payload))
        self.assertEqual(v["state"], "SUBMISSION_UNCONFIRMED")
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")

    def test_begin_requires_registered_request(self):
        self.refuse(self.begin)

    def test_partial_registration_crash_is_unbound_and_unsendable(self):
        reserve_mock(
            self.fx.ledger, self.sealed, scope="scopeA",
            units=25, current_binding=self.binding,
        )
        self.reopen()
        self.refuse(self.begin, "TRANSACTION_PAYLOAD_CHANGED")
        self.refuse(self.recover, "TRANSACTION_PAYLOAD_CHANGED")
        self.assertEqual(self.state(), "RESERVED")

    def test_reopen_before_transition_preserves_no_send(self):
        self.register()
        self.reopen()
        v = self.safe(self.recover())
        self.assertEqual(v["state"], "RESERVED")
        self.assertEqual(v["reason"], "B37C_PRE_SUBMISSION_NO_AUTO_RETRY")
        self.assertEqual(self.budget()["reserved_units"], 25)

    def test_reopen_after_transition_quarantines_unknown(self):
        self.register()
        self.begin()
        self.reopen()
        v = self.safe(self.recover())
        self.assertEqual(v["state"], "REMOTE_OUTCOME_UNKNOWN")
        self.assertEqual(self.state(), "REMOTE_OUTCOME_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 25)
        self.assertEqual(self.budget()["used_units"], 0)

    def test_repeated_recovery_never_resubmits(self):
        self.register()
        self.begin()
        self.reopen()
        first = self.safe(self.recover())
        second = self.safe(self.recover())
        self.assertEqual(first["state"], second["state"])
        self.refuse(self.begin, "STATE_NOT_RESERVED")

    def test_cancel_after_uncertain_transition_holds_budget(self):
        self.register()
        self.begin()
        self.reopen()
        self.recover()
        self.fx.cancel_mock("attemptA")
        self.assertEqual(self.state(), "CANCEL_PENDING")
        self.assertEqual(self.budget()["reserved_units"], 25)
        self.refuse(self.begin, "STATE_NOT_RESERVED")

    def test_revoke_after_transition_holds_budget(self):
        self.register()
        self.begin()
        revoked = dict(self.binding, generation=8)
        self.fx.revoke_if_changed("attemptA", revoked)
        self.assertEqual(self.state(), "REVOKED_REMOTE_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 25)
        self.refuse(self.begin, "STATE_NOT_RESERVED")

    def test_pre_transition_cancel_releases_only_fake_reservation(self):
        self.register()
        self.fx.cancel_mock("attemptA")
        self.assertEqual(self.state(), "ABORTED_PRE_SUBMISSION")
        self.assertEqual(self.budget()["reserved_units"], 0)
        self.refuse(self.begin, "STATE_NOT_RESERVED")

    def test_replayed_mock_handoff_is_refused(self):
        self.register()
        self.begin()
        self.refuse(self.begin, "STATE_NOT_RESERVED")

    def test_swapped_final_bytes_refused_without_state_change(self):
        self.register()
        for raw in (
            b"{}", b"", b"\xff",
            self.sealed.payload + b"\n",
            self.sealed.payload.replace(b"fixture prompt", b"swapped prompt"),
            bytearray(self.sealed.payload), "not bytes",
        ):
            with self.subTest(raw=repr(raw)[:20]):
                self.refuse(
                    lambda: self.begin(offered_bytes=raw),
                    "FINAL_BYTES_CHANGED",
                )
        self.assertEqual(self.state(), "RESERVED")

    def test_original_mutable_request_no_longer_controls_handoff(self):
        self.register()
        self.request["input"][0]["content"] = "malicious mutable edit"
        self.request["tools"] = [{"type": "function", "name": "shell"}]
        self.safe(self.begin(offered_bytes=self.sealed.payload))

    def test_modified_seal_request_id_refused(self):
        self.register()
        fake = replace(self.sealed, client_request_id="b37b." + "0"*64)
        self.refuse(
            lambda: self.fx.begin_mock(fake, current_binding=self.binding),
            "SEAL_OR_AUTHORITY_INVALID",
        )
        self.assertEqual(self.state(), "RESERVED")

    def test_modified_seal_payload_refused(self):
        self.register()
        fake = replace(
            self.sealed, payload=self.sealed.payload + b" ",
            payload_sha256=hashlib.sha256(self.sealed.payload + b" ").hexdigest(),
        )
        self.refuse(
            lambda: self.fx.begin_mock(fake, current_binding=self.binding),
            "SEAL_OR_AUTHORITY_INVALID",
        )
        self.assertEqual(self.state(), "RESERVED")

    def test_stale_synthetic_authority_refused_all_dimensions(self):
        self.register()
        for key, value in (
            ("room", "foreign"), ("patient", "foreign"),
            ("assignment", "foreign"), ("bed", "foreign"),
            ("turnId", "foreign"), ("generation", 8),
        ):
            with self.subTest(key=key):
                bad = dict(self.binding, **{key: value})
                self.refuse(
                    lambda: self.fx.begin_mock(
                        self.sealed, current_binding=bad),
                    "SEAL_OR_AUTHORITY_INVALID",
                )
        self.assertEqual(self.state(), "RESERVED")

    def test_immutable_database_trigger_blocks_request_id_change(self):
        self.register()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE b29_fixture_attempts SET client_request_id='fake'"
            )
        self.assertEqual(self.state(), "RESERVED")

    def test_immutable_database_trigger_blocks_digest_change_or_clear(self):
        self.register()
        for value in ("'0'", "NULL"):
            with self.subTest(value=value):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(
                        "UPDATE b29_fixture_attempts "
                        "SET b37c_payload_sha256=" + value
                    )

    def test_immutable_database_trigger_blocks_binding_change(self):
        self.register()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE b29_fixture_attempts SET binding_json='{}'"
            )

    def test_transaction_guard_fails_if_db_identity_corrupted(self):
        self.register()
        # Disposable DB intrusion simulation: bypass our fixture trigger,
        # then prove the BEGIN IMMEDIATE comparison still refuses.
        self.conn.execute("DROP TRIGGER b37c_fixture_request_immutable")
        self.conn.execute(
            "UPDATE b29_fixture_attempts SET client_request_id='foreign'"
        )
        self.refuse(self.begin, "TRANSACTION_IDENTITY_CHANGED")
        self.assertEqual(self.state(), "RESERVED")

    def test_transaction_guard_fails_if_db_digest_corrupted(self):
        self.register()
        self.conn.execute("DROP TRIGGER b37c_fixture_request_immutable")
        self.conn.execute(
            "UPDATE b29_fixture_attempts SET b37c_payload_sha256='00'"
        )
        self.refuse(self.begin, "TRANSACTION_PAYLOAD_CHANGED")
        self.assertEqual(self.state(), "RESERVED")

    def test_late_fake_observation_persisted_and_reconciled(self):
        self.register()
        self.begin()
        self.fx.observe_mock(
            self.sealed, current_binding=self.binding, events=text_events()
        )
        self.reopen()
        v = self.safe(self.recover())
        self.assertEqual(v["state"], "SUBMISSION_UNCONFIRMED")
        self.assertEqual(
            v["reason"], "B37C_DURABLE_MOCK_OBSERVATION_RECONCILE_ONLY"
        )
        self.assertTrue(v["durableMockObservation"])
        self.assertEqual(self.budget()["reserved_units"], 25)

    def test_mock_observation_then_mock_settlement(self):
        self.register()
        self.begin()
        observed = self.fx.observe_mock(
            self.sealed, current_binding=self.binding, events=text_events()
        )
        self.assertTrue(observed["durableEventDigestBound"])
        settled = self.fx.settle_mock(
            self.sealed, current_binding=self.binding,
            events=text_events(), witness=self.witness(),
        )
        self.assertEqual(settled["state"], "MOCK_COMPLETED")
        self.assertEqual(self.budget()["reserved_units"], 0)
        self.assertEqual(self.budget()["used_units"], 11)
        self.safe(self.recover())
        self.assertEqual(self.recover()["reason"], "B37C_ALREADY_MOCK_SETTLED_NO_REPLAY")
        self.refuse(self.begin, "STATE_NOT_RESERVED")

    def test_observation_after_reopen_can_settle_with_new_mock_witness(self):
        self.register()
        self.begin()
        self.fx.observe_mock(
            self.sealed, current_binding=self.binding, events=text_events()
        )
        self.reopen()
        self.safe(self.recover())
        settled = self.fx.settle_mock(
            self.sealed, current_binding=self.binding, events=text_events(),
            witness=self.witness(),
        )
        self.assertEqual(settled["state"], "MOCK_COMPLETED")

    def test_changed_observation_digest_refused_by_b33(self):
        self.register()
        self.begin()
        self.fx.observe_mock(
            self.sealed, current_binding=self.binding, events=text_events()
        )
        self.refuse(
            lambda: self.fx.observe_mock(
                self.sealed, current_binding=self.binding,
                events=text_events("changed")
            ),
            "OBSERVATION_DRIFT",
        )

    def test_mock_witness_replay_never_settles_twice(self):
        self.register()
        self.begin()
        self.fx.observe_mock(
            self.sealed, current_binding=self.binding, events=text_events()
        )
        witness = self.witness()
        self.fx.settle_mock(
            self.sealed, current_binding=self.binding,
            events=text_events(), witness=witness,
        )
        self.refuse(
            lambda: self.fx.settle_mock(
                self.sealed, current_binding=self.binding,
                events=text_events(), witness=witness,
            ),
            "NOT_ACTIVE",
        )
        self.assertEqual(self.budget()["used_units"], 11)

    def test_interrupted_stream_without_observation_reconciliation_hold(self):
        self.register()
        self.begin()
        self.reopen()
        self.safe(self.recover())
        self.refuse(
            lambda: self.fx.observe_mock(
                self.sealed, current_binding=self.binding,
                events=text_events(),
            ),
            "NOT_ACTIVE",
        )
        self.assertEqual(self.budget()["reserved_units"], 25)

    def test_second_connection_observes_same_seal_and_state(self):
        self.register()
        self.begin()
        with sqlite3.connect(self.db, isolation_level=None, timeout=3) as other:
            second = AtomicOfflineFixture(other, TestOnlyEvidenceIssuer())
            self.assertEqual(
                second.ledger._attempt("attemptA")["b37c_payload_sha256"],
                self.sealed.payload_sha256,
            )
            v = self.safe(second.recover_mock(
                self.sealed, current_binding=self.binding))
            self.assertEqual(v["state"], "REMOTE_OUTCOME_UNKNOWN")

    def test_two_connections_only_one_atomic_transition(self):
        self.register()
        successes, errors = [], []
        barrier = threading.Barrier(2)
        handles = [
            sqlite3.connect(self.db, isolation_level=None, timeout=4,
                            check_same_thread=False)
            for _ in range(2)
        ]
        for connection in handles:
            self.addCleanup(connection.close)
        separate = [
            AtomicOfflineFixture(connection, TestOnlyEvidenceIssuer())
            for connection in handles
        ]
        def runner(fixture):
            barrier.wait()
            try:
                successes.append(fixture.begin_mock(
                    self.sealed, current_binding=self.binding,
                ))
            except Refused as exc:
                errors.append(str(exc))
        workers = [
            threading.Thread(target=runner, args=(item,))
            for item in separate
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
        self.assertTrue(all(not w.is_alive() for w in workers))
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("STATE_NOT_RESERVED", errors[0])
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")

    def test_prepared_attempt_cannot_be_reused_with_new_request(self):
        self.register()
        alternative = seal_fixture(
            build_request("different text"),
            binding=self.binding, attempt_id="attemptA",
        )
        self.refuse(
            lambda: self.fx.register_mock(
                alternative, scope="scopeA", units=25,
                current_binding=self.binding,
            ),
            "RESERVE_REFUSED",
        )
        self.assertEqual(self.state(), "RESERVED")

    def test_unauthorized_fixture_issuer_refused(self):
        with self.assertRaises(Refused):
            AtomicOfflineFixture(self.conn, object())

    def test_foreign_sqlite_tables_refused(self):
        foreign = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(foreign.close)
        foreign.execute("CREATE TABLE hospital_private_records(id INT)")
        with self.assertRaises(LedgerRefused):
            AtomicOfflineFixture(foreign, TestOnlyEvidenceIssuer())

    def test_no_network_process_or_real_provider(self):
        with patch.object(socket, "create_connection",
                          side_effect=AssertionError("network")), \
             patch.object(subprocess, "Popen",
                          side_effect=AssertionError("process")):
            self.register()
            self.safe(self.begin())
            self.safe(self.recover())
        self.assertNotIn("openai", sys.modules)
        self.refuse(lambda: self.fx.require_real_dispatch(self.sealed),
                    "NO_REAL_TRANSPORT")

    def test_recovery_and_receipts_never_claim_real_delivery(self):
        self.safe(self.register())
        self.safe(self.begin())
        self.safe(self.recover())
        for receipt in (self.fx.snapshot("attemptA"), self.recover()):
            self.safe(receipt)
            self.assertNotIn("requestBody", receipt)
            self.assertNotIn("launchToken", receipt)


if __name__ == "__main__":
    unittest.main()
