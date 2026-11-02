# PX EXEC-S3 // B38-A Option A PX-owned model-only mock client

> STATE // IMPLEMENTED IN DRAFT BRANCH · OFFLINE-ONLY · REVIEW REQUIRED
> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // Hermes Integration Security (Hospital-compatible; not live-attached)
> ASSIGNMENT // Option A first slice: a PX-owned, non-Hermes, text-only client consuming mock stream frames
> SOURCE // PX main e5b773a0ac23c5453c2144d24457ab9435d86231; H11.6 design merged in PR #107
> AUTHORITY // Operator selected Option A on 2026-11-02; bounded fake-only GitHub implementation
> PRODUCTION // HOLD · B24 real-provider admission unchanged

## IMPLEMENTATION

The operator selected **Option A** from H11.6: a separate PX-owned
model-only client, not a version-pinned Hermes fork. B38-A begins with an
inert, fake-only implementation and does not create an authenticated sender.

New \`bin/px_s3_b38a_model_only_mock_client.py\`:

1. Reuses existing **B37-A** strictly text-only request validation through
   the **B37-B** immutable \`SealedFixture\` and \`verify_fixture\`. B37-A/B are
   imported read-only, not altered or given real network capabilities.
2. Accepts only exact \`FakeTextStream\` data containing an exact request ID,
   identical offered request bytes, and a finite tuple of literal byte frames.
   A callable transport, subclass, socket, SDK, native Hermes provider, or
   user-supplied dispatch object cannot be used as a sender.
3. Parses only invented synthetic \`mock.text.delta\` and
   \`mock.text.completed\` events with exact fields, strictly contiguous
   sequence numbers, valid UTF-8, no duplicate JSON keys or non-finite
   numbers, and strict frame/text/count budgets. Structured shell, file,
   browser, MCP, delegation, plugin or other unknown events are refused.
   The events are **not** claimed to be a real Responses API schema.
4. After validating the entire fake stream, calls B37-B's existing
   \`mock_handoff\`, which uses the B29 SQLite **synthetic** ledger
   reservation/transition and rejects replay. It never calls an HTTP
   transport. Invalid frames do not mark a reserved attempt submitted.
5. Returns a frozen \`FakeTextReply\` whose provenance explicitly says
   \`SYNTHETIC_IN_MEMORY_TEXT_ONLY\`. Its content is untrusted fake text and
   is never interpreted as a tool request. The public \`require_real_send\`
   entry point always refuses with a fixed error code.

This is a functional mock response parser and byte-bound fake handoff, **not**
a functioning authenticated model service. Neither user prompt nor
response is included in refusal diagnostics. No real provider/model calls,
credential loads, actual sockets or subprocesses occur.

## HOW TO USE

From an isolated checkout or GitHub CI, run:

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38a-model-only-mock-client.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37b-sealed-handoff.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37a-tool-free-contract.py
~~~

No normal user-facing model mode exists yet. Do **not** run the current
\`bin/px-agent\` as if this were wired to its provider registry.

## VERIFY

The new test suite checks:

- Positive fake-only two/three-frame text assembly; no execution or real-model
  claims and no interpretation of tool-looking JSON within **text**.
- Direct/native tool, plugin, MCP, delegation, memory, context, tool call
  and unsupported response frame denial; all extra keys denied.
- Duplicate JSON keys, malformed UTF-8, non-finite values, invalid types,
  empty text, invalid Unicode, out-of-order sequence, too-large inputs,
  missing/early completion, replay, and unreserved handoff refusal.
- Exact request ID, offered bytes, original request mutation isolation,
  forged seal, stale caller-supplied Hospital fixture binding and synthetic
  ledger state.
- No real-send path; no callable or subclass transport; frozen reply;
  static import check excludes Hermes/SDK/network/process imports.

Tests are offline. Import inspection is a cheap regression check, **not**
an OS proof or malicious-code confinement. H11.5 PR #106 is a separate fake
broker and is still unmerged at this branch's base.

## WATCH OUT FOR

- **No real sender exists.** B37-A's fixture model is not a real model ID;
  any text produced by B38-A is pre-supplied fake data.
- **No live Hospital authority exists here.** \`current_binding\` is
  supplied by the test; callers can lie. Hashing request bytes cannot
  authenticate the sender or prove remote delivery.
- Fake positive responses do **not** establish that a credential-bearing
  runtime is incapable of spawning local tools, accessing files, or opening
  arbitrary network connections.
- This does not replace H11.5 fake-broker tests, does not implement PX
  tool proposals, and cannot execute a Doctor with tools.
- **Stage A/B/C**, authenticated sender boundary, provider permissions,
  billing/retry/timeout, actual response schema and streaming, trusted
  source of authority, correct cancellation/revocation, secure replay,
  credential separation, native tool absence, and audit are still open.
- B37 owner files, \`bin/px-agent\`, \`config/agent-providers.json\`,
  Fedora, Hermes, real credentials, real Hospital and production
  activation remain untouched.

## CHECKLIST

- [x] Operator selected architecture A
- [x] Inspected PX main, Syntagma, current B37-A/B code, owner/PR status
- [x] New mock-only PX client, refusal tests and workflow authored
- [ ] Dedicated GitHub CI pass and independent code review
- [ ] Operator acceptance of the fake-only increment
- [ ] Separate review of a real **trusted** sender / streaming protocol
- [ ] OS/process boundary, model auth, and Hospital Stage A/B/C verification
- [ ] Production admission (currently DENY)

## NEXT

Review B38-A on a dedicated draft PR. The next separately scoped milestone
should specify the real client/transport ownership, request and response
schemas, credential containment, refusal-before-send semantics, and a mock
authenticated-sender protocol **before** any actual network/provider use.
Do not introduce implicit native Hermes compatibility or a real API key
as an experiment.

## DECISIONS

Option A is now the chosen architecture. Option B is not being pursued
as the primary path. This acceptance is not authorization for real
provider authentication or production activation. No merge is authorized
by the test status alone; preserve H11.5 PR #106.
