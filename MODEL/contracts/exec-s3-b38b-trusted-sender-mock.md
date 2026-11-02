# PX EXEC-S3 // B38-B Synthetic trusted-sender boundary

> STATE // DRAFT · OFFLINE FIXTURE ONLY · IMPLEMENTATION REVIEW REQUIRED
> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // Hermes Integration Security (external Hospital-compatible; no live attachment)
> ASSIGNMENT // B38-B: Option A bounded synthetic sender and last-moment refusal
> BASE // B38-A draft PR #108 head fc10bd67a045ef32ef2f1af9c22cbe3e367ffb7a
> NEIGHBOR // B37-C draft PR #109 owns atomic sealed-request and mock crash recovery; untouched
> PRODUCTION // HOLD · B24 provider admission DENY · NO REAL AUTHENTICATION

## IMPLEMENTATION

B38-B builds only **new** files atop the unmerged B38-A draft branch
as a stacked pull request. Neither B38-A nor B37-A/B37-B/B37-C nor
\`bin/px-agent\`, provider configuration, Hermes, Fedora or live Hospital is
changed by this branch.

\`bin/px_s3_b38b_trusted_sender_mock.py\` models an intentionally **fake**
PX-owned trusted sender. Its non-cryptographic, in-memory ticket is minted
only by the test's simulated supervisor lane. A final \`send_mock\` consumes
the exact issued ticket, rechecks its epoch, six-part B29 binding,
B37-B sealed request, and B29 **mock** RESERVED state. Only then does it
synthesize fixed text frames and pass them into B38-A's existing
\`exchange_mock\` path, which records a simulated handoff in B29's
disposable SQLite fixture.

It exposes no real endpoint, URL, client SDK, arbitrary transport callback,
model login, socket, native tool executor, or real \`send\` action.
\`require_real_sender\` unconditionally refuses. Its fixed
\`B38B_SENTINEL_NOT_A_REAL_CREDENTIAL\` is a disposable marker in the same
Python process, **not** a secret confidentiality proof.

The only positive response is **prewritten fake text**:
\`B38B synthetic text, never a provider response\`.
It is not a generated answer, delivery acknowledgment, remote cancellation,
or actual provider use. The B29 state \`SUBMISSION_UNCONFIRMED\` is merely
its offline fixture label; no remote submission occurred.

The fake supervisor API is accessible to the calling test code. A malicious
caller in the same process could manipulate its private attributes, so this
fixture explicitly **does not** confer real authorization or an authenticated
identity. It explores refusal ordering and orchestration, not resistance to
a compromised trusted process.

## HOW TO USE

In a disposable checkout **after checking out the stacked branch**:

~~~bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38b-trusted-sender-mock.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38a-model-only-mock-client.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37b-sealed-handoff.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37a-tool-free-contract.py
~~~

The dedicated GitHub workflow runs these same commands. No local Fedora
installation, process restart, Hermes session, credentials or HTTP is needed.

## VERIFY

The new tests exercise:

1. Positive single-use fixed fake-text handoff and explicit zero real
   network/provider calls.
2. Unconditional real sender refusal, malformed source binding, wrong
   ledger or seal, forged request, and missing reservation.
3. Synthetic pause, revocation, Assignment/generation replacement, readiness
   change, and restart between ticket issuance and final handoff.
4. In-memory ticket duplication, wrong ticket type, direct replacement of
   the sender with untrusted frames, repeated send and independently queued
   replay against an already-submitted fixture attempt.
5. Mutation of the original request without changing the sealed bytes;
   readonly reply; no imported native Hermes/SDK/network module.

Negative pre-handoff cases must leave the B29 mock reservation RESERVED
and the positive-send counter zero. Replay after an earlier fake success
must not increment the counter again.

These do not verify concurrency/atomic OS authority, remote attempt
uncertainty, original Hermes hooks, actual credentials, live provider
networking, or real Hospital ownership.

## WATCH OUT FOR

**Ownership:** B37-C PR #109 is separately working on atomic sealed-request
fencing and mock crash recovery. B38-B has not reused or changed its files;
any later production send should use independently reviewed B37-C
reconciliation rather than inventing a competing durable send ledger.

**Stacking:** B38-B depends on B38-A PR #108, still a draft at the
initial checkpoint. Review or merge B38-A separately first, then rebase
or retarget B38-B so its diff remains only B38-B files; never infer that
passing a stacked PR automatically accepts either parent.

**Credential model:** A fake string hidden from returned data is NOT
credential isolation. A true trusted sender must be a separate,
OS-restricted, authenticated component with explicit allowlisted
network destination, FD/secret ownership and a stable actual API
contract, all requiring separate operator approval.

**Stage A/B/C:** The simulated readiness boolean is not kernel attestable
sandbox readiness. A real sender must refuse before outgoing persistence
when Stage A/B fails; no unconfined fallback or automatic retry.

## CHECKLIST

- [x] Operator selected Option A and approved next offline slice
- [x] Checked main, PR #108 parent, PR #109 adjacent ownership
- [x] Added fake sender and synthetic negative tests in isolated branch
- [ ] Dedicated branch-head CI verified
- [ ] Independent security review
- [ ] Operator final acceptance for B38-B
- [ ] Separately authorize real sender, credential transport, runtime gates
- [ ] Production admission (HOLD)

## NEXT

Obtain independent review of the stacked B38-B fixture and tests. The
subsequent non-production milestone should refine genuine process/network
and authenticated-sender design **without** using real provider keys.
Coordinate explicitly with the B37-C owner for atomic recovery boundaries.

## DECISIONS

Option A remains selected; only **offline fake-only sender modeling** is
implemented here. No merge, native Hermes patch, local machine action,
real HTTP/API call, model selection, live authority grant or production
activation has been authorized by this work.
