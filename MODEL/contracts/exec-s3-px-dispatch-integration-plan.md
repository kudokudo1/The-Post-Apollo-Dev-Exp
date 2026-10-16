# PX EXEC-S3 // Actual PX dispatch integration planning gate

> STATE // TECHNICAL PLAN ONLY · PROPOSED · NO RUNTIME IMPLEMENTATION AUTHORITY
> ROOM // PX Doctor Execution Security
> PATIENT // The-Post-Apollo-Dev-Exp
> OWNER // Proxy Doctor (engineering) · Nurse 2 (independent security review) · Head Nurse .C (reconciliation)
> BASE // main 41c18802e714e2f38a11f3f01007c93c0675ad14
> PREDECESSORS // EXEC-S1/#76, EXEC-S2/#77, accepted S3 contract/#78, accepted S3 fake-only prototype/#79; all merged
> HARD HOLD // real Codex/Hermes authentication, local Fedora install, live Hospital DB, production Doctor activation, runtime changes until independently authorized

This is a **planning-only** proposal for the NEXT phase. The operator's "let's go" following
the Head Nurse merge checkpoint authorizes preparation of a concrete engineering plan,
not real-provider or production activation. Do not merge this plan or start runtime coding
without a further bounded operator decision and Nurse 2 review.

## 1 // Source facts confirmed on main

- \`bin/px-agent\` already serializes one Doctor turn using \`acquire_turn_lock()\`
  (an \`flock\` on a session-specific file). \`_run_turn_unlocked()\` validates current
  session/Room, registered Bed and working-directory equality, invokes
  \`preflight_edit_target(...allow_dirty=True)\`, then assembles assignment and mandatory
  HANDOFF / approved Chart context using \`live_context_payload()\`.
- The live provider selection comes from \`config/agent-providers.json\` and currently
  lists Codex \`exec\` / \`exec resume\` and Hermes CLI configurations.
- The legacy provider environment uses \`provider_authority_environment()\` with
  \`os.environ.copy()\`, plus PATH command shims advertised as \`COMMAND_GUARD\`.
  This is **not S3 OS isolation** and is not to be relabeled.
- Today, \`_run_turn_unlocked()\` appends an outgoing operator message and emits separate
  \`turn.context\` and \`turn.started\` events **before** \`subprocess.Popen\`. Each
  \`px_hospital\` call launches a separate \`px hospital\` CLI process; those three writes
  are not one atomic SQLite transaction.
- \`bin/px-hospital-store\` currently uses SQLite schema v10, including session,
  message, event and Assignment records. The Assignment table has status/permissions
  but no dedicated monotonic **authority generation** column. The in-process RLock
  in the accepted \`tests/px_exec_s3_fake.py\` cannot protect actual multi-process PX.
- \`tests/test-px-agent-runtime.sh\` supplies a disposable provider registry and
  disposable Hospital storage; \`tests/test-pxd-p1-provider-boundary.py\` and
  \`tests/test-pxd-s2-required-continuity.py\` cover foreign Assignment refusal and
  non-droppable mandatory HANDOFF/Chart context.
- Merged S3 code lives in \`tests/px_exec_s3_fake.py\` and
  \`tests/test-pxd-exec-s3-fake-integration.py\`; it is a fixed tool probe, NOT imported
  by \`bin/px-agent\`. 22/22 unit tests and S1/S2/S3 synthetic OS smoke passed on
  Ubuntu 22.04 at reviewed SHA 3794f432900b3eb783d5f56a192e2adf433909b7.
  Ubuntu 24.04 Bubblewrap loopback setup remains a fail-closed platform limit.

## 2 // Recommended bounded implementation: EXEC-S3-INT1, fake-only actual PX call path

**Goal:** prove that an explicitly selected **synthetic-only** execution profile
traverses the real \`bin/px-agent\` turn path with a **disposable test Hospital/Bed**,
maintains existing context/continuity and enforces Stage A/B/C ordering, WITHOUT
ever launching a real AI provider or touching an installed PX or live Hospital.

**Not in scope:** a real Codex/Hermes model-only client, arbitrary tool execution,
a production Bed EDIT mount, network-enabled tools, a live Hospital migration,
changes to actual installed Fedora services, or enabling production Doctors.

Suggested change areas for a separate *implementation* PR after authorization:

1. **Explicit opt-in profile and fail-closed default.**
   Add an implementation-gated \`EXEC_S3_FAKE_ONLY\` profile selected only by a
   disposable fixture provider registry plus an explicit test-mode invocation.
   Keep default \`config/agent-providers.json\` unchanged. Any Codex/Hermes ID,
   unknown profile, missing isolation prerequisites, wrong registry/Bed, or
   inconsistent start/resume profile MUST refuse, never fall back to
   \`COMMAND_GUARD\` under an S3 label.
2. **Separate code boundary, not an import from \`tests/\`.**
   Refactor audited OS broker construction from the synthetic harness into a
   narrow source-owned module, with explicit sanitized environment, no inherited
   provider credential FD/socket, root-owned absolute Bubblewrap dependency,
   strict mount/network boundaries, bounded child lifetime, and supervisor-owned
   IPC. Keep fake tool schema versioned with single-use nonce and scope fields.
3. **Stage A before any mutation.**
   Use existing Session/Room/Bed/Assignment and required HANDOFF/Chart validation,
   additionally bind provider-profile version, synthetic provider session ID,
   resolved Bed identity, branch/commit and Authority generation. Confirm a
   functioning trusted audit sink or refuse with no outgoing message. No prompt
   goes to any model and no \`provider_authority_environment()\` host-copy runs on
   this path.
4. **Stage B actual broker startup.**
   Start an idle, OS-isolated broker. Verify trusted launcher and kernel-observed
   process/namespace/mount/FD readiness; catch premature exit, corrupted handshake,
   stale \`ready\` flags and profile changes. Revalidate live Room/Patient/
   Assignment/version against the dispatch barrier immediately before acceptance.
   Tear down/reap everything on refusal, still without an outgoing message.
5. **Stage C accepted-turn persistence as ONE storage operation.**
   Design a new, explicitly versioned \`px-hospital-store\` operation that commits
   the outgoing message, \`turn.context\` and \`turn.started\` within a SQLite
   \`BEGIN IMMEDIATE\` transaction, guarded by current authority/profile/turn ID.
   It must be idempotent by turn identity and return the committed operator
   message ID. Do **not** reuse three independent \`px_hospital\` calls and claim
   atomicity. A post-commit fake-provider failure must persist an explicit
   FAILED attempt and must not silently replay a message or mint a session ID.
6. **Authority epoch and multi-process revocation design before dispatch.**
   Introduce a database-backed monotonic authority generation updated atomically
   with Assignment pause/cancel, permission reduction, Room identity/Bed changes,
   and session invalidation. Propose a supervisor↔broker revoke mechanism and a
   serialization strategy for generation-check → one-use grant → *actual pipe
   dispatch*. A per-session \`flock\` by itself does NOT guarantee cross-process
   cancellation. The design must allow revocation while a tool is running,
   terminate/reap descendants and reject partial results. **If this cannot be
   implemented and tested within INT1, stop rather than silently omit it.**
7. **Result and continuity handling.**
   Feed the offline fake model result through the existing message/session event
   pathways with the correct Room, Patient, Assignment, turn and native fake
   session identity. On resume re-run A/B/C; never resurrect tool grants. Preserve
   complete mandatory operator-approved Patient Chart and Room HANDOFF/Chart
   lanes, unchanged historic message IDs and existing report ownership.

No default end-user CLI behavior may be changed on this first slice. If a user
selects a real provider, its current route still has only COMMAND_GUARD safety
and must not claim S3 certification; promotion to a secured provider is separate.

## 3 // Atomicity / revocation risks that must be resolved by source review

| Risk | Current evidence | Required demonstration |
|---|---|---|
| Early persistence | Three store calls precede provider Popen | Stage A/B failures leave zero outgoing message and zero started turn; Stage C atomically accepts once |
| Revocation race | Fake RLock only in one process | Persistent generation changes and cross-process revocation close dispatch race and interrupt running process groups |
| Credential/FD leakage | Legacy host \`os.environ.copy()\`; fake S1/S2 exclude fake secrets | No inherited secret-like environment, auth files, FDs, Unix sockets, or provider-native tool route on S3 fixture |
| Provider feasibility | Current Codex/Hermes registry describes general CLIs | No real-provider call; secure model-only transport is a separate feasibility gate |
| Stale or mismatched resume | Native providerSessionId exists today | Start/resume enforce same Bed, Assignment, provider profile, authority generation and broker readiness |
| Continuity regression | Non-droppable Room and Patient lanes from S2 tests | Mandatory HANDOFF/Chart IDs and content survive on actual \`bin/px-agent\` fixture run |
| Compromised Bed or path | Existing path preflight is not an OS sandbox | Foreign/symlink/swap/mount escapes refuse; no unsafe fallback |
| Failed broker and audit | Fake S3 H1/H3/H4 now accepted | Deterministic premature death, missing audit sink, partial persistence, FD/reap failures all fail closed |
| OS compatibility | Ubuntu 24.04 namespace failure | Preserve no-fallback refusal; no claim of Fedora compatibility without later separately authorized observation |

## 4 // Required acceptance matrix for a proposed INT1 implementation PR

- **Baseline regressions:** existing PX agent/runtime, P1 provider boundary,
  S2 continuity, S1 and S2 fake credential isolation, S3 fake broker tests;
  test with isolated temp dirs and disposable SQLite, not operator home.
- **Preflight:** missing/foreign/paused Assignment, permission change, wrong
  Room/Patient, moved or dirty-but-matching Bed, wrong branch/ref, provider
  mismatch, symlink escape, missing root-owned bwrap, bad audit sink, missing
  native session ID; assert zero accepted outgoing messages for Stage A/B
  failures.
- **Start/resume:** initial fake turn and resumed fake turn from *actual*
  \`bin/px-agent\` invocation with the same persisted fake session identity;
  mandatory HANDOFF, approved Room/Patient Chart, source IDs retained.
- **Permanence:** transaction failure between message/event writes rolls back
  completely, no duplicate message from retry, and post-accepted fake provider
  failure has one FAILED turn with no successful reply.
- **Authority races:** cross-process pause/permission revocation just before
  grant dispatch, during broker startup and during a sleeping tool; verify
  old generation is rejected, process tree killed/reaped, results quarantined,
  no untracked scratch write after cancellation.
- **Confinement/mediation:** no broker socket reachable by model, tool-to-tool
  bypass, replayed grants, forged scope, parent credential canaries or FDs,
  host HOME, unrelated Bed, arbitrary egress; all source claims corroborated
  by independent OS observation.
- **Evidence:** trusted supervisor audit reason codes, raw CI logs and
  automated assertions; record real model calls=0, real credentials used=false,
  installed Fedora writes=0, live Hospital writes=0, productionReady=false.
- **Independent signoff:** Nurse 2 exact-SHA review and Head Nurse .C
  reconciliation BEFORE any INT1 merge decision. A green fake-only PR is not
  real-provider acceptance.

## 5 // Suggested delivery sequence and checkpoints

**INT1-A // Contract-to-runtime seam:** a draft implementation PR with a
default-off fake-profile switch, reusable fake broker adapter, and source tests
proving no default behavior change. Nurse 2 review checkpoint.

**INT1-B // Transaction + authority:** disposable SQLite atomic acceptance
and durable authority epoch/revocation. Test contention from *distinct
processes*, not just RLock threads. Nurse 2 review checkpoint.

**INT1-C // Actual agent fake turns:** run start, resume, refused and revoked
fixture turns through the real \`bin/px-agent\`, verify mandatory continuity,
audit and teardown. CI on supported disposable runner, no authenticated AI.
Nurse 2 independent acceptance; Head Nurse reconciliation; separate
operator decision whether to merge implementation.

**Later gate // provider feasibility (NOT included here):** independently
research stable Codex/Hermes model-only APIs and exhaustive native-tool
suppression; do not experiment with real auth or host-installed CLIs until
operator grants a separately specified authenticated probe. If complete
mediation is impossible, mark provider UNSUPPORTED and fail closed.

## 6 // Operator decision requested

Authorize **only** INT1-A/B/C fake-only PX runtime integration source
changes and tests in a new GitHub development branch and draft PR, with
strictly disposable Hospital fixtures and no real provider or local host
changes. Require Nurse 2 exact-commit review and Head Nurse reconciliation.
This permission would not authorize merge, real provider login, live Hospital
schema migration, installed Fedora changes or production Doctor execution.

Until the operator explicitly approves this separate implementation scope:
**plan only**. All production security gates remain HOLD.
