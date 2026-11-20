"""Typed Hospital staffing operator review contract, source-only and uninstalled.

This module DEFINES the exact information an independently trusted native
Connections issuer must obtain and show for a Session or Doctor operation.
It does not authenticate any operator, read login1, call pkcheck, load a
signing key, open a socket or create authorization. A caller can construct
these data structures without privileges: they are never themselves proof
of consent. Only a separately signed and root-pinned grant can be consumed
by a protected native writer after independent identity/seat verification.

The merged Connections C5-H2 native issuer owns logind/Polkit mechanisms
for TRASH/RESTORE, but its two actions CANNOT authorize staffing.
"""
from __future__ import annotations

import hashlib
import re

import px_hospital_staffing_grants as grants
import px_hospital_staffing_transport as transport

REVIEW_DOMAIN = b"post-apollo.hospital.staffing-operator-review.v1\x00"
PREPARED_SCHEMA = "postapollo.hospital.native-staffing-prepared.v1"
ACTION_IDS = {
    grants.ATTACH: "org.postapollo.hospital.session-attach",
    grants.SUCCEED: "org.postapollo.hospital.doctor-succeed",
}
SEAT = re.compile(r"logind-[A-Za-z0-9_-]{1,64}-[A-Za-z0-9_-]{1,64}\Z",
                  re.ASCII)
HEX = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
FIELDS = frozenset((
    "schema", "requestNonce", "roomId", "action",
    "expectedRevision", "expectedDigest", "writerInstance",
    "state", "expiresInSeconds", "operatorAuthenticated",
    "requiresExternalConsent",
))


class StaffingReviewHold(RuntimeError):
    pass


def hold(reason):
    raise StaffingReviewHold("HOSPITAL_STAFFING_REVIEW_HOLD // " + reason)


def _hex(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def _review_inputs(request, prepared, *, operator_uid, seat_id,
                   client_sha, issuer_release_sha, policy_generation):
    """Strict composition of source review and external witness *claims*.

    A future native issuer must obtain operator_uid/seat_id from kernel
    PID + system login1 and verify them before and after interactive
    Polkit. It must obtain SHA/policy generation from independently
    authenticated root-enrolled release/policy sources, NOT these kwargs.
    """
    if type(request) is not dict:
        hold("TYPED_STAFFING_REQUEST_REQUIRED")
    transport.parse_request(transport.canonical(request))
    if request["kind"] != transport.KIND_PREPARE:
        hold("PREPARE_REVIEW_REQUIRED")
    if type(prepared) is not dict or set(prepared) != FIELDS:
        hold("EXACT_PREPARED_SOURCE_FIELDS")
    if (prepared["schema"] != PREPARED_SCHEMA
            or prepared["requestNonce"] != request["requestNonce"]
            or prepared["action"] != request["action"]
            or prepared["roomId"] != request["roomId"]
            or prepared["state"] != "ACTIVE"
            or prepared["operatorAuthenticated"] is not False
            or prepared["requiresExternalConsent"] is not True
            or type(prepared["expectedRevision"]) is not int
            or not 0 <= prepared["expectedRevision"] < 1_000_000_000
            or not _hex(prepared["expectedDigest"])
            or type(prepared["expiresInSeconds"]) is not int
            or not 0 < prepared["expiresInSeconds"] <= 45
            or type(prepared["writerInstance"]) is not str
            or grants.APPROVAL.fullmatch(prepared["writerInstance"]) is None):
        hold("UNTRUSTED_OR_STALE_PREPARED_SOURCE")
    if (type(operator_uid) is not int or not 0 < operator_uid < 2**31):
        hold("NONROOT_OPERATOR_UID_REQUIRED")
    if (type(seat_id) is not str
            or SEAT.fullmatch(seat_id) is None):
        hold("NATIVE_ACTIVE_LOGIN1_SEAT_REQUIRED")
    if not _hex(client_sha) or not _hex(issuer_release_sha):
        hold("RELEASE_DIGEST_EVIDENCE_REQUIRED")
    if (type(policy_generation) is not int
            or not 0 < policy_generation < 2**63):
        hold("ROOT_POLICY_GENERATION_REQUIRED")
    op = request["action"]
    action_id = ACTION_IDS.get(op)
    if action_id is None:
        hold("STAFFING_POLKIT_ACTION_ONLY")
    context = {
        "schema": "postapollo.hospital.staffing-operator-review.v1",
        "action": op,
        "polkitActionId": action_id,
        "roomId": request["roomId"],
        "scope": request["intent"],
        "roomRevision": prepared["expectedRevision"],
        "graphDigest": prepared["expectedDigest"],
        "requestNonce": request["requestNonce"],
        "writerInstance": prepared["writerInstance"],
        "operatorUid": operator_uid,
        "seatId": seat_id,
        "clientExecutableSha256": client_sha,
        "issuerReleaseSha256": issuer_release_sha,
        "policyGeneration": policy_generation,
    }
    return context


def review_digest(request, prepared, *, operator_uid, seat_id,
                  client_sha, issuer_release_sha, policy_generation):
    """Domain-separated SHA-256 of exact review context, NOT authorization."""
    context = _review_inputs(
        request, prepared, operator_uid=operator_uid, seat_id=seat_id,
        client_sha=client_sha, issuer_release_sha=issuer_release_sha,
        policy_generation=policy_generation,
    )
    return hashlib.sha256(
        REVIEW_DOMAIN + transport.canonical(context)
    ).hexdigest()


def review_summary(request, prepared, *, operator_uid, seat_id,
                   client_sha, issuer_release_sha, policy_generation):
    """Human-readable source review proposal, NOT proof of display/approval."""
    context = _review_inputs(
        request, prepared, operator_uid=operator_uid, seat_id=seat_id,
        client_sha=client_sha, issuer_release_sha=issuer_release_sha,
        policy_generation=policy_generation,
    )
    scope = context["scope"]
    if context["action"] == grants.ATTACH:
        staffing = (
            "Attach Session {sessionId}, Doctor {doctorId}, Provider "
            "{providerId}, mode {mode}"
        ).format(**scope)
    else:
        staffing = (
            "Succeed Session {previousSessionId} to {newSessionId}; "
            "Doctor {previousDoctorId} to {successorDoctorId}; "
            "Provider {previousProviderId} to {successorProviderId}"
        ).format(**scope)
    display = (
        "{staffing}; Room {roomId}; Patient {patientId}; "
        "repository {repository}; Assignment {assignmentId}; "
        "Bed {bedPath}; revision {roomRevision}; graph {graphDigest}; "
        "request {requestNonce}; seat {seatId}"
    ).format(staffing=staffing, **scope, **{
        "roomRevision": context["roomRevision"],
        "graphDigest": context["graphDigest"],
        "requestNonce": context["requestNonce"],
        "seatId": context["seatId"],
    })
    return {
        "actionId": context["polkitActionId"],
        "detail": display,
        "reviewDigest": review_digest(
            request, prepared, operator_uid=operator_uid,
            seat_id=seat_id, client_sha=client_sha,
            issuer_release_sha=issuer_release_sha,
            policy_generation=policy_generation,
        ),
        "operatorAuthorized": False,
        "polkitCompleted": False,
        "installedSignedReleaseVerified": False,
    }


def native_operator_authorize(*_args, **_kwargs):
    """This is NOT the merged H2 issuer; staffing native permission is HOLD."""
    hold("STAFFING_NATIVE_POLKIT_ISSUER_NOT_INSTALLED")
