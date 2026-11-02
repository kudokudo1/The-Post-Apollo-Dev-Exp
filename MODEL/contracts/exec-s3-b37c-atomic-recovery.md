# PX EXEC-S3 // B37-C Atomic Offline Fence and Recovery

> STATE // DRAFT · OFFLINE-ONLY · REVIEW REQUIRED  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // PX Doctor Execution Security · B37-C synthetic request handoff  
> CONNECTION // External Hospital-compatible browser worker, no live registration  
> ASSIGNMENT // B37-C fixed request identity inside the B29 local transaction, B33 recovery continuity  
> PRODUCTION // HOLD

## IMPLEMENTATION

Additive B37-C fixture `bin/px_s3_b37c_atomic_recovery_fixture.py` reuses
merged B37-A/B37-B (fake model, immutable JSON bytes and deterministic client
request ID), B29 (disposable SQLite budget/attempt ledger), and B32/B33
(synthetic durable response observation, independent mock evidence and cost
settlement). It does **not** replace any B29, B32, B33, PX provider registry,
`px-agent` or installed Fedora runtime.

### Three boundaries

1. **Registration:** B29 reserves a synthetic attempt and client request ID,
   then B37-C binds the B37-B SHA-256 payload digest in a separate
   `BEGIN IMMEDIATE` transaction. A crash between reservation and binding
   leaves `RESERVED` with no hash. B37-C refuses to transition such an
   attempt. No external request exists in this fixture.
2. **Atomic local mock transition:** Within **one B29 SQLite transaction**,
   compare the persisted client request ID, exact payload hash, full
   Room/Patient/Assignment/Bed/turn/generation binding, foreground mode,
   `RESERVED` state and absence of prior observation. Update to
   `SUBMISSION_UNCONFIRMED` only with the same SQL predicates.
   A B37-C trigger preserves request ID, binding and hash after registration.
   The candidate outbound bytes must independently match the immutable seal.
   **There is no network send at this step.**
3. **Crash/restart:** Reopening a disposable fixture DB revalidates the same
   sealed identity. A pre-transition `RESERVED` attempt stays unsubmitted
   without automatic retry. An unobserved `SUBMISSION_UNCONFIRMED` becomes
   `REMOTE_OUTCOME_UNKNOWN`, retaining mock budget for reconciliation.
   A previously recorded B33 mock observation stays durable and can be
   settled using B33's **separately issued test-only witness**, without any
   redispatch. Canceled/revoked/settled states remain non-retryable.

### Explicit limits

- SHA-256 is not a signature or proof that caller-provided Assignment identity
  is authentic. `current_binding` remains an untrusted **synthetic argument**.
- The B37-C transaction does **not** make HTTP delivery atomic. Future real
  senders need a trusted current-authority source, process confinement,
  audited credential boundary, crash consistency, remote-state reconciliation
  and explicit permission to authenticate/pay for provider calls.
- SQLite trigger prevents accidental row mutation, not an adversary with DB
  owner privileges who can drop triggers or replace the database.
- B33 observation/settlement use **separate protected transactions**. Their
  existing binding and B33 digest/witness rules remain in force. Do not
  describe the entire request/observation/settlement lifecycle as one atomic
  transaction or as authenticated external evidence.
- `SUBMISSION_UNCONFIRMED` is a reused **mock state name**. It never means
  that an actual remote request was sent.

## HOW TO USE

On the PR checkout in CI:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37c-atomic-recovery.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37b-sealed-handoff.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b33-durable-observation.py
```

All database data comes from disposable SQLite fixtures. No user/system
configuration, external connector, native Codex/Hermes, HTTP SDK, API key,
billing, Hospital session or tool execution is involved.

## VERIFY

The new 36-case suite covers:

- correct request ID and payload hash, no launch authorization, exact bytes;
- mismatched ID/SHA, altered Assignment fields, failed partial registration;
- SQLite trigger immutability plus transactional checks when fixture DB
  corruption is injected;
- two concurrent connections competing for one local transition;
- restart before and after transition, uncertainty holds, cancellations,
  generation revocation, duplicate/replayed transition refusal;
- durable B33 observation, independent mock evidence settlement across
  reopen, witness replay refusal and altered observation digest rejection;
- foreign-database rejection and no real provider/network execution.

CI also runs the merged B37-B and B33 tests. Review both the exact
PR-head SHA and the generated PR merge checkout before accepting results.

## WATCH OUT FOR

No real model-only transport was implemented. The principal security
requirement from EXEC-S3 S3-C1/C2/C3 remains **unresolved** for native
Codex/Hermes and requires separate authorization.

This development does not own PR #106 (Hermes H11.5), PR #107's design
implementation, or prior Hospital authority PRs. There is no automatic
merge or permission to modify production execution paths.

## CHECKLIST

- [x] Offline B37-C source/test/contract prepared on isolated branch
- [ ] GitHub CI result verified, including B33/B37-B regression jobs
- [ ] Independent Nurse 2 / Head Nurse scope/security review
- [ ] Operator merge decision
- [ ] Any future real transport/authenticated security design separately authorized
- [ ] Production Doctors: HOLD

## NEXT

Review identity comparison inside the B29 transaction and source-level
mock-only boundaries. Any real sender must add an independently trusted
authority recheck and remote-uncertainty/replay protocol; never promote a
synthetic green suite into a production provider admission.

## DECISIONS

Do not edit `bin/px-agent`, `config/agent-providers.json`, B29/B32/B33
or live Hospital, user credentials, Fedora or installed Codex/Hermes.
Implementation scope is new B37-C files only. PR stays draft/unmerged
pending named review and the operator's merge decision.
