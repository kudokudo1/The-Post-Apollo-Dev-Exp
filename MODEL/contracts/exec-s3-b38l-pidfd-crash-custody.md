# EXEC-S3 B38-L // Disposable Kernel pidfd Crash-Custody Experiment

**PATIENT:** The-Post-Apollo-Dev-Exp  
**ROOM:** Hermes Integration Security  
**ROLE:** PXD, external Hospital-compatible, no verified live registration  
**BASE:** B38-K #126 merged at `c856f6edafb27b3f2a233ad3beaf33653c9dbde9`  
**SCOPE:** new fake-only test harness, CI and contract; no existing B29/B33/B37-C/B38-K runtime edits.  
**PRODUCTION:** HOLD · B24 REAL_PROVIDER_DENY.

## IMPLEMENTATION

Previous B38-K proved termination of the owned Bubblewrap wrapper and
heartbeat quietness, not kernel-managed descendant custody. B38-L
performs a narrow *separate* Linux experiment:

- A disposable fake supervisor creates a parent and leaf fake worker.
  Both outlive the supervisor's intentional hard crash.
- The controller captures **both actual Linux pidfds before crash**.
  After the crash it retains those kernel handles, not simply
  numeric PIDs, and issues `signal.pidfd_send_signal(SIGTERM)` to the
  two known fake test processes.
- Linux pidfd readability is polled for actual exit indication for
  each known process. The controller separately reaps its own
  supervisor via `wait()`.
- A synthetic SQLite STOP_REQUESTED state is committed before
  triggering supervisor failure. STOP_OBSERVED is committed only
  after both kernel pidfds show exit. The ledger is reopened to
  demonstrate durable state and denial of duplicate finalization.
- The leaf writes a disposable heartbeat file for supporting
  observation, not as primary termination evidence.
- Tests also reject missing pidfd, invalid PIDs, and duplicate
  stop transitions. No kill on reused numeric PIDs after pidfd capture.

The processes execute a *fixed* Python fake loop from the repository.
No arbitrary task, HTTP, provider SDK, secret or Hospital connection.
The inherited B38-K/J/I/H tests separately cover real S1 Bubblewrap
fake model and earlier B37/B38 integration behavior.

## HOW TO USE

Inspect draft PR and exact-head GitHub CI; no local Fedora action.
In a disposable Linux runner only:

```sh
python3 -B tests/test-pxd-exec-s3-b38l-pidfd-crash-custody.py --unit
python3 -B tests/test-pxd-exec-s3-b38l-pidfd-crash-custody.py --smoke
```

## VERIFY

Require actual Linux pidfd syscalls, supervisor forced crash and exit
77, fake parent and leaf still alive after supervisor crash,
SIGTERM through their captured pidfds, both pidfds signaling exit,
and monotonic durable STOP_REQUESTED / STOP_OBSERVED transitions.
B38-K/J/I/H regressions, B34 and Grammar must pass.

## WATCH OUT FOR

**NOT certified process-tree custody:** two deliberately known
descendants are tracked. Unexpected forked grandchildren, escapes,
cgroup membership, privileged actors, FD ownership across
*controller* crash/reboot, and pidfd recovery after controller
restart are not proven.

**NOT equivalent to production cancellation:** fake stop SQLite
is a standalone experiment and is not the B29/B37-C production
ledger. pidfds are kernel references held in a *living controller*;
they cannot be durably stored in SQLite and recovered after that
controller dies. Only the STOP_REQUESTED intent persists.

**NOT B33 remote observation:** pidfd exit describes local OS
processes only. It says nothing about whether a provider request
finished or how to settle budget. It is not atomic with real
physical process launch, nor a mandatory sender fence.

The test parent/leaf processes are not run inside S1 for this
particular pidfd experiment; inherited B38-K tests exercise S1.
Future review must combine the two boundaries without conflating
their evidence.

## CHECKLIST

- [x] Verify B38-K merged, no B38-L colliding ownership.
- [x] Add isolated Linux pidfd fake crash-custody tests and CI.
- [ ] Exact-head CI success and independent Nurse 2 technical review.
- [ ] Operator separate merge authorization.
- [ ] Cgroup v2 accounting / unknown descendant detection, crash-safe
      external stop agent and source-of-truth authorization.
- [ ] Trusted B33 response observation and production certification.

## NEXT

If Linux CI succeeds, hand off for independent Nurse 2 review.
Follow-on implementation must combine owned cgroup v2 process
membership with pidfd / safe kill & reap and supervised recovery.
Do not infer production readiness from this experiment.

## DECISIONS

B38-L is scoped strictly to a disposable fake-only pidfd
demonstration. No local machine, production, real provider or
Hospital writes; B24 and EXEC-S3 production HOLD stay unchanged.
