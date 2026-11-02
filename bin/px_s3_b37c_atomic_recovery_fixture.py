#!/usr/bin/env python3
"""B37-C: disposable SQLite atomic request fence and fake recovery lifecycle.

OFFLINE FIXTURE ONLY. No provider, network, SDK, credentials, native tools,
real Hospital authority, real submission, or permission to dispatch.
The only state modifications are inside a caller-supplied B29/B33 mock DB.
"""
import hashlib
import hmac
import json
import sqlite3

from px_s3_b29_transport_ledger import Refused as LedgerRefused, canonical_binding
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b33_durable_observation import DurableObservedFixture
from px_s3_b37a_tool_free_contract import validate_wire_payload
from px_s3_b37b_sealed_handoff import (
    Refused as SealRefused, reserve_mock, verify_fixture,
)

TRIGGER = """
CREATE TRIGGER IF NOT EXISTS b37c_fixture_request_immutable
BEFORE UPDATE OF client_request_id, binding_json, b37c_payload_sha256
ON b29_fixture_attempts
WHEN OLD.b37c_payload_sha256 IS NOT NULL AND
     (NEW.client_request_id IS NOT OLD.client_request_id OR
      NEW.binding_json IS NOT OLD.binding_json OR
      NEW.b37c_payload_sha256 IS NOT OLD.b37c_payload_sha256)
BEGIN
    SELECT RAISE(ABORT, 'B37C_REQUEST_IMMUTABLE');
END;
"""


class Refused(RuntimeError):
    """Non-sensitive fixture error code, never prompt or provider context."""


def _deny(code):
    raise Refused("B37C_REFUSED_" + code)


def _safe(state, reason, *, sealed=None, observed=False):
    # These are synthetic facts only, never tokens, permissions or send receipts.
    return {
        "schema": "B37C_OFFLINE_ATOMIC_FENCE_V1",
        "state": state, "reason": reason,
        "payloadSha256": sealed.payload_sha256 if sealed else None,
        "clientRequestId": sealed.client_request_id if sealed else None,
        "durableMockObservation": bool(observed),
        "launchAuthorized": False, "toolDispatchAuthorized": False,
        "retryAuthorized": False, "productionReady": False,
        "providerStarted": False, "modelCalls": 0, "toolCalls": 0,
        "hospitalWrites": 0, "remoteDeliveryObserved": False,
        "realStopVerified": False, "realSpendVerified": False,
    }


class AtomicOfflineFixture:
    """A mock-only B29/B33 fixture with an atomic local request identity fence."""

    def __init__(self, connection, test_issuer):
        if type(test_issuer) is not TestOnlyEvidenceIssuer:
            _deny("TEST_ISSUER_REQUIRED")
        self.observed = DurableObservedFixture(connection, test_issuer)
        self.ledger = self.observed.ledger
        self.conn = self.ledger.conn
        self._install()

    def _install(self):
        columns = {
            row["name"]: row
            for row in self.conn.execute("PRAGMA table_info(b29_fixture_attempts)")
        }
        if "b37c_payload_sha256" not in columns:
            self.conn.execute(
                "ALTER TABLE b29_fixture_attempts "
                "ADD COLUMN b37c_payload_sha256 TEXT"
            )
        elif columns["b37c_payload_sha256"]["type"] != "TEXT":
            _deny("COLUMN_SCHEMA")
        self.conn.executescript(TRIGGER)

    def configure_mock_budget(self, scope, units):
        return self.observed.configure_mock_budget(scope, units)

    def _preflight(self, sealed, current_binding, offered_bytes=None):
        try:
            binding_json = canonical_binding(current_binding)
            # Freeze the synthetic supplied binding for the rest of this call.
            fixed_binding = json.loads(binding_json)
            verify_fixture(sealed, current_binding=fixed_binding)
            if offered_bytes is not None:
                if (type(offered_bytes) is not bytes or
                        not hmac.compare_digest(offered_bytes, sealed.payload)):
                    _deny("FINAL_BYTES_CHANGED")
            validate_wire_payload(sealed.payload)
            if hashlib.sha256(sealed.payload).hexdigest() != sealed.payload_sha256:
                _deny("PAYLOAD_HASH_CHANGED")
            return binding_json
        except Refused:
            raise
        except (SealRefused, LedgerRefused, ValueError, TypeError):
            _deny("SEAL_OR_AUTHORITY_INVALID")

    def _checked(self, attempt_id, sealed, binding_json):
        row = self.ledger._attempt(attempt_id)
        if (row["client_request_id"] != sealed.client_request_id or
                row["turn_id"] != json.loads(binding_json)["turnId"] or
                row["binding_json"] != binding_json):
            _deny("TRANSACTION_IDENTITY_CHANGED")
        if row["mode"] != "FOREGROUND_STREAM":
            _deny("MODE_NOT_FOREGROUND")
        if (row["b37c_payload_sha256"] is None or
                not hmac.compare_digest(
                    row["b37c_payload_sha256"], sealed.payload_sha256)):
            _deny("TRANSACTION_PAYLOAD_CHANGED")
        return row

    def register_mock(self, sealed, *, scope, units, current_binding):
        """B29 reservation followed by a separate protected SHA binding.

        Crash between the two leaves RESERVED but unbound, never eligible
        for the B37-C transition; no remote submission is possible here.
        """
        binding_json = self._preflight(sealed, current_binding)
        try:
            reserve_mock(
                self.ledger, sealed, scope=scope, units=units,
                current_binding=json.loads(binding_json),
            )
        except SealRefused:
            _deny("RESERVE_REFUSED")

        def bind():
            row = self.ledger._attempt(sealed.attempt_id)
            if (row["state"] != "RESERVED" or
                    row["client_request_id"] != sealed.client_request_id or
                    row["binding_json"] != binding_json or
                    row["turn_id"] != json.loads(binding_json)["turnId"]):
                _deny("RESERVED_IDENTITY_CHANGED")
            stored = row["b37c_payload_sha256"]
            if stored is not None and stored != sealed.payload_sha256:
                _deny("REGISTER_PAYLOAD_DRIFT")
            if stored is None:
                self.conn.execute(
                    "UPDATE b29_fixture_attempts "
                    "SET b37c_payload_sha256=? "
                    "WHERE attempt_id=? AND state='RESERVED' "
                    "AND client_request_id=? AND binding_json=? "
                    "AND b37c_payload_sha256 IS NULL",
                    (sealed.payload_sha256, sealed.attempt_id,
                     sealed.client_request_id, binding_json)
                )
                self._checked(sealed.attempt_id, sealed, binding_json)
        self.ledger._transaction(bind)
        return _safe("RESERVED", "B37C_REGISTERED_NO_SENDER", sealed=sealed)

    def begin_mock(self, sealed, *, current_binding, offered_bytes=None):
        """Single SQLite transaction: identity, SHA, binding, state -> mock mark.

        No network dispatch occurs inside/outside this transaction.
        """
        binding_json = self._preflight(sealed, current_binding, offered_bytes)
        def transition():
            row = self._checked(sealed.attempt_id, sealed, binding_json)
            if row["state"] != "RESERVED":
                _deny("STATE_NOT_RESERVED")
            if row["response_id"] is not None or row["b33_observed_digest"] is not None:
                _deny("OBSERVATION_PRECEDES_SUBMISSION")
            cursor = self.conn.execute(
                "UPDATE b29_fixture_attempts "
                "SET state='SUBMISSION_UNCONFIRMED' "
                "WHERE attempt_id=? AND state='RESERVED' "
                "AND client_request_id=? AND b37c_payload_sha256=? "
                "AND binding_json=? AND turn_id=? AND mode=\'FOREGROUND_STREAM\' "
                "AND response_id IS NULL AND b33_observed_digest IS NULL",
                (sealed.attempt_id, sealed.client_request_id,
                 sealed.payload_sha256, binding_json,
                 json.loads(binding_json)["turnId"]),
            )
            if cursor.rowcount != 1:
                _deny("ATOMIC_FENCE_FAILED")
            return _safe(
                "SUBMISSION_UNCONFIRMED",
                "B37C_MOCK_TRANSITION_NOT_NETWORK_DELIVERY", sealed=sealed,
            )
        return self.ledger._transaction(transition)

    def recover_mock(self, sealed, *, current_binding):
        """Crash/restart classification. Never performs or authorizes resend."""
        binding_json = self._preflight(sealed, current_binding)
        def recover():
            row = self._checked(sealed.attempt_id, sealed, binding_json)
            state = row["state"]
            observed = row["b33_observed_digest"] is not None
            if state == "RESERVED":
                return _safe(state, "B37C_PRE_SUBMISSION_NO_AUTO_RETRY",
                             sealed=sealed, observed=observed)
            if state == "SUBMISSION_UNCONFIRMED" and not observed:
                self.conn.execute(
                    "UPDATE b29_fixture_attempts "
                    "SET state='REMOTE_OUTCOME_UNKNOWN' "
                    "WHERE attempt_id=? AND state='SUBMISSION_UNCONFIRMED'",
                    (sealed.attempt_id,),
                )
                state = "REMOTE_OUTCOME_UNKNOWN"
            if state == "SUBMISSION_UNCONFIRMED" and observed:
                reason = "B37C_DURABLE_MOCK_OBSERVATION_RECONCILE_ONLY"
            elif state == "MOCK_COMPLETED" and observed:
                reason = "B37C_ALREADY_MOCK_SETTLED_NO_REPLAY"
            else:
                reason = "B37C_HOLD_UNKNOWN_OR_CLOSED_NO_AUTO_RETRY"
            return _safe(state, reason, sealed=sealed, observed=observed)
        return self.ledger._transaction(recover)

    def observe_mock(self, sealed, *, current_binding, events):
        """Reuse B33's atomic response-ID + digest observation, synthetic only.

        B37-C's immutability trigger holds request ID/SHA/binding invariant
        across B33's separate observation transaction. No model or HTTP call.
        """
        bound = self._preflight(sealed, current_binding)
        self.ledger._transaction(
            lambda: self._checked(sealed.attempt_id, sealed, bound)
        )
        return self.observed.observe_mock(
            sealed.attempt_id, json.loads(bound), events
        )

    def settle_mock(self, sealed, *, current_binding, events, witness):
        """Reuse B33 independent mock witness and atomic mock cost settlement."""
        bound = self._preflight(sealed, current_binding)
        self.ledger._transaction(
            lambda: self._checked(sealed.attempt_id, sealed, bound)
        )
        return self.observed.settle_mock(
            sealed.attempt_id, json.loads(bound), events, witness
        )

    def cancel_mock(self, attempt_id):
        return self.observed.cancel_mock(attempt_id)

    def revoke_if_changed(self, attempt_id, changed_binding):
        return self.observed.revoke_if_changed(attempt_id, changed_binding)

    def snapshot(self, attempt_id):
        row = self.ledger._attempt(attempt_id)
        return _safe(
            row["state"], "B37C_SNAPSHOT_NOT_DISPATCH_AUTHORITY",
            observed=row["b33_observed_digest"] is not None,
        )

    def require_real_dispatch(self, *_args, **_kwargs):
        _deny("NO_REAL_TRANSPORT_OR_HOSPITAL_AUTHORITY")
