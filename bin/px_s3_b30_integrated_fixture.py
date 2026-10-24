#!/usr/bin/env python3
"""B30: detached B27+B29 integration over caller-owned disposable SQLite.

NO real transport, SDK, secret, Hospital I/O, provider, tool broker or billing.
Synthetic response streams are UNTRUSTED, including their IDs and usage.
Never use these simulator observations as real provider attestation.
"""
from px_s3_b27_stream_compat import (
    FixtureRefusal, normalize_documented_stream,
)
from px_s3_b25_responses_fixture import consume_fixture_stream
from px_s3_b29_transport_ledger import SyntheticLedger, canonical_binding, Refused

SUCCESS = frozenset(("COMPLETED_TEXT", "UNTRUSTED_FUNCTION_PROPOSAL"))


def _deny(reason):
    raise Refused("B30_REFUSED_" + reason)


def _inert(result, reason, *, observation=None):
    """Return only fixture diagnostics; no production authorization."""
    state = result["state"]
    answer = {
        "state": state, "reason": reason,
        "attemptId": result["attemptId"], "responseId": result["responseId"],
        "reservedUnits": result["reservedUnits"], "cursor": result["cursor"],
        "validatedMockText": "", "untrustedProposalCount": 0,
        "realProviderCalls": 0, "realSpendVerified": False,
        "realStopVerified": False, "retryAuthorized": False,
        "toolDispatchAuthorized": False, "launchAuthorized": False,
        "productionReady": False,
    }
    if observation is not None and observation["state"] in SUCCESS:
        answer["validatedMockText"] = observation["text"]
        answer["untrustedProposalCount"] = len(observation["proposals"])
    return answer


class OfflineIntegratedTurn:
    """One disposable fixture turn; durable source of truth is B29 ledger."""

    def __init__(self, connection):
        self.ledger = SyntheticLedger(connection)
        self.ledger.initialize()

    def configure_mock_budget(self, scope, units):
        return self.ledger.configure_mock_budget(scope, units)

    def reserve(self, *, attempt_id, client_request_id, scope, binding,
                mode="FOREGROUND_STREAM", units=20):
        return self.ledger.reserve(
            attempt_id=attempt_id, client_request_id=client_request_id,
            scope=scope, binding=binding, mode=mode, units=units)

    def submit_simulated(self, attempt_id, current_binding):
        # B29 transitions to UNCONFIRMED before any fake stream is received.
        return self.ledger.mark_submission(attempt_id, current_binding)

    def snapshot(self, attempt_id):
        return _inert(self.ledger.state(attempt_id), "B30_LEDGER_SNAPSHOT")

    def _active(self, attempt_id, current_binding):
        """Full B29 binding includes BED; B27's narrower fields are insufficient."""
        canonical_binding(current_binding)
        current = self.ledger.revoke_if_changed(attempt_id, current_binding)
        if current["state"] != "SUBMISSION_UNCONFIRMED":
            _deny("NOT_ACTIVE_OR_REVOKED")
        return current

    def _validate(self, events):
        # Normalizer enforces B27 event lifecycles; existing B25 reducer
        # refuses malformed arguments, extra tool calls and unknown output.
        # Require a materialized list so IDs and sequence cannot mutate
        # between iterative normalization and the ID check.
        if type(events) is not list or not 1 <= len(events) <= 64:
            return None, "B30_INVALID_EVENT_BATCH"
        try:
            normalized = normalize_documented_stream(events)
        except FixtureRefusal as exc:
            return None, str(exc)
        result = consume_fixture_stream(normalized)
        if result["state"] not in SUCCESS:
            return None, result["reason"]
        if (len(normalized) < 2 or normalized[0].get("type") != "response.created"
                or normalized[-1].get("type") != "response.completed"):
            return None, "B30_UNFINISHED_STREAM"
        return {
            "responseId": normalized[0]["response"]["id"],
            "result": result,
        }, None

    def observe_simulated(self, attempt_id, current_binding, events):
        """Accept a MOCK completed stream for display only, never dispatch.

        Unsafe or truncated streams turn the ledger into an uncertain hold.
        No budget is released and no tool request is executed from this step.
        """
        self._active(attempt_id, current_binding)
        validated, error = self._validate(events)
        if error is not None:
            row = self.ledger.transport_lost(attempt_id)
            return _inert(row, error)
        # B29 pins response identity durably and forbids foreign/replayed IDs.
        row = self.ledger.bind_mock_response(attempt_id, validated["responseId"])
        return _inert(row, "B30_MOCK_OBSERVED_NOT_SETTLED",
                      observation=validated["result"])

    def settle_simulated(self, attempt_id, current_binding, events, usage_units):
        """Explicit MOCK settlement after B27+B25 validation, no real billing.

        Crash before this B29 transaction => reserved hold remains.
        After reopen caller must revalidate the entire stream. A failed or
        duplicate settlement cannot free budget or authorize replay.
        """
        self._active(attempt_id, current_binding)
        validated, error = self._validate(events)
        if error is not None:
            row = self.ledger.transport_lost(attempt_id)
            return _inert(row, error)
        row = self.ledger.bind_mock_response(attempt_id, validated["responseId"])
        # B29 transaction atomically exchanges mock reserved->mock used.
        settled = self.ledger.reconcile_mock_completed(
            attempt_id, validated["responseId"], usage_units, current_binding)
        return _inert(settled, "B30_MOCK_SETTLED_NOT_REAL_BILLING",
                      observation=validated["result"])

    def checkpoint_simulated_cursor(self, attempt_id, current_binding, events):
        """A completed B27-valid event prefix can advance a MOCK BG cursor.

        B27 normalizer accepts a bounded unfinished prefix, but no assertion
        of delivery/recovery/trusted remote ownership follows from the cursor.
        """
        row = self._active(attempt_id, current_binding)
        if row["mode"] != "BACKGROUND_POLL" or row["responseId"] is None:
            _deny("CURSOR_MODE_OR_ID")
        if type(events) is not list or not 2 <= len(events) <= 64:
            _deny("CURSOR_EVENTS")
        try:
            norm = normalize_documented_stream(events)
        except FixtureRefusal:
            _deny("CURSOR_UNVALIDATED")
        if (norm[0]["response"]["id"] != row["responseId"] or
                norm[-1]["type"] in ("response.failed", "response.incomplete", "error")):
            _deny("CURSOR_RESPONSE_DRIFT")
        # Use original (not renumbered) B27-verified source sequence.
        cursor = events[-1]["sequence_number"]
        updated = self.ledger.stream_cursor(attempt_id, cursor)
        return _inert(updated, "B30_MOCK_CURSOR_ONLY")

    def interrupt_simulated(self, attempt_id):
        return _inert(self.ledger.transport_lost(attempt_id),
                      "B30_UNKNOWN_DELIVERY_NO_RETRY")

    def revoke_if_changed(self, attempt_id, current_binding):
        return _inert(self.ledger.revoke_if_changed(attempt_id, current_binding),
                      "B30_AUTHORITY_RECHECK")

    def cancel_simulated(self, attempt_id):
        return _inert(self.ledger.cancel(attempt_id),
                      "B30_CANCEL_REMOTE_STOP_UNVERIFIED")

    def background_cancel_observed(self, attempt_id, response_id, status):
        return _inert(self.ledger.observe_mock_background_cancel(
            attempt_id, response_id, status), "B30_MOCK_CANCEL_NOT_REMOTE_PROOF")
