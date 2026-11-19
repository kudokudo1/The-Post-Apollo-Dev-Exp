"""Hospital Trash/Restore // Protected Universal Connections approval bridge.

This adds the native PREPARE -> COMMIT protocol expected by merged
Universal Connections C5-H2 without weakening PX's existing protected
Hospital Room database service.

Production MUST fail closed until a root-owned retention decision exists
for the exact Room, action, graph, and revision. No user-/UI-supplied policy,
DB, socket, signed key, operator decision or grant is accepted.

Source only. No host installation, unit, root key or production consent.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import struct
import time

import px_hospital_room_authority as authority
import px_hospital_room_lifecycle as lifecycle

REQUEST_SCHEMA = "postapollo.hospital.protected-writer-request.v1"
PREPARED_SCHEMA = "postapollo.hospital.protected-writer-prepared.v1"
RECEIPT_SCHEMA = "postapollo.hospital.protected-writer-receipt.v1"
POLICY_SCHEMA = "postapollo.hospital.room-retention-decisions.v1"
POLICY_PATH = Path("/etc/post-apollo/hospital/room-retention-decisions.json")
CONSENT_SOCKET = Path("/run/post-apollo/hospital/px-writer.sock")
ROOM = re.compile(r"[A-Za-z0-9._:/-]{1,160}\Z", re.ASCII)
NONCE = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
WRITER = re.compile(r"[A-Za-z0-9_-]{12,128}\Z", re.ASCII)
DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
MAX_FRAME = 8192
MAX_POLICY = 65536
PREPARE_SECONDS = 55
MAX_PENDING = 128
PREPARE_FIELDS = frozenset(
    ("schema", "kind", "action", "roomId", "requestNonce")
)
COMMIT_FIELDS = frozenset(
    ("schema", "kind", "action", "roomId", "requestNonce",
     "writerInstance", "signedGrant")
)
POLICY_FIELDS = frozenset(
    ("schema", "policyGeneration", "expiresAt", "decisions")
)
DECISION_FIELDS = frozenset(
    ("roomId", "action", "expectedRevision", "expectedDigest",
     "retentionApproved", "legalHold")
)


class ConsentHold(RuntimeError):
    pass


def refuse(reason):
    raise ConsentHold("HOSPITAL_CONSENT_HOLD // " + reason)


def _unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            refuse("DUPLICATE_JSON_FIELD")
        obj[key] = value
    return obj


def _nonfinite(_value):
    refuse("NONFINITE_NUMBER")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _parse(raw: bytes, *, max_bytes=MAX_FRAME):
    if type(raw) is not bytes or not 2 <= len(raw) <= max_bytes:
        refuse("FRAME_SIZE")
    try:
        decoded = json.loads(raw.decode("utf-8", "strict"),
                             object_pairs_hook=_unique,
                             parse_constant=_nonfinite)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ConsentHold("HOSPITAL_CONSENT_HOLD // INVALID_JSON") from exc
    if type(decoded) is not dict or canonical(decoded) != raw:
        refuse("NONCANONICAL_OBJECT")
    return decoded


def _id(value, expression):
    return type(value) is str and expression.fullmatch(value) is not None


def _valid_nonce(value):
    if not _id(value, NONCE):
        return False
    try:
        raw = base64.urlsafe_b64decode(value + "=")
    except (TypeError, ValueError):
        return False
    return (len(raw) == 32 and
            base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") == value)


def parse_request(raw: bytes):
    req = _parse(raw)
    if req.get("schema") != REQUEST_SCHEMA:
        refuse("WRONG_HOSPITAL_PROTOCOL")
    action = req.get("action")
    if action not in ("TRASH", "RESTORE") or not _id(req.get("roomId"), ROOM):
        refuse("INVALID_ROOM_ACTION")
    if not _valid_nonce(req.get("requestNonce")):
        refuse("INVALID_REQUEST_NONCE")
    kind = req.get("kind")
    if kind == "prepare":
        if set(req) != PREPARE_FIELDS:
            refuse("PREPARE_FIELDS")
    elif kind == "commit":
        if (set(req) != COMMIT_FIELDS or
                not _id(req.get("writerInstance"), WRITER) or
                type(req.get("signedGrant")) is not str or
                not 1 <= len(req["signedGrant"]) <= 4096):
            refuse("COMMIT_FIELDS")
    else:
        refuse("UNKNOWN_NATIVE_STEP")
    return req


def _owner_root_parents(path: Path):
    if not path.is_absolute():
        refuse("ROOT_PATH_REQUIRED")
    for parent in path.parents:
        try:
            info = parent.lstat()
        except OSError as exc:
            raise ConsentHold("HOSPITAL_CONSENT_HOLD // ROOT_POLICY_PARENT_ABSENT") from exc
        if (not stat.S_ISDIR(info.st_mode)
                or info.st_uid != 0
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            refuse("UNTRUSTED_ROOT_POLICY_DIRECTORY")


def read_retention_policy():
    """No client selected path, override, trust key, or environment fallback.

    The policy is root-managed, but readable only by the dedicated database
    service group. It must explicitly approve the exact Room + graph +
    revision for each intended action. This is separate from human Polkit
    approval, which is performed later by Universal Connections.
    """
    _owner_root_parents(POLICY_PATH)
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(str(POLICY_PATH), flags)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                    or before.st_gid != os.getegid()
                    or before.st_nlink != 1
                    or stat.S_IMODE(before.st_mode) not in (0o440, 0o640)
                    or not 10 <= before.st_size <= MAX_POLICY):
                refuse("RETENTION_POLICY_FILE_UNTRUSTED")
            raw = os.read(fd, MAX_POLICY + 1)
            after = os.fstat(fd)
            if (len(raw) != before.st_size or
                    (before.st_dev, before.st_ino, before.st_size,
                     before.st_mtime_ns, before.st_ctime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size,
                     after.st_mtime_ns, after.st_ctime_ns)):
                refuse("RETENTION_POLICY_CHANGED_DURING_READ")
        finally:
            os.close(fd)
    except OSError as exc:
        raise ConsentHold("HOSPITAL_CONSENT_HOLD // RETENTION_POLICY_UNAVAILABLE") from exc
    policy = _parse(raw, max_bytes=MAX_POLICY)
    if set(policy) != POLICY_FIELDS or policy.get("schema") != POLICY_SCHEMA:
        refuse("RETENTION_POLICY_SCHEMA")
    now = int(time.time())
    if (type(policy["policyGeneration"]) is not int
            or policy["policyGeneration"] <= 0
            or type(policy["expiresAt"]) is not int
            or not now < policy["expiresAt"] <= now + 86400
            or type(policy["decisions"]) is not list
            or len(policy["decisions"]) > 2500):
        refuse("RETENTION_POLICY_EXPIRED_OR_INVALID")
    seen = set()
    for entry in policy["decisions"]:
        if (type(entry) is not dict or set(entry) != DECISION_FIELDS
                or not _id(entry["roomId"], ROOM)
                or entry["action"] not in ("TRASH", "RESTORE")
                or type(entry["expectedRevision"]) is not int
                or not 0 <= entry["expectedRevision"] < 1_000_000_000
                or not _id(entry["expectedDigest"], DIGEST)
                or type(entry["retentionApproved"]) is not bool
                or type(entry["legalHold"]) is not bool):
            refuse("RETENTION_POLICY_DECISION_INVALID")
        identity = (entry["roomId"], entry["action"])
        if identity in seen:
            refuse("DUPLICATE_ROOM_POLICY")
        seen.add(identity)
    return policy, hashlib.sha256(raw).hexdigest()


def _allowed(policy, *, room, action, revision, digest):
    decisions = [
        row for row in policy["decisions"]
        if row["roomId"] == room and row["action"] == action
    ]
    if len(decisions) != 1:
        refuse("ROOM_RETENTION_APPROVAL_MISSING")
    d = decisions[0]
    if (d["expectedRevision"] != revision
            or d["expectedDigest"] != digest
            or d["retentionApproved"] is not True
            or d["legalHold"] is not False):
        refuse("ROOM_RETENTION_OR_LEGAL_HOLD")
    return d


@dataclass(frozen=True)
class Pending:
    nonce: str
    action: str
    room: str
    patient: str
    repository: str
    revision: int
    digest: str
    policy_hash: str
    generation: int
    expires: int
    writer_instance: str


class ConsentCoordinator:
    """Only the protected Hospital DB owner may construct this service."""

    def __init__(self, protected_writer, *, policy_loader=None, now=None,
                 grant_verifier=None):
        # No production runtime accepts custom dependencies. Injection is
        # restricted to in-process disposable tests by explicitly passing
        # a separate object. The production daemon always uses defaults.
        if not hasattr(protected_writer, "_connect"):
            refuse("PROTECTED_DB_WRITER_REQUIRED")
        self.writer = protected_writer
        self.writer_instance = base64.urlsafe_b64encode(
            secrets.token_bytes(18)).rstrip(b"=").decode("ascii")
        self.pending = {}
        self._policy_loader = policy_loader or read_retention_policy
        self._now = now or (lambda: int(time.time()))
        self._verifier = grant_verifier or self._trusted_grant

    @staticmethod
    def _trusted_grant(encoded: str):
        grant = authority._verify_bytes(
            encoded.encode("utf-8"), authority.trusted_public_key()
        )
        if grant.body["hostId"] != authority.installed_host_binding():
            refuse("SIGNED_HOST_IDENTITY_MISMATCH")
        return grant

    def _drop_expired(self):
        tick = self._now()
        for nonce, value in list(self.pending.items()):
            if value.expires <= tick:
                del self.pending[nonce]

    def _policy(self):
        result = self._policy_loader()
        if (type(result) is not tuple or len(result) != 2
                or type(result[0]) is not dict
                or type(result[1]) is not str
                or DIGEST.fullmatch(result[1]) is None):
            refuse("RETENTION_AUTHORITY_UNAVAILABLE")
        return result

    def _prepare(self, request):
        nonce = request["requestNonce"]
        self._drop_expired()
        if (nonce in self.pending or len(self.pending) >= MAX_PENDING
                or any(value.room == request["roomId"]
                       for value in self.pending.values())):
            refuse("DUPLICATE_OR_BUSY_ROOM_REVIEW")
        policy, policy_sha = self._policy()
        now = self._now()
        if not now < policy["expiresAt"]:
            refuse("RETENTION_POLICY_EXPIRED")
        with closing(self.writer._connect()) as db:
            snapshot = lifecycle.review(db, request["roomId"])
            if snapshot["blockers"]:
                refuse("ROOM_HAS_ACTIVE_OR_HELD_DEPENDENCIES")
            if (request["action"] == "TRASH" and not snapshot["canTrash"]
                    or request["action"] == "RESTORE" and not snapshot["canRestore"]):
                refuse("ROOM_NOT_ELIGIBLE_FOR_ACTION")
            _allowed(policy, room=request["roomId"], action=request["action"],
                     revision=snapshot["revision"], digest=snapshot["digest"])
            identity = db.execute(
                "SELECT r.patient_id, p.repository FROM rooms r "
                "JOIN patients p ON p.patient_id=r.patient_id "
                "WHERE r.room_id=?", (request["roomId"],)
            ).fetchone()
            if identity is None:
                refuse("ROOM_PATIENT_NOT_VERIFIED")
            patient = str(identity["patient_id"] or "")
            repository = str(identity["repository"] or "")
            if (authority.SAFE_OPERATOR.fullmatch(patient) is None
                    or not 1 <= len(repository) <= 256
                    or any(ord(ch) < 33 or ord(ch) > 126
                           for ch in repository)):
                refuse("INVALID_PROTECTED_PATIENT_IDENTITY")
        expires = min(now + PREPARE_SECONDS, policy["expiresAt"])
        if expires <= now:
            refuse("REVIEW_EXPIRED")
        pending = Pending(
            nonce=nonce, action=request["action"], room=request["roomId"],
            patient=patient, repository=repository,
            revision=snapshot["revision"], digest=snapshot["digest"],
            policy_hash=policy_sha, generation=policy["policyGeneration"],
            expires=expires, writer_instance=self.writer_instance,
        )
        self.pending[nonce] = pending
        return {
            "schema": PREPARED_SCHEMA,
            "requestNonce": nonce,
            "action": pending.action,
            "roomId": pending.room,
            "patientId": pending.patient,
            "repository": pending.repository,
            "expectedRevision": pending.revision,
            "expectedDigest": pending.digest,
            "state": snapshot["state"],
            "blockers": [],
            "canTrash": snapshot["canTrash"],
            "canRestore": snapshot["canRestore"],
            "retentionApproved": True,
            "legalHold": False,
            "policyGeneration": pending.generation,
            "writerInstance": pending.writer_instance,
            "expiresAt": expires,
        }

    def _commit(self, request):
        self._drop_expired()
        pending = self.pending.pop(request["requestNonce"], None)
        if pending is None:
            refuse("REPLAYED_OR_MISSING_PREPARE")
        if (request["writerInstance"] != self.writer_instance
                or pending.writer_instance != self.writer_instance
                or pending.room != request["roomId"]
                or pending.action != request["action"]
                or pending.expires <= self._now()):
            refuse("PREPARED_OPERATION_CHANGED_OR_EXPIRED")

        # Only the root-controlled public verifier and installed machine ID
        # can validate this signed envelope. No user-selected key or env.
        verified = self._verifier(request["signedGrant"])
        if not isinstance(verified, authority.VerifiedGrant):
            refuse("UNVERIFIED_ROOT_ISSUER")
        signed = verified.body
        if (signed["roomId"] != pending.room
                or signed["action"] != pending.action
                or signed["patientId"] != pending.patient
                or signed["repository"] != pending.repository
                or signed["expectedRevision"] != pending.revision
                or signed["expectedDigest"] != pending.digest
                or signed["retentionApproved"] is not True):
            refuse("SIGNED_ROOM_OR_GRAPH_CHANGED")

        # The callback executes INSIDE lifecycle.transition's BEGIN
        # IMMEDIATE; a revoked root-controlled policy or changed source
        # graph must not pass after interactive human consent.
        def policy_guard(source):
            policy, policy_sha = self._policy()
            if (policy_sha != pending.policy_hash
                    or policy["policyGeneration"] != pending.generation
                    or policy["expiresAt"] <= self._now()
                    or source["roomId"] != pending.room
                    or source["revision"] != pending.revision
                    or source["digest"] != pending.digest):
                refuse("PROTECTED_ROOM_OR_RETENTION_CHANGED")
            _allowed(policy, room=pending.room, action=pending.action,
                     revision=pending.revision, digest=pending.digest)

        with closing(self.writer._connect()) as db:
            result = lifecycle.transition(
                db, pending.room, pending.action, pending.revision,
                pending.digest, pending.room, authorization=verified,
                policy_guard=policy_guard,
            )
        if (result["state"] != ("TRASHED" if pending.action == "TRASH" else "ACTIVE")
                or result["revision"] != pending.revision + 1
                or result["burnAllowed"] is not False
                or result["originalPreserved"] is not True):
            refuse("SOURCE_RECEIPT_INVARIANT")
        return {
            "schema": RECEIPT_SCHEMA,
            "requestNonce": pending.nonce,
            "roomId": pending.room,
            "action": pending.action,
            "revisionAfter": result["revision"],
            "grantDigest": verified.digest,
            "state": result["state"],
            "originalPreserved": True,
            "burnAllowed": False,
        }

    def dispatch(self, raw: bytes, *, peer_uid: int):
        # The socket server obtains peer_uid strictly from Linux kernel
        # credentials. No field inside a request can nominate the issuer.
        if type(peer_uid) is not int or peer_uid != 0:
            refuse("ROOT_ISSUER_ONLY")
        req = parse_request(raw)
        return self._prepare(req) if req["kind"] == "prepare" else self._commit(req)


def kernel_peer(s: socket.socket):
    if not hasattr(socket, "SO_PEERCRED") or not hasattr(socket, "SO_PASSCRED"):
        refuse("LINUX_CREDENTIALS_UNAVAILABLE")
    raw = s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    if len(raw) != 12:
        refuse("KERNEL_PEER_TRUNCATED")
    pid, uid, gid = struct.unpack("3i", raw)
    if pid <= 1 or uid != 0 or gid < 0:
        refuse("NONROOT_CONNECTION_REFUSED")
    return pid, uid, gid


def receive_native_packet(s: socket.socket, peer):
    if not hasattr(socket, "SCM_CREDENTIALS"):
        refuse("PER_PACKET_CREDENTIALS_REQUIRED")
    s.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    data, anc, flags, _addr = s.recvmsg(
        MAX_FRAME + 1, socket.CMSG_SPACE(struct.calcsize("3i")))
    if not data or len(data) > MAX_FRAME or flags & (
            socket.MSG_TRUNC | socket.MSG_CTRUNC):
        refuse("PACKET_SIZE_OR_CONTROL_TRUNCATED")
    credentials = [
        struct.unpack("3i", value)
        for level, kind, value in anc
        if level == socket.SOL_SOCKET
        and kind == socket.SCM_CREDENTIALS
        and len(value) == struct.calcsize("3i")
    ]
    if len(credentials) != 1 or credentials[0] != peer:
        refuse("NATIVE_PACKET_SENDER_CHANGED")
    return data


def handle_connection(conn, coordinator: ConsentCoordinator):
    peer = kernel_peer(conn)
    raw = receive_native_packet(conn, peer)
    if kernel_peer(conn) != peer:
        refuse("ISSUER_PEER_CHANGED")
    body = coordinator.dispatch(raw, peer_uid=peer[1])
    response = canonical(body)
    if len(response) > MAX_FRAME:
        refuse("NATIVE_RESPONSE_TOO_LARGE")
    if conn.send(response) != len(response):
        refuse("PARTIAL_NATIVE_RESPONSE")
    return body


def verify_root_socket(path=CONSENT_SOCKET):
    # The native Socket unit creates this fixed path; the unprivileged PX
    # process NEVER binds a caller-selected socket or chmods it.
    if path != CONSENT_SOCKET:
        refuse("CONSENT_SOCKET_MUST_BE_FIXED")
    for parent in (path.parent, path.parent.parent):
        st = parent.lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0
                or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            refuse("UNTRUSTED_SYSTEMD_SOCKET_DIRECTORY")
    info = path.lstat()
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0
            or info.st_mode & stat.S_IWOTH):
        refuse("SYSTEMD_CONSENT_SOCKET_UNTRUSTED")
