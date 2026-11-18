"""Hospital Room v12 // source-side Ed25519 authorization verification.

The trusted signing *issuer* is deliberately external to PX and QML. A
verified signature, scoped Room/action/graph, bounded lifetime, and atomic
one-use nonce are all mandatory for any Room lifecycle mutation.

No private key or signing command exists here. The operator's protected
native host, active seat, retention policy and consent have NOT been
implemented by this module; a signature proves only control of the pinned
issuer key. Without the separately installed root-owned trust anchor,
production fails closed. No environment-based key override is supported.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN = b"post-apollo.hospital.room-lifecycle-grant.v1\x00"
SCHEMA = "post-apollo.hospital.room-lifecycle-grant.v1"
AUDIENCE = "px-hospital-room-lifecycle-v12"
KEY_PATH = "/etc/post-apollo/hospital/room-lifecycle-issuer.pub"
BODY_FIELDS = frozenset((
    "schema", "audience", "action", "roomId", "patientId",
    "repository", "expectedRevision", "expectedDigest", "operatorId",
    "approvalId", "seatId", "hostId", "retentionApproved",
    "nonce", "issuedAt", "expiresAt",
))
SAFE_ROOM = re.compile(r"[A-Za-z0-9._:/-]{1,160}\Z", re.ASCII)
SAFE_OPERATOR = re.compile(r"[A-Za-z0-9_.:@/-]{1,96}\Z", re.ASCII)
SAFE_APPROVAL = re.compile(r"[A-Za-z0-9_-]{12,128}\Z", re.ASCII)
HEX64 = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
B64NONCE = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
B64SIGNATURE = re.compile(r"[A-Za-z0-9_-]{86}\Z", re.ASCII)

class GrantRefused(RuntimeError):
    pass

def _stop(reason):
    raise GrantRefused("HOSPITAL ROOM GRANT HOLD // " + reason)

def _unique_pairs(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            _stop("DUPLICATE_JSON_FIELD")
        result[name] = value
    return result

def _nonfinite(_value):
    _stop("NONFINITE_JSON_REFUSED")

def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")

def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

def _unb64(encoded, length):
    if type(encoded) is not str:
        _stop("ENCODING_INVALID")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, TypeError) as exc:
        raise GrantRefused("HOSPITAL ROOM GRANT HOLD // ENCODING_INVALID") from exc
    if len(raw) != length or _b64(raw) != encoded:
        _stop("NONCANONICAL_ENCODING")
    return raw

def _body(body, now=None):
    if type(body) is not dict or set(body) != BODY_FIELDS:
        _stop("EXACT_GRANT_FIELDS_REQUIRED")
    if body["schema"] != SCHEMA or body["audience"] != AUDIENCE:
        _stop("WRONG_SIGNING_DOMAIN")
    if body["action"] not in ("TRASH", "RESTORE"):
        _stop("UNAUTHORIZED_ACTION")
    if type(body["roomId"]) is not str or not SAFE_ROOM.fullmatch(body["roomId"]):
        _stop("INVALID_ROOM_ID")
    for field in ("patientId", "operatorId"):
        if type(body[field]) is not str or not SAFE_OPERATOR.fullmatch(body[field]):
            _stop("INVALID_" + field.upper())
    for field in ("approvalId", "seatId", "hostId"):
        if type(body[field]) is not str or not SAFE_APPROVAL.fullmatch(body[field]):
            _stop("INVALID_" + field.upper())
    if (type(body["repository"]) is not str or
            not 1 <= len(body["repository"]) <= 256 or
            any(ord(x) < 33 or ord(x) > 126 for x in body["repository"])):
        _stop("INVALID_REPOSITORY")
    if type(body["expectedRevision"]) is not int or not 0 <= body["expectedRevision"] < 1_000_000_000:
        _stop("INVALID_REVISION")
    if type(body["expectedDigest"]) is not str or not HEX64.fullmatch(body["expectedDigest"]):
        _stop("INVALID_GRAPH_DIGEST")
    if body["retentionApproved"] is not True:
        _stop("RETENTION_NOT_APPROVED_BY_ISSUER")
    if type(body["nonce"]) is not str or not B64NONCE.fullmatch(body["nonce"]):
        _stop("INVALID_NONCE")
    _unb64(body["nonce"], 32)
    if type(body["issuedAt"]) is not int or type(body["expiresAt"]) is not int:
        _stop("INVALID_TIMESTAMPS")
    if not 0 < body["expiresAt"] - body["issuedAt"] <= 60:
        _stop("GRANT_TOO_LONG")
    tick = int(time.time()) if now is None else int(now)
    if body["issuedAt"] > tick + 3:
        _stop("FUTURE_ISSUE_TIME")
    if body["expiresAt"] <= tick:
        _stop("EXPIRED_GRANT")
    return body

def parse(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= 4096:
        _stop("BOUNDED_SIGNED_ENVELOPE_REQUIRED")
    try:
        frame = json.loads(raw.decode("utf-8", "strict"),
                           object_pairs_hook=_unique_pairs,
                           parse_constant=_nonfinite)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise GrantRefused("HOSPITAL ROOM GRANT HOLD // INVALID_JSON") from exc
    if type(frame) is not dict or set(frame) != {"body", "signature"}:
        _stop("EXACT_ENVELOPE_REQUIRED")
    return frame

def trusted_public_key():
    """No CLI-, QML-, env- or DB-selected key. Root controls installed anchor."""
    p = Path(KEY_PATH)
    for parent in (p.parent, p.parent.parent, p.parent.parent.parent):
        try:
            st = parent.lstat()
        except OSError as exc:
            raise GrantRefused("HOSPITAL ROOM GRANT HOLD // TRUST_ROOT_MISSING") from exc
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0
                or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            _stop("TRUST_ROOT_UNPROTECTED")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(str(p), flags)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                    or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                    or info.st_size != 32):
                _stop("PINNED_KEY_UNPROTECTED")
            value = os.read(fd, 33)
        finally:
            os.close(fd)
        if len(value) != 32:
            _stop("PINNED_KEY_INVALID")
        return Ed25519PublicKey.from_public_bytes(value)
    except (OSError, ValueError) as exc:
        raise GrantRefused("HOSPITAL ROOM GRANT HOLD // TRUSTED_ISSUER_UNAVAILABLE") from exc

def _verify_bytes(raw, public_key, *, now=None):
    """For test-verified signature parsing; CLI NEVER supplies a key."""
    if not isinstance(public_key, Ed25519PublicKey):
        _stop("VERIFIER_KEY_INVALID")
    frame = parse(raw)
    body = _body(frame["body"], now)
    encoded = frame["signature"]
    if type(encoded) is not str or not B64SIGNATURE.fullmatch(encoded):
        _stop("INVALID_SIGNATURE")
    signed = DOMAIN + canonical(body)
    try:
        public_key.verify(_unb64(encoded, 64), signed)
    except InvalidSignature as exc:
        raise GrantRefused("HOSPITAL ROOM GRANT HOLD // SIGNATURE_MISMATCH") from exc
    return VerifiedGrant(body, hashlib.sha256(signed).hexdigest())

def verify_file(grant_file):
    """Only signed envelope bytes are caller-selected; key is always pinned."""
    if type(grant_file) is not str or not grant_file.startswith("/") or len(grant_file) > 1024:
        _stop("ABSOLUTE_GRANT_FILE_REQUIRED")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(grant_file, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                _stop("INVALID_GRANT_FILE")
            raw = os.read(fd, 4097)
        finally:
            os.close(fd)
    except OSError as exc:
        raise GrantRefused("HOSPITAL ROOM GRANT HOLD // GRANT_FILE_UNAVAILABLE") from exc
    return _verify_bytes(raw, trusted_public_key())

class VerifiedGrant:
    __slots__ = ("body", "digest")
    def __init__(self, body, digest):
        self.body = body
        self.digest = digest

    def consume(self, conn, *, room_id, patient_id, repository,
                action, revision, digest):
        """Call ONLY inside the lifecycle's BEGIN IMMEDIATE. Refuse replay."""
        if not conn.in_transaction:
            _stop("ATOMIC_TRANSACTION_REQUIRED")
        body = _body(self.body)
        expected = {
            "roomId": room_id, "patientId": patient_id,
            "repository": repository, "action": action,
            "expectedRevision": revision, "expectedDigest": digest,
        }
        for field, actual in expected.items():
            if body[field] != actual:
                _stop("SIGNED_" + field.upper() + "_MISMATCH")
        try:
            conn.execute(
                """INSERT INTO room_lifecycle_authorizations
                   (nonce, grant_digest, approval_id, room_id, operator_id,
                    operation, revision_before, graph_digest)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (body["nonce"], self.digest, body["approvalId"],
                 room_id, body["operatorId"], action, revision, digest)
            )
        except sqlite3.IntegrityError as exc:
            raise GrantRefused("HOSPITAL ROOM GRANT HOLD // REPLAYED_APPROVAL") from exc
        return body["operatorId"], self.digest
