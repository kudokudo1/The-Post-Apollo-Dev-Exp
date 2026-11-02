#!/usr/bin/env python3
"""B38-D: B38-C policy checks are required at BOTH fake sender boundaries."""
import copy
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import seal_fixture
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture
from px_s3_b38b_trusted_sender_mock import MockTrustedSender, Refused

BINDING = dict(room="fake-room", patient="fake-patient", assignment="fake-assignment",
               bed="fake-bed", turnId="fake-turn", generation=11)
POLICY_MODULE = "px_s3_b38b_trusted_sender_mock"


class DefaultPolicyIntegration(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.conn.close)
        self.atomic = AtomicOfflineFixture(self.conn, TestOnlyEvidenceIssuer())
        self.atomic.configure_mock_budget("fake-budget", 10)
        self.sealed = seal_fixture(
            build_request("fake-private-prompt"),
            binding=BINDING, attempt_id="fakeAttemptB38D",
        )
        self.atomic.register_mock(
            self.sealed, scope="fake-budget", units=1,
            current_binding=BINDING,
        )
        self.sender = MockTrustedSender(BINDING)

    def status(self):
        return self.atomic.ledger.state(self.sealed.attempt_id)["state"]

    def denied(self, code, fn):
        with self.assertRaises(Refused) as cm:
            fn()
        self.assertEqual(str(cm.exception), "B38B_REFUSED_" + code)
        self.assertNotIn("fake-private-prompt", str(cm.exception))
        self.assertEqual(self.sender.fake_handoffs, 0)
        self.assertEqual(self.status(), "RESERVED")

    def bad_policy(self):
        from px_s3_b38c_transport_policy_fixture import default_fake_manifest
        m = default_fake_manifest()
        m["credentials"]["hostEnvInherited"] = True
        return m

    def test_valid_policy_is_checked_before_one_fake_handoff(self):
        permit = self.sender.prepare_mock(self.atomic, self.sealed)
        from px_s3_b38c_transport_policy_fixture import OfflinePlan
        self.assertIs(type(permit.policy_plan), OfflinePlan)
        reply = self.sender.send_mock(self.atomic, self.sealed, permit)
        self.assertFalse(reply.real_transport_used)
        self.assertFalse(reply.production_ready)
        self.assertEqual(self.sender.fake_handoffs, 1)
        self.assertEqual(self.status(), "SUBMISSION_UNCONFIRMED")

    def test_disallowed_host_environment_blocks_prepare(self):
        with mock.patch(POLICY_MODULE + ".default_fake_manifest", side_effect=self.bad_policy):
            self.denied("B38C_POLICY_REFUSED",
                        lambda: self.sender.prepare_mock(self.atomic, self.sealed))

    def test_disallowed_host_environment_after_queue_blocks_send(self):
        ticket = self.sender.prepare_mock(self.atomic, self.sealed)
        with mock.patch(POLICY_MODULE + ".default_fake_manifest", side_effect=self.bad_policy):
            self.denied("B38C_POLICY_REFUSED",
                        lambda: self.sender.send_mock(self.atomic, self.sealed, ticket))

    def test_changed_but_allowed_policy_after_queue_blocks_send(self):
        from px_s3_b38c_transport_policy_fixture import default_fake_manifest
        ticket = self.sender.prepare_mock(self.atomic, self.sealed)
        m = default_fake_manifest()
        m["environment"]["names"] = ["LANG", "LC_ALL", "TZ"]
        with mock.patch(POLICY_MODULE + ".default_fake_manifest", return_value=m):
            self.denied("B38C_POLICY_REFUSED",
                        lambda: self.sender.send_mock(self.atomic, self.sealed, ticket))

    def test_bad_policy_does_not_consume_budget_or_submit(self):
        before = self.atomic.ledger.budget("fake-budget")
        with mock.patch(POLICY_MODULE + ".default_fake_manifest", side_effect=self.bad_policy):
            self.denied("B38C_POLICY_REFUSED",
                        lambda: self.sender.prepare_mock(self.atomic, self.sealed))
        self.assertEqual(self.atomic.ledger.budget("fake-budget"), before)

    def test_policy_failure_after_queue_does_not_lose_recovery_identity(self):
        ticket = self.sender.prepare_mock(self.atomic, self.sealed)
        with mock.patch(POLICY_MODULE + ".default_fake_manifest", side_effect=self.bad_policy):
            self.denied("B38C_POLICY_REFUSED",
                        lambda: self.sender.send_mock(self.atomic, self.sealed, ticket))
        recovery = self.atomic.recover_mock(self.sealed, current_binding=BINDING)
        self.assertEqual(recovery["state"], "RESERVED")
        self.assertFalse(recovery["retryAuthorized"])

    def test_missing_or_wrong_policy_result_denied(self):
        ticket = self.sender.prepare_mock(self.atomic, self.sealed)
        for value in ({"decision": "REAL_ALLOWED", "transportReady": False,
                       "launchAuthorized": False},
                      {"decision": "OFFLINE_SHAPE_ONLY", "transportReady": True,
                       "launchAuthorized": False},
                      {"decision": "OFFLINE_SHAPE_ONLY", "transportReady": False,
                       "launchAuthorized": True},
                      {}):
            # Every time requires a fresh issued ticket, failed permits are consumed.
            with mock.patch(POLICY_MODULE + ".recheck_fake_plan", return_value=value):
                self.denied("B38C_POLICY_RESULT_INVALID",
                            lambda: self.sender.send_mock(self.atomic, self.sealed, ticket))
            ticket = self.sender.prepare_mock(self.atomic, self.sealed)

    def test_b38c_check_called_for_prepare_and_send(self):
        from px_s3_b38c_transport_policy_fixture import (
            prepare_fake_plan, recheck_fake_plan,
        )
        with (mock.patch(POLICY_MODULE + ".prepare_fake_plan", wraps=prepare_fake_plan) as p,
              mock.patch(POLICY_MODULE + ".recheck_fake_plan", wraps=recheck_fake_plan) as q):
            ticket = self.sender.prepare_mock(self.atomic, self.sealed)
            self.sender.send_mock(self.atomic, self.sealed, ticket)
            self.assertEqual(p.call_count, 1)
            self.assertEqual(q.call_count, 1)

    def test_unchanged_fail_closed_real_sender(self):
        from px_s3_b38b_trusted_sender_mock import require_real_sender
        with self.assertRaisesRegex(Refused, "NO_AUTHENTICATED_SENDER"):
            require_real_sender(api_key="fake-not-real")
        self.assertEqual(self.sender.fake_handoffs, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
