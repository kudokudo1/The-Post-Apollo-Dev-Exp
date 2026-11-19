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
