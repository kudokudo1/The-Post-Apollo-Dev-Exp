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

## 3 // Proposed trust-boundary graph

    Operator / Hospital authorization (trusted)
                  |
                  v
    PX supervisor / policy decision (trusted, no model action authority)
       |                                     |
       | allowed context + prompt            | allowlisted tool request
       v                                     v
    Trusted model-only client             OS-isolated tool broker
    (may hold model auth)                 (never holds model auth)
       |                                     |
       | model response / request            v
       +---------------------------->  disposable isolated tool
                                       (bounded Bed mounts, no network)
                                                |
                                                v
                                       verified outcome/evidence
       |
       v
    PX stores sanitized Doctor message, status, and trusted audit events

The model-only client is NOT by itself a safe tool. Codex/Hermes may contain native
tool abilities. Prior to any real credential integration, independently establish
how the selected provider can run without unmediated shell, filesystem writes,
plugins, remote apps, MCP, network browsing or arbitrary host tools. Configuration
flags, prompt statements, and provider-emitted JSON alone are NOT sufficient proof.
If trustworthy model-only execution and a complete tool-mediation boundary cannot
be demonstrated for a provider, classify that provider UNSUPPORTED and fail closed.

No provider may receive real credentials as an experiment under this contract.

## 4 // Required preflight and refusal ordering

Proposed secure turn order (first turn AND resume):

1. Acquire the existing single-session lock. Read live session, Room, Patient,
   active Assignment, permissions, Bed path and expected repository/branch.
2. Validate active authority and registered Bed/branch target, including symlink
   containment, mount roots, changed authority since last turn, and requested
   working-directory overrides. Permissions must come from *current* Hospital
   state, never historical provider/session content.
3. Select a reviewed, explicitly enabled execution profile and exact provider
   executable/version/flags; reject unknown, downgraded, disabled or changed
   profile. Verify fixed trusted launcher and directory ownership and permissions.
4. Verify the credential-owner/tool-owner separation and prepare minimal
   capability grants. Compute a sanitized environment allowlist; never
   os.environ.copy() for an untrusted process.
5. Re-evaluate first-turn versus resume status and session identity binding.
   An existing native provider session MUST NOT widen Room, Bed, Patient,
   tool capability or credential access; missing/foreign/mismatched resume ID
   fails closed.
6. Construct sandbox and transport topology with network and filesystem grants
   matched to current permissions. Verify namespace and mount requirements,
   tool binary trust, FD closure and audit sink availability.
7. If ANY security preflight fails, do NOT spawn a provider, do NOT send a
   prompt, do NOT append the outgoing operator message, and do NOT commit
   a new native provider session ID. Return a stable refusal reason and
   append only minimal, sanitized, supervisor-owned security evidence if the
   audit sink is usable. Missing audit sink is itself a refusal.
8. Only after all preflight passes: begin a supervised turn, append/store the
   outgoing operator input as appropriate, and launch through the verified
   boundary. On runtime failure, record FAILED safely, terminate the full
   process group/descendants, never silently retry without preflight, and do
   not treat partial output as a completed Doctor response.
9. Revalidate authority for each tool request and at resume boundaries.
   Cross-Patient or foreign Room calls must be denied even if prior provider
   history asks otherwise. A pause/cancel revokes outstanding tool ability.

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
results, designed for mutually suspicious components. A tool request is
untrusted input: validate action type, target/Room/Patient identity,
capability, arguments and size in PX before dispatch. The broker alone decides
whether and how to execute it. Never trust a model/tool statement such as
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

For resume, require compatible identity and a security preflight identical
in strength to a first launch. If a provider's native resume mechanism
automatically restores tools/config/plugins or loads host state not covered
by the boundary, refuse instead of resuming insecurely. Do not fall back
to an unconfined new session.

The source-side command guards can remain defense in depth for legacy flows,
but cannot be labeled "OS_ISOLATED" or used as the S3 proof.

## 8 // Supervisor-owned audit contract (proposed fields)

Record scrubbed facts rather than secrets. Minimum proposed event names:
- isolation.preflight.passed / isolation.preflight.refused
- isolation.provider.started / isolation.provider.failed
- isolation.tool.requested / isolation.tool.allowed / isolation.tool.refused
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

A. **Source preflight, fake-only**: outdated/inactive/wrong-Room/wrong-Patient
Assignment, Bed mismatch, symlink escape, dirty valid Bed, unknown provider,
missing/untrusted bwrap, altered provider binary, unexpected environment
or socket, unavailable audit sink. Verify refusal before outgoing message
append and before spawning any provider/tool. Positive dirty matching Bed
continues where authority allows.

B. **Start and resume equivalence, fake-only**: fresh session, matching native
ID, mismatching native ID, foreign Room/Patient identity, revoked authority,
changed branch/path/profile, missing native resume capability, leaked prior
mount grants, paused/cancelled and concurrent sessions. Zero fallback to
unconfined operations.

C. **Credential/IPC negative tests, fake-only**: fake secret canaries,
parent-held FD, inherited environment, unintended unix sockets, argv,
stdout/stderr and logs, size/command injection and spoofed tool requests.
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

Nurse 2: review and challenge the proposed separation, real Codex model-only
feasibility prerequisite, pre-append fail-closed rule, resumability, audit
trust and acceptance matrix. Mark questions **OPEN** rather than silently
claiming provider capability. Head Nurse .C: coordinate collision review
with active PX/Hospital work, and submit a small operator-readable approval
packet for an eventual S3 implementation phase.

**Status on submission:** DESIGN PROPOSAL ONLY. S3 implementation HOLD;
real provider security certification HOLD; production Doctors HOLD.
