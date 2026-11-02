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
    OfflinePlan, Refused as B38CRefused, default_fake_manifest,
    prepare_fake_plan, recheck_fake_plan,
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
    policy_plan: OfflinePlan


class MockTrustedSender:
    """Pretend trusted sender lane; contains no pluggable real transport."""

    def __init__(self, binding, *, mock_manifest=None):
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
        # Caller-controlled *fake* policy description, never OS evidence.
        # A mutable caller manifest is deliberately revalidated at send time.
        self._mock_manifest = (
            default_fake_manifest() if mock_manifest is None else mock_manifest
        )
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
            plan = prepare_fake_plan(
                self._mock_manifest, sealed=sealed,
                current_binding=self._current_binding(),
            )
        except (B38CRefused, ValueError, TypeError, KeyError):
            _deny("FAKE_POLICY_PREPARE_REFUSED")
        ticket = _MockPermit(sealed.client_request_id, sealed.payload_sha256,
                             self._binding_json, self._epoch, plan)
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
        # The one-use permit also binds immutable policy bytes to this seal.
        # Recheck caller-supplied offline shape immediately before mock action;
        # no claim about real OS isolation, credentials, network or readiness.
        try:
            policy = recheck_fake_plan(
                ticket.policy_plan, self._mock_manifest, sealed=sealed,
                current_binding=self._current_binding(),
            )
        except (B38CRefused, ValueError, TypeError, KeyError):
            _deny("FAKE_POLICY_RECHECK_REFUSED")
        forbidden = (
            "credentialBoundaryCertified", "networkPolicyEnforced",
            "osIsolationVerified", "hospitalAuthorityVerified",
            "transportReady", "launchAuthorized", "productionReady",
        )
        counters = ("modelCalls", "networkCalls", "toolCalls", "hospitalWrites")
        if (type(policy) is not dict or
                policy.get("decision") != "OFFLINE_SHAPE_ONLY" or
                policy.get("requestShapeValid") is not True or
                any(policy.get(key) is not False for key in forbidden) or
                any(type(policy.get(key)) is not int or policy[key] != 0
                    for key in counters)):
            _deny("FAKE_POLICY_RECEIPT_INVALID")
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
            "networkPolicyEnforced": False,
            "osIsolationVerified": False,
            "hospitalAuthorityVerified": False,
            "transportReady": False,
            "launchAuthorized": False,
            "productionReady": False,
        }


def require_real_sender(*_args, **_kwargs):
    _deny("NO_AUTHENTICATED_SENDER")
