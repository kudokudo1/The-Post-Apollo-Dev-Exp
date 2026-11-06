#!/usr/bin/env python3
"""B38-H: additive TEST-ONLY B37-C durable fence -> B38-G sandboxed fake IPC.

No production sender, no authorization to use a model/provider, no edits to
either owning implementation. Missing admission fails before subprocess
launch. After atomic begin, failure or crash is UNKNOWN and never resent.
"""
from dataclasses import dataclass
import argparse
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b29_transport_ledger import canonical_binding, Refused as B29Refused
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37b_sealed_handoff import SealedFixture
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture, Refused as B37CRefused

def load_b38g():
    path = ROOT / "tests" / "test-pxd-exec-s3-b38g-external-fake-supervisor.py"
    if not path.is_file():
        raise RuntimeError("B38H_REFUSED_B38G_SOURCE_MISSING")
    name = "b38h_imported_b38g_fixture"
    if name in sys.modules:
        return sys.modules[name]
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
    """Stable, non-sensitive B38-H synthetic refusal, never provider content."""

def deny(code):
    raise Refused("B38H_REFUSED_" + code)

@dataclass(frozen=True)
class B38HDurableFakeReceipt:
    state: str
    text: str
    client_request_id: str
    attempt_id: str
    sandbox_pid: int
    source: str = "B38H_B37C_ATOMIC_PLUS_B38G_FAKE_ONLY"
    retry_authorized: bool = False
    model_calls: int = 0
    tool_calls: int = 0
    network_calls: int = 0
    hospital_writes: int = 0
    real_provider_started: bool = False
    production_ready: bool = False
    durable_response_observed: bool = False

def fenced_fake_sandbox_exchange(atomic, sealed, *, current_binding, s1, root, fake_secret):
    """B37-C atomic mark happens strictly before calling unmodified B38-G.

    B37-C already protects the same sealed request against replay in SQLite.
    The caller must have registered the *same* request through register_mock.
    No fake B33 observation/witness is fabricated from model-produced text.
    """
    if type(atomic) is not AtomicOfflineFixture:
        deny("ATOMIC_FIXTURE_REQUIRED")
    if type(sealed) is not SealedFixture:
        deny("SEALED_REQUEST_REQUIRED")
    try:
        binding = json.loads(canonical_binding(current_binding))
    except (TypeError, ValueError, KeyError, RuntimeError):
        deny("SYNTHETIC_BINDING_INVALID")
    try:
        fence = atomic.begin_mock(
            sealed, current_binding=binding, offered_bytes=sealed.payload,
        )
    except (B37CRefused, B29Refused, ValueError, KeyError, TypeError, sqlite3.Error):
        deny("DURABLE_FENCE_DENIED")
    if (type(fence) is not dict or
        fence.get("state") != "SUBMISSION_UNCONFIRMED" or
        fence.get("reason") != "B37C_MOCK_TRANSITION_NOT_NETWORK_DELIVERY" or
        fence.get("retryAuthorized") is not False or
        fence.get("launchAuthorized") is not False or
        fence.get("productionReady") is not False):
        # Already marked submission: never undo or resend based on a bad receipt.
        deny("DURABLE_RECEIPT_UNTRUSTED")
    # Detect an already-committed cancellation/revocation before starting
    # the fake process. This read is NOT a race-free production launch lease.
    try:
        latest = atomic.ledger.state(sealed.attempt_id)
    except (B29Refused, sqlite3.Error):
        deny("POST_FENCE_STATE_UNAVAILABLE_NO_SEND")
    if (type(latest) is not dict or
        latest.get("state") != "SUBMISSION_UNCONFIRMED" or
        latest.get("clientRequestId") != sealed.client_request_id or
        latest.get("retryAuthorized") is not False):
        deny("POST_FENCE_STATE_CHANGED_NO_SEND")
    try:
        reply = G.external_supervisor_fake_exchange(
            s1, root, fake_secret, sealed, current_binding=binding,
        )
        if (type(reply) is not G.FakeHostSandboxReceipt or
            reply.text != G.TEXT or
            reply.request_id != sealed.client_request_id or
            type(reply.sandbox_local_pid) is not int or
            reply.sandbox_local_pid != G.EXPECTED_PID or
            type(reply.host_bwrap_pid) is not int or
            reply.host_bwrap_pid <= G.EXPECTED_PID or
            reply.model_calls != 0 or reply.tool_calls != 0 or
            reply.network_calls != 0 or
            any(getattr(reply, key) is not False for key in (
                "authenticated_unix_peer", "credential_isolation_certified",
                "launch_authorized", "production_ready"))):
            deny("SIGNED_FAKE_REPLY_INVALID")
    except Exception:
        # B37-C owns the quarantine transaction; avoid any retry or reversal.
        try:
            recovered = atomic.recover_mock(sealed, current_binding=binding)
        except Exception:
            deny("UNCERTAIN_RECOVERY_UNAVAILABLE")
        if (type(recovered) is not dict or
            recovered.get("state") != "REMOTE_OUTCOME_UNKNOWN" or
            recovered.get("retryAuthorized") is not False):
            deny("UNCERTAIN_RECOVERY_INVALID")
        deny("SANDBOX_OUTCOME_UNKNOWN_NO_RETRY")

    # A verified local fake reply is NOT a B33 authenticated observation.
    # Keep B37-C's durable state SUBMISSION_UNCONFIRMED until separate witness.
    if atomic.ledger.state(sealed.attempt_id)["state"] != "SUBMISSION_UNCONFIRMED":
        deny("ATOMIC_STATE_CHANGED")
    return B38HDurableFakeReceipt(
        state="SUBMISSION_UNCONFIRMED", text=reply.text,
        client_request_id=sealed.client_request_id,
        attempt_id=sealed.attempt_id,
        sandbox_pid=reply.sandbox_local_pid,
    )

class Harness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="b38h-fake-ledger-")
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "synthetic.sqlite3"
        self.conn = sqlite3.connect(self.db, isolation_level=None, timeout=3)
        self.addCleanup(self.conn.close)
        self.atomic = AtomicOfflineFixture(self.conn, TestOnlyEvidenceIssuer())
        self.atomic.configure_mock_budget("scopeB38H", 100)
        self.sealed, self.binding = G.fixture()
        self.test_s1 = object()  # Mock unit boundary; smoke uses real accepted S1.
        self.test_root = Path(self.temp.name)
        self.test_secret = self.test_root / "fake-canary"
        self.dispatch_count = 0

    def register(self):
        return self.atomic.register_mock(
            self.sealed, scope="scopeB38H", units=25,
            current_binding=self.binding,
        )

    def reopen(self):
        self.conn.close()
        self.conn = sqlite3.connect(self.db, isolation_level=None, timeout=3)
        self.addCleanup(self.conn.close)
        self.atomic = AtomicOfflineFixture(self.conn, TestOnlyEvidenceIssuer())

    def invoke(self, binding=None):
        return fenced_fake_sandbox_exchange(
            self.atomic, self.sealed, current_binding=(
                self.binding if binding is None else binding),
            s1=self.test_s1, root=self.test_root, fake_secret=self.test_secret,
        )

    def fake_reply(self, *args, **kwargs):
        self.dispatch_count += 1
        return G.FakeHostSandboxReceipt(
            text=G.TEXT, request_id=self.sealed.client_request_id,
            sandbox_local_pid=G.EXPECTED_PID, host_bwrap_pid=4321,
        )

    def state(self):
        return self.atomic.ledger.state(self.sealed.attempt_id)["state"]

    def test_unregistered_request_never_spawns(self):
        with mock.patch.object(G, "external_supervisor_fake_exchange") as send:
            with self.assertRaisesRegex(Refused, "DURABLE_FENCE_DENIED"):
                self.invoke()
            send.assert_not_called()

    def test_registered_then_one_fake_send_and_no_duplicate(self):
        self.register()
        with mock.patch.object(G, "external_supervisor_fake_exchange",
                               side_effect=self.fake_reply):
            receipt = self.invoke()
            self.assertEqual(receipt.state, "SUBMISSION_UNCONFIRMED")
            self.assertEqual(receipt.text, G.TEXT)
            self.assertFalse(receipt.retry_authorized)
            self.assertFalse(receipt.durable_response_observed)
            self.assertFalse(receipt.production_ready)
            with self.assertRaisesRegex(Refused, "DURABLE_FENCE_DENIED"):
                self.invoke()
            self.assertEqual(self.dispatch_count, 1)
            self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")

    def test_stale_binding_before_atomic_mark_does_not_spawn(self):
        self.register()
        with mock.patch.object(G, "external_supervisor_fake_exchange") as send:
            for field, value in (
                ("generation", 999), ("room", "wrongRoom"),
                ("assignment", "wrongAssignment"), ("bed", "wrongBed"),
                ("turnId", "wrongTurn")):
                with self.assertRaisesRegex(Refused, "DURABLE_FENCE_DENIED"):
                    self.invoke({**self.binding, field: value})
            send.assert_not_called()
        self.assertEqual(self.state(), "RESERVED")

    def test_pretransition_restart_keeps_reserved_no_automatic_send(self):
        self.register()
        self.reopen()
        with mock.patch.object(G, "external_supervisor_fake_exchange") as send:
            evidence = self.atomic.recover_mock(
                self.sealed, current_binding=self.binding,
            )
            self.assertEqual(evidence["state"], "RESERVED")
            send.assert_not_called()
        self.assertEqual(self.state(), "RESERVED")

    def test_crash_after_atomic_mark_restart_quarantines_without_replay(self):
        self.register()
        with mock.patch.object(G, "external_supervisor_fake_exchange",
                               side_effect=SystemExit(51)) as send:
            with self.assertRaises(SystemExit):
                self.invoke()
            self.assertEqual(send.call_count, 1)
        self.assertEqual(self.state(), "SUBMISSION_UNCONFIRMED")
        self.reopen()
        recovery = self.atomic.recover_mock(
            self.sealed, current_binding=self.binding,
        )
        self.assertEqual(recovery["state"], "REMOTE_OUTCOME_UNKNOWN")
        self.assertIs(recovery["retryAuthorized"], False)
        with mock.patch.object(G, "external_supervisor_fake_exchange") as retry:
            with self.assertRaisesRegex(Refused, "DURABLE_FENCE_DENIED"):
                self.invoke()
            retry.assert_not_called()
        self.assertEqual(self.atomic.ledger.budget("scopeB38H")["reserved_units"], 25)

    def test_process_failure_quarantines_and_holds_budget(self):
        self.register()
        with mock.patch.object(G, "external_supervisor_fake_exchange",
                               side_effect=G.Refused("B38G_REFUSED_CHILD_TIMEOUT")) as send:
            with self.assertRaisesRegex(Refused, "SANDBOX_OUTCOME_UNKNOWN_NO_RETRY"):
                self.invoke()
            self.assertEqual(send.call_count, 1)
        self.assertEqual(self.state(), "REMOTE_OUTCOME_UNKNOWN")
        self.assertEqual(self.atomic.ledger.budget("scopeB38H")["reserved_units"], 25)
        self.assertEqual(self.atomic.ledger.budget("scopeB38H")["used_units"], 0)

    def test_corrupt_fake_reply_does_not_create_durable_observation(self):
        self.register()
        forged = G.FakeHostSandboxReceipt(
            text="MALICIOUS_FAKE", request_id=self.sealed.client_request_id,
            sandbox_local_pid=2, host_bwrap_pid=4321,
        )
        with mock.patch.object(G, "external_supervisor_fake_exchange",
                               return_value=forged):
            with self.assertRaisesRegex(Refused, "SANDBOX_OUTCOME_UNKNOWN_NO_RETRY"):
                self.invoke()
        self.assertEqual(self.state(), "REMOTE_OUTCOME_UNKNOWN")
        self.assertFalse(self.atomic.snapshot(self.sealed.attempt_id)["durableMockObservation"])

    def test_success_then_restart_never_auto_resubmits_or_auto_settles(self):
        self.register()
        with mock.patch.object(G, "external_supervisor_fake_exchange",
                               side_effect=self.fake_reply):
            self.invoke()
        self.reopen()
        recover = self.atomic.recover_mock(
            self.sealed, current_binding=self.binding,
        )
        self.assertEqual(recover["state"], "REMOTE_OUTCOME_UNKNOWN")
        self.assertFalse(recover["retryAuthorized"])
        self.assertEqual(self.dispatch_count, 1)
        self.assertFalse(recover["durableMockObservation"])
        with mock.patch.object(G, "external_supervisor_fake_exchange") as retry:
            with self.assertRaisesRegex(Refused, "DURABLE_FENCE_DENIED"):
                self.invoke()
            retry.assert_not_called()

    def test_cancel_after_atomic_mark_before_spawn_refuses(self):
        self.register()
        begin = self.atomic.begin_mock
        def cancel_between(*args, **kwargs):
            receipt = begin(*args, **kwargs)
            self.atomic.cancel_mock(self.sealed.attempt_id)
            return receipt
        with mock.patch.object(self.atomic, "begin_mock",
                               side_effect=cancel_between):
            with mock.patch.object(G, "external_supervisor_fake_exchange") as send:
                with self.assertRaisesRegex(Refused, "POST_FENCE_STATE_CHANGED_NO_SEND"):
                    self.invoke()
                send.assert_not_called()
        self.assertEqual(self.state(), "CANCEL_PENDING")
        self.assertEqual(self.atomic.ledger.budget("scopeB38H")["reserved_units"], 25)

    def test_revoke_after_atomic_mark_before_spawn_refuses(self):
        self.register()
        begin = self.atomic.begin_mock
        def revoke_between(*args, **kwargs):
            receipt = begin(*args, **kwargs)
            self.atomic.revoke_if_changed(
                self.sealed.attempt_id,
                {**self.binding, "generation": self.binding["generation"] + 1},
            )
            return receipt
        with mock.patch.object(self.atomic, "begin_mock",
                               side_effect=revoke_between):
            with mock.patch.object(G, "external_supervisor_fake_exchange") as send:
                with self.assertRaisesRegex(Refused, "POST_FENCE_STATE_CHANGED_NO_SEND"):
                    self.invoke()
                send.assert_not_called()
        self.assertEqual(self.state(), "REVOKED_REMOTE_UNKNOWN")
        self.assertEqual(self.atomic.ledger.budget("scopeB38H")["reserved_units"], 25)

    def test_ledger_issuer_and_fake_only_guards(self):
        self.register()
        self.assertIs(type(self.atomic), AtomicOfflineFixture)
        with mock.patch.object(G, "external_supervisor_fake_exchange",
                               side_effect=self.fake_reply):
            receipt = self.invoke()
        self.assertEqual(receipt.model_calls, 0)
        self.assertEqual(receipt.tool_calls, 0)
        self.assertEqual(receipt.network_calls, 0)
        self.assertEqual(receipt.hospital_writes, 0)
        self.assertFalse(receipt.real_provider_started)
        self.assertFalse(receipt.production_ready)
        self.assertEqual(self.atomic.ledger.budget("scopeB38H")["used_units"], 0)

def smoke():
    """Real B38-G sandbox once, gated through B37-C disposable SQLite."""
    s1 = G.load_s1()
    with tempfile.TemporaryDirectory(prefix="b38h-real-fake-") as td:
        tmp = Path(td)
        db = tmp / "disposable.sqlite3"
        with sqlite3.connect(db, isolation_level=None, timeout=3) as conn:
            atomic = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
            atomic.configure_mock_budget("scopeB38H", 100)
            sealed, binding = G.fixture()
            atomic.register_mock(
                sealed, scope="scopeB38H", units=25,
                current_binding=binding,
            )
            sandbox_path = tmp / "sandbox"
            sandbox_path.mkdir(mode=0o700)
            root, secret = G.prepare_disposable_root(str(sandbox_path))
            receipt = fenced_fake_sandbox_exchange(
                atomic, sealed, current_binding=binding,
                s1=s1, root=root, fake_secret=secret,
            )
            if (receipt.text != G.TEXT or
                receipt.state != "SUBMISSION_UNCONFIRMED" or
                receipt.sandbox_pid != G.EXPECTED_PID or
                atomic.ledger.state(sealed.attempt_id)["state"] !=
                    "SUBMISSION_UNCONFIRMED"):
                deny("LIVE_FAKE_BRIDGE_INVALID")
            # Even after a *locally* signed synthetic reply, restart can only
            # quarantine absent a separate B33 witnessed observation.
        with sqlite3.connect(db, isolation_level=None, timeout=3) as conn:
            reopened = AtomicOfflineFixture(conn, TestOnlyEvidenceIssuer())
            recovered = reopened.recover_mock(
                sealed, current_binding=binding,
            )
            if (recovered["state"] != "REMOTE_OUTCOME_UNKNOWN" or
                recovered["retryAuthorized"] is not False or
                reopened.ledger.budget("scopeB38H")["reserved_units"] != 25):
                deny("RESTART_QUARANTINE_INVALID")
            with mock.patch.object(G, "external_supervisor_fake_exchange") as resend:
                try:
                    fenced_fake_sandbox_exchange(
                        reopened, sealed, current_binding=binding,
                        s1=s1, root=root, fake_secret=secret,
                    )
                except Refused as exc:
                    if str(exc) != "B38H_REFUSED_DURABLE_FENCE_DENIED":
                        raise
                else:
                    deny("REPLAY_WAS_ALLOWED")
                resend.assert_not_called()
    return {
        "state": "B38H_FAKE_DURABLE_SANDBOX_REPLAY_DENIED",
        "outsideSupervisor": True,
        "sandboxedB38E": True,
        "b37cRegisteredBeforeLaunch": True,
        "atomicMarkBeforeFakeExchange": True,
        "signedFakeReply": True,
        "restartOutcomeUnknown": True,
        "automaticResend": False,
        "fakeBudgetHeld": True,
        "realProviderCalls": 0,
        "productionReady": False,
        "hospitalAccess": False,
    }

def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--unit", action="store_true")
    modes.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.unit:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Harness)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    try:
        print(json.dumps(smoke(), sort_keys=True))
        return 0
    except (Refused, G.Refused, B37CRefused) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
