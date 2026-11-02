#!/usr/bin/env python3
"""B38-B fake-only sender refusal suite. No Hermes, HTTP or credentials."""
from dataclasses import FrozenInstanceError, replace
import ast
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import reserve_mock, seal_fixture
from px_s3_b38b_trusted_sender_mock import MockTrustedSender, Refused, require_real_sender

BINDING = {"room": "synthetic-room", "patient": "synthetic-patient",
           "assignment": "synthetic-assignment", "bed": "synthetic-bed",
           "turnId": "synthetic-turn", "generation": 9}


class B38BMockTrustedSenderTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)
        self.atomic = AtomicOfflineFixture(self.db, TestOnlyEvidenceIssuer())
        self.ledger = self.atomic.ledger
        self.atomic.configure_mock_budget("synthetic-budget", 20)
        self.binding = dict(BINDING)
        self.request = build_request("private fake prompt")
        self.sealed = seal_fixture(self.request, binding=self.binding,
                                  attempt_id="syntheticAttempt")
        self.sender = MockTrustedSender(self.binding)
        self.reserve()

    def reserve(self):
        return self.atomic.register_mock(self.sealed, scope="synthetic-budget",
                                         units=2, current_binding=self.binding)

    def prepare(self, *, atomic=None, sealed=None):
        return self.sender.prepare_mock(self.atomic if atomic is None else atomic,
                                        self.sealed if sealed is None else sealed)

    def send(self, permit, *, atomic=None, sealed=None):
        return self.sender.send_mock(self.atomic if atomic is None else atomic,
                                     self.sealed if sealed is None else sealed,
                                     permit)

    def denied(self, reason, operation, reserved=True):
        with self.assertRaises(Refused) as caught:
            operation()
        self.assertEqual(str(caught.exception), "B38B_REFUSED_" + reason)
        self.assertNotIn("private fake prompt", str(caught.exception))
        self.assertNotIn("B38B_SENTINEL_NOT_A_REAL_CREDENTIAL", str(caught.exception))
        self.assertEqual(self.sender.fake_handoffs, 0)
        if reserved:
            self.assertEqual(self.ledger.state(self.sealed.attempt_id)["state"],
                             "RESERVED")

    def test_positive_one_shot_is_inert_text(self):
        reply = self.send(self.prepare())
        self.assertEqual(reply.text, "B38B synthetic text, never a provider response")
        self.assertFalse(reply.production_ready)
        self.assertFalse(reply.real_transport_used)
        self.assertFalse(reply.real_model_called)
        self.assertEqual(self.sender.fake_handoffs, 1)
        self.assertEqual(self.ledger.state(self.sealed.attempt_id)["state"],
                         "SUBMISSION_UNCONFIRMED")
        metrics = self.sender.inspect_mock()
        self.assertEqual(metrics["fakeHandoffs"], 1)
        for name in ("realNetworkCalls", "realProviderCalls"):
            self.assertEqual(metrics[name], 0)
        for name in ("credentialBoundaryCertified", "launchAuthorized", "productionReady"):
            self.assertIs(metrics[name], False)
        self.assertNotIn("B38B_SENTINEL_NOT_A_REAL_CREDENTIAL", repr(reply))
        self.assertNotIn("B38B_SENTINEL_NOT_A_REAL_CREDENTIAL", repr(metrics))

    def test_real_sender_unconditionally_refused(self):
        self.denied("NO_AUTHENTICATED_SENDER",
                    lambda: require_real_sender(self.sealed, api_key="fake"))

    def test_non_fixture_ledger_denied(self):
        self.denied("B37C_ATOMIC_FIXTURE_REQUIRED", lambda: self.prepare(atomic={}))

    def test_non_fixture_seal_denied(self):
        self.denied("SEAL_TYPE", lambda: self.prepare(sealed={}))

    def test_forged_seal_denied(self):
        altered = replace(self.sealed, payload=b'{"tools":[{"type":"shell"}]}')
        self.denied("SEALED_REQUEST_INVALID", lambda: self.prepare(sealed=altered))

    def test_mismatched_request_after_prepare(self):
        permit = self.prepare()
        other = replace(self.sealed, client_request_id="foreign-request")
        self.denied("SEALED_REQUEST_INVALID", lambda: self.send(permit, sealed=other))

    def test_missing_reservation_denied(self):
        second = seal_fixture(build_request("new prompt"), binding=self.binding,
                              attempt_id="differentAttempt")
        self.denied("FAKE_RESERVATION_REQUIRED", lambda: self.prepare(sealed=second))

    def test_invalid_binding_denied(self):
        for bad in ({}, dict(self.binding, generation=True),
                    dict(self.binding, room="bad space")):
            with self.subTest(bad=repr(bad)[:30]):
                self.denied("BINDING_INVALID", lambda: MockTrustedSender(bad))

    def test_paused_before_prepare_denied(self):
        self.sender.pause()
        self.denied("AUTHORITY_PAUSED", lambda: self.prepare())

    def test_unready_before_prepare_denied(self):
        self.sender.set_mock_ready(False)
        self.denied("MOCK_SENDER_UNAVAILABLE", lambda: self.prepare())

    def test_readiness_must_be_boolean(self):
        self.denied("READINESS_INVALID",
                    lambda: self.sender.set_mock_ready("yes"))

    def test_pause_after_issuance_denied(self):
        permit = self.prepare()
        self.sender.pause()
        self.denied("STALE_PERMIT", lambda: self.send(permit))

    def test_revocation_after_issuance_denied(self):
        permit = self.prepare()
        self.sender.revoke()
        self.denied("STALE_PERMIT", lambda: self.send(permit))

    def test_assignment_change_after_issuance_denied(self):
        permit = self.prepare()
        replacement = dict(self.binding, generation=10, assignment="other-assignment")
        self.sender.change_binding(replacement)
        self.denied("STALE_PERMIT", lambda: self.send(permit))

    def test_restart_after_issuance_denied(self):
        permit = self.prepare()
        self.sender.restart()
        self.denied("STALE_PERMIT", lambda: self.send(permit))
        self.denied("MOCK_SENDER_UNAVAILABLE", lambda: self.prepare())

    def test_invalid_binding_update_refused(self):
        self.denied("BINDING_INVALID",
                    lambda: self.sender.change_binding(dict(self.binding, generation="bad")))

    def test_readiness_epoch_change_invalidates_queued_permit(self):
        permit = self.prepare()
        self.sender.set_mock_ready(False)
        self.denied("STALE_PERMIT", lambda: self.send(permit))

    def test_forged_copy_is_not_granted(self):
        permit = self.prepare()
        self.denied("PERMIT_NOT_ISSUED_OR_REPLAYED", lambda: self.send(replace(permit)))

    def test_wrong_ticket_type_denied(self):
        for value in (None, {}, "ticket", 1, True):
            with self.subTest(type=type(value).__name__):
                self.denied("PERMIT_TYPE", lambda: self.send(value))

    def test_arbitrary_stream_cannot_replace_sender(self):
        permit = self.prepare()
        self.denied("PERMIT_TYPE",
                    lambda: self.send({"frames": [b'{"type":"mcp"}'], "permit": permit}))

    def test_second_send_of_single_ticket_denied(self):
        permit = self.prepare()
        self.send(permit)
        with self.assertRaisesRegex(Refused, "PERMIT_NOT_ISSUED_OR_REPLAYED"):
            self.send(permit)
        self.assertEqual(self.sender.fake_handoffs, 1)

    def test_separately_queued_ticket_cannot_resubmit_same_attempt(self):
        first = self.prepare()
        second = self.prepare()
        self.send(first)
        with self.assertRaisesRegex(Refused, "FAKE_RESERVATION_MISMATCH"):
            self.send(second)
        self.assertEqual(self.sender.fake_handoffs, 1)

    def test_fake_ledger_must_still_exist_at_send(self):
        ticket = self.prepare()
        self.denied("B37C_ATOMIC_FIXTURE_REQUIRED", lambda: self.send(ticket, atomic={}))

    def test_mutated_input_still_uses_fixed_seal(self):
        old = self.sealed.payload
        self.request["tools"].append({"type": "terminal"})
        self.request["input"][0]["content"] = "changed"
        reply = self.send(self.prepare())
        self.assertEqual(self.sealed.payload, old)
        self.assertIn("synthetic text", reply.text)

    def test_reply_data_is_frozen(self):
        reply = self.send(self.prepare())
        with self.assertRaises(FrozenInstanceError):
            reply.real_model_called = True

    def test_no_native_network_or_provider_dependencies(self):
        text = (ROOT / "bin" / "px_s3_b38b_trusted_sender_mock.py").read_text()
        tree = ast.parse(text)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(n.name.split(".")[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        self.assertFalse(names & {
            "socket", "subprocess", "requests", "urllib", "http", "httpx",
            "aiohttp", "openai", "hermes_cli", "litellm", "run_agent",
            "model_tools", "tools", "ctypes",
        })
        for token in ("Popen(", "os.system(", "eval(", "exec(", "create_connection("):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
