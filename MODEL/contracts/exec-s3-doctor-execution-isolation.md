# PX EXEC-S3 // Doctor execution isolation integration contract

> STATE // PROPOSED · REVIEW ONLY · NO IMPLEMENTATION AUTHORIZATION
> OWNER // The-Post-Apollo-Dev-Exp (PX provider execution security)
> SOURCE // PX main at d1eed3e5b989907f5035e6e8c8e7f8dfe173a254
> PREDECESSORS // EXEC-S1 PR #76 and EXEC-S2 PR #77, merged and independently accepted at *offline synthetic* scope
> NEXT REVIEW // Nurse 2, then Head Nurse .C, then separate operator implementation decision
> PRODUCTION // HOLD

This is a proposed technical contract, NOT an executable plan, installation instruction,
approved provider policy, or authorization to make runtime changes. It is intentionally
distinct from the older Hospital "S3" Doctor succession demonstration and from the
offline EXEC-S1 / EXEC-S2 tests.

## 1 // Goal and non-goals

Goal: Define the narrow prerequisites for PX to supervise a real Doctor turn *without*
giving an untrusted Doctor tool process access to the model login, unrelated projects,
live Hospital storage, operator home, ambient sockets, or a network escape route. Apply
the *same* enforcement on a first turn and on all resumed turns.

Not established by the existing merged tests:

- EXEC-S1 proves Bubblewrap fixture isolation with fake files; it is not a live PX launcher.
- EXEC-S2 proves an in-process fake model service in a trusted parent can keep a
  disposable fake credential away from a fixed, controlled tool probe.
- Neither proves that an actual Codex client can authenticate and produce answers
  while prohibited from autonomously executing unrestricted tools.
- Tool-reported JSON is not trusted security attestation for arbitrary tool code.
- Existing PX command guards are not an OS sandbox.

Do not equate success of the synthetic tests with authenticated Codex safety.

## 2 // Current source seams (verified)

- [bin/px-agent](../../bin/px-agent): _run_turn_unlocked performs session/Room/Bed
  checks and preflight_edit_target on each turn, builds context and prompt, and
  selects provider startArgs/resumeArgs using providerSessionId.
- provider_authority_environment copies os.environ, creates PATH command-guard
  shims, and reports authorityEnforcement = COMMAND_GUARD.
- _run_turn_unlocked appends the outgoing operator message, writes turn.context
  and turn.started, THEN calls subprocess.Popen(command, env=provider_env,
  cwd=Room Bed, stdin=PIPE, stdout=PIPE, stderr=PIPE). Security launch
  preflight cannot safely fail after the outgoing append.
- Provider events are parsed after execution; a resumed providerSessionId
  mismatch is detected, but that is not proof of tool confinement or of secure
  authentication transport.
- [config/agent-providers.json](../../config/agent-providers.json) has Codex
  exec / exec resume and Hermes CLI records; neither currently declares a
  separately enforced credential-isolation capability.
- [EXEC-S1 harness](../../tests/test-pxd-exec-s1-isolation.py) has a fixed trusted
  /usr/bin/bwrap prerequisite and disposable system/fake Patient/scratch profile.
- [EXEC-S2 harness](../../tests/test-pxd-exec-s2-credential-boundary.py)
  models fake client authentication followed by an isolated tool with close_fds=True.

## 3 // Proposed trust-boundary graph (S3-C1 clarified)

    Operator / live Hospital authorization
                    |
                    v
    PX supervisor (trusted: authority, scheduling, audit)
           |                          ^
           | authorized context       | proposed model output and
           | + prompt                 | UNTRUSTED tool request
           v                          |
    Trusted model-only client --------+
    (holds model credentials; no native tool execution)
                                      |
    [PX: validate live Room/Patient/Assignment, tool type,
     arguments, grants, generation and request identity]
                                      |
                           ONLY APPROVED REQUESTS
                                      v
                   PX-controlled isolated tool broker
                    (no credentials; no bypass routes)
                                      |
                                      v
                         OS-isolated disposable tool
                      (bounded Bed grants, no tool network)
                                      |
                           result treated as UNTRUSTED DATA
                                      v
                    PX validates, audits and forwards
                          sanitized result to model
                                      |
                           final Doctor response via PX

**Invariant S3-C1:** There is NO direct model-to-broker, model-to-tool,
provider-plugin-to-tool, or tool-to-next-tool dispatch path. Every tool
request, including calls spawned by a provider's native interface, a resumed
session, or chained tool output, MUST enter PX's supervised authorization gate
and then PX's isolated broker. The model client never owns a broker socket
or executable tool handle. The broker rejects commands lacking a current
PX-authorized, single-use, scope-bound dispatch identity; tool processes
cannot self-authorize or invoke one another as a way around PX. A provider
that cannot reliably disable/mediate *all* native tool paths fails the
provider-feasibility gate and cannot be used for this profile.

The model-only client is NOT by itself a safe tool. Codex/Hermes may contain native
tool abilities. Prior to any real credential integration, independently establish
how the selected provider can run without unmediated shell, filesystem writes,
plugins, remote apps, MCP, network browsing or arbitrary host tools. Configuration
flags, prompt statements, and provider-emitted JSON alone are NOT sufficient proof.
If trustworthy model-only execution and a complete tool-mediation boundary cannot
be demonstrated for a provider, classify that provider UNSUPPORTED and fail closed.

No provider may receive real credentials as an experiment under this contract.

## 4 // Required preflight and refusal ordering

Proposed secure turn lifecycle (first turn AND resume), with three distinct
stages. This section resolves S3-C2; no stage may be silently skipped.

**STAGE A // Static trusted-supervisor preflight (NO outgoing persistence):**

1. Acquire the existing single-session lock. Read current session, Room,
   Patient, active Assignment, permissions, Bed, repository and branch.
2. Validate authority and registered target, including symlink/mount
   containment, working-directory overrides, provider/session resume identity
   and any changed authority. Old messages and stored permissions have NO
   authorizing force.
3. Select an explicitly enabled, reviewed provider execution profile
   (binary/version/flags, trusted broker and launcher) and check credential
   separation, sanitized environment allowlist, FD and socket constraints,
   namespace/mount plan and functioning trusted audit sink.
4. If any Stage A check fails, refuse without starting the model/provider
   or broker, without sending the prompt, and **without appending the outgoing
   operator message or turn.started**. Record a scrubbed refusal only in a
   working supervisor-owned audit sink; if the sink is unavailable, fail
   closed and return an error without pretending to have audited the event.

**STAGE B // Actual sandbox startup and verified readiness (still NO
outgoing persistence or provider launch):**

5. Spawn the *isolated, idle tool broker* with zero tool requests or model
   credentials. The PX supervisor verifies successful process startup,
   required OS namespace/mount/FD restrictions, readiness of the controlled
   transport, valid profile identity and zero unapproved tool-execution paths.
   Readiness MUST be based on trusted supervisor/OS observations, not a
   broker/tool's self-reported JSON or a mere successful configuration check.
6. Handle startup failure, premature exit, malformed or timed-out readiness,
   wrong profile, or broker loss as **pre-persistence refusal**: terminate
   and reap all launched sandbox children, record a sanitized trusted denial
   if possible, and do NOT append the outgoing message, turn.started, or
   providerSessionId. No unsandboxed fallback.
7. Immediately before persistence, atomically revalidate current Assignment
   authority/generation, Room, Patient, Bed, profile, pause state and broker
   readiness under the supervisor's dispatch barrier. Any change or inability
   to obtain the barrier cancels the prepared broker and refuses as above.

**STAGE C // Accepted turn and provider startup (after verified readiness):**

8. **Only now** commit the outgoing operator message and trusted
   turn.context/turn.started state as one clearly tracked accepted attempt,
   or refuse before acceptance if these operations cannot be made
   consistent. Then launch the *model-only* provider through the reviewed
   transport. Native model startup and later tool requests remain subject
   to the same boundary. No model prompt is transmitted before this point.
9. A provider start failure **after** Stage C acceptance does not erase the
   already persisted outgoing message: retain it with an explicit FAILED
   turn and sanitized launch-failed audit event, with no completed Doctor
   reply or new provider session ID. Replaying the message requires a new
   preflight and deliberate turn/retry identity, never a silent duplicate.
10. For every tool request, verify current authority at the dispatch barrier
    and route it only via PX to the broker (see S3-C1/C3). Resume and
    cancellation obey the same stages and failure semantics. A pause or
    revocation stops queued work and actively interrupts running tools;
    do not complete a turn from untrusted partial output.

**Persistence boundary:** A/B errors have NO outgoing message and NO provider
launch. Stage C errors retain a clearly FAILED accepted turn. Neither case
may be labeled a successful Doctor response; both have supervisor-owned
auditable decisions to the extent the trusted sink remains available.

Preserve existing PX continuity behavior and source IDs. Do not silently
delete, truncate, or reorder mandatory Room HANDOFF and approved Chart lanes
to simplify sandbox launch.

## 5 // Credential ownership and provider feasibility gate

The model's credential material, service tokens, login directory, secret-bearing
configuration, and network/session transport belong ONLY to the trusted
model-client side. That process must not become a general shell/tool executor.

Untrusted tools must receive neither:
- credential files or parent credentials through bind mounts;
- bearer tokens, cookies, GitHub/Codex auth, or host environment through argv,
  stdin, configuration files or environment;
- inherited credential file descriptors or agent/SSH/IPC sockets;
- arbitrary network egress, host home directories, unrelated Bed paths or
  host namespace access.

Use a dedicated allowlisted, versioned IPC schema for *tool requests* and
results, designed for mutually suspicious components. The *only* entry to the
broker is the PX supervisor's controlled dispatch channel, never the provider
or its native tool/plugin API. Treat requests as untrusted input; PX validates
action type, target/Room/Patient identity, current Assignment and revocation
generation, capability, arguments, size and one-use request identity *before*
granting a broker dispatch. The broker independently enforces the granted
scope and refuses missing, stale, replayed, wider or unrecognized grants.
An isolated tool's result returns to PX as untrusted data; it never authorizes
a subsequent tool invocation. Never trust a model/tool statement such as
"isolationPassed": true as a supervisor security assertion.

**OPEN DESIGN GATE:** Is actual Codex login usable in a trusted model-only
process with native tool execution reliably disabled? What stable interface
can forward approved tool requests out to a separate sandbox? S1/S2 provide
no answer. If the answer is no, S3 cannot proceed by merely wrapping the
existing full Codex process; a different provider/broker architecture and
separate operator approval are necessary. Hermes requires its own review.

## 6 // File and OS grants

- Read-only grants: only explicitly authorized fixture or Bed paths, by
  resolved identity and registered Room/Patient; no broad host root or HOME bind.
- Writable grants: separate disposable scratch only by default.
  Granting actual Bed EDIT access requires distinct authority, mount review,
  atomicity/rollback and deterministic tests; never infer EDIT from a command
  guard or from successful read-only smoke.
- Do not allow a symlink, traversal, mount alias or swapped path to lead to
  foreign Patient data or credentials. Detect/inhibit TOCTOU where possible.
  A mere pathname comparison is not an OS confinement proof.
- Untrusted tool runs without outbound network by default. Only an
  explicitly reviewed brokered service operation may require network.
- Validate the same fixed trusted Bubblewrap prerequisite on every launch,
  with no unsafe PATH fallback or weaker "run outside sandbox" alternative.
- Tool subprocesses use no inherited credential descriptors, no default
  host cwd/stdio privileges beyond reviewed pipes, and bounded process time,
  memory/output/resource usage. Cancel/reap all children and avoid orphaned
  tasks. Keep security-critical supervisor state outside writable tool paths.

Provider authentication may require network on the trusted model side;
that does not authorize network on the untrusted tool side.

## 7 // Capability identity / resume binding

A future profile MUST bind: provider kind, provider binary/version + flags,
execution mode, native provider session identity, Hospital Room, Patient,
Assignment authority and version, Bed repository/ref/path, granted mount
profile, and tool capability set. Recompute live authority at each turn;
do not treat stored metadata as permission forever.

For resume, require compatible identity and all three secure-turn stages
from section 4, including a new verified sandbox readiness barrier. If a
provider's native resume mechanism automatically restores tools/config/plugins
or loads host state not covered by the boundary, refuse instead of resuming
insecurely. Do not fall back to an unconfined new session.

**Revocation S3-C3 // queued, dispatched and running tools:** A pause,
cancellation, Assignment withdrawal, permission reduction, or Room/Patient
identity change advances a supervisor-owned authority generation and revokes
all outstanding one-use dispatch grants. PX must serialize each
check-and-dispatch operation against changes to the live authority generation,
and the broker must reject any grant whose generation is stale or revoked.
A second authorization check is required at the last launch boundary, not
merely when a request first enters a queue. The supervisor must signal
revocation to the broker and *actively terminate/reap* already-running tool
process groups/descendants, revoke writable grants, quarantine/discard
in-flight results, and move the turn to a safe FAILED/CANCELLED state.
Do not treat a revoked request's prior approval as a license to continue.
If a tool cannot be stopped and verified dead or writable access cannot be
revoked, block further activity and escalate: never claim successful
revocation or a completed Doctor turn.

**Race requirement:** A tool request cannot be authorized using an earlier
snapshot if the Assignment changes between approval and broker dispatch.
Authority checks, dispatch-grant generation, launch and revocation have an
enforced serialization/atomicity strategy to be demonstrated by tests,
including adversarial pauses between validation and launch. Stopping a
running tool may take finite time; that interval and the possibility of
side effects before termination are explicit residual risks, NOT proof
of instantaneous revocation.

The source-side command guards can remain defense in depth for legacy flows,
but cannot be labeled "OS_ISOLATED" or used as the S3 proof.

## 8 // Supervisor-owned audit contract (proposed fields)

Record scrubbed facts rather than secrets. Minimum proposed event names:
- isolation.preflight.passed / isolation.preflight.refused
- isolation.provider.started / isolation.provider.failed
- isolation.tool.requested / isolation.tool.allowed / isolation.tool.refused
- isolation.broker.ready / isolation.broker.startup_refused
- isolation.authority.revoked / isolation.tool.interrupted / isolation.tool.reap_failed
- isolation.resume.validated / isolation.resume.refused
- isolation.cancelled / isolation.completed

Audit only trusted supervisor observations: source commit/profile revision,
bounded Room/Patient/Assignment references, event ID, intent, requested
capability, decision, stable reason code, namespace/mount profile identifier,
provider/native session identifier in a non-sensitive representation, and
relevant test/run provenance. **Do not record** credential/token bytes,
auth file contents, entire environment, arbitrary tool stdout/stderr or
unredacted native login/session material. Sanitize error messages.

Events produced by the untrusted tool are *input evidence*, not privileged
audit facts. Keep file/FD/network guarantees grounded in OS-verified
supervisor conditions and behavioral negative tests. A reported pass from an
arbitrary tool does not certify its own confinement.

## 9 // Acceptance matrix BEFORE execution (proposed)

A. **Preflight and readiness, fake-only (S3-C2)**: outdated/inactive/
wrong-Room/wrong-Patient Assignment, Bed mismatch, symlink escape, dirty
valid Bed, unknown provider, missing/untrusted bwrap, altered provider
binary, unexpected environment/socket, unavailable audit sink; assert Stage A
refuses without outgoing message, turn.started, model launch or tool launch.
Inject broker spawn failure, namespace denial, malformed readiness signal,
timed-out readiness, and post-readiness broker exit; assert Stage B rejects
before outgoing persistence/model launch and reaps descendants. Positive
Stage C test must show supervisor/OS readiness precedes outgoing message,
then provider launch; inject post-acceptance model startup failure and
assert one persisted FAILED attempt, no duplicate prompt, no new native
session ID. Dirty matching Bed proceeds only where current authority allows.

B. **Start and resume equivalence + revocation, fake-only (S3-C3)**:
fresh session, matching native ID, mismatching native ID, foreign Room/
Patient identity, revoked authority, changed branch/path/profile, missing
native resume capability, leaked prior mount grants, paused/cancelled and
concurrent sessions. Exercise permission revocation while a request is
queued, after validation but before dispatch, during broker tool startup,
and during a long-running writable action; assert no new launches under
stale grants, queued requests rejected, running tool group/descendants
terminated/reaped, writable grants revoked, untrusted partial results
discarded, and failure/quarantine if shutdown cannot be proven. Verify
operator message persistence respects Stage A/B/C for every resumed turn.
Zero fallback to unconfined operations.

C. **Credential/IPC + mediation negatives, fake-only (S3-C1)**: fake
secret canaries, parent-held FD, inherited environment, unintended unix
sockets, argv, stdout/stderr and logs, size/command injection and spoofed
tool requests. Attempt direct provider-to-broker socket access,
native-provider or plugin tool bypass, tool-to-tool chaining, stale/
replayed grants and model/tool output that asks for unauthorized follow-up
actions: all must fail at PX/broker boundaries without a launched tool.
A child cannot access credential-bearing resources or trigger unauthorized
network. Strictly allowlist and version each tool action.

D. **Actual OS tool isolation, fake-only**: real Bubblewrap smoke, fake
Patient read-only, scratch writable, foreign Patient inaccessible,
no tool egress, denied write escalation, timeout and descendant cleanup.
Both source/CI and Fedora operator-host observations have distinct provenance.

E. **Trusted model-only feasibility**: *separate approval required* before
any real Codex/Hermes authentication. Verify tool-free provider operation by
negative observation and independent review, not only vendor flags or
LLM statements. If unsupported, stop.

F. **Review**: Nurse 2 independently inspects exact commit, subprocess
boundary, environment/FD handling, first/resume rejection, audit veracity,
failure paths and raw evidence; Head Nurse reconciles scope and records
review decisions. Operator separately decides implementation, merge,
Fedora changes, authenticated provider probe and final production activation.

No check here should claim DONE on the strength of a draft specification.

## 10 // Explicit implementation hold / sequencing

- **NOW authorized:** prepare/document/review this contract on a separate
  GitHub development branch as a draft proposal.
- **HOLD:** changing bin/px-agent, config/agent-providers.json, CLI
  dispatch/resume, Hospital schemas, installed runtime or real provider
  behavior; building and executing S3 integration tests before approval.
- **HOLD:** enabling authenticated model calls, real credentials, login
  migration, adding system packages on Fedora, production deployment,
  activation of Doctors, or merging this draft PR.
- After Nurse 2 contract review and Head Nurse reconciliation, obtain an
  **explicit, bounded operator S3 implementation approval**. Split further
  irreversible/live steps into separate approvals, preserving a fail-closed
  default and a reversible deployment path.

## 11 // Reviewer decision request

Nurse 2: re-review **only** the S3-C1 tool-mediation graph and broker
bypass prohibitions (sections 3/5/9C); S3-C2 explicit static-preflight,
sandbox-readiness and provider-start persistence barrier (sections 4/9A);
and S3-C3 generation-bound revocation and active-tool termination
(sections 7/8/9B). Decide whether these three documentation findings are
closed. Real Codex model-only feasibility remains an OPEN independent gate,
not evidence supplied by revised prose.

Head Nurse .C: reconcile the bounded revised contract and review with
active PX/Hospital work, then submit a separate operator-readable S3
implementation approval decision. No review result itself authorizes code.

**Status on submission:** DESIGN PROPOSAL ONLY. S3 implementation HOLD;
real provider security certification HOLD; production Doctors HOLD.
