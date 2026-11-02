#!/usr/bin/env python3
"""B38-B: synthetic PX-owned sender barrier; NO network, auth or provider launch.

Intentionally separate from the B37-C atomic recovery work. All state is
caller-controlled, in memory, and NOT a trusted Hospital/OS authority source.
The only "send" passes fixed mock text frames into B38-A's fake parser.
"""
from dataclasses import dataclass
import json

from px_s3_b29_transport_ledger import canonical_binding
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture
from px_s3_b37b_sealed_handoff import (
    Refused as B37BRefused, SealedFixture, verify_fixture,
)
from px_s3_b38a_model_only_mock_client import (
    FakeTextStream, Refused as B38ARefused, exchange_mock,
)
from px_s3_b38c_transport_policy_fixture import (
    Refused as B38CRefused, default_fake_manifest, prepare_fake_plan,
    recheck_fake_plan,
)

_FAKE_TEXT = "B38B synthetic text, never a provider response"
_FAKE_AUTH_MATERIAL = "B38B_SENTINEL_NOT_A_REAL_CREDENTIAL"


class Refused(RuntimeError):
    """Fixed diagnostics only; never include payload, fake auth or user text."""


def _deny(code):
    raise Refused("B38B_REFUSED_" + code)


@dataclass(frozen=True, slots=True)
class _MockPermit:
    """Identity-only test ticket; not cryptographically authenticated."""
    request_id: str
    payload_sha256: str
    binding_json: str
    epoch: int
    policy_plan: object  # Synthetic B38-C plan, never a real authorization token.


class MockTrustedSender:
    """Pretend trusted sender lane; contains no pluggable real transport."""

    def __init__(self, binding):
        try:
            binding_json = canonical_binding(binding)
        except Exception:
            _deny("BINDING_INVALID")
        self._binding_json = binding_json
        self._epoch = 1
        self._paused = False
        self._ready = True
        self._pending = {}
        self._fake_auth_material = _FAKE_AUTH_MATERIAL
        self.fake_handoffs = 0

    def _current_binding(self):
        return json.loads(self._binding_json)

    def pause(self):
        self._paused = True
        self._epoch += 1

    def revoke(self):
        self._paused = True
        self._epoch += 1

    def restart(self):
        self._epoch += 1
        self._ready = False

    def change_binding(self, new_binding):
        try:
            next_json = canonical_binding(new_binding)
        except Exception:
            _deny("BINDING_INVALID")
        self._binding_json = next_json
        self._epoch += 1

    def set_mock_ready(self, ready):
        if type(ready) is not bool:
            _deny("READINESS_INVALID")
        self._ready = ready
        self._epoch += 1

    def _check_conditions(self):
        if self._paused:
            _deny("AUTHORITY_PAUSED")
        if not self._ready:
            _deny("MOCK_SENDER_UNAVAILABLE")

    def _verify(self, atomic, sealed):
        if type(atomic) is not AtomicOfflineFixture:
            _deny("B37C_ATOMIC_FIXTURE_REQUIRED")
        if type(sealed) is not SealedFixture:
            _deny("SEAL_TYPE")
        try:
            verify_fixture(sealed, current_binding=self._current_binding())
        except (B37BRefused, ValueError, KeyError, TypeError):
            _deny("SEALED_REQUEST_INVALID")
        try:
            row = atomic.ledger.state(sealed.attempt_id)
        except Exception:
            _deny("FAKE_RESERVATION_REQUIRED")
        if (row["state"] != "RESERVED"
                or row["clientRequestId"] != sealed.client_request_id
                or row["turnId"] != self._current_binding()["turnId"]):
            _deny("FAKE_RESERVATION_MISMATCH")

    def prepare_mock(self, atomic, sealed):
        """Synthetic Stage A/B checks, NOT a verified OS sandbox/readiness."""
        self._check_conditions()
        self._verify(atomic, sealed)
        try:
            policy_plan = prepare_fake_plan(
                default_fake_manifest(), sealed=sealed,
                current_binding=self._current_binding(),
            )
        except B38CRefused:
            _deny("B38C_POLICY_REFUSED")
        ticket = _MockPermit(sealed.client_request_id, sealed.payload_sha256,
                             self._binding_json, self._epoch, policy_plan)
        self._pending[id(ticket)] = ticket
        return ticket

    def send_mock(self, atomic, sealed, ticket):
        """One-use simulated dispatch. No endpoint/transport/callback supplied."""
        if type(ticket) is not _MockPermit:
            _deny("PERMIT_TYPE")
        issued = self._pending.pop(id(ticket), None)
        if issued is not ticket:
            _deny("PERMIT_NOT_ISSUED_OR_REPLAYED")
        if ticket.epoch != self._epoch or ticket.binding_json != self._binding_json:
            _deny("STALE_PERMIT")
        self._check_conditions()
        self._verify(atomic, sealed)
        if (ticket.request_id != sealed.client_request_id
                or ticket.payload_sha256 != sealed.payload_sha256):
            _deny("PERMIT_REQUEST_MISMATCH")
        try:
            policy_result = recheck_fake_plan(
                ticket.policy_plan, default_fake_manifest(),
                sealed=sealed, current_binding=self._current_binding(),
            )
        except B38CRefused:
            _deny("B38C_POLICY_REFUSED")
        if (policy_result.get("decision") != "OFFLINE_SHAPE_ONLY"
                or policy_result.get("transportReady") is not False
                or policy_result.get("launchAuthorized") is not False):
            _deny("B38C_POLICY_RESULT_INVALID")
        # Constructed entirely here. No arbitrary transport function is
        # injectable, and the fake credential is never placed in frames.
        frames = (
            json.dumps({"type": "mock.text.delta", "seq": 0,
                        "text": _FAKE_TEXT}, separators=(",", ":")).encode("ascii"),
            b'{"type":"mock.text.completed","seq":1}',
        )
        stream = FakeTextStream(
            request_id=sealed.client_request_id, offered_bytes=sealed.payload,
            frames=frames,
        )
        try:
            reply = exchange_mock(
                atomic, sealed, current_binding=self._current_binding(),
                stream=stream,
            )
        except (B38ARefused, B37BRefused, ValueError, TypeError, KeyError):
            _deny("FAKE_HANDOFF_REFUSED")
        self.fake_handoffs += 1
        return reply

    def inspect_mock(self):
        """Scrubbed counters, explicitly not network or authority evidence."""
        return {
            "schema": "B38B_FAKE_TRUSTED_SENDER_V1",
            "fakeHandoffs": self.fake_handoffs,
            "realNetworkCalls": 0,
            "realProviderCalls": 0,
            "credentialBoundaryCertified": False,
            "launchAuthorized": False,
            "productionReady": False,
        }


def require_real_sender(*_args, **_kwargs):
    _deny("NO_AUTHENTICATED_SENDER")
