#!/usr/bin/env python3
"""Hospital Session/Doctor operator review and Polkit separation, CI only.

No native authorization, login1 invocation, system Polkit installation,
operator identity, actual root issuer or live Hospital DB is touched.
The existing C5-H2 Room Trash/Restore issuer stays independently owned.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import os
from pathlib import Path
import secrets
import sys
import xml.etree.ElementTree as ET

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()):
    raise SystemExit("HOSPITAL_STAFFING_OPERATOR_REVIEW_HOLD // CI_ONLY")

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"bin"))
import px_hospital_staffing_grants as grants
import px_hospital_staffing_operator_review as review
import px_hospital_staffing_transport as transport

def refuse(callback, reason):
    try:
        callback()
    except (review.StaffingReviewHold,
            transport.NativeStaffingTransportHold) as exc:
        assert reason in str(exc), (reason,str(exc))
        return
    raise AssertionError("STAFFING_OPERATOR_REVIEW_IMPROPERLY_ACCEPTED")

def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

intent=dict(
    roomId="room-ci",patientId="patient-ci",repository="org/repo",
    branch="feat/test",bedPath="/tmp/hospital-ci",
    assignmentId="1",sessionId="session-ci",doctorId="doctor-ci",
    providerId="provider-ci",mode="create",
)
req=dict(
    schema=transport.SCHEMA,kind=transport.KIND_PREPARE,
    action=grants.ATTACH,roomId=intent["roomId"],intent=intent,
    requestNonce=b64(secrets.token_bytes(32)),
)
prepared=dict(
    schema=review.PREPARED_SCHEMA,requestNonce=req["requestNonce"],
    roomId="room-ci",action=grants.ATTACH,expectedRevision=5,
    expectedDigest="a"*64,writerInstance="writer-ci-fixture-001",
    state="ACTIVE",expiresInSeconds=40,
    operatorAuthenticated=False,requiresExternalConsent=True,
)
witness=dict(
    operator_uid=1001,seat_id="logind-seat0-ciFixture",
    client_sha="b"*64,issuer_release_sha="c"*64,
    policy_generation=4,
)
expected=review.review_digest(req,prepared,**witness)
assert len(expected)==64
assert expected==review.review_digest(
    dict(reversed(list(req.items()))),
    dict(reversed(list(prepared.items()))),**witness)
summary=review.review_summary(req,prepared,**witness)
assert summary["actionId"]=="org.postapollo.hospital.session-attach"
assert summary["reviewDigest"]==expected
assert summary["operatorAuthorized"] is False
assert summary["polkitCompleted"] is False
assert summary["installedSignedReleaseVerified"] is False
for piece in (
    "Session session-ci","Doctor doctor-ci","Provider provider-ci",
    "Room room-ci","Patient patient-ci","repository org/repo",
    "Assignment 1","Bed /tmp/hospital-ci","revision 5",
    "graph "+"a"*64,"request "+req["requestNonce"],
    "seat logind-seat0-ciFixture",
):
    assert piece in summary["detail"], piece

def changed_request(**fields):
    data=deepcopy(req)
    data.update(fields)
    return data

def changed_prepared(**fields):
    data=deepcopy(prepared)
    data.update(fields)
    return data

for newer in (
    changed_request(requestNonce=b64(secrets.token_bytes(32))),
    changed_request(intent=dict(intent,sessionId="different-session")),
    changed_request(intent=dict(intent,doctorId="different-doctor")),
):
    if newer["requestNonce"] != prepared["requestNonce"]:
        refuse(lambda n=newer:review.review_digest(n,prepared,**witness),
               "UNTRUSTED_OR_STALE_PREPARED_SOURCE")
    else:
        assert review.review_digest(newer,prepared,**witness)!=expected

for altered in (
    changed_prepared(expectedRevision=6),
    changed_prepared(expectedDigest="f"*64),
    changed_prepared(writerInstance="writer-ci-restarted-002"),
):
    assert review.review_digest(req,altered,**witness)!=expected

for altered in (
    changed_prepared(state="TRASHED"),
    changed_prepared(expiresInSeconds=0),
    changed_prepared(expiresInSeconds=46),
    changed_prepared(operatorAuthenticated=True),
    changed_prepared(requiresExternalConsent=False),
    changed_prepared(expectedDigest="bad"),
    changed_prepared(action=grants.SUCCEED),
):
    refuse(lambda s=altered:review.review_digest(req,s,**witness),
           "UNTRUSTED_OR_STALE_PREPARED_SOURCE")

for altered in (
    dict(witness,operator_uid=1002),
    dict(witness,seat_id="logind-seat1-ciFixture"),
    dict(witness,client_sha="d"*64),
    dict(witness,issuer_release_sha="e"*64),
    dict(witness,policy_generation=5),
):
    assert review.review_digest(req,prepared,**altered)!=expected

for altered, message in (
    (dict(witness,operator_uid=True),"NONROOT_OPERATOR_UID_REQUIRED"),
    (dict(witness,operator_uid=0),"NONROOT_OPERATOR_UID_REQUIRED"),
    (dict(witness,seat_id="XDG_SESSION_ID=1"),
     "NATIVE_ACTIVE_LOGIN1_SEAT_REQUIRED"),
    (dict(witness,seat_id="logind-seat0-not a session"),
     "NATIVE_ACTIVE_LOGIN1_SEAT_REQUIRED"),
    (dict(witness,client_sha="unknown"),
     "RELEASE_DIGEST_EVIDENCE_REQUIRED"),
    (dict(witness,issuer_release_sha=None),
     "RELEASE_DIGEST_EVIDENCE_REQUIRED"),
    (dict(witness,policy_generation=0),
     "ROOT_POLICY_GENERATION_REQUIRED"),
    (dict(witness,policy_generation=True),
     "ROOT_POLICY_GENERATION_REQUIRED"),
):
    refuse(lambda w=altered:review.review_digest(req,prepared,**w),message)

# A syntactically VALID COMMIT frame still cannot generate the
# initial operator review; the phase must be the original PREPARE.
valid_commit=dict(req,kind="commit",
                  writerInstance=prepared["writerInstance"],
                  signedEnvelope=b64(b'{"body":{}}'))
refuse(lambda:review.review_digest(
    valid_commit,prepared,**witness),"PREPARE_REVIEW_REQUIRED")
refuse(lambda:review.review_digest(
    dict(req,action="TRASH"),prepared,**witness),
    "UNKNOWN_OR_CROSS_SYSTEM_OPERATION")
refuse(lambda:review.native_operator_authorize(
    summary,authorized=True,polkitOk=True),"STAFFING_NATIVE_POLKIT_ISSUER_NOT_INSTALLED")

succ_scope=dict(
    roomId="room-ci",patientId="patient-ci",repository="org/repo",
    branch="feat/test",bedPath="/tmp/hospital-ci",assignmentId="1",
    previousSessionId="session-old",newSessionId="session-new",
    previousDoctorId="doctor-old",previousProviderId="provider-old",
    successorDoctorId="doctor-new",successorProviderId="provider-new",
)
succ_req=dict(req,action=grants.SUCCEED,intent=succ_scope)
succ_prepared=dict(prepared,action=grants.SUCCEED)
succ_review=review.review_summary(succ_req,succ_prepared,**witness)
assert succ_review["actionId"]=="org.postapollo.hospital.doctor-succeed"
assert "Doctor doctor-old to doctor-new" in succ_review["detail"]
assert "session-old" in succ_review["detail"]
assert succ_review["reviewDigest"]!=expected

# This source-only candidate is NOT installed in /usr/share/polkit-1.
policy=ROOT/"packaging/hospital-trash-restore"/(
    "candidate-org.postapollo.hospital.staffing.policy")
assert policy.is_file()
root=ET.fromstring(policy.read_text("utf-8"))
actions=root.findall("./action")
ids={item.attrib["id"] for item in actions}
assert len(actions)==2
assert ids==set(review.ACTION_IDS.values())
assert ids==set(grants.POLKIT_ACTIONS.values())
assert "org.postapollo.hospital.room-trash" not in ids
assert "org.postapollo.hospital.room-restore" not in ids
for action in actions:
    defaults=action.find("defaults")
    assert defaults is not None
    assert defaults.findtext("allow_any")=="no"
    assert defaults.findtext("allow_inactive")=="no"
    assert defaults.findtext("allow_active")=="auth_self"
    assert not any(
        "keep" in value.text.lower()
        for value in defaults if value.text is not None)

# Merged C5-H2 source is read-only independent owner witness. Neither
# current source nor the policy is allowed to repurpose its Room actions.
merged=ROOT/"app-source/services/connections/hospital/native"/(
    "org.postapollo.hospital.policy")
service=ROOT/"app-source/services/connections/hospital"/(
    "HospitalNativeIssuerService.py")
if not merged.is_file() or not service.is_file():
    raise RuntimeError("PINNED_MERGED_CONNECTIONS_ISSUER_SOURCE_MISSING")
old_actions={item.attrib["id"] for item in
             ET.fromstring(merged.read_text("utf-8")).findall("./action")}
assert old_actions=={
    "org.postapollo.hospital.room-trash",
    "org.postapollo.hospital.room-restore"}
assert not old_actions.intersection(ids)
existing_service=service.read_text("utf-8")
assert "def _active_seat(" in existing_service
assert "def _polkit_approve(" in existing_service
assert "def _same_peer(" in existing_service
assert "org.postapollo.hospital.room-trash" in existing_service
assert "org.postapollo.hospital.room-restore" in existing_service
assert "org.postapollo.hospital.session-attach" not in existing_service
assert "org.postapollo.hospital.doctor-succeed" not in existing_service

print("HOSPITAL STAFFING OPERATOR REVIEW // PASS // exact Room Assignment Session Doctor source graph, seat, release and policy binding; distinct Polkit actions; native issuer HOLD")
