#!/usr/bin/env python3
"""B38-I: actual disposable B37-C + SQLite launch-claim + B38-G fake sandbox.

Offline only. Process creation is NOT inside the SQLite transaction, and the
claim is NOT a real provider launch permit. This tests order and recovery.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b29_transport_ledger import (
    Refused as B29Refused, canonical_binding,
)
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37b_sealed_handoff import SealedFixture
from px_s3_b37c_atomic_recovery_fixture import (
    AtomicOfflineFixture, Refused as B37CRefused,
)
from px_s3_b38i_fake_launch_claim import (
    AtomicFakeLaunchClaim, Refused as B38IRefused,
)

def load_b38g():
    path = ROOT / "tests" / "test-pxd-exec-s3-b38g-external-fake-supervisor.py"
    name = "b38i_test_only_b38g"
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod

G = load_b38g()

class Refused(RuntimeError):
    pass

def deny(code):
    raise Refused("B38I_SANDBOX_REFUSED_" + code)

@dataclass(frozen=True)
class FakeClaimedSandboxReceipt:
    text: str
    client_request_id: str
    local_state: str = "SUBMISSION_UNCONFIRMED"
    fake_claim_recorded: bool = True
    retry_authorized: bool = False
    authenticated_peer: bool = False
    authenticated_observation: bool = False
    launch_authorized: bool = False
    production_ready: bool = False

def claimed_fake_exchange(atomic, claimant, sealed, *, current_binding,
                          s1, root, fake_secret):
    """B37-C atomic mark -> B38-I atomic claim -> B38-G fake IPC.

    Cancellation before claim prevents claim; cancellation after claim is an
    already-in-flight synthetic attempt. Physical spawn remains non-atomic.
    """
    if (type(atomic) is not AtomicOfflineFixture or
        type(claimant) is not AtomicFakeLaunchClaim or
        claimant.atomic is not atomic or type(sealed) is not SealedFixture):
        deny("TEST_FIXTURE_REQUIRED")
    try:
        binding = json.loads(canonical_binding(current_binding))
        mark = atomic.begin_mock(
            sealed, current_binding=binding, offered_bytes=sealed.payload,
        )
    except (B29Refused, B37CRefused, ValueError, TypeError, KeyError):
        deny("DURABLE_MARK_DENIED")
    if (type(mark) is not dict or
        mark.get("state") != "SUBMISSION_UNCONFIRMED" or
        mark.get("reason") != "B37C_MOCK_TRANSITION_NOT_NETWORK_DELIVERY" or
        mark.get("retryAuthorized") is not False or
        mark.get("productionReady") is not False):
        deny("DURABLE_MARK_RECEIPT_INVALID")
    try:
        claim = claimant.claim_mock(sealed, current_binding=binding)
    except B38IRefused:
        # Mark is already durable. Do not reverse or assume safe retry.
        deny("FAKE_CLAIM_DENIED_NO_LAUNCH")
    if (type(claim) is not dict or
        claim.get("fakeLaunchClaimRecorded") is not True or
        claim.get("launchAuthorized") is not False or
        claim.get("retryAuthorized") is not False or
        claim.get("productionReady") is not False):
        deny("FAKE_CLAIM_RECEIPT_INVALID")

    try:
        # No arbitrary transport injection; only already-merged G fake fixture.
        reply = G.external_supervisor_fake_exchange(
            s1, root, fake_secret, sealed, current_binding=binding,
        )
        if (type(reply) is not G.FakeHostSandboxReceipt or
            reply.text != G.TEXT or
            reply.request_id != sealed.client_request_id or
            reply.sandbox_local_pid != G.EXPECTED_PID or
            type(reply.host_bwrap_pid) is not int or
            reply.host_bwrap_pid <= G.EXPECTED_PID or
            reply.model_calls != 0 or reply.tool_calls != 0 or
            reply.network_calls != 0 or
            any(getattr(reply, key) is not False for key in (
                "authenticated_unix_peer", "credential_isolation_certified",
                "launch_authorized", "production_ready"))):
            deny("SIGNED_FAKE_RESULT_INVALID")
        if (atomic.ledger.state(sealed.attempt_id)["state"] !=
                "SUBMISSION_UNCONFIRMED"):
            deny("FAKE_STATE_CHANGED_NO_COMPLETION")
    except Exception:
        # After claim, even a missing process is an uncertain outcome.
        try:
            recovered = atomic.recover_mock(sealed, current_binding=binding)
            if (type(recovered) is not dict or
                recovered.get("retryAuthorized") is not False or
                recovered.get("state") not in (
                    "REMOTE_OUTCOME_UNKNOWN", "CANCEL_PENDING",
                    "REVOKED_REMOTE_UNKNOWN")):
                deny("RECOVERY_NOT_QUARANTINED")
        except (B37CRefused, B29Refused, sqlite3.Error):
            deny("RECOVERY_UNAVAILABLE_NO_RETRY")
        deny("FAKE_OUTCOME_UNKNOWN_NO_RETRY")

    # A local fake HMAC reply is not a separate B33 witness.
    return FakeClaimedSandboxReceipt(
        text=reply.text, client_request_id=sealed.client_request_id,
    )

class Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="b38i-fake-claim-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / "synthetic.sqlite3"
        self.conn = self.open_connection()
        self.addCleanup(self.conn.close)
        self.atomic = AtomicOfflineFixture(self.conn, TestOnlyEvidenceIssuer())
        self.atomic.configure_mock_budget("b38iScope", 100)
        self.claims = AtomicFakeLaunchClaim(self.atomic)
        self.sealed, self.binding = G.fixture()
        self.fake_calls = 0

    def open_connection(self):
        return sqlite3.connect(
            self.db, isolation_level=None, timeout=5, check_same_thread=False,
        )

    def reopen(self):
        self.conn.close()
        self.conn = self.open_connection()
        self.addCleanup(self.conn.close)
        self.atomic = AtomicOfflineFixture(self.conn, TestOnlyEvidenceIssuer())
        self.claims = AtomicFakeLaunchClaim(self.atomic)

    def register(self):
        self.atomic.register_mock(
            self.sealed, scope="b38iScope", units=25,
            current_binding=self.binding,
        )

    def mark(self):
        return self.atomic.begin_mock(
            self.sealed, current_binding=self.binding,
            offered_bytes=self.sealed.payload,
        )

    def claim(self, binding=None):
        return self.claims.claim_mock(
            self.sealed,
            current_binding=self.binding if binding is None else binding,
        )

    def state(self):
        return self.atomic.ledger.state(self.sealed.attempt_id)["state"]

    def stub_reply(self, *_args, **_kwargs):
        self.fake_calls += 1
        return G.FakeHostSandboxReceipt(
            text=G.TEXT, request_id=self.sealed.client_request_id,
            sandbox_local_pid=G.EXPECTED_PID, host_bwrap_pid=4242,
        )

    def run_bridge(self):
        return claimed_fake_exchange(
            self.atomic, self.claims, self.sealed,
            current_binding=self.binding, s1=object(),
            root=self.root, fake_secret=self.root / "fake-secret",
        )

    def assert_hold(self):
        budget = self.atomic.ledger.budget("b38iScope")
        self.assertEqual(budget["reserved_units"], 25)
        self.assertEqual(budget["used_units"], 0)

    def test_registration_required_before_atomic_mark(self):
        with mock.patch.object(G, "external_supervisor_fake_exchange") as send:
            with self.assertRaisesRegex(Refused, "DURABLE_MARK_DENIED"):
                self.run_bridge()
            send.assert_not_called()
        # There is no registered attempt to claim or launch.

    def test_claim_cannot_precede_b37c_submission_mark(self):
        self.register()
        with self.assertRaisesRegex(B38IRefused, "NOT_UNCONFIRMED"):
            self.claim()
        self.assertFalse(self.claims.claim_recorded(self.sealed.attempt_id))
        self.assertEqual(self.state(), "RESERVED")

    def test_single_claim_durable_and_replay_denied(self):
        self.register()
        self.mark()
        c = self.claim()
        self.assertTrue(c["fakeLaunchClaimRecorded"])
        self.assertIs(c["launchAuthorized"], False)
        self.assertIs(c["retryAuthorized"], False)
        self.assertTrue(self.claims.claim_recorded(self.sealed.attempt_id))
        with self.assertRaisesRegex(B38IRefused, "FAKE_CLAIM_ALREADY_USED"):
            self.claim()
        self.reopen()
        self.assertTrue(self.claims.claim_recorded(self.sealed.attempt_id))
        with self.assertRaisesRegex(B38IRefused, "FAKE_CLAIM_ALREADY_USED"):
            self.claim()

    def test_cancel_before_claim_refuses_without_child(self):
        self.register()
        self.mark()
        self.atomic.cancel_mock(self.sealed.attempt_id)
        self.assertEqual(self.state(), "CANCEL_PENDING")
        with self.assertRaisesRegex(B38IRefused, "NOT_UNCONFIRMED"):
            self.claim()
        self.assertFalse(self.claims.claim_recorded(self.sealed.attempt_id))
        self.assert_hold()

    def test_revoke_before_claim_refuses_without_child(self):
        self.register()
        self.mark()
        self.atomic.revoke_if_changed(
            self.sealed.attempt_id,
            {**self.binding, "generation": self.binding["generation"] + 1},
        )
        self.assertEqual(self.state(), "REVOKED_REMOTE_UNKNOWN")
        with self.assertRaisesRegex(B38IRefused, "NOT_UNCONFIRMED"):
            self.claim()
        self.assertFalse(self.claims.claim_recorded(self.sealed.attempt_id))
        self.assert_hold()

    def test_stale_binding_refused_in_claim_transaction(self):
        self.register()
        self.mark()
        for k, v in [("room", "changedRoom"), ("generation", 99),
                     ("turnId", "changedTurn"), ("assignment", "otherJob")]:
            with self.assertRaisesRegex(B38IRefused, "SEALED_BINDING_INVALID"):
                self.claim({**self.binding, k: v})
        self.assertFalse(self.claims.claim_recorded(self.sealed.attempt_id))

    def test_claim_column_immutable_after_commit(self):
        self.register()
        self.mark()
        self.claim()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE b29_fixture_attempts SET b38i_fake_launch_claim=NULL "
                "WHERE attempt_id=?", (self.sealed.attempt_id,),
            )
        self.assertTrue(self.claims.claim_recorded(self.sealed.attempt_id))

    def test_two_connections_compete_for_exactly_one_claim(self):
        self.register()
        self.mark()
        conn2 = self.open_connection()
        self.addCleanup(conn2.close)
        atomic2 = AtomicOfflineFixture(conn2, TestOnlyEvidenceIssuer())
        claim2 = AtomicFakeLaunchClaim(atomic2)
        start = threading.Barrier(2)
        def attempt(claims):
            start.wait(timeout=5)
            try:
                claims.claim_mock(self.sealed, current_binding=self.binding)
                return "CLAIMED"
            except B38IRefused:
                return "REFUSED"
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(attempt, self.claims)
            b = pool.submit(attempt, claim2)
            outcomes = sorted([a.result(timeout=10), b.result(timeout=10)])
        self.assertEqual(outcomes, ["CLAIMED", "REFUSED"])
        self.assertTrue(self.claims.claim_recorded(self.sealed.attempt_id))

    def test_concurrent_cancel_and_claim_have_one_sql_order(self):
        self.register()
        self.mark()
        conn2 = self.open_connection()
        self.addCleanup(conn2.close)
        other = AtomicOfflineFixture(conn2, TestOnlyEvidenceIssuer())
        start = threading.Barrier(2)
        def do_claim():
            start.wait(timeout=5)
            try:
                self.claim()
                return "CLAIMED"
            except B38IRefused:
                return "REFUSED"
        def do_cancel():
            start.wait(timeout=5)
            other.cancel_mock(self.sealed.attempt_id)
            return "CANCELLED"
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(do_claim)
            b = pool.submit(do_cancel)
            result = a.result(timeout=10)
            self.assertEqual(b.result(timeout=10), "CANCELLED")
        self.assertIn(result, ("CLAIMED", "REFUSED"))
        self.assertEqual(self.state(), "CANCEL_PENDING")
        self.assertEqual(self.claims.claim_recorded(self.sealed.attempt_id),
                         result == "CLAIMED")
        self.assert_hold()

    def test_crash_after_mark_but_before_claim_no_replay(self):
        self.register()
        self.mark()
        self.reopen()
        self.assertFalse(self.claims.claim_recorded(self.sealed.attempt_id))
        recovery = self.atomic.recover_mock(
            self.sealed, current_binding=self.binding,
        )
        self.assertEqual(recovery["state"], "REMOTE_OUTCOME_UNKNOWN")
        self.assertIs(recovery["retryAuthorized"], False)
        with self.assertRaisesRegex(B38IRefused, "NOT_UNCONFIRMED"):
            self.claim()
        self.assert_hold()

    def test_crash_after_claim_before_child_no_replay(self):
        self.register()
        self.mark()
        self.claim()
        self.reopen()
        self.assertTrue(self.claims.claim_recorded(self.sealed.attempt_id))
        recovery = self.atomic.recover_mock(
            self.sealed, current_binding=self.binding,
        )
        self.assertEqual(recovery["state"], "REMOTE_OUTCOME_UNKNOWN")
        with self.assertRaisesRegex(B38IRefused, "NOT_UNCONFIRMED"):
            self.claim()
        self.assert_hold()

    def test_process_failure_never_resends_or_releases_budget(self):
        self.register()
        with mock.patch.object(G, "external_supervisor_fake_exchange",
                               side_effect=G.Refused("FAKE_TIMEOUT")) as send:
            with self.assertRaisesRegex(Refused, "FAKE_OUTCOME_UNKNOWN_NO_RETRY"):
                self.run_bridge()
            send.assert_called_once()
        self.assertTrue(self.claims.claim_recorded(self.sealed.attempt_id))
        self.assertEqual(self.state(), "REMOTE_OUTCOME_UNKNOWN")
        self.assert_hold()
        with mock.patch.object(G, "external_supervisor_fake_exchange") as retry:
            with self.assertRaisesRegex(Refused, "DURABLE_MARK_DENIED"):
                self.run_bridge()
            retry.assert_not_called()

    def test_fake_success_does_not_create_b33_witness_or_spend(self):
        self.register()
        with mock.patch.object(G, "external_supervisor_fake_exchange",
                               side_effect=self.stub_reply):
            result = self.run_bridge()
        self.assertEqual(result.text, G.TEXT)
        self.assertFalse(result.authenticated_observation)
        self.assertFalse(result.launch_authorized)
        self.assertEqual(self.fake_calls, 1)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        self.assertFalse(self.atomic.snapshot(
            self.sealed.attempt_id)["durableMockObservation"])
        self.assert_hold()
        self.reopen()
        self.assertEqual(self.atomic.recover_mock(
            self.sealed, current_binding=self.binding)["state"],
            "REMOTE_OUTCOME_UNKNOWN")

    def test_cancel_after_claim_is_in_flight_not_fake_completion(self):
        self.register()
        def late_cancel(*args, **kwargs):
            self.atomic.cancel_mock(self.sealed.attempt_id)
            return self.stub_reply()
        with mock.patch.object(G, "external_supervisor_fake_exchange",
                               side_effect=late_cancel):
            with self.assertRaisesRegex(Refused, "FAKE_OUTCOME_UNKNOWN_NO_RETRY"):
                self.run_bridge()
        self.assertTrue(self.claims.claim_recorded(self.sealed.attempt_id))
        self.assertEqual(self.state(), "CANCEL_PENDING")
        self.assert_hold()

    def test_no_real_sender_or_live_hospital(self):
        self.register()
        with self.assertRaisesRegex(B38IRefused, "NO_REAL_OS_LAUNCH"):
            self.claims.require_real_launch()
        self.assertEqual(self.state(), "RESERVED")

def smoke():
    """One actual Bubblewrap B38-E fake child after B37-C + durable claim."""
    s1 = G.load_s1()
    with tempfile.TemporaryDirectory(prefix="b38i-os-fake-") as td:
        root = Path(td)
        db = root / "fake.sqlite3"
        with sqlite3.connect(db, isolation_level=None, timeout=5) as conn:
            atomic = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
            atomic.configure_mock_budget("b38iScope", 100)
            claims = AtomicFakeLaunchClaim(atomic)
            sealed, binding = G.fixture()
            atomic.register_mock(
                sealed, scope="b38iScope", units=25,
                current_binding=binding,
            )
            sandbox = root / "sandbox"
            sandbox.mkdir(mode=0o700)
            sandbox_root, fake_secret = G.prepare_disposable_root(str(sandbox))
            reply = claimed_fake_exchange(
                atomic, claims, sealed, current_binding=binding,
                s1=s1, root=sandbox_root, fake_secret=fake_secret,
            )
            if (reply.text != G.TEXT or
                reply.local_state != "SUBMISSION_UNCONFIRMED" or
                not claims.claim_recorded(sealed.attempt_id) or
                atomic.ledger.state(sealed.attempt_id)["state"] !=
                    "SUBMISSION_UNCONFIRMED" or
                atomic.ledger.budget("b38iScope")["reserved_units"] != 25):
                deny("FAKE_SANDBOX_OR_CLAIM_INVALID")
        with sqlite3.connect(db, isolation_level=None, timeout=5) as conn:
            atomic = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
            claims = AtomicFakeLaunchClaim(atomic)
            if not claims.claim_recorded(sealed.attempt_id):
                deny("FAKE_CLAIM_LOST_AFTER_REOPEN")
            recovery = atomic.recover_mock(
                sealed, current_binding=binding,
            )
            if (recovery["state"] != "REMOTE_OUTCOME_UNKNOWN" or
                recovery["retryAuthorized"] is not False):
                deny("FAKE_UNKNOWN_NOT_QUARANTINED")
            try:
                claims.claim_mock(sealed, current_binding=binding)
            except B38IRefused:
                pass
            else:
                deny("FAKE_CLAIM_REPLAY_ALLOWED")
    return {
        "state": "B38I_FAKE_CLAIM_SANDBOX_PASS",
        "atomicClaimInB29Transaction": True,
        "oneFakeProcess": True,
        "b37cMarkedBeforeClaim": True,
        "insideBubblewrapB38E": True,
        "outsideSandboxB38GSupervisor": True,
        "restartedClaimStillRecorded": True,
        "remoteOutcomeUnknown": True,
        "automaticRetry": False,
        "realProviderCalls": 0,
        "realLaunchAuthorization": False,
        "productionReady": False,
    }

def main():
    arg = argparse.ArgumentParser()
    group = arg.add_mutually_exclusive_group(required=True)
    group.add_argument("--unit", action="store_true")
    group.add_argument("--smoke", action="store_true")
    mode = arg.parse_args()
    if mode.unit:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    try:
        print(json.dumps(smoke(), sort_keys=True))
        return 0
    except (Refused, B38IRefused, B37CRefused, G.Refused) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
