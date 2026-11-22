#!/usr/bin/env python3
"""CI-only hostile signed history evidence, without production custody.

A key held in the SAME disposable runner is not an independently enrolled
root signer. This test verifies *format and fail-closed comparison semantics*
of a future external write-ahead PENDING witness. No native key, socket,
source mutation, recovery status or real antirollback source is created.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()
        or not sys.platform.startswith("linux")):
    raise SystemExit("HOSPITAL_SIGNED_HISTORY_FIXTURE_HOLD // RUNNER_ONLY")

SCHEMA = "postapollo.hospital.staffing-history-witness.ci-v1"
PURPOSE = "hospital-staffing-original-request-pending-ci-only"
DOMAIN = b"postapollo.hospital.staffing-history-witness.ci-v1\0"
FIELDS = frozenset((
    "schema", "purpose", "requestNonce", "scopeDigest", "commitDigest",
    "grantDigest", "writerInstance", "sequence", "state", "hostId",
    "writerReleaseSha256", "issuerReleaseSha256", "policyGeneration",
))
DENY = {
    "canExecuteNewGrant": False,
    "canRetryOriginalRequest": False,
    "canDeclareCommitted": False,
    "canDeclareRefused": False,
    "canTreatPendingAsSuccess": False,
    "nativeRecoveryInstalled": False,
    "productionHistoryTrusted": False,
}


class HistoryHold(RuntimeError):
    pass


def hold(code):
    raise HistoryHold("HOSPITAL_HISTORY_CI_HOLD // " + code)


def canonical(obj):
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def b64(x):
    return base64.urlsafe_b64encode(x).rstrip(b"=").decode("ascii")


def unb64(value, n):
    if not isinstance(value, str):
        hold("INVALID_SIGNATURE")
    if len(value) != (n*8+5)//6 or not all(
        x in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for x in value
    ):
        hold("INVALID_SIGNATURE")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * ((-len(value)) % 4))
    except (ValueError, Exception) as exc:
        hold("INVALID_SIGNATURE")
    if len(decoded) != n or b64(decoded) != value:
        hold("INVALID_SIGNATURE")
    return decoded


def no_duplicate_keys(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            hold("DUPLICATE_JSON_FIELD")
        out[k] = v
    return out


def parse(raw):
    if not isinstance(raw, bytes) or len(raw) > 4096:
        hold("INVALID_CANONICAL_ENVELOPE")
    try:
        obj = json.loads(
            raw, object_pairs_hook=no_duplicate_keys,
            parse_constant=lambda _: hold("NONFINITE_JSON"),
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        hold("INVALID_CANONICAL_ENVELOPE")
    if type(obj) is not dict or set(obj) != {"body", "signature"}:
        hold("UNEXPECTED_ENVELOPE_FIELDS")
    if type(obj["body"]) is not dict or set(obj["body"]) != FIELDS:
        hold("UNEXPECTED_WITNESS_FIELDS")
    if canonical(obj) != raw:
        hold("NONCANONICAL_WITNESS")
    return obj


def verify(raw, *, installed_ci_pin, expected, independent_floor):
    """All production authority is deliberately hard-denied.

    The only accepted evidence state is PENDING. The pin, expected original
    transaction identity and monotonic floor are independent test inputs,
    never supplied inside a caller's signed packet or public-key field.
    """
    if installed_ci_pin is None or independent_floor is None:
        hold("INDEPENDENT_CUSTODY_UNAVAILABLE")
    if type(independent_floor) is not int or independent_floor < 1:
        hold("INVALID_INDEPENDENT_FLOOR")
    packet = parse(raw)
    body = packet["body"]
    if (body["schema"] != SCHEMA or body["purpose"] != PURPOSE
            or body["state"] != "PENDING"):
        hold("WRONG_PURPOSE_OR_UNTRUSTED_TERMINAL")
    if type(body["sequence"]) is not int or body["sequence"] != independent_floor:
        hold("STALE_OR_UNPINNED_SEQUENCE")
    if type(body["requestNonce"]) is not str or len(body["requestNonce"]) != 43:
        hold("INVALID_ORIGINAL_NONCE")
    for k in ("scopeDigest", "commitDigest", "grantDigest", "hostId",
              "writerReleaseSha256", "issuerReleaseSha256"):
        if (type(body[k]) is not str or len(body[k]) != 64
                or any(c not in "0123456789abcdef" for c in body[k])):
            hold("INVALID_DIGEST")
    if (type(body["policyGeneration"]) is not int
            or body["policyGeneration"] < 1):
        hold("INVALID_POLICY_GENERATION")
    if (type(body["writerInstance"]) is not str
            or len(body["writerInstance"]) < 5
            or len(body["writerInstance"]) > 160):
        hold("INVALID_WRITER_INSTANCE")
    sig = unb64(packet["signature"], 64)
    try:
        installed_ci_pin.verify(sig, DOMAIN + canonical(body))
    except InvalidSignature:
        hold("WITNESS_SIGNATURE_MISMATCH")
    if (type(expected) is not dict
            or set(expected) != FIELDS - {"schema", "purpose", "sequence", "state"}):
        hold("INDEPENDENT_EXPECTATION_REQUIRED")
    if any(body[k] != expected[k] for k in expected):
        hold("ORIGINAL_TRANSACTION_IDENTITY_CHANGED")
    return {"observation": "CI_SIGNED_PENDING_NOT_A_TRANSACTION_RESULT", **DENY}


def require_hold(call, reason):
    try:
        call()
    except HistoryHold as exc:
        assert reason in str(exc), (reason, str(exc))
        return
    raise AssertionError("HISTORY_PROOF_UNEXPECTEDLY_AUTHORIZED")


def issue(private, body):
    return canonical({
        "body": body,
        "signature": b64(private.sign(DOMAIN + canonical(body))),
    })


with tempfile.TemporaryDirectory(
    prefix="hospital-signed-history-ci-", dir=os.environ["RUNNER_TEMP"]
) as isolated:
    assert Path(isolated).is_dir()
    signer = Ed25519PrivateKey.generate()
    attacker = Ed25519PrivateKey.generate()
    pin = signer.public_key()  # CI-local fixed pin, NOT installed root custody.
    original = {
        "requestNonce": b64(b"\x11" * 32),
        "scopeDigest": hashlib.sha256(b"original-scope").hexdigest(),
        "commitDigest": hashlib.sha256(b"exact-original-commit").hexdigest(),
        "grantDigest": hashlib.sha256(b"exact-original-grant").hexdigest(),
        "writerInstance": "original-writer-instance-ci",
        "hostId": hashlib.sha256(b"test-host").hexdigest(),
        "writerReleaseSha256": hashlib.sha256(b"ci-writer-release").hexdigest(),
        "issuerReleaseSha256": hashlib.sha256(b"ci-issuer-release").hexdigest(),
        "policyGeneration": 3,
    }
    body = dict(original, schema=SCHEMA, purpose=PURPOSE,
                sequence=17, state="PENDING")
    raw = issue(signer, body)
    accepted = verify(raw, installed_ci_pin=pin, expected=original,
                      independent_floor=17)
    assert accepted["observation"] == "CI_SIGNED_PENDING_NOT_A_TRANSACTION_RESULT"
    assert all(accepted[k] is False for k in DENY)

    # The producer must not be able to substitute a caller-supplied key.
    require_hold(
        lambda: verify(issue(attacker, body), installed_ci_pin=pin,
                       expected=original, independent_floor=17),
        "WITNESS_SIGNATURE_MISMATCH",
    )
    # A signed original PENDING is not COMMITTED or REFUSED evidence.
    for status in ("COMMITTED", "REFUSED", "ALREADY_APPLIED", "UNKNOWN"):
        tampered = dict(body, state=status)
        require_hold(
            lambda x=tampered: verify(issue(signer, x), installed_ci_pin=pin,
                                     expected=original, independent_floor=17),
            "WRONG_PURPOSE_OR_UNTRUSTED_TERMINAL",
        )
    for invalid in (
        dict(body, purpose="timew-restore"),
        dict(body, purpose="hospital-room-trash"),
        dict(body, schema="postapollo.hospital.room-restore"),
    ):
        require_hold(
            lambda x=invalid: verify(issue(signer, x), installed_ci_pin=pin,
                                     expected=original, independent_floor=17),
            "WRONG_PURPOSE_OR_UNTRUSTED_TERMINAL",
        )

    # Even an otherwise valid packet for a second grant or writer cannot
    # rename the originally pinned request, COMMIT or scope.
    for name, value in (
        ("requestNonce", b64(b"\x22" * 32)),
        ("scopeDigest", "f"*64),
        ("commitDigest", "e"*64),
        ("grantDigest", "d"*64),
        ("writerInstance", "different-writer-instance-ci"),
        ("hostId", "c"*64),
        ("writerReleaseSha256", "b"*64),
        ("issuerReleaseSha256", "a"*64),
        ("policyGeneration", 4),
    ):
        changed = dict(body, **{name: value})
        require_hold(
            lambda x=changed: verify(issue(signer, x), installed_ci_pin=pin,
                                     expected=original, independent_floor=17),
            "ORIGINAL_TRANSACTION_IDENTITY_CHANGED",
        )

    # Independently pinned sequence 18 makes formerly signed sequence 17
    # unusable. An attacker-supplied future sequence does not advance floor.
    require_hold(
        lambda: verify(raw, installed_ci_pin=pin,
                       expected=original, independent_floor=18),
        "STALE_OR_UNPINNED_SEQUENCE",
    )
    next_body = dict(body, sequence=18)
    newer = issue(signer, next_body)
    require_hold(
        lambda: verify(newer, installed_ci_pin=pin,
                       expected=original, independent_floor=17),
        "STALE_OR_UNPINNED_SEQUENCE",
    )
    assert verify(
        newer, installed_ci_pin=pin,
        expected=original, independent_floor=18,
    )["canExecuteNewGrant"] is False
    for floor in (None, 0, True):
        require_hold(
            lambda x=floor: verify(raw, installed_ci_pin=pin,
                                  expected=original, independent_floor=x),
            "INDEPENDENT_CUSTODY_UNAVAILABLE" if floor is None
            else "INVALID_INDEPENDENT_FLOOR",
        )
    require_hold(
        lambda: verify(raw, installed_ci_pin=None,
                       expected=original, independent_floor=17),
        "INDEPENDENT_CUSTODY_UNAVAILABLE",
    )
    # Malformed/noncanonical/double-key bytes never bypass exact parser.
    require_hold(
        lambda: verify(raw.replace(b'"body":', b'"extra":1,"body":'),
                       installed_ci_pin=pin, expected=original,
                       independent_floor=17),
        "UNEXPECTED_ENVELOPE_FIELDS",
    )
    require_hold(
        lambda: verify(raw[:-1] + b',"body":{}}',
                       installed_ci_pin=pin, expected=original,
                       independent_floor=17),
        "DUPLICATE_JSON_FIELD",
    )
    require_hold(
        lambda: verify(raw + b"\n", installed_ci_pin=pin,
                       expected=original, independent_floor=17),
        "NONCANONICAL_WITNESS",
    )
    # Packet format cannot smuggle self-chosen trust keys, source status,
    # a replacement challenge or an extra authorization role.
    added = dict(body, publicKey=b64(b"\x44"*32))
    require_hold(
        lambda: verify(issue(signer, added), installed_ci_pin=pin,
                       expected=original, independent_floor=17),
        "UNEXPECTED_WITNESS_FIELDS",
    )
    assert not any(accepted[k] for k in DENY)

print(
    "HOSPITAL SIGNED PENDING HISTORY CI // PASS // pinned fixture signature, "
    "exact original request/commit/scope, writer/issuer release pinning, "
    "stale signed sequence & mismatched grants refused, "
    "missing pin/floor HOLD, PENDING never authorizes COMMITTED/REFUSED; "
    "no independent production custodian; native OFF"
)
