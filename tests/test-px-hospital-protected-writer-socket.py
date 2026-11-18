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
from px_hospital_room_writer import ProtectedRoomWriter, SCHEMA, parse_request

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
    assert peer.pw_uid != os.geteuid()

    with tempfile.TemporaryDirectory(prefix="px-hospital-writer-socket-") as tmp:
        parent = Path(tmp)
        parent.chmod(0o711)
        private = parent / "db"
        private.mkdir(mode=0o700)
        runtime = parent / "socket"
        runtime.mkdir(mode=0o711)
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
        assert not writer.socket_path.exists()

        # Restart the service on the SAME owner-controlled DB. No signed
        # grant is injected for this read-only recovery check.
        with ProtectedRoomWriter(
            state_directory=private, socket_directory=runtime,
            client_uid=peer.pw_uid,
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
        "Burn/raw-SQL denial, service restart and WAL-aware backup recovery, "
        "no production issuer or native install"
    )


if __name__ == "__main__":
    main()
