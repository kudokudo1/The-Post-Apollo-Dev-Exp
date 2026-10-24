#!/usr/bin/env python3
"""EXEC-S3 B33: offline, durable observation-to-settlement continuity proof.

Test-only extension of the disposable B29 SQLite fixture, integrating pinned
B30/B31/B32. A SHA-256 fingerprint is *not* provider authentication, an
attestation, or protection against an actor with SQLite write authority.
Never use this fixture for real spend, credentials, provider or tool dispatch.
"""
import sqlite3

from px_s3_b29_transport_ledger import (
    Refused, SyntheticLedger, STATES_HOLD, canonical_binding,
)
from px_s3_b30_integrated_fixture import OfflineIntegratedTurn
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer, _snapshot_events
from px_s3_b32_staged_evidence import StagedOfflineEvidenceTurn


def _deny(reason):
    raise Refused("B33_REFUSED_" + reason)


SCHEMA_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS b33_fixture_observation_immutable
BEFORE UPDATE OF b33_observed_digest, response_id ON b29_fixture_attempts
WHEN OLD.b33_observed_digest IS NOT NULL AND
     (NEW.b33_observed_digest IS NOT OLD.b33_observed_digest OR
      NEW.response_id IS NOT OLD.response_id)
BEGIN
    SELECT RAISE(ABORT, 'B33_OBSERVATION_IMMUTABLE');
END;
"""


class DurableObservedFixture:
    """Synthetic-only bridge over the same caller-provided disposable DB."""

    def __init__(self, connection, test_issuer):
        if type(test_issuer) is not TestOnlyEvidenceIssuer:
            _deny("TEST_ISSUER_REQUIRED")
        self._joint = StagedOfflineEvidenceTurn(connection, test_issuer)
        self._issuer = test_issuer
        self.ledger = self._joint.ledger
        self._install_fixture_extension()

    def _install_fixture_extension(self):
        # B29 has already refused other table names and checked its fixture
        # marker. No real Hospital DB is ever opened by this bridge.
        columns = {
            row["name"]: row for row in self.ledger.conn.execute(
                "PRAGMA table_info(b29_fixture_attempts)"
            )
        }
        if "b33_observed_digest" not in columns:
            self.ledger.conn.execute(
                "ALTER TABLE b29_fixture_attempts "
                "ADD COLUMN b33_observed_digest TEXT"
            )
        elif columns["b33_observed_digest"]["type"] != "TEXT":
            _deny("OBSERVATION_COLUMN_SCHEMA")
        self.ledger.conn.executescript(SCHEMA_TRIGGER)

    def configure_mock_budget(self, scope, limit_units):
        return self._joint.configure_mock_budget(scope, limit_units)

    def reserve(self, *, attempt_id, client_request_id, scope, binding,
                units, mode="FOREGROUND_STREAM"):
        return self._joint.reserve(
            attempt_id=attempt_id, client_request_id=client_request_id,
            scope=scope, binding=binding, units=units, mode=mode
        )

    def submit_mock(self, attempt_id, current_binding):
        return self._joint.begin_simulated(attempt_id, current_binding)

    def snapshot(self, attempt_id):
        result = self._joint.snapshot(attempt_id)
        row = self.ledger._attempt(attempt_id)
        result["durableEventDigestBound"] = row["b33_observed_digest"] is not None
        return result

    def _validated_snapshot(self, events):
        # B31 snapshots the source batch ONCE, then B30 validates exactly
        # that copy with B27+B25. No post-hash mutable-list substitution.
        frozen, digest = _snapshot_events(events)
        validated, reason = self._joint._stream._validate(frozen)
        return frozen, digest, validated, reason

    def _authority_or_fence(self, row, binding_json):
        if row["binding_json"] == binding_json:
            return False
        # Keep ambiguous post-submission spending reservations held.
        if row["state"] in STATES_HOLD:
            self.ledger.conn.execute(
                "UPDATE b29_fixture_attempts "
                "SET state='REVOKED_REMOTE_UNKNOWN' WHERE attempt_id=?",
                (row["attempt_id"],)
            )
            return True
        if row["state"] == "RESERVED":
            self.ledger.conn.execute(
                "UPDATE b29_fixture_attempts "
                "SET state='REVOKED_PRE_SUBMISSION' WHERE attempt_id=?",
                (row["attempt_id"],)
            )
            self.ledger.conn.execute(
                "UPDATE b29_fixture_budgets "
                "SET reserved_units=reserved_units-? WHERE scope=?",
                (row["reserved_units"], row["scope"])
            )
        return True

    def observe_mock(self, attempt_id, current_binding, events):
        binding_json = canonical_binding(current_binding)
        _, digest, validated, reason = self._validated_snapshot(events)
        if reason is not None:
            # Invalid or interrupted observations are never recorded as
            # completed and cannot subsequently release budget.
            self._joint.revoke_if_changed(attempt_id, current_binding)
            self._joint.interrupted_simulated(attempt_id)
            _deny("STREAM_UNCERTAIN")
        response_id = validated["responseId"]

        def op():
            row = self.ledger._attempt(attempt_id)
            if self._authority_or_fence(row, binding_json):
                return "REVOKED"
            if row["state"] != "SUBMISSION_UNCONFIRMED":
                _deny("NOT_ACTIVE")
            if row["response_id"] is not None:
                # Reject legacy B30 records without original content digest.
                if row["b33_observed_digest"] is None:
                    _deny("LEGACY_OBSERVATION_UNBOUND")
                if (row["response_id"] != response_id or
                        row["b33_observed_digest"] != digest):
                    _deny("OBSERVATION_DRIFT")
                return "ALREADY_BOUND_IDENTICALLY"
            try:
                self.ledger.conn.execute(
                    "UPDATE b29_fixture_attempts SET response_id=?, "
                    "b33_observed_digest=? WHERE attempt_id=?",
                    (response_id, digest, attempt_id)
                )
            except sqlite3.IntegrityError:
                _deny("RESPONSE_ID_REPLAY")
            return "OBSERVED_ATOMICALLY"

        result = self.ledger._transaction(op)
        if result == "REVOKED":
            _deny("AUTHORITY_CHANGED")
        return {**self.snapshot(attempt_id), "reason": result}

    def settle_mock(self, attempt_id, current_binding, events, witness):
        """Compare persisted observation and settle mock budget in ONE txn.

        No API information is trusted. B31's issuer is test Python; real
        network provenance, billing and remote cancellation are still absent.
        """
        bound = canonical_binding(current_binding)
        _, digest, validated, reason = self._validated_snapshot(events)
        if reason is not None:
            _deny("STREAM_UNVERIFIED")
        response_id = validated["responseId"]

        def op():
            row = self.ledger._attempt(attempt_id)
            if self._authority_or_fence(row, bound):
                return "REVOKED"
            if row["state"] != "SUBMISSION_UNCONFIRMED":
                _deny("NOT_ACTIVE")
            if (row["b33_observed_digest"] is None or
                    row["response_id"] is None):
                _deny("OBSERVATION_REQUIRED")
            if row["response_id"] != response_id:
                _deny("RESPONSE_ID_DRIFT")
            if row["b33_observed_digest"] != digest:
                _deny("OBSERVED_BATCH_MISMATCH")

            # The *test-only* issuer supplies mock billing independently
            # from model events. Consume witness on first presentation.
            evidence = self._issuer._take(witness)
            if (evidence["attempt"] != attempt_id or
                    evidence["client"] != row["client_request_id"] or
                    evidence["binding"] != bound or
                    evidence["status"] != "completed" or
                    evidence["response"] != response_id or
                    evidence["digest"] != digest):
                _deny("MOCK_EVIDENCE_MISMATCH")
            usage = evidence["usage"]
            if type(usage) is not int or not 0 <= usage <= row["reserved_units"]:
                _deny("MOCK_USAGE_EXCEEDS_HOLD")
            self.ledger.conn.execute(
                "UPDATE b29_fixture_budgets SET "
                "reserved_units=reserved_units-?, used_units=used_units+? "
                "WHERE scope=?", (row["reserved_units"], usage, row["scope"])
            )
            self.ledger.conn.execute(
                "UPDATE b29_fixture_attempts "
                "SET state='MOCK_COMPLETED', mock_usage=? WHERE attempt_id=?",
                (usage, attempt_id)
            )
            return "MOCK_SETTLED_CONTINUOUS"

        result = self.ledger._transaction(op)
        if result == "REVOKED":
            _deny("AUTHORITY_CHANGED")
        return {**self.snapshot(attempt_id), "reason": result,
                "validatedFixtureOutput": validated["result"]["state"]}

    def interrupt_mock(self, attempt_id):
        return self._joint.interrupted_simulated(attempt_id)

    def cancel_mock(self, attempt_id):
        return self._joint.cancel_simulated(attempt_id)

    def revoke_if_changed(self, attempt_id, current_binding):
        return self._joint.revoke_if_changed(attempt_id, current_binding)
