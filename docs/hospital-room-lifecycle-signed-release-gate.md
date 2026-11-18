# 🏥 Hospital Room lifecycle // PX v12 signed authorization and release gate

PATIENT // The-Post-Apollo-Dev-Exp
ROOM // Hospital / Source-Owned Room Trash++ Integration
STAFF // External Hospital-compatible DOC; live registration not verified
ASSIGNMENT // Complete Batch 1 signed Room Trash/Restore source gate and coordinate native activation
STATUS // IMPLEMENTED SOURCE GATE, **PRODUCTION HOLD**

## IMPLEMENTATION

PX [PR #130] is stacked on Room names [PR #121]. App [PR #2045]
is its paired Hospital/Trash++ consumer. This is one coordinated feature,
not a succession of standalone rehearsal PRs.

- The original Room row and its linked evidence are retained. SQL v12 holds
  all selected writer relations while Room is TRASHED.
- Plain \`px hospital room-lifecycle-trash\` and \`...-restore\` no longer
  accept merely \`--confirm-room-id\`; they require a
  \`--signed-authorization-file\`. A CLI-selected public key, unsigned boolean,
  optional bypass flag or environment trust override is not supported.
- The externally produced Ed25519 grant uses a fixed domain
  \`post-apollo.hospital.room-lifecycle-grant.v1\` and pinned audience
  \`px-hospital-room-lifecycle-v12\`.
- Signed fields: operation (TRASH/RESTORE), exact Room/Patient/repository,
  graph SHA-256, revision, operator ID, independent seat and host IDs, issuer's
  retention approval, one-use 256-bit nonce, approval ID, issue/expiry time.
  The maximum lifetime is 60 seconds.
- Production verification reads the **root-owned** 32-byte Ed25519 public key
  at \`/etc/post-apollo/hospital/room-lifecycle-issuer.pub\`, refuses symlinks
  and writable/trust-weak key path components, and cross-checks the signed
  host witness against \`/etc/machine-id\`. Neither path is created by PX.
- \`room_lifecycle_authorizations\` consumes nonce and approval ID exactly
  once in the **same BEGIN IMMEDIATE transaction** as Room state and receipt.
  SQL errors roll the entire operation back.
- API \`review\` **never** returns an authenticated operator grant simply
  because a Room is eligible to trash. The signed transition receipt reports
  grant signature verification, but continues to mark independent
  \`operatorAuthenticated:false\` and \`requiresOwnerReview:true\`.
- Permanent Burn is **not** included in the source or UI.

## VERIFY // AUTOMATED

The PX workflow tests a real disposable v11→v12 schema upgrade, old unsigned
CLI refusal, forged/wrong-domain/wrong-key/expired/retention-denied grants,
exact Room bindings, old writer denial, transaction+approval rollback,
nonce/approval replay, preserved messages, Restore and Bin inventory.

The app workflow checks the PX PR head as a separate checkout and exercises
Trash → Bin → Restore on disposable SQLite via a generated Ed25519 **fixture**
key. CI fixture signatures are not operator approvals or installable keys.

## WATCH OUT FOR // BLOCKERS BEFORE ANY MERGE OR NATIVE ACTIVATION

1. **No trusted native issuer exists yet for Hospital Room scope.** Existing
   Connections C5a–C5d broker is TASKS-specific, much of it CI-only and
   deny-only. Do **not** reuse its TASKS permission as a Hospital grant.
   Connections/Identity source owner must supply an installed, separately
   authenticated signer with Linux caller/process and active-seat evidence,
   explicit per-Room operator approval, trusted retention/hold decision,
   correct host binding and protected signing-key custody.
2. **Current PX database is writable by its desktop user.** The exact writer inventory, concurrent branch collisions, and a disposable same-UID direct-SQL bypass witness are preserved in [hospital-room-protected-writer-audit-v1.md](./hospital-room-protected-writer-audit-v1.md). `tests/test-px-hospital-unprotected-writer-witness.py` passing is explicit **negative security evidence** and is NOT release acceptance. Signed CLI
   checks do not stop that same UID from changing SQLite with another
   program. Before security acceptance, PX owner must decide the protected
   storage/service-writer boundary, or clearly limit claims to accident
   prevention rather than malicious peer security. All old PX writers and
   parallel Bed/Session/Assignment branches require reconciliation.
3. **Root key and install provenance are unverified.** No one should copy a
   CI fixture key into \`/etc\` or mark \`operatorAuthenticated:true\` in QML.
4. **Version coordination is required:** v10 → #121 v11 → #130 v12.
   Existing older PX binaries reject newer schemas. All Room-related
   services and local runtime must upgrade together after a verified backup.
5. **Backup and power-loss acceptance are still required.** The Room remains
   in the same SQLite file; soft Trash is not a backup. A native owner
   must quiesce writers, create a verified recoverable SQLite backup with
   WAL-aware consistency, prove restoration on a separate disposable DB,
   and inventory Room/Session/Assignment/Chart row preservation before and
   after simulated recovery.
6. **App contract is blocked by design:** HospitalRoomLifecycleService
   does not yet have a trusted native grant transport. It keeps
   \`permissionReady\` false. The PX CLI expects an independently signed
   file; an untrusted QML-selected path must never become its own grant.
7. Source-owner review, independent security review and **operator native
   acceptance** are required. Passing CI is not operator final acceptance.

## HOW TO USE // AFTER APPROVED INSTALLATION, NOT NOW

Target UI:
**Hospital → Surgery → SHOW WORKERS → Room → Trash++ Review → TRASH**  
**Trash++ → TRASH → HOSP → select Room → RESTORE**

Before exposing these actions, trusted native issuer returns a request-bound,
one-use signed approval and PX consumes it atomically. There is no safe
production command to issue such an approval in the current repository.
No local steps are offered until the actual host and documented install
plan pass independent review.

## PX WRITER SECURITY CHECKPOINT // 2026-11-18

The verified user-relative `bin/px-hospital-store` connection and direct SQL bypass are an open production blocker. The separate-UID Linux DAC fixture (`tests/test-px-hospital-protected-dac-fixture.py`) now proves, on a **disposable real PX v12 DB plus backup**, that an unprivileged desktop-UID analogue cannot directly open or mutate data stored under another UID's 0700 directory, while the owning process can use PX normally. The test does **not** install or implement the production writer service, caller authentication, signed-issuer transport, SELinux rules or privileged backup custody. A recommended candidate is a dedicated, non-desktop-UID native database service, OS-private WAL/SHM/backup storage, allowlisted RPC and authenticated peer credentials. This architecture requires service identity/SELinux/install and all-writer migration review before it can be claimed implemented. The existing signed source-side transaction alone cannot enforce a malicious same-UID boundary.

## NEXT // OWNER HANDOFF / DECISIONS

- PX owner: review source gate, DB write ownership and v11/v12 migration.
- Connections/Identity owner: provide Hospital-specific native signer and
  per-operation human consent, not TASKS consent.
- Trash++ owner: verify Hospital Bin entry and Restore are separate from
  GIO/managed-copy deletion and Burn.
- Independent security reviewer: verify exact heads after owner fixes.
- Operator: approve merge, local migration/install, and native acceptance
  separately. Permanent Burn is a subsequent distinct authorization.

No real user Room, local file, provider Session or running service was changed
as part of this source implementation.
