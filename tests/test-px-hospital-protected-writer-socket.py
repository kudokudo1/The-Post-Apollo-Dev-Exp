#!/usr/bin/env python3
"""Protected PX Room RPC source integration with real Linux SO_PEERCRED.

Runs ONLY on disposable Linux CI. This is a separate-UID socket/SQLite test,
not a systemd install, root-pinned real key, human consent or legal-hold
acceptance. The test alone injects an ephemeral signing public key in-process
via unittest.mock.patch: the production writer offers no such client option.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "bin" / "px-hospital-store"
sys.path.insert(0, str(ROOT / "bin"))
import px_hospital_room_authority as auth
from px_hospital_room_writer import ProtectedRoomWriter, SCHEMA, WriterHold
from px_hospital_protected_client import (
    prepare_argv, send_command, pinned_socket_contract, MAX_BODY,
)

CLIENT = r"""
import json
from pathlib import Path
import socket
import sys

path = Path(sys.argv[1])
frame = sys.stdin.buffer.read()
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
    sock.settimeout(3)
    sock.connect(str(path))
    sock.sendall(frame)
    sock.shutdown(socket.SHUT_WR)
    parts = bytearray()
    while True:
        chunk = sock.recv(16384)
        if not chunk: break
        parts.extend(chunk)
        if len(parts) > 1048576: raise AssertionError("SERVER_REPLY_UNBOUNDED")
print(parts.decode("utf-8", "strict"), end="")
"""
RUNTIME_CLIENT = r"""
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from px_hospital_protected_client import prepare_argv, send_command
argv, _as_json = prepare_argv(
    sys.argv[4:], body_data=b"streamed fixture body"
)
reply = send_command(Path(sys.argv[2]), int(sys.argv[3]), argv)
print(json.dumps(reply))
"""
DIRECT = r"""
from pathlib import Path
import sqlite3
import sys
db = Path(sys.argv[1])
for label, attempt in (
    ("db_read", lambda: db.open("rb")),
    ("db_modify", lambda: db.open("r+b")),
    ("sql_read", lambda: sqlite3.connect("file:" + str(db) + "?mode=ro", uri=True)),
    ("sql_write", lambda: sqlite3.connect("file:" + str(db) + "?mode=rw", uri=True)),
):
    try:
        handle = attempt()
    except sqlite3.OperationalError as exc:
        if "unable to open database file" not in str(exc).lower():
            raise
    except OSError:
        continue
    else:
        handle.close()
        raise AssertionError("UNTRUSTED_SQL_DIRECT_ACCESS: " + label)
print("SEPARATE_UID_DIRECT_SQL_DENIED")
"""


def px(env, *args):
    run = subprocess.run(
        [sys.executable, str(STORE), *args, "--json"],
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert run.returncode == 0, (args, run.stdout, run.stderr)
    return json.loads(run.stdout)


def send(path, frame, uid_user=None, *, exact_bytes=False):
    raw = frame if exact_bytes else (
        json.dumps(frame, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    )
    cmd = [sys.executable, "-c", CLIENT, str(path)]
    if uid_user is not None:
        cmd = ["sudo", "-n", "-u", uid_user, *cmd]
    result = subprocess.run(
        cmd, input=raw, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, (result.returncode, result.stderr)
    return json.loads(result.stdout)


def grant(private, review, action, *, host="native-host-fixture",
          nonce=None, approval=None):
    now = int(time.time())
    body = {
        "schema": auth.SCHEMA, "audience": auth.AUDIENCE,
        "action": action, "roomId": review["roomId"],
        "patientId": "fixture-p", "repository": "fixture/repo",
        "expectedRevision": review["revision"],
        "expectedDigest": review["digest"],
        "operatorId": "operator-fixture",
        "approvalId": approval or "approval-" + secrets.token_hex(12),
        "seatId": "native-seat-fixture", "hostId": host,
        "retentionApproved": True,
        "nonce": nonce or auth._b64(os.urandom(32)),
        "issuedAt": now, "expiresAt": now + 40,
    }
    signed = auth._b64(private.sign(auth.DOMAIN + auth.canonical(body)))
    return auth.canonical({"body": body, "signature": signed}).decode("ascii")


def request(action, **values):
    return dict(schema=SCHEMA, operation=action, **values)


def mutate(action, review, signed):
    return request(
        action, roomId=review["roomId"], expectedRevision=review["revision"],
        expectedDigest=review["digest"], confirmRoomId=review["roomId"],
        signedEnvelope=signed,
    )


def main():
    assert sys.platform == "linux" and os.geteuid() not in (0, 65534)
    assert shutil.which("sudo")
    peer = pwd.getpwnam("nobody")
    runtime_peer = pwd.getpwnam("daemon")
    assert len({peer.pw_uid, runtime_peer.pw_uid, os.geteuid(), 0}) == 4

    args, json_mode = prepare_argv([
        "message-append", "--room-id", "room1",
        "--author-role", "DOCTOR", "--direction", "outgoing",
        "--body-stdin", "--json",
    ], body_data=b"safe-stream-body")
    assert json_mode and args[-2:] == ["--body", "safe-stream-body"]
    for broken in (b"\xff", b"x" * (MAX_BODY + 1)):
        try:
            prepare_argv([
                "message-append", "--room-id", "room1",
                "--author-role", "DOCTOR", "--direction", "outgoing",
                "--body-stdin",
            ], body_data=broken)
        except WriterHold:
            pass
        else:
            raise AssertionError("UNSAFE_STDIN_BODY_ACCEPTED")
    try:
        pinned_socket_contract()
    except (WriterHold, OSError):
        # The temporary CI runner has no installed root-owned native
        # config. This is expected and MUST NOT create one.
        pass
    else:
        raise AssertionError("UNEXPECTED_CI_PRODUCTION_CONFIG")

    with tempfile.TemporaryDirectory(prefix="px-hospital-writer-socket-") as tmp:
        parent = Path(tmp)
        parent.chmod(0o711)
        private = parent / "db"
        private.mkdir(mode=0o700)
        runtime = parent / "socket"
        runtime.mkdir(mode=0o711)
        # GitHub's runner checkout is not traversable by the separate
        # daemon UID. Copy this exact commit's client code into a separate
        # non-writable-by-daemon fixture directory, never the real host.
        client_code = parent / "read-only-runtime-source"
        client_code.mkdir(mode=0o755)
        for name in (
            "px_hospital_protected_client.py",
            "px_hospital_protected_store_bridge.py",
            "px_hospital_room_writer.py",
            "px_hospital_room_lifecycle.py",
            "px_hospital_room_authority.py",
            "px-hospital-store",
        ):
            dest = client_code / name
            shutil.copyfile(ROOT / "bin" / name, dest)
            dest.chmod(0o644)
        database = private / "hospital.db"
        env = dict(os.environ, PX_HOSPITAL_DATA_DIR=str(private))
        env.pop("PX_HOSPITAL_DB", None)

        # Migrate/create data only under owner control, before writer starts.
        old_umask = os.umask(0o077)
        try:
            assert px(env, "status")["schema_version"] == 12
            room = "socket-fixture-room"
            px(
                env, "room-bind", room, "--repository", "fixture/repo",
                "--patient-id", "fixture-p",
            )
        finally:
            os.umask(old_umask)

        with ProtectedRoomWriter(
            state_directory=private, socket_directory=runtime,
            client_uid=peer.pw_uid,
            runtime_uid=runtime_peer.pw_uid,
        ) as writer:
            assert writer.socket_path.stat().st_mode & 0o777 == 0o600
            # Only the disposable runner opens access for test's foreign UID.
            # The real host service must use a reviewed socket ACL/group.
            writer.socket_path.chmod(0o666)
            disallowed = send(
                writer.socket_path, request("review", roomId=room),
            )
            assert disallowed == {"ok": False, "error": "DENIED"}

            direct = subprocess.run(
                ["sudo", "-n", "-u", peer.pw_name,
                 sys.executable, "-c", DIRECT, str(database)],
                capture_output=True, text=True, timeout=10,
            )
            assert direct.returncode == 0, (direct.stdout, direct.stderr)
            assert "SEPARATE_UID_DIRECT_SQL_DENIED" in direct.stdout

            # A desktop UID is not the trusted PX runtime service identity.
            assert send(writer.socket_path, request(
                "store-command", argv=["room", room],
            ), peer.pw_name) == {"ok": False, "error": "DENIED"}
            assert send(writer.socket_path, request(
                "store-command", argv=["room", room],
            ), runtime_peer.pw_name)["data"]["id"] == room
            for blocked_argv in (
                ["init"],
                ["room-lifecycle-trash", room],
                ["room-lifecycle-restore", room],
                ["sql", "UPDATE rooms SET branch='bad'"],
                ["message-append", "--room-id", room,
                 "--author-role", "DOCTOR", "--direction", "outgoing",
                 "--body-stdin"],
                ["room-name-set", room, "--name", "test",
                 "--signed-authorization-file", "/tmp/bogus"],
            ):
                assert send(writer.socket_path, request(
                    "store-command", argv=blocked_argv,
                ), runtime_peer.pw_name) == {
                    "ok": False, "error": "DENIED",
                }
            assert send(writer.socket_path, request(
                "store-command", argv=["room-name-set", room,
                                      "--name", "Protected fixture Room"],
            ), runtime_peer.pw_name)["ok"]
            assert send(writer.socket_path, request(
                "store-command", argv=["doctor-put", "fixture-doctor",
                                      "--name", "Fixture Doctor"],
            ), runtime_peer.pw_name)["ok"]
            # Preserve the pre-existing reset-to-ID semantics in the
            # migrated CLI. Empty *values* are valid even though an empty
            # command token is not.
            for argv in (
                ["doctor-name-set", "fixture-doctor", "--name", ""],
                ["room-name-set", room, "--name", ""],
                ["room-name-set", room, "--name", "Protected fixture Room"],
            ):
                assert send(writer.socket_path, request(
                    "store-command", argv=argv,
                ), runtime_peer.pw_name)["ok"], argv

            review_call = request("review", roomId=room)
            reviewed = send(writer.socket_path, review_call, peer.pw_name)
            assert reviewed["ok"]
            snap = reviewed["data"]
            assert snap["state"] == "ACTIVE" and snap["revision"] == 0
            assert snap["operatorAuthenticated"] is False
            assert snap["requiresOwnerReview"] is True
            assert send(writer.socket_path, request("bin"), peer.pw_name) == {
                "ok": True, "data": [],
            }

            # No generic SQL, Burn, caller-selected key, DB path, duplicate
            # frame keys, or signed-envelope omission can mutate Room state.
            blocked = [
                request("sql", sql="UPDATE rooms SET team='bad'"),
                request("burn", roomId=room),
                dict(review_call, database=str(database)),
                request("review", roomId=room, publicKey="FAKE"),
                request("trash", roomId=room),
            ]
            for bad in blocked:
                assert send(writer.socket_path, bad, peer.pw_name) == {
                    "ok": False, "error": "DENIED",
                }
            duplicate = (
                b'{"schema":"' + SCHEMA.encode() + b'","schema":"' +
                SCHEMA.encode() + b'","operation":"bin"}\n'
            )
            assert send(
                writer.socket_path, duplicate, peer.pw_name,
                exact_bytes=True,
            ) == {"ok": False, "error": "DENIED"}

            fake = mutate("trash", snap, "{}")
            assert send(writer.socket_path, fake, peer.pw_name) == {
                "ok": False, "error": "DENIED",
            }
            with sqlite3.connect(database) as db:
                assert db.execute(
                    "SELECT COUNT(*) FROM room_lifecycle"
                ).fetchone()[0] == 0

            # This test-only monkeypatch runs IN the owner process, not via
            # the Unix socket. No production signer or override is created.
            private_key = Ed25519PrivateKey.generate()
            other_key = Ed25519PrivateKey.generate()
            with patch.object(
                auth, "trusted_public_key",
                return_value=private_key.public_key(),
            ), patch.object(
                auth, "installed_host_binding",
                return_value="native-host-fixture",
            ):
                wrong_key = grant(other_key, snap, "TRASH")
                assert send(
                    writer.socket_path, mutate("trash", snap, wrong_key),
                    peer.pw_name,
                )["ok"] is False
                wrong_host = grant(private_key, snap, "TRASH",
                                   host="native-host-other")
                assert send(
                    writer.socket_path,
                    mutate("trash", snap, wrong_host), peer.pw_name,
                )["ok"] is False
                signed = grant(private_key, snap, "TRASH")
                accepted = send(
                    writer.socket_path,
                    mutate("trash", snap, signed), peer.pw_name,
                )
                assert accepted["ok"], accepted
                assert accepted["data"]["state"] == "TRASHED"
                assert accepted["data"]["receiptRecorded"] is True
                assert accepted["data"]["operatorAuthenticated"] is False

                # One-use grant and state revision, never reusable.
                assert not send(
                    writer.socket_path,
                    mutate("trash", snap, signed), peer.pw_name,
                )["ok"]
                bin_result = send(
                    writer.socket_path, request("bin"), peer.pw_name,
                )
                assert bin_result["ok"] and len(bin_result["data"]) == 1
                assert bin_result["data"][0]["roomId"] == room
                assert bin_result["data"][0]["state"] == "TRASHED"
                # The PX runtime route must still obey v12 SQLite hold
                # triggers; moving a writer must NOT bypass trashed state.
                denied_trashed_write = send(
                    writer.socket_path, request("store-command", argv=[
                        "message-append", "--room-id", room,
                        "--author-role", "DOCTOR", "--direction", "outgoing",
                        "--body", "must not appear in trashed Room",
                    ]), runtime_peer.pw_name,
                )
                assert denied_trashed_write == {
                    "ok": False, "error": "DENIED",
                }
                restored_review = send(
                    writer.socket_path, review_call, peer.pw_name,
                )["data"]
                assert restored_review["canRestore"]
                restored = send(
                    writer.socket_path,
                    mutate("restore", restored_review, grant(
                        private_key, restored_review, "RESTORE",
                    )), peer.pw_name,
                )
                assert restored["ok"] and restored["data"]["state"] == "ACTIVE"
                assert send(
                    writer.socket_path, request("bin"), peer.pw_name,
                )["data"] == []

            # Existing store semantics are now available to the isolated
            # PX runtime identity, never to the ordinary desktop UID.
            runtime_writes = [
                ["session-put", "fixture-session", "--room-id", room],
                ["event-append", "--session-id", "fixture-session",
                 "--event-type", "TEST", "--payload", "{}"],
                ["message-append", "--room-id", room,
                 "--author-role", "DOCTOR", "--direction", "outgoing",
                 "--body", "fixture message"],
                ["checkpoint-append", "--room-id", room,
                 "--body", "fixture checkpoint"],
                ["room-report-append", "--room-id", room,
                 "--body", "fixture report"],
                ["assignment-create", "--room-id", room,
                 "--goal", "synthetic trusted runtime migration"],
                ["chart-entry-add", "--scope", "ROOM", "--room-id", room,
                 "--title", "Synthetic chart", "--body", "fixture note"],
            ]
            for argv in runtime_writes:
                result = send(writer.socket_path, request(
                    "store-command", argv=argv,
                ), runtime_peer.pw_name)
                assert result["ok"], (argv, result)
            runtime_reads = [
                ["session", "fixture-session"],
                ["sessions", "--room-id", room],
                ["events", "fixture-session"],
                ["messages", room],
                ["checkpoints", room],
                ["room-reports", room],
                ["assignments", "--room-id", room],
                ["chart-entries", "--scope", "ROOM", "--room-id", room],
            ]
            for argv in runtime_reads:
                result = send(writer.socket_path, request(
                    "store-command", argv=argv,
                ), runtime_peer.pw_name)
                assert result["ok"] and result["data"], (argv, result)

            # Owner sees both consumed approvals/receipts. No physical
            # deletion was attempted.
            with sqlite3.connect(database) as db:
                assert db.execute(
                    "SELECT COUNT(*) FROM room_lifecycle_receipts"
                ).fetchone()[0] == 2
                assert db.execute(
                    "SELECT COUNT(*) FROM room_lifecycle_authorizations"
                ).fetchone()[0] == 2
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert database.exists()

            # The protected client must reject a world-writable socket
            # instead of trusting a caller-supplied address.
            try:
                send_command(writer.socket_path, os.geteuid(),
                             ["room", room])
            except WriterHold as exc:
                assert "SOCKET_OWNER_OR_PERMISSIONS_REFUSED" in str(exc)
            else:
                raise AssertionError("WORLD_WRITABLE_SOCKET_ACCEPTED")

            # A disposable CI-only group handoff models the approved
            # runtime socket ACL; no host daemon account is created.
            permission = subprocess.run(
                ["sudo", "-n", "chgrp", str(runtime_peer.pw_gid),
                 str(writer.socket_path)],
                capture_output=True, text=True, timeout=10,
            )
            assert permission.returncode == 0, permission.stderr
            writer.socket_path.chmod(0o660)
            native_client = subprocess.run([
                "sudo", "-n", "-u", runtime_peer.pw_name, sys.executable,
                "-c", RUNTIME_CLIENT, str(client_code),
                str(writer.socket_path), str(os.geteuid()), "room", room,
            ], capture_output=True, text=True, timeout=10)
            assert native_client.returncode == 0, (
                native_client.stdout, native_client.stderr
            )
            assert json.loads(native_client.stdout)["id"] == room
            streamed = subprocess.run([
                "sudo", "-n", "-u", runtime_peer.pw_name, sys.executable,
                "-c", RUNTIME_CLIENT, str(client_code),
                str(writer.socket_path), str(os.geteuid()),
                "message-append", "--room-id", room,
                "--author-role", "DOCTOR", "--direction", "outgoing",
                "--body-stdin",
            ], capture_output=True, text=True, timeout=10)
            assert streamed.returncode == 0, (
                streamed.stdout, streamed.stderr
            )
            assert int(json.loads(streamed.stdout)["id"]) > 0
        assert not writer.socket_path.exists()

        # Restart the service on the SAME owner-controlled DB. No signed
        # grant is injected for this read-only recovery check.
        with ProtectedRoomWriter(
            state_directory=private, socket_directory=runtime,
            client_uid=peer.pw_uid,
            runtime_uid=runtime_peer.pw_uid,
        ) as restarted:
            restarted.socket_path.chmod(0o666)
            after_restart = send(
                restarted.socket_path,
                request("review", roomId=room), peer.pw_name,
            )
            assert after_restart["ok"] and after_restart["data"]["state"] == "ACTIVE"
            assert after_restart["data"]["revision"] == 2

        # Backup through SQLite's online backup API, not filesystem copying
        # a live WAL. Verify a *separate* recovered DB still has the exact
        # Room and both durable grant receipts after service restart.
        recovered = private / "restored-from-online-backup.db"
        old_umask = os.umask(0o077)
        try:
            with sqlite3.connect(database) as source:
                with sqlite3.connect(recovered) as target:
                    source.backup(target)
                    assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                    assert target.execute(
                        "SELECT state, revision FROM room_lifecycle WHERE room_id=?",
                        (room,),
                    ).fetchone() == ("ACTIVE", 2)
                    assert target.execute(
                        "SELECT COUNT(*) FROM room_lifecycle_receipts WHERE room_id=?",
                        (room,),
                    ).fetchone()[0] == 2
                    assert target.execute(
                        "SELECT COUNT(*) FROM room_lifecycle_authorizations WHERE room_id=?",
                        (room,),
                    ).fetchone()[0] == 2
                    assert target.execute(
                        "SELECT COUNT(*) FROM rooms WHERE room_id=?", (room,),
                    ).fetchone()[0] == 1
        finally:
            os.umask(old_umask)
        assert recovered.stat().st_mode & 0o777 == 0o600

    print(
        "PX PROTECTED ROOM SOCKET PASS // separate-UID peer, direct SQLite "
        "denial, pinned signed TRASH/RESTORE atomic fixture, replay, "
        "Burn/raw-SQL denial, distinct runtime UID legacy writers/reads, "
        "trashed-Room trigger enforcement, pinned-client peer verification "
        "and bounded stdin routing, service restart and WAL-aware backup "
        "recovery, no production issuer or native install"
    )


if __name__ == "__main__":
    main()
