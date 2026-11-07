#!/usr/bin/env python3
"""B38-I: TEST-ONLY durable fake process-launch claim over disposable B37-C SQLite.

This is an offline *ordering fixture*, not an OS spawn transaction, provider
authority, live Hospital identity, or a production cancellation guarantee.
It extends ONLY a caller-supplied, verified B29/B37-C disposable database.
No runtime, network, real credentials, or automatic retry capability exists.
"""
import hashlib
import hmac
import json
import secrets
import sqlite3

from px_s3_b29_transport_ledger import Refused as B29Refused, canonical_binding
from px_s3_b37b_sealed_handoff import (
    Refused as B37BRefused, SealedFixture, verify_fixture,
)
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture

CLAIM_COLUMN = "b38i_fake_launch_claim"
CLAIM_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS b38i_fake_claim_immutable
BEFORE UPDATE OF b38i_fake_launch_claim ON b29_fixture_attempts
WHEN OLD.b38i_fake_launch_claim IS NOT NULL
     AND NEW.b38i_fake_launch_claim IS NOT OLD.b38i_fake_launch_claim
BEGIN
    SELECT RAISE(ABORT, 'B38I_FAKE_CLAIM_IMMUTABLE');
END;
"""

class Refused(RuntimeError):
    """Fixed refusal code, no prompt bytes or model output."""

def _deny(code):
    raise Refused("B38I_REFUSED_" + code)

class AtomicFakeLaunchClaim:
    """One irreversible fake launch claim, serialized with B29 cancel/revoke.

    The linearization point is the successful SQL UPDATE, NOT OS process
    creation. Cancel after that point is *in-flight*, even if Python has not
    yet called Popen. That ambiguity must not become an automatic retry.
    """

    def __init__(self, atomic):
        if type(atomic) is not AtomicOfflineFixture:
            _deny("B37C_FIXTURE_REQUIRED")
        self.atomic = atomic
        self.conn = atomic.conn
        columns = {row["name"]: row for row in self.conn.execute(
            "PRAGMA table_info(b29_fixture_attempts)"
        )}
        if CLAIM_COLUMN not in columns:
            self.conn.execute(
                "ALTER TABLE b29_fixture_attempts "
                "ADD COLUMN b38i_fake_launch_claim TEXT"
            )
        elif columns[CLAIM_COLUMN]["type"] != "TEXT":
            _deny("FAKE_CLAIM_SCHEMA")
        self.conn.executescript(CLAIM_TRIGGER)

    def claim_mock(self, sealed, *, current_binding):
        """Single B29 BEGIN IMMEDIATE transaction, same lock as cancel/revoke.

        A caller may attempt a fake process at most once after this record.
        Crash before or after spawn leaves claim durable; never replay it.
        """
        if type(sealed) is not SealedFixture:
            _deny("SEALED_FIXTURE_REQUIRED")
        try:
            bound = canonical_binding(current_binding)
            verify_fixture(sealed, current_binding=json.loads(bound))
            if hashlib.sha256(sealed.payload).hexdigest() != sealed.payload_sha256:
                _deny("SEALED_BYTES_CHANGED")
        except Refused:
            raise
        except (B37BRefused, B29Refused, KeyError, TypeError, ValueError):
            _deny("SEALED_BINDING_INVALID")

        fake_claim = "b38i.fake." + secrets.token_hex(16)

        def transition():
            row = self.atomic.ledger._attempt(sealed.attempt_id)
            if (row["state"] != "SUBMISSION_UNCONFIRMED" or
                row["mode"] != "FOREGROUND_STREAM" or
                row["response_id"] is not None or
                row["b33_observed_digest"] is not None):
                _deny("NOT_UNCONFIRMED_OR_ALREADY_CLOSED")
            if (row["client_request_id"] != sealed.client_request_id or
                row["binding_json"] != bound or
                row["turn_id"] != json.loads(bound)["turnId"] or
                row["b37c_payload_sha256"] is None or
                not hmac.compare_digest(
                    row["b37c_payload_sha256"], sealed.payload_sha256)):
                _deny("DURABLE_IDENTITY_CHANGED")
            if row[CLAIM_COLUMN] is not None:
                _deny("FAKE_CLAIM_ALREADY_USED")
            cur = self.conn.execute(
                "UPDATE b29_fixture_attempts "
                "SET b38i_fake_launch_claim=? "
                "WHERE attempt_id=? AND state='SUBMISSION_UNCONFIRMED' "
                "AND mode='FOREGROUND_STREAM' AND client_request_id=? "
                "AND binding_json=? AND b37c_payload_sha256=? "
                "AND b38i_fake_launch_claim IS NULL AND response_id IS NULL "
                "AND b33_observed_digest IS NULL",
                (fake_claim, sealed.attempt_id, sealed.client_request_id,
                 bound, sealed.payload_sha256)
            )
            if cur.rowcount != 1:
                _deny("FAKE_CLAIM_ATOMIC_CONFLICT")
            return {
                "schema": "B38I_DISPOSABLE_FAKE_CLAIM_V1",
                "state": "SUBMISSION_UNCONFIRMED",
                "fakeLaunchClaimRecorded": True,
                "clientRequestId": sealed.client_request_id,
                "launchAuthorized": False,
                "retryAuthorized": False,
                "productionReady": False,
                "providerStarted": False,
                "realProviderCalls": 0,
                "hospitalWrites": 0,
            }

        try:
            return self.atomic.ledger._transaction(transition)
        except Refused:
            raise
        except (B29Refused, sqlite3.Error):
            _deny("FAKE_CLAIM_STORAGE_UNAVAILABLE")

    def claim_recorded(self, attempt_id):
        """Read-only fixture introspection; never a reusable send permit."""
        try:
            row = self.atomic.ledger._attempt(attempt_id)
            return row[CLAIM_COLUMN] is not None
        except (B29Refused, sqlite3.Error, IndexError):
            _deny("FAKE_CLAIM_SNAPSHOT_UNAVAILABLE")

    def require_real_launch(self, *_args, **_kwargs):
        _deny("NO_REAL_OS_LAUNCH_OR_PROVIDER_AUTHORITY")
