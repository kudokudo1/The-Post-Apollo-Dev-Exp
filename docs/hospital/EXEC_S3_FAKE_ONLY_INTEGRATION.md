# EXEC-S3 // Offline PX-shaped synthetic integration proof

> STATE // IMPLEMENTED AS TEST-ONLY PROTOTYPE, REVIEW PENDING
> OWNER // PX Doctor Execution Security
> BASE // PX main d1eed3e5b989907f5035e6e8c8e7f8dfe173a254
> CONTRACT // PR #78 at 0912efafc4d09553de539a61c26e3eab2102012d (ACCEPTED AT DESIGN SCOPE, NOT MERGED)
> AUTHORITY // Operator-authorized fake-only development-branch tests. NO PR MERGE.
> REAL CODEX/HERMES, FEDORA HOST CHANGES, LIVE HOSPITAL, PRODUCTION // HOLD

## What this implements

`tests/px_exec_s3_fake.py` is a **test-only simulation of the PX supervisor and
provider turn lifecycle**. It deliberately does not import or modify the live
`bin/px-agent`, real PX Hospital database, installed dispatch path, provider
registry, model credentials or CLI.

- **S3-C1**: the fake model returns a tool request to the trusted supervisor.
  Only PX-shaped supervisor code issues a single-use, nonce-bound, scoped grant
  to the isolated broker. The sandbox is a fixed S1 Bubblewrap program with
  one stdin pipe owned by the supervisor, not by the fake model. Tool requests
  have an exact allowlist and are rejected when stale.
- **S3-C2**: Stage A performs fake authority/Bed and S1/S2 prerequisites
  without outgoing persistence. Stage B actually starts a long-lived
  root-owned /usr/bin/bwrap child, obtains its child PID using `--info-fd`,
  and independently compares mount/network namespace links from **host
  /proc**. It checks the child root's fixture path and absence of the fake
  private fixture. Only after the idle broker returns HELLO and Stage B
  passes does Stage C re-check live fake authority and persist a synthetic
  outgoing message, then invoke the S2 in-process fake-auth service.
  A startup failure precludes message persistence; a later failure is an
  accepted FAILED turn, not silently replayed.
- **S3-C3**: fake authority includes a version/generation and pause flag.
  The supervisor revalidates them before each grant and after each tool
  result. `revoke` invalidates outstanding grants and actively stops the
  broker process group; its S1 `--die-with-parent` keeps the child from
  surviving the launcher. Partial results cannot mark a completed Doctor
  turn after revocation. A deliberately sleeping fake tool is killed by the
  revocation smoke before it writes.

The synthetic "Hospital" is an in-memory record with an RLock. No real
Hospital sessions or Chart/Report records are read or written.

## How to test on disposable CI (NO live machine changes)

```sh
python3 -B tests/test-pxd-exec-s3-fake-integration.py --unit
python3 -B tests/test-pxd-exec-s3-fake-integration.py --smoke
```

The second command requires a trusted root-owned /usr/bin/bwrap and a
machine permitting rootless user/network/mount namespaces. No fallback.
The PR CI workflow installs Bubblewrap in its disposable Ubuntu runner,
not on the user's Fedora machine.

## Review caveats (not a production certification)

1. The fake client is in-process and not Codex/Hermes. There is no
   authenticated model transport, no real provider disable-tool API and no
   protection against a full privileged provider CLI's own native actions.
2. The isolated broker uses a fixed, source-controlled program and controlled
   pipe. It does not implement a production-grade authenticated broker socket
   or a general open-ended tool API.
3. The host observes namespaces and fake mounts from /proc at readiness, but
   this proof does not certify all namespace/FD/mount/time-of-check races or
   runtime integrity for arbitrary hostile executables.
4. Fake revocation prevents subsequent completion, but cannot undo writes or
   effects that already occurred before revocation. Complex cross-process
   authorization transactions and writable real Beds remain future work.
5. The fake in-memory outgoing/event list does not test actual persistent
   Hospital message transaction guarantees or original Chart continuity.
6. This branch does NOT add an integration hook into the actual `bin/px-agent`.
   S3 runtime adoption, full launch/resume enforcement and authenticated model
   execution require separately reviewed implementation and operator authority.

## Scope and reviewer handoff

This prototype reuses exact merged S1/S2 harnesses unmodified. Only new test
files, workflow and this note are in the proposed branch. Nurse 2 should
verify pre-append refusal, real readiness from OS facts, exclusive mediation,
grant replay and authority race negatives, active process termination,
source-only fake providers, and the explicit limitations above.

**No merge permission. S3 production activation HOLD.**
