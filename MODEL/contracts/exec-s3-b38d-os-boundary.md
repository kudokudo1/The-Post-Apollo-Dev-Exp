# PX EXEC-S3 // B38-D OS Probe Reconciled with Merged #114

> STATE // DRAFT · OFFLINE SECURITY EVIDENCE · REVIEW REQUIRED  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // Hermes Integration Security (external Hospital-compatible; no live registration)  
> ASSIGNMENT // Preserve stricter merged B38 sender policy; add distinct disposable OS probe from #115  
> BASE // main f1e742de54fa38c30d00a513a7f33a9f9ad21cb7 (PR #114 merged)  
> SOURCE // #115 test-only Bubblewrap probe, copied unchanged  
> PRODUCTION // HOLD · B24 real-provider admission DENY

## IMPLEMENTATION

PR #114's stronger mandatory B38-C mock policy validation is **already
merged into `main`**. It uses `MockTrustedSender(mock_manifest=...)`,
revalidates the mutable manifest at `prepare_mock` and `send_mock`,
and rejects any receipt claiming real credentials, network, OS/Hospital
authority, model/tool calls or production readiness. It uses B37-C's
SQLite atomic request fence. The concurrent original #115 implemented a
narrower policy gate on the **same B38-B sender file**.

This reconciliation **preserves merged #114 exactly**, and moves only
#115's distinct test-only Linux isolation implementation into its own
new base-on-main PR. Nothing in the B38-B/B38-A/B38-C runtime mock sender,
B37-C, production `bin/px-agent`, Hermes, or provider config is
changed by this follow-up.

Three files are added:

1. `tests/test-pxd-exec-s3-b38d-os-boundary.py` is copied byte-for-byte
   from #115's verified test fixture. It reuses the existing EXEC-S1
   fixed root-owned `/usr/bin/bwrap` and disposable namespace/mount
   launcher. No second sandbox policy is invented.
2. `.github/workflows/px-exec-s3-b38d-os-boundary.yml` runs the
   **21 stronger merged #114 policy tests** alongside 180 B37/B38
   regression cases and 4 B38-D unit checks. It then runs the
   disposable OS smoke and prints the exact generated PR merge checkout
   and base/head identities. The workflow **fails** if stronger source
   predicates disappear.
3. This continuity record describes the overlap, exact owner boundaries,
   evidence, and reasons for keeping #115's old conflicting sender code
   out of `main`.

### Linux observation boundary

The smoke creates a private temporary fixture tree containing
an obviously fake provider credential and fake Patient data, and opens
the fake credential in the parent during child launch. The disposable
untrusted child runs through the accepted S1 Bubblewrap profile with
isolated PID/network namespaces, clear environment, restricted mounts,
read-only Patient data, writable scratch, and `close_fds=True`.
The child inspects kernel-derived `/proc/self/ns` and
`/proc/self/fd`, checks inherited canary environment absence,
fake-secret paths hidden, denial of a tested direct IPv4 connection,
and scratch/Patient restrictions. The parent rejects incomplete or
false checks and verifies fixture invariants. If Bubblewrap is unavailable
or namespaces cannot be created, the test fails without fallback.

This is OS-observed confinement of a **disposable probe child**. It is
**not** the actual model-only sender or independent signed attestation,
and it does not prove universal network egress denial, every possible
descriptor hidden, real provider credential isolation, or a malicious
child's inability to lie about observations.

## HOW TO USE

Review the new consolidated PR's GitHub Actions workflow. On the
disposable Ubuntu CI runner only, the workflow installs Bubblewrap
and executes:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38-policy-default-gate.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38d-os-boundary.py --unit
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38d-os-boundary.py --smoke
```

Other B37/B38 regression cases run in the same job. No Fedora
command, installation, service restart, credentials or real provider
network call is required.

## VERIFY

Required verification:

- The three-file diff is **additive only**, with no change to merged
  B38-B policy or B37-C.
- 21/21 strict default policy cases, 180/180 B37/B38 regressions,
  4/4 B38-D static checks and all 19 disposable OS checks pass.
- A green CI reports the **actual** merge checkout and current main base,
  not simply a stacked PR parent.
- No real sender, Hermes tool runtime, API token or production access.
- Source documentation preserves #114 as canonical for policy and
  #115 solely as source of the distinct OS probe.

## WATCH OUT FOR

- Original draft PR #115 still has a **conflicting, weaker copy** of
  B38-B policy code. Do not merge it as-is after #114. Preserve
  source history in a supersession comment and close it **unmerged**
  only after the reconciled OS probe lands successfully.
- OS probe evidence comes from a disposable Ubuntu CI process, not
  the operator's Fedora Silverblue or any real provider process.
- The process-internal model fixture remains untrusted Python policy
  data, not actual Hospital authority or cryptographic identity.
- The test calls one direct IPv4 destination, not every permitted path.
  The FD scan looks for the fake credential path, not all sensitive FD
  classes. A malicious child can misreport its own observations.
- The next real topology milestone requires a separately restricted
  model-only sender process and authenticated supervisor IPC with
  independent OS checks using only fake credentials.

## CHECKLIST

- [x] Operator designated Nurse 2 acceptance and authorized necessary consolidation merges
- [x] Rechecked source ownership; discovered #114 merged during overlap
- [x] Preserved stronger #114 source unchanged
- [x] Copied verified #115 disposable OS probe only
- [x] Added combined CI and durable handoff document
- [ ] Verify exact head and generated merge CI
- [ ] Merge reconciled OS probe after successful verification
- [ ] Supersede/close old conflicting #115 without merging its sender
- [ ] Independently review actual model-only process and IPC
- [ ] Production authorization (HOLD)

## NEXT

Verify this PR on the combined `main` checkout, then merge the
additive probe only if all checks pass. Document #115's supersession
without rewriting or deleting its branch. Continue with an actual
model-only sender process using fake credentials and authenticated,
versioned IPC under separate assignment scope.

## DECISIONS

**Policy owner is merged #114**, which is stronger than #115's parallel
implementation. **OS evidence origin is #115**. This PR combines their
non-overlapping outputs while avoiding policy regression. The operator
authorized necessary safe merges; this does not grant production,
real provider, live Hospital registration or Fedora write authority.
