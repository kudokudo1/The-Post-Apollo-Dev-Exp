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
