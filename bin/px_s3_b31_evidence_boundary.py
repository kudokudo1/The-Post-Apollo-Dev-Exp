#!/usr/bin/env python3
"""EXEC-S3 B31: synthetic, in-process provider-evidence boundary experiment.

No model client, network, SDK, credential, live Hospital record or real bill.
The issuer is TEST CODE, not an authenticated server or security primitive.
Opaque object identity simulates a separate transport-owned observation.
Do not use this module to certify or admit a real provider.
"""
import hashlib
import json
import weakref

from px_s3_b27_stream_compat import FixtureRefusal, normalize_documented_stream
from px_s3_b25_responses_fixture import consume_fixture_stream
from px_s3_b29_transport_ledger import Refused, SyntheticLedger, canonical_binding

VALID_OUTPUT = frozenset(("COMPLETED_TEXT", "UNTRUSTED_FUNCTION_PROPOSAL"))


def _deny(code):
    raise Refused("B31_REFUSED_" + code)


def _digest(events):
    if type(events) is not list or not 2 <= len(events) <= 64:
        _deny("EVENTS_SHAPE")
    try:
        data = json.dumps(events, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        _deny("EVENTS_ENCODING")
    if len(data) > 262144:
        _deny("EVENTS_BUDGET")
    return hashlib.sha256(data).hexdigest()


class _FixtureWitness:
    __slots__ = ("__weakref__",)
    # No caller-writable payload. Issuer keeps observed metadata separately.


class TestOnlyEvidenceIssuer:
    """Models a controlled observer, but explicitly does not authenticate one."""

    def __init__(self):
        self._issued = weakref.WeakKeyDictionary()

    def issue_test_only(self, *, attempt_id, client_request_id, binding,
                        response_id, events, usage_units, status="completed"):
        """Construct mock observation OUTSIDE model output, from test harness.

        A caller that can execute arbitrary Python here can impersonate
        the issuer. Real provenance requires a separately certified transport.
        """
        bound = canonical_binding(binding)
        if (type(attempt_id) is not str or type(client_request_id) is not str or
                type(response_id) is not str or
                not all(1 <= len(v) <= 96 and
                        all(c.isascii() and (c.isalnum() or c in "_.-") for c in v)
                        for v in (attempt_id, client_request_id, response_id))):
            _deny("OBSERVER_ID")
        if type(usage_units) is not int or usage_units < 0:
            _deny("OBSERVER_USAGE")
        if type(status) is not str or status not in (
                "completed", "failed", "cancelled", "cancelling"):
            _deny("OBSERVER_STATUS")
        witness = _FixtureWitness()
        self._issued[witness] = {
            "attempt": attempt_id, "client": client_request_id,
            "binding": bound, "response": response_id,
            "digest": _digest(events), "usage": usage_units,
            "status": status,
        }
        return witness

    def _take(self, witness):
        # Exact class avoids subclasses that could alter behavior. Consume
        # on FIRST presentation: neither rejection nor crash permits reuse.
        if type(witness) is not _FixtureWitness:
            _deny("UNTRUSTED_EVIDENCE")
        try:
            return self._issued.pop(witness)
        except KeyError:
            _deny("UNTRUSTED_OR_REPLAYED_EVIDENCE")


class OfflineEvidenceBoundary:
    """Runs only over an explicitly caller-supplied disposable B29 database."""

    def __init__(self, connection, issuer):
        if type(issuer) is not TestOnlyEvidenceIssuer:
            _deny("TEST_ISSUER_REQUIRED")
        self.issuer = issuer
        self.ledger = SyntheticLedger(connection)
        self.ledger.initialize()

    def reserve(self, *, attempt_id, client_request_id, scope, binding,
                units=20, mode="FOREGROUND_STREAM"):
        return self.ledger.reserve(
            attempt_id=attempt_id, client_request_id=client_request_id,
            scope=scope, binding=binding, mode=mode, units=units)

    def submit_mock(self, attempt_id, binding):
        return self.ledger.mark_submission(attempt_id, binding)

    def _snapshot(self, attempt_id, reason, *, output_state=None):
        row = self.ledger.state(attempt_id)
        return {
            "state": row["state"], "reason": reason,
            "attemptId": row["attemptId"], "responseId": row["responseId"],
            "reservedUnits": row["reservedUnits"],
            "validatedFixtureOutput": output_state,
            "realProviderObserved": False, "realSpendVerified": False,
            "realStopVerified": False, "launchAuthorized": False,
            "toolDispatchAuthorized": False, "retryAuthorized": False,
            "productionReady": False, "realProviderCalls": 0,
        }

    def accept_and_mock_settle(self, *, attempt_id, binding, events,
                               evidence):
        """Require separate fixture-observer metadata and model event shape.

        Does NOT settle actual invoices. Does NOT consume real network
        responses. Only B29 atomically updates fake budget units.
        """
        # Authority check fences stale Bed, Room, Patient and generation.
        bound = canonical_binding(binding)
        row = self.ledger.revoke_if_changed(attempt_id, binding)
        if row["state"] != "SUBMISSION_UNCONFIRMED":
            _deny("TURN_NOT_ACTIVE")
        # Observed evidence is an in-memory capability, never a model JSON
        # boolean, copied dict or caller-supplied usage number.
        obs = self.issuer._take(evidence)
        if (obs["attempt"] != attempt_id or
                obs["client"] != row["clientRequestId"] or
                obs["binding"] != bound or
                obs["status"] != "completed" or
                obs["digest"] != _digest(events)):
            _deny("EVIDENCE_SCOPE_OR_STATUS")

        try:
            normalized = normalize_documented_stream(events)
        except FixtureRefusal:
            _deny("STREAM_INVALID")
        result = consume_fixture_stream(normalized)
        if (result["state"] not in VALID_OUTPUT or
                normalized[0]["type"] != "response.created" or
                normalized[-1]["type"] != "response.completed"):
            _deny("STREAM_UNFINISHED")
        response_id = normalized[0]["response"]["id"]
        if response_id != obs["response"]:
            _deny("EVIDENCE_RESPONSE_MISMATCH")
        # Server-usage spoofing in the stream cannot affect settlement.
        # Mock usage originates only from the separate test issuer record.
        self.ledger.bind_mock_response(attempt_id, response_id)
        self.ledger.reconcile_mock_completed(
            attempt_id, response_id, obs["usage"], binding)
        return self._snapshot(attempt_id,
                              "B31_MOCK_EVIDENCE_NOT_AUTHENTICATED",
                              output_state=result["state"])

    def interrupt_mock(self, attempt_id):
        self.ledger.transport_lost(attempt_id)
        return self._snapshot(attempt_id, "B31_DELIVERY_UNKNOWN_NO_REPLAY")

    def cancel_mock(self, attempt_id):
        self.ledger.cancel(attempt_id)
        return self._snapshot(attempt_id, "B31_REMOTE_CANCEL_UNVERIFIED")

    def revoke_if_changed(self, attempt_id, binding):
        self.ledger.revoke_if_changed(attempt_id, binding)
        return self._snapshot(attempt_id, "B31_AUTHORITY_RECHECK")
