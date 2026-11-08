# PX EXEC-S3 // B38-J External Fake Launch Worker and Host Exit Observation

> PHASE // DRAFT · OFFLINE TEST-ONLY · EXTERNAL REVIEW REQUIRED  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // Hermes Integration Security  
> STAFF ROLE // PXD, B37-C synthetic interface owner and bounded B38-J implementer  
> CONNECTION // External Hospital-compatible, no verified live Hospital registration  
> ASSIGNMENT // B38-J first checkpoint: separate fake process worker + cancellation prelaunch refusal  
> BASE // B38-I merged main b138aa9a4e279d07612a4769dd9fe1c121b71237  
> PRODUCTION // HOLD · B24 REAL_PROVIDER_DENY

## IMPLEMENTATION

B38-I now provides a one-time claim serialized with B29 cancel/revoke
in synthetic SQLite. It **does not** make physical OS spawn atomic with a
database transaction. B38-J introduces an independent disposable **launch
worker OS process**, separately observed/reaped by a host test harness.
This is a *small next checkpoint* and does not solve real-provider launch
atomicity, cancellation/stop-acknowledgment or trusted external observation.

- A new standalone test harness
  \`tests/test-pxd-exec-s3-b38j-external-fake-launch-worker.py\` starts a
  real separate Python worker process using a fixed allowlisted
  environment, close_fds and its own process group.
- A bounded single-command protocol accepts **only**
  \`LAUNCH\`, \`CANCEL\`, or \`CRASH\` plus a negative invalid-command test.
  Worker emits fixed schema, nonce, process PID and structured
  status. Host sees and reaps its actual OS process exit and validates
  the bounded status framing; fake worker content remains **untrusted**.
- The worker opens only an explicitly supplied disposable B29/B37-C
  synthetic SQLite database and checks the already merged B38-I
  durable launch claim before starting B38-G.
- An already-committed cancellation or generation revocation
  causes \`LAUNCH\` to be rejected without starting the **sandboxed
  fake model child**. A pre-launch \`CANCEL\` request can be acknowledged
  by the worker and records \`CANCEL_PENDING\` with fake budget held.
- A valid \`LAUNCH\` calls the unchanged B38-G outside-supervisor
  exchange, which invokes the unchanged B38-E fake child inside S1
  Bubblewrap. The parent observes the separate worker's OS exit.
- No B33 witness/settlement is fabricated from a fake worker's
  self-report or from its exit status. Crash after B38-I claim is
  quarantined via B37-C \`recover_mock\` after restart and never retried.

Three additive files only: new B38-J test harness, CI workflow and
this continuity contract. **No existing runtime, B29, B33, B37-C,
B38-G, B38-H, B38-I, S1 or provider code modified.**

## HOW TO USE

Review the draft B38-J PR, its CI workflow and raw logs.
The following commands are intended **only for a disposable Linux
test checkout**, not the operator's live Fedora desktop:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38j-external-fake-launch-worker.py --unit
    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38j-external-fake-launch-worker.py --smoke

No real provider, API credentials, Hospital session or native Hermes
Doctor turn is used.

## VERIFY

Tests cover a real separate worker process and the following:
- A non-claimed attempt refuses fake child launch.
- A valid one-use B38-I claim reaches the B38-G fake child inside
  S1 Bubblewrap and returns only bounded synthetic fixed data.
- Cancel/revoke committed **before the worker's command dispatch**
  refuses launching the fake child.
- A worker CANCEL produces a host-observed process exit and a
  cancellation acknowledgment, but no verified real remote stop.
- Forced worker CRASH leaves a durable B38-I claim, followed by
  B37-C restart quarantine and no replay.
- Wrong/unknown worker commands are refused.
- No B33 authenticated observation, mock usage settlement or
  production authorization is inferred from self-reported status.
- B38-I/H/G/F/E/D/B37/B38 regression suites and B34/Grammar CI
  must pass on the generated GitHub PR merge checkout.

## WATCH OUT FOR

**THIS IS NOT ATOMIC CANCELLATION VERSUS OS SPAWN.** The worker reads
B29 state and can still race cancellation **after** that check. If
the claim precedes cancel, current synthetic semantics permit one
possibly in-flight fake attempt even if physical launch is later.
No tested interrupt or kill acknowledgment yet proves a child
was stopped during active execution. The host's process group
cleanup is best-effort error handling, not verified real stop.

**THIS IS NOT AN AUTHENTICATED PEER OR INDEPENDENT RESPONSE OBSERVER.**
The worker supplies its own result frame and B38-G's fake child owns
a disposable HMAC key. The host knows only the worker OS PID and
exit status, not the true provenance of content. No B33
\`issue_test_only\` witness is minted by worker self-report.
Untrusted fake text must never authorize budget settlement.

The helper accepts only a user-supplied disposable SQLite DB path and
fake-only commands, never a provider endpoint, token or OS command.
A local user with arbitrary Python or DB write access can bypass the
test policy or forge DB state. Never reuse as a production launch daemon.

B24 real-provider DENY, EXEC-S3 production HOLD and separate operator
merge authorization remain.

## CHECKLIST

- [x] Verify B38-I merged main and B37-C/B38-G ownership.
- [x] Add separate real fake worker, host exit observer, tests and CI.
- [ ] Verify exact-head unit tests, real sandbox smoke and regressions.
- [ ] Nurse 2 independent review of trust and cancellation claims.
- [ ] Operator merge decision.
- [ ] Future separate trusted launch service and authenticated response
      observer with process stop/ack, crash, concurrent cancellation tests.
- [ ] Production credentials/security certification separately authorized.

## NEXT

Review CI, patch only B38-J-owned files as required and preserve
full negative-case/OS evidence. The next separately scoped checkpoint
must address **cancellation during an already running process**,
including the worker's actual stop and acknowledgment, and then
an independently authenticated observer. No real provider activation.

## DECISIONS

B38-J initially proves a separate fake launcher process and
host OS-exit observation, not a certified sender/observer.
No mandatory default gate, real provider, installed Fedora work
or live Hospital write. Leave PR DRAFT/UNMERGED pending review.
