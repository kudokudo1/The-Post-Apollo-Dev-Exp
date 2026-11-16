# PXD EXEC-S3 // B36-H11.5 Hermes fake-only dispatch refusal

> STATE // DRAFT · TEST-ONLY · REVIEW REQUIRED
> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (Hospital-compatible; not live-registered)
> ASSIGNMENT // H11.5 negative model-to-tool dispatch and generation/replay probes
> PRODUCTION // HOLD · REAL PROVIDER ADMISSION DENY

## IMPLEMENTATION

A standalone in-memory fixture under `tests/fixtures/pxd_b36_h115_fake_dispatch.py`
models a **synthetic** supervisor authority, an explicitly trusted *test-only*
ticket issuance lane, and a broker whose sole possible handler increments an
in-memory counter. The test file `tests/test-pxd-exec-s3-b36-h115-fake-dispatch.py`
exercises fake model/native attempts and dispatch after stale authority.

This is not a patch to `bin/px-agent`, Hermes, its installed `tools/registry.py`,
Hospital, or B37-A/B37-B. It deliberately has **no** provider transport, Hermes
import, native process, real OS grant, credentials, filesystem operation, network,
production dispatcher, or durable Hospital write. The issuance method is a
*test fixture*, not an implemented authorization endpoint. Identity-only fake
tickets do not represent cryptographically authenticated broker grants.

## HOW TO USE

Run in an isolated checkout or CI:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b36-h115-fake-dispatch.py
```

Only the fixed `fixture_counter` tool can be positively dispatched by the
synthetic trusted lane. `OFFLINE_FAKE_EXECUTED` means only that the test counter
incremented; it is not an authorization to launch anything.

## VERIFY

Negative cases require the fake handler count to remain **zero**:

- Model/native/hidden-plugin/`tool_call` attempts, even with an alleged grant.
- Unknown tool capability, malformed/foreign scope, mismatched Patient/Room.
- Queued ticket invalidated by pause, permission withdrawal, Assignment change.
- Forged fake ticket, repeated ticket, invalid modes, unsolicited native resume.
- Resume without renewed validation or matching fake session identity.
- Restart invalidates queued ticket; disabled/paused authority cannot issue more.
- Untrusted payload redaction; all fixture outcomes keep launchAuthorized=false.

A separate positive control increments the **in-memory** counter to prove tests
are not trivially passing because the handler is unreachable. It does not prove
real Hermes cannot bypass this fake broker. For previously executed permits, a
replay denial asserts **no additional** increment, not total calls zero.

This fixture is inspired by installed Hermes revision
`5cc1369fa298021f8c740de154ff8c37c30bdcc8` and source inspection of
`model_tools.py`, `agent/tool_executor.py`, `agent/conversation_loop.py`, and
`tools/registry.py`. It **does not import or exercise that Hermes code**.

## WATCH OUT FOR

- A true Hermes native bypass may never pass through this modeled PX broker.
  The test cannot demonstrate provider-wide interception or disablement.
- No real trusted authority barrier, revocation interruption of running tools,
  race serialization, authenticated IPC, kernel verification, credentials,
  or provider first/resume tool-free operation has been established.
- H10.2 Fedora Bubblewrap/cgroup success is separate host evidence and does
  not certify Hermes model-only mode.
- Keep B24 production denial; no auto merge or service activation.

## CHECKLIST

- [x] Fake-only negative dispatch fixture and inert counter positive control
- [ ] CI pass on exact branch head
- [ ] Independent review and operator acceptance
- [ ] Separate implementation decision for a production launch-time barrier
- [ ] Authenticated provider and native tool suppression verification

## NEXT

Review the artificial boundaries and their gaps before making any proposal to
intercept real Hermes tool handlers or modify PX provider launch/resume logic.
Reacquire live GitHub and Hospital ownership state before further changes.

## DECISIONS

Only bounded GitHub test/contract/CI modifications are authorized for H11.5.
No live Fedora or Hermes mutation, credential use, real broker, provider
admission, or Hospital persistence. Production remains HOLD.
