# PX EXEC-S3 // B36-H11.6 Hermes model-only boundary design review

> STATE // PROPOSED DESIGN · DOCS ONLY · NOT APPROVED FOR IMPLEMENTATION
> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (Hospital-compatible browser worker; no live Room registration verified)
> ASSIGNMENT // B36-H11.6 assess real Hermes native-dispatch interception feasibility and choose a provable fail-closed architecture
> SOURCE // PX main at c3dd9f10c4a0ed9ad4a2346dbe4dea934dc703f4; inspected Hermes revision 5cc1369fa298021f8c740de154ff8c37c30bdcc8
> RELATED // B36-H11.5 draft PR #106; B37-A/B37-B offline request work; EXEC-S3 S3-C1/C2/C3 contract
> PRODUCTION // HOLD · B24 REAL_PROVIDER_PRODUCTION_HOLD PRESERVED

This is a **design review**, not a Hermes compatibility certification, implementation
authorization, runbook for installing a model provider, or permission to modify
Fedora, live Hermes, PX launch/resume, Hospital state or credentials. It must
not be merged as acceptance of any selected implementation.

## IMPLEMENTATION // Observed source mechanisms

The following facts are grounded in the inspected sources. Ten selected tracked
files in the operator's local Hermes checkout were reported clean relative to
the Git revision; that is **not** a whole-installation integrity certification.

| Layer | Exact observed seam | Security consequence |
| --- | --- | --- |
| PX | \`bin/px-agent:provider_authority_environment\` copies \`os.environ\` and creates PATH command-guard shims | Commands not captured by shims are not confined by an OS sandbox |
| PX | \`bin/px-agent:_run_turn_unlocked\` appends the operator message and \`turn.started\` before \`subprocess.Popen\` | No Stage B sandbox-readiness barrier ahead of accepted-turn persistence |
| PX | \`config/agent-providers.json\` Hermes start/resume call \`hermes chat\` | Registered path is the native full CLI, not a certified model-only transport |
| Hermes | \`hermes_cli/main.py:cmd_chat\` initializes and routes the CLI; \`cli.py\` selects toolsets/config | Toolsets are process/runtime configuration, not independent PX authorization |
| Hermes | \`agent/agent_init.py\` calls \`get_tool_definitions\`, building advertised and valid tool names | Hiding tool schemas is useful, but does not remove Python handler execution authority |
| Hermes | \`agent/conversation_loop.py\` processes \`assistant_message.tool_calls\` and invokes \`agent._execute_tool_calls\` | Native request flow can execute inside the credential-bearing provider process |
| Hermes | \`agent/tool_executor.py\` leads to \`model_tools.handle_function_call\`; \`model_tools.py\` calls \`registry.dispatch\` | Python-native tool execution path exists without a PX dispatch-grant identity |
| Hermes | \`tools/registry.py:dispatch\` invokes a registered \`entry.handler\` | Direct handler reachability requires stronger prevention than advertised-tool filtering |

Upstream source links (pinned):
- [Hermes main CLI](https://github.com/NousResearch/hermes-agent/blob/5cc1369fa298021f8c740de154ff8c37c30bdcc8/hermes_cli/main.py)
- [Hermes conversation loop](https://github.com/NousResearch/hermes-agent/blob/5cc1369fa298021f8c740de154ff8c37c30bdcc8/agent/conversation_loop.py)
- [Hermes tool executor](https://github.com/NousResearch/hermes-agent/blob/5cc1369fa298021f8c740de154ff8c37c30bdcc8/agent/tool_executor.py)
- [Hermes function dispatcher](https://github.com/NousResearch/hermes-agent/blob/5cc1369fa298021f8c740de154ff8c37c30bdcc8/model_tools.py)
- [Hermes registry](https://github.com/NousResearch/hermes-agent/blob/5cc1369fa298021f8c740de154ff8c37c30bdcc8/tools/registry.py)

B36-H11.5 [PR #106](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/106)
uses an **inert fake counter** with synthetic generation/replay checks.
It neither imports Hermes nor proves that direct native handler calls are
intercepted. Its correct result is limited to the modeled broker.

## Proposed trust graph // mandatory authority topology

    Operator approval / live Hospital Assignment
                   |
                   v
    PX trusted supervisor and audit ledger
       |                         ^
       | sanitized prompt         | untrusted model proposal
       v                         |
    TRUSTED MODEL-ONLY CLIENT ----+
    (may hold model auth; no native tools, plugins, broker socket,
     writable host home, arbitrary local processes or other tool egress)
                   |
                   v
    PX validate Room/Patient/Assignment/turn/generation,
    tool type, arguments, budget, mount grants, nonce & expiry
                   |
                   v
    PX single-use authenticated broker dispatch channel
    (not reachable or forgeable by model/plugin/native Hermes)
                   |
                   v
    disposable systemd-owned cgroup + Bubblewrap worker
    (no model auth, restricted mounts, no direct network)
                   |
                   v
    untrusted result -> PX validation/audit -> trusted client

**S3-C1:** A provider response is *data* requesting an action. Neither the
provider nor any native callback may execute, authorize, relay, or replay
an action by itself.

**S3-C2:** Sandbox readiness and the last authority check precede accepted
outgoing-message persistence; launch failures after acceptance have an
explicit FAILED state.

**S3-C3:** Generation/revocation is serialized with last-moment dispatch;
running tasks must be terminated/reaped and in-flight results quarantined.
An observed cgroup stop may take finite time and cannot reverse prior effects.

## Candidate architectures (decision pending)

### A. Separate PX-owned model-only request sender (PREFERRED FOR REVIEW)

Use the B37 **conceptual** sealed, tool-free request path as a starting point
for a future trusted model-only client: explicit \`tools: []\`, no native tool
SDK execution, tightly constrained input/output, and a separately reviewed
authenticated sender. Keep all model responses untrusted. A later supervised
tool-request feature must be explicitly designed; \`tools: []\` alone does
not provide a tool-calling Doctor. Never connect B37's **fake** model,
fake ledger, or mock receipts to real credentials/HTTP by assumption.

Advantages: avoids importing a general-purpose agent runtime with many
native side-effect paths into the credential-bearing process; easier to
prove absence of a local handler.

Tradeoff: may not preserve Hermes session formats, CLI memory, or autonomous
tool-loop behavior; such features would need deliberate PX-owned substitutes
or a separate approved compatibility adapter.

Ownership collision: B37-A/B37-B belongs to an adjacent workstream.
This H11.6 document proposes **no edits** to its code, PR, or accepted scope.

### B. Version-pinned Hermes-derived model-only adapter (CONDITIONAL)

Potentially fork/vendor a separately reviewed subset of the pinned Hermes
revision used strictly for model communication. It must not import or
initialize plugin discovery, MCP, hooks, background agents, the tool registry,
native handler code, cron/delegation, browser, terminal or arbitrary
\`execute_code\`. Tool proposals must be data emitted to PX, not calls to
Hermes handler functions. The artifact's interpreter, code, dependencies,
argv, environment and capabilities must be pinned and independently tested.

Reject this candidate if the whole process cannot be made model-only with
host-side OS restrictions *despite* holding credentials. A patch to
\`tools/registry.py:dispatch\` alone is insufficient: other Python code in
the same process could still import modules, spawn processes, open files,
access sockets, or load unreviewed plugins.

### C. Wrap existing \`hermes chat\` with Bubblewrap (REJECT AS SOLE FIX)

H8/H9/H10.2 demonstrate disposable Fedora process/cgroup and sandbox behavior,
but they do not prove the full Hermes CLI becomes a model-only client.
The full CLI needs model authentication/network and includes native tool
and plugin functionality. Running that *same* credential-bearing process
inside one sandbox does not create the required model/client-versus-untrusted-tool
separation. This may provide defense in depth **after** a separate
trusted-model-only proof, never replace it.

**Proposed review preference:** Evaluate A first; keep B available only
if a complete native capability-exclusion proof is achievable. No operator
architecture selection is recorded by this document.

## Specific interception and bypass gates

Before any real Hermes adapter is eligible:

1. **Early bootstrap:** Show that imports, \`_prepare_agent_startup\`,
   plugins, MCP discovery, hooks, startup recovery, GUI/TUI backgrounds
   and cached clients cannot start unauthorized work before PX preflight.
2. **Tool exposure:** No terminal/file/browser/delegate/cron/tool-search or
   indirect wrapper tool is advertised without an actual PX grant.
   Empty \`--toolsets\`, absent \`--toolsets\`, \`--safe-mode\`, and
   \`--ignore-user-config\` are *not* security proofs.
3. **Native bypass:** Adversarially invoke
   \`registry.dispatch\`, \`model_tools.handle_function_call\`,
   deferred \`tool_call\`, plugin hook callbacks and delegation with
   fake handler counters. A refusal must prove **zero handler execution**,
   not merely a safe-looking response text. Test discovery after launch too.
4. **Trust separation:** PX owns the only broker endpoint and secret used
   to authenticate dispatch. Model/native code must not get it from env,
   argv, files, stdin, inherited FDs or sockets. Tool workers receive
   no model auth, host HOME, foreign Bed, ambient IPC or network.
5. **Authority freshness:** All first/resume paths revalidate live
   Room/Patient/Assignment/Bed/generation under the dispatch barrier;
   queue-then-pause, queue-then-reassign, and queue-then-revoke refuse.
6. **Resume / recovery:** Restored session metadata, native tool caches,
   plugin state, new process launches and reconnects cannot re-enable
   native execution or silently replay a tool. Resume gets Stage A/B/C again.
7. **Cancellation:** Verify owner identity and all descendant cgroups from
   trusted OS sources. Distinguish stop-request, termination confirmed,
   empty scope, and state reconciliation; quarantine uncertain outcomes.
8. **Persistence:** No outgoing message on Stage A/B failure. Stage C
   provider startup failure remains FAILED with explicit retry identity
   and sanitized audit, not a false success or silent duplicate.
9. **Evidence provenance:** H11.5 fake counters, H10.2 host kernel checks,
   provider response JSON, native receipts and live Hospital acceptance
   are separate categories; never promote one into another.
10. **Pinned identity:** Store and verify exact installed binary/source
    revision, dependency inventory, native interfaces, config, flags and
    target Bed before testing or admitting a profile. The operator's
    read-only check verified *selected tracked files*, not all runtime state.

## Proposed test matrix / negative acceptance gates

| Test family | Required observable evidence | What it cannot claim |
| --- | --- | --- |
| Offline synthetic broker | Fake counter remains zero under untrusted direct/indirect calls; single-use positive control increments once | Real Hermes interception |
| Detached Hermes code-under-test | In a disposable, credential-free checkout, instrument/replace each handler and attempt direct registry, plugin, MCP, delegated, restored and stream-generated calls | Actual installed gateway isolation |
| Tool-free model client | Show no native import/handler/proc/broker paths and exact outbound request schema, with mock transport | Authenticated provider behavior |
| Fake authority race | Revoke/change/pause between decision and dispatch, including concurrent queue races | Live Hospital atomicity |
| Host isolation | OS-observed unique systemd scope and Bubblewrap constraints, every descendant stopped | Real credential/IPC isolation unless separately verified |
| Fake credential boundary | Disposable sentinel excluded from tool env, files, args, FDs, and sockets | Safety of actual provider auth |
| Real provider feasibility | Separately authorized pinned process, authenticated transport and independent OS/process evidence | Production admission without full review |
| End-to-end Stage A/B/C | Durable ledger and trusted barrier replay/timeout/failure invariants | Final operator acceptance by CI alone |

**No credentials may be supplied merely to run this design's proposed tests.**
Real-provider tests, live Hospital changes, and runtime wiring require explicit
new scope, owner approval and permission. Preserve B24 hard DENY.

## HOW TO USE

Read this design alongside the existing
[EXEC-S3 isolation contract](exec-s3-doctor-execution-isolation.md),
the [B37-A](exec-s3-b37a-tool-free-contract.md) and
[B37-B](exec-s3-b37b-sealed-handoff.md) offline notes, and the
H11.5 draft PR #106. Use the decision gates above to review alternative A
versus B. This document executes no code and provides no operator shell command.

## VERIFY

- Source-inspection design only, grounded in the pinned Hermes commit
  and current PX main noted in the header.
- No adapter, provider, credentials, Hospital state, socket, kernel probe,
  or runtime test was executed as part of H11.6.
- Review must independently confirm the required bypass coverage; passing
  markdown/grammar checks cannot certify security.

## WATCH OUT FOR

- Existing Hermes installation uses a short Bash launcher into a
  versioned Python checkout. A clean Git status for ten files is not a
  complete pinned runtime, and a future update changes the evidence.
- Model-only transport cannot be declared secure solely by \`tools: []\`;
  arbitrary code running with credentials must itself be constrained.
- No in-process software hook can enforce a privilege boundary against
  a malicious component sharing the same Python process/OS privileges.
- Direct network, filesystem or shell actions outside the normal tool
  registry are part of the threat model.
- PR #106 remains a separate **unmerged** H11.5 draft, not a prerequisite
  to merely reading this design. B37 ownership remains separate.

## CHECKLIST

- [x] Verify PX main and H11.5 PR status before design work
- [x] Pin existing Hermes and PX source seams; distinguish source from runtime
- [x] Define alternative architectures, rejection gates and test matrix
- [ ] Independent Nurse/Head Nurse review; identify affected B37 owners
- [ ] Operator chooses an architecture
- [ ] Separately approve any implementation or real-provider feasibility work
- [ ] Prove genuine no-native-tool and credential isolation in a disconnected fixture
- [ ] Validate Stage A/B/C and cancellation before any admission
- [ ] Operator final acceptance

## NEXT

Request architecture selection and cross-lane review. If option A is selected,
design a **separately owned** trusted model-only sender with an explicit mock
boundary before production network work. If B is selected, require an initial
offline Hermes code reachability study in a disposable sandbox before any
fork or runtime patch. Do not mutate native Hermes / PX dispatch from this PR.

## DECISIONS

**No architecture selected.** This document records two conditional options,
rejects sandbox-wrapping the full Hermes CLI as a sufficient standalone fix,
and preserves the existing immutable production HOLD and no-merge boundaries.
