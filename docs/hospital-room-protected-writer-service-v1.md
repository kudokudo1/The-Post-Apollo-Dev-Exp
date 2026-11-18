# 🏥 PX // Protected Hospital Room Writer Service V1, source checkpoint

**Patient:** `The-Post-Apollo-Dev-Exp` · **Room:** Hospital Room Trash/Restore backend · **Staff:** operator-assigned PX owner, external Hospital-compatible DOC; live Hospital registration unverified.

**Branch:** PX draft [#130](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/130), stacked on Room-name v11 [#121](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/121). **Status:** Functional *source-only* Unix-socket Room writer and disposable Linux integration. **PRODUCTION HOLD**.

## IMPLEMENTATION

The initial [writer audit](hospital-room-protected-writer-audit-v1.md) demonstrated a same-UID bypass against the desktop-owned `hospital.db`. The new code implements a first genuinely separate-UID **Room lifecycle subset** rather than claiming that a signed CLI alone can secure user-writable SQLite.

- `bin/px_hospital_room_writer.py`: a real local AF_UNIX stream server. Linux `SO_PEERCRED` provides kernel PID/UID/GID, and the server accepts only a pinned, distinct desktop UID. That UID is **not** an authenticated application executable, logged-in operator, active seat, or human consent decision. The server does not take identity assertions from request JSON.
- The storage owner must be a **non-root, separate service UID**. Its existing `hospital.db` must be an owner-only regular file inside an owner-only `0700` directory; WAL/SHM files are checked. The server opens one fixed `hospital.db` via SQLite `mode=rw` and **refuses missing/non-v12 storage** rather than creating or migrating it.
- A different, service-owned `0711` socket directory permits traversal. The daemon-created socket is **0600 by default**. A future trusted installer must separately grant access only to the approved client UID via a reviewed ACL/group policy; the daemon does **not** widen socket access itself. The disposable CI test temporarily uses 0666 on a private ephemeral runner socket to exercise the UID gate; **never copy that mode into the installed system**.
- Exact, bounded one-frame JSON RPC; a single connection handles one request. An untrusted client cannot choose DB directory, SQL, grant verifier, public key, issuer, operator, or arbitrary CLI. Only `review`, `bin`, `trash`, and `restore` exist. An unknown command, extra field, duplicate JSON key, malformed frame, missing signature, wrong host, wrong UID or Burn returns generic DENIED. There is no raw SQL or filesystem delete endpoint.
- `review` returns the existing `room_lifecycle.review()` summary without a signed authorization claim. `bin` returns the existing metadata-only trashed Room inventory, with no transcript/report bodies. Both are limited to the pinned client UID in this prototype.
- `trash` and `restore` verify the request's **actual Ed25519 envelope bytes** with the existing PX root-pinned public-key reader at `/etc/post-apollo/hospital/room-lifecycle-issuer.pub`, compare signed current host identity to `/etc/machine-id`, and call the original `room_lifecycle.transition()`. It consumes nonce and approval ID and writes state+receipt in the same `BEGIN IMMEDIATE` transaction. The signed source alone does not prove installed seat or true human approval; those are independent Connections/C5 responsibilities.
- `bin/px-hospital-room-writerd`: a pre-install daemon entrypoint with **no arguments** and no environment-selected DB. It reads the exact `/etc/post-apollo/hospital/room-writer.json` root-owned config with `O_NOFOLLOW`, exact field schema, strict owner and parent permissions, a pinned `writerUid` matching its actual nonroot process UID, and a distinct `clientUid`. It validates fixed state/socket directories and requires the service manager to supply lifecycle and identity isolation. The repository **does not install, start, enable or configure** that service.
- No QML permission flag or existing desktop CLI has been rewired to this service. The old user-owned PX database remains a separate *unprotected* data store until a coordinated, backed-up, fail-closed migration and all-writer cutover is approved.

## HOST CONFIG CONTRACT // Administrator-owned, **not** a user setting

Root-owned path: `/etc/post-apollo/hospital/room-writer.json`.

Required exact keys:

| Key | Semantics |
|---|---|
| `schema` | `post-apollo.hospital.protected-room-writer-host.v1` |
| `writerUid` | Non-root dedicated service UID, must equal actual real/effective process UID |
| `clientUid` | Distinct, non-root desktop client UID pinned by the native installer |
| `stateDirectory` | Absolute trusted service-owner directory containing pre-migrated `hospital.db` |
| `socketDirectory` | Separate absolute service-owner socket directory accessible only under reviewed policy |

This document deliberately supplies **no** complete install commands, machine UIDs, service users, SELinux policy or runtime override. The correct values require a verified installed-host inventory, approved systemd unit, root-owned config and rollback plan. Do not configure this from QML, the desktop environment or a user-selected file.

## VERIFY // Disposable CI tests

`tests/test-px-hospital-protected-writer-socket.py`:

1. Creates a fresh v12 SQLite database and fixture Room under a temporary private owner directory.
2. Starts the real Unix socket server using the unprivileged runner as the writer owner, with `nobody` as a distinct unprivileged desktop-like client.
3. Proves a wrong-UID process is denied over the socket, but the configured peer can request bounded Room review/bin metadata. Neither UID can supply SQL, Burn, a key path, or an unsigned lifecycle transition.
4. Verifies the desktop-like UID cannot open SQLite directly while it can communicate through the socket.
5. Uses ephemeral Ed25519 keys solely via `unittest.mock.patch.object` *inside the test owner's process* to replace root-pin lookup for this fixture; **no client-accessible test key injection exists**. Tests wrong issuer, wrong host, accepted signed TRASH, one-use replay refusal, fresh signed RESTORE, retained Room, nonce rows and receipts.
6. Restarts the protected socket against the original database and verifies restored state/revision. Uses SQLite's online backup API, checks a separately recovered database with `PRAGMA integrity_check` and matching Room, grants and receipts. No copy of a live WAL file.
7. Leaves the user host untouched. The temporary database, keys, socket, ACL simulation and recovered backup vanish with CI cleanup.

`tests/test-px-hospital-writer-host-refusals.py` confirms the pre-install launcher refuses caller-provided config/DB/key/unsigned options. Existing signed lifecycle, same-UID bypass-negative and separate-UID DAC tests remain.

**IMPORTANT:** The passing bypass witness against the old user-owned DB is still a **negative** security test. The protected socket positive test is not installed-host, crash/power-loss, executable provenance, logind, SELinux or consent acceptance.

## WATCH OUT FOR // Security blockers and collisions

1. **Legacy writers remain outside the service.** The existing `bin/px-hospital-store` supports Room, Patient, Doctor, Session, Event, Assignment, Chart, Checkpoint, Report, Message and suggestion writes. PX #121/#123/#125/#127/#128 and other Hospital workers modify those call paths. They must retain their authority logic and be explicitly migrated behind a supervised service. *Do not make the protected DB writable by the desktop UID to keep old CLIs working.*
2. **Connections issuer is not installed.** Application [C5-H1 #2051](https://github.com/kudokudo1/The-Post-Apollo-Project/pull/2051) provides scoped CI-only grant admission, not an independent native signer. A trusted C5/C3e host must prove real caller/executable+start identity, active seat, explicit per-Room and per-action human consent, retention/legal-hold and revocation, and protected private signing key. A desktop process that merely learns a signed grant may race to consume it; native request-to-issuer-to-writer transport and anti-confusion rules require security review.
3. **Kernel UID is necessary, not sufficient.** Any process of the configured desktop UID could request metadata or submit a stolen signed envelope. Production origin, IPC admission, rate limiting, supervised restart, socket permissions and per-operator data authorization require independently accepted implementation.
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
- [ ] Migrate **all** legacy Hospital writers behind the protected storage owner
- [ ] Installed Connections/C5 Hospital-specific issuer, per-operation human consent and trusted transport
- [ ] Verified native backup, migration, interrupted-write recovery and rollback
- [ ] Hospital UI/Trash++ native end-to-end test and independent review
- [ ] Operator-approved merge, deployment and final acceptance

## NEXT

PX owner: obtain shared Hospital writer ownership/installation contract, then migrate ordinary Room/Session/Assignment/Bed/Chart writer paths without weakening their existing assignment protections. Prepare a sealed native service account/socket/SELinux unit and backup plan with the operator and PX runtime owners. Connections/Identity owner: deliver independently authenticated native Hospital-specific signer. Hospital/Trash++ owner: keep controls locked until installed acceptance.

## DECISIONS

Maintain PX #130 as draft, unmerged. Keep schema v11 dependency #121 and concurrent ownership intact. No root config, local migration, real grant, live Room change, host installation or permanent Burn was performed.
