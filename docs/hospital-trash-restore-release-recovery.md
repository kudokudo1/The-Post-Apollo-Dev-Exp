# 🏥 Hospital Trash and Restore // Safe installation and recovery contract

**Status:** source preparation only · not a completed installer, not a runtime activation
**Patient:** The-Post-Apollo-Dev-Exp
**Assignment:** Hospital Trash and Restore, coordinated with the application and Connections system
**Application:** The-Post-Apollo-Project PR #2069
**Database and security:** PX #121 → #130 → #133
**Operator:** final authority for merge, machine changes, native installation, and acceptance

## IMPLEMENTATION // what exists

The existing Hospital database owns its actual SQLite rows. The code now
supports recoverable **Room Trash/Restore**, preserves linked history, and
requires a signed, short-lived, one-use native approval and root-managed
Room retention/legal-hold decision. The Hospital UI asks the protected
service for that approval and uses separate protected read-only Room/bin
requests. **Hospital Burn does not exist.**

The new read-only release-preflight source
\`bin/px_hospital_release_preflight.py\` inspects an independently supplied
SQLite connection. It checks the schema version, SQLite quick check, foreign
keys, required Hospital tables, record counts, open Sessions, and active
Assignments. It **cannot** authorize a migration or prove that outside
processes are stopped. Its output deliberately keeps
\`externalWritersStopped:false\`,
\`verifiedRecoverableBackup:false\`, and
\`approvedToMigrate:false\`.

The disposable release rehearsal
\`tests/test-px-hospital-release-cutover-v1.py\` performs a complete
v10 → v11 → v12 source migration against the *real PX source* using a
separate temporary SQLite database. A WAL-only write is captured through
SQLite's online backup API. It verifies all original Patient, Room,
Doctor, Session, event, message, checkpoint, report, Chart, suggestion
and Assignment field values via a private in-memory fingerprint.
It checks schema integrity, foreign keys, Room lifecycle triggers,
idempotence, a v11 ADD COLUMN crash state, v10 recovery from backup,
future-version refusal, and active-Session/Assignment holds.

**This code can only run as a disposable GitHub Actions test. It
refuses execution outside the CI runner. It does not reference or open
the user's live Hospital database.**

## HOW TO USE // after a separately approved native release plan

Target controls remain:

Hospital → Surgery → Show Workers → Room → Trash++ Review →
Request native approval → Confirm exact Room

Trash++ → Trash → HOSP → select Room → Restore

Before approved installation, the correct UI is
**HOSPITAL BACKEND NOT READY**. It must not display an empty Bin or
enable real Room mutations just because the source tests are green.

## VERIFY // required release sequence, in this order

1. **Identify the live system.** Record the real installed PX executable
   revision, direct and indirect Hospital writers, application source
   revision, SQLite schema, path, owner UID, SELinux contexts,
   current Rooms, Sessions and Assignments. Do not infer these from GitHub
   or this external browser chat.
2. **Freeze intake and quiesce Hospital work.** Explicitly suspend new
   Session/Assignment changes, stop ALL existing source SQLite writers
   and refuse new old-binary launches. Merely seeing zero active
   Sessions in SQL is not a process fence.
3. **Take a protected and recoverable source backup.** Use SQLite's
   online backup API as the source owner for the live WAL database, not
   \`cp hospital.db\` while a WAL is active. Keep the backup owner-only,
   encrypted where required, off the desktop writable path and with an
   operator-approved retention schedule. Do not print private messages
   or reports into logs.
4. **Prove rollback before upgrade.** Restore the online backup to a
   separate test file. Check \`PRAGMA integrity_check\`,
   \`foreign_key_check\`, schema, all expected Room IDs and historical
   graph counts/hashes. Store a tested backup locator and known-good
   executable revision. No live rename/move until this succeeds.
5. **Stage migration against a separate protected copy.** The exact
   approved PX source must advance schema 10 → 11 (Room names) → 12
   (Room lifecycle). Compare complete historical row witnesses, not
   only \`rooms\` counts. An unexpected version, missing table, FK
   error, interrupted migration, mismatch or unreviewed pending writer
   change is a HOLD, not an opportunity to run \`init\` on live data.
6. **Install the service security boundary under separate authority.**
   Review the three distinct non-root identities (desktop client, PX
   runtime, protected Hospital database writer). Install root-owned
   configuration, exact source/executable hashes, Polkit, active-seat
   checks, the issuer key, verifier public key, signed Room-specific
   retention/legal-hold policy with anti-rollback requirements, restricted
   socket ACL, SELinux labels and systemd activation. The root-created
   signed-approval socket is owned by the pinned non-root database
   writer account, with root-controlled parent directories.
7. **Switch ALL Hospital source writers to the protected owner.**
   This includes every installed Session, Assignment, Doctor, Bed and
   Chart operation. Do not give desktop processes write access to the
   protected DB as a compatibility workaround. Do not retain a second,
   mutable desktop Hospital database as a silent fallback. Any unsupported
   command or uncertain writer provenance must refuse.
8. **Prove negative security paths first.** Test uninstalled backend,
   unauthorized caller, inactive/locked seat, missing/expired retention
   approval, protected Room with active work, replayed signed approval,
   changed Room revision, wrong socket/process UID, wrong key and
   stopped protected service. Each must refuse with no Room mutation.
9. **Prove the actual positive workflow only on disposable native data
   first.** Hospital UI → independently authenticated consent → protected
   Room TRASH → Hospital Bin displays that exact Room → RESTORE. Verify
   original Session, Assignment, Message, Report and Chart row contents
   remain exactly unchanged, receipts record both transitions, and
   no Burn path is exposed.
10. **Independent security and operator acceptance.** Only after the
    owner and independent reviewer accept source, install provenance,
    backup/recovery and native evidence should the operator separately
    approve a real-machine cutover, merge order, and final release.

## WATCH OUT FOR // rollback rules

- **Before live activation:** If any install/migration step fails, keep
  source writers fenced, stop the new protected services and use the
  independently verified backup to restore the *pre-upgrade state*.
  Re-enable the exact old compatible binaries only after checking the
  restored schema and process admission. Never point old binaries at a
  newer schema.
- **After live writes:** A blind v10 rollback will DISCARD everything
  written after the backup. Do not overwrite a live v12 DB with an old
  backup once new Sessions, receipts, approvals, Messages or Room
  changes exist. Halt writes, preserve both databases and logs,
  reconcile new records, and require a separate explicit recovery plan
  and operator approval.
- **If the signer and writer disagree:** Leave Trash/Restore locked.
  No signed grant may be returned through QML and no direct SQLite or
  unsigned PX fallback is permitted.
- **If backup provenance cannot be established:** Do not migrate,
  remove or replace the existing database. A fresh empty Hospital DB
  is not a recovery.
- **No Burn or Burn All for Hospital originals.** Soft Trash/Restore
  preserves the existing Room graph; permanent deletion requires a
  future, separately approved system.

## CHECKLIST // current source vs real host

- [x] Merged Connections signer source and PX signed Room lifecycle test together
- [x] Source-only protected Room/bin read client in application draft
- [x] Source-only protected Trash/Restore approval transaction in PX draft
- [x] CI backup of WAL-only history and recovery to pre-migration schema
- [x] CI interrupted v11 migration, idempotence and downgrade refusal
- [x] CI verification that active Session/Assignment and missing host evidence cannot approve cutover
- [ ] Approved complete installed-writer inventory, native service UIDs and root config
- [ ] Reviewed secure host release/SELinux/socket unit and key provenance
- [ ] Verified independent Room retention/legal-hold authority and revocation floor
- [ ] Operator-approved quiescence and WAL-consistent real backup/restore evidence
- [ ] Complete all-writer native cutover (including other open Hospital branch writers)
- [ ] Independent native security review and operator end-to-end acceptance

## NEXT // consolidated remaining package

The next development package is **native release admission**: a
reviewable installed-host inventory and immutable release manifest,
root-controlled service/socket/SELinux policy, stop-all-old-writers
evidence, migration recovery receipt, and native acceptance tests.
None of those may be declared completed from this CI-only rehearsal.

## DECISIONS

Remain on draft PX #133 and its application counterpart #2069.
PX #130 and schema #121 remain prerequisites; do not silently merge
parallel Bed/Session/Doctor work. All changes here are GitHub source
and disposable CI. No local machine or live Hospital data is modified,
and no production release is authorized by this document.


## 2026-11-19 // Protected startup and old-writer inspection package

This is an extension of the **same Hospital Trash and Restore PR #133**.

### Source files added

- \`bin/px_hospital_native_release_audit.py\` is a root-only, **read-only**
  Linux process/DB descriptor inventory. It reads the existing fixed
  root-controlled Hospital writer configuration, checks distinct writer /
  runtime / desktop UIDs, inventories open \`hospital.db\`, \`hospital.db-wal\`
  and \`hospital.db-shm\` file descriptors, reads kernel process UIDs and
  access flags, and identifies database handles outside the protected
  source path or owned by the wrong UID. Unreadable or changing /proc
  observations cause a HOLD; the program never scans a user-supplied path.
  It does not read patient records or print private paths/PIDs.
- \`tests/test-px-hospital-native-release-audit.py\` checks the actual
  source parser still has **21 allowlisted writes and 19 allowlisted
  reads**. The disposable Linux /proc fixture tests approved and
  unapproved source file descriptors, direct desktop-owned Hospital DB
  handles, and fail-closed partial process evidence.
- \`packaging/hospital-trash-restore/*.in\` defines **source-only**
  systemd service/socket and tmpfiles templates for protected Hospital
  database writer, separate signed Room approval service, root-owned
  Connections issuer and root-owned IPC directories. They are deliberately
  **not rendered, installed, enabled, or complete without the host
  identity/security review**; no \`WantedBy\` directive is provided and
  all machine-specific owner/service identities are unresolved.
- \`tests/test-px-hospital-native-unit-contract.py\` checks the actual
  merged Connections issuer and pinned Hospital UI executable source
  against the templates' exact socket paths, non-root writer identities,
  root-created/writer-owned approval socket, 0600/0660 modes and inert
  startup settings. The template test does **not** install systemd units.
- All tests run with temporary files or source parsing in GitHub CI,
  not on the operator's desktop.

### Unresolved install decisions, not hidden defaults

1. The operator and installer must identify the actual dedicated Hospital
   database writer identity and the approved desktop/runtime UIDs. No
   hard-coded local UID, new account or group is created by this PR.
2. A reviewable RPM/immutable-OS or equivalent trusted installation path
   must provision \`/usr/libexec/post-apollo/hospital\`; on Fedora
   Silverblue, casually writing into the immutable \`/usr\` tree is not
   an approved rollout procedure.
3. The writer's existing SOCK_STREAM socket defaults to **0600**. A
   separately reviewed, narrow access-control-list policy must grant only
   the pinned desktop read client and protected PX runtime access. The
   templates intentionally do not widen it or disguise this missing step.
4. The root-created signed \`px-writer.sock\` must be owned by the
   dedicated non-root database writer, matching both PX and Universal
   Connections source. The issuer's own socket stays root-owned and is
   limited to an explicitly approved operator group.
5. Legacy Hospital commands must be inventoried and fenced at their
   *launch sources*, not just in an instantaneous process list. A clean
   read-only /proc audit **never** sets \`releaseApproved:true\` or
   \`externalWritersStopped:true\`. Startup unit source cannot prove that
   unrelated per-user scripts, old binary versions, or future commands
   will not open the old database again.
6. SELinux labels, Polkit active-seat agent, key/certificate provenance,
   root retention/legal-hold decisions, WAL backup restore receipt, all
   open Bed/Session/Doctor writer compatibility and operator native
   acceptance are still separate required gates.
7. **No live Hospital Burn.** Permanent deletion remains outside this
   Room Trash/Restore source integration.

### Release and rollback decision

No unit should be enabled merely because its template parses or the
process inventory is quiet. If any identity, ACL, source hash, root policy,
schema, recovery witness, or old-writer fence is missing, the native
release stays **HOSPITAL BACKEND NOT READY**. A real cutover needs an
independently verified backup and explicit operator approval.


## 2026-11-19 // Exact remaining Hospital writer ownership inventory

I inspected the real PX source diffs for the independently owned open
Hospital branches. These are **not** silently merged or granted new
protected database privileges:

| Existing Hospital work | New source command / request | Release decision |
|---|---|---|
| PX [#123](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/123), Session admission | \`session-attach-atomic\` | Must be reconciled with the protected PX runtime command validator |
| PX [#125](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/125), Doctor succession | \`session-succeed-atomic\` | Must be reconciled with the protected PX runtime command validator |
| PX [#127](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/127), initial Bed | \`room-bed-claim-atomic\` | Explicitly synthetic; cannot be promoted to native permissions |
| PX [#128](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/128), signed initial Bed | \`room-bed-claim-signed-atomic\` | Separate signing and Room/Bed review required |
| PX [#129](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/129), native Bed gateway | Native signed Bed request service, no new store parser command in this PR | Distinct staff/Bed authority; cannot reuse Room Trash consent |

The protected Hospital writer in PX #130 currently admits exactly
**21 existing write commands + 19 read commands**. The four commands above
are **not** part of that allowlist. Its source coverage check rejects
an unrecognized future command rather than granting it access. This
prevents accidental privilege expansion, but also means installing
the protected database before coordinating those branches could strand
pending Session/Doctor/Bed workflows.

**Next release gate:** preserve those workers' individual ownership and
tests, reconcile their complete operations with the protected service's
actual Room, Assignment, Session, Bed and process authority, then prove
that every executable admitted after cutover uses the same private
Hospital database. Merely whitelisting these names or adding a generic
raw SQL transport is NOT an acceptable fix. The operator need not
coordinate these other chats: the Hospital integration owner must do
that work through PR review and exact source evidence.


## 2026-11-19 // Package 1 source compatibility checkpoint

**Result:** independent-source compatibility audit PASS at Hospital draft
commit `c7ed0e59` (3/3 GitHub workflows). **Protected compatibility and
installation remain HOLD.** The test does NOT execute or promote any
independently owned writer or unmerged branch.

The new CI-only file
`tests/test-px-hospital-pending-writer-compatibility.py` checks the
exact Git commit revisions, command names, actual function entrypoints,
transaction and confirmation witnesses, and hard denial by the current
21-write/19-read protected source router:

| Branch / owner draft | Exact revision | New command | Next permission decision |
|---|---|---|---|
| PX #123 Session attachment | `4c3f0c97` | `session-attach-atomic` | Require protected runtime and precise Room/Assignment/Bed/Doctor/Provider caller authority |
| PX #125 Doctor succession | `4e0fe43c` | `session-succeed-atomic` | Require verified terminal prior Session, recorded handoff, successor staffing and assignment authority |
| PX #127 initial Bed | `81f626d9` | `room-bed-claim-atomic` | Keep synthetic fixture-only; never elevate an ordinary `--confirm` argument |
| PX #128 signed Bed | `a76a7b07` | `room-bed-claim-signed-atomic` | Requires separate host-bound intent signature and trusted native Bed gateway; never tunnel `--signed-intent-file` through generic store-command |
| PX #129 native Bed gateway | `0dd14de0` | Adds gateway, not another store parser command | Verify peer/executable/seat/one-use authority and source compatibility with #128 |

`bin/px_hospital_native_release_audit.py` now publishes explicit
`allWriterCompatibilityVerified:false` and the four unreconciled
command names, even when no old database descriptor is observed.
This is intentionally never an authorization token or release approval.

**Next integration work, not yet completed:** obtain separately owned
writer-contract acceptance for the Session, Doctor and Bed actions; add
narrow source-owned protected RPC handling with their original atomic
validation intact and per-command runtime/native identity checks;
reconcile schema v12 migration against their exact existing branches;
then run complete positive and negative disposable tests. Do not
whitelist the four names by themselves. Preserve independent branch
ownership, no direct desktop SQLite fallback, no application changes,
no live database migration, and no Hospital Burn.

**Verification reference:** GitHub Actions commit `c7ed0e59a19dcead3b827e66a4e27b915a0f11da`,
workflow `Hospital / Universal Connections Signed Trash Restore` +
`PX / HOSPITAL STORE` + `Meta Apollo Grammar`: three SUCCESS.



## 2026-11-19 // Package 1 original owner functions against live-format v12 fixture

**Cross-source compatibility test: PASS, source-only.**
`tests/test-px-hospital-cross-owner-v12-compatibility.py` runs under GitHub
Actions only with one throwaway **actual PX v12 database** created using
the Hospital owner `migrate()` function. The test does not import the owner
code into the installed protected service or grant it runtime permissions.

The CI workflow checks out independent branches at pinned exact SHAs,
and the test runs their real function objects against the v12 tables and
actual Room lifecycle triggers:

- `#123` atomic Session attachment: ACTIVE Room/Doctor/Assignment/Bed
  snapshot, atomic Session insert, idempotent replay and duplicate denial.
- `#125` atomic Doctor succession: terminal prior Session and handoff,
  old history retained, simulated insertion failure rolls back the Room
  staffing change, single succession event and idempotence.
- `#127/#128` Bed registration: original synthetic-only plain Bed claim
  and Ed25519 signed Bed intent, on v12, only with the owner-defined
  ephemeral CI path/test gate. Production path refusal remains tested.
- v12 lifecycle's actual frozen Room triggers refuse an attempted Bed
  change to a trashed Room. SQLite integrity and foreign key checks pass.

The cross-version check supplements the earlier exact source inventory.
The existing protected service still exposes only its 21 reviewed writes
and 19 reads; the four newer commands remain denied and
`allWriterCompatibilityVerified:false` remains in the native release
audit. Passing this test DOES NOT demonstrate trusted caller/active-seat
authorization, migration of native binaries, or safe release enrollment.

**Exact verified source checkpoint:** `b9a26845ce2279f5c52aad14f5efec072b46c44f`;
Hospital signed integration, PX Hospital Store, and Meta Apollo Grammar
workflows all passed.

**Next required work:** separate review of each command's runtime/native
authority; rebase/reconcile source owners' changes without copying
synthetic-only Bed authority into production; perform a complete secured
all-writer cutover and native backup/restore acceptance. Until then,
HOSPITAL BACKEND NOT READY is the correct state. No Hospital Burn.


## 2026-11-19 // Package 1 Session + Doctor source adapter staged

**Status:** source milestone PASS · native permissions and release still HOLD.

`bin/px_hospital_staffing_admission.py` stages the **exact atomic
function bodies** from independently owned PX [#123](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/123)
(`session_attach_atomic`, pinned `4c3f0c97`) and
PX [#125](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/125)
(`session_succeed_atomic`, pinned `4e0fe43c`).
Only their signatures inject the existing v12 `session_record` and
`room_record` readers; the original source code bodies, transaction
checks and rollback remain unchanged. This does not move either source
owner's branch or replace their independent PR.

The existing `tests/test-px-hospital-cross-owner-v12-compatibility.py`
now verifies **full source parity** against both pinned owner files and
executes the staged adapter on the disposable v12 Room/Session/Assignment
database. It checks idempotence, conflicting Session denial, rollback of
a partially updated Doctor Room, historical messages/HANDOFF preservation,
and the existing frozen/trashed Room and signed Bed refusals.
Exact head `0e848d0f349a240c65e913743f3b3b87f453c9c9`:
Hospital/Universal Connections, PX Hospital Store, Meta Apollo Grammar
**3/3 SUCCESS**.

**Native security boundary:** `dispatch_native_staffing` unconditionally
raises `NATIVE_SESSION_DOCTOR_AUTHORITY_NOT_INSTALLED`, including if
an untrusted caller supplies `authorized=True`. The module is NOT
imported by the protected writer, does not add any CLI subcommand or
socket operation and cannot be used to bypass the existing
21-write/19-read router. Tests exercise internal functions only with
temporary CI storage. Plain `--confirm` does not authenticate an
operator, release a live Doctor, or establish Bed owner authority.

**Next required integration steps:**
1. Reconcile the two independently owned commands with an explicit
   native Session/Doctor consent/caller identity and one-use authority
   contract. Review exact Room/Assignment/Doctor/Provider/Session/Bed,
   operator seat and run provenance, and check revocation in the same
   source transaction; do not let a runtime UID or CLI flag alone
   authorize worker replacement.
2. Only after that review, expose separately typed and bounded native
   operations on the fixed protected database owner. Keep unknown
   commands, raw SQL, cross-patient authority and signed Bed file
   injection denied. Re-run original owner tests and hostile
   runtime/socket/rollback cases.
3. Reconcile existing PX #123/#125 owner release order, then native
   PX agent front doors and all old direct SQLite writers at one
   approved cutover. Bed #127/#128/#129 remains synthetic/independent.
4. Complete the existing release manifest, key/SELinux/Polkit review,
   actual old-writer process fence, real backup/restore and
   supervised operator-accepted installation. **No Hospital Burn**.

This is an **implementation checkpoint**, not a certification,
merge decision, native installation, or final operator acceptance.


## 2026-11-19 // Package 1 independent signed Session/Doctor permission boundary

**Source-only checkpoint, no installed/native permission granted.** The
existing #133 protected Room Trash/Restore integration remains separate
from Session attachment and Doctor succession. The new staff actions do
NOT reuse the Room Trash/Restore issuer key, signing domain, retention
permission, operator decision, or socket command.

### IMPLEMENTATION

- `bin/px_hospital_staffing_grants.py` defines two exact native staff
  intent scopes, `SESSION_ATTACH` and `DOCTOR_SUCCEED`, in their own
  Ed25519 domain. Signed bytes bind the exact Room, Patient, repository,
  Git Bed, branch, ACTIVE Assignment, old/new Session and Doctor/Provider,
  operation, source Room revision and complete v12 graph digest,
  operator/seat/host, distinct approval ID, 32-byte nonce, and
  <=30-second lifetime. No client-selected key, raw SQL, private signer,
  QML approval, or test-key CLI exists.
- The *future* trusted verifier path is pinned to a separate root-owned
  `/etc/post-apollo/hospital/staffing-issuer.pub`. The root-pinned
  entrypoint separately checks machine binding. Verification with an
  arbitrary fixture public key is intentionally **not** native authority;
  a source-level `native_verified` witness is set only after the trusted
  entrypoint checks the root key and installed machine ID.
- `VerifiedStaffingGrant.consume()` requires an open SQLite transaction
  and independently rechecks the source Room state, current Room graph,
  Patient, linked ACTIVE Assignment, Doctor and Room/Bed identity.
  It records a unique approval/nonce/digest under the SAME write
  transaction that must include the original staffing change. A
  changed signature/body, stale Room, expired grant, replay or missing
  ledger refuses, without issuing a positive authorization.
- The per-action ledger schema is deliberately **NOT** installed by the
  current v12 migration and is never auto-created by an untrusted
  request. The schema and source runtime wiring require a separately
  reviewed versioned migration.
- `bin/px_hospital_staffing_admission.py` now contains narrow optional
  native-grant consumption hooks immediately after each original atomic
  `BEGIN IMMEDIATE`, with exact Session/Doctor command fields checked
  against the signed scope. Its owner-function source parity check
  strips ONLY these two explicitly reviewed hook insertions and
  the injected reader arguments before comparing against the exact
  #123/#125 original source bodies.
- **Release surface remains CLOSED:** `dispatch_native_staffing()`
  unconditionally refuses; `px_hospital_room_writer.py` never
  imports staffing grant handlers; the protected bridge still supports
  21 existing writes and 19 reads but **not** either new staffing
  command; direct `--confirm` has no native authority. Experimental
  Bed #127/#128/#129 remains unexposed and independently owned.

### VERIFY // Disposable CI only

- `tests/test-px-hospital-staffing-grants-v1.py` verifies real
  Ed25519 signatures, separate signing domains, exact field and ID
  validation, wrong signer/tamper/expiry, atomic nonce/replay,
  stale graph, mutation after verification, uninstalled ledger refusal,
  and preservation of historical records.
- `tests/test-px-hospital-staffing-atomic-consent.py` tests isolated
  native-verifier simulation through test-interpreter-only `unittest.mock`
  patches: an unattested fixture signature is refused as native;
  matched staff grants admit original staged Session and Doctor
  functions; a forced SQLite Session INSERT failure rolls back both the
  Session and the consumed approval, and retry of that specific signed
  grant is successful after the failure is removed. Earlier
  HANDOFF, Session history and messages remain intact.
- `tests/test-px-hospital-cross-owner-v12-compatibility.py` still
  verifies pinned original upstream function parity, including
  precisely the new optional native authorization hooks.
- GitHub workflow `Hospital / Universal Connections Signed Trash Restore`
  runs the new tests with ephemeral keys and disposable v12 database.
  This source-level witness is not a real signed operator grant or native
  deployed Fedora / Silverblue test.

### WATCH OUT FOR // Missing native admission, not hidden as done

1. No installed staffing-specific signer, independently authenticated
   executable/start identity, active human seat/Polkit review or
   operator-approved per-action native consent exists.
2. No production staffing-ledger migration, root key provision,
   key rotation/revocation/anti-rollback protocol or signed staff
   issuer enrollment has been accepted.
3. No protected socket endpoint for these two new commands is enabled.
   The old CLI and native PX agent front doors are not switched over.
   Production remains **HOSPITAL BACKEND NOT READY** for this lane.
4. PX #123 and #125 remain independently owned, open drafts and must
   preserve their merge/source order. Bed work remains separate.
5. No actual Hospital database backup/migration/old-writer fence or
   native acceptance has been performed, and Hospital Burn remains
   explicitly unsupported.

### NEXT

Review the root-pinned staffing issuer and exact operator/seat consent
contract with the Connections and Hospital owners. Reconcile the
transaction-bound staff grant with the separately owned original
functions and versioned ledger migration, then provide a narrowly typed
native protected service endpoint under verified source identity.
Only then proceed to old-writer admission fencing, backup/recovery,
independent security review and operator-authorized native release.

### DECISIONS

All changes stay inside existing draft PX #133. No source-owner branch
edit, merge, live local-machine write, production privilege or
Hospital Burn is authorized by the passing tests.


## 2026-11-19 // Package 1 typed staffing request + v13 ledger candidate

**Engineering status:** disposable v12->v13 migration rehearsal PASS;
source-only typed transport parser PASS; **native service remains HOLD**.

### IMPLEMENTATION

- bin/px_hospital_staffing_transport.py defines an independent,
  canonical, bounded request contract:
  postapollo.hospital.native-staffing-request.v1, with exact
  prepare/commit kinds, Session attach or Doctor succession only,
  Room/Patient/Assignment/Bed/Session/Doctor intent fields,
  a separately encoded 32-byte request nonce, and bounded
  signed-envelope bytes plus a writer-instance ID on COMMIT.
  Unrecognized action, Bed claim, Room TRASH/RESTORE, unknown
  fields, request-selected SQL/CLI commands, malformed/noncanonical
  Base64, duplicate JSON fields, nonfinite numbers, mixed Room IDs
  and extra permissions fail parsing.
- dispatch_native_request() **always refuses**
  NATIVE_STAFFING_SERVICE_NOT_INSTALLED; there is no socket listener,
  process/seat authentication, native issuer or host-invocable write.
  parse_request() is untrusted-data validation, NOT authorization.
  A validly encoded envelope does not prove a trusted signature.
  The future installed host must verify issuer provenance, exact
  operator consent and active seat, bind COMMIT to a protected
  PREPARE nonce and source snapshot, and invoke only the reviewed
  original atomic Session/Doctor operation on the protected DB owner.
- packaging/hospital-trash-restore/candidate-staffing-ledger-v13.sql
  proposes an additive source-ledger migration from PX 12 to
  **candidate** version 13. It uses BEGIN IMMEDIATE, rejects a
  non-v12 starting schema, creates hospital_staffing_authorizations
  with unique nonce, grant digest and approval ID, preserves all
  historical Room/Session tables, and updates schema_meta to 13
  in the same transaction.
- **This is not an approved canonical PX schema bump.** PX #130
  currently supports v12 only. Candidate SQL is not invoked by
  PX migrate(), native daemon, build installer or systemd units.
  The PX owner must approve and reconcile this version change
  with all open writer branches and recovery protocols. Old PX
  source intentionally refuses a candidate v13 DB.

### VERIFY

tests/test-px-hospital-staffing-transport-v13.py runs only on
GitHub Actions using temporary SQLite WAL databases. It verifies
request frame shapes, exact parser refusals, duplicate fields,
invalid or unsupported operations, denied native dispatcher and
versioned migration semantics.

The candidate migration rehearsal takes a WAL online backup of an
intact disposable v12 store, preserves old Hospital messages,
migrates the copy to candidate v13, checks uniqueness and foreign
keys, proves older v12 PX code refuses newer schema, then restores
the exact pre-upgrade backup and verifies source integrity.
Conflicted candidate tables and wrong starting versions fail without
advancing schema_meta or overwriting existing rows.

Existing signed staff grant and original atomic Session/Doctor
rollback tests still run independently. Latest integration,
Hospital Store and Grammar workflows passed **3/3** at exact commit
eafa7b791329d1144edb396558d2a616c25c8afb.

### WATCH OUT FOR

No installed staff native issuer, authenticated process/seat,
Polkit consent, reviewed signing key revocation, native handler,
host migration/fencing/backup/rollback, or production acceptance.
The staged source adapter and migration candidate are not an
installed release. PX #123 and #125 still require source-owner
reconciliation; Bed #127/#128/#129 remains fixture-only. Hospital
Burn remains explicitly unsupported.

### NEXT

Independent PX/Connections/Hospital review of the typed PREPARE/COMMIT
contract and candidate v13 schema; then the purpose-specific protected
native handler, operator/seat permission and exact signed approval.
After those approvals: real backup/restore, all-writer cutover,
independent security review and operator-authorized installation.

### DECISIONS

Keep PR #133 draft; no adjacent owner branch, real database,
local machine, service, key, QML permission, merge or production
switch changed.


## 2026-11-19 // Package 1 protected Session/Doctor PREPARE/COMMIT rehearsal

**Status:** source-only, disposable CI PASS; native staffing service remains
UNINSTALLED, UNAUTHORIZED and UNMERGED. Exact test head:
ab4499b4d4967d2511b0df8515cbc03f79132c9e (3/3 workflows PASS).

### IMPLEMENTATION

- bin/px_hospital_staffing_grants.py now cryptographically binds exact
  signed requestNonce (32 bytes) and writerInstance to the granted
  staffing change. This prevents reusing a grant issued for one
  PREPARE or another writer/service instance.
- bin/px_hospital_staffing_prepare_commit.py implements a CI-ONLY
  coordinator, never an installed socket or native handler. PREPARE
  checks a protected Room/Patient/Bed, linked ACTIVE Assignment,
  current Doctor and Provider, source revision and graph digest.
  It records the exact typed intent, a bounded expiry and synthetic
  root peer identity (PID, UID, process-start witness).
- COMMIT consumes exactly that PREPARE, checks unchanged caller,
  Room and intent, writer instance and deadline, requires a
  separately signed staffing grant via the root-pinned verifier,
  and matches signed scope/revision/graph/nonce/writer identity.
  It then calls the original independently sourced atomic
  Session attach or Doctor succession operation with the
  verified grant consumed inside the same BEGIN IMMEDIATE.
- A COMMIT attempt spends its in-memory PREPARE even if rejected;
  in-memory tombstones prevent reusing the same PREPARE nonce
  during its authorization lifetime. SQLite failures roll back
  both approval ledger and Session/Doctor changes.
- The coordinator constructor requires GitHub Actions and
  disposable RUNNER_TEMP, and has no active network, socket, CLI,
  key override, production DB opener, service unit or issuer.
  Existing native dispatch_native_request and
  dispatch_native_staffing remain DENY ONLY. PX protected writer
  and generic store allowlist remain unchanged.

### VERIFY

- tests/test-px-hospital-staffing-prepare-commit.py runs only in
  disposable GitHub CI, builds v12 and rehearses proposed v13
  ledger migration. It tests exact signed PREPARE/COMMIT success,
  wrong peer, wrong signed nonce, forged signer, writer restart,
  stale graph, expired PREPARE, repeated COMMIT and replayed
  PREPARE. A forced Session insert error after signed approval
  consumption rolls back the ledger and Session together.
- A fresh signed Session attachment and subsequent signed Doctor
  succession preserve historical Message, HANDOFF and event
  records, with SQLite integrity and foreign-key checks.
- Existing independent owner source parity, Room Trash/Restore,
  candidate ledger rollback, grammar and Hospital Store tests
  remain in CI. 3/3 GitHub workflows passed at the exact
  tested source head ab4499b4.

### WATCH OUT FOR

A synthetic CI root peer tuple is NOT real kernel process evidence,
active user consent or an installed Polkit signer. PX schema v13 is
a candidate, not an approved canonical migration. Real runtime still
uses legacy v12 and no native staffing socket. No review of service
identity, signing-key custody, revocation, actual Bed ownership,
all-writer old-binary fencing or native backup/rollback is complete.
Bed operations remain separately owned and unexposed. Hospital Burn
is unsupported.

### NEXT

Independent PX and Connections owner review of the exact grant
fields, source v13 migration, CI coordinator and protected host
identity. Only after signed executable/seat proof and explicit
operator-approved consent can this be converted to a native
service handler, with separately approved database migration,
complete all-writer cutover, backup/recovery and final acceptance.

### DECISIONS

Retain PR #133 as draft. No owner branch, local files, machine
services, production keys, live Hospital Room, merge or permanent
Burn changed in this milestone.


## 2026-11-19 // Session/Doctor trusted native grant revalidation fix

**Status:** security implementation and disposable GitHub CI PASS. No
native host installation, kernel-confirmed operator seat, protected
staffing dispatcher or database migration has been approved.

### IMPLEMENTATION

- Removed reliance on the editable Python native_verified flag as
  authorization in the staged native Session/Doctor mutation path.
  VerifiedStaffingGrant now retains the original canonical signed
  envelope bytes rather than an arbitrary reconstituted body.
- require_native_grant() in bin/px_hospital_staffing_grants.py
  verifies the original signed bytes AGAIN under the current
  root-controlled public issuer key, validates the installed
  host fingerprint, compares the reverified digest and body
  against the previously accepted grant, and checks current
  expiration. A fixture-verified grant or forged flag cannot
  bypass this check.
- The staged atomic Session/Doctor adapter calls root-pinned
  revalidation immediately before attempting the staffing
  transaction. The grant consume() method also revalidates any
  native-verified grant WITHIN the original atomic SQLite
  transaction. A revoked or expired authorization cannot
  spend its nonce or change the staffing records.
- No live signer, private key, installed anchor, socket
  command or QML permit flag was added.

### VERIFY

- tests/test-px-hospital-staffing-atomic-consent.py now verifies
  that forcibly setting a forged fixture grant's
  native_verified flag to True does not promote it to trusted
  authorization. A legitimate grant is also refused if the
  installed issuer key changes, the host identity changes or
  the signed grant expires before the actual Session write.
- Existing signed PREPARE/COMMIT, source-level Session/Doctor
  atomic rollback, candidate v13 WAL migration, Room
  Trash/Restore and old-writer protections continue in CI.
- Three exact-source-head workflows PASS at
  57eee11a915c91af56e677c81b770c88e19dc72c:
  Hospital / Universal Connections Signed Trash Restore,
  PX / HOSPITAL STORE, Meta Apollo Grammar.

### WATCH OUT FOR

This closes an in-process flag-promotion bug, not the entire
native authorization problem. Arbitrary malicious Python
running inside the writer process is not a safe security
boundary. Production still requires a review of the installed
executable and protected process/UID, real kernel peer evidence,
active-seat Polkit consent, issuer enrollment, native connector,
versioned v13 schema owner acceptance, all-writer fencing,
verified live backup and rollback, and operator acceptance.
The CI-only PREPARE/COMMIT coordinator and version-13 candidate
remain uninstalled. Bed and Hospital Burn stay unexposed.

### NEXT

Coordinate with the independent PX #123/#125 Session/Doctor owners
and Connections issuer owner before introducing native protected
staffing commands. Reuse the existing reviewed Linux peer and
per-packet credential checks rather than inventing a second
unreviewed privilege mechanism. After schema-owner approval,
test true native operator/seat/executable provenance, cut over
all old writers, and verify WAL recovery before release.

### DECISIONS

PR #133 remains draft/unmerged. No live Hospital DB, service,
local host state, production key, unrelated owner branch or
permanent Hospital Burn was modified.
