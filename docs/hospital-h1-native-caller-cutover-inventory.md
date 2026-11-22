# 🏥 H1 Hospital Trash++ // Native caller cutover inventory

PATIENT // The-Post-Apollo-Dev-Exp (PX) and The-Post-Apollo-Project (application evidence)  
ROOM // Hospital Trash++ ↔ Universal Connections  
ROLE // External Hospital-compatible DOC; live Hospital registration unverified  
ASSIGNMENT // Read-only source caller/launcher inventory for safe H1 Room Trash/Restore cutover  
STATE // SOURCE/CI ONLY · PRODUCTION HOLD

## IMPLEMENTATION // What the source really does

The existing H1 release has TWO substantially different client paths:

1. The **new Room Trash/Restore** application services use a pinned native
   `hospital-room-request` and `hospital-room-read`. The root Connections
   issuer and PX consent writer use one-use PREPARE → signed COMMIT against the
   dedicated protected Room database, tested on disposable SQLite.
2. Many **other Hospital operations** still invoke a desktop-local PX
   executable from QML, generally preferring
   `~/.local/share/post-apollo-dev-runtime/bin/px` and falling back to
   `~/.local/bin/px`. PX `bin/px` delegates `hospital` commands directly
   to `python3 "$ROOT/bin/px-hospital-store"`. Three other PX routes
   invoke the same legacy store for Session and Assignment checks.

PX #130's cutover marker refuses any future direct `connect()` from
**current-source** `px-hospital-store`; the native writer and Connections
consent writer now require a root-trusted marker before starting. These
protections prevent accidental fallback access, but do NOT automatically
reroute existing desktop callers to the protected writer.

The generic PX protected `store-command` endpoint has **21 reviewed writes
and 19 reviewed reads**, reserved for a **distinct native runtime UID**.
It is **not an approved desktop-user RPC or arbitrary QML command proxy**.
Permitting direct desktop access to that bridge would change the authority
boundary and is NOT authorized by this H1 inventory.

## VERIFY // Exact pinned, executable-source evidence

The Hospital / Universal Connections CI workflow checks out
The-Post-Apollo-Project at exact `e8de69000d4ebb5b36a580cfbf87f59989317b1c`
as `hospital-ui-source`. The new
`tests/test-px-hospital-h1-native-caller-inventory.py` reads every
`services/hospital/**/*.qml` in that pinned checkout and the current
PX `bin/px`. It does not execute those UI launchers, inspect the user's
processes, open a Hospital DB, modify a file or approve native release.

The first passing raw CI run recorded **22** QML services referencing
desktop-local PX and **2** referencing protected Room native executables.
The former include:

- HospitalAssignmentService, HospitalAuditService,
  HospitalCertificationDriftService, HospitalChartService
- HospitalDoctorNameService, HospitalDoctorRuntimeService,
  HospitalDoctorService, HospitalDoctorSuccessionCapabilityService
- HospitalPersistentDispatchService, HospitalProviderService,
  HospitalResponsibilityService
- HospitalRoomCheckpointService, HospitalRoomContinuityService,
  HospitalRoomConversationAdapter, HospitalRoomNameService
- HospitalRoomReportCatalogService, HospitalRoomReportService,
  HospitalRoomService
- HospitalWorkerAttachmentActionService,
  HospitalWorkerAttachmentPreviewService, HospitalWorkerTranscriptService,
  HospitalWorkforceRoomCreateService

The two protected Room-specific services are
`HospitalRoomLifecycleService.qml` and `HospitalRoomBinService.qml`.
PX `bin/px` has **four** direct `px-hospital-store` call sites, including
the generic `hospital` dispatcher. Counts refer to *source files/call
sites*, NOT separate database processes or installed services.

Especially important: `HospitalRoomConversationAdapter.qml` invokes
`px agent session-create`, which leads into existing Session registration.
`HospitalWorkerAttachmentActionService.qml` contains a conditional
`px agent session-attach` action whose atomic PX source remains a separate
unmerged draft. A capability probe is not permission to activate it.

The test deliberately emits
`allWriterCompatibilityVerified:false`,
`oldBinariesAndLaunchersFenced:false`,
`installedHostObserved:false`, and `releaseApproved:false`,
**even when source inventory and signed Trash/Restore CI pass**.

## WATCH OUT FOR // Why this gates native H1

- Existing source includes **desktop read and write** Hospital use, not
  only Trash/Restore buttons. If the protected cutover marker is installed
  without compatible routing, ordinary Hospital controls may fail closed.
- New protected Room read service currently exposes Room lifecycle review
  and Bin enumeration only; that does not replace the older general
  Doctor/Assignment/Chart/Session/Report read paths.
- The protected runtime store bridge cannot simply be made readable/writable
  by the desktop UID or wrapped in a setuid shell. Each required command
  needs an owner-approved native caller identity and appropriate permission
  boundary, with no raw SQL or unconstrained generic write proxy.
- The four separately owned, unmerged atomic Session/Doctor/Bed commands
  remain denied. Installed caller discovery must determine whether any
  existing runtime, partial UI feature or agent script still requires one.
- A source checkout cannot prove that the operator has installed these same
  bytes, has quiesced older binaries, has fenced new legacy starts, owns a
  recoverable WAL backup, or has authentic seat/Polkit/retention consent.
- This document does not add a live diagnostic, installed service,
  desktop permission or user-facing activation button. **Hospital Burn is
  still out of scope.**

## NEXT // Release-order decisions

1. Reconcile this pinned QML inventory against **current application main**
   and the actual installed user-facing launchers. Identify the concrete
   required Session/Doctor/Assignment/Chart/Room workflows, not just names.
2. Assign protected **read** and authenticated **write** route ownership
   for each required operation. Retain the separate runtime identity and
   explicit command allowlist; never permit a desktop shortcut to privileged
   `store-command`. Unmerged Bed/succession paths remain gated.
3. Verify the source and installed versions of all PX launchers, including
   `bin/px`, `bin/px-agent`, Quickshell QML, systemd and any alternate
   legacy direct-SQL processes. Establish irreversible old-binary launch
   fencing before the root-controlled cutover marker is installed.
4. Independently verify WAL-consistent backup, v10→v11→v12 migration,
   rollback, root ownership, UID/socket/SELinux, C5 issuer and retention
   authority. Run a native integration acceptance covering **both**
   ordinary Hospital operations and Room Trash/Restore.
5. Keep draft/source CI separate from final operator acceptance, merge and
   live host installation.

## DECISIONS

H1 Room Trash/Restore remains first, with no weakening of linked Room history,
native source ownership, old-writer safety or operator authorization.
H2 D1–D5 staffing historical recovery remains separately tracked, and
Hospital Burn remains future Batch 2. This source inventory establishes a
**real routing gap**, not a new authority to rewrite the application's
separately owned UI or start protected services.

## H1 next increment // Doctor metadata source route (no UI migration yet)

At PX #130 source head `ff963f5de5d73f473fd58246f9ba056740fca208`,
the protected Room writer added an exact `doctor-directory` operation
to its existing desktop-reader UID lane. This is *not* general
`store-command` access: zero arguments, no SQL or user-selected filters,
fixed six-field Doctor metadata projection, at most 250 records,
a fail-closed refusal when larger, and an existing
Linux `SO_PEERCRED` socket CI fixture that tests rejection of forged
fields, untrusted peers and over-limit output. Neither Doctor edits nor
new staffing Session/Bed commands become available to the desktop.

This is the **first source-level read-only building block**, not a
completed Hospital service migration. The pinned
`HospitalDoctorService.qml` still launches `px hospital doctors` and
`px hospital doctor-put`. The installed native reader and that QML
service have **not** been modified or activated, and Doctor writes
remain unresolved. Before this new action can be used by the UI, the
fixed trusted `hospital-room-read` client requires an independent
reviewed operation/response contract and explicit source-identity
enrollment, followed by end-to-end native tests and operator acceptance.

**Native release HOLD** stays unchanged. The 22-source-caller inventory
and all-writer compatibility gaps remain. Hospital Burn remains denied.
