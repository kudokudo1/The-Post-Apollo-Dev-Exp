"""B36-H11.5: INERT Python-only simulation of a PX-authenticated tool broker.

Not a Hermes adapter, not an OS sandbox, and not a production authority.
There is deliberately no subprocess, socket, filesystem, credential, Hospital,
or arbitrary handler call. Only a fixed in-memory fixture counter can run.
"""
from dataclasses import dataclass


SCOPE_FIELDS = frozenset(("patient", "room", "assignment", "session", "turn", "generation"))
FAKE_TOOL = "fixture_counter"
MODES = frozenset(("FIRST_TURN", "REQUESTED_RESUME"))


def _scope_tuple(value):
    """Require a complete typed six-part scope; never echo untrusted input."""
    if type(value) is not dict or set(value) != SCOPE_FIELDS:
        return None
    for key in SCOPE_FIELDS - {"generation"}:
        if type(value[key]) is not str or not value[key] or len(value[key]) > 80:
            return None
    if type(value["generation"]) is not int or value["generation"] < 1:
        return None
    return tuple(value[key] for key in
                 ("patient", "room", "assignment", "session", "turn", "generation"))


@dataclass(frozen=True)
class _FakeTicket:
    """Identity-only token: not cryptographic, serializable, or production-safe."""
    tool: str
    scope: tuple
    generation: int
    mode: str
    resume_identity: str
    epoch: int


class FakeAuthority:
    """Controlled directly by the test's synthetic trusted-supervisor lane."""

    def __init__(self):
        self.scope = ("fake-patient", "fake-room", "fake-assignment",
                      "fake-session", "fake-turn", 7)
        self.generation = 7
        self.epoch = 1
        self.paused = False
        self.tool_allowed = True
        self.resume_identity = "fake-provider-session"
        self.resume_revalidated = False

    def current_scope(self):
        return dict(zip(("patient", "room", "assignment", "session", "turn", "generation"), self.scope))

    def _advance(self):
        self.generation += 1
        self.scope = (*self.scope[:-1], self.generation)

    def pause(self):
        self.paused = True
        self._advance()

    def revoke_tool(self):
        self.tool_allowed = False
        self._advance()

    def change_assignment(self):
        self.scope = (*self.scope[:2], "replacement-assignment", *self.scope[3:-1], self.generation)
        self._advance()

    def mark_resume_revalidated(self):
        self.resume_revalidated = True

    def restart(self):
        self.epoch += 1
        self.resume_revalidated = False


class FakeBroker:
    """Fixture-only controlled-dispatch demonstration, never launch authority."""

    def __init__(self, authority):
        self.authority = authority
        self._pending = {}
        self.fake_handler_calls = 0

    def _result(self, reason, executed=False):
        return {
            "decision": "OFFLINE_FAKE_EXECUTED" if executed else "DENY",
            "reason": reason,
            "fakeHandlerCalls": self.fake_handler_calls,
            "launchAuthorized": False,
            "productionReady": False,
            "modelCalls": 0,
            "providerCalls": 0,
            "hospitalWrites": 0,
        }

    def from_model_or_native(self, tool, arguments=None, alleged_grant=None):
        """A model, native plugin, bridge or MCP client cannot mint fixture grants."""
        return self._result("UNTRUSTED_DISPATCH_ORIGIN")

    def trusted_queue_fixture(self, tool, claimed_scope, mode="FIRST_TURN",
                              resume_identity=""):
        """Test-only stand-in for a checked PX dispatch barrier.

        This method is NOT exposed by a real model-facing interface. Only the
        test drives it, with a completely synthetic authority object.
        """
        scope = _scope_tuple(claimed_scope)
        a = self.authority
        if scope is None:
            return self._result("SCOPE_INVALID")
        if scope != a.scope or scope[-1] != a.generation:
            return self._result("STALE_OR_FOREIGN_AUTHORITY")
        if a.paused or not a.tool_allowed:
            return self._result("AUTHORITY_REVOKED")
        if tool != FAKE_TOOL:
            return self._result("TOOL_NOT_GRANTED")
        if mode not in MODES:
            return self._result("NATIVE_REPLAY_OR_MODE_DENIED")
        if mode == "REQUESTED_RESUME" and (
            not a.resume_revalidated or resume_identity != a.resume_identity
        ):
            return self._result("RESUME_NOT_REVALIDATED")
        ticket = _FakeTicket(tool, scope, a.generation, mode, resume_identity, a.epoch)
        # Exactly this object, rather than a lookalike dict or copy, is eligible.
        self._pending[id(ticket)] = ticket
        return ticket

    def trusted_dispatch_fixture(self, ticket):
        """Consume one synthetic permit before the final launch-time checks."""
        if type(ticket) is not _FakeTicket:
            return self._result("GRANT_NOT_ISSUED")
        issued = self._pending.pop(id(ticket), None)
        if issued is not ticket:
            return self._result("GRANT_NOT_ISSUED_OR_REPLAYED")
        a = self.authority
        if ticket.epoch != a.epoch:
            return self._result("RESTART_INVALIDATED_GRANT")
        if (ticket.scope != a.scope or ticket.generation != a.generation):
            return self._result("STALE_OR_FOREIGN_AUTHORITY")
        if a.paused or not a.tool_allowed:
            return self._result("AUTHORITY_REVOKED")
        if ticket.tool != FAKE_TOOL:
            return self._result("TOOL_NOT_GRANTED")
        if ticket.mode == "REQUESTED_RESUME" and (
            not a.resume_revalidated or ticket.resume_identity != a.resume_identity
        ):
            return self._result("RESUME_NOT_REVALIDATED")
        if ticket.mode not in MODES:
            return self._result("NATIVE_REPLAY_OR_MODE_DENIED")
        # The only "handler" is a counter with no external side effects.
        self.fake_handler_calls += 1
        return self._result("FIXTURE_COUNTER_ONLY", executed=True)
