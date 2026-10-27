# PX EXEC-S3 // B36-H1 Hermes Recovery and Authority Fence

> STATE // DRAFT · OFFLINE POLICY SOURCE ONLY · NO NATIVE PROVIDER LAUNCH
> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (Hospital-compatible external coordination, not live registration)
> ASSIGNMENT // B36-H1: refuse Hermes native recovery as Hospital execution authority
> BASE // B35 merged main `39b13a09ad497d18d19f78adeed947b89ea7c2ef`
> AUTHORITY // bounded GitHub development; NO local Fedora writes, service restart, credential use, real model calls, PR merge or production activation

## IMPLEMENTATION

The operator's **read-only Fedora observations** identified a personal `hermes-gateway.service` active as PID 1493, using Python 3.11.16 and containing only one process in its cgroup at the time inspected. Idle state does **not** prove turn ownership, cancellation, or tool termination.

The operator's installed Hermes `gateway/run.py` source showed:
1. Recovery reasons `restart_timeout`, `shutdown_timeout`, `restart_interrupted`.
2. Startup and platform-reconnect `_schedule_resume_pending_sessions()` selection, platform-user authorization, pre-claimed agent slot, synthetic empty `MessageEvent`, and `asyncio.create_task(_run_startup_resume_event(...))`.
3. `adapter.handle_message(event)` enters the message-processing path. A startup-restore timeout may release the gate **without cancelling** unfinished recovery work.
4. Interactive adapters can ask for input; non-interactive adapters can continue interrupted work.

These are host source observations, **not** proof of a currently running model turn or of a defect in ordinary Hermes use.

`bin/px_s3_b36_hermes_recovery_fence.py` provides a pure **diagnostic refusal fence** for disposable envelopes. It forbids startup/reconnect replay; detects restart recovery presented as a fresh turn; checks exact patient/room/assignment/session/turn/generation scope; rejects shared owner, active auto-continuation, missing native tool controls, and unverified cancellation.

Crucially, **the candidate and even the supplied expected scope are not trusted Hospital evidence**. Every result returns `DENY`, `TRUSTED_HOSPITAL_AUTHORITY_UNAVAILABLE`, and `REAL_PROVIDER_PRODUCTION_HOLD`. No grant is created, and the new source is **not wired into legacy `bin/px-agent`**. Existing B24 secure admission remains DENY.

## HOW TO USE

No Fedora action or UI control is needed. Tests use synthetic Python dictionaries only:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b36-hermes-recovery-fence.py

Do not modify the personal gateway or execute real Hermes turns for this checkpoint.

## VERIFY

23 offline tests cover the three Hermes recovery reasons; startup, reconnect, manual and fresh-message inputs; six-part scope mismatch; malformed generations; dedicated-owner and gateway assertions; native tool restriction flags; incomplete cancellation including spoofed `TERMINATED_VERIFIED`; malformed envelopes; immutable input; and zero attempted process, filesystem or socket use.

The existing PR integration workflow runs B36 23 + B35 20 + B34 14 + B24-B33 274 = **331 expected**. Its main baseline remains B24-B33 **274**. CI counts/checkout provenance must be independently verified after the PR is created.

## WATCH OUT FOR

- Source-only diagnostic refusal does **not** establish a real gateway isolation, a trusted kernel attestation, or a Hospital-authorized model-only client.
- A Hermes platform-user allowlist is not an Assignment permission. CLI termination is not gateway-side cancellation; a gateway restore task may survive the startup wait.
- Every native tool avenue must be proven disabled or mediated: shell, filesystem, MCP, plugins, hooks, web, skills, delegated sessions and background gateway work.
- The personal shared gateway is **UNSUPPORTED for secured S3** at this checkpoint. A dedicated disposable per-Doctor gateway is a proposed next design, not a launched service.
- The B35 128 MiB inventory cap rejects the user's observed ~289 MB Codex executable; this distinct issue is untouched.
- No credential access, model call, Hospital write, real turn, or production permission has occurred.

## CHECKLIST

- [x] Verify main, Syntagma authority and concurrent repository PRs
- [x] Distinguish native Hermes recovery from Hospital authority
- [x] Add offline DENY fence and fixture regressions
- [ ] Verify exact PR SHA, CI and baseline
- [ ] Independent security review / operator-authorized merge
- [ ] Prove disposable gateway ownership and OS native tool denial
- [ ] Prove per-turn gateway STOP acknowledgment plus independent teardown
- [ ] Gate startup/reconnect/revocation at a trusted pre-launch PX boundary
- [ ] Separately approve any local installation and real-provider probe

## NEXT

After B36-H1 review, build a disposable **offline gateway ownership and recovery lifecycle** contract for a trusted PX supervisor. Before any real model request, validate Room/Patient/Assignment authority, fresh generation, tool grants, authenticated gateway owner, and restart/stop reconciliation. Do **not** silently disable recovery in the operator's personal Hermes gateway or reroute through the legacy native CLI.

## DECISIONS

B36-H1 is an isolated diagnostic policy, **not** execution isolation. No provider registry, personal gateway, `px-agent` live dispatch, credentials or production gates are changed. PR stays draft; production HOLD.

## RECOVERY / HANDOFF

New source `bin/px_s3_b36_hermes_recovery_fence.py`, tests `tests/test-pxd-exec-s3-b36-hermes-recovery-fence.py`, this contract; existing B34/B35 integration workflow updated. Recheck current main and branch ownership before editing. Rollback: close the draft PR or revert B36 commits after a separately authorized merge. No live Hospital Room or Assignment has been registered.
