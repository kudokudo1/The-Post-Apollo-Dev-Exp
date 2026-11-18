# Hospital PX // Room lifecycle protected-writer audit V1

**Patient:** The-Post-Apollo-Dev-Exp. **Room:** Hospital source-owned Room Trash/Restore (PX #130). **Role:** External Hospital-compatible DOC, PX ownership assigned by operator; no live Hospital registration verified.

**Checkpoint:** audited against PX #130 head 8c0f9c4e5788579efd9d34672ff308f4bca2937f, which stacks on PX #121 (v11); current PX main is not v12. **State:** security boundary NOT IMPLEMENTED. Source and CI are not native acceptance.

## IMPLEMENTATION // Where the bytes are written

1. `bin/px` delegates `px hospital ...` commands to Python `bin/px-hospital-store`. This is a convenience wrapper, not a service or security principal.
2. `bin/px-hospital-store` lines 338–368 select a user-relative directory (`$XDG_DATA_HOME/post-apollo/hospital` or `~/.local/share/post-apollo/hospital`), with `PX_HOSPITAL_DATA_DIR` / `PX_HOSPITAL_DB` overrides. The entrypoint creates the directory, opens `hospital.db` with `sqlite3.connect`, and sets `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`. No distinct OS-level writer identity or server boundary is established.
3. The same store performs migrations and direct Room/Patient/Doctor/Session/Message/Event/Checkpoint/Report/Chart/Assignment writes. Representative functions: `room_bind`, `room_put`, `room_name_set`, `session_put`, `session_runtime_update`, `event_append`, `checkpoint_append`, `room_report_append`, `chart_entry_add`, `chart_entry_status`, `chart_suggestion_add`, `chart_suggestion_reject`, `chart_suggestion_promote`, `assignment_create`, `assignment_update`, `assignment_status`, `assignment_activate`, `message_append`, and the Doctor/Patient setters.
4. PX v12's `bin/px_hospital_room_lifecycle.py` uses `BEGIN IMMEDIATE` for signed TRASH/RESTORE. The signature verifier in `bin/px_hospital_room_authority.py` pins an independent public key and consumes a nonce/approval once inside that transaction. SQL triggers reject normal writes to a TRASHED Room and linked records. These source invariants remain useful.
5. `bin/px-operation-store` has its own operation-journal SQLite connection, **not** the Room database; this audit must not conflate them or migrate it by accident.
6. `bin/px-agent` and the `bin/px` wrapper do not supply a protected database owner. Their requests eventually reach the direct store. Audit/room registry TSV files and the separately scoped operation journal are not lifecycle source storage.

## VERIFIED RISK // The current source is not a trust boundary

An untrusted peer running under the same desktop UID can open the user-writable SQLite file directly. It can write `room_lifecycle`, erase lifecycle state, alter receipts or approvals, or modify the database schema and triggers. A CLI-only signed-grant check cannot stop such a peer.

`tests/test-px-hospital-unprotected-writer-witness.py` uses **only** a disposable temporary v12 database. It creates a Room using the real PX CLI, opens a second SQLite connection, marks that Room TRASHED with no signature/nonce/receipt, observes it vanish from active Rooms, then removes the lifecycle row to make it active again. This is an intentionally passing **negative security witness**. It is not a security-acceptance test and must be replaced by a denial test when real OS isolation exists.

A signed request alone, SQLite triggers alone, `chmod 0600` on a file owned by the desktop UID, and `SO_PEERCRED` on a service sharing that same UID are not complete malicious-same-user protection.

## COORDINATION // Shared file and branch collisions

The v11 prerequisite PX #121 changes `bin/px-hospital-store` and the Hospital workflow. PX #123 (Session admission), #125 (Doctor succession), #127 (first Bed), and #128 (signed Bed) also change the store. PX #129 adds a Bed intent gateway on its own nested branch. Do not overwrite these heads or infer that a merged nested feature equals mainline delivery. Their writer operations must be ported or mediated through the final owner-owned service before native activation.

The application counterpart #2045 is already merged, but its `permissionReady` gate remains fail-closed. Connections/Identity still owns native signer/human consent. Trash++ owns the user-facing bin; PX owns the Room database and source receipts.

## PROPOSED PROTECTED WRITER BOUNDARY // Requires owner approval

1. Use a **dedicated system service identity distinct from the desktop UID**, with a private OS-protected database directory and file/WAL/SHM/backup ownership. The desktop UID must not have directory write or SQLite file access. No user-controlled `PX_HOSPITAL_DB` or `PX_HOSPITAL_DATA_DIR` override may select the protected production database.
2. A narrow local Unix-domain RPC interface exposes authenticated read methods and explicit allowlisted mutations. Check kernel peer credentials and caller lifetime. Do not expose raw SQL, `ATTACH`, arbitrary database paths or a general signed-file upload that bypasses issuer binding.
3. For lifecycle mutation, obtain a one-use grant from the separately trusted Hospital-specific Connections/Identity issuer, with exact Room/action/revision/graph, operator presence, live seat, retention/legal-hold decision and bounded expiry. Only the protected writer consumes it with the Room transition and receipt in one transaction.
4. Authoritative Room/Session/Assignment/Message/Chart writers must be ported into this service. Read-only UI clients cannot reopen the original database directly. Do not break Session heartbeat/recovery or other worker workflows during cutover.
5. Root-controlled unit/service installation, daemon UID/group provisioning, private socket and storage ownership, SELinux confinement, key custody, backup destination and rollback require a reviewed native install plan. A fake in-process verifier or a signed local CLI is not a replacement for the OS barrier.
6. Keep production locked until positive disposable and installed-host tests show: same-UID direct SQLite writes denied; authorized service writes succeed; forged/wrong-UID/wrong-PID/replayed/expired requests refused; old writer APIs cannot bypass; crash/restart retains receipts; v10→v11→v12 backup/restore passes without losing Room history. No permanent Burn.

This is a **candidate architecture**, not a finalized host service design. Do not create real service accounts, install units, change filesystem permissions, move the user database, or activate the UI without explicit operator consent and independent security/Connections review.

## HOW TO USE

No host action required. CI may run the negative witness against disposable SQLite only. Read the output as `RISK CONFIRMED`, never as protected storage completed.

## VERIFY

- Source-only: inspect `bin/px-hospital-store` and `bin/px_hospital_room_lifecycle.py` at their exact branch SHA.
- Negative witness: `python3 tests/test-px-hospital-unprotected-writer-witness.py`.
- Positive future release gate: a separately owned writer, failed same-UID direct access, native operator consent and WAL-aware backup/restore **must be independently verified**.

## WATCH OUT FOR

An untrusted same-UID process may modify file permissions or triggers if it owns the storage. A signature validates the intended operation only when every mutation path is behind an independently protected writer. Current `HospitalRoomLifecycleService.permissionReady` must stay false; neither unsigned file paths nor QML flags can authorize a Room transition.

## CHECKLIST

- [x] Current direct-writer call graph inventoried
- [x] Parallel PX ownership/collision map captured
- [x] Disposable same-UID bypass reproduced in CI fixture (negative evidence)
- [ ] Protected storage/writer service design approved
- [ ] Protected-service implementation and all-writer migration
- [ ] Hospital-specific installed issuer and caller/seat consent
- [ ] Positive peer-denial, lifecycle and recovery tests
- [ ] v11/v12 installation/backup/rollback reviewed
- [ ] Independent security acceptance and operator-approved release

## NEXT

PX owner: coordinate dedicated service identity/storage and all legacy writer migration with PX runtime/Bed/Session owners; implement in existing coordinated scope only after approval of that OS-level authority boundary. Connections/Identity owner: supply native Hospital-specific issuer and signed transport. Hospital/Trash++ owner: retain UI fail-close and test native consumer after PX is protected. This is a blocking handoff, not completion of the Room lifecycle.

## DECISIONS

Remain on PX #130 draft. Do not merge, install, activate or burn. Keep the existing signed transaction and graph/receipt invariants. Continue PX work after preserving this checkpoint; do not absorb Connections or Hospital ownership.
