# PX EXEC-S3 // B37-B Immutable Request Handoff (Offline Fixture)

> STATE // DRAFT · SYNTHETIC ONLY · INDEPENDENT REVIEW REQUIRED  
> PATIENT // The-Post-Apollo-Dev-Exp  
> SCOPE // B37-A byte sealing + B29 mock transport-ledger identity binding  
> CONNECTION // EXTERNAL HOSPITAL-COMPATIBLE; NO LIVE ROOM / ASSIGNMENT CLAIM  
> PRODUCTION // HOLD

## IMPLEMENTATION

The merged B37-A validator returns a caller-owned mutable dictionary. B37-B adds
`bin/px_s3_b37b_sealed_handoff.py` as a **fixture-only** handoff that never
launches a provider, performs HTTP, calls a real API, opens credentials or
connects to live Hospital.

1. Validate the B37-A fake-model, text-only input; encode **fresh canonical
   JSON bytes**. This is an immutable snapshot independent of the original
   mutable dictionary. Revalidate the serialized bytes.
2. Compute SHA-256 over those bytes; derive a separate deterministic
   `b37b.<sha256>` client request ID from a domain tag, attempt identity,
   canonical B29 binding (Room, Patient, Assignment, Bed, turn and generation)
   and the **same** body bytes.
3. Reserve synthetic budget using the existing B29 SQLite fixture ledger.
   B29 persists the derived client request ID and binding, rather than a
   new table that would violate B29's fixture-schema allowlist.
4. At `mock_handoff`, verify the frozen seal, current *supplied fixture*
   binding, B29 reserved attempt, persisted derived request ID, and the
   exact offered bytes. B29 atomically checks binding/state with
   `BEGIN IMMEDIATE` before marking simulated submission.
5. Return **sanitized mock evidence**, never the request body, a send token,
   authentication proof or an external transport result.

`SealedFixture` is frozen and holds immutable `bytes`; sealed identity
and payload cannot change through mutation of the original request.
The explicit `require_real_dispatch` function always refuses.

## HOW TO USE

For CI or a separately authorized disposable repository checkout:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37b-sealed-handoff.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37a-tool-free-contract.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b29-transport-ledger.py
```

B29 uses a caller-provided **in-memory disposable SQLite** connection in
B37-B tests. Do not give it a Hospital database or a personal data path.

## VERIFY

B37-B negative tests require refusal for modified/tampered payload, forged
digest/request identity, noncanonical JSON, replacement bytes at the final
boundary, stale Room/Patient/Assignment/Bed/generation, wrong/missing ledger,
reused attempt with changed body, cancellation, revocation and replay after
simulated submission. Positive cases verify the original mutable request
can change without affecting the sealed bytes, and B29's persisted
client request ID matches the byte-derived identity.

No test executes native Codex, Hermes, an authenticated provider, a tool,
or a real network sender. CI runs B37-B, B37-A and B29 offline regressions.

## WATCH OUT FOR

- A SHA-256 digest does **not** authenticate a provider, sign trusted
  supervisor authority, or prove a remote API received anything.
- `current_binding` is passed by the fake test harness; the fixture does
  **not** read current Hospital Assignment state and cannot prevent a lying
  caller from inventing authority. A real supervisor must obtain and check
  current authority immediately before dispatch.
- The fake receipt says `SUBMISSION_UNCONFIRMED` because it reuses B29's
  state machine; **no HTTP submission occurred**. It is *not* delivery,
  billing, cancellation or process-termination proof.
- The fixture itself does not provide durable replay protection if
  separately integrated without B29's transaction, and it has no real
  atomic check+send primitive. Real network submission needs its own
  audited sender boundary and failure/quarantine semantics.
- No B33 event settlement, production model choice, credentials, API
  billing, native Codex tool suppression, live Hospital attachment,
  PX `px-agent` dispatch/resume changes or production activation.

## CHECKLIST

- [x] Isolated offline implementation and 26 tests prepared
- [ ] Exact PR checkout / CI reviewed independently
- [ ] Nurse 2 / Head Nurse review and operator merge decision
- [ ] Trusted actual send-boundary design and crash/remote uncertainty proof
- [ ] Real-provider isolation/authentication authorization
- [ ] Production acceptance

## NEXT

After review, decide whether to build the next **offline staged evidence**
milestone with B32/B33 or an independent trusted sender proposal. Neither
is authorized by this PR. Keep existing S3-C1/C2/C3 authority and tool broker
requirements intact.

## DECISIONS

Additive new B37-B files only. Do not modify merged B37-A, B29, B33,
`bin/px-agent`, `config/agent-providers.json`, Fedora, Codex/Hermes,
or live Hospital. No merge or production readiness is implied.
