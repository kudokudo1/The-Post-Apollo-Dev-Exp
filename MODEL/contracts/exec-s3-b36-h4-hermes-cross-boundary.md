# PX EXEC-S3 // B36-H4 Hermes Cross-Boundary Negative Integration

> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (Hospital-compatible external coordination, not live attached)
> ASSIGNMENT // H4 cross-boundary negative integration of H1, H2, H3, B24
> BASE // H3a merged main `2dbad7928ea1bb9183b0b57bb5685bc9b49948a5`
> STATE // DRAFT · GITHUB SOURCE + CI ONLY · REAL PROVIDER DENIED

## IMPLEMENTATION

H1, H2, H3 and B24 are merged and individually refuse real Hermes execution. Their **composition is not automatically safe**: independently well-formed records can refer to different Patients, Rooms, Assignments, Sessions, Turns, generations, startup triggers or cancellation stages.

`bin/px_s3_b36_h4_hermes_cross_boundary.py` is a pure negative-evidence coordinator. It invokes the existing four offline validators against one synthetic case while independently checking:

1. Exact full six-part Hospital scope across H1 recovery, H2 prior-owner state, H2 owner event, H3 supervisor, and a purported expected scope/generation. **The supplied expected scope is also untrusted**, not a Hospital authority grant.
2. H2's fixture-only owner identity, event sequence and terminal state, including no restart or new event following a simulated closed/quarantined owner.
3. Startup/native replay and platform reconnection cannot be presented as new messages. An automatic recovery event is **forbidden** and can only produce a fake quarantine transition.
4. Ordering of stop intent, H1 cancellation stage, H3 gateway STOP_ACK claim and H3 kernel-observation claim. STOP_REQUESTED cannot carry STOP_ACK; a claimed kernel exit cannot be projected backward to ACK_OBSERVED.
5. B24 synthetic provider restrictions, tool and credential claims. All are rejected for real execution regardless of the apparent evidence.

The core **missing structural link** remains intentional and explicit: H2 only has `fake-gateway-*`, whereas H3 currently has a Boolean `gatewayIdentityVerified` and H1 has no concrete gateway identity. There is no authentically bound gateway owner common to all three, and no authoritative Hospital or kernel receipt source. H4 returns `CROSS_GATEWAY_IDENTITY_BINDING_UNAVAILABLE`, `TRUSTED_HOSPITAL_AUTHORITY_UNAVAILABLE`, `KERNEL_ATTESTATION_UNAVAILABLE`, and `REAL_PROVIDER_PRODUCTION_HOLD` in every result.

The result is **only fixed codes, booleans and a fake outcome enum**, never a candidate/expected scope, secret-bearing input, nextState or raw provider output. It cannot launch, resume, stop or certify any real process. `require_real_hermes_execution` always raises.

## HOW TO USE

No Fedora changes or real gateway probe. From a disposable checkout:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b36-h4-hermes-cross-boundary.py

The existing Actions workflow runs this suite before H3, H2, H1, B35, B34 and prior S3 negative regressions.

## VERIFY

41 new H4 tests cover stage-consistent fake reservation/stop/ACK/exit, three replay triggers, cross-document owner/scope/generation drift, stale and invalid authority, bad event sequence, cancellation stage inversion, premature ACK/OS claims, denied native tools/credentials, B24 provider profile drift, crash/revocation, malformed and malicious untrusted objects, no raw payload copying, and zero attempted file/socket/subprocess activity.

Expected PR integration: **428** (H4 41 + H3 28 + H2 26 + H1 23 + B35 22 + B34 14 + B24–B33 274). Exact main baseline: **274** (historical B24–B33 suites by workflow design). CI results and generated checkout SHA must be inspected after the PR opens; test count alone is not attestation.

## WATCH OUT FOR

- **NOT A TRUSTED SUPERVISOR.** H4 composes disposable source evaluators with untrusted Python dictionaries. No real Hospital state, gateway auth, kernel cgroup observation, pidfds, credential namespace, native-tool denial or process execution.
- **A gateway `STOP_ACK` cannot prove all descendants stopped.** H4's `FAKE_KERNEL_CGROUP_EMPTY` is an H2 test symbol and must never become an acceptance receipt.
- Existing personal `hermes-gateway.service` is a shared gateway for other purposes; do not change, kill, start, or reuse it in these experiments. The Hermes CLI is not a proven turn execution owner.
- B24 secure real-provider admission stays hard DENY. This PR does not touch `bin/px-agent`, `config/agent-providers.json`, local Fedora, credentials, live Hospital, or production.
- These checks find contradictions in fake evidence but **cannot** prove actual runtime model-only capabilities. The next checkpoint must be independently specified and approved.

## CHECKLIST

- [x] Verify merged main, ownership and previous contracts
- [x] Implement H1/H2/H3/B24 negative composition without real dispatch
- [x] Add 41 malicious/cross-boundary test cases
- [ ] Verify PR merge checkout, source and full CI
- [ ] Independent security acceptance and operator-authorized merge
- [ ] Specify dedicated real gateway owner identity end-to-end
- [ ] Prove suppression or PX-only mediation of all Hermes native tools
- [ ] Verify authenticated STOP/independent kernel teardown and unknown/restart fencing
- [ ] Separately authorize limited real-provider feasibility and any host changes

## NEXT

**B36-H5 (proposed)** should address the non-fake engineering gap with an independently reviewed **disposable local gateway probe plan**, not an immediate launch. The plan must identify the actual Linux OS isolation unit and Hermes gateway API surface, bind Patient/Room/Assignment/Session/Turn/Generation to a newly issued gateway identity, describe a no-network/no-credential dry-run to test process ownership, and define kernel-observed cancellation before any authenticated model turn. Prove ALL native tool execution paths unavailable or strictly PX mediated before S3 admission is enabled. If the pinned Hermes release cannot do this, declare the native CLI **UNSUPPORTED** for secure S3, rather than pretending a Python fixture is a sandbox.

## DECISIONS

Draft PR, no merge, no local-machine modifications, no credentials, no real Hermes execution, no new Hospital registration and **PRODUCTION HOLD**.

## RECOVERY / HANDOFF

New `bin/px_s3_b36_h4_hermes_cross_boundary.py`, `tests/test-pxd-exec-s3-b36-h4-hermes-cross-boundary.py`, this document. Modified existing offline integration Actions workflow by one test step. Reacquire live branch and main before any future changes. Rollback by closing this draft PR or separately authorized revert after merge.
