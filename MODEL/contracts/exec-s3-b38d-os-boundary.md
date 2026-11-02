# PX EXEC-S3 // B38-D Disposable Credential and OS Isolation Evidence

> STATE // DRAFT · OFFLINE CI-ONLY · REVIEW REQUIRED
> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // Hermes Integration Security (external Hospital-compatible; no live Hospital registration)
> ASSIGNMENT // B38-D tests B38-C default mock policy and disposable Linux process boundary
> BASE // main at 381dd60b187e920a743a3d68597cb56e49da2d7f (B38 A/B/C atomic consolidation #113 merged)
> OWNER // B38 workstream; B37-C owner source untouched
> PRODUCTION // HOLD · B24 real provider admission remains DENY

## IMPLEMENTATION

Two bounded changes extend the merged Option A mock-only architecture.

**Mock default policy integration.** B38-B `MockTrustedSender.prepare_mock`
now calls the preexisting B38-C `prepare_fake_plan` with the fixed
`default_fake_manifest`; a synthetic frozen `OfflinePlan` is bound to
the in-memory, identity-only mock ticket. `send_mock` rechecks this plan
against the immutable request/Assignment fixture using B38-C
`recheck_fake_plan`, before synthesizing any fake frames or invoking
B37-C's SQLite atomic transition. A refused policy denies issuance or
dispatch. The sender still has *no* real transport, credentials,
provider, real launch authorization, authenticated Hospital authority,
or native tool runtime.

**Disposable OS-observed test.** New test-only
`tests/test-pxd-exec-s3-b38d-os-boundary.py` reuses the accepted
EXEC-S1 root-owned `/usr/bin/bwrap` loader and its fixed mount/namespace
profile; it does not invent a parallel sandbox or install anything
on the operator's Fedora machine.

The CI runner creates a private temporary tree with an **obviously fake**
credential file and keeps that file descriptor open in the trusted parent.
It launches a disposable child through Bubblewrap with
`--clearenv`, `--unshare-all`, `--die-with-parent`,
`--new-session`, capability dropping, readonly `/usr` and `/patient`,
temporary home and an isolated writable `/scratch`. The child reads
kernel-backed `/proc/self/ns` and `/proc/self/fd` observations and
tests secret path denial, environment stripping, inability to write the
fake Patient directory, scratch write, and direct IPv4 egress denial.
The trusted parent rejects missing/incorrect evidence and verifies that
the fake private file remains unchanged.

If `/usr/bin/bwrap` is missing or the host disallows the requested
namespaces, the job **fails**; no unconfined fallback or passing skip
exists. No actual provider endpoint, token, model request, SDK, or
Hermes process is touched.

### What this does NOT establish

This is **real Linux process sandbox observation** on an ephemeral
CI runner, but it is **not** a real B38 model-provider runtime launch.
The isolated child is only a disposable *untrusted workload probe*;
the mock B38 sender still runs in Python test memory. The probe's
kernel observations are primarily read from inside the isolated child
and checked by the trusted parent. They do not constitute independently
authenticated attestations of every kernel process property.

No actual model authentication, credential-bearing sender isolation,
separate trusted sender identity, broker IPC authentication,
all-network egress certification, live Hospital authority, runtime
persistence-barrier repair, or production admission is demonstrated.
The synthetic fake-auth file is a test sentinel only. A process
with arbitrary execution rights in a trusted client remains a
different threat model from a confined *tool* process.

## HOW TO USE

Open the draft pull request and its GitHub Actions run. The CI workflow
installs Bubblewrap **only on GitHub's disposable Ubuntu runner** and runs:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38d-default-policy.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38d-os-boundary.py --unit
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38d-os-boundary.py --smoke
```

It also executes B37-A/B/C, B38-A/B/C and atomic-default regression
tests. There is no step to run on the operator's workstation.

## VERIFY

- B38-C refusal before mock issuance, after permit issuance and before
  B37-C fake submission; valid non-authorizing policy positive control.
- No fake send or mock ledger transition on invalid or changed B38-C
  policy, except the existing test-only reservation.
- Strict read-only B37-C atomic fence remains the default.
- Exact kernel namespace mount/FD/env/network checks on the ephemeral
  Bubblewrap child, plus parent fixture invariants.
- Missing Bubblewrap, incorrect evidence or failing child exit refuses,
  not skips, the CI job.
- No provider calls or production assertions.

## WATCH OUT FOR

- Installing the CI runner's Bubblewrap is **not** permission to
  install Bubblewrap on the user's Fedora workstation.
- A green CI check only proves this disposable runner's configuration.
  It does not prove equivalent constraints on a Silverblue host.
- The B38-C default manifest describes `executable: NONE`, so its policy
  check is intentionally separate from the real S1 child sandbox smoke.
  Do not claim this is a real model sender running inside a sandbox.
- The mock sender's `_MockPermit` remains an in-memory identity token
  that could be forged by an adversarial Python component in-process.
- Do not merge or activate the old unguarded B38 branches; they were
  closed as superseded when PR #113 landed.
- Nearby H11.5 PR #106 and independent B37-C compatibility PR #112
  remain separate; this PR does not modify or close them.

## CHECKLIST

- [x] Reconstruct merged main and canonical Syntagma rules
- [x] Reuse B38-C policy fixture and existing S1 sandbox
- [x] Isolated GitHub branch and B38 default policy tests
- [x] Disposable Linux Bubblewrap fake-secret evidence tests
- [ ] GitHub CI pass on exact head and generated PR merge tree
- [ ] Independent Nurse/Head Nurse review and operator final acceptance
- [ ] Trusted model-only sender process and authenticated local IPC
- [ ] Real credential isolation certification, separate authorization
- [ ] Production admission (still HOLD)

## NEXT

Independent review should verify B38-C's refusal ordering and
the exact OS boundary evidence from the GitHub runner. Next work
must define the **actual trusted model-only sender process topology**
with an authenticated supervisor interface and no tool-capable imports,
then test it with fake credentials before any real provider login.
B37-C owns atomic recovery and must remain authoritative for
request identity and remote-unknown reconciliation.

## DECISIONS

Continue Option A. Keep B38-D entirely **offline fake-only**,
reusing S1, preserving B37-C, avoiding real model/network use and
not changing the operator's Fedora files. CI passing is technical
evidence, not operator final acceptance or production activation.
