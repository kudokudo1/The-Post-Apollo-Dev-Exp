"""Hospital native Session/Doctor signed-grant verifier, source-only v1.

Separate signing domain and root-pinned public key from Room Trash/Restore.
No private signer, test-key CLI, installed service, socket, UID authorization
or production schema migration is provided. An opaque verified grant alone
does not prove a trusted operator, active seat, or process provenance.

For a future approved native host: verify the envelope against a root-owned
anchor, bind to the installed host, then consume under the same BEGIN
IMMEDIATE as the exact source Session/Doctor mutation. The old atomic
functions are NOT wired to this grant yet, so dispatch stays disabled.
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

import px_hospital_room_lifecycle as lifecycle

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:
    Ed25519PublicKey = None

    class InvalidSignature(Exception):
        pass

DOMAIN = b"post-apollo.hospital.staffing-grant.v1\x00"
SCHEMA = "post-apollo.hospital.staffing-grant.v1"
AUDIENCE = "px-hospital-native-staffing-v1"
KEY_PATH = Path("/etc/post-apollo/hospital/staffing-issuer.pub")
HOST_PATH = Path("/etc/machine-id")
MAX_FRAME = 8192
BODY_FIELDS = frozenset((
    "schema", "audience", "operation", "scope", "roomRevision",
    "graphDigest", "operatorId", "approvalId", "seatId", "hostId",
    "nonce", "issuedAt", "expiresAt",
))
ATTACH = "SESSION_ATTACH"
SUCCEED = "DOCTOR_SUCCEED"
SHARED_SCOPE = frozenset((
    "roomId", "patientId", "repository", "branch", "bedPath", "assignmentId",
))
ATTACH_SCOPE = SHARED_SCOPE | frozenset((
    "sessionId", "doctorId", "providerId", "mode",
))
SUCCEED_SCOPE = SHARED_SCOPE | frozenset((
    "previousSessionId", "newSessionId", "previousDoctorId",
    "previousProviderId", "successorDoctorId", "successorProviderId",
))
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:@/-]{1,160}\Z", re.ASCII)
APPROVAL = re.compile(r"[A-Za-z0-9_-]{12,128}\Z", re.ASCII)
NONCE = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
ASSIGNMENT = re.compile(r"[1-9][0-9]{0,17}\Z", re.ASCII)
SIGNATURE = re.compile(r"[A-Za-z0-9_-]{86}\Z", re.ASCII)
DIGEST = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
_TRUSTED_VERIFICATION = object()


class StaffingGrantHold(RuntimeError):
    pass


def hold(reason):
    raise StaffingGrantHold("HOSPITAL_STAFFING_GRANT_HOLD // " + reason)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            hold("DUPLICATE_FIELD")
        result[key] = value
    return result


def _nonfinite(_value):
    hold("NONFINITE_NUMBER")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _unb64(value, length):
    if type(value) is not str:
        hold("INVALID_BASE64")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise StaffingGrantHold(
            "HOSPITAL_STAFFING_GRANT_HOLD // INVALID_BASE64"
        ) from exc
    if len(raw) != length or (
            base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != value):
        hold("NONCANONICAL_BASE64")
    return raw


def _id(value):
    return type(value) is str and IDENTIFIER.fullmatch(value) is not None


def _scope(operation, value):
    wanted = ATTACH_SCOPE if operation == ATTACH else SUCCEED_SCOPE
    if type(value) is not dict or set(value) != wanted:
        hold("EXACT_STAFFING_SCOPE_REQUIRED")
    for key, item in value.items():
        if key in ("repository", "branch", "bedPath", "assignmentId", "mode"):
            continue
        if not _id(item):
            hold("INVALID_SCOPE_IDENTITY")
    if type(value["repository"]) is not str or not (
            1 <= len(value["repository"]) <= 256
            and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
                             value["repository"], re.ASCII)):
        hold("INVALID_REPOSITORY")
    for key in ("branch", "bedPath"):
        item = value[key]
        if (type(item) is not str or not 1 <= len(item) <= 1024
                or any(ord(c) < 32 or ord(c) == 127 for c in item)):
            hold("INVALID_PATH_OR_BRANCH")
    bed = Path(value["bedPath"])
    if not bed.is_absolute() or ".." in bed.parts or str(bed) != value["bedPath"]:
        hold("INVALID_CANONICAL_BED")
    if (type(value["assignmentId"]) is not str
            or ASSIGNMENT.fullmatch(value["assignmentId"]) is None):
        hold("INVALID_ASSIGNMENT")
    if operation == ATTACH and value["mode"] not in ("create", "reuse"):
        hold("INVALID_ATTACH_MODE")
    if operation == SUCCEED and (
            value["previousSessionId"] == value["newSessionId"]
            or value["previousDoctorId"] == value["successorDoctorId"]):
        hold("SAME_SESSION_OR_DOCTOR")
    return value


def _body(value, *, now=None):
    if type(value) is not dict or set(value) != BODY_FIELDS:
        hold("EXACT_GRANT_FIELDS_REQUIRED")
    if value["schema"] != SCHEMA or value["audience"] != AUDIENCE:
        hold("WRONG_SIGNING_DOMAIN")
    op = value["operation"]
    if type(op) is not str or op not in (ATTACH, SUCCEED):
        hold("UNSUPPORTED_STAFFING_OPERATION")
    _scope(op, value["scope"])
    if (type(value["roomRevision"]) is not int
            or not 0 <= value["roomRevision"] < 1_000_000_000
            or type(value["graphDigest"]) is not str
            or not DIGEST.fullmatch(value["graphDigest"])):
        hold("INVALID_ROOM_VERSION")
    if not _id(value["operatorId"]):
        hold("INVALID_OPERATOR")
    for key in ("approvalId", "seatId", "hostId"):
        if (type(value[key]) is not str
                or not APPROVAL.fullmatch(value[key])):
            hold("INVALID_APPROVAL_SEAT_OR_HOST")
    if (type(value["nonce"]) is not str
            or not NONCE.fullmatch(value["nonce"])):
        hold("INVALID_NONCE")
    _unb64(value["nonce"], 32)
    if (type(value["issuedAt"]) is not int
            or type(value["expiresAt"]) is not int
            or not 0 < value["expiresAt"] - value["issuedAt"] <= 30):
        hold("INVALID_GRANT_LIFETIME")
    tick = int(time.time()) if now is None else int(now)
    if value["issuedAt"] > tick + 3:
        hold("FUTURE_GRANT")
    if value["expiresAt"] <= tick:
        hold("EXPIRED_GRANT")
    return value


def _verify_bytes(raw: bytes, public_key, *, now=None):
    """Cryptographic verification for isolated CI and a future native host.

    Production callers MUST obtain public_key only from trusted_public_key;
    never pass client-selected key objects through an RPC or CLI option.
    """
    if Ed25519PublicKey is None or not isinstance(public_key, Ed25519PublicKey):
        hold("CRYPTO_VERIFIER_UNAVAILABLE")
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_FRAME:
        hold("BOUNDED_SIGNED_GRANT_REQUIRED")
    try:
        obj = json.loads(raw.decode("utf-8", "strict"),
                         object_pairs_hook=_unique,
                         parse_constant=_nonfinite)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise StaffingGrantHold(
            "HOSPITAL_STAFFING_GRANT_HOLD // INVALID_SIGNED_JSON"
        ) from exc
    if type(obj) is not dict or set(obj) != {"body", "signature"}:
        hold("EXACT_SIGNED_ENVELOPE")
    if canonical(obj) != raw:
        hold("NONCANONICAL_ENVELOPE")
    body = _body(obj["body"], now=now)
    signature = obj["signature"]
    if type(signature) is not str or not SIGNATURE.fullmatch(signature):
        hold("INVALID_SIGNATURE")
    digest = hashlib.sha256(DOMAIN + canonical(body)).hexdigest()
    try:
        public_key.verify(_unb64(signature, 64), DOMAIN + canonical(body))
    except InvalidSignature as exc:
        raise StaffingGrantHold(
            "HOSPITAL_STAFFING_GRANT_HOLD // SIGNATURE_MISMATCH"
        ) from exc
    return VerifiedStaffingGrant(body, digest, token=_TRUSTED_VERIFICATION)


def _root_file(path: Path, expected_bytes: int):
    for parent in path.parents:
        try:
            st = parent.lstat()
        except OSError as exc:
            raise StaffingGrantHold(
                "HOSPITAL_STAFFING_GRANT_HOLD // ROOT_PARENT_MISSING"
            ) from exc
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0
                or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            hold("UNTRUSTED_ROOT_PARENT")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0
                    or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                    or st.st_size != expected_bytes):
                hold("UNTRUSTED_ROOT_FILE")
            raw = os.read(fd, expected_bytes + 1)
        finally:
            os.close(fd)
    except OSError as exc:
        raise StaffingGrantHold(
            "HOSPITAL_STAFFING_GRANT_HOLD // ROOT_FILE_UNAVAILABLE"
        ) from exc
    if len(raw) != expected_bytes:
        hold("BAD_ROOT_FILE_LENGTH")
    return raw


def trusted_public_key():
    if Ed25519PublicKey is None:
        hold("CRYPTO_VERIFIER_UNAVAILABLE")
    try:
        return Ed25519PublicKey.from_public_bytes(_root_file(KEY_PATH, 32))
    except ValueError as exc:
        raise StaffingGrantHold(
            "HOSPITAL_STAFFING_GRANT_HOLD // INVALID_TRUSTED_KEY"
        ) from exc


def installed_host_binding():
    # Machine-id is 32 lowercase hex bytes, often with a trailing newline.
    # Verify it from a trusted root-controlled path, never a caller field.
    path = HOST_PATH
    for parent in path.parents:
        st = parent.lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0
                or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            hold("UNTRUSTED_HOST_PARENT")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0
                    or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                    or st.st_size > 128):
                hold("UNTRUSTED_HOST_ID")
            raw = os.read(fd, 129).strip()
        finally:
            os.close(fd)
    except OSError as exc:
        raise StaffingGrantHold(
            "HOSPITAL_STAFFING_GRANT_HOLD // HOST_ID_UNAVAILABLE"
        ) from exc
    if not re.fullmatch(rb"[0-9a-f]{32}", raw):
        hold("INVALID_HOST_ID")
    return hashlib.sha256(DOMAIN + bytes.fromhex(raw.decode("ascii"))).hexdigest()


def verify_native_envelope(raw: bytes):
    """No caller key, path, host or verifier can be selected in this API."""
    grant = _verify_bytes(raw, trusted_public_key())
    if grant.body["hostId"] != installed_host_binding():
        hold("SIGNED_HOST_MISMATCH")
    # Only this root-pinned code path marks a grant as native-verified.
    # _verify_bytes is testable but its caller-supplied key is not proof
    # of installed-host authorization.
    grant.native_verified = True
    return grant


class VerifiedStaffingGrant:
    __slots__ = ("body", "digest", "native_verified")

    def __init__(self, body, digest, *, token=None):
        if token is not _TRUSTED_VERIFICATION:
            hold("UNVERIFIED_GRANT_INSTANCE")
        self.body = body
        self.digest = digest
        self.native_verified = False

    def consume(self, db: sqlite3.Connection, *, operation: str, scope: dict):
        """Validate source state, then consume a distinct nonce in source txn.

        The external protected handler must open BEGIN IMMEDIATE, construct
        the operation's exact scope from independently read trusted state,
        and perform its original atomic Session/Doctor write *before COMMIT*.
        This function alone does not mutate staffing or authorize a caller.
        """
        if not isinstance(db, sqlite3.Connection) or not db.in_transaction:
            hold("ATOMIC_WRITER_TRANSACTION_REQUIRED")
        body = _body(self.body)
        if hashlib.sha256(DOMAIN + canonical(body)).hexdigest() != self.digest:
            hold("VERIFIED_GRANT_MUTATED")
        if operation != body["operation"]:
            hold("SIGNED_OPERATION_CHANGED")
        _scope(operation, scope)
        if scope != body["scope"]:
            hold("SIGNED_SCOPE_CHANGED")

        snapshot = lifecycle.review(db, scope["roomId"])
        if snapshot["state"] != "ACTIVE":
            hold("ROOM_NOT_ACTIVE")
        if (snapshot["revision"] != body["roomRevision"]
                or snapshot["digest"] != body["graphDigest"]):
            hold("STALE_ROOM_GRAPH")
        source = db.execute(
            """SELECT r.patient_id, p.repository, r.branch, r.bed_path,
                      r.current_assignment_id, r.doctor_id, r.provider_id
               FROM rooms r JOIN patients p ON p.patient_id=r.patient_id
               WHERE r.room_id=?""", (scope["roomId"],)
        ).fetchone()
        if source is None:
            hold("ROOM_PATIENT_UNVERIFIED")
        for key, original in (
            ("patientId", "patient_id"), ("repository", "repository"),
            ("branch", "branch"), ("bedPath", "bed_path"),
            ("assignmentId", "current_assignment_id"),
        ):
            if scope[key] != str(source[original] or ""):
                hold("CHANGED_ROOM_ASSIGNMENT_OR_BED")
        assignment = db.execute(
            "SELECT status,room_id,patient_id FROM assignments "
            "WHERE assignment_id=?", (int(scope["assignmentId"]),)
        ).fetchone()
        if (assignment is None or assignment["status"] != "ACTIVE"
                or assignment["room_id"] != scope["roomId"]
                or assignment["patient_id"] != scope["patientId"]):
            hold("ASSIGNMENT_NOT_ACTIVE_OR_LINKED")
        if operation == ATTACH:
            doctor = db.execute("SELECT status FROM doctors WHERE doctor_id=?",
                                (scope["doctorId"],)).fetchone()
            if doctor is None or doctor["status"] != "ACTIVE":
                hold("ATTACH_DOCTOR_NOT_ACTIVE")
            if (str(source["doctor_id"] or "") not in ("", scope["doctorId"])
                    or str(source["provider_id"] or "") not in (
                        "", scope["providerId"])):
                hold("ATTACH_STAFFING_CHANGED")
        else:
            if (str(source["doctor_id"] or "") != scope["previousDoctorId"]
                    or str(source["provider_id"] or "")
                    != scope["previousProviderId"]):
                hold("PREVIOUS_STAFFING_CHANGED")
            doctor = db.execute(
                "SELECT status FROM doctors WHERE doctor_id=?",
                (scope["successorDoctorId"],)
            ).fetchone()
            if doctor is None or doctor["status"] != "ACTIVE":
                hold("SUCCESSOR_DOCTOR_NOT_ACTIVE")
        # Migration of this new table is intentionally NOT performed here.
        # It must be separately reviewed and present before protected use.
        try:
            db.execute(
                """INSERT INTO hospital_staffing_authorizations
                   (nonce,grant_digest,approval_id,room_id,operation,operator_id,
                    session_id,graph_digest)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (body["nonce"], self.digest, body["approvalId"],
                 scope["roomId"], operation, body["operatorId"],
                 scope["sessionId"] if operation == ATTACH
                 else scope["newSessionId"], snapshot["digest"])
            )
        except sqlite3.IntegrityError as exc:
            raise StaffingGrantHold(
                "HOSPITAL_STAFFING_GRANT_HOLD // REPLAYED_APPROVAL"
            ) from exc
        except sqlite3.OperationalError as exc:
            raise StaffingGrantHold(
                "HOSPITAL_STAFFING_GRANT_HOLD // LEDGER_NOT_MIGRATED"
            ) from exc
        return {"roomId":scope["roomId"], "operation":operation,
                "operatorId":body["operatorId"], "grantDigest":self.digest}
