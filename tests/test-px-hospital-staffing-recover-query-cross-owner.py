#!/usr/bin/env python3
"""Hospital cross-owner witness of Connections proposed RECOVER query, CI ONLY.

This tests an exact pinned Connections #2103 draft against real Hospital
#133 framing and existing fixture constants. It does not select a production
RECOVER schema, issue a challenge, sign or authenticate anything, query the
protected database, or install a native socket/endpoint. No production
COMMITTED or REFUSED outcome can result from these bytes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()
        or not sys.platform.startswith("linux")):
    raise SystemExit("HOSPITAL_RECOVER_CROSS_OWNER_HOLD // CI_ONLY")

ROOT = Path(__file__).resolve().parents[1]
C_ROOT = ROOT / "connections-staffing-recover-proposal"
if not C_ROOT.is_dir():
    raise SystemExit("HOSPITAL_RECOVER_CROSS_OWNER_HOLD // PINNED_CONNECTIONS_SOURCE_MISSING")
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(C_ROOT / "services/connections/hospital/staffing"))

import px_hospital_staffing_grants as HGrant
import px_hospital_staffing_prepare_commit as HCoordinator
import px_hospital_staffing_transport as HTransport
import StaffingTransportPreflight as CT
import StaffingReceiptIdentityPreflight as CR
import StaffingRecoveryQueryPreflight as CQ

def encoded(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

def rejects(fn, token):
    try:
        fn()
    except (CQ.RecoveryQueryHold, HTransport.NativeStaffingTransportHold) as exc:
        assert token in str(exc), (token, str(exc))
        return
    raise AssertionError("HOSPITAL_RECOVER_CROSS_OWNER_HOLD // EXPECTED_REFUSAL_" + token)

assert CT.REQUEST_SCHEMA == HTransport.SCHEMA
assert CT.MAX_FRAME == HTransport.MAX_FRAME == 16384
assert CT.MAX_GRANT_BYTES == HTransport.MAX_GRANT_BYTES == 8192
assert CT.PREPARE_FIELDS == HTransport.PREPARE_FIELDS
assert CT.COMMIT_FIELDS == HTransport.COMMIT_FIELDS
assert CQ.PROTOCOL_VERSION == 1  # Unapproved CI proposal; NOT a native version.
assert CQ.SCHEMA != HTransport.SCHEMA
assert CQ.KIND not in (HTransport.KIND_PREPARE, HTransport.KIND_COMMIT)
assert CR.PREPARED_SCHEMA == HCoordinator.PREPARED_SCHEMA
assert CR.GRANT_DOMAIN == HGrant.DOMAIN
assert set(CQ.DENIED) and all(v is False for v in CQ.DENIED.values())

scope = {
    "roomId": "ci-room", "patientId": "ci-patient",
    "repository": "org/repo", "branch": "feature/staffing",
    "bedPath": "/tmp/nonexistent-ci-bed", "assignmentId": "1",
    "sessionId": "ci-session", "doctorId": "ci-doctor",
    "providerId": "ci-provider", "mode": "create",
}
original = {
    "schema": HTransport.SCHEMA, "kind": HTransport.KIND_PREPARE,
    "action": HGrant.ATTACH, "roomId": scope["roomId"],
    "intent": scope, "requestNonce": encoded(b"P"*32),
}
prepared = {
    "schema": HCoordinator.PREPARED_SCHEMA,
    "requestNonce": original["requestNonce"],
    "roomId": original["roomId"], "action": original["action"],
    "expectedRevision": 5, "expectedDigest": "a"*64,
    "writerInstance": "writer-fixture-001",
    "state": "ACTIVE", "expiresInSeconds": 40,
    "operatorAuthenticated": False,
    "requiresExternalConsent": True,
}
body = {
    "schema": HGrant.SCHEMA, "audience": HGrant.AUDIENCE,
    "operation": HGrant.ATTACH, "scope": scope,
    "roomRevision": 5, "graphDigest": "a"*64,
    "operatorId": "uid:1001", "approvalId": "ci-approval-fixture-01",
    "seatId": "logind-seat0-ciFixture", "hostId": "b"*64,
    "nonce": encoded(b"N"*32), "requestNonce": original["requestNonce"],
    "writerInstance": prepared["writerInstance"], "issuedAt": 1760000000,
    "expiresAt": 1760000025, "operatorUid": 1001,
    "polkitActionId": HGrant.POLKIT_ACTIONS[HGrant.ATTACH],
    "policyGeneration": 3, "clientExecutableSha256": "c"*64,
    "issuerReleaseSha256": "d"*64, "reviewDigest": "e"*64,
}
assert set(body) == HGrant.BODY_FIELDS
# Deliberately synthetic Ed25519-shaped signature, NOT cryptographic trust.
synthetic_signed = CT.canonical({
    "body": body, "signature": encoded(b"\x91"*64)
})
original_raw = HTransport.canonical(original)
prepared_raw = HTransport.canonical(prepared)
commit_raw = CT.compose_commit(
    original_raw, prepared["writerInstance"], synthetic_signed
)
assert HTransport.parse_request(original_raw)["kind"] == "prepare"
assert HTransport.parse_request(commit_raw)["kind"] == "commit"
assert HTransport.canonical(HTransport.parse_request(commit_raw)) == commit_raw
assert len(commit_raw) < HTransport.MAX_FRAME

query_id = "11111111-1111-4111-8111-111111111111"
challenge = b"C"*32  # Caller-supplied, NOT authenticated freshness.
time_ms = 1760000000000
args = dict(
    original_prepare_raw=original_raw, prepared_raw=prepared_raw,
    commit_raw=commit_raw, query_id=query_id, challenge=challenge,
    issued_ms=time_ms, expires_ms=time_ms+1000, now_ms=time_ms
)
built = CQ.candidate_query_ci_only(**args)
raw = built["candidateQueryRawForTestOnly"]
query = json.loads(raw)
assert set(query) == CQ.FIELDS
assert query["originalPrepareSha256"] == hashlib.sha256(original_raw).hexdigest()
assert query["preparedSha256"] == hashlib.sha256(prepared_raw).hexdigest()
assert query["commitSha256"] == hashlib.sha256(commit_raw).hexdigest()
assert query["originalScopeSha256"] == hashlib.sha256(
    HTransport.canonical(scope)).hexdigest()
assert query["requestNonce"] == original["requestNonce"]
assert query["writerInstance"] == prepared["writerInstance"]
assert query["grantDigest"] == hashlib.sha256(
    HGrant.DOMAIN + HTransport.canonical(body)).hexdigest()
assert query["grantNonce"] == body["nonce"]
assert query["reviewDigest"] == body["reviewDigest"]
assert query["roomId"] == scope["roomId"]
assert query["sessionId"] == scope["sessionId"]
assert query["action"] == HGrant.ATTACH
assert query["challengeB64"] == encoded(challenge)
assert len(raw) <= HTransport.MAX_FRAME
assert built["originalCommitOutcome"] == "UNKNOWN"
assert built["canSendRecoveryQuery"] is False
assert built["recoveryProtocolAcceptedByHospital"] is False

def inspect(raw_query, **overrides):
    supplied = dict(
        candidate_query_raw=raw_query,
        original_prepare_raw=original_raw,
        prepared_raw=prepared_raw, commit_raw=commit_raw,
        now_ms=time_ms, expected_query_id=query_id,
        expected_challenge=challenge)
    supplied.update(overrides)
    return CQ.inspect_candidate_query_ci_only(**supplied)

match = inspect(raw)
assert match["status"] == "UNTRUSTED_RECOVERY_QUERY_IDENTITY_MATCH_ONLY"
assert match["originalCommitOutcome"] == "UNKNOWN"
assert match["noSameGrantRetryEverFromThisObservation"] is True
assert all(match[key] is False for key in CQ.DENIED)
# Test fixture accepts a replay of the same query; it does NOT provide
# a durable, independently minted/replayed challenge.
assert inspect(raw) == match
assert inspect(raw)["challengeReplayProtected"] is False

# The protected Hospital staffing parser must NOT accept Connections'
# proposal as a native request, even if the fixture query is well-shaped.
rejects(lambda:HTransport.parse_request(raw), "WRONG_PROTOCOL_DOMAIN")

# Mutations of the original operation, hash, grant, response-looking
# fields, challenge and purported version cannot acquire native authority.
for field in ("requestNonce", "writerInstance", "commitSha256",
              "grantDigest", "reviewDigest", "roomId", "sessionId",
              "originalScopeSha256", "approvalId", "originalPrepareSha256",
              "preparedSha256", "graphDigest", "grantNonce"):
    altered = dict(query, **{field: "attacker-controlled"})
    rejects(lambda value=altered:inspect(CT.canonical(value)),
            "QUERY_PROTOCOL_OR_ORIGINAL_IDENTITY_CHANGED")
for field, value in (("protocolVersion", 2), ("kind", "commit"),
                     ("schema", HTransport.SCHEMA)):
    rejects(lambda f=field,v=value:inspect(
        CT.canonical(dict(query, **{f:v}))),
        "QUERY_PROTOCOL_OR_ORIGINAL_IDENTITY_CHANGED")
rejects(lambda:inspect(CT.canonical(dict(query, status="COMMITTED"))),
        "QUERY_FIELDS_CHANGED")
rejects(lambda:inspect(CT.canonical(dict(query, challengeB64=encoded(b"D"*32)))),
        "QUERY_NOT_BOUND_TO_EXPECTED_CHALLENGE")
rejects(lambda:inspect(raw, expected_challenge=b"D"*32),
        "QUERY_NOT_BOUND_TO_EXPECTED_CHALLENGE")
rejects(lambda:inspect(raw, expected_query_id=str(uuid.uuid4())),
        "QUERY_NOT_BOUND_TO_EXPECTED_CHALLENGE")
rejects(lambda:inspect(raw[:-1]+b',"queryId":"duplicate"}'),
        "INVALID_QUERY_FRAME")
rejects(lambda:inspect(raw, now_ms=time_ms+5000), "QUERY_STALE_OR_UNBOUNDED")
# A fake altered original scope can never validate the original COMMIT.
wrong = dict(original, intent=dict(scope, sessionId="other-session"))
rejects(lambda:inspect(raw, original_prepare_raw=CT.canonical(wrong)),
        "INVALID_ORIGINAL_SOURCE")

rejects(lambda:CQ.run_native_staffing_recover_query(
    approved=True, canSendRecoveryQuery=True),
    "NATIVE_RECOVERY_REQUEST_NOT_APPROVED_OR_INSTALLED")
assert not hasattr(CQ, "verify_native_receipt")
assert not hasattr(CQ, "dispatch_recover")
assert not hasattr(CQ, "retry_original_commit")
assert query["kind"] != HTransport.KIND_COMMIT

print(
    "HOSPITAL CROSS-OWNER CONNECTIONS RECOVER QUERY // PASS // "
    "exact pinned query-source identities, Hospital parser separation, "
    "changed digest/challenge refusals, replay remains untrusted; NATIVE OFF"
)
