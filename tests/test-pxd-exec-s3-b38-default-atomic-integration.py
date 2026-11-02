#!/usr/bin/env python3
"""B37-C/B38 default-path fake integration. No monkeypatch or provider I/O."""
from dataclasses import replace
import ast
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import reserve_mock, seal_fixture
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture
from px_s3_b38a_model_only_mock_client import (
    FakeTextStream, Refused as B38ARefused, exchange_mock,
)
from px_s3_b38b_trusted_sender_mock import (
    MockTrustedSender, Refused as B38BRefused,
)

BINDING = dict(room="fixture-room", patient="fixture-patient",
               assignment="fixture-assignment", bed="fixture-bed",
               turnId="fixture-turn", generation=7)


class B37CB38AtomicDefaultTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="b38-atomic-fixture-")
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "fixture.sqlite3"
        self.conn = sqlite3.connect(self.db_path, isolation_level=None)
        self.addCleanup(self.conn.close)
        self.binding = dict(BINDING)
        self.atomic = AtomicOfflineFixture(self.conn, TestOnlyEvidenceIssuer())
        self.atomic.configure_mock_budget("fixture-budget", 30)
        self.sealed = seal_fixture(build_request("fixture prompt private"),
                                   binding=self.binding, attempt_id="fixtureAttempt")
        self.sender = MockTrustedSender(self.binding)

    def register(self):
        return self.atomic.register_mock(
            self.sealed, scope="fixture-budget", units=2,
            current_binding=self.binding,
        )

    def reserve_legacy_only(self):
        """Intentionally create the old B29 row without B37-C hash."""
        return reserve_mock(
            self.atomic.ledger, self.sealed,
            scope="fixture-budget", units=2, current_binding=self.binding,
        )

    def frames(self, offered=None):
        return FakeTextStream(
            request_id=self.sealed.client_request_id,
            offered_bytes=self.sealed.payload if offered is None else offered,
            frames=(b'{"type":"mock.text.delta","seq":0,"text":"fake text"}',
                    b'{"type":"mock.text.completed","seq":1}'),
        )

    def direct(self, atomic=None, stream=None):
        return exchange_mock(
            self.atomic if atomic is None else atomic, self.sealed,
            current_binding=self.binding,
            stream=self.frames() if stream is None else stream,
        )

    def assert_reserved(self):
        self.assertEqual(self.atomic.ledger.state(self.sealed.attempt_id)["state"],
                         "RESERVED")

    def test_direct_b38a_requires_b37c_registration(self):
        self.reserve_legacy_only()
        with self.assertRaisesRegex(B38ARefused, "B37C_ATOMIC_HANDOFF_DENIED"):
            self.direct()
        self.assert_reserved()

    def test_sender_b38b_cannot_bypass_missing_hash(self):
        self.reserve_legacy_only()
        token = self.sender.prepare_mock(self.atomic, self.sealed)
        with self.assertRaisesRegex(B38BRefused, "FAKE_HANDOFF_REFUSED"):
            self.sender.send_mock(self.atomic, self.sealed, token)
        self.assert_reserved()
        self.assertEqual(self.sender.fake_handoffs, 0)

    def test_direct_b38a_refuses_corrupt_registered_hash(self):
        self.register()
        self.conn.execute("DROP TRIGGER b37c_fixture_request_immutable")
        self.conn.execute(
            "UPDATE b29_fixture_attempts SET b37c_payload_sha256=? WHERE attempt_id=?",
            ("0" * 64, self.sealed.attempt_id),
        )
        with self.assertRaisesRegex(B38ARefused, "B37C_ATOMIC_HANDOFF_DENIED"):
            self.direct()
        self.assert_reserved()

    def test_b38b_refuses_corrupt_registered_hash(self):
        self.register()
        token = self.sender.prepare_mock(self.atomic, self.sealed)
        self.conn.execute("DROP TRIGGER b37c_fixture_request_immutable")
        self.conn.execute(
            "UPDATE b29_fixture_attempts SET b37c_payload_sha256=? WHERE attempt_id=?",
            ("0" * 64, self.sealed.attempt_id),
        )
        with self.assertRaisesRegex(B38BRefused, "FAKE_HANDOFF_REFUSED"):
            self.sender.send_mock(self.atomic, self.sealed, token)
        self.assert_reserved()
        self.assertEqual(self.sender.fake_handoffs, 0)

    def test_legacy_ledger_cannot_replace_atomic_default(self):
        self.register()
        with self.assertRaisesRegex(B38ARefused, "B37C_ATOMIC_FIXTURE_REQUIRED"):
            self.direct(atomic=self.atomic.ledger)
        with self.assertRaisesRegex(B38BRefused, "B37C_ATOMIC_FIXTURE_REQUIRED"):
            self.sender.prepare_mock(self.atomic.ledger, self.sealed)
        self.assert_reserved()

    def test_direct_valid_request_uses_b37c_atomic_transition(self):
        self.register()
        reply = self.direct()
        self.assertEqual(reply.text, "fake text")
        self.assertFalse(reply.real_transport_used)
        self.assertFalse(reply.production_ready)
        self.assertEqual(self.atomic.ledger.state(self.sealed.attempt_id)["state"],
                         "SUBMISSION_UNCONFIRMED")

    def test_sender_valid_request_uses_same_atomic_transition(self):
        self.register()
        ticket = self.sender.prepare_mock(self.atomic, self.sealed)
        reply = self.sender.send_mock(self.atomic, self.sealed, ticket)
        self.assertIn("synthetic text", reply.text)
        self.assertEqual(self.sender.fake_handoffs, 1)
        self.assertEqual(self.atomic.ledger.state(self.sealed.attempt_id)["state"],
                         "SUBMISSION_UNCONFIRMED")

    def test_duplicate_direct_exchange_never_retransitions(self):
        self.register()
        self.direct()
        with self.assertRaisesRegex(B38ARefused, "B37C_ATOMIC_HANDOFF_DENIED"):
            self.direct()
        self.assertEqual(self.atomic.ledger.state(self.sealed.attempt_id)["state"],
                         "SUBMISSION_UNCONFIRMED")

    def test_independent_queued_permits_cannot_repeat_atomic_handoff(self):
        self.register()
        first = self.sender.prepare_mock(self.atomic, self.sealed)
        second = self.sender.prepare_mock(self.atomic, self.sealed)
        self.sender.send_mock(self.atomic, self.sealed, first)
        with self.assertRaisesRegex(B38BRefused, "FAKE_RESERVATION_MISMATCH"):
            self.sender.send_mock(self.atomic, self.sealed, second)
        self.assertEqual(self.sender.fake_handoffs, 1)

    def test_bad_frame_refused_before_any_atomic_transition(self):
        self.register()
        stream = FakeTextStream(
            request_id=self.sealed.client_request_id,
            offered_bytes=self.sealed.payload,
            frames=(b'{"type":"mock.tool.call","seq":0,"command":"run"}',
                    b'{"type":"mock.text.completed","seq":1}'),
        )
        with self.assertRaisesRegex(B38ARefused, "NON_TEXT_EVENT"):
            self.direct(stream=stream)
        self.assert_reserved()

    def test_request_byte_drift_refused_before_transition(self):
        self.register()
        with self.assertRaisesRegex(B38ARefused, "OFFERED_BYTES_MISMATCH"):
            self.direct(stream=self.frames(offered=b'{"tools":[]}'))
        self.assert_reserved()

    def test_crash_recovery_quarantines_unknown_without_resend(self):
        self.register()
        self.sender.send_mock(
            self.atomic, self.sealed,
            self.sender.prepare_mock(self.atomic, self.sealed),
        )
        self.conn.close()
        reopened = sqlite3.connect(self.db_path, isolation_level=None)
        self.addCleanup(reopened.close)
        replacement = AtomicOfflineFixture(reopened, TestOnlyEvidenceIssuer())
        recovery = replacement.recover_mock(self.sealed, current_binding=self.binding)
        self.assertEqual(recovery["state"], "REMOTE_OUTCOME_UNKNOWN")
        self.assertFalse(recovery["retryAuthorized"])
        with self.assertRaisesRegex(B38BRefused, "FAKE_RESERVATION_MISMATCH"):
            self.sender.prepare_mock(replacement, self.sealed)
        self.assertEqual(self.sender.fake_handoffs, 1)

    def test_stale_permit_refused_without_submission(self):
        self.register()
        ticket = self.sender.prepare_mock(self.atomic, self.sealed)
        self.sender.pause()
        with self.assertRaisesRegex(B38BRefused, "STALE_PERMIT"):
            self.sender.send_mock(self.atomic, self.sealed, ticket)
        self.assert_reserved()

    def test_default_source_has_no_legacy_b37b_handoff_call(self):
        source = (ROOT / "bin" / "px_s3_b38a_model_only_mock_client.py").read_text()
        tree = ast.parse(source)
        called = [
            n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        self.assertNotIn("mock_handoff", called)
        from_names = [
            a.name for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) for a in n.names
        ]
        self.assertNotIn("mock_handoff", from_names)
        self.assertIn("AtomicOfflineFixture", from_names)

    def test_invalid_seal_is_not_laundered_by_atomic_fixture(self):
        self.register()
        altered = replace(self.sealed, payload=b'{"tools":[{"type":"shell"}]}')
        stream = self.frames()
        with self.assertRaisesRegex(B38ARefused, "SEALED_REQUEST_INVALID"):
            exchange_mock(self.atomic, altered, current_binding=self.binding,
                          stream=stream)
        self.assert_reserved()


if __name__ == "__main__":
    unittest.main(verbosity=2)
