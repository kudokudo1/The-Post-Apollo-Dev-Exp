# PX EXEC-S3 // B38-L Host pidfd Custody of One Observed Fake Child

> STATUS // DRAFT · TEST-ONLY · GITHUB CI PENDING · NO PRODUCTION  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // Hermes Integration Security  
> STAFF ROLE // PXD implementation lane, external Hospital-compatible (no verified live registration)  
> ASSIGNMENT // B38-L: kernel pidfd evidence for fixed S1 fake child and owned Bubblewrap wrapper  
> BASE // merged B38-K main c856f6edafb27b3f2a233ad3beaf33653c9dbde9  
> OWNERSHIP // additive test/CI/contract only; B37-C/B38-K owner code unchanged  
> SAFETY // B24 REAL_PROVIDER_DENY · EXEC-S3 PRODUCTION HOLD

## IMPLEMENTATION

B38-K established B29 durable cancellation, OS signal/reap of its own Bubblewrap
wrapper and self-reported scratch heartbeat quiescence. It explicitly did NOT
pin a sandbox descendant by host-kernel identity.

B38-L is a **separate fake-only Linux feasibility experiment**. It reuses
B38-K's exact fixed Python heartbeat child, sealed B37-B request,
B37-C mock SQLite transition, B38-I one-use fake claim and S1 sandbox.
It adds a read-only, bounded host **/proc parent/child census** to find the
one fixed running Python child, requiring:

- An observed child under the owned wrapper ancestry while it is running.
- Expected unique fake nonce in the actual child command-line; sandbox PID 2.
- A distinct Linux PID namespace from the host and host-visible /proc start time.
- A **pidfd** opened for that exact observed child, plus one for the
  directly spawned Bubblewrap wrapper; stable start times before/after pinning.
- Both pidfds initially non-signaled; after B29 cancellation and the existing
  B38-K owner-scoped process-group SIGTERM/wait, both pidfds signal exit.
- B29 CANCEL_PENDING, reserved fake budget, no retry after SQLite restart.

No provider/model/credential, real Hospital mutation, B33 observation or Fedora
installation is performed. The new code does not edit the shared B37-C,
B38-I, B38-J, B38-K, S1 or B38-G implementations.

## HOW TO USE

Review the draft B38-L PR and exact GitHub Actions run. On a **disposable**
Linux runner where trusted Bubblewrap and /proc NSpid are supported:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38l-pidfd-child-custody.py --unit
    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38l-pidfd-child-custody.py --smoke

The CI workflow installs Bubblewrap only on the disposable Ubuntu runner and
also runs all inherited B38-K/J/I/H/G/F/E/D and B37/B38 suites. Unsupported
pidfd or kernel /proc evidence is a **fail-closed test result**, not permission
to fall back to heartbeat-only evidence.

## VERIFY

Require independently checked:
- Exact PR head/base and GitHub-generated merge checkout SHA in job logs.
- Unit tests for malformed NSpid, missing kernel pidfd, unowned handles,
  closed/replayed handles, actual pidfd exit observation and negative
  production/complete-tree receipt.
- Actual pidfd for **both** the owned wrapper and observed fixed child,
  both not signaled before stop and signaled after cancel/stop.
- Distinct namespace, pinned host start time, unchanged B29 reserved budget.
- B38-K real sandbox stop and all inherited OS/ledger regressions.
- Independent Nurse 2 review and operator merge decision.

## WATCH OUT FOR

**Not complete process-tree custody.** A pidfd pins one concrete kernel
process, preventing confusion caused by recycling its numeric PID. The
host's /proc/<pid>/task/<pid>/children enumeration is **best-effort**,
not an atomic snapshot. It can miss newly spawned, reparented, malicious,
or unobserved descendants. The test does not have a delegated writable
cgroup with cgroup.kill; it does not independently certify that *all*
descendants stopped. The fixed fake Python child is not a malicious model.

**Not atomic cancellation/physical spawn.** B38-K's process-group kill and
B29 cancel remain separate. A pidfd exit observation cannot repair this
race and cannot authenticate a provider's remote stop acknowledgment.
A child-controlled heartbeat still contributes weaker evidence but is
not substituted for kernel pidfd exit in the new success criteria.

**Not a trusted response observer.** No B33 witness, settlement, complete
network isolation, real credentials, production process control, mandatory
sender, or authenticated Hospital authority is provided. The returned
receipt explicitly has:
completeTreeCertified=false, cgroupKillCertified=false,
realStopVerified=false, authenticatedB33Witness=false,
productionReady=false, providerCalls=0.

If the CI kernel or namespace layout cannot support host-side pinning,
the PR stays blocked, and the next step is a documented feasibility
decision, not weakening the assertion to a fake pass.

## CHECKLIST

- [x] Independently recheck B38-K merged main and missing competing B38-L.
- [x] Add isolated fake-only host pidfd and bounded process census harness.
- [x] Add CI workflow and durable technical contract.
- [ ] Exact-head CI and disposable sandbox evidence pass.
- [ ] Independent security and source review.
- [ ] Operator merge authorization.
- [ ] Separate cgroup-owned full-tree stop/ack and launch-race design.
- [ ] Production security clearance (NOT AUTHORIZED).

## NEXT

Resolve CI failures only inside B38-L's three new files; preserve B37-C/K
owner boundaries. If the kernel can attest to the fixed child, document
that as an incremental OS-observation milestone. Do not promote its
pidfd pair to a complete process-tree termination guarantee. A delegated
cgroup/pidfd lifecycle protocol and authenticated B33 observer require a
distinct owner-approved assignment.

## DECISIONS

New additive fake-only experiment, draft and unmerged. No real provider,
live Hospital, user-local Fedora writes, real-model stop, or production
activation. Operator holds acceptance and merge authority.
