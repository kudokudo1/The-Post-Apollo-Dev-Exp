# 🏥 PX // Protected Hospital Room Writer Service V1, source checkpoint

**Patient:** `The-Post-Apollo-Dev-Exp` · **Room:** Hospital Room Trash/Restore backend · **Staff:** operator-assigned PX owner, external Hospital-compatible DOC; live Hospital registration unverified.

**Branch:** PX draft [#130](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/130), stacked on Room-name v11 [#121](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/121). **Status:** Functional *source-only* Unix-socket Room writer and disposable Linux integration. **PRODUCTION HOLD**.

## IMPLEMENTATION

The initial [writer audit](hospital-room-protected-writer-audit-v1.md) demonstrated a same-UID bypass against the desktop-owned `hospital.db`. The code now implements a separate-UID **Room lifecycle service plus reviewed legacy store command routing**, rather than claiming that a signed CLI alone secures user-writable SQLite. Runtime service admission is distinguished from desktop-human approval.

- `bin/px_hospital_room_writer.py`: a real local AF_UNIX stream server. Linux `SO_PEERCRED` provides kernel PID/UID/GID. The server accepts exactly two **distinct**, root-configured non-root peer UIDs: a desktop `clientUid` for Room review/bin and individually signed lifecycle operations, and an independent `runtimeUid` for the explicit legacy store-command routes. Neither UID is proof of an authenticated executable, active seat or human consent; the server does not trust request JSON identity claims.
- The storage owner must be a **non-root, separate service UID**. Its existing `hospital.db` must be an owner-only regular file inside an owner-only `0700` directory; WAL/SHM files are checked. The server opens one fixed `hospital.db` via SQLite `mode=rw` and **refuses missing/non-v12 storage** rather than creating or migrating it.
- A different, service-owned `0711` socket directory permits traversal. The daemon-created socket is **0600 by default**. A future trusted installer must grant exactly the approved `clientUid` and `runtimeUid` access by a reviewed restricted ACL/group policy; the daemon does **not** widen socket access itself. Disposable CI uses a briefly world-writable socket for kernel UID-denial testing, then changes its group to the runtime fixture identity and removes world access for the client transport test. **Never copy the temporary mode into an installed system.**
- Exact, bounded one-frame JSON RPC; a single connection handles one request. An untrusted client cannot choose DB directory, SQL, grant verifier, public key or issuer. The desktop peer can request only `review`, `bin`, `trash`, `restore`. The separate runtime peer may additionally request `store-command` with a bounded string-argv array reviewed against the actual `px-hospital-store` argparse command schema. An unknown command, extra field, duplicate JSON key, malformed frame, missing signature, wrong host, wrong UID or Burn returns generic DENIED. There is no raw SQL or filesystem delete endpoint.
- `review` returns the existing `room_lifecycle.review()` summary without a signed authorization claim. `bin` returns the existing metadata-only trashed Room inventory, with no transcript/report bodies. Both pinned peer UIDs may use these two lifecycle metadata operations, but only `clientUid` can submit an individually signed Room lifecycle transition.
- `trash` and `restore` verify the request's **actual Ed25519 envelope bytes** with the existing PX root-pinned public-key reader at `/etc/post-apollo/hospital/room-lifecycle-issuer.pub`, compare signed current host identity to `/etc/machine-id`, and call the original `room_lifecycle.transition()`. It consumes nonce and approval ID and writes state+receipt in the same `BEGIN IMMEDIATE` transaction. The signed source alone does not prove installed seat or true human approval; those are independent Connections/C5 responsibilities.
- `bin/px-hospital-room-writerd`: a pre-install daemon entrypoint with **no arguments** and no environment-selected DB. It reads the exact `/etc/post-apollo/hospital/room-writer.json` root-owned config with `O_NOFOLLOW`, exact field schema, strict owner and parent permissions, a pinned `writerUid` matching its actual nonroot process UID, and distinct `clientUid`/`runtimeUid`. It validates fixed state/socket directories and requires the service manager to supply lifecycle and identity isolation. The repository **does not install, start, enable or configure** that service.
- `bin/px_hospital_protected_store_bridge.py`: **21 explicit write routes and 19 read routes** call the original trusted `px-hospital-store` functions on the protected owner connection, preserving source validation, Assignment logic, Room SQL triggers, transaction/receipt behavior and output structures. `init`, unsigned/signed legacy lifecycle CLI, raw SQL, unknown future Bed commands, file-based grants and server stdin are excluded. Parser/allowlist coverage is checked before any route; new Hospital subcommands cannot be silently promoted into remote privileges.
- `bin/px_hospital_protected_client.py` and `bin/px-hospital-protected-runtime`: the separate PX runtime caller reads only the fixed root-owned native host config, requires the exact `runtimeUid`, verifies the Unix socket's owner and kernel-reported **server UID**, and translates bounded legacy `--body-stdin` input into an ordinary `--body` argument. The runtime client has **no fallback** to the old SQLite DB when the host contract or socket fails. Tests demonstrate the private runtime identity can read and write through the socket, while the desktop peer receives DENIED for `store-command`.
- No QML permission flag or existing desktop CLI has been rewired to this service. The old user-owned PX database remains a separate *unprotected* data store until a coordinated, backed-up, fail-closed migration and all-writer cutover is approved.

## HOST CONFIG CONTRACT // Administrator-owned, **not** a user setting

Root-owned path: `/etc/post-apollo/hospital/room-writer.json`.

Required exact keys:

| Key | Semantics |
|---|---|
| `schema` | `post-apollo.hospital.protected-room-writer-host.v1` |
| `writerUid` | Non-root dedicated service UID, must equal actual real/effective process UID |
| `clientUid` | Distinct, non-root desktop client UID; metadata + separately signed Room lifecycle only |
| `runtimeUid` | Third, separate non-root PX runtime service UID; explicit legacy store routes only |
| `stateDirectory` | Absolute trusted service-owner directory containing pre-migrated `hospital.db` |
| `socketDirectory` | Separate absolute service-owner socket directory accessible only under reviewed policy |

This document deliberately supplies **no** complete install commands, machine UIDs, service users, SELinux policy or runtime override. The correct values require a verified installed-host inventory, approved systemd unit, root-owned config and rollback plan. Do not configure this from QML, the desktop environment or a user-selected file.

## VERIFY // Disposable CI tests

`tests/test-px-hospital-protected-writer-socket.py`:

1. Creates a fresh v12 SQLite database and fixture Room under a temporary private owner directory.
2. Starts the real Unix socket server using the unprivileged runner as the writer owner, with `nobody` as the desktop analogue and `daemon` as a **third distinct PX runtime UID**. All identities and files are temporary to CI.
3. Proves a wrong-UID process is denied over the socket, but the configured peer can request bounded Room review/bin metadata. Neither UID can supply SQL, Burn, a key path, or an unsigned lifecycle transition.
4. Verifies the desktop-like UID cannot open SQLite directly while it can communicate through the socket.
5. Uses ephemeral Ed25519 keys solely via `unittest.mock.patch.object` *inside the test owner's process* to replace root-pin lookup for this fixture; **no client-accessible test key injection exists**. Tests wrong issuer, wrong host, accepted signed TRASH, one-use replay refusal, fresh signed RESTORE, retained Room, nonce rows and receipts.
6. Restarts the protected socket against the original database and verifies restored state/revision. Uses SQLite's online backup API, checks a separately recovered database with `PRAGMA integrity_check` and matching Room, grants and receipts. No copy of a live WAL file.
7. Tests the complete reviewed legacy router with the third UID: Room/Doctor updates, Session/Event, Assignment, Message, Checkpoint, Report and Chart writes/reads; direct legacy write while Room is trashed is denied. The desktop UID cannot use `store-command`; `init`, legacy lifecycle CLI, raw SQL, server stdin and unknown operations all refuse.
8. Tests the separate runtime CLI transport against the exact source copied to a read-only disposable fixture directory, checks the protected server UID and rejects a world-writable socket. A bounded `--body-stdin` message round-trip succeeds over a group-restricted disposable socket, with the host-config reader remaining fail closed in CI.
9. Leaves the user host untouched. The temporary database, keys, socket, identities, group permission simulation and recovered backup vanish with CI cleanup.

`tests/test-px-hospital-writer-host-refusals.py` confirms the pre-install launcher refuses caller-provided config/DB/key/unsigned options. Existing signed lifecycle, same-UID bypass-negative and separate-UID DAC tests remain.

**IMPORTANT:** The passing bypass witness against the old user-owned DB is still a **negative** security test. The protected socket positive test is not installed-host, crash/power-loss, executable provenance, logind, SELinux or consent acceptance.

## WATCH OUT FOR // Security blockers and collisions

1. **Source routing exists, installed all-writer cutover does not.** The reviewed legacy v12 commands are available behind the third PX runtime UID in the **draft** source service, but the existing desktop `bin/px-hospital-store` still opens the old user-owned database directly and native PX runtime processes have not been redirected to the protected client. PX #121/#123/#125/#127/#128 and other Hospital workers add new writer commands or authority checks that are **not** silently imported into the reviewed allowlist. Their owning branches must reconcile, then a supervised root-owned native release must switch every client to the same protected DB, fence old binaries and remove any writable fallback. *Never make the protected DB writable by the desktop UID to keep old CLIs working.*
2. **Connections issuer is not installed.** Application [C5-H1 #2051](https://github.com/kudokudo1/The-Post-Apollo-Project/pull/2051) provides scoped CI-only grant admission, not an independent native signer. A trusted C5/C3e host must prove real caller/executable+start identity, active seat, explicit per-Room and per-action human consent, retention/legal-hold and revocation, and protected private signing key. A desktop process that merely learns a signed grant may race to consume it; native request-to-issuer-to-writer transport and anti-confusion rules require security review.
3. **Kernel UID is necessary, not sufficient.** Any process of the configured desktop UID could request metadata or submit a stolen signed envelope. Any process with the privileged `runtimeUid` could invoke the existing store's allowed mutations and could set unverified textual author/operator fields. Production executable/PID-start identity, sandboxing of runtime workers, per-Assignment authority, IPC admission, rate limiting, supervised restart, socket ACL and per-operator data authorization require independently accepted implementation.
4. **No production migration/backup/recovery yet.** The native owner must inventory the real database, quiesce writers, take a WAL-consistent backup, prove restoration, stage v10→v11→v12 and rollback with old binaries fenced, establish service account and SELinux policy, and verify installed-host replacement without interrupting active Hospital work.
5. **No permissionReady promotion.** Hospital UI is still fail-closed, and these source-level results do not set `operatorAuthenticated:true`. Permanent Burn remains disabled.
6. **No root-owned config or systemd unit is created by this PR.** This source is designed to refuse startup until a separately approved native installer establishes its fixed OS trust boundary.

## HOW TO USE

No action on the operator's machine. The CI workflow runs the disposable socket integration automatically. Host deployment, root config, service identity, migration and client cutover are **not approved by this source milestone**.

## CHECKLIST

- [x] Same-user direct SQL bypass reproduced against old storage
- [x] Distinct-UID SQLite and backup DAC isolation proven
- [x] Source-only protected AF_UNIX writer and signed transitions added
- [x] Root-config-pinned daemon launcher and no-override refusals added
- [x] Exact peer identity, bounded RPC, wrong-UID and arbitrary-operation refusal tests
- [x] Disposable signed Trash/Restore, replay, restart and online backup restore tests added
- [ ] Host service identity/socket/SELinux/install design independently accepted
- [x] Route reviewed legacy v12 read/write commands through the protected owner under a third PX runtime UID; preserve trashed-Room triggers and refuse future commands without explicit review
- [x] Provide a pinned, no-fallback runtime client and bounded stdin compatibility with real cross-UID socket CI
- [ ] Install and migrate **all native callers and new Bed/Session/Assignment branch writers** to the supervised protected store, fence legacy direct SQLite and verify rollback
- [ ] Installed Connections/C5 Hospital-specific issuer, per-operation human consent and trusted transport
- [ ] Verified native backup, migration, interrupted-write recovery and rollback
- [ ] Hospital UI/Trash++ native end-to-end test and independent review
- [ ] Operator-approved merge, deployment and final acceptance

## NEXT

PX owner: source-level v12 legacy store routes are staged behind the privileged runtime UID and tested. **Next, coordinate the native caller cutover and new Bed/Session/Assignment branch command reconciliation**, without weakening existing assignment protections. Prepare a sealed native service account/socket/SELinux unit and backup plan with the operator and PX runtime owners. Connections/Identity owner: deliver independently authenticated native Hospital-specific signer. Hospital/Trash++ owner: keep controls locked until installed acceptance.

## DECISIONS

Maintain PX #130 as draft, unmerged. Keep schema v11 dependency #121 and concurrent ownership intact. No root config, local migration, real grant, live Room change, host installation or permanent Burn was performed.

## H1 legacy-store cutover tombstone // source gate, not activation

**State: source/CI only. Operator-approved native installation and complete
old-process inventory remain required.** After the operator's decision to
release H1 with the four unmerged Session/Doctor/Bed commands disabled, this
branch provides a narrow safeguard against accidentally reopening the old
desktop-owned Hospital database from the *current source revision*.

- `bin/px-hospital-store` now checks exactly
  `/etc/post-apollo/hospital/legacy-store-cutover.v1` at the beginning of
  `connect()`, **before** creating a data directory, opening SQLite or
  migrating a schema. Any present file, directory or symlink refuses with
  `HOSPITAL_NATIVE_PROTECTED_RUNTIME_REQUIRED`; errors inspecting the
  marker also refuse. The path cannot be chosen through argv/environment.
- **Native startup now enforces a stronger counterpart:** the PX writer's
  `read_host_config()` demands this same exact marker under root-controlled,
  non-group/world-writable directory ancestors before returning the configured
  service identities. The marker must be a root-owned, single-link regular
  file with mode `0400`, `0440` or `0444`. Absence, a symlink, a directory,
  a writable marker, or an untrusted parent refuses service startup.
  `px-hospital-consent-writerd` imports this exact function, so both writer
  endpoints inherit the gate. The legacy CLI still denies on *any* marker
  entry, including invalid ones; an invalid marker can never open the old
  desktop database by making the native service refuse.
- The marker is **deny-only**: it does not configure the protected owner,
  authorize Trash/Restore, prove a live issuer, or validate the host. Its
  contents are deliberately not parsed for permissions. No marker is
  created or installed by this PR. A trusted installer must own the marker
  and its parent directories under the approved native release.
- The protected runtime's 21 reviewed write and 19 read routes operate on
  the already protected service-owned SQLite connection. They do **not**
  invoke the old `connect()`; this is verified with the marker present.
  `session-attach-atomic`, `session-succeed-atomic`,
  `room-bed-claim-atomic` and `room-bed-claim-signed-atomic` remain
  `COMMAND_NOT_EXPOSED`. The marker is not permission to use those
  unmerged features.
- New `tests/test-px-hospital-h1-legacy-cutover-fence.py` uses disposable
  paths and in-process marker redirection only inside CI. It proves
  pre-cutover legacy compatibility, marker/fail-closed refusal,
  environment override refusal, protected read/write compatibility and
  exclusion of all four unreviewed commands.

### Native operator acceptance order (not automated here)

1. Inventory **all** installed PX/Doctor/Session/Bed/Assignment/Chart
   commands and process launch sources, including versions that predate
   this guard. Decide which four draft commands are required vs deferred.
   Validate runtime and operator UI use only approved routes.
2. Quiesce every old writer and fence future launches independently.
   A current process scan cannot prove a future binary will not start;
   this marker only protects binaries containing the new source guard.
3. Make and independently restore-verify a WAL-consistent owner-only
   Hospital backup. Stage schema v10→v11→v12 migration and reconcile all
   historical records before switching the authoritative database.
4. Install and verify exact root-owned release sources, dedicated writer
   identity, separate runtime/client identities, socket ACL/SELinux,
   Connections issuer, Polkit/seat/retention authority and tested protected
   native read/write transports. Do not grant desktop SQLite access.
5. Only in the operator-approved quiesced cutover window, atomically
   provision the root-controlled deny-only marker; re-observe that all
   current-source direct `px-hospital-store` access refuses, that **old
   pre-marker executables remain prevented from launching**, and that
   protected native routes work without fallback. Then resume the
   approved Hospital workflow against the one protected database.
6. If validation fails, **leave Hospital writers stopped** and the
   original archive protected. Do not remove the marker to improvise
   a desktop fallback. An old-schema rollback after new writes requires
   deliberate history reconciliation and fresh operator permission.

**Scope warning:** This marker is *one defense* in native old-writer
fencing, not a replacement for installed process provenance, trusted
enrollment, backup/rollback or native end-to-end acceptance. It does not
enable Hospital Trash/Burn, does not affect the operator's workstation,
and does not complete H1 production release.

## H1 native Doctor directory // first bounded metadata-only route

**Source-only, pending independent review and native installation.** The
existing protected Room writer now accepts one additional exact action,
`doctor-directory`, on its existing desktop-reader UID lane, alongside
`review` and `bin`. The request has **exactly** `schema` and `operation`:
no Room ID, caller-selected argv, filters, raw SQL, paths or alternate
client UID. The response carries only Doctor `id`, `name`, `role`,
`status`, `createdAt` and `updatedAt`, ordered as in the existing PX
Doctor list. The protected owner performs a parameter-free fixed SQL
`SELECT` with a hard limit; above **250 records**, the whole request
fails closed rather than truncating a roster.

This is intentionally separate from the generic `store-command` bridge:
only the distinct native runtime service UID may invoke its 21-write/19-read
legacy argv allowlist. The desktop UID gains **no Doctor mutation**, no
Session/Assignment/Chart reads and no ability to elevate through argv,
SQL or forged fields. Existing C5 signed Room Trash/Restore and legal-hold
authority are unchanged.

The disposable Linux `SO_PEERCRED` socket fixture verifies a real
distinct-client Doctor directory read after source-owned `doctor-put`,
exact output fields, denial to the writer's own UID, denial of arbitrary
payload fields, and over-limit refusal with no persistent fixture changes.
It does not prove user-interactive entitlement, installed socket ACL,
native client executable provenance or a production Doctor roster.

The application Doctor QML service **still invokes the old desktop PX CLI**.
No application native read client or UI is switched by this source change;
the caller-inventory release HOLD remains in force. Next integration requires
a separately reviewed installed `hospital-room-read` operation contract
and UI routing, preserving exact-source behavior and returning no privileged
`store-command` access. The additional read is not a reason to place the
root cutover marker early.

