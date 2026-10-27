# PX EXEC-S3 // B36-H7 Fedora Host Evidence-to-Feasibility Review

> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (Hospital-compatible, not live attached)
> ASSIGNMENT // H7 interpret H6 sanitized host capability evidence without any real gateway probe
> BASE // H6 merged main `372ebf2607392cea079fd4f468541fab3bd33299`
> STATE // DRAFT · OFFLINE INPUT ONLY · NO HOST OR PROVIDER ACTION
> PRODUCTION // HOLD

## IMPLEMENTATION

H6 is now merged and provides a deliberately restricted **opt-in read-only Fedora collector**, but no actual operator Fedora results have been supplied in H7. Do not guess them from the Fedora distribution, prior screenshots, or GitHub's Ubuntu runner.

`bin/px_s3_b36_h7_feasibility_from_h6.py` consumes **only H6's sanitized bounded JSON report** from stdin, with exact schema, field, reason-code, nested-controller and tri-state validation. It does not open host files, enumerate PIDs, connect to services, spawn processes, touch Hermes, inspect credentials, or write data. It is inactive by default and only reads stdin on explicit `--stdin`.

Its limited purpose is **choose which disposable, non-Hermes isolation experiment would be worth reviewing next**, not grant execution. It uses two conditional checklists:

- `systemdUserScope`: cgroup v2 mounted at the standard path, this process in a unified cgroup, `pids` controller visible, fixed `/usr/bin/systemd-run` executable metadata and a current user-bus socket. Even with all present, this is `POTENTIAL_FAKE_EXPERIMENT_ONLY`, *not* delegated cgroup control, process identity, working user-service systemd, or proof that `systemd-run --user --scope` can confine a worker. A tool's presence is insufficient to prove successful unit launch, `Delegate=`, `KillMode=`, subtree delegation, or teardown.
- `bubblewrapNamespaces`: fixed `/usr/bin/bwrap` executable metadata, current user/mount/net namespace links, and positive user namespace sysctl and max count. Even with all present, the result is `POTENTIAL_FAKE_EXPERIMENT_ONLY`, *not* proof an unprivileged Bubblewrap setup actually succeeds, or that networking/host home/tool/credential access is isolated. On Fedora an absent `unprivileged_userns_clone` sysctl may be legitimately UNKNOWN; never convert UNKNOWN to True.
- `pidfdOrKernelLifecycle` is `NOT_MEASURED`. H6 does not attempt pidfd_open, cgroup.procs reads, direct OS kills, delegated cgroup creation or any syscall probes.
- Hermes native tool denial, per-turn authenticated STOP, restart safety and credential isolation remain `SOURCE_AUDIT_REQUIRED`, independently of either OS strategy.

Outputs contain only fixed enums, a recommended **future review direction** and fixed refusal codes. No raw H6 observations, cgroup paths, identity strings, secrets or arbitrary user input can be echoed. Every output reports `DENY`, `launchAuthorized=false`, `hostAttested=false`, `realHermesSupported=false`, zero provider/gateway/tool/Hospital calls and `productionReady=false`. A forged H6 report asserting launch approval, kernel attestation, native tool safety, nonzero model calls or an unknown reason set is rejected as untrusted.

This is **not an implementation of the real gateway** and does not replace a trusted supervisor.

## HOW TO USE

During this PR, no Fedora action is requested, performed or required. Only injected synthetic H6 reports are used in CI.

After independent merge/security acceptance and if an approved clone already contains H6/H7, a **separately operator-reviewed read-only** usage on the operator's Fedora host would be:

    PYTHONDONTWRITEBYTECODE=1 python3 -B bin/px_s3_b36_h6_readonly_host_inventory.py --host-readonly |
      PYTHONDONTWRITEBYTECODE=1 python3 -B bin/px_s3_b36_h7_feasibility_from_h6.py --stdin

That command makes fixed public OS reads (H6) and pipes only sanitized output into H7. It is **not being run by this worker**, and must not be mistaken for authorized local installation, process creation or real Hermes feasibility verification. Without H7's exact `--stdin` flag, it will not read stdin. Do not execute a GitHub source download piped straight into a shell.

Alternatively, the operator can supply H6's sanitized JSON output in this conversation for a human-reviewed feasibility assessment without deploying H7.

## VERIFY

37 new H7 tests cover valid synthetic H6 potential routes, systemd-vs-bwrap fallback, unknown/absent prerequisites, cgroup/pids/user bus, user namespaces, malformed/spoofed claims, nonzero provider activity, wrong schema/reasons/nested field types, secret-containing fields, huge/recursive data, strict bounded stdin and duplicate-key rejection, disabled default CLI and no host/process/network/filesystem access.

Expected full CI integration: **510** (H7 37 + H6 32 + H5 13 + H4 41 + H3 28 + H2 26 + H1 23 + B35 22 + B34 14 + B24-B33 274). Existing historical main-baseline job: **274** by design. Exact GitHub Actions provenance and counts must be verified after opening the draft PR.

These tests do not establish actual Fedora capability or real kernel attestation.

## WATCH OUT FOR

- A **positive candidate** is permission only to *consider a separately approved fake experiment*, never to run one. A missing user bus does not prove no other route exists. A visible cgroup controller does not prove delegation.
- No authenticated Hermes turn-specific `STOP_ACK` or native tool suppression was proved. The personal `hermes-gateway.service` cannot be reused for secured PX.
- No actual Fedora H6 output exists in this checkpoint. Until it does, declaring a feasible deployment or choosing a production strategy would be speculation.
- H7 requires exact H6 schema and refusal codes. If H6 evolves, update the contract together rather than silently accepting unknown security claims.
- The collector's evidence is untrusted input, even when taken from /proc and /sys: it is **not** a kernel-attested execution receipt and is unrelated to a future gateway's cgroup/namespace state.
- Secure B24 provider admission remains hard DENY. No PX agent, provider configuration, credentials, local files, running Hermes gateway, services or live Hospital state are modified.

## CHECKLIST

- [x] Inspect PR #101 merge and current H6 and H5 source
- [x] Build strict H6-report interpreter with conditional non-Hermes experiment direction
- [x] Add 37 malformed/unknown/no-input-leak offline tests
- [ ] Independently verify full PR CI/Grammar and exact merge checkout
- [ ] Independent security acceptance and operator-authorized PR merge
- [ ] Obtain actual approved Fedora read-only H6 report
- [ ] Determine whether systemd user scope or Bubblewrap candidate is worth a disposable experiment
- [ ] Separate explicit authorization before **any** Fedora writes, new cgroups, process launches, gateway probe, credentials or model call
- [ ] Audit pinned Hermes native tool execution paths, restart/reconnect handlers and authenticated turn-specific stop protocol

## NEXT

B36-H8 should focus on **the observed Fedora host**, not invent a safe gateway. On operator-approved H6 sanitized evidence: record specific missing prerequisites and pick exactly one bounded non-Hermes fake containment experiment for review. That experiment must prove actual isolation and descendant teardown (including `setsid` escape), remain credential-free, and have reliable rollback. Separately source-inspect the pinned Hermes release's ability to disable or mediate *every* native tool channel and provide an authenticated per-turn stop. If this is not possible, mark Hermes native EXEC-S3 MODEL_ONLY **UNSUPPORTED**. Never silently resume interrupted Hospital turns.

## DECISIONS

GitHub source and offline CI only; no local actions, no real Hermes calls, no production activation, no new Hospital assignment. Draft PR remains unmerged pending acceptance. Closing PR rolls back; a post-merge revert requires separate authorization.

## RECOVERY / HANDOFF

New code `bin/px_s3_b36_h7_feasibility_from_h6.py`, tests `tests/test-pxd-exec-s3-b36-h7-feasibility.py`, this contract. Existing offline B34 workflow gets one new 37-case test step. All older tests retained. Recheck GitHub branch state and Hospital ownership before subsequent changes.
