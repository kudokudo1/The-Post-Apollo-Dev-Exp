"""Hospital writer-owned staffing COMMIT ledger reconciliation, CI-only.

A source transaction can commit, then lose its reply. The v13 draft ledger
is written in that transaction, but currently lacks requestNonce,
writerInstance and an independently authenticated durable recovery receipt.

This module inspects DISPOSABLE v13 ledgers only. It never sends/retries a
COMMIT, authenticates an installed writer, certifies consent, or authorizes
staffing. Positive fixture matches are not production COMMITTED receipts;
missing records are UNKNOWN, never proof of refusal.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3

import px_hospital_staffing_grants as grants
import px_hospital_staffing_operator_review as review
import px_hospital_staffing_transport as transport

SCHEMA = "postapollo.hospital.staffing-ledger-observation.ci-v1"
MATCH = "CI_LEDGER_ROW_MATCH_OBSERVED_NOT_AUTHENTICATED"
UNKNOWN = "CI_NO_MATCHING_LEDGER_ROW_OUTCOME_UNKNOWN"
LEDGER_COLUMNS = frozenset((
    "nonce", "grant_digest", "approval_id", "room_id", "operation",
    "operator_id", "session_id", "graph_digest", "consumed_at",
))
PREPARED_FIELDS = frozenset((
    "schema", "requestNonce", "roomId", "action", "expectedRevision",
    "expectedDigest", "writerInstance", "state", "expiresInSeconds",
    "operatorAuthenticated", "requiresExternalConsent",
))
DENIED = {
    "independentlyAuthenticatedHospitalWriter": False,
    "nativeWriterReceiptVerified": False,
    "historicalSigningAuthorityVerified": False,
    "liveHospitalTransactionVerified": False,
    "liveHospitalReplayProtectionVerified": False,
    "nativeOperatorConsentVerified": False,
    "canRetrySameGrant": False,
    "canAttachSession": False,
    "canSucceedDoctor": False,
    "productionAuthority": False,
}


class LedgerRecoveryHold(RuntimeError):
    pass


def hold(reason):
    raise LedgerRecoveryHold("HOSPITAL_STAFFING_LEDGER_RECOVERY_HOLD // " + reason)


def _fixture_only():
    if (os.environ.get("CI") != "true"
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or not os.environ.get("RUNNER_TEMP")
            or not Path(os.environ["RUNNER_TEMP"]).is_dir()):
        hold("CI_ONLY_RECOVERY_NOT_INSTALLED")


def _prepared(raw):
    if type(raw) is not bytes or not 2 <= len(raw) <= 16384:
        hold("BOUNDED_PREPARED_REQUIRED")
    try:
        obj = json.loads(raw.decode("ascii", "strict"),
                         object_pairs_hook=transport._unique,
                         parse_constant=transport._nonfinite)
        if (type(obj) is not dict or set(obj) != PREPARED_FIELDS
                or transport.canonical(obj) != raw):
            hold("EXACT_CANONICAL_PREPARED_REQUIRED")
    except (transport.NativeStaffingTransportHold, ValueError, UnicodeError,
            RecursionError, TypeError, OverflowError) as exc:
        raise LedgerRecoveryHold(
            "HOSPITAL_STAFFING_LEDGER_RECOVERY_HOLD // INVALID_PREPARED"
        ) from exc
    if (obj["schema"] != review.PREPARED_SCHEMA
            or obj["state"] != "ACTIVE"
            or obj["operatorAuthenticated"] is not False
            or obj["requiresExternalConsent"] is not True
            or type(obj["expectedRevision"]) is not int
            or not 0 <= obj["expectedRevision"] < 1_000_000_000
            or type(obj["expectedDigest"]) is not str
            or grants.DIGEST.fullmatch(obj["expectedDigest"]) is None
            or type(obj["expiresInSeconds"]) is not int
            or not 0 < obj["expiresInSeconds"] <= 45
            or type(obj["writerInstance"]) is not str
            or transport.WRITER.fullmatch(obj["writerInstance"]) is None):
        hold("UNTRUSTED_PREPARED_SOURCE")
    return obj


def inspect_ci_only(db, *, original_prepare_raw, prepared_raw, commit_raw,
                    previously_verified_fixture_grant):
    """Read only exact v13 fixture ledger; no authenticated outcome or retry.

    previously_verified_fixture_grant must come from actual Ed25519 bytes
    verified by a caller-selected test key. That is cryptographic testing,
    NOT pinned production signer or historical release provenance.
    """
    _fixture_only()
    if (not isinstance(db, sqlite3.Connection)
            or db.in_transaction or db.row_factory is not sqlite3.Row
            or db.execute("PRAGMA foreign_keys").fetchone()[0] != 1):
        hold("PROTECTED_CI_SQLITE_SNAPSHOT_REQUIRED")
    version = db.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    if version is None or version[0] != "13":
        hold("CANDIDATE_V13_LEDGER_REQUIRED")
    cols = db.execute(
        "PRAGMA table_info(hospital_staffing_authorizations)"
    ).fetchall()
    if {r["name"] for r in cols} != LEDGER_COLUMNS:
        hold("EXACT_V13_LEDGER_REQUIRED")
    prepared = _prepared(prepared_raw)
    try:
        initial = transport.parse_request(original_prepare_raw)
        commit = transport.parse_request(commit_raw)
    except (transport.NativeStaffingTransportHold, TypeError, ValueError) as exc:
        raise LedgerRecoveryHold(
            "HOSPITAL_STAFFING_LEDGER_RECOVERY_HOLD // ORIGINAL_REQUEST_REFUSED"
        ) from exc
    if initial["kind"] != transport.KIND_PREPARE or commit["kind"] != transport.KIND_COMMIT:
        hold("ORIGINAL_PREPARE_AND_COMMIT_REQUIRED")
    for key in transport.PREPARE_FIELDS - {"kind"}:
        if initial[key] != commit[key]:
            hold("CHANGED_REQUEST_CONTEXT")
    for key in ("roomId", "action", "requestNonce"):
        if prepared[key] != initial[key]:
            hold("CHANGED_PREPARED_CONTEXT")
    if commit["writerInstance"] != prepared["writerInstance"]:
        hold("CHANGED_WRITER_INSTANCE")
    expected = (initial["intent"]["sessionId"]
                if initial["action"] == grants.ATTACH
                else initial["intent"]["newSessionId"])

    verified = previously_verified_fixture_grant
    if (not isinstance(verified, grants.VerifiedStaffingGrant)
            or type(verified._signed_raw) is not bytes):
        hold("CI_VERIFIED_GRANT_OBJECT_REQUIRED")
    envelope = transport._decode_b64(
        commit["signedEnvelope"], max_length=transport.MAX_GRANT_BYTES)
    if verified._signed_raw != envelope:
        hold("SIGNED_ENVELOPE_BYTES_CHANGED")
    signed = verified.body
    if (type(signed) is not dict
            or set(signed) != grants.BODY_FIELDS
            or hashlib.sha256(grants.DOMAIN + grants.canonical(signed)).hexdigest()
            != verified.digest):
        hold("SIGNED_CI_GRANT_CHANGED")
    if (signed["operation"] != initial["action"]
            or signed["scope"] != initial["intent"]
            or signed["requestNonce"] != initial["requestNonce"]
            or signed["writerInstance"] != prepared["writerInstance"]
            or signed["roomRevision"] != prepared["expectedRevision"]
            or signed["graphDigest"] != prepared["expectedDigest"]):
        hold("SIGNED_REQUEST_PREPARE_GRAPH_CHANGED")
    digest = review.review_digest(
        initial, prepared, operator_uid=signed["operatorUid"],
        seat_id=signed["seatId"],
        client_sha=signed["clientExecutableSha256"],
        issuer_release_sha=signed["issuerReleaseSha256"],
        policy_generation=signed["policyGeneration"],
    )
    if (signed["reviewDigest"] != digest
            or signed["polkitActionId"] != review.ACTION_IDS[initial["action"]]):
        hold("SIGNED_ORIGINAL_OPERATOR_REVIEW_CHANGED")

    # Source ledger has no original requestNonce/writerInstance columns.
    # Match all independently stored identities and reject collisions.
    try:
        entries = db.execute(
            """SELECT nonce, grant_digest, approval_id, room_id, operation,
                      operator_id, session_id, graph_digest
               FROM hospital_staffing_authorizations
               WHERE nonce=? OR grant_digest=? OR approval_id=?
               LIMIT 4""",
            (signed["nonce"], verified.digest, signed["approvalId"])
        ).fetchall()
    except sqlite3.Error as exc:
        raise LedgerRecoveryHold(
            "HOSPITAL_STAFFING_LEDGER_RECOVERY_HOLD // LEDGER_READ_UNAVAILABLE"
        ) from exc
    matches = {
        "nonce": signed["nonce"], "grant_digest": verified.digest,
        "approval_id": signed["approvalId"], "room_id": initial["roomId"],
        "operation": initial["action"], "operator_id": signed["operatorId"],
        "session_id": expected, "graph_digest": signed["graphDigest"],
    }
    if len(entries) > 1 or (entries and any(
            str(entries[0][key]) != str(value)
            for key, value in matches.items())):
        hold("DURABLE_LEDGER_COLLISION_OR_SCOPE_CONFLICT")
    # There is deliberately NO route from a missing row to a safe retry.
    # A lost, withheld or rolled-back local ledger cannot prove that the
    # original protected writer refused or never committed elsewhere.
    observed = len(entries) == 1
    return {
        "schema": SCHEMA,
        "status": MATCH if observed else UNKNOWN,
        "requestNonceFromUntrustedFixture": initial["requestNonce"],
        "writerInstanceFromUntrustedFixture": prepared["writerInstance"],
        "grantDigestFromFixture": verified.digest,
        "roomIdFromFixture": initial["roomId"],
        "actionFromFixture": initial["action"],
        "sessionIdFromFixture": expected,
        "matchingDisposableLedgerRowObserved": observed,
        "absentLedgerIsNotProofOfRefusal": True,
        "recoveryRequiresProtectedWriter": True,
        "neverAutoRetryThisGrant": True,
        **DENIED,
    }


def recover_native_staffing(*_args, **_kwargs):
    hold("NATIVE_STAFFING_RECOVERY_NOT_INSTALLED")
