# PX EXEC-S3 // B20 Codex & Hermes real-provider feasibility review

> **STATE //** TECHNICAL PROPOSAL · READ-ONLY RESEARCH · NO PROVIDER EXECUTION
> **ROOM //** PX Doctor Execution Security
> **PATIENT //** The-Post-Apollo-Dev-Exp
> **AUTHOR-SIDE SOURCE //** B19 commit `79321dc6c9dc4bd332e5682714904ff294e51294`
> **REVIEW //** Nurse 2 independent security; Head Nurse .C reconciliation; operator final decision
> **SCOPE //** Public/current provider documentation and reviewed GitHub source only
> **AUTHORITY //** No real credential probe, host inspection, model call, live Hospital write, real provider enablement, merge, or production activation
> **NOTE //** B19 155/155 fixture tests + 3 CI passes prove synthetic behavior only. They are not evidence of authenticated provider confinement.

## 1 // Verdict

**No existing Codex or Hermes execution profile has demonstrated the mandatory S3 model-only and exclusive PX tool-mediation boundary. Neither may be promoted by reusing the legacy native CLI path.**

- **Codex CLI:** *FEASIBILITY OPEN / PRODUCTION BLOCKED*. The registry selects `codex exec --json -` and `exec resume`; no reviewed tool-disable or effective read-only profile is applied there. A *separate, historical* operator-controlled S3 manual acceptance runner explicitly added `--sandbox read-only` and `approval_policy=never`, but that is a continuity demonstration, not model-only isolation. CLI sandbox policy restricts selected actions; it does not demonstrate that the model client has no native tool execution or host file-read ability.
- **Hermes CLI:** *FEASIBILITY OPEN / PRODUCTION BLOCKED*. The registry selects `hermes chat --format stream-json --query-file -` plus `--resume`. Current upstream documentation says stream-json requires an explicit `--model`, which this registry does not provide. This is a **version-dependent compatibility risk**, not proof of an observed local failure. More importantly, current Hermes CLI is a **gateway client**: exiting/detaching the CLI need not cancel a gateway-owned turn. Native toolsets, plugins, hooks, MCP and other persistent sessions require independent confinement and cancellation proofs.
- **Alternative:** Design a dedicated *trusted model-only transport* whose sole authority is inference, not commands. It may be an approved SDK/API client or a provider-supported isolated gateway if strict model-only semantics can be independently proven. This architectural choice needs a separate operator decision; do not silently swap provider identity, billing or authentication method.

**Production status for both: HOLD.** No model-only certification or host runtime inspection was performed.

## 2 // Inspected PX launch, credentials and cancellation (exact B19 source)

| Trust seam | Observed source | Consequence |
|---|---|---|
| Provider registry | `config/agent-providers.json` | Codex and Hermes are native CLIs without S3-certified execution profiles; no version/attestation pin |
| Provider selection | `bin/px-agent` `_run_turn_unlocked`, `resolve_command` | Resolves executable by path/PATH; runs start or native resume args |
| Credentials/environment | `provider_authority_environment` | Copies `os.environ`; PATH Git/GH/PX shims describe **COMMAND_GUARD**, not OS isolation or secret filtering |
| Persistence order | `_run_turn_unlocked` | Appends operator message, then `turn.context` and `turn.started` as *separate* store actions **before** `subprocess.Popen` |
| Process launch | `subprocess.Popen` | Native provider launched in registered Bed with inherited environment and process-group separation; no S3 namespace/tool-mediation boundary |
| Cancellation | `cancel_session` / `terminate_process_group` | Marks Session PAUSED and signals stored active process group; no verified pidfd/cgroup receipt or gateway-side turn-stop acknowledgment |
| Logs/audit | `parse_codex`, `parse_hermes`, `store_event` | Raw normalized provider events can enter Hospital event storage; require secret/output redaction and trusted audit-vs-provider evidence separation |
| Resume | providerSessionId + `startArgs`/`resumeArgs` | Checks native session identity after the response; this does not prove persisted provider config/tools/gateway grants are unchanged before resuming |
| B11–B19 synthetic path | `px_int1_fake_agent_bridge.py`, dispatcher, B18 teardown ledger | Fixed synthetic arithmetic only, no real provider, no credentials; no bridge for general provider tool requests |

**Do not relabel legacy `COMMAND_GUARD` behavior as S3 OS isolation.** Never assume a successful native CLI response proves credential confinement.

## 3 // Codex-specific feasibility

Official current CLI reference documents `codex exec`, JSONL output, `exec resume`, `--sandbox read-only`, configuration overrides, MCP and tool-bearing agent behavior.

Required negative proofs before an authenticated probe is even proposed:
1. Pin installed Codex **binary/version/hash, exact arguments, inherited features and config/profile provenance**; verify source/source-path identity in the actual executor context, not just on another machine.
2. Demonstrate a supported, stable mode in which **ALL native tool, shell, file mutation/read outside permitted prompt, MCP, hook, plugin, web/search, app and delegated execution paths** are either absent or exclusively mediated by PX. `--sandbox read-only` and `approval_policy=never` are **not** sufficient alone.
3. Ensure the trusted model client receives only approved context and credentials; no editable Bed mounts, host HOME or privileged tool handles. A model-only client may need restricted network for inference; this never grants network to an untrusted tool.
4. On resume, reject the native session unless model-only mode and every feature/tool grant are revalidated against the same Room/Patient/Assignment, Bed, authority generation, credential profile and native session identity.
5. Establish child/process ownership, signal/kill and *kernel-observed* termination evidence for the actual Codex version; do not substitute `killpg` return or native JSON output for proof.

**Codex priority:** An older operator decision selected Codex for a *manual Doctor succession acceptance exercise*, not blanket approval to invoke Codex in S3. Do not use that historical choice to infer a running login, credential availability or execution authorization.

## 4 // Hermes-specific feasibility

Current upstream descriptions expose `hermes chat` as a gateway-attached CLI. Its session can survive CLI detachment, persist state in its own database, and resume with stored tool/profile settings. Structured stream-json needs explicit model selection in the current documentation, and session stream events include `tool_use`/`tool_result`.

Required negative proofs:
1. Pin actual Hermes version and determine whether it uses a **gateway owner**, separate worker, attached CLI, persistent session, scheduled task or background delegation. Enumerate descendants and independently running owners; no assumption that CLI PID or its process group owns all work.
2. Establish an authenticated, execution-generation-bound gateway stop/interrupt protocol for **one exact Room/turn**. Check acknowledged stop *and* OS-observed terminal state of every granted tool/descendant before claiming termination. A local WebSocket control surface is a privileged API and must not be exposed to the untrusted tool.
3. Reject gateway reuse across different Rooms/Patients unless complete isolation and authorization can be independently demonstrated; preferred first design uses a dedicated, disposable per-Doctor profile/gateway with no persistent unrelated sessions, cron, messaging integrations, background child or ambient sockets.
4. Show exhaustive tool suppression (builtins, terminal, browser, web, delegation, MCP, hooks, skills, plugins and remote services). `--safe-mode` disables customizations but is not by itself evidence that all builtin tools are removed; `--ignore-user-config` still permits environment/credential loading according to upstream docs.
5. Determine precisely how stream-json, required `--model`, tool request interception, resume identity, stderr/session ID, full `result` terminal event and interrupted/unknown admission states behave for the **pinned** release. Validate no fallback to legacy text output as an implicit security downgrade.
6. Treat gateway restart state `unknown` as unresolved side effects, never automatic retry or completed Doctor output. Define PX↔gateway dual-ledger reconciliation without granting native Hermes sessions authority to write Hospital acceptance records.

**Hermes currently has an additional control-plane problem beyond Codex:** the CLI may not be the execution owner. Until gateway stop and persistent-session boundaries are demonstrated, a CLI kill is not a valid cancellation claim.

## 5 // Minimum S3 reference architecture (proposed, not approved)

```text
Hospital Room / Patient / Assignment / Bed (authoritative)
                 |
                 v
PX trusted supervisor (single-use turn & generation, durable audit)
                 |
         Stage A static checks
                 |
         Stage B verified idle OS broker
                 |
         Stage C atomic accepted attempt
                 |
          trusted MODEL-ONLY client
         (credentials; inference network ONLY)
                 |
        untrusted proposed tool intent
                 v
PX policy validator + authority/nonce/Bed checks
                 |
           single-use IPC grant
                 v
PX-controlled isolated tool broker
(no model credentials, host HOME, arbitrary egress, ambient FDs)
                 |
               result (untrusted data)
                 v
PX sanitization + durable result + model continuation
```

**Invariant:** Model-to-tool, provider-to-tool, tool-to-tool, and gateway-to-tool bypasses are forbidden. If the native provider cannot prevent an independent execution route, classify that provider **UNSUPPORTED for the S3 secured profile**.

## 6 // Required restart, cancellation and persistence semantics

- **Before accepted turn:** An absent/mismatched provider binary, unknown model-only capability, dangerous enabled tool, missing trusted audit, stale Assignment, unsafe Bed, bad broker readiness or compromised credential separation must refuse **without outgoing operator message, provider launch or tool startup**.
- **After accepted turn:** If the trusted provider fails, persist accepted attempt as FAILED with no Doctor reply and no automatic duplicate request. Durable identity/nonce prevents replay.
- **Cancellation:** Commit a bounded turn-specific intent with explicit actor/Room/Session identity; fence model continuations and broker grants; interrupt the *actual execution owner* (gateway when applicable); prove verified tool/descendant teardown independently. Report `REQUESTED`, `ACKNOWLEDGED`, `TERMINATED_VERIFIED`, or `UNVERIFIED` distinctly.
- **Supervisor crash:** Existing B19 evidence holds only for the fake tracked wrapper/one descendant. If trusted teardown evidence is missing, do not infer death, retry or completion. Query reconciled provider/gateway state only through separately reviewed authenticated channels; unknown native effect means manual no-retry closure.
- **Double ledger:** An ACK from Codex/Hermes, a model response, a broker result, a supervisor teardown receipt, and a Doctor message are **five distinct events**; none implies the next. Only PX's trusted atomic state transitions can declare success.
- **Audit:** Keep event metadata bounded/redacted; never store credential values, entire ambient env, secret-bearing native output, auth sockets or unredacted tool arguments as security evidence.

## 7 // Gate-by-gate acceptance matrix

| Gate | Required evidence | Today |
|---|---|---|
| B20-1 current-source inventory | Provider registry, actual PX launch/cancel/resume path and public provider docs | **DESIGN EVIDENCE COLLECTED** |
| B20-2 local pinned binary inventory | Correct host/toolbox provider binary, signed/hash/version, actual `--help`, explicit feature/tool inventory, auth **status only** | **NOT INSPECTED** (local access/approval required) |
| B20-3 strict model-only capability | Exhaustive native tool deny/no-bypass behavioral proof, including resume and automatic gateway/tool hooks | **NOT PROVEN** |
| B20-4 credential transport confinement | Trusted client only, no host secret/env/FD/sockets or unexpected network in broker | **NOT PROVEN** |
| B20-5 execution ownership | Kernel-observed process tree / gateway worker ownership / cgroup-pidfd stop proof | **NOT PROVEN** |
| B20-6 cancellation and crash | No background continuation, no replay, explicit gateway unknown/stop reconciliation, bounded durable attestation | **NOT PROVEN** |
| B20-7 concurrency and Hospital authority | Cross-Room/Patient and per-turn isolation, permission downgrade, same-session resume equivalence, full HANDOFF/Chart preservation | **FAKE ONLY** |
| B20-8 live capability promotion | Nurse 2 exact-SHA independent review, Head Nurse reconciliation, operator approval for bounded probe, then separate production gate | **HOLD** |

Do not infer a successful provider API/authentication or usable subscription from the presence of binaries, source config or historic notes.

## 8 // Recommended decision path

1. **Keep B19 and PR #83 fake-only, draft and unmerged.** Close B20 as a *planning/evidence* checkpoint only; no CI test count is implied by writing a markdown file.
2. **Codex first for version-pinned feasibility**, honoring the historical preference without using credentials yet. Research whether a guaranteed *model-only* transport is available. If not, specify a separate trusted API client (potentially different billing/credentials) as an **unapproved architectural alternative**, or mark Codex CLI UNSUPPORTED for secured S3.
3. **Hermes separately**: gateway ownership/cancellation and custom/tool suppression must be independently addressed. Do not treat its client PID as the worker, and do not start/stop the operator's gateway in a feasibility test.
4. **Next engineering proposal** should be only a disposable *fake* provider-capability adapter with no real executable, network or auth. Host binary inventory, any authenticated test, real billing, local installation, repository merge and production activation each require their own explicit operator authorization plus required independent security acceptance.

## 9 // Source and provenance

**Canonical internal references, source reviewed at B19 commit:**
- `bin/px-agent` (`provider_authority_environment`, `build_hermes_turn`, `_run_turn_unlocked`, `cancel_session`, `parse_codex`, `parse_hermes`)
- `config/agent-providers.json`
- `MODEL/contracts/exec-s3-doctor-execution-isolation.md` (proposed S3-C1/C2/C3 and credential gate)
- `MODEL/contracts/exec-s3-px-dispatch-integration-plan.md`
- `docs/hospital/S3_REAL_PROVIDER_SUCCESSION_ACCEPTANCE.md` (separately authorized manual exercise, not an S3 authorization)
- `bin/px_int1_fake_dispatch.py`, `bin/px_int1_fake_agent_bridge.py`, `bin/px_int1_fake_lifecycle.py`

**External primary documentation inspected on 2026-10-22 (not host runtime attestation):**
- Codex CLI options: https://learn.chatgpt.com/docs/cli/reference
- Codex noninteractive exec: https://learn.chatgpt.com/docs/developer-commands
- Hermes CLI / gateway: https://hermes-agent.nousresearch.com/docs/user-guide/cli
- Hermes CLI stream-json/model and tool options: https://hermes-agent.nousresearch.com/docs/reference/cli-commands
- Hermes gateway restart unknown and generation fencing: https://hermes-agent.nousresearch.com/docs/developer-guide/gateway-internals
- Hermes tool capabilities and plugin exposure: https://hermes-agent.nousresearch.com/docs/user-guide/features/tools

**Verification classification:** GitHub source read and public docs inspected; no local CLI/version checked, no authentication performed, no model call, no process or network probe, no live execution, no Hospital DB write.


## 10 // B21 implementation decision: fake capability admission only

> B21 is a **source-owned disposable-fixture contract**, not a Codex or
> Hermes execution adapter. It carries no credential, process launch,
> generic model transport, native tool capability or production grant.

The B21 adapter in `bin/px_int1_fake_capability.py` pins an exact
versioned `int1-fake` profile, checks the existing fake provider registry
and Linux read-only source mounts, and hashes the fixture's source-owned
broker, dispatcher and adapter files. Those bytes are observed inside the
already accepted isolated fixture, **not signed provider attestation**.

The real `px-agent` fake preflight checks this profile without accepting a
turn; synthetic execution rechecks it immediately before source parity and
dispatch. Both responses clearly expose `modelOnlyCertified: false`,
`realProviderCertified: false`, `productionReady: false`,
`realModelCalls: 0` and `nativeToolsAllowed: false`. The test probe rejects
mismatched contract versions, Codex/Hermes IDs, credentials, tools, gateway
ownership, native resume, unsafe cancellation and automatic replay.

**B21 does not change `config/agent-providers.json`, open an authenticated
provider, or authorize any new execution profile.** It is a negative-path
building block for the separate version-pinned, operator-authorized real
provider feasibility gate. The parent B20 assessment remains PROPOSED.
