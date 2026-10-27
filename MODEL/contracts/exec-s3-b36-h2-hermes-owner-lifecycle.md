# PX EXEC-S3 // B36-H2 Disposable Hermes Owner Lifecycle (OFFLINE)

> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (external Hospital-compatible; not live-registered)
> ASSIGNMENT // B36-H2 disposable owner lifecycle specification and fake verification
> BASE // B36-H1 merged main 3e8ac2563f510c5308b989f13bc37ce72fd9a7bc
> STATE // DRAFT; NO NATIVE HERMES EXECUTION, CREDENTIALS, LOCAL MUTATION OR PRODUCTION ACTIVATION

## IMPLEMENTATION

B36-H1 is the merged fail-closed Hermes native recovery authority diagnostic. This checkpoint creates a **pure, disposable, simulated owner state machine** at bin/px_s3_b36_h2_hermes_owner_lifecycle.py, not a real service or launcher.

A fake owner is bound to one full Patient/Room/Assignment/Session/Turn/Generation scope and a fake-gateway-* identity. Every event must match its owner, scope and consecutive sequence, and carries a fixture-only event ID.

States are UNALLOCATED → RESERVED_FAKE → STOP_REQUESTED_FAKE → ACK_OBSERVED_FAKE → CLOSED_FAKE. The last transition requires a **FAKE_KERNEL_CGROUP_EMPTY** test marker. It is not a kernel receipt. Native startup/reconnect auto-resume, revocation and crash-unknown lead to QUARANTINED_FAKE; terminal states cannot re-enter. Invalid scope, owner, ordering, identity or replay refuses without progressing the fixture.

**Every response denies real execution**, reports TRUSTED_HOSPITAL_OWNER_UNAVAILABLE and REAL_PROVIDER_PRODUCTION_HOLD, and has launchAuthorized=false, terminationVerified=false, and zero model/gateway/tool/Hospital calls. Even CLOSED_FAKE does **not** mean any real process stopped. require_real_gateway_owner always raises. Neither bin/px-agent nor the provider registry is changed.

## HOW TO USE

No Post-Apollo UI or Fedora action is needed. Review the draft PR and its GitHub CI. To reproduce in a disposable checkout:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b36-h2-hermes-owner.py

## VERIFY

26 disposable tests cover: idle fake seed, ownership and scope validation, ordered fake lifecycle, ACK ≠ OS termination, fake receipt ordering, terminal no-reentry, revocation/crash/startup/reconnect quarantine, all six scope dimensions, wrong owner, replay/gap, malformed or fabricated state, immutable inputs, no subprocess/file/socket effects and unconditional real-admission refusal.

The integration workflow expects B36-H2 **26** + B36-H1 **23** + B35 **20** + B34 **14** + B24-B33 **274**, total **357**, on the GitHub PR merge checkout. Exact existing-main baseline only runs the older **274** tests, by established workflow design. Actual workflow results must be independently inspected.

## WATCH OUT FOR

1. These are **untrusted Python dictionaries**, not durable leases, live Hospital authorization, kernel pidfd/cgroup observations, authenticated Hermes ACKs or working cancellation.
2. The operator's installed Hermes gateway can auto-recover interrupted sessions; the personal hermes-gateway.service must not be restarted, modified, or recruited into Hospital. A separate disposable gateway remains a **proposed** real implementation, not an H2 deliverable.
3. Even a dedicated native gateway needs model-only tool denial, isolated credentials, reliable gateway-owned stop acknowledgement, kernel-observed descendants and restart/unknown reconciliation. H2 implements **none** of those OS or provider mechanisms.
4. Legacy CLI and B24 secure admission remain production DENY. No local Fedora write, model call, service restart, credential inspection, native process, or live Hospital write.
5. B35's separate size cap for the observed ~289 MB Codex binary remains outside Hermes H2 scope.

## CHECKLIST

- [x] Reacquire main, H1 merge, current GitHub ownership, Syntagma authority
- [x] Implement fake exact-scoped lifecycle; explicit ACK/teardown separation
- [x] Add 26 negative/ordering/zero-execution tests
- [ ] Inspect exact PR checkout provenance and full GitHub CI counts
- [ ] Independent security review and operator-authorized merge
- [ ] Design trusted single-use actual owner and credential separation
- [ ] Add authenticated per-turn gateway-stop and OS teardown proofs
- [ ] Enforce Hospital authority on each turn/recovery path
- [ ] Separate approval for local install, authenticated probe and production

## NEXT

B36-H3 (separately scoped) should specify and test an offline trusted-supervisor adapter interface: fresh Assignment authority before model request, owner identity and generation, cancellation intent, authenticated per-turn gateway ACK, real OS-observed process tree teardown, replay rejection and fail-closed unknown states. Do **not** wire H2 fake markers to a real launcher or claim that a personal gateway is safe.

## DECISIONS

B36-H2 advances only **fixture specification**, not actual disposable gateway construction or production acceptance. This draft PR is reversible by closing it. Post-merge rollback would require separately authorized revert. No live Hospital registration is claimed.

## RECOVERY / HANDOFF

Expected new: bin/px_s3_b36_h2_hermes_owner_lifecycle.py, tests/test-pxd-exec-s3-b36-h2-hermes-owner.py, this contract; existing workflow receives a single new B36-H2 test step. GitHub is source of truth; recheck PR HEAD and base before any later implementation.
