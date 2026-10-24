#!/usr/bin/env python3
"""EXEC-S3 B32: staged, synthetic-only B30+B31 integration.

Tests B30's offline stream/ledger lifecycle against B31's separate mock
evidence issuer. No actual credentials, network, provider, real billing,
tool execution, or Hospital writes. Not a dispatch/production entry point.

Until PRs #88 and #89 merge, CI imports their exact immutable GitHub commits
using read-only checkouts. This module never fetches those dependencies.
"""
from px_s3_b29_transport_ledger import Refused, canonical_binding
from px_s3_b30_integrated_fixture import OfflineIntegratedTurn
from px_s3_b31_evidence_boundary import (
    OfflineEvidenceBoundary, TestOnlyEvidenceIssuer,
)


def _refuse(code):
    raise Refused("B32_REFUSED_" + code)


class StagedOfflineEvidenceTurn:
    """A single disposable SQLite attempt shared by both existing fixtures."""

    def __init__(self, disposable_connection, test_issuer):
        if type(test_issuer) is not TestOnlyEvidenceIssuer:
            _refuse("TEST_ISSUER_REQUIRED")
        self._stream = OfflineIntegratedTurn(disposable_connection)
        self._evidence = OfflineEvidenceBoundary(
            disposable_connection, test_issuer
        )
        # Both views intentionally refer to the SAME connection and B29 tables.
        if self._stream.ledger.conn is not self._evidence.ledger.conn:
            _refuse("LEDGER_NOT_SHARED")

    @property
    def ledger(self):
        """Exposes only the explicitly mock B29 ledger for fixture inspection."""
        return self._stream.ledger

    def configure_mock_budget(self, scope, limit_units):
        return self._stream.configure_mock_budget(scope, limit_units)

    def reserve(self, *, attempt_id, client_request_id, scope, binding,
                units, mode="FOREGROUND_STREAM"):
        return self._stream.reserve(
            attempt_id=attempt_id, client_request_id=client_request_id,
            scope=scope, binding=binding, units=units, mode=mode
        )

    def begin_simulated(self, attempt_id, current_binding):
        return self._stream.submit_simulated(attempt_id, current_binding)

    def observe_simulated(self, attempt_id, current_binding, events):
        """B30 validates structure and durably binds an UNTRUSTED response ID."""
        return self._stream.observe_simulated(
            attempt_id, current_binding, events
        )

    def settle_with_independent_mock_evidence(
            self, attempt_id, current_binding, events, mock_witness):
        """Require B30 observation before allowing B31 mock settlement.

        A caller's event list, response ID, model usage, or status cannot
        serve as witness. B31 independently validates and snapshots events.
        B29 rechecks authority and atomically settles *mock* budget.
        """
        canonical_binding(current_binding)
        # The B30 recheck permanently fences changed full Hospital authority,
        # including Bed and generation. Do not rely on an old observed snapshot.
        state = self._stream.revoke_if_changed(
            attempt_id, current_binding
        )
        if state["state"] != "SUBMISSION_UNCONFIRMED":
            _refuse("NOT_ACTIVE")
        # No evidence may settle a turn that was never structurally observed
        # by B30, even if a mock issuer can mint a valid object.
        if state["responseId"] is None:
            _refuse("B30_OBSERVATION_REQUIRED")
        # B31 consumes a witness exactly once, validates event batch and
        # response identity, then makes a separate B29 SQLite transaction.
        return self._evidence.accept_and_mock_settle(
            attempt_id=attempt_id, binding=current_binding,
            events=events, evidence=mock_witness
        )

    def interrupted_simulated(self, attempt_id):
        return self._stream.interrupt_simulated(attempt_id)

    def cancel_simulated(self, attempt_id):
        return self._stream.cancel_simulated(attempt_id)

    def mock_background_cancel(self, attempt_id, response_id, status):
        return self._stream.background_cancel_observed(
            attempt_id, response_id, status
        )

    def checkpoint_simulated_cursor(
            self, attempt_id, current_binding, events):
        return self._stream.checkpoint_simulated_cursor(
            attempt_id, current_binding, events
        )

    def revoke_if_changed(self, attempt_id, current_binding):
        return self._stream.revoke_if_changed(attempt_id, current_binding)

    def snapshot(self, attempt_id):
        """Durable B29 facts only. Ephemeral B31 witnesses are not serialized."""
        state = self._stream.snapshot(attempt_id)
        state["witnessPersisted"] = False
        state["realProviderObserved"] = False
        state["realSpendVerified"] = False
        state["realStopVerified"] = False
        return state
