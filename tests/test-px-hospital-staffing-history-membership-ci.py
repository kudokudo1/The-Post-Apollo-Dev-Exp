#!/usr/bin/env python3
"""CI-only authenticated historical membership under an advancing head.

A full bounded hash-chain prefix is the *fixture membership proof*, NOT
production append-only custody, fork consistency, antirollback, HSM proof,
or a native writer recovery service. Test keys/head pins remain in one CI
process. An old PENDING is only an observation, never COMMITTED/REFUSED.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()
        or not sys.platform.startswith("linux")):
    raise SystemExit("HOSPITAL_HISTORY_MEMBERSHIP_HOLD // CI_ONLY")

ROOT = Path(__file__).resolve().parents[1]
PENDING = runpy.run_path(
    str(ROOT / "tests" / "test-px-hospital-staffing-signed-history-ci.py"),
    run_name="hospital_membership_pending_verifier",
)
SCHEMA = "postapollo.hospital.staffing-history-head.ci-v1"
PURPOSE = "hospital-original-request-append-history-head-ci-only"
HEAD_DOMAIN = b"postapollo.hospital.history-head.ci-v1\0"
LINK_DOMAIN = b"postapollo.hospital.history-link.ci-v1\0"
GENESIS = hashlib.sha256(b"postapollo.hospital.history-genesis.ci-v1\0").hexdigest()
HEAD_FIELDS = {
    "schema", "purpose", "hostId", "sequence", "headSha256",
    "writerReleaseSha256", "issuerReleaseSha256", "policyGeneration",
}
ENTRY_FIELDS = {"sequence", "requestNonce", "signedPendingSha256"}
MAX_RECORDS = 32
DENY = {
    "mayReuseOriginalRequest": False,
    "mayExecuteNewGrant": False,
    "sourceCommitted": False,
    "sourceRefused": False,
    "nativeTrustEstablished": False,
    "productionCustodyEstablished": False,
}


class MembershipHold(RuntimeError):
    pass


def hold(reason):
    raise MembershipHold("HOSPITAL_HISTORY_MEMBERSHIP_CI_HOLD // " + reason)


def canonical(obj):
    return PENDING["canonical"](obj)


def h(data):
    return hashlib.sha256(data).hexdigest()


def valid_hex(s):
    return type(s) is str and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            hold("DUPLICATE_FIELD")
        out[k] = v
    return out


def parse(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= 4096:
        hold("HEAD_FRAME_BOUNDS")
    try:
        obj = json.loads(raw.decode("ascii", "strict"),
                         object_pairs_hook=no_duplicates,
                         parse_constant=lambda _: hold("NONFINITE"))
    except (UnicodeError, ValueError, TypeError) as exc:
        hold("HEAD_FRAME_INVALID")
    if (type(obj) is not dict or set(obj) != {"body", "signature"}
            or type(obj["body"]) is not dict
            or set(obj["body"]) != HEAD_FIELDS):
        hold("HEAD_SHAPE_INVALID")
    if canonical(obj) != raw:
        hold("HEAD_NOT_CANONICAL")
    return obj


def linked_head(entries):
    if type(entries) not in (tuple, list) or not 1 <= len(entries) <= MAX_RECORDS:
        hold("BOUNDED_HISTORY_REQUIRED")
    head = GENESIS
    seen = set()
    for i, e in enumerate(entries, start=1):
        if type(e) is not dict or set(e) != ENTRY_FIELDS:
            hold("ENTRY_SHAPE_INVALID")
        if type(e["sequence"]) is not int or e["sequence"] != i:
            hold("ENTRY_SEQUENCE_GAP_OR_REORDER")
        if (type(e["requestNonce"]) is not str
                or len(e["requestNonce"]) != 43
                or e["requestNonce"] in seen):
            hold("DUPLICATE_OR_MALFORMED_REQUEST_NONCE")
        if not valid_hex(e["signedPendingSha256"]):
            hold("PENDING_DIGEST_INVALID")
        seen.add(e["requestNonce"])
        head = h(LINK_DOMAIN + bytes.fromhex(head) + canonical(e))
    return head


def signed_head(private, body):
    return canonical({
        "body": body,
        "signature": PENDING["b64"](private.sign(
            HEAD_DOMAIN + canonical(body))),
    })


def verify_historical_pending(*, entries, signed_current_head,
                              pinned_current_head, pinned_current_sequence,
                              pinned_head_signer, expected_context,
                              historical_pending_packet,
                              pinned_pending_signer, expected_pending):
    # Expected current head and release are separately supplied CI pins.
    # A signed old checkpoint cannot select its own trusted head or floor.
    if (pinned_head_signer is None or pinned_pending_signer is None
            or pinned_current_head is None or pinned_current_sequence is None):
        hold("INDEPENDENT_CURRENT_CUSTODY_UNAVAILABLE")
    if (type(pinned_current_sequence) is not int
            or not 1 <= pinned_current_sequence <= MAX_RECORDS
            or not valid_hex(pinned_current_head)):
        hold("INVALID_CURRENT_HEAD_ANCHOR")
    if (type(expected_context) is not dict
            or set(expected_context) != HEAD_FIELDS -
                {"schema", "purpose", "sequence", "headSha256"}):
        hold("EXTERNALLY_EXPECTED_RELEASE_REQUIRED")
    if (type(expected_pending) is not dict
            or set(expected_pending) != PENDING["FIELDS"] -
                {"schema", "purpose", "state", "sequence"}):
        hold("EXPECTED_ORIGINAL_IDENTITY_REQUIRED")
    if type(historical_pending_packet) is not bytes:
        hold("ORIGINAL_SIGNED_PENDING_REQUIRED")

    packet = parse(signed_current_head)
    body = packet["body"]
    if body["schema"] != SCHEMA or body["purpose"] != PURPOSE:
        hold("WRONG_SIGNED_HISTORY_PURPOSE")
    if (type(body["sequence"]) is not int
            or body["sequence"] != pinned_current_sequence
            or len(entries) != pinned_current_sequence):
        hold("OLD_OR_UNPINNED_HISTORY_HEAD")
    if any(body[k] != expected_context[k] for k in expected_context):
        hold("HOST_OR_RELEASE_CHANGED")
    head = linked_head(entries)
    if (head != pinned_current_head
            or body["headSha256"] != pinned_current_head):
        hold("HEAD_FORK_OR_MISSING_HISTORY")
    try:
        pinned_head_signer.verify(
            PENDING["unb64"](packet["signature"], 64),
            HEAD_DOMAIN + canonical(body),
        )
    except InvalidSignature:
        hold("HEAD_SIGNER_NOT_PINNED")

    matching = [e for e in entries
                if e["requestNonce"] == expected_pending["requestNonce"]]
    if len(matching) != 1:
        hold("ORIGINAL_REQUEST_NOT_IN_CURRENT_HISTORY")
    historical = matching[0]
    if historical["signedPendingSha256"] != h(historical_pending_packet):
        hold("SIGNED_PENDING_BYTES_NOT_IN_HISTORY")
    try:
        observed = PENDING["verify"](
            historical_pending_packet,
            installed_ci_pin=pinned_pending_signer,
            expected=expected_pending,
            # The authenticated *historical membership* pins this older
            # per-request sequence. It is NOT the global current floor;
            # current head is checked separately above.
            independent_floor=historical["sequence"],
        )
    except PENDING["HistoryHold"] as exc:
        raise MembershipHold(
            "HOSPITAL_HISTORY_MEMBERSHIP_CI_HOLD // "
            "ORIGINAL_PENDING_EVIDENCE_INVALID"
        ) from exc
    assert observed["canExecuteNewGrant"] is False
    assert observed["canDeclareCommitted"] is False
    assert observed["canDeclareRefused"] is False
    return {
        "observation": "CI_HISTORICAL_PENDING_UNDER_CURRENT_ANCHORED_HEAD",
        "historicalSequence": historical["sequence"],
        "currentSequence": pinned_current_sequence,
        "currentHeadSha256": head,
        **DENY,
    }


def denied(cb, expected):
    try:
        cb()
    except MembershipHold as exc:
        assert expected in str(exc), (expected, str(exc))
        return
    raise AssertionError("HISTORY_MEMBERSHIP_UNEXPECTEDLY_ACCEPTED")


with tempfile.TemporaryDirectory(
        prefix="hospital-history-membership-ci-",
        dir=os.environ["RUNNER_TEMP"]) as td:
    assert Path(td).is_dir()
    pending_key = Ed25519PrivateKey.generate()
    head_key = Ed25519PrivateKey.generate()
    wrong_key = Ed25519PrivateKey.generate()
    origin = {
        "requestNonce": PENDING["b64"](b"\x11"*32),
        "scopeDigest": h(b"historic-source-scope"),
        "commitDigest": h(b"historic-exact-commit"),
        "grantDigest": h(b"historic-original-grant"),
        "writerInstance": "historical-ci-writer-v1",
        "hostId": h(b"ci-pinned-host"),
        "writerReleaseSha256": h(b"ci-writer-release"),
        "issuerReleaseSha256": h(b"ci-issuer-release"),
        "policyGeneration": 7,
    }
    def original_pending(expected, sequence):
        return PENDING["issue"](pending_key, dict(
            expected,
            schema=PENDING["SCHEMA"],
            purpose=PENDING["PURPOSE"],
            state="PENDING",
            sequence=sequence,
        ))
    old_packet = original_pending(origin, 1)
    new_ident = [
        dict(origin, requestNonce=PENDING["b64"](b"\x22"*32),
             commitDigest=h(b"another-commit"),
             grantDigest=h(b"another-grant")),
        dict(origin, requestNonce=PENDING["b64"](b"\x33"*32),
             commitDigest=h(b"third-commit"),
             grantDigest=h(b"third-grant")),
        dict(origin, requestNonce=PENDING["b64"](b"\x44"*32),
             commitDigest=h(b"fourth-commit"),
             grantDigest=h(b"fourth-grant")),
    ]
    new_packets = [
        original_pending(item, index)
        for index, item in enumerate(new_ident, start=2)
    ]
    entries = [
        {"sequence":i+1,
         "requestNonce":v["requestNonce"],
         "signedPendingSha256":h(pkt)}
        for i,(v,pkt) in enumerate(
            zip([origin]+new_ident, [old_packet]+new_packets))
    ]
    context = {k:origin[k] for k in (
        "hostId", "writerReleaseSha256", "issuerReleaseSha256",
        "policyGeneration")}
    def head_packet(items):
        return signed_head(head_key, dict(
            context, schema=SCHEMA, purpose=PURPOSE,
            sequence=len(items), headSha256=linked_head(items),
        ))
    def verify(items, pkt, *, query=origin, old=old_packet,
               signer=None, oldsigner=None, root=None, floor=None,
               external=context):
        return verify_historical_pending(
            entries=items, signed_current_head=pkt,
            pinned_current_head=linked_head(items) if root is None else root,
            pinned_current_sequence=len(items) if floor is None else floor,
            pinned_head_signer=head_key.public_key() if signer is None else signer,
            expected_context=external,
            historical_pending_packet=old,
            pinned_pending_signer=pending_key.public_key()
                if oldsigner is None else oldsigner,
            expected_pending=query,
        )

    assert verify(entries[:1],head_packet(entries[:1]))["historicalSequence"]==1
    current = head_packet(entries)
    pinned_current_head = linked_head(entries)
    older = verify(entries,current)
    assert (older["historicalSequence"],older["currentSequence"]) == (1,4)
    assert all(older[k] is False for k in DENY)
    # A legitimate later request has distinct nonce and remains observable
    # as its OWN PENDING under the same current head, without authorizing it.
    newest=verify(entries,current,query=new_ident[3-1],old=new_packets[3-1])
    assert (newest["historicalSequence"],newest["currentSequence"]) == (4,4)
    assert newest["mayExecuteNewGrant"] is False

    # A valid old signed head must not be accepted as the independently
    # anchored current head. It cannot delete later reservations.
    denied(lambda:verify_historical_pending(
        entries=entries[:1],signed_current_head=head_packet(entries[:1]),
        pinned_current_head=pinned_current_head,pinned_current_sequence=4,
        pinned_head_signer=head_key.public_key(),expected_context=context,
        historical_pending_packet=old_packet,
        pinned_pending_signer=pending_key.public_key(),
        expected_pending=origin,
    ),"OLD_OR_UNPINNED_HISTORY_HEAD")

    # Tamper, truncate, reorder or fork the full bounded history prefix
    # while retaining separately pinned current head: all must fail.
    for corrupted in (
        entries[:3],
        entries[:2] + entries[3:],
        list(reversed(entries)),
        [entries[0], entries[0], *entries[2:]],
        [dict(entries[0], signedPendingSha256="f"*64), *entries[1:]],
        [dict(entries[0], requestNonce=PENDING["b64"](b"\x55"*32)),
         *entries[1:]],
    ):
        denied(lambda x=corrupted:verify_historical_pending(
            entries=x,signed_current_head=current,
            pinned_current_head=pinned_current_head,pinned_current_sequence=4,
            pinned_head_signer=head_key.public_key(),expected_context=context,
            historical_pending_packet=old_packet,
            pinned_pending_signer=pending_key.public_key(),
            expected_pending=origin,
        ),"HOLD")

    # Same head but wrong signing authority cannot authenticate the head.
    denied(lambda:verify(entries,current,signer=wrong_key.public_key()),
           "HEAD_SIGNER_NOT_PINNED")
    denied(lambda:verify(entries,current,
                         oldsigner=wrong_key.public_key()),
           "ORIGINAL_PENDING_EVIDENCE_INVALID")
    denied(lambda:verify(entries,current,
                         external=dict(context,policyGeneration=8)),
           "HOST_OR_RELEASE_CHANGED")
    denied(lambda:verify(entries,current,
                         query=dict(origin,grantDigest="0"*64)),
           "ORIGINAL_PENDING_EVIDENCE_INVALID")
    denied(lambda:verify(entries,current,old=new_packets[0]),
           "SIGNED_PENDING_BYTES_NOT_IN_HISTORY")
    denied(lambda:verify(entries,current,root="f"*64),
           "HEAD_FORK_OR_MISSING_HISTORY")
    denied(lambda:verify(entries,current,floor=5),
           "OLD_OR_UNPINNED_HISTORY_HEAD")
    # No current independently pinned head/key is still UNKNOWN/HOLD.
    denied(lambda:verify_historical_pending(
        entries=entries,signed_current_head=current,
        pinned_current_head=None,pinned_current_sequence=4,
        pinned_head_signer=head_key.public_key(),expected_context=context,
        historical_pending_packet=old_packet,
        pinned_pending_signer=pending_key.public_key(),
        expected_pending=origin,
    ),"INDEPENDENT_CURRENT_CUSTODY_UNAVAILABLE")

print(
    "HOSPITAL HISTORY MEMBERSHIP CI // PASS // old signed PENDING retained "
    "under later pinned head, new request distinct, rollback/fork/truncation/"
    "signature/identity/pin mismatch HOLD, no outcome or grant authority; "
    "no production antirollback custodian"
)
