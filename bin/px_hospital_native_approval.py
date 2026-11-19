"""Hospital Trash/Restore // protected Connections prepare/commit owner adapter.

This is PX source-side authorization, not a test signer or a desktop
mutation command. It implements the exact C5-H2 request/response contract.
The installed, root-owned retention decision file is independently provided
by an administrator after a legal-hold/retention review. No such policy is
created here. Without it, all PREPARE and COMMIT requests refuse.
"""
from __future__ import annotations
from contextlib import closing
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time

import px_hospital_room_authority as authority
import px_hospital_room_lifecycle as lifecycle

SCHEMA = "postapollo.hospital.protected-writer-request.v1"
PREPARED_SCHEMA = "postapollo.hospital.protected-writer-prepared.v1"
RECEIPT_SCHEMA = "postapollo.hospital.protected-writer-receipt.v1"
POLICY_SCHEMA = "postapollo.hospital.room-retention-decision.v1"
POLICY_PATH = Path("/etc/post-apollo/hospital/room-retention-policy.json")
ROOM = re.compile(r"[A-Za-z0-9._:/-]{1,160}\Z", re.ASCII)
NONCE = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{12,128}\Z", re.ASCII)
MAX_IPC = 8192
MAX_PENDING = 64

class Refused(RuntimeError):
    pass

def hold(reason):
    raise Refused("HOSPITAL_ROOM_APPROVAL_HOLD // " + reason)

def _unique(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            hold("DUPLICATE_FIELD")
        data[key] = value
    return data

def _nonfinite(_value):
    hold("NONFINITE_REFUSED")

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),
                      ensure_ascii=True,allow_nan=False).encode("ascii")

def _json(raw, ceiling=MAX_IPC):
    if type(raw) is not bytes or not 2 <= len(raw) <= ceiling:
        hold("FRAME_SIZE_INVALID")
    try:
        return json.loads(raw.decode("utf-8","strict"),
                          object_pairs_hook=_unique,parse_constant=_nonfinite)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise Refused("HOSPITAL_ROOM_APPROVAL_HOLD // JSON_INVALID") from exc

def parse(raw):
    frame = _json(raw)
    if type(frame) is not dict or frame.get("schema") != SCHEMA:
        hold("WRONG_PROTOCOL")
    kind = frame.get("kind")
    if kind == "prepare":
        expected = {"schema","kind","roomId","action","requestNonce"}
    elif kind == "commit":
        expected = {
            "schema","kind","roomId","action","requestNonce",
            "writerInstance","signedGrant"
        }
    else:
        hold("UNSUPPORTED_KIND")
    if set(frame) != expected:
        hold("EXACT_FIELDS_REQUIRED")
    if (type(frame["roomId"]) is not str or
            ROOM.fullmatch(frame["roomId"]) is None or
            frame["action"] not in ("TRASH","RESTORE") or
            type(frame["requestNonce"]) is not str or
            NONCE.fullmatch(frame["requestNonce"]) is None):
        hold("ROOM_ACTION_NONCE_INVALID")
    try:
        raw_nonce=base64.urlsafe_b64decode(
            frame["requestNonce"] + "=" * (-len(frame["requestNonce"]) % 4))
    except (ValueError, TypeError) as exc:
        raise Refused("HOSPITAL_ROOM_APPROVAL_HOLD // NONCE_INVALID") from exc
    if (len(raw_nonce)!=32 or
        base64.urlsafe_b64encode(raw_nonce).rstrip(b"=").decode("ascii")
        !=frame["requestNonce"]):
        hold("NONCE_INVALID")
    if kind == "commit":
        if (type(frame["writerInstance"]) is not str
            or IDENTIFIER.fullmatch(frame["writerInstance"]) is None
            or type(frame["signedGrant"]) is not str
            or not 1 <= len(frame["signedGrant"]) <= 4096):
            hold("SIGNED_COMMIT_FIELDS_INVALID")
    return frame

def _root_policy_bytes():
    path = POLICY_PATH
    for parent in path.parents:
        try: info=parent.lstat()
        except OSError as exc: raise Refused("RETENTION_POLICY_NOT_INSTALLED") from exc
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or info.st_mode & (stat.S_IWGRP|stat.S_IWOTH)):
            hold("RETENTION_ROOT_NOT_PROTECTED")
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
    try:
        fd=os.open(str(path),flags)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_nlink != 1
                or info.st_mode & (stat.S_IWGRP|stat.S_IWOTH)
                or not 1 <= info.st_size <= 8192):
                hold("RETENTION_POLICY_UNPROTECTED")
            raw=os.read(fd,8193)
            if len(raw)!=info.st_size:
                hold("RETENTION_POLICY_CHANGED")
        finally:os.close(fd)
    except OSError as exc:
        raise Refused("RETENTION_POLICY_NOT_INSTALLED") from exc
    return raw

def _policy():
    """No caller-selected file, env override, or trust fallback."""
    doc=_json(_root_policy_bytes())
    if (type(doc) is not dict or
        set(doc)!={"schema","policyGeneration","expiresAt","rooms"} or
        doc["schema"]!=POLICY_SCHEMA or
        type(doc["policyGeneration"]) is not int or
        not 1 <= doc["policyGeneration"] < 2**31 or
        type(doc["expiresAt"]) is not int or
        doc["expiresAt"] <= int(time.time()) or
        type(doc["rooms"]) is not list or
        len(doc["rooms"]) > 256):
        hold("UNTRUSTED_RETENTION_POLICY")
    return doc

def _decision(policy, room_id, patient_id, repository, action):
    rows=[]
    for entry in policy["rooms"]:
        if (type(entry) is not dict or
            set(entry) != {"roomId","patientId","repository",
                           "allowTrash","allowRestore","legalHold"} or
            type(entry["allowTrash"]) is not bool or
            type(entry["allowRestore"]) is not bool or
            type(entry["legalHold"]) is not bool):
            hold("INVALID_RETENTION_ROOM_ENTRY")
        if entry["roomId"]==room_id:
            rows.append(entry)
    if len(rows)!=1:
        hold("ROOM_RETENTION_NOT_INDEPENDENTLY_APPROVED")
    item=rows[0]
    if (item["patientId"]!=patient_id or
        item["repository"]!=repository or
        item["legalHold"] is not False or
        item["allowTrash" if action=="TRASH" else "allowRestore"] is not True):
        hold("ROOM_RETENTION_OR_LEGAL_HOLD_REFUSED")
    return item

class ProtectedApproval:
    """In-process reservations; a restart invalidates all pending operations.

    All final authority stays with PX source DB and one-use signed grant.
    A root-provided retention policy is required at both PREPARE and COMMIT.
    """
    def __init__(self, connect, *, retention=None, now=None):
        self.connect = connect
        self.retention = retention if retention is not None else _policy
        self.now = now if now is not None else lambda: int(time.time())
        self.instance = secrets.token_urlsafe(24)
        self.pending = {}

    def process(self, raw, *, peer_uid):
        if peer_uid != 0:
            hold("ROOT_NATIVE_ISSUER_REQUIRED")
        req=parse(raw)
        if req["kind"]=="prepare":
            return canonical(self._prepare(req))
        return canonical(self._commit(req))

    def _prepare(self, req):
        now=self.now()
        self.pending={k:v for k,v in self.pending.items() if v["expiresAt"]>now}
        if len(self.pending)>=MAX_PENDING:
            hold("TOO_MANY_OUTSTANDING_APPROVALS")
        if req["requestNonce"] in self.pending:
            hold("DUPLICATE_REQUEST_NONCE")
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                review=lifecycle.review(conn,req["roomId"])
                expected="ACTIVE" if req["action"]=="TRASH" else "TRASHED"
                approved=review["canTrash" if req["action"]=="TRASH" else "canRestore"]
                if review["state"]!=expected or not approved or review["blockers"]:
                    hold("ROOM_NOT_ELIGIBLE")
                row=conn.execute(
                    "SELECT r.patient_id,p.repository FROM rooms r "
                    "JOIN patients p ON p.patient_id=r.patient_id "
                    "WHERE r.room_id=?",(req["roomId"],)).fetchone()
                if row is None:
                    hold("PATIENT_IDENTITY_NOT_FOUND")
                patient_id,repository=str(row["patient_id"]),str(row["repository"])
                pol=self.retention()
                _decision(pol,req["roomId"],patient_id,repository,req["action"])
                expiry=min(now+45,pol["expiresAt"])
                if expiry<=now:
                    hold("POLICY_EXPIRED")
                prepared={
                    "schema":PREPARED_SCHEMA,
                    "requestNonce":req["requestNonce"],
                    "action":req["action"],
                    "roomId":req["roomId"],
                    "patientId":patient_id,
                    "repository":repository,
                    "expectedRevision":review["revision"],
                    "expectedDigest":review["digest"],
                    "state":review["state"],
                    "blockers":[],
                    "canTrash":review["canTrash"],
                    "canRestore":review["canRestore"],
                    "retentionApproved":True,
                    "legalHold":False,
                    "policyGeneration":pol["policyGeneration"],
                    "writerInstance":self.instance,
                    "expiresAt":expiry,
                }
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        self.pending[req["requestNonce"]]=prepared
        return prepared

    def _commit(self, req):
        now=self.now()
        prepared=self.pending.pop(req["requestNonce"],None)
        if (prepared is None or prepared["expiresAt"]<=now
            or prepared["writerInstance"]!=req["writerInstance"]
            or prepared["writerInstance"]!=self.instance
            or prepared["roomId"]!=req["roomId"]
            or prepared["action"]!=req["action"]):
            hold("STALE_OR_UNBOUND_APPROVAL")
        # Pinned root key and host identity live in PX owner source. Nothing
        # about the caller's request may select a verifier or modify policy.
        verified=authority._verify_bytes(
            req["signedGrant"].encode("ascii"),
            authority.trusted_public_key(),
        )
        if verified.body["hostId"]!=authority.installed_host_binding():
            hold("HOST_MISMATCH")
        if (verified.body["nonce"]!=req["requestNonce"]
            or verified.body["issuedAt"]>now+3
            or verified.body["expiresAt"]<=now):
            hold("SIGNED_NONCE_OR_TIME_MISMATCH")
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row=conn.execute(
                    "SELECT r.patient_id,p.repository FROM rooms r "
                    "JOIN patients p ON p.patient_id=r.patient_id "
                    "WHERE r.room_id=?",(req["roomId"],)).fetchone()
                if row is None:
                    hold("PATIENT_CHANGED")
                pol=self.retention()
                if (pol["policyGeneration"]!=prepared["policyGeneration"]
                    or pol["expiresAt"]<=now):
                    hold("RETENTION_POLICY_CHANGED_OR_EXPIRED")
                _decision(pol,req["roomId"],str(row["patient_id"]),
                          str(row["repository"]),req["action"])
                reviewed=lifecycle.review(conn,req["roomId"])
                if (reviewed["revision"]!=prepared["expectedRevision"]
                    or reviewed["digest"]!=prepared["expectedDigest"]
                    or reviewed["state"]!=prepared["state"]
                    or reviewed["blockers"]):
                    hold("ROOM_CHANGED_AFTER_OPERATOR_APPROVAL")
                # lifecycle.transition opens its own BEGIN IMMEDIATE and
                # inserts the one-use nonce+receipt atomically. We release
                # this read transaction only after guards are verified,
                # then transition recomputes all witnesses under its lock.
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            def final_retention_guard(_conn, final_room, final_identity):
                current=self.retention()
                if (current["policyGeneration"]!=prepared["policyGeneration"]
                    or current["expiresAt"]<=self.now()
                    or final_room["digest"]!=prepared["expectedDigest"]):
                    hold("RETENTION_REVOKED_DURING_TRANSACTION")
                _decision(
                    current,req["roomId"],
                    str(final_identity["patient_id"]),
                    str(final_identity["repository"]),req["action"],
                )
            result=lifecycle.transition(
                conn,req["roomId"],req["action"],
                prepared["expectedRevision"],prepared["expectedDigest"],
                req["roomId"],authorization=verified,
                protected_hold=final_retention_guard,
            )
        return {
            "schema":RECEIPT_SCHEMA,
            "requestNonce":req["requestNonce"],
            "roomId":req["roomId"],
            "action":req["action"],
            "revisionAfter":result["revision"],
            "grantDigest":verified.digest,
            "state":result["state"],
            "originalPreserved":True,
            "burnAllowed":False,
        }
