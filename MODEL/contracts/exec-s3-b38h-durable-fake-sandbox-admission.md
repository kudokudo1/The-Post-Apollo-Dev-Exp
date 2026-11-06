# PX EXEC-S3 // B38-H Disposable Durable Admission for Sandboxed Fake Child

> STATUS // DRAFT · OWNER REVIEW REQUIRED · PRODUCTION HOLD  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // Hermes Integration Security  
> ROLE // PXD (external Hospital-compatible; no live Hospital registration)  
> ASSIGNMENT // B38-H: B37-C durable atomic mock transition before B38-G sandboxed fake exchange  
> BASE // merged main f320431e87c50dbec8dff34eca3b2747b42991b9  
> OWNERSHIP // B37-C ledger owner retains file/API ownership; adapter is test-only and added separately.

## IMPLEMENTATION

B38-G is merged and demonstrates an external test supervisor exchanging a
signed, fixed synthetic response with the unchanged B38-E handler confined
by Bubblewrap. Previously, that standalone call did **not** require
B37-C's durable SQLite fence, although B38-A/B already used the fence
in their in-memory mock path.

B38-H adds a **new isolated harness**, not a modification to either owner:
- \`tests/test-pxd-exec-s3-b38h-durable-fake-sandbox-admission.py\` imports
  the existing B37-C \`AtomicOfflineFixture\` and B38-G test-only
  supervisor and connects them in one explicitly opt-in adapter.
- The adapter receives a pre-registered sealed synthetic request and
  the same caller-supplied binding. It snapshots the binding, invokes
  B37-C's **unchanged** \`begin_mock\` SQLite transaction, and only after
  it returns the exact \`SUBMISSION_UNCONFIRMED\` receipt does it invoke
  B38-G's **unchanged** sandboxed fake exchange.
- A missing, invalid or replayed registration is rejected before any
  sandbox spawn. After the durable transition, an ordinary sandbox error
  or tampered synthetic response triggers B37-C's existing
  \`recover_mock\` quarantine to \`REMOTE_OUTCOME_UNKNOWN\`. An abnormal
  hard crash is deliberately not intercepted: after process restart
  \`recover_mock\` performs that same quarantine.
- After a valid signed fake reply, the ledger **remains**
  \`SUBMISSION_UNCONFIRMED\`, because a local mock reply is not the
  separately authenticated B33 observer/witness. On restart this
  uncertain state is quarantined and the fake budget remains held.
  The adapter never sends the same request again automatically.
- Eleven unit tests and one actual Bubblewrap smoke test are included.
  Workflow also runs all B38-G/F/E/D and prior B37/B38 regression suites
  against GitHub's generated merge checkout.

**Important:** This creates an opt-in **test-only** combined path; it does
not change the default sender API, guarantee all callers are fenced,
change live credentials, make real provider calls, or certify the model
child's trust identity. B37-C remains the authority for its own
SQLite schema, immutable-request trigger, single-writer transaction,
recovery and mock budget rules. No B37-C or B38-G source modifications.

## HOW TO USE

Review the B38-H draft PR and its new CI workflow. No Fedora
installation, live Hospital, provider credentials or local machine
changes are requested.

Test-only commands on a disposable Linux CI runner:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38h-durable-fake-sandbox-admission.py --unit
    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38h-durable-fake-sandbox-admission.py --smoke

The smoke uses a temporary SQLite DB, B37-C mock request registration,
the original B38-G external-supervisor sandbox, and a restart
quarantine; all state is erased afterward.

## VERIFY

Require the generated PR merge checkout SHA, exact base/head provenance,
the new units and real OS smoke, all B37/B38 regressions, B34 integration
and grammar checks. Inspect at least:
- Strict order: B37-C atomic \`RESERVED -> SUBMISSION_UNCONFIRMED\`
  before sandbox launch. No launch for missing/stale/replayed requests.
- Interrupted process after atomic mark does not roll back or retry;
  a new SQLite connection yields \`REMOTE_OUTCOME_UNKNOWN\`.
- Bad child result and ordinary process failure quarantine; no
  synthetic B33 observation is silently fabricated.
- A genuine B38-G fake sandbox exchange succeeds once and leaves
  \`SUBMISSION_UNCONFIRMED\`. Restart quarantines; fake budget held.
- No provider, network, real credentials or live Hospital authority.
- Separate B37-C owner review and Nurse 2 independent security review
  of the exact code and workflows, then operator merge decision.

## WATCH OUT FOR

This is **not** a production dispatcher. B37-C's transaction cannot
atomically encompass external sandbox execution. That is precisely why
unknown outcomes must be quarantined and no replay is allowed.
The caller supplies synthetic \`current_binding\` rather than an
authenticated live Hospital identity; the child controls its own fake
HMAC key and signed answer; OS probes are not adversarial identity
certification. A real integration must enforce the admission fence at
the one true sender entrypoint and authenticate the transport-owned
observer before accepting billable outcomes.

The harness now reads B29's post-transition snapshot before spawning the
fake model. If cancellation or generation revocation was already committed
between B37-C's atomic mark and this snapshot, launch is refused and the
existing ledger cancellation/revocation state and held budget remain.
**This is only a deterministic negative guard, not an atomic send lease.**
A concurrent cancellation *after* the snapshot can race the fake spawn.
B37-C's owner must design the actual lease/fence before any real sender.

The bridge's error classification deliberately reveals only fixed
non-sensitive refusal codes. It does not infer that a sandbox exception
means no request occurred: after \`begin_mock\`, every error is uncertain.

A signed fake reply does not constitute B33 durable observation,
cost settlement, authorization for tools or proof of real delivery.
B24 REAL PROVIDER DENY and EXEC-S3 PRODUCTION HOLD stay in effect.
This draft does not represent B37-C owner approval or a live Hospital
assignment/registration.

## CHECKLIST

- [x] B38-G merged at f320431e... confirmed.
- [x] No B38-H competing PR or matching branch found at preflight.
- [x] B37-C and B38-G source/interface inspected.
- [x] Add separate fake-only durable-admission harness with no owner edits.
- [x] Add CI plus continuity documentation.
- [ ] Verify exact GitHub merge checkout and smoke/regressions.
- [ ] B37-C owner reconciliation and independent Nurse 2 audit.
- [ ] Operator acceptance and merge authorization.
- [ ] Certified real peer/credential isolation and B33 evidence
      integration (separately scoped future; no production).

## NEXT

Review CI; fix only isolated B38-H files on the same branch if needed.
Request B37-C owner and Nurse 2 review before any PR consolidation.
Future milestone must design a single non-bypassable sender entrypoint and
trusted observer semantics without modifying B37-C's owner-controlled
transaction contract without coordinated authorization.

## DECISIONS

One new opt-in fake-only adapter; do not replace the existing B38-B
sender or B38-G direct test function, and do not claim default path
enforcement. Parent main is stable source of truth. PR remains
DRAFT/UNMERGED pending operator and owner decisions. No Fedora or
live Hospital changes; production HOLD unaltered.
