"""One-use signed first-Bed intent, strictly limited to disposable PX fixtures.

This validates a genuinely cryptographic Ed25519 signature, but it DOES NOT
establish the human operator's identity or an installed, attested native host.
In production, only a separately approved and verified host may sign these
requests. No client-supplied public key, unsigned boolean or QML signal grants
authority. Native Hospital installation is deliberately disabled.
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
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

DOMAIN = b"post-apollo.hospital.first-bed-intent.experimental-v1\x00"
SCHEMA = "post-apollo.hospital.first-bed-intent.experimental-v1"
OPERATION = "FIRST_BED_REGISTER"
KEY_ENV = "PX_HOSPITAL_BED_INTENT_PINNED_KEY_FIXTURE"
RECEIPT_FIELDS = frozenset({"schema", "operation", "roomId", "patientId",
    "repository", "branch", "bedPath", "head", "roomUpdatedAt", "operatorId",
    "nonce", "issuedAt", "expiresAt"})
ENVELOPE_FIELDS = frozenset({"body", "signature"})
SAFE_ID = re.compile(r"[A-Za-z0-9_.:@/-]{1,96}\Z", re.ASCII)
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z", re.ASCII)
NONCE = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
SIGNATURE = re.compile(r"[A-Za-z0-9_-]{86}\Z", re.ASCII)
SHA = re.compile(r"[a-f0-9]{40}(?:[a-f0-9]{24})?\Z", re.ASCII)


class IntentRefused(RuntimeError):
    pass


def _stop(msg: str):
    raise IntentRefused("HOSPITAL BED INTENT HOLD // " + msg)


def _pairs_unique(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            _stop("duplicate JSON key")
        output[key] = value
    return output


def _no_constants(value):
    _stop("non-finite JSON constant")


def _parse(raw: bytes):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 4096:
        _stop("bounded JSON envelope required")
    try:
        obj = json.loads(raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs_unique, parse_constant=_no_constants)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise IntentRefused("HOSPITAL BED INTENT HOLD // invalid JSON envelope") from error
    if type(obj) is not dict or set(obj) != ENVELOPE_FIELDS:
        _stop("exact receipt envelope required")
    return obj


def _canon(body):
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _b64(value: bytes):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str, expected_len: int):
    try:
        out = base64.urlsafe_b64decode(value + "==")
    except (ValueError, TypeError):
        _stop("invalid signature or nonce encoding")
    if len(out) != expected_len or _b64(out) != value:
        _stop("noncanonical signature or nonce encoding")
    return out


def _valid_body(body):
    if type(body) is not dict or set(body) != RECEIPT_FIELDS:
        _stop("exact signed Bed fields required")
    if body["schema"] != SCHEMA or body["operation"] != OPERATION:
        _stop("wrong signing domain or operation")
    for key in ("roomId", "patientId", "operatorId"):
        if type(body[key]) is not str or not SAFE_ID.fullmatch(body[key]):
            _stop("invalid signed identity " + key)
    if (type(body["repository"]) is not str
            or not REPOSITORY.fullmatch(body["repository"])
            or body["repository"] != body["repository"].lower()):
        _stop("noncanonical repository")
    for key in ("branch", "bedPath"):
        value = body[key]
        if (type(value) is not str or not 1 <= len(value) <= 1024
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            _stop("invalid signed " + key)
    if (body["branch"] == "DETACHED" or not body["bedPath"].startswith("/")
            or ".." in Path(body["bedPath"]).parts):
        _stop("invalid signed Git target")
    if type(body["head"]) is not str or not SHA.fullmatch(body["head"]):
        _stop("invalid signed Git HEAD")
    if (type(body["roomUpdatedAt"]) is not str
            or not 1 <= len(body["roomUpdatedAt"]) <= 64):
        _stop("missing Room version binding")
    if type(body["nonce"]) is not str or not NONCE.fullmatch(body["nonce"]):
        _stop("invalid challenge")
    _unb64(body["nonce"], 32)
    if type(body["issuedAt"]) is not int or type(body["expiresAt"]) is not int:
        _stop("integer receipt timestamps required")
    if body["expiresAt"] <= body["issuedAt"] or body["expiresAt"] - body["issuedAt"] > 90:
        _stop("receipt lifetime must not exceed 90 seconds")
    return body


def _now_valid(body, now=None):
    clock = int(time.time()) if now is None else int(now)
    if body["issuedAt"] > clock + 3:
        _stop("receipt issued in the future")
    if body["expiresAt"] <= clock:
        _stop("receipt expired")


def _read_file(path: str, limit=4096):
    if not path or not Path(path).is_absolute():
        _stop("absolute receipt/key fixture path required")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                _stop("invalid receipt/key file")
            data = os.read(fd, limit + 1)
            if len(data) > limit:
                _stop("oversize receipt/key file")
            return data
        finally:
            os.close(fd)
    except (OSError, ValueError) as error:
        raise IntentRefused("HOSPITAL BED INTENT HOLD // receipt/key file unavailable") from error


def _pinned_fixture_public_key():
    # This override is NOT part of a production trust store. Production holds
    # in hospital_bed_claim._fixture_gate() before this function is reached.
    if os.environ.get("PX_HOSPITAL_BED_CLAIM_TEST_ONLY") != "1":
        _stop("native trusted host not installed")
    key_path = os.environ.get(KEY_ENV, "")
    key_bytes = _read_file(key_path, limit=32)
    if len(key_bytes) != 32:
        _stop("exact 32-byte pinned Ed25519 public key required")
    try:
        return Ed25519PublicKey.from_public_bytes(key_bytes)
    except ValueError as error:
        raise IntentRefused("HOSPITAL BED INTENT HOLD // invalid pinned key") from error


class VerifiedBedIntent:
    def __init__(self, body, digest):
        self.body = body
        self.digest = digest

    def consume(self, conn, room, git, *, expected_room, expected_repository,
                expected_branch, expected_bed):
        """Called under the SAME SQLite BEGIN IMMEDIATE as Room Bed UPDATE."""
        b = self.body
        _now_valid(b)
        pairs = (
            ("roomId", str(expected_room)),
            ("patientId", str(room["patient_id"] or "")),
            ("repository", str(expected_repository).lower()),
            ("branch", str(expected_branch)),
            ("bedPath", str(expected_bed)),
            ("head", str(git["head"])),
            ("roomUpdatedAt", str(room["updated_at"])),
        )
        for key, actual in pairs:
            if b[key] != actual:
                _stop("signed " + key + " no longer matches Room or Git")
        # Only the first successful transaction consumes a nonce; failures roll
        # back both the nonce ledger and the Room update. No external replay cache.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hospital_bed_intent_consumptions(
                nonce TEXT PRIMARY KEY,
                receipt_digest TEXT NOT NULL,
                room_id TEXT NOT NULL,
                consumed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute("""
                INSERT INTO hospital_bed_intent_consumptions
                    (nonce, receipt_digest, room_id)
                VALUES (?, ?, ?)
            """, (b["nonce"], self.digest, expected_room))
        except sqlite3.IntegrityError as error:
            raise IntentRefused(
                "HOSPITAL BED INTENT HOLD // signed intent already consumed"
            ) from error


def verify_signed_intent(intent_file: str):
    """No user-controlled verifier key; only the fixed fixture trust location."""
    key = _pinned_fixture_public_key()
    frame = _parse(_read_file(intent_file))
    body = _valid_body(frame["body"])
    raw_sig = frame["signature"]
    if type(raw_sig) is not str or not SIGNATURE.fullmatch(raw_sig):
        _stop("signature encoding invalid")
    signature = _unb64(raw_sig, 64)
    signed = DOMAIN + _canon(body)
    try:
        key.verify(signature, signed)
    except InvalidSignature as error:
        raise IntentRefused(
            "HOSPITAL BED INTENT HOLD // wrong signer or tampered intent"
        ) from error
    _now_valid(body)
    return VerifiedBedIntent(body, hashlib.sha256(signed).hexdigest())


def seal_fixture(private_key: Ed25519PrivateKey, body: dict):
    """For disposable CI/test signers only. NEVER a PX command."""
    if not isinstance(private_key, Ed25519PrivateKey):
        _stop("fixture signer must be Ed25519")
    _valid_body(body)
    signed = DOMAIN + _canon(body)
    return _canon({"body": body, "signature": _b64(private_key.sign(signed))})
