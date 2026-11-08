# PX EXEC-S3 // B38-I Durable Fake Launch Claim and Cancel Ordering

> STATUS // DRAFT · OFFLINE ONLY · OWNER/SECURITY REVIEW REQUIRED  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // Hermes Integration Security  
> ROLE // PXD · operator-confirmed B37-C owner for fake-only interface  
> CONNECTION // External Hospital-compatible, no live Hospital registration  
> ASSIGNMENT // B38-I: model a durable fake launch-claim ordering seam after B38-H  
> BASE // merged B38-H main 46a3eae7637b948388c7d7911c5684aaadcb3575  
> PRODUCTION // HOLD · B24 real-provider DENY

## IMPLEMENTATION

B38-H demonstrated an opt-in sequence: B37-C atomic request transition,
read B29 state, launch B38-G's sandboxed fake child. But a cancellation may
commit **between the final read and the actual process spawn**. A second
read cannot make an OS launch atomic.

B38-I introduces a strictly TEST-ONLY, *durable intent to attempt one fake
child launch*. It does **not** atomically start a process.

1. \`bin/px_s3_b38i_fake_launch_claim.py\`: an additive fixture attached to
   an already-validated, **disposable B29/B37-C SQLite database**. It adds
   only the nullable \`b38i_fake_launch_claim\` column to the existing
   synthetic attempt table plus an immutable-claim trigger. No new table
   is created, preserving the preexisting B29 fixture-marker/table guard
   and B37-C reopen compatibility. No B29, B37-C or B38-H source is edited.
2. Within B29's existing \`BEGIN IMMEDIATE\` transaction, the claim compares
   sealed synthetic request ID, payload digest, full six-field binding,
   foreground mode, \`SUBMISSION_UNCONFIRMED\`, absent B33 observation and
   missing prior fake claim, then writes a one-use 128-bit random *fixture*
   marker with a conditional SQL UPDATE. An immutable SQLite trigger
   prevents accidental clearing/mutation after claim.
3. This transaction serializes with B29's existing cancellation and
   generation-revocation transactions. **Cancellation first** leaves
   \`CANCEL_PENDING\`, so the fake claim refuses. **Claim first** permits
   *one attempted* fake process, while any later cancellation is an
   in-flight \`CANCEL_PENDING\` event, with budget held and no automatic retry.
4. The new test harness takes B37-C's existing \`begin_mock\` transition,
   then B38-I's claim, then the unchanged B38-G outside-supervisor /
   Bubblewrap-confined fake B38-E child. Process failure, crash or an
   invalid signed fake reply remains uncertain; no B33 witness is
   fabricated and no budget is released.
5. Reopening the disposable database preserves the marker. Even if
   the process never started after the durable claim, recovery treats
   the outcome as unknown and prohibits replay. A valid synthetic
   reply is not independently authenticated B33 observation.

### Linearization is NOT an OS launch guarantee

The SQLite claim is a **durable scheduling decision**, not a trusted
physical-process start, capability token or real-provider launch
authorization. Cancellation after claim may be recorded before the
actual \`Popen\` executes. This is not a violation of the synthetic
in-flight ordering rule but is **not** a safe real-provider cancellation
protocol without an additional, separately designed launch worker,
revocation/stop delivery and authenticated observation/acknowledgment.

B29 cancellation itself remains unchanged. A real sender must define
the semantics of cancellation after durable claim, including whether
a process may start after an already-committed cancellation and how it
can be stopped. The test proves only a *total SQLite order* between
claim and cancel and an irrevocable no-replay budget hold.

## HOW TO USE

Review B38-I draft PR and CI. Disposable Ubuntu-22.04 GitHub Actions
uses the unchanged merged B38-G S1 sandbox and B38-E fake handler.
No Fedora action, real provider, keyring, actual Hospital database,
credentials or local installation is involved.

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38i-durable-fake-launch-claim.py --unit
    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38i-durable-fake-launch-claim.py --smoke

## VERIFY

Require exact PR head/base/generated merge-checkout provenance,
all new unit tests, genuine Bubblewrap smoke, B38-H/G/F/E/D and
B37/B38 regressions, separate B34 baseline/integration and grammar.

Security-critical negative tests:
- No claim before registration/B37-C atomic mark; replay refused.
- Cancel/revoke committed before claim refuses; fake budget retained.
- Two independent SQLite connections race for one claim: exactly one
  wins. Concurrent claim/cancel serialized with both valid orders.
- Trigger prevents changing an already persisted claim.
- Crash after B37-C mark but before claim, and after claim before
  process start, both quarantine on reopen with **no automatic retry**.
- A signed fake child response does NOT become B33 observation.
- Later cancellation remains \`CANCEL_PENDING\`, not fabricated
  completion or false evidence of verified remote stop.
- Real Bubblewrap smoke observes one fake child attempt after the
  durable claim and verifies persisted marker across restart.
- All test receipts retain real launch/provider/production authority false.

## WATCH OUT FOR

This is a new synthetic fixture **schema extension on disposable test
DB only**. It must never be applied to real Hospital or untrusted storage.
B29's initializer validates its known tables but does not certify
user-supplied SQLite content as trusted; a caller with owner-level DB
write access could replace triggers and fixtures. Synthetic bindings
are not authenticated current Hospital identity. The fake child has a
disposable HMAC key. Sandbox self-probes are not malicious child proof.
No independent B33 observer is connected to the fake process.

**Do not call this production-safe launch atomicity.** No SQLite transaction
can atomically encompass OS \`Popen\` or provider network delivery.
A claim-then-cancel ordering without enforcement at the actual launcher
and stop/acknowledgment cannot certify that no canceled operation begins.

B24 REAL_PROVIDER_DENY, EXEC-S3 PRODUCTION HOLD and operator-only
merge authority remain.

## CHECKLIST

- [x] Verify B38-H merged main and current B37-C contract before changes.
- [x] Confirm no B38-I competing branch or PR at preflight.
- [x] New additive fake-only claim fixture, CI, tests and contract.
- [ ] Verify source/negative tests/sandbox on exact GitHub merge checkout.
- [ ] Nurse 2 independent security review and operator acceptance.
- [ ] Future default sender integration, trusted launch agent and
      separately authenticated B33 observations, out of current scope.
- [ ] Production authorization separately required.

## NEXT

Fix only B38-I-owned files if new CI finds issues. Preserve actual
main, B37-C/B38-H code and test-only behavior. Ask Nurse 2 to review
the claim ordering and crash classification against current B29/B37-C
source. Do not merge without the operator's approval. Future work
needs an independently trusted launch worker and response observer
before any real provider.

## DECISIONS

Use the smallest additive mock state extension instead of editing
B29/B37-C or pretending a read check atomically starts a process.
Define \`CLAIM FIRST → CANCEL PENDING\` as an acceptable fake-only
in-flight ordering, not as a physical launch guarantee. Never retry
an uncertain claimed request. No production / Fedora / live Hospital
changes were authorized or performed. PR remains DRAFT/UNMERGED.
