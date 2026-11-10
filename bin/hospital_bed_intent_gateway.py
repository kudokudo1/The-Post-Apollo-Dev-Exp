"""Disposable-only native Hospital first-Bed intent gateway.

Actual AF_UNIX socket with kernel SO_PEERCRED, injected protected caller,
active-seat and one-use human intent guards. These production guards are not
implemented in this module: tests inject fake approvals. Does NOT give QML,
same-UID clients, or the Identity Center signed status authority.
Responds with a genuine signed receipt consumable by PX's atomic claim.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import socketserver
import sqlite3
import stat
import struct
import threading
import time
from urllib.parse import quote

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hospital_bed_claim import _fixture_gate, _repository, verify_bed
from hospital_bed_signed_intent import (
    NONCE, OPERATION, SCHEMA as INTENT_SCHEMA, SHA, SAFE_ID,
    seal_fixture, _unb64,
)

REQUEST_SCHEMA = "post-apollo.hospital.first-bed-native-request.experimental-v1"
SOCKET_NAME = "hospital-first-bed-intent-test-v1.sock"
_REQUEST_KEYS = frozenset(("schema", "action", "roomId", "repository",
                           "branch", "bedPath", "head", "nonce"))
_MAX_REQUEST = 2048
_MAX_REPLY = 4096


@dataclass(frozen=True, slots=True)
class KernelPeer:
    pid: int
    uid: int
    gid: int


def peer_credentials(conn: socket.socket):
    if not hasattr(socket, "SO_PEERCRED"):
        raise RuntimeError("Linux kernel peer identity required")
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    if len(raw) != 12:
        raise RuntimeError("Incomplete kernel peer identity")
    pid, uid, gid = struct.unpack("3i", raw)
    if pid <= 0 or uid < 0 or gid < 0:
        raise RuntimeError("Invalid kernel peer identity")
    return KernelPeer(pid, uid, gid)


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def parse_request(raw):
    if (not isinstance(raw, bytes) or len(raw) > _MAX_REQUEST
            or not raw.endswith(b"\n") or raw.count(b"\n") != 1):
        raise ValueError("Single bounded request frame required")
    try:
        command = json.loads(raw[:-1].decode("utf-8", errors="strict"),
                             object_pairs_hook=_unique_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(
                                 ValueError("Non-finite command")))
    except (UnicodeError, ValueError, TypeError) as error:
        raise ValueError("Invalid native request") from error
    if (type(command) is not dict or set(command) != _REQUEST_KEYS
            or command["schema"] != REQUEST_SCHEMA
            or command["action"] != OPERATION):
        raise ValueError("Exact Hospital Bed request required")
    for key in ("roomId", "repository", "branch", "bedPath", "head", "nonce"):
        if type(command[key]) is not str or not command[key]:
            raise ValueError("Invalid request " + key)
    if (SAFE_ID.fullmatch(command["roomId"]) is None
            or _repository(command["repository"]) != command["repository"]
            or not command["bedPath"].startswith("/")
            or "\x00" in command["bedPath"]
            or len(command["bedPath"]) > 1024
            or len(command["branch"]) > 256
            or any(ord(c) < 32 or ord(c) == 127 for c in
                   command["branch"] + command["bedPath"])
            or SHA.fullmatch(command["head"]) is None
            or NONCE.fullmatch(command["nonce"]) is None):
        raise ValueError("Invalid exact Git target")
    _unb64(command["nonce"], 32)
    return command


class _SocketServer(socketserver.ThreadingUnixStreamServer):
    allow_reuse_address = False
    daemon_threads = True
    block_on_close = False


class NativeBedIntentGateway:
    """Real native transport. Host owns security callbacks and private key."""

    def __init__(self, *, runtime_directory: Path, database: Path,
                 signer: Ed25519PrivateKey, trusted_peer,
                 active_seat, approved_intent, clock=None):
        if (not isinstance(runtime_directory, Path)
                or not runtime_directory.is_absolute()
                or not isinstance(database, Path) or not database.is_absolute()
                or not isinstance(signer, Ed25519PrivateKey)
                or not all(callable(v) for v in
                           (trusted_peer, active_seat, approved_intent))):
            raise ValueError("Protected native host, signer and approval gates required")
        self._dir = runtime_directory
        self._path = runtime_directory / SOCKET_NAME
        if len(os.fsencode(self._path)) >= 102:
            raise ValueError("Native socket path too long")
        self._db = database
        self._signer = signer
        self._trusted_peer = trusted_peer
        self._active_seat = active_seat
        self._approved_intent = approved_intent
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._seen = set()
        self._server = None
        self._thread = None
        self._inode = None
        self._closing = False
        self._started = False

    @property
    def socket_path(self):
        return self._path

    def _fixture_only(self):
        _fixture_gate()
        if self._db.resolve() != Path(os.environ["PX_HOSPITAL_DB"]).resolve():
            raise RuntimeError("Native gateway database differs from PX fixture")
        info = self._dir.lstat()
        if (not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise RuntimeError("Gateway directory must be owner-private 0700")

    def start(self):
        with self._lock:
            if self._started or self._closing:
                raise RuntimeError("Native gateway is single-use")
            self._started = True
            self._fixture_only()
            if os.path.lexists(self._path):
                raise FileExistsError("Refusing an existing command socket")
            server = _SocketServer(str(self._path), self._Handler)
            server.owner = self
            self._server = server
            try:
                self._inode = self._path.lstat().st_ino
                os.chmod(self._path, 0o600)
                info = self._path.lstat()
                if (not stat.S_ISSOCK(info.st_mode)
                        or info.st_uid != os.geteuid()
                        or stat.S_IMODE(info.st_mode) != 0o600):
                    raise RuntimeError("Native command socket must be private 0600")
                self._thread = threading.Thread(
                    target=server.serve_forever,
                    kwargs={"poll_interval": 0.02}, daemon=True,
                    name="hospital-disposable-bed-intent")
                self._thread.start()
            except Exception:
                self._server = None
                server.server_close()
                self._remove_socket()
                self._closing = True
                raise

    def _remove_socket(self):
        try:
            if self._inode is not None and self._path.lstat().st_ino == self._inode:
                self._path.unlink()
        except FileNotFoundError:
            pass
        self._inode = None

    def _checks(self, peer):
        if self._closing or peer.uid != os.geteuid():
            return False
        try:
            return (self._trusted_peer(peer) is True
                    and self._active_seat() is True)
        except Exception:
            return False

    def _room_evidence(self, request):
        db_uri = "file:" + quote(str(self._db), safe="/") + "?mode=ro"
        with sqlite3.connect(db_uri, uri=True, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            room = conn.execute("""
                SELECT r.room_id, r.patient_id, r.updated_at, r.branch,
                       r.bed_path, r.doctor_id, r.provider_id,
                       r.current_assignment_id, p.repository
                FROM rooms r
                JOIN patients p ON p.patient_id = r.patient_id
                WHERE r.room_id=?
            """, (request["roomId"],)).fetchone()
            if room is None or _repository(room["repository"]) != request["repository"]:
                raise ValueError("Room/Patient identity mismatch")
            if any(str(room[x] or "").strip() for x in
                   ("branch", "bed_path", "doctor_id", "provider_id")):
                raise ValueError("Room already configured or staffed")
            if conn.execute("SELECT 1 FROM sessions WHERE room_id=? LIMIT 1",
                            (request["roomId"],)).fetchone():
                raise ValueError("Room has Session history")
            assignment = str(room["current_assignment_id"] or "").strip()
            if assignment:
                linked = conn.execute(
                    "SELECT room_id, patient_id, status FROM assignments"
                    " WHERE assignment_id=?", (assignment,)
                ).fetchone()
                if (linked is None or linked["room_id"] != request["roomId"]
                        or linked["patient_id"] != room["patient_id"]
                        or linked["status"] != "ACTIVE"):
                    raise ValueError("Room Assignment is not ACTIVE")
            patient_id = str(room["patient_id"] or "")
            version = str(room["updated_at"] or "")
        git = verify_bed(request["bedPath"], request["repository"], request["branch"])
        if git["head"] != request["head"]:
            raise ValueError("Git HEAD changed since operator review")
        return patient_id, version, git

    def _prepare(self, peer, request):
        with self._lock:
            if not self._checks(peer) or request["nonce"] in self._seen:
                return None
            self._seen.add(request["nonce"])
            try:
                patient_id, version, git = self._room_evidence(request)
                if not self._checks(peer):
                    return None
                # Only the host's trusted callback selects the operator ID.
                # Client JSON cannot supply consent, role, keys or identity.
                target = {
                    "roomId": request["roomId"],
                    "patientId": patient_id,
                    "repository": request["repository"],
                    "branch": request["branch"],
                    "bedPath": git["path"],
                    "head": git["head"],
                    "roomUpdatedAt": version,
                    "nonce": request["nonce"],
                }
                operator = self._approved_intent(peer, OPERATION, dict(target))
                if type(operator) is not str or SAFE_ID.fullmatch(operator) is None:
                    return None
                if not self._checks(peer):
                    return None
                now = int(self._clock())
                body = dict(target, schema=INTENT_SCHEMA, operation=OPERATION,
                            operatorId=operator, issuedAt=now, expiresAt=now + 60)
                signed = seal_fixture(self._signer, body)
                if not self._checks(peer) or len(signed) > _MAX_REPLY:
                    return None
                return signed + b"\n"
            except (ValueError, RuntimeError, OSError, sqlite3.Error):
                return None

    class _Handler(socketserver.BaseRequestHandler):
        def handle(self):
            sock = self.request
            try:
                sock.settimeout(1.5)
                peer = peer_credentials(sock)
                raw = bytearray()
                while len(raw) <= _MAX_REQUEST and b"\n" not in raw:
                    data = sock.recv(_MAX_REQUEST + 1 - len(raw))
                    if not data:
                        break
                    raw.extend(data)
                command = parse_request(bytes(raw))
                signed = self.server.owner._prepare(peer, command)
                sock.sendall(signed if signed is not None
                             else b'{"status":"DENIED"}\n')
            except (OSError, TimeoutError, ValueError, RuntimeError):
                try:
                    sock.sendall(b'{"status":"DENIED"}\n')
                except OSError:
                    pass

    def close(self):
        with self._lock:
            self._closing = True
            server, thread = self._server, self._thread
            self._server = None
            self._thread = None
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
            server.server_close()
        self._remove_socket()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
