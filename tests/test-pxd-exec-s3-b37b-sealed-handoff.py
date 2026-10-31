#!/usr/bin/env python3
"""B37-B inert sealed-byte handoff and B29 ledger integration tests."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b29_transport_ledger import SyntheticLedger
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import (
    Refused, SealedFixture, mock_handoff, require_real_dispatch,
    reserve_mock, seal_fixture, verify_fixture,
)

FIXTURE_BINDING = {
    "room": "roomA", "patient": "patientA",
    "assignment": "assignmentA", "bed": "bedA",
    "turnId": "turnA", "generation": 3,
}


class B37BSealedHandoffTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.connection.close)
        self.ledger = SyntheticLedger(self.connection)
        self.ledger.initialize()
        self.ledger.configure_mock_budget("scopeA", 20)
        self.binding = dict(FIXTURE_BINDING)
        self.request = build_request("fixture text")
        self.sealed = seal_fixture(
            self.request, binding=self.binding, attempt_id="attemptA",
        )

    def reserve(self, sealed=None):
        return reserve_mock(
            self.ledger, self.sealed if sealed is None else sealed,
            scope="scopeA", units=3, current_binding=self.binding,
        )

    def handoff(self, sealed=None, **extra):
        return mock_handoff(
            self.ledger, self.sealed if sealed is None else sealed,
            current_binding=self.binding, **extra,
        )

    def assert_refused(self, callback):
        with self.assertRaises((Refused, ValueError)) as cm:
            callback()
        self.assertNotIn("fixture text", str(cm.exception))
        self.assertNotIn("FAKE_SECRET", str(cm.exception))

    def test_canonical_immutable_bytes_and_digest(self):
        expected = json.dumps(
            self.request, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("ascii")
        self.assertIs(type(self.sealed.payload), bytes)
        self.assertEqual(self.sealed.payload, expected)
        self.assertEqual(self.sealed.payload_sha256,
                         hashlib.sha256(expected).hexdigest())
        self.assertTrue(self.sealed.client_request_id.startswith("b37b."))
        self.assertEqual(len(self.sealed.client_request_id), 69)

    def test_frozen_seal_cannot_reassign_bytes(self):
        with self.assertRaises(FrozenInstanceError):
            self.sealed.payload = b'{"tools":[{"type":"shell"}]}'

    def test_mutated_original_dict_does_not_change_seal(self):
        original = self.sealed.payload
        self.request["tools"].append({"type": "shell"})
        self.request["input"][0]["content"] = "FAKE_SECRET"
        proof = verify_fixture(self.sealed, current_binding=self.binding)
        self.assertEqual(proof["payloadSha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(self.sealed.payload, original)

    def test_seal_is_not_permission(self):
        proof = verify_fixture(self.sealed, current_binding=self.binding)
        self.assertTrue(proof["requestShapeValid"])
        self.assertFalse(proof["launchAuthorized"])
        self.assertFalse(proof["productionReady"])
        for key in ("modelCalls", "toolCalls", "hospitalWrites"):
            self.assertEqual(proof[key], 0)
        self.assertNotIn("payload", proof)

    def test_binding_is_request_and_attempt_specific(self):
        self.assertNotEqual(self.sealed.client_request_id, seal_fixture(
            build_request("different text"), binding=self.binding,
            attempt_id="attemptA",
        ).client_request_id)
        self.assertNotEqual(self.sealed.client_request_id, seal_fixture(
            self.request, binding=self.binding,
            attempt_id="attemptB",
        ).client_request_id)
        changed = dict(self.binding, generation=4)
        self.assertNotEqual(self.sealed.client_request_id, seal_fixture(
            build_request("fixture text"), binding=changed,
            attempt_id="attemptA",
        ).client_request_id)

    def test_reject_invalid_request_before_sealing(self):
        for key, value in (
            ("tools", [{"type": "shell"}]),
            ("tool_choice", "auto"),
            ("model", "real-model"),
            ("background", True),
            ("store", True),
        ):
            with self.subTest(key=key):
                bad = build_request("fixture text")
                bad[key] = value
                self.assert_refused(lambda: seal_fixture(
                    bad, binding=self.binding, attempt_id="attemptA"))

    def test_reject_malformed_binding_or_attempt_identity(self):
        for binding, attempt in (
            ({}, "attemptA"),
            (dict(self.binding, generation=0), "attemptA"),
            (self.binding, "attempt with spaces"),
            (self.binding, None),
            (self.binding, "../attempt"),
        ):
            with self.subTest(attempt=str(attempt)):
                self.assert_refused(lambda: seal_fixture(
                    self.request, binding=binding, attempt_id=attempt))

    def test_reject_changed_binding_fields(self):
        for key, value in (
            ("room", "otherRoom"), ("patient", "otherPatient"),
            ("assignment", "foreignAssignment"), ("bed", "foreignBed"),
            ("turnId", "otherTurn"), ("generation", 4),
        ):
            with self.subTest(field=key):
                changed = dict(self.binding, **{key: value})
                self.assert_refused(lambda: verify_fixture(
                    self.sealed, current_binding=changed))

    def test_reject_tampered_payload_even_if_hash_modified(self):
        bad_payload = self.sealed.payload.replace(b"fixture text", b"altered text")
        self.assert_refused(lambda: verify_fixture(
            replace(self.sealed, payload=bad_payload), current_binding=self.binding))
        self.assert_refused(lambda: verify_fixture(
            replace(self.sealed, payload=bad_payload,
                    payload_sha256=hashlib.sha256(bad_payload).hexdigest()),
            current_binding=self.binding))

    def test_reject_tampered_request_identity(self):
        for change in (
            {"client_request_id": "b37b." + "0"*64},
            {"attempt_id": "attemptB"},
            {"binding_json": '{"wrong":"room"}'},
            {"payload_sha256": "0"*64},
        ):
            with self.subTest(change=str(change)[:30]):
                self.assert_refused(lambda: verify_fixture(
                    replace(self.sealed, **change), current_binding=self.binding))

    def test_reject_noncanonical_bytes_even_with_rebuilt_hash(self):
        alternative = json.dumps(
            self.request, indent=2, sort_keys=True,
        ).encode("ascii")
        forged = replace(
            self.sealed, payload=alternative,
            payload_sha256=hashlib.sha256(alternative).hexdigest(),
        )
        self.assert_refused(lambda: verify_fixture(
            forged, current_binding=self.binding))

    def test_reject_wrong_seal_type(self):
        self.assert_refused(lambda: verify_fixture(
            {"payload": self.sealed.payload}, current_binding=self.binding))

    def test_reservation_persists_derived_id_in_b29(self):
        reserved = self.reserve()
        self.assertEqual(reserved["state"], "RESERVED")
        ledger_state = self.ledger.state(self.sealed.attempt_id)
        self.assertEqual(ledger_state["clientRequestId"],
                         self.sealed.client_request_id)
        self.assertFalse(reserved["launchAuthorized"])

    def test_positive_mock_handoff_has_no_actual_sender(self):
        self.reserve()
        observed = self.handoff()
        self.assertEqual(observed["state"], "SUBMISSION_UNCONFIRMED")
        self.assertEqual(observed["transport"], "MOCK_ONLY_NO_SENDER")
        self.assertEqual(observed["payloadSha256"], self.sealed.payload_sha256)
        self.assertFalse(observed["remoteDeliveryObserved"])
        self.assertFalse(observed["remoteStopVerified"])
        self.assertFalse(observed["launchAuthorized"])
        self.assertFalse(observed["retryAuthorized"])
        self.assertEqual(observed["modelCalls"], 0)

    def test_handoff_refuses_unreserved_attempt(self):
        self.assert_refused(lambda: self.handoff())

    def test_handoff_refuses_swapped_or_reencoded_bytes(self):
        self.reserve()
        for fake_sent in (
            self.sealed.payload.replace(b"fixture text", b"altered text"),
            json.dumps(self.request, indent=1).encode("ascii"),
            b"{}", b"", bytearray(self.sealed.payload), "string not bytes",
        ):
            with self.subTest(raw=repr(fake_sent)[:35]):
                self.assert_refused(lambda: self.handoff(observed_bytes=fake_sent))
        self.assertEqual(self.ledger.state(self.sealed.attempt_id)["state"],
                         "RESERVED")

    def test_handoff_refuses_replay(self):
        self.reserve()
        self.handoff()
        self.assert_refused(lambda: self.handoff())

    def test_reserve_is_idempotent_but_not_resend_authorization(self):
        self.reserve()
        again = self.reserve()
        self.assertEqual(again["state"], "RESERVED")
        self.handoff()
        again = self.reserve()
        self.assertEqual(again["state"], "SUBMISSION_UNCONFIRMED")
        self.assertFalse(again["launchAuthorized"])
        self.assert_refused(lambda: self.handoff())

    def test_b29_rejects_attempt_rebound_to_different_body(self):
        self.reserve()
        other = seal_fixture(build_request("other body"),
                             binding=self.binding, attempt_id="attemptA")
        self.assert_refused(lambda: self.reserve(other))
        self.assertEqual(self.ledger.state("attemptA")["clientRequestId"],
                         self.sealed.client_request_id)

    def test_b29_rejects_pre_submission_cancelled_attempt(self):
        self.reserve()
        self.ledger.cancel("attemptA")
        self.assert_refused(lambda: self.handoff())

    def test_b29_rejects_revoked_authority(self):
        self.reserve()
        changed = dict(self.binding, generation=4)
        self.ledger.revoke_if_changed("attemptA", changed)
        self.assert_refused(lambda: self.handoff())

    def test_caller_supplied_stale_binding_fails_before_transition(self):
        self.reserve()
        changed = dict(self.binding, bed="otherBed")
        self.assert_refused(lambda: mock_handoff(
            self.ledger, self.sealed, current_binding=changed))
        self.assertEqual(self.ledger.state("attemptA")["state"], "RESERVED")

    def test_wrong_ledger_is_not_accepted(self):
        self.assert_refused(lambda: reserve_mock(
            object(), self.sealed, scope="scopeA", units=3,
            current_binding=self.binding))
        self.assert_refused(lambda: mock_handoff(
            object(), self.sealed, current_binding=self.binding))

    def test_never_echoes_prompt_in_safe_receipts(self):
        self.reserve()
        recorded = self.handoff()
        combined = json.dumps(recorded)
        self.assertNotIn("fixture text", combined)
        self.assertNotIn("input", combined)

    def test_no_network_subprocess_or_sdk(self):
        with mock.patch.object(socket, "create_connection",
                               side_effect=AssertionError("NETWORK")), \
             mock.patch.object(subprocess, "Popen",
                               side_effect=AssertionError("NATIVE")):
            self.reserve()
            self.handoff()
        self.assertNotIn("openai", sys.modules)

    def test_real_dispatch_always_refuses(self):
        self.assert_refused(lambda: require_real_dispatch(self.sealed))


if __name__ == "__main__":
    unittest.main()
