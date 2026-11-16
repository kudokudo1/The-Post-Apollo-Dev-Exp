#!/usr/bin/env python3
"""B37-C/B38 cross-lane compatibility evidence, not an integrated sender.

B38-A/B come from the separate exact B38-B commit checked out READ-ONLY
by CI. This test does NOT modify those sources or install a runtime shim.
Patching the mock handoff is test-local proof of a possible seam; it is NOT
a real access-control boundary or an approved B38 sender change.
"""
from dataclasses import replace
import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MAIN_BIN = ROOT / "bin"
PINNED_B38 = ROOT / "b38-pinned" / "bin"
if not PINNED_B38.is_dir():
    raise RuntimeError("B37_B38_REFUSED_PINNED_B38_SOURCE_REQUIRED")
sys.path.insert(0, str(MAIN_BIN))
sys.path.append(str(PINNED_B38))

from px_s3_b29_transport_ledger import SyntheticLedger
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import Refused as B37BRefused, reserve_mock, seal_fixture
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture, Refused as B37CRefused
import px_s3_b38a_model_only_mock_client as b38a
from px_s3_b38a_model_only_mock_client import FakeTextStream, Refused as B38ARefused
from px_s3_b38b_trusted_sender_mock import MockTrustedSender, Refused as B38BRefused

BIND = {
    "room": "syntheticRoom", "patient": "syntheticPatient",
    "assignment": "syntheticAssignment", "bed": "syntheticBed",
    "turnId": "syntheticTurn", "generation": 11,
}


class B37CB38CompatEvidence(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="b37c-b38-offline-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "disposable.sqlite3"
        self.conn = sqlite3.connect(self.path, isolation_level=None, timeout=3)
        self.addCleanup(self.conn.close)
        self.binding = dict(BIND)
        self.sealed = seal_fixture(
            build_request("PRIVATE_TEST_PROMPT"),
            binding=self.binding, attempt_id="attemptA",
        )
        self.issuer = TestOnlyEvidenceIssuer()
        self.atomic = AtomicOfflineFixture(self.conn, self.issuer)
        self.atomic.configure_mock_budget("mockBudget", 30)
        self.sender = MockTrustedSender(self.binding)
        self.handoff_calls = []

    def register_atomic(self):
        self.atomic.register_mock(
            self.sealed, scope="mockBudget", units=5,
            current_binding=self.binding,
        )

    def reserve_old(self):
        reserve_mock(
            self.atomic.ledger, self.sealed, scope="mockBudget",
            units=5, current_binding=self.binding,
        )

    def state(self):
        return self.atomic.ledger.state("attemptA")["state"]

    def budget(self):
        return self.atomic.ledger.budget("mockBudget")

    def guarded_test_handoff(self, ledger, sealed, *,
                             current_binding, observed_bytes=None):
        """Test-only shim. Avoid treating monkeypatching as authorization."""
        self.handoff_calls.append(sealed.client_request_id)
        if ledger is not self.atomic.ledger:
            raise B37BRefused("B37B_REFUSED_WRONG_FIXTURE_LEDGER")
        try:
            return self.atomic.begin_mock(
                sealed, current_binding=current_binding,
                offered_bytes=observed_bytes,
            )
        except B37CRefused:
            # B38-B currently handles B37-B style rejection codes.
            raise B37BRefused("B37B_REFUSED_ATOMIC_FENCE")
        # Never let an unrecognized exception imply a successful send.

    def send_guarded_in_test(self, ticket):
        with patch.object(b38a, "mock_handoff",
                          side_effect=self.guarded_test_handoff):
            return self.sender.send_mock(
                self.atomic.ledger, self.sealed, ticket,
            )

    def assert_no_remote(self, reply=None):
        receipt = self.sender.inspect_mock()
        self.assertEqual(receipt["realNetworkCalls"], 0)
        self.assertEqual(receipt["realProviderCalls"], 0)
        self.assertIs(receipt["credentialBoundaryCertified"], False)
        self.assertIs(receipt["productionReady"], False)
        if reply is not None:
            self.assertFalse(reply.real_model_called)
            self.assertFalse(reply.real_transport_used)
            self.assertFalse(reply.production_ready)
            self.assertEqual(reply.client_request_id,
                             self.sealed.client_request_id)

    def test_current_unmodified_b38_sender_bypasses_unbound_b37c_digest(self):
        """EXPECTED GAP: only B37-B reserve, no B37-C registration."""
        self.reserve_old()
        self.assertIsNone(
            self.atomic.ledger._attempt("attemptA")["b37c_payload_sha256"]
        )
        ticket = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        reply = self.sender.send_mock(self.atomic.ledger, self.sealed, ticket)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        self.assertEqual(self.handoff_calls, [])
        self.assert_no_remote(reply)

    def test_current_unmodified_b38_sender_ignores_corrupted_b37c_digest(self):
        """EXPECTED GAP: demonstrates lack of atomic digest verification."""
        self.register_atomic()
        self.conn.execute("DROP TRIGGER b37c_fixture_request_immutable")
        self.conn.execute(
            "UPDATE b29_fixture_attempts SET b37c_payload_sha256=?",
            ("0" * 64,),
        )
        ticket = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        reply = self.sender.send_mock(self.atomic.ledger, self.sealed, ticket)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        self.assert_no_remote(reply)

    def test_test_only_redirect_exercises_atomic_b37c_before_fake_reply(self):
        self.register_atomic()
        ticket = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        reply = self.send_guarded_in_test(ticket)
        self.assertEqual(reply.text,
                         "B38B synthetic text, never a provider response")
        self.assertEqual(self.handoff_calls,
                         [self.sealed.client_request_id])
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        self.assertEqual(
            self.atomic.ledger._attempt("attemptA")["b37c_payload_sha256"],
            hashlib.sha256(self.sealed.payload).hexdigest(),
        )
        self.assert_no_remote(reply)

    def test_test_only_redirect_requires_registered_payload_hash(self):
        self.reserve_old()
        permit = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        with self.assertRaisesRegex(B38BRefused, "FAKE_HANDOFF_REFUSED"):
            self.send_guarded_in_test(permit)
        self.assertEqual(self.handoff_calls,
                         [self.sealed.client_request_id])
        self.assertEqual(self.state(), "RESERVED")
        self.assert_no_remote()

    def test_test_only_redirect_refuses_corrupt_stored_hash(self):
        self.register_atomic()
        permit = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        self.conn.execute("DROP TRIGGER b37c_fixture_request_immutable")
        self.conn.execute(
            "UPDATE b29_fixture_attempts SET b37c_payload_sha256=?",
            ("0" * 64,),
        )
        with self.assertRaisesRegex(B38BRefused, "FAKE_HANDOFF_REFUSED"):
            self.send_guarded_in_test(permit)
        self.assertEqual(self.state(), "RESERVED")
        self.assert_no_remote()

    def test_test_only_redirect_refuses_changed_final_bytes(self):
        self.register_atomic()
        permit = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        with patch.object(
            self.atomic, "begin_mock",
            side_effect=B37CRefused("B37C_REFUSED_FINAL_BYTES_CHANGED")
        ):
            with self.assertRaisesRegex(B38BRefused, "FAKE_HANDOFF_REFUSED"):
                self.send_guarded_in_test(permit)
        self.assertEqual(self.state(), "RESERVED")

    def test_test_only_redirect_will_not_replay_sealed_ticket(self):
        self.register_atomic()
        permit = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        self.send_guarded_in_test(permit)
        with self.assertRaisesRegex(B38BRefused, "PERMIT_NOT_ISSUED"):
            self.send_guarded_in_test(permit)
        self.assertEqual(len(self.handoff_calls), 1)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        self.assert_no_remote()

    def test_test_only_redirect_refuses_second_mock_submission(self):
        self.register_atomic()
        self.send_guarded_in_test(
            self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        )
        with self.assertRaisesRegex(B38BRefused, "FAKE_RESERVATION_MISMATCH"):
            self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")

    def test_test_only_redirect_refuses_paused_sender_after_prepare(self):
        self.register_atomic()
        permit = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        self.sender.pause()
        with self.assertRaisesRegex(B38BRefused, "STALE_PERMIT"):
            self.send_guarded_in_test(permit)
        self.assertEqual(self.handoff_calls, [])
        self.assertEqual(self.state(), "RESERVED")

    def test_test_only_redirect_refuses_generation_change_after_prepare(self):
        self.register_atomic()
        permit = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        self.sender.change_binding(dict(self.binding, generation=12))
        with self.assertRaisesRegex(B38BRefused, "STALE_PERMIT"):
            self.send_guarded_in_test(permit)
        self.assertEqual(self.handoff_calls, [])
        self.assertEqual(self.state(), "RESERVED")

    def test_test_only_redirect_refuses_revocation_after_prepare(self):
        self.register_atomic()
        permit = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        self.sender.revoke()
        with self.assertRaisesRegex(B38BRefused, "STALE_PERMIT"):
            self.send_guarded_in_test(permit)
        self.assertEqual(self.state(), "RESERVED")

    def test_test_only_redirect_refuses_sender_restart_after_prepare(self):
        self.register_atomic()
        permit = self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        self.sender.restart()
        with self.assertRaisesRegex(B38BRefused, "STALE_PERMIT"):
            self.send_guarded_in_test(permit)
        self.assertEqual(self.state(), "RESERVED")

    def test_restart_after_test_only_transition_quarantines_uncertain(self):
        self.register_atomic()
        self.send_guarded_in_test(
            self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        )
        self.conn.close()
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=3)
        self.addCleanup(conn.close)
        recovered = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
        result = recovered.recover_mock(
            self.sealed, current_binding=self.binding,
        )
        self.assertEqual(result["state"], "REMOTE_OUTCOME_UNKNOWN")
        self.assertFalse(result["retryAuthorized"])
        self.assertFalse(result["remoteDeliveryObserved"])
        self.assertEqual(recovered.ledger.budget("mockBudget")["reserved_units"], 5)
        self.assertEqual(recovered.ledger.budget("mockBudget")["used_units"], 0)
        other_sender = MockTrustedSender(self.binding)
        with self.assertRaisesRegex(B38BRefused, "FAKE_RESERVATION_MISMATCH"):
            other_sender.prepare_mock(recovered.ledger, self.sealed)

    def test_pretransition_cancel_refuses_b38_sender_and_handoff(self):
        self.register_atomic()
        self.atomic.cancel_mock("attemptA")
        with self.assertRaisesRegex(B38BRefused, "FAKE_RESERVATION_MISMATCH"):
            self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        self.assertEqual(self.state(), "ABORTED_PRE_SUBMISSION")
        self.assertEqual(self.budget()["reserved_units"], 0)

    def test_test_only_redirect_denies_non_text_injected_frame(self):
        self.register_atomic()
        fake = FakeTextStream(
            request_id=self.sealed.client_request_id,
            offered_bytes=self.sealed.payload,
            frames=(
                b'{"type":"mock.tool.call","seq":0,"arguments":"{}"}',
                b'{"type":"mock.text.completed","seq":1}',
            ),
        )
        with patch.object(
            b38a, "mock_handoff",
            side_effect=AssertionError("non-text reached ledger")
        ):
            with self.assertRaisesRegex(B38ARefused, "NON_TEXT_EVENT"):
                b38a.exchange_mock(
                    self.atomic.ledger, self.sealed,
                    current_binding=self.binding, stream=fake,
                )
        self.assertEqual(self.state(), "RESERVED")
        self.assert_no_remote()

    def test_test_only_redirect_refuses_forged_seal(self):
        self.register_atomic()
        fake = replace(self.sealed, client_request_id="b37b." + "0"*64)
        with self.assertRaisesRegex(B38BRefused, "SEALED_REQUEST_INVALID"):
            self.sender.prepare_mock(self.atomic.ledger, fake)
        self.assertEqual(self.state(), "RESERVED")

    def test_mock_paths_cannot_open_network_or_native_process(self):
        self.register_atomic()
        with patch.object(socket, "create_connection",
                          side_effect=AssertionError("NETWORK")), \
             patch.object(subprocess, "Popen",
                          side_effect=AssertionError("NATIVE")):
            self.send_guarded_in_test(
                self.sender.prepare_mock(self.atomic.ledger, self.sealed)
            )
        self.assert_no_remote()
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")


if __name__ == "__main__":
    unittest.main()
