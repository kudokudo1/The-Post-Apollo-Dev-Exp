"""Source-only Hospital staffing PREPARE / COMMIT coordinator, CI rehearsal.

This is NOT a native service or production entrypoint. Construction is
restricted to GitHub Actions and a disposable runner fixture. The trusted
Linux peer identity and active-seat/Polkit consent service have NOT been
implemented. In a real deployment the root-pinned issuer must bind these
details, process provenance and exact operator approval.

The coordinator checks a durable source Room snapshot at PREPARE and
COMMIT; an approval also signs its one-use PREPARE nonce. Only an exact
trusted signed grant can enter the original source atomic transaction.
No general SQL, Bed claims, Trash/Restore or fallback to user SQLite.
The separately exported native dispatcher STILL refuses unconditionally.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import sqlite3
import time
from types import SimpleNamespace

import px_hospital_room_lifecycle as lifecycle
import px_hospital_staffing_grants as grants
import px_hospital_staffing_admission as admission
import px_hospital_staffing_transport as transport

PREPARED_SCHEMA = "postapollo.hospital.native-staffing-prepared.v1"
RECEIPT_SCHEMA = "postapollo.hospital.native-staffing-fixture-receipt.v1"
PREPARE_TTL_SECONDS = 40
MAX_PENDING = 128


class StaffingCoordinatorHold(RuntimeError):
    pass


def _hold(reason):
    raise StaffingCoordinatorHold("HOSPITAL_STAFFING_COORDINATOR_HOLD // " + reason)


@dataclass(frozen=True)
class Pending:
    nonce: str
    action: str
    room: str
    intent: bytes
    peer: tuple
    revision: int
    digest: str
    deadline: float
    writer_instance: str


def _fixture_only():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("CI") != "true"
            or not os.environ.get("RUNNER_TEMP")
            or not Path(os.environ["RUNNER_TEMP"]).is_dir()):
        _hold("CI_ONLY_NATIVE_HANDLER_NOT_INSTALLED")


def _peer_witness(value):
    """An external kernel-credential verifier must supply this tuple.

    Here it is an explicitly synthetic CI input, NOT authentication.
    Source production deliberately has no socket that can produce one.
    """
    if (type(value) is not tuple or len(value) != 3
            or any(type(v) is not int for v in value)
            or value[0] <= 1 or value[1] != 0 or value[2] <= 0):
        _hold("NATIVE_ROOT_PEER_WITNESS_REQUIRED")
    return value


def _source_snapshot(db, request):
    if (not isinstance(db, sqlite3.Connection) or db.in_transaction
            or db.row_factory is not sqlite3.Row
            or db.execute("PRAGMA foreign_keys").fetchone()[0] != 1):
        _hold("PROTECTED_SQLITE_CONNECTION_REQUIRED")
    v = db.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    if v is None or v[0] != "13":
        _hold("CANDIDATE_V13_NOT_INSTALLED")
    scope = request["intent"]
    room_id = request["roomId"]
    snapshot = lifecycle.review(db, room_id)
    if snapshot["state"] != "ACTIVE":
        _hold("ROOM_NOT_ACTIVE")
    source = db.execute("""
        SELECT r.patient_id,p.repository,r.branch,r.bed_path,
               r.current_assignment_id,r.doctor_id,r.provider_id
        FROM rooms r JOIN patients p ON p.patient_id=r.patient_id
        WHERE r.room_id=?
    """, (room_id,)).fetchone()
    if source is None or any(
            scope[key] != str(source[column] or "")
            for key, column in (
                ("patientId", "patient_id"), ("repository", "repository"),
                ("branch", "branch"), ("bedPath", "bed_path"),
                ("assignmentId", "current_assignment_id"),
            )):
        _hold("PATIENT_ROOM_ASSIGNMENT_OR_BED_CHANGED")
    active = db.execute(
        "SELECT patient_id,room_id,status FROM assignments "
        "WHERE assignment_id=?", (int(scope["assignmentId"]),)
    ).fetchone()
    if (active is None or active["status"] != "ACTIVE"
            or active["room_id"] != room_id
            or active["patient_id"] != scope["patientId"]):
        _hold("ASSIGNMENT_NOT_ACTIVE")
    if request["action"] == grants.ATTACH:
        if (str(source["doctor_id"] or "") not in ("", scope["doctorId"])
                or str(source["provider_id"] or "") not in (
                    "", scope["providerId"])):
            _hold("ROOM_STAFF_IDENTITY_CHANGED")
        doctor_id = scope["doctorId"]
    else:
        if (str(source["doctor_id"] or "") != scope["previousDoctorId"]
                or str(source["provider_id"] or "")
                != scope["previousProviderId"]):
            _hold("PREVIOUS_STAFF_IDENTITY_CHANGED")
        doctor_id = scope["successorDoctorId"]
    doctor = db.execute(
        "SELECT status FROM doctors WHERE doctor_id=?", (doctor_id,)
    ).fetchone()
    if doctor is None or doctor["status"] != "ACTIVE":
        _hold("SELECTED_DOCTOR_NOT_ACTIVE")
    return snapshot


def _atomic_args(action, scope):
    base = dict(
        confirm=True, room_id=scope["roomId"],
        assignment_id=scope["assignmentId"],
        repository=scope["repository"], branch=scope["branch"],
        bed_path=scope["bedPath"],
    )
    if action == grants.ATTACH:
        base.update(
            session_id=scope["sessionId"], doctor_id=scope["doctorId"],
            provider_id=scope["providerId"], mode=scope["mode"],
        )
    elif action == grants.SUCCEED:
        base.update(
            previous_session_id=scope["previousSessionId"],
            new_session_id=scope["newSessionId"],
            previous_doctor_id=scope["previousDoctorId"],
            previous_provider_id=scope["previousProviderId"],
            successor_doctor_id=scope["successorDoctorId"],
            successor_provider_id=scope["successorProviderId"],
        )
    else:
        _hold("UNKNOWN_STAFFING_OPERATION")
    return SimpleNamespace(**base)


class SourceStaffingRehearsal:
    """CI-only protected PREPARE/COMMIT logic, never a live service.

    The reviewed v12 source owner record reader functions are explicitly
    injected for this test; the candidate v13 schema has no official PX
    versioned migration yet. No session/Doctor launch occurs.
    """

    def __init__(self, *, session_record, room_record):
        _fixture_only()
        if not callable(session_record) or not callable(room_record):
            _hold("SOURCE_READERS_REQUIRED")
        self._session_record = session_record
        self._room_record = room_record
        self.writer_instance = "writer-" + secrets.token_urlsafe(18)
        self.pending = {}

    def _drop_expired(self):
        tick = time.monotonic()
        for nonce, value in list(self.pending.items()):
            if value.deadline <= tick:
                del self.pending[nonce]

    def prepare(self, db, raw: bytes, *, kernel_peer):
        _fixture_only()
        peer = _peer_witness(kernel_peer)
        request = transport.parse_request(raw)
        if request["kind"] != transport.KIND_PREPARE:
            _hold("PREPARE_STEP_REQUIRED")
        self._drop_expired()
        if (request["requestNonce"] in self.pending
                or len(self.pending) >= MAX_PENDING):
            _hold("DUPLICATE_OR_FULL_PENDING")
        snapshot = _source_snapshot(db, request)
        nonce = request["requestNonce"]
        pending = Pending(
            nonce=nonce, action=request["action"], room=request["roomId"],
            intent=transport.canonical(request["intent"]), peer=peer,
            revision=snapshot["revision"], digest=snapshot["digest"],
            deadline=time.monotonic() + PREPARE_TTL_SECONDS,
            writer_instance=self.writer_instance,
        )
        self.pending[nonce] = pending
        return {
            "schema": PREPARED_SCHEMA, "requestNonce":nonce,
            "roomId":pending.room, "action":pending.action,
            "expectedRevision":pending.revision,
            "expectedDigest":pending.digest,
            "writerInstance":pending.writer_instance,
            "state":"ACTIVE",
            "expiresInSeconds":PREPARE_TTL_SECONDS,
            "operatorAuthenticated":False,
            "requiresExternalConsent":True,
        }

    def commit(self, db, raw: bytes, *, kernel_peer):
        """Synthetic transaction; no native socket can invoke this."""
        _fixture_only()
        peer = _peer_witness(kernel_peer)
        request = transport.parse_request(raw)
        if request["kind"] != transport.KIND_COMMIT:
            _hold("COMMIT_STEP_REQUIRED")
        self._drop_expired()
        pending = self.pending.pop(request["requestNonce"], None)
        if pending is None:
            _hold("MISSING_EXPIRED_OR_REPLAYED_PREPARE")
        if (pending.peer != peer
                or pending.writer_instance != self.writer_instance
                or request["writerInstance"] != pending.writer_instance
                or pending.room != request["roomId"]
                or pending.action != request["action"]
                or pending.intent != transport.canonical(request["intent"])):
            _hold("PREPARE_COMMIT_IDENTITY_CHANGED")
        if pending.deadline <= time.monotonic():
            _hold("PREPARE_EXPIRED")
        snapshot = _source_snapshot(db, request)
        if (snapshot["revision"] != pending.revision
                or snapshot["digest"] != pending.digest):
            _hold("PREPARE_ROOM_GRAPH_CHANGED")
        envelope = transport._decode_b64(
            request["signedEnvelope"],
            max_length=transport.MAX_GRANT_BYTES,
        )
        # No injected public key here. Only the pinned root issuer path.
        # CI uses unittest.mock.patch on that trusted implementation.
        grant = grants.verify_native_envelope(envelope)
        if (not isinstance(grant, grants.VerifiedStaffingGrant)
                or grant.native_verified is not True):
            _hold("NATIVE_GRANT_REQUIRED")
        signed = grant.body
        if (signed["requestNonce"] != pending.nonce
                or signed["scope"] != request["intent"]
                or signed["operation"] != pending.action
                or signed["roomRevision"] != pending.revision
                or signed["graphDigest"] != pending.digest):
            _hold("SIGNED_PREPARE_MISMATCH")
        args = _atomic_args(pending.action, request["intent"])
        if pending.action == grants.ATTACH:
            result = admission.session_attach_atomic(
                db, args, session_record=self._session_record,
                native_grant=grant,
            )
            sid = request["intent"]["sessionId"]
        else:
            result = admission.session_succeed_atomic(
                db, args, room_record=self._room_record,
                session_record=self._session_record, native_grant=grant,
            )
            sid = request["intent"]["newSessionId"]
        if result["sessionId"] != sid:
            _hold("SOURCE_RECEIPT_IDENTITY_MISMATCH")
        return {
            "schema": RECEIPT_SCHEMA, "requestNonce":pending.nonce,
            "roomId":pending.room, "action":pending.action,
            "sessionId":sid, "grantDigest":grant.digest,
            "fixtureTransactionCommitted":True,
            "nativeInstallationVerified":False,
            "operatorAuthenticated":False,
        }
