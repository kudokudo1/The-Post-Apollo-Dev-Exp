#!/usr/bin/env python3
"""B34: verify the *landed* B24-B33 tree, not pinned draft checkouts.

Offline disposable regression only; no credentials, provider, tool dispatch,
model request, live Hospital database or local-machine interaction.
"""
import importlib
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
sys.path.insert(0, str(BIN))
from px_s3_b33_durable_observation import DurableObservedFixture
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b29_transport_ledger import Refused
from px_s3_b32_staged_evidence import StagedOfflineEvidenceTurn
from px_s3_b30_integrated_fixture import OfflineIntegratedTurn

# Reuse the accepted B33 SSE-shaped *test sample*, not its fixture engine.
spec = importlib.util.spec_from_file_location(
    "b34_b33_test_samples",
    ROOT / "tests" / "test-pxd-exec-s3-b33-durable-observation.py",
)
samples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(samples)
BIND = dict(samples.BIND)


class B34MergedMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="b34-merged-offline-")
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "fixture.sqlite3"
        self.conn = sqlite3.connect(self.db, isolation_level=None, timeout=2)
        self.addCleanup(self.conn.close)
        self.issuer = TestOnlyEvidenceIssuer()
        self.turn = DurableObservedFixture(self.conn, self.issuer)
        self.turn.configure_mock_budget("B34_scope", 100)

    def reopen(self):
        self.conn.close()
        self.conn = sqlite3.connect(self.db, isolation_level=None, timeout=2)
        self.addCleanup(self.conn.close)
        self.issuer = TestOnlyEvidenceIssuer()
        self.turn = DurableObservedFixture(self.conn, self.issuer)

    def started(self, attempt="B34_attempt", client="B34_client",
                binding=BIND, units=30):
        self.turn.reserve(attempt_id=attempt, client_request_id=client,
                          scope="B34_scope", binding=binding, units=units)
        self.turn.submit_mock(attempt, binding)

    def observe(self, events=None):
        return self.turn.observe_mock(
            "B34_attempt", BIND,
            samples.text_events() if events is None else events,
        )

    def witness(self, events=None, **kw):
        events = samples.text_events() if events is None else events
        args = dict(attempt_id="B34_attempt", client_request_id="B34_client",
                    binding=BIND, response_id="respA", events=events,
                    usage_units=8, status="completed")
        args.update(kw)
        return self.issuer.issue_test_only(**args)

    def settle(self, evidence, events=None, binding=BIND):
        return self.turn.settle_mock(
            "B34_attempt", binding,
            samples.text_events() if events is None else events, evidence,
        )

    def budget(self):
        return self.turn.ledger.budget("B34_scope")

    def test_all_merged_runtime_modules_resolve_to_one_checkout(self):
        # This catches PYTHONPATH overrides and accidentally executed
        # historical PR files when running post-merge verification.
        for name in (
                "px_s3_provider_admission",
                "px_s3_b25_responses_fixture",
                "px_s3_b27_stream_compat",
                "px_s3_b29_transport_ledger",
                "px_s3_b30_integrated_fixture",
                "px_s3_b31_evidence_boundary",
                "px_s3_b32_staged_evidence",
                "px_s3_b33_durable_observation"):
            with self.subTest(module=name):
                module = importlib.import_module(name)
                self.assertEqual(Path(module.__file__).resolve(),
                                 (BIN / (name + ".py")).resolve())

    def test_staged_modules_share_exact_class_implementations(self):
        import px_s3_b33_durable_observation as b33
        import px_s3_b32_staged_evidence as b32
        import px_s3_b31_evidence_boundary as b31
        import px_s3_b30_integrated_fixture as b30
        import px_s3_b29_transport_ledger as b29
        self.assertIs(b33.StagedOfflineEvidenceTurn, b32.StagedOfflineEvidenceTurn)
        self.assertIs(b32.OfflineIntegratedTurn, b30.OfflineIntegratedTurn)
        self.assertIs(b32.OfflineEvidenceBoundary, b31.OfflineEvidenceBoundary)
        self.assertIs(b30.SyntheticLedger, b29.SyntheticLedger)
        self.assertIs(b33.TestOnlyEvidenceIssuer, b31.TestOnlyEvidenceIssuer)

    def test_merged_test_sources_exist_in_checkout(self):
        for batch in ("b24-provider-admission", "b25-responses-fixtures",
                      "b27-stream-compat", "b29-transport-ledger",
                      "b30-integrated-fixture", "b31-evidence-boundary",
                      "b32-staged-evidence", "b33-durable-observation"):
            self.assertTrue(
                (ROOT / "tests" / ("test-pxd-exec-s3-" + batch + ".py")).is_file(),
                batch,
            )

    def test_ci_has_merged_main_push_and_manual_triggers(self):
        workflow = (ROOT / ".github/workflows/"
                    "px-exec-s3-b33-durable-observation.yml").read_text()
        self.assertIn("push:", workflow)
        self.assertIn("branches: [main]", workflow)
        self.assertIn("pull_request:", workflow)
        self.assertIn("workflow_dispatch:", workflow)

    def test_ci_no_pinned_pr_checkouts_or_premerge_paths(self):
        workflow = (ROOT / ".github/workflows/"
                    "px-exec-s3-b33-durable-observation.yml").read_text()
        self.assertNotIn("deps/b30", workflow)
        self.assertNotIn("deps/b31", workflow)
        self.assertNotIn("deps/b32", workflow)
        self.assertNotIn("Checkout immutable", workflow)
        self.assertNotIn("persist-credentials: true", workflow)
        self.assertIn("github.event.pull_request.base.sha", workflow)

    def test_observation_and_settlement_on_landed_code(self):
        self.started()
        observation = self.observe()
        self.assertTrue(observation["durableEventDigestBound"])
        self.assertEqual(self.budget()["used_units"], 0)
        settled = self.settle(self.witness())
        self.assertEqual(settled["state"], "MOCK_COMPLETED")
        self.assertEqual(self.budget()["used_units"], 8)
        self.assertEqual(self.budget()["reserved_units"], 0)
        self.assertFalse(settled["realProviderObserved"])
        self.assertFalse(settled["realSpendVerified"])

    def test_observation_then_restart_then_matching_settlement(self):
        self.started()
        self.observe()
        original = self.conn.execute(
            "SELECT b33_observed_digest FROM b29_fixture_attempts"
        ).fetchone()[0]
        self.reopen()
        self.assertTrue(self.turn.snapshot("B34_attempt")["durableEventDigestBound"])
        self.assertEqual(original, self.conn.execute(
            "SELECT b33_observed_digest FROM b29_fixture_attempts"
        ).fetchone()[0])
        self.settle(self.witness())
        self.assertEqual(self.budget()["used_units"], 8)

    def test_same_response_id_changed_batch_denied_after_reopen(self):
        self.started()
        self.observe()
        self.reopen()
        swapped = samples.text_events("different but valid batch", "respA")
        with self.assertRaisesRegex(Refused, "OBSERVED_BATCH_MISMATCH"):
            self.settle(self.witness(swapped), swapped)
        self.assertEqual(self.budget()["used_units"], 0)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_settlement_without_observation_denied(self):
        self.started()
        with self.assertRaisesRegex(Refused, "OBSERVATION_REQUIRED"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["used_units"], 0)

    def test_changed_authority_fences_post_observation_settlement(self):
        self.started()
        self.observe()
        with self.assertRaisesRegex(Refused, "AUTHORITY_CHANGED"):
            self.settle(self.witness(), binding=dict(BIND, generation=2))
        self.reopen()
        self.assertEqual(self.turn.snapshot("B34_attempt")["state"],
                         "REVOKED_REMOTE_UNKNOWN")
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_cancel_then_restart_retains_budget_hold(self):
        self.started()
        self.observe()
        self.turn.cancel_mock("B34_attempt")
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_interrupted_delivery_cannot_resubmit_or_settle(self):
        self.started()
        self.turn.interrupt_mock("B34_attempt")
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        with self.assertRaisesRegex(Refused, "ALREADY_SUBMITTED"):
            self.turn.submit_mock("B34_attempt", BIND)
        self.assertEqual(self.budget()["reserved_units"], 30)

    def test_forged_model_claim_cannot_be_mock_witness(self):
        self.started()
        self.observe()
        with self.assertRaisesRegex(Refused, "UNTRUSTED_EVIDENCE"):
            self.settle({"authenticated": True, "usage_units": 0})
        self.assertEqual(self.budget()["used_units"], 0)

    def test_second_mock_settlement_cannot_spend_again(self):
        self.started()
        self.observe()
        self.settle(self.witness())
        self.reopen()
        with self.assertRaisesRegex(Refused, "NOT_ACTIVE"):
            self.settle(self.witness())
        self.assertEqual(self.budget()["used_units"], 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
