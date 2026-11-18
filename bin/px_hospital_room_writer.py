"""PX Hospital protected Room writer, pre-install native service prototype.

This is an actual AF_UNIX, SO_PEERCRED-checked RPC to a separately owned
SQLite database, but NOT an installed or activated production service.
Client peers cannot select a database, key, SQL command or grant verifier.
Read-only Room review and bin are exposed; the ONLY mutations are the
existing signed/atomic Room TRASH and RESTORE transitions.

Other Hospital store writers remain unmigrated. No service unit, sudo,
setuid, operator approval, signing key, environment-selected trust anchor
or host storage migration is provided by this module.
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import socket
import socketserver
import sqlite3
import stat
import struct
import threading
from urllib.parse import quote

import px_hospital_room_authority as authority
import px_hospital_room_lifecycle as lifecycle

SCHEMA = "post-apollo.hospital.protected-room-writer.v1"
_MAX_REQUEST = 8192
_MAX_RESPONSE = 1048576
_ALLOWED_READ = frozenset(("review", "bin"))
_ALLOWED_WRITE = frozenset(("trash", "restore"))


class WriterHold(RuntimeError):
    pass


def _pairs_unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise WriterHold("DUPLICATE_FIELD")
        obj[key] = value
    return obj


def _invalid_constant(value):
    raise WriterHold("NONFINITE_FIELD")


def parse_request(frame: bytes):
    if (type(frame) is not bytes or not 2 <= len(frame) <= _MAX_REQUEST
            or not frame.endswith(b"\n") or frame.count(b"\n") != 1):
        raise WriterHold("BOUNDED_SINGLE_FRAME_REQUIRED")
    try:
        request = json.loads(
            frame[:-1].decode("utf-8", "strict"),
            object_pairs_hook=_pairs_unique,
            parse_constant=_invalid_constant,
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise WriterHold("INVALID_JSON") from exc
    if type(request) is not dict or request.get("schema") != SCHEMA:
        raise WriterHold("SCHEMA_REFUSED")
    action = request.get("operation")
    if action == "review":
        expected = {"schema", "operation", "roomId"}
    elif action == "bin":
        expected = {"schema", "operation"}
    elif action in _ALLOWED_WRITE:
        expected = {
            "schema", "operation", "roomId", "expectedRevision",
            "expectedDigest", "confirmRoomId", "signedEnvelope",
        }
    else:
        raise WriterHold("UNSUPPORTED_OPERATION")
    if set(request) != expected:
        raise WriterHold("EXACT_FIELDS_REQUIRED")
    if action != "bin":
        lifecycle._identity(request["roomId"])
    if action in _ALLOWED_WRITE:
        if (type(request["expectedRevision"]) is not int
                or not 0 <= request["expectedRevision"] < 1_000_000_000
                or type(request["expectedDigest"]) is not str
                or lifecycle.DIGEST_PATTERN.fullmatch(
                    request["expectedDigest"]) is None
                or request["confirmRoomId"] != request["roomId"]
                or type(request["signedEnvelope"]) is not str
                or not 1 <= len(request["signedEnvelope"]) <= 4096):
            raise WriterHold("INVALID_TRANSITION_FRAME")
    return request


def kernel_peer(sock: socket.socket):
    if not hasattr(socket, "SO_PEERCRED"):
        raise WriterHold("LINUX_PEER_CREDENTIALS_REQUIRED")
    raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    if len(raw) != 12:
        raise WriterHold("PEER_CREDENTIALS_TRUNCATED")
    pid, uid, gid = struct.unpack("3i", raw)
    if pid <= 0 or uid < 0 or gid < 0:
        raise WriterHold("INVALID_PEER")
    return pid, uid, gid


def _private_directory(path: Path, expected_mode: int):
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != expected_mode):
        raise WriterHold("WRITER_DIRECTORY_NOT_PRIVATE")


class ProtectedRoomWriter:
    """One-process protected SQLite owner with a deliberately narrow RPC.

    The trusted native service manager must choose owner-only paths and the
    desktop UID; a client request never supplies or changes those settings.
    The socket is 0600 by default. Installers must separately approve a
    restricted per-client ACL/owner-owned socket activation policy.
    """

    def __init__(self, *, state_directory: Path, socket_directory: Path,
                 client_uid: int):
        if (os.name != "posix" or not hasattr(socket, "SO_PEERCRED")
                or os.geteuid() == 0 or type(client_uid) is not int
                or client_uid in (0, os.geteuid())
                or not isinstance(state_directory, Path)
                or not isinstance(socket_directory, Path)
                or not state_directory.is_absolute()
                or not socket_directory.is_absolute()
                or state_directory == socket_directory):
            raise WriterHold("DISTINCT_NATIVE_OWNER_REQUIRED")
        self.state_directory = state_directory
        self.database = state_directory / "hospital.db"
        self.socket_directory = socket_directory
        self.socket_path = socket_directory / "hospital-room-writer-v1.sock"
        self.client_uid = client_uid
        if len(os.fsencode(self.socket_path)) >= 100:
            raise WriterHold("UNIX_SOCKET_PATH_TOO_LONG")
        self._server = None
        self._thread = None
        self._socket_inode = None

    def _check_storage(self):
        _private_directory(self.state_directory, 0o700)
        _private_directory(self.socket_directory, 0o711)
        info = self.database.lstat()
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o177):
            raise WriterHold("PROTECTED_DATABASE_NOT_OWNER_ONLY")
        # No migrations or implicit database creation via RPC. The actual
        # source owner must verify backup/recovery before starting the host.
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.database) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                side = sidecar.lstat()
                if (not stat.S_ISREG(side.st_mode)
                        or side.st_uid != os.geteuid()
                        or stat.S_IMODE(side.st_mode) & 0o177):
                    raise WriterHold("PROTECTED_SQLITE_SIDECAR_UNSAFE")

    def _connect(self):
        self._check_storage()
        url = "file:" + quote(str(self.database), safe="/") + "?mode=rw"
        connection = sqlite3.connect(
            url, uri=True, timeout=3, isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=3000")
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        if row is None or row["value"] != "12":
            connection.close()
            raise WriterHold("MIGRATION_AND_BACKUP_NOT_ACCEPTED")
        return connection

    @staticmethod
    def _verify_envelope(raw: str):
        # The only trusted issuer is pinned by PX authority's installed
        # root-owned KEY_PATH. No caller-selected key or test/CI env flag.
        verified = authority._verify_bytes(
            raw.encode("utf-8"), authority.trusted_public_key(),
        )
        if verified.body["hostId"] != authority.installed_host_binding():
            raise WriterHold("SIGNED_HOST_MISMATCH")
        return verified

    def process(self, request):
        action = request["operation"]
        with closing(self._connect()) as db:
            if action == "review":
                return lifecycle.review(db, request["roomId"])
            if action == "bin":
                return lifecycle.trashed_rooms(db)
            if action in _ALLOWED_WRITE:
                verified = self._verify_envelope(request["signedEnvelope"])
                return lifecycle.transition(
                    db, request["roomId"], action.upper(),
                    request["expectedRevision"], request["expectedDigest"],
                    request["confirmRoomId"], authorization=verified,
                )
            raise WriterHold("UNSUPPORTED_OPERATION")

    class _Handler(socketserver.BaseRequestHandler):
        def handle(self):
            conn = self.request
            try:
                conn.settimeout(1.5)
                _pid, uid, _gid = kernel_peer(conn)
                if uid != self.server.owner.client_uid:
                    raise WriterHold("UNTRUSTED_PEER")
                raw = bytearray()
                while len(raw) <= _MAX_REQUEST:
                    packet = conn.recv(min(2048, _MAX_REQUEST + 1 - len(raw)))
                    if not packet:
                        break
                    raw.extend(packet)
                request = parse_request(bytes(raw))
                data = self.server.owner.process(request)
                result = {"ok": True, "data": data}
                wire = json.dumps(
                    result, separators=(",", ":"), ensure_ascii=True,
                    allow_nan=False,
                ).encode("ascii") + b"\n"
                if len(wire) > _MAX_RESPONSE:
                    raise WriterHold("RESPONSE_TOO_LARGE")
            except (OSError, ValueError, TypeError, RuntimeError,
                    sqlite3.Error):
                # Do not disclose DB paths, historical Room contents or
                # pinned-issuer failure internals to a failed caller.
                wire = b'{"ok":false,"error":"DENIED"}\n'
            try:
                conn.sendall(wire)
            except OSError:
                pass

    def start(self):
        if self._server is not None:
            raise WriterHold("ALREADY_STARTED")
        self._check_storage()
        with closing(self._connect()) as connection:
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        if os.path.lexists(self.socket_path):
            raise WriterHold("EXISTING_SOCKET_REFUSED")
        old_umask = os.umask(0o077)
        try:
            server = socketserver.UnixStreamServer(
                str(self.socket_path), self._Handler,
            )
        finally:
            os.umask(old_umask)
        try:
            server.owner = self
            os.chmod(self.socket_path, 0o600)
            info = self.socket_path.lstat()
            if (not stat.S_ISSOCK(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise WriterHold("SOCKET_NOT_OWNER_CONTROLLED")
            self._socket_inode = info.st_ino
            self._server = server
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.02},
                daemon=True,
                name="px-hospital-protected-room-writer",
            )
            self._thread = thread
            thread.start()
        except BaseException:
            server.server_close()
            if self._socket_inode == self.socket_path.lstat().st_ino:
                self.socket_path.unlink()
            self._socket_inode = None
            self._server = None
            raise

    def close(self):
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
            if thread is not None:
                thread.join(timeout=3)
        try:
            if (self._socket_inode is not None
                    and self.socket_path.lstat().st_ino == self._socket_inode):
                self.socket_path.unlink()
        except FileNotFoundError:
            pass
        self._socket_inode = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
