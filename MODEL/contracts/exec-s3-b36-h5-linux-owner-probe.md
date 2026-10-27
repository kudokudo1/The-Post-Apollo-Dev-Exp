# PX EXEC-S3 // B36-H5 Linux Fake Owner Probe and Real Hermes Isolation Plan

> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (external Hospital-compatible; no live Room claim)
> ASSIGNMENT // H5 Linux kernel ownership reality check and independently reviewable real gateway feasibility plan
> BASE // H4 merged main `35ae23321253547dcd5eb37bd99db0af54989e9f`
> STATE // DRAFT · CI DISPOSABLE FAKE PROCESSES ONLY · NO HERMES EXECUTION · NO FEDORA CHANGES
> PRODUCTION // HOLD

## IMPLEMENTATION

### Why H5 exists

H1–H4 test synthetic authority, recovery, stop-order, and no-replay semantics. Those are necessary but insufficient. The actual Unix process boundary matters: `subprocess.Popen(start_new_session=True)` makes a process the leader of a new session/process group but **does not** prevent a descendant from calling `setsid()` and escaping `os.killpg`. A successful `killpg` does not independently prove all descendants exited, does not establish a dedicated cgroup, and does not prove network egress blocked or credentials inaccessible.

H5 adds a **real Linux-kernel-observed, CI-only experiment with disposable Python fake processes**, not Hermes. `bin/px_s3_b36_h5_linux_fake_owner_probe.py`:

1. Refuses process spawning except on a Linux runner with `GITHUB_ACTIONS=true` AND explicitly set `PX_H5_FAKE_OS_PROBE_APPROVED_IN_CI=1`. No normal local invocation is armed.
2. Launches a fixed Python fake worker in a fresh POSIX session with `start_new_session=True`, `close_fds=True`, an allowlisted environment, /tmp cwd, no stdin, and a fixed short-lived Python sleeper as its only child. No network calls, model calls, live Hermes or Hospital access.
3. Parses procfs `/proc/<pid>/stat` correctly even when the `comm` field includes spaces/parentheses; records PID, process-group, session, parent, state and start ticks to discriminate a potential PID reuse. Reads the CI process's procfs cgroup to identify *differences*, never assert dedicated ownership merely from a different path.
4. Exercises two real OS behaviors in the isolated GitHub Actions runner:
   - **Same-group fake descendant:** the fake worker and child share a process group; `killpg` stops their running execution. The child may remain an unreaped zombie, so real process-tree teardown stays *uncertified*.
   - **`setsid()` fake descendant:** the child creates a different session/process group, is still executing after `killpg(worker_pgid)`, and is cleaned up separately by pinned PID/birth observation. It also has an independent 12-second lifetime bound.
5. Returns only fixed, bounded booleans/enums. No PID, cgroup, credentials, or raw procfs content is exported in the result. Every report is `DENY`, `realHermesLaunched=false`, `completeDescendantTeardownCertified=false`, `credentialBoundaryCertified=false`, `networkEgressPrevented=false` and `productionReady=false`.

**Distinguish facts:** The fake subprocess inherits the runner's Linux network capabilities; *it simply performs no network requests*. The sanitized fake environment is not proof a future real Hermes client cannot read credentials from mounts, IPC, inherited sockets, agent paths or services. The generated tests do not claim an authenticated gateway STOP_ACK, kernel attestation, persistent owner registration, isolated namespaces, or durable gateway identity.

### Concrete next real-gateway design, not implemented

- **Trusted PX supervisor owns the authority.** On every start/resume it must fetch current Patient/Room/Assignment/Session/Turn/Generation from live Hospital. An input dictionary, old user allowlist, existing provider session, or Hermes restart marker has no authorizing force. Reject before sending prompts or writing accepted turns.
- **Owner identity.** Allocate an exclusive disposable supervisor-managed cgroup v2 subtree (e.g. a distinct transient user unit/scope *if supported*) rather than inheriting the operator's `hermes-gateway.service` or only using a process group. Bind a newly generated owner/turn identity to supervisor generation, cgroup identity, Linux boot ID, kernel PID birth/start time, and retained pidfd or equivalent kernel handle. Record an immutable launch profile and all descendant memberships. PID, path strings and self-reported Hermes session IDs alone are insufficient.
- **Zero-credential first.** A separately authorized, **non-Hermes fake worker** should demonstrate the actual target kernel/namespace/cgroup restrictions on Fedora. It must not inherit operator HOME, IPC/sockets, model/provider credentials or unrestricted mounts. Networking must be actually denied (e.g. a proven isolated network namespace plus egress controls), not merely unused. Establish exact tool paths, including shell, MCP, hooks, plugins, browser, skills, delegation, background jobs and auto-resume, before real provider admission.
- **Cancellation:** record `STOP_REQUESTED` bound to owner+generation+turn; an authenticated Hermes `STOP_ACK` would only prove protocol reception/claimed stop; then independently observe and terminate all processes in the dedicated cgroup and all reparented descendants. A trusted observer must attest to the same owner/generation after stop, including cgroup populated state, PID birth stamps and cgroup disappearance/empty status. Unknowns, escaped descendants, crash or restart mean QUARANTINED with no automatic resume.
- **Failure criterion:** if Hermes cannot expose a turn-specific cancellation protocol and disable/mediate native tools, classify Hermes native gateway/CLI **UNSUPPORTED for EXEC-S3 MODEL_ONLY**, not as a partially safe profile. Never convert H1/H2/H3/H4 fake results or H5 fake kernel observations into real authorization.

### Planned approved-host feasibility stages (NONE performed)

1. **READ-ONLY INVENTORY:** identify pinned Hermes binary and config entrypoint (without inspecting credentials); read `/proc` for gateway ownership, cgroup mode and namespace support; inspect systemd user, bubblewrap availability and exact gateway stop/recovery APIs. Existing operator-provided Hermes source proves startup continuation exists, not that per-turn stop is authenticated. This stage can be re-run on operator approval of a *specific* host command set.
2. **DISPOSABLE LOCAL FAKE:** after separate local change approval, create temporary isolated cgroup/namespace for a short-lived inert Python worker and intentionally escaping descendant; demonstrate containment or refuse. Provide PID/cgroup identity, stop receipts and cleaned-up state. Never touch the personal gateway.
3. **HERMES TOOL-FREE / CREDENTIAL-FREE:** only if fake containment is independently accepted, inspect and test a newly isolated **uncredentialed** dedicated Hermes instance for startup/reconnect behavior and native tool channels, without invoking a model. If the pinned release cannot do this safely, stop as unsupported.
4. **NARROW REAL PROVIDER PROBE:** requires a separate explicit authorization after tool/credential/cancel controls and Hospital supervisor integration are proven. Do not initiate in H5. Preserve all B20 eligibility gates and B24 `REAL_PROVIDER_PRODUCTION_HOLD` until independent acceptance.

## HOW TO USE

No Fedora commands or personal-gateway actions. H5's only process-creating test runs on GitHub Actions' disposable Ubuntu runner, with the explicit CI-only enablement on that step. Offline procfs parser/refusal tests can be run without enabling the probe. The test suite:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b36-h5-linux-fake-owner.py

On non-CI hosts the process-creating cases are intentionally skipped. Do **not** try to enable this test on Fedora without a separately authorized local plan.

## VERIFY

13 H5 tests: Linux proc-stat parser including parentheses, malformed/oversized records, current test PID inspection, gating refusal without CI or opt-in, two real fake process-group observations, and unconditional no-credential/network/isolation/production certification. Previous combined regression count is 428; PR integration target **441/441** (H5 13 + earlier 428). Existing historical main baseline remains **274/274**.

CI success proves only the fake experiment on *that GitHub runner*. No local Fedora cgroup or Hermes behavior was executed or certified.

## WATCH OUT FOR

- CI fake worker **does spawn and kill short-lived Python processes** in the isolated runner. It is not a zero-process fixture. It never touches the operator's machine.
- `killpg` is not a security boundary for arbitrary descendants. A new session via `setsid()` can escape the process group. There can also be PID reuse and observation races; this experiment is not a production-grade pidfd/cgroup implementation.
- Even `/proc` kernel snapshots are a limited observation. Proving no escaped descendants requires a trusted cgroup/namespace owner with proper isolation design and an independent OS enforcement plane.
- Temporary Python worker inherits the CI runner's network namespace. H5 explicitly reports networking **NOT blocked**.
- H5 does not run Hermes, touch `bin/px-agent`, `config/agent-providers.json`, credentials, Fedora, personal `hermes-gateway.service`, or live Hospital.

## CHECKLIST

- [x] Reinspect main and H4 merge
- [x] Implement CI-only, no-credential fake OS process identity/cancellation observation
- [x] Establish incomplete process-group containment vs `setsid()` escape as distinct outcomes
- [x] Add explicit no-Fedora-change and staged review/host-approval plan
- [ ] Verify exact new PR CI run, source and generated checkout SHA
- [ ] Independent security acceptance, then operator-authorized merge
- [ ] Approve and inspect local Fedora read-only suitability
- [ ] Build dedicated cgroup/namespace boundary in later separately approved work
- [ ] Verify real Hermes native tool denial, turn stop and credentials by source and separate controlled tests

## NEXT

H6 can propose a no-secrets **read-only host-feasibility inventory** whose output avoids credential paths, for explicit operator review before any local run; it must not automatically start processes or change services. Only after the operator approves should a disposable local fake be considered. Do not add more abstract authorization flags as a substitute for kernel ownership, full descendant containment or model-only Hermes API evidence.

## DECISIONS

Source/CI-only H5. No real Hermes launch, no local writes, no authenticated provider, no production activation, no live Hospital registration. Branch remains draft/unmerged pending independent review. Rollback: close PR; after separately authorized merge revert H5 commits.
