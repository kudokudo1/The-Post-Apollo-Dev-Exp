# PX EXEC-S3 // B35 Read-only Real-Provider Binary Inventory

> STATE // DRAFT · GITHUB SOURCE / CI ONLY · HOST OBSERVATION PENDING
> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (Hospital-compatible, not live-attached)
> STAFF // PXD successor, scoped B35
> BASE // B34 merged main 31c2e82d6534d30b3a09b3b297343ded1af857fb
> AUTHORITY // bounded GitHub preparation; no native provider turn, host mutation, production or credential access
> REFERENCES // exec-s3-b20-provider-feasibility-review.md, B24 default DENY, B34 merged-main verification

## IMPLEMENTATION

B34 passed 288/288 offline tests on real merged main. The next *real-world feasibility prerequisite* from B20 is B20-2: accurate host-specific provider executable identity. B35 provides a read-only fingerprint helper, not another synthetic model-turn simulator.

- bin/px_s3_b35_provider_binary_inventory.py takes one explicitly chosen absolute executable path and a Codex/Hermes name. It never searches PATH, launches a provider, inspects provider configuration/login, sends a network request or accesses live Hospital.
- It resolves a launcher symlink, opens the target as a regular executable with O_NOFOLLOW, bounds the read to 128 MiB, hashes it and checks metadata before and after. It reports observed path, target, kind, size, inode, mtime and SHA-256.
- Every success reports decision INVENTORY_ONLY, versionObserved=false, modelOnlyCertified=false and productionReady=false.
- Missing/relative/changed/non-executable/nonregular/oversize inputs refuse with stable codes, without exposing input bytes or path in an error.
- Tests use only disposable synthetic executable files; no native provider, SDK, network, credentials or Hospital writes.

This is **not** a trusted interpreter or entire launch-chain identity, native feature inventory, authenticity check, sandbox audit, tool suppression proof, credential safety certification or provider admission. A script hash does not hash its interpreter, imported modules, plugins, dynamic libraries, gateway or execution owner.

B35 does not edit bin/px-agent, bin/px-hospital-store, config/agent-providers.json, Fedora, local services or the Hospital database.

## HOW TO USE

There is no verified Post-Apollo UI control for executable inventory. After B35 source review, the operator can choose a READ-ONLY Terminal check from a reviewed B35 checkout in the exact host/Toolbox context where execution would occur:

    command -v codex
    python3 -B bin/px_s3_b35_provider_binary_inventory.py --provider codex --binary "$(command -v codex)"

Use hermes in both positions for Hermes. It never runs codex --version, codex login, hermes chat, a model API, or a gateway. Functions/non-absolute aliases fail closed. The output is JSON. Keep host paths and hashes in a private evidence file until review; never paste login files, secrets, full config or environment into GitHub.

Host inspection remains operator-initiated and is not performed automatically by a PR merge.

## VERIFY

The existing B34 merged-main workflow is extended to run B35 standalone tests alongside B24-B34 regressions. Tests cover exact SHA, symlinks, changed bytes, invalid providers/paths, oversized and special files, changed metadata, structured stdout, scrubbed stderr and no process/network execution.

Passing CI proves only the source behavior on disposable GitHub fixtures, **not** the operator's Fedora or Toolbox binary.

## WATCH OUT FOR

1. Legacy config/agent-providers.json still launches native Codex/Hermes CLIs with no S3-certified model-only mode. Neither has independently verified disabled native shell, browser, MCP, plugins, gateway or resume tools.
2. Fingerprinting a launcher is not fingerprinting its interpreter/package tree or Hermes gateway execution owner. A different host/Toolbox can resolve different bytes. Concurrent filesystem mutation remains a residual risk.
3. A Hermes gateway turn may survive a client CLI exit. Never stop the operator's running Hermes service merely to collect B35 fingerprints.
4. An OpenAI Responses request with no tools and tool_choice none can constrain API-level tool invocation per published docs, but does not prove process or credential isolation and may require separately billed API use. This is an **unselected alternative**, not a silent change to the user's ChatGPT or Codex subscription.
5. No authenticated provider call, cost, production Doctor, real tool-dispatch authority or live Hospital attachment is approved.

## CHECKLIST

- [x] Reacquire B34 merged main and current ownership / PR state
- [x] Inspect current real provider registry, contracts and offline source
- [x] Add explicit-path binary inventory source without provider execution
- [x] Add disposable negative and zero-execution tests
- [ ] Verify B35 PR CI and exact source
- [ ] Independent review and separately authorized merge
- [ ] Operator-initiated Fedora/Toolbox binary inventory
- [ ] Pin whole launcher, interpreter, gateway and capability graph
- [ ] Prove model-only transport, tool mediation, credential safety and cancellation
- [ ] Obtain separate real-provider and production authorization

## NEXT

Verify CI and report the PR for review. After a separately authorized merge, B20-2 local inspection is the next feasibility gate. If the native CLIs cannot demonstrate truly model-only execution, return a clear UNSUPPORTED verdict rather than falling back to command shims. Any alternative authenticated model-only API transport requires a distinct architecture and operator billing/credential decision.

## DECISIONS

B35 is bounded to GitHub source/CI and a manually invoked, non-executing inspection tool. No provider identity, payment route, production rights or live Hospital state changed. PRODUCTION HOLD.

## RECOVERY / HANDOFF

Recheck current main and PR ownership before resuming. B34 merge SHA was 31c2e82d6534d30b3a09b3b297343ded1af857fb; its 288/288 verification is not B35 evidence. New files: bin/px_s3_b35_provider_binary_inventory.py, tests/test-pxd-exec-s3-b35-provider-inventory.py, MODEL/contracts/exec-s3-b35-binary-inventory.md; one change to the existing B34 workflow. Close unmerged draft PR as rollback, or revert B35 commit(s) if later merged. No local runtime or provider credentials were touched.
