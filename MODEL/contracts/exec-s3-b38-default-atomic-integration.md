# PX EXEC-S3 // B37-C → B38 default mock atomic integration

> STATE // DRAFT · OFFLINE COMBINED-PATH IMPLEMENTATION · NO MERGE
> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // Hermes Integration Security (external Hospital-compatible; not registered live)
> ASSIGNMENT // B38 owner: replace old fake sender dispatch with merged B37-C atomic request identity fence
> MAIN BASE // 8b288f1b548f4ebc50fb134b77f8df3527efa805
> UPSTREAM // B38-A #108, B38-B #110, B38-C #111 are still open/draft; unchanged there
> CROSS-LANE // Independent B37-C/B38 evidence PR #112; no files in #112 modified
> PRODUCTION // HOLD · no provider, credentials, native Hermes or live Hospital

## IMPLEMENTATION

This **independent integration preview branch**, created from current
`main` after B37-C PR #109 was merged, copies the B38-A/B/C stack
unaltered first, then changes **only the B38-owned default mock
entry-point and associated tests**. It does not change B37-C, the B29
ledger, the production `bin/px-agent`, provider settings, Hermes or
the operator's Fedora installation.

Old path (proven bypass in PR #112):

```text
B38-B MockTrustedSender.send_mock
 -> B38-A exchange_mock
 -> B37-B mock_handoff
 -> B29 mark_submission (no stored B37-C payload hash)
```

New candidate default:

```text
B38-B MockTrustedSender.send_mock(atomic)
 -> B38-A exchange_mock(atomic)
 -> B37-C AtomicOfflineFixture.begin_mock(
      sealed, current_binding, offered_bytes)
 -> B29 BEGIN IMMEDIATE with registered request SHA256,
      exact client request ID, Room/Patient/Assignment/Bed/turn/
      generation binding, foreground mode and RESERVED state
 -> fake SUBMISSION_UNCONFIRMED
```

- B38-A accepts **exact** `AtomicOfflineFixture`, not a plain B29
  `SyntheticLedger`. Its prior `mock_handoff` import and invocation
  are removed. After validating the entire fake text stream, it calls
  B37-C's public `begin_mock`; invalid receipts or refused transitions
  fail closed. There is no optional fallback to the old B37-B route.
- B38-B's simulated sender `prepare_mock` and `send_mock`
  now require the same exact B37-C fixture; their own one-use fake
  ticket, generation, pause, revoke, restart and frame checks remain.
  The final transition is still performed by B37-C, not B38-B.
- Parent B38-A/B tests now register synthetic requests via
  B37-C `register_mock` rather than B37-B `reserve_mock`.
- The new direct-B38-A and B38-B integration tests cover missing
  B37-C registration, hash corruption injected after fixture trigger
  removal, plain-B29 rejection, replay/parallel queued tokens, failed
  frame parsing, stale permits and B37-C crash recovery uncertainty.
- This candidate is based on **merged B37-C main**, not a test-local
  monkeypatch of a module global. Test-only compatibility PR #112 is
  respected as independent evidence; it is not an implementation
  dependency or replacement for the new combined-path tests.

## HOW TO USE

In the isolated GitHub PR branch checkout, the dedicated workflow runs:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38-default-atomic-integration.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38a-model-only-mock-client.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38b-trusted-sender-mock.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38c-transport-policy.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37c-atomic-recovery.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37b-sealed-handoff.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37a-tool-free-contract.py
```

No local machine change, process launch, network, credentials or
real provider activation is needed.

## VERIFY

Approval requires exact PR head and GitHub Actions **merge checkout**
identity, all seven suites passing, no source import/call of the old
`mock_handoff` in B38-A, and negative results proving both
direct `exchange_mock` and B38-B default `send_mock`
cannot transition a row without B37-C registered payload SHA.

Test counters and B29 states are **synthetic**. B37-C's transaction is
atomic **within SQLite**; real network delivery is neither performed
nor atomic with the local ledger.

## WATCH OUT FOR

- This branch contains B38-A/B/C files copied from **three unmerged
  draft PRs** so it can perform a single genuine combined-main test.
  It is an alternative **integration preview**, not permission
  to silently merge the copied feature stack or self-accept its
  still-pending independent milestones.
- When the operator chooses merge sequencing, reconcile the existing
  draft branches and mark supersession/ownership explicitly. Never
  merge the old unguarded B38-A/B defaults into main first as a
  "production-ready" sender.
- B37-C public `register_mock` is required to bind request identity;
  direct invocation of B37-B mock functions outside B38 remains a
  separate legacy **test fixture**, not an authenticated live
  sender. No claim is made about securing all unrelated call sites.
- A malicious process sharing Python memory could still mutate
  mock fixtures or call B29 directly. No credential/OS/Hospital
  access-control boundary is implemented.
- After simulated B37-C submission with no durable observed response,
  recovery moves the local attempt to REMOTE_OUTCOME_UNKNOWN and
  denies automatic resend. This is **not actual network uncertainty**.
- `bin/px-agent`, Hermes CLI, real credentials and production
  provider launch/resume remain unchanged and unauthorized.

## CHECKLIST

- [x] Read Syntagma and confirmed B38 ownership / #112 evidence
- [x] Created separate branch from B37-C merged main
- [x] Routed B38-A/B default to B37-C begin_mock
- [x] Updated parent tests and added no-bypass/unknown-recovery tests
- [ ] Exact GitHub branch-head and merged PR checkout verified
- [ ] Independent Nurse/Head Nurse acceptance (not assumed)
- [ ] Explicit operator merge decision and stack reconciliation
- [ ] Real OS provider and credential isolation (not in scope)

## NEXT

Review this combined-path PR with the B37-C owner and existing B38
reviewers. Then choose explicit merge/supersession handling of
#108/#110/#111. The distinct B38-D OS-enforced test milestone remains
separately authorized work, not part of this PR.

## DECISIONS

**Default B38 mock integration candidate selected:** use the B37-C
public atomic fixture and reject old B29-only handoff. This is an
offline design/implementation decision pending independent verification,
not production acceptance or authorization to merge.
