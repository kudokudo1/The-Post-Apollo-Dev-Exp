#!/usr/bin/env python3
"""B38-C policy-shape integration into B38-B default fake sender, offline only."""
from dataclasses import replace
import copy
import sqlite3
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import px_s3_b38b_trusted_sender_mock as sender_module
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import seal_fixture
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture
from px_s3_b38a_model_only_mock_client import FakeTextStream, exchange_mock
from px_s3_b38b_trusted_sender_mock import (
    MockTrustedSender, Refused as SenderRefused, require_real_sender,
)
from px_s3_b38c_transport_policy_fixture import (
    OfflinePlan, default_fake_manifest, require_real_transport,
    Refused as PolicyRefused,
)

BINDING = {
    "room": "policyRoom", "patient": "policyPatient",
    "assignment": "policyAssignment", "bed": "policyBed",
    "turnId": "policyTurn", "generation": 4,
}


class B38CDefaultSenderGateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="px-b38c-default-")
        self.addCleanup(temp.cleanup)
        self.db_path = Path(temp.name) / "mock.sqlite3"
        self.conn = sqlite3.connect(self.db_path, isolation_level=None)
        self.addCleanup(self.conn.close)
        self.binding = dict(BINDING)
        self.atomic = AtomicOfflineFixture(self.conn, TestOnlyEvidenceIssuer())
        self.atomic.configure_mock_budget("mockScope", 100)
        self.sealed = seal_fixture(
            build_request("PRIVATE_POLICY_TEST_PROMPT"),
            binding=self.binding, attempt_id="mockAttempt",
        )
        self.atomic.register_mock(
            self.sealed, scope="mockScope", units=5,
            current_binding=self.binding,
        )
        self.manifest = default_fake_manifest()
        self.sender = MockTrustedSender(
            self.binding, mock_manifest=self.manifest,
        )

    def state(self):
        return self.atomic.ledger.state("mockAttempt")["state"]

    def hold(self):
        return self.atomic.ledger.budget("mockScope")["reserved_units"]

    def check_denied(self, operation, code):
        with self.assertRaisesRegex(SenderRefused, "B38B_REFUSED_" + code) as cm:
            operation()
        self.assertNotIn("PRIVATE_POLICY_TEST_PROMPT", str(cm.exception))
        self.assertEqual(self.state(), "RESERVED")
        self.assertEqual(self.sender.fake_handoffs, 0)
        self.assertEqual(self.hold(), 5)

    def prepare(self):
        return self.sender.prepare_mock(self.atomic, self.sealed)

    def send(self, permit):
        return self.sender.send_mock(self.atomic, self.sealed, permit)

    def test_implicit_default_manifest_is_mandatory_and_inert(self):
        sender = MockTrustedSender(self.binding)
        with patch.object(
            sender_module, "prepare_fake_plan",
            wraps=sender_module.prepare_fake_plan,
        ) as prep, patch.object(
            sender_module, "recheck_fake_plan",
            wraps=sender_module.recheck_fake_plan,
        ) as recheck:
            permit = sender.prepare_mock(self.atomic, self.sealed)
            self.assertEqual(type(permit.policy_plan), OfflinePlan)
            reply = sender.send_mock(self.atomic, self.sealed, permit)
        self.assertEqual(prep.call_count, 1)
        self.assertEqual(recheck.call_count, 1)
        self.assertFalse(reply.real_model_called)
        self.assertFalse(reply.real_transport_used)
        self.assertFalse(reply.production_ready)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")

    def test_valid_explicit_manifest_plan_binds_request_and_bytes(self):
        permit = self.prepare()
        plan = permit.policy_plan
        self.assertIs(type(plan), OfflinePlan)
        self.assertEqual(plan.request_id, self.sealed.client_request_id)
        self.assertEqual(plan.payload_sha256, self.sealed.payload_sha256)
        self.assertEqual(plan.binding_json, self.sealed.binding_json)
        self.assertGreater(len(plan.manifest_bytes), 0)
        reply = self.send(permit)
        self.assertIn("synthetic text", reply.text)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        inspected = self.sender.inspect_mock()
        for key in (
            "credentialBoundaryCertified", "networkPolicyEnforced",
            "osIsolationVerified", "hospitalAuthorityVerified",
            "transportReady", "launchAuthorized", "productionReady",
        ):
            self.assertIs(inspected[key], False)

    def test_secret_fields_denied_at_prepare(self):
        for group, key, value in (
            ("credentials", "source", "API_KEY"),
            ("credentials", "hostEnvInherited", True),
            ("credentials", "hostHomeMounted", True),
            ("credentials", "argvSecret", True),
            ("credentials", "fdsInherited", True),
            ("credentials", "socketsInherited", True),
            ("credentials", "toolSecret", True),
        ):
            with self.subTest(key=key):
                self.manifest[group][key] = value
                self.check_denied(self.prepare, "FAKE_POLICY_PREPARE_REFUSED")
                self.manifest = default_fake_manifest()
                self.sender = MockTrustedSender(
                    self.binding, mock_manifest=self.manifest,
                )

    def test_network_egress_denied_at_prepare(self):
        for key, value in (
            ("mode", "HTTPS"),
            ("destination", "example.com"),
            ("tcpEnabled", True),
            ("proxy", True),
            ("redirects", True),
            ("ambientDNS", True),
            ("toolEgress", True),
        ):
            with self.subTest(key=key):
                self.manifest["network"][key] = value
                self.check_denied(self.prepare, "FAKE_POLICY_PREPARE_REFUSED")
                self.manifest = default_fake_manifest()
                self.sender = MockTrustedSender(
                    self.binding, mock_manifest=self.manifest,
                )

    def test_native_tool_process_and_broker_denied_at_prepare(self):
        for group, key, value in (
            ("process", "nativeTools", True),
            ("process", "plugins", True),
            ("process", "mcp", True),
            ("process", "executable", "hermes"),
            ("ipc", "brokerAddressVisible", True),
            ("ipc", "modelCanMintGrant", True),
        ):
            with self.subTest(key=key):
                self.manifest[group][key] = value
                self.check_denied(self.prepare, "FAKE_POLICY_PREPARE_REFUSED")
                self.manifest = default_fake_manifest()
                self.sender = MockTrustedSender(
                    self.binding, mock_manifest=self.manifest,
                )

    def test_secret_extra_field_and_bad_env_names_denied(self):
        self.manifest["apiKey"] = "PRIVATE_POLICY_TEST_PROMPT"
        self.check_denied(self.prepare, "FAKE_POLICY_PREPARE_REFUSED")
        del self.manifest["apiKey"]
        self.manifest["environment"]["names"] = ["OPENAI_API_KEY"]
        self.check_denied(self.prepare, "FAKE_POLICY_PREPARE_REFUSED")

    def test_invalid_type_manifest_refused_not_silently_defaulted(self):
        self.sender = MockTrustedSender(self.binding, mock_manifest=[])
        self.check_denied(self.prepare, "FAKE_POLICY_PREPARE_REFUSED")

    def test_mutated_manifest_to_bad_secret_denied_at_send(self):
        permit = self.prepare()
        self.manifest["credentials"]["source"] = "FAKE_SECRET"
        self.check_denied(lambda: self.send(permit), "FAKE_POLICY_RECHECK_REFUSED")

    def test_mutated_manifest_to_network_enabled_denied_at_send(self):
        permit = self.prepare()
        self.manifest["network"]["tcpEnabled"] = True
        self.check_denied(lambda: self.send(permit), "FAKE_POLICY_RECHECK_REFUSED")

    def test_mutated_manifest_to_broker_enabled_denied_at_send(self):
        permit = self.prepare()
        self.manifest["ipc"]["kind"] = "unix-socket"
        self.check_denied(lambda: self.send(permit), "FAKE_POLICY_RECHECK_REFUSED")

    def test_changed_but_valid_manifest_denied_by_snapshot_mismatch(self):
        permit = self.prepare()
        # This environment-name change is legal for a new plan, but not for
        # the already-issued request-bound permit.
        self.manifest["environment"]["names"] = ["LANG", "LC_ALL", "TZ"]
        self.check_denied(lambda: self.send(permit), "FAKE_POLICY_RECHECK_REFUSED")

    def test_replaced_manifest_object_denied_at_send(self):
        permit = self.prepare()
        other = default_fake_manifest()
        other["environment"]["names"] = ["LANG", "LC_ALL", "TZ"]
        self.sender._mock_manifest = other  # explicit in-process tamper fixture
        self.check_denied(lambda: self.send(permit), "FAKE_POLICY_RECHECK_REFUSED")

    def test_tampered_policy_plan_hash_denied_at_send(self):
        permit = self.prepare()
        object.__setattr__(
            permit, "policy_plan",
            replace(permit.policy_plan, manifest_sha256="0" * 64),
        )
        self.check_denied(lambda: self.send(permit), "FAKE_POLICY_RECHECK_REFUSED")

    def test_swapped_request_seal_after_plan_preparation_denied(self):
        permit = self.prepare()
        swapped = replace(self.sealed, client_request_id="fake-other")
        self.check_denied(
            lambda: self.sender.send_mock(self.atomic, swapped, permit),
            "SEALED_REQUEST_INVALID",
        )

    def test_no_policy_recheck_failure_reaches_fake_exchange(self):
        permit = self.prepare()
        self.manifest["network"]["proxy"] = True
        with patch.object(
            sender_module, "exchange_mock",
            side_effect=AssertionError("B38-C policy failed open"),
        ) as exchange:
            self.check_denied(
                lambda: self.send(permit),
                "FAKE_POLICY_RECHECK_REFUSED",
            )
            exchange.assert_not_called()

    def test_recheck_receipt_cannot_claim_real_authority(self):
        permit = self.prepare()
        fake = {
            "decision": "OFFLINE_SHAPE_ONLY",
            "requestShapeValid": True,
            "credentialBoundaryCertified": True,
            "networkPolicyEnforced": False,
            "osIsolationVerified": False,
            "hospitalAuthorityVerified": False,
            "transportReady": False,
            "launchAuthorized": False,
            "productionReady": False,
            "modelCalls": 0,
            "networkCalls": 0,
            "toolCalls": 0,
            "hospitalWrites": 0,
        }
        with patch.object(sender_module, "recheck_fake_plan", return_value=fake):
            self.check_denied(lambda: self.send(permit), "FAKE_POLICY_RECEIPT_INVALID")

    def test_recheck_receipt_cannot_claim_network_calls(self):
        permit = self.prepare()
        fake = {
            "decision": "OFFLINE_SHAPE_ONLY",
            "requestShapeValid": True,
            **{key: False for key in (
                "credentialBoundaryCertified", "networkPolicyEnforced",
                "osIsolationVerified", "hospitalAuthorityVerified",
                "transportReady", "launchAuthorized", "productionReady",
            )},
            "modelCalls": 0, "networkCalls": 1,
            "toolCalls": 0, "hospitalWrites": 0,
        }
        with patch.object(sender_module, "recheck_fake_plan", return_value=fake):
            self.check_denied(lambda: self.send(permit), "FAKE_POLICY_RECEIPT_INVALID")

    def test_prepared_ticket_is_single_use_after_policy_recheck(self):
        permit = self.prepare()
        self.send(permit)
        with self.assertRaisesRegex(SenderRefused, "PERMIT_NOT_ISSUED_OR_REPLAYED"):
            self.send(permit)
        self.assertEqual(self.sender.fake_handoffs, 1)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")

    def test_restart_after_policy_checked_mock_transition_quarantines(self):
        permit = self.prepare()
        self.send(permit)
        self.conn.close()
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        self.addCleanup(conn.close)
        recovered = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
        proof = recovered.recover_mock(
            self.sealed, current_binding=self.binding,
        )
        self.assertEqual(proof["state"], "REMOTE_OUTCOME_UNKNOWN")
        self.assertFalse(proof["retryAuthorized"])
        self.assertEqual(recovered.ledger.budget("mockScope")["reserved_units"], 5)
        other = MockTrustedSender(self.binding)
        with self.assertRaisesRegex(SenderRefused, "FAKE_RESERVATION_MISMATCH"):
            other.prepare_mock(recovered, self.sealed)

    def test_b38a_direct_call_is_outside_b38b_policy_contract(self):
        # Explicit scope limitation: B38-A is not a route through
        # MockTrustedSender. It still requires B37-C atomic identity.
        frame = FakeTextStream(
            request_id=self.sealed.client_request_id,
            offered_bytes=self.sealed.payload,
            frames=(
                b'{"type":"mock.text.delta","seq":0,"text":"fake"}',
                b'{"type":"mock.text.completed","seq":1}',
            ),
        )
        reply = exchange_mock(
            self.atomic, self.sealed,
            current_binding=self.binding, stream=frame,
        )
        self.assertEqual(reply.text, "fake")
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        self.assertFalse(reply.real_transport_used)

    def test_no_native_network_or_real_sender(self):
        permit = self.prepare()
        with patch.object(socket, "create_connection",
                          side_effect=AssertionError("network")), \
             patch.object(subprocess, "Popen",
                          side_effect=AssertionError("subprocess")):
            reply = self.send(permit)
        self.assertFalse(reply.real_model_called)
        self.assertFalse(reply.production_ready)
        with self.assertRaises(SenderRefused):
            require_real_sender()
        with self.assertRaises(PolicyRefused):
            require_real_transport()


if __name__ == "__main__":
    unittest.main(verbosity=2)
