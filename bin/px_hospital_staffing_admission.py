"""Hospital Session/Doctor v12 SOURCE adapter, pending native authorization.

These are exact independently owned source functions from:
PX #123 Session attachment: 4c3f0c97c4b6342bc7adb70443afecf65666d3cb
PX #125 Doctor succession: 4e0fe43c1324c0011dbbdbcbdfc8bddfb06bcdc1

Only injected Room/Session record readers differ from source signatures;
CI verifies functional bodies against those pinned owners. Both routines
preserve their original SQLite BEGIN IMMEDIATE / rollback semantics.

CRITICAL: This module does NOT add protected writer RPC operations, does
NOT authenticate any operator, and does NOT enable either operation on
a user's direct PX CLI. A CLI --confirm flag is NOT authorization.
The native dispatcher stays HOLD until a distinct installed, reviewed
Session/Doctor operator-approval service and source-owner reconciliation
exist. Do not expose internal helpers to untrusted process peers.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import px_hospital_staffing_grants as grants


def _native_scope(grant, operation, expected):
    """Only an installed root-pinned verifier may supply native authority.

    The owner functions are callable internally during isolated source
    verification; this helper never turns plain --confirm into approval.
    The protected request dispatcher remains deny-only.
    """
    if (not isinstance(grant, grants.VerifiedStaffingGrant)
            or grant.native_verified is not True
            or grant.body.get("operation") != operation):
        raise NativeStaffingHold("ROOT_PINNED_STAFFING_GRANT_REQUIRED")
    # The in-memory flag is not an authorization capability. Recheck the
    # original signed bytes under the root-pinned installed issuer, including
    # current host binding, before any staffing mutation is attempted.
    grants.require_native_grant(grant)
    scope = grant.body.get("scope")
    if type(scope) is not dict or any(
            scope.get(key) != str(value) for key, value in expected.items()):
        raise NativeStaffingHold("NATIVE_STAFFING_REQUEST_SCOPE_CHANGED")


class NativeStaffingHold(RuntimeError):
    """Native staff-operation authority has not been installed/reviewed."""


def dispatch_native_staffing(*_args, **_kwargs):
    """Unconditionally refuse until signed staff authority is implemented.

    This function is deliberately NOT injected with test-only booleans,
    environment overrides, custom verifier keys, or caller-supplied grants.
    Source-stage tests call the original atomic helpers on temporary DBs.
    """
    raise NativeStaffingHold("NATIVE_SESSION_DOCTOR_AUTHORITY_NOT_INSTALLED")


def session_attach_atomic(conn: sqlite3.Connection, args, *, session_record, native_grant=None) -> dict:
    """Admission-only attach. Same-DB Room/Bed check and INSERT are one write.

    No model process is started. No existing Session is moved or overwritten.
    Explicit --confirm represents a requested action, not caller authentication.
    """
    if not args.confirm:
        raise RuntimeError("HOSPITAL ATTACH REFUSED // explicit confirmation required")
    room_id = str(args.room_id or "").strip()
    session_id = str(args.session_id or "").strip()
    doctor_id = str(args.doctor_id or "").strip()
    provider_id = str(args.provider_id or "").strip()
    requested_assignment = str(args.assignment_id or "").strip()
    repository = str(args.repository or "").strip()
    branch = str(args.branch or "").strip()
    bed_text = str(args.bed_path or "").strip()
    if not all((room_id, session_id, doctor_id, provider_id,
                requested_assignment, repository, branch, bed_text)):
        raise RuntimeError("HOSPITAL ATTACH REFUSED // missing required identity")
    if not requested_assignment.isdecimal():
        raise RuntimeError("HOSPITAL ATTACH REFUSED // invalid Assignment ID")
    if provider_id == "int1-fake":
        raise RuntimeError("HOSPITAL ATTACH REFUSED // fake-only provider")
    if any(ch in session_id for ch in "\r\n\t"):
        raise RuntimeError("HOSPITAL ATTACH REFUSED // invalid Session ID")

    # Resolve outside the transaction; paths must already exist. An atomic DB
    # claim is not a cross-host or filesystem lock.
    bed_path = Path(bed_text).expanduser().resolve(strict=True)
    if not bed_path.is_dir() or not Path(bed_text).is_absolute():
        raise RuntimeError("HOSPITAL ATTACH REFUSED // Bed must be an absolute directory")
    if str(Path(bed_text).expanduser()) != bed_text:
        raise RuntimeError("HOSPITAL ATTACH REFUSED // Bed path must be explicit")

    if native_grant is not None:
        _native_scope(native_grant, grants.ATTACH, {
            "roomId": room_id, "sessionId": session_id,
            "doctorId": doctor_id, "providerId": provider_id,
            "assignmentId": requested_assignment,
            "repository": repository, "branch": branch,
            "bedPath": bed_text, "mode": args.mode,
        })
    try:
        conn.execute("BEGIN IMMEDIATE")
        if native_grant is not None:
            native_grant.consume(
                conn, operation=grants.ATTACH,
                scope=native_grant.body["scope"])
        room = conn.execute(
            """
            SELECT r.*, p.repository AS repository
            FROM rooms r
            LEFT JOIN patients p ON p.patient_id = r.patient_id
            WHERE r.room_id = ?
            """, (room_id,),
        ).fetchone()
        if room is None:
            raise RuntimeError("HOSPITAL ATTACH REFUSED // unknown Room")
        if (not str(room["patient_id"] or "")
                or str(room["repository"] or "") != repository
                or str(room["branch"] or "") != branch
                or str(room["bed_path"] or "") != bed_text):
            raise RuntimeError("HOSPITAL ATTACH REFUSED // Room snapshot changed")
        for field, selected, label in (
            ("doctor_id", doctor_id, "Doctor"),
            ("provider_id", provider_id, "Provider"),
        ):
            old = str(room[field] or "")
            if old and old != selected:
                raise RuntimeError("HOSPITAL ATTACH REFUSED // Room " + label + " mismatch")

        doctor = conn.execute(
            "SELECT status FROM doctors WHERE doctor_id = ?", (doctor_id,)
        ).fetchone()
        if doctor is None or str(doctor["status"] or "") != "ACTIVE":
            raise RuntimeError("HOSPITAL ATTACH REFUSED // Doctor not ACTIVE")
        assignment = conn.execute(
            "SELECT room_id, patient_id, status FROM assignments WHERE assignment_id = ?",
            (int(requested_assignment),),
        ).fetchone()
        if (assignment is None or str(assignment["room_id"] or "") != room_id
                or str(assignment["patient_id"] or "") != str(room["patient_id"] or "")
                or str(assignment["status"] or "") != "ACTIVE"
                or str(room["current_assignment_id"] or "") != requested_assignment):
            raise RuntimeError("HOSPITAL ATTACH REFUSED // Assignment not active and linked")

        # Every nonterminal session counts, including WAITING / REVIEW / PAUSED.
        # Check all Rooms while BEGIN IMMEDIATE holds the sole DB writer slot.
        others = conn.execute(
            """
            SELECT s.*, r.bed_path AS room_bed
            FROM sessions s JOIN rooms r ON r.room_id = s.room_id
            WHERE (s.ended_at IS NULL
                   AND s.status NOT IN ('COMPLETE', 'ENDED', 'FAILED'))
               OR COALESCE(s.active_pid, 0) != 0
            """
        ).fetchall()
        for row in others:
            other_id = str(row["session_id"] or "")
            other_room_id = str(row["room_id"] or "")
            if other_room_id == room_id:
                if other_id != session_id:
                    raise RuntimeError("HOSPITAL ATTACH REFUSED // Room already has open Session")
                continue
            candidate = str(row["room_bed"] or "")
            if candidate and Path(candidate).expanduser().resolve() == bed_path:
                raise RuntimeError("HOSPITAL ATTACH REFUSED // Bed owned by another open Room")

        existing = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if existing is not None:
            if (str(existing["room_id"] or "") != room_id
                    or str(existing["doctor_id"] or "") != doctor_id
                    or str(existing["provider_id"] or "") != provider_id
                    or str(existing["working_directory"] or "") != bed_text
                    or str(existing["status"] or "") != "IDLE"
                    or existing["ended_at"] is not None
                    or int(existing["active_pid"] or 0) != 0):
                raise RuntimeError(
                    "HOSPITAL ATTACH REFUSED // existing Session identity or state differs"
                )
            created = False
        else:
            if args.mode == "reuse":
                raise RuntimeError(
                    "HOSPITAL ATTACH REFUSED // requested Session not found for reuse"
                )
            conn.execute(
                """
                INSERT INTO sessions(
                    session_id, room_id, doctor_id, provider_id,
                    status, working_directory
                ) VALUES(?, ?, ?, ?, 'IDLE', ?)
                """,
                (session_id, room_id, doctor_id, provider_id, bed_text),
            )
            created = True

        # Fill only blank Room staffing; never replace another worker/Provider.
        if not str(room["doctor_id"] or "") or not str(room["provider_id"] or ""):
            conn.execute(
                """
                UPDATE rooms SET
                    doctor_id = CASE WHEN doctor_id = '' THEN ? ELSE doctor_id END,
                    provider_id = CASE WHEN provider_id = '' THEN ? ELSE provider_id END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE room_id = ?
                """,
                (doctor_id, provider_id, room_id),
            )
        result = {
            "roomId": room_id,
            "sessionId": session_id,
            "doctorId": doctor_id,
            "providerId": provider_id,
            "assignmentId": requested_assignment,
            "mode": "CREATED" if created else "REUSED",
            "created": created,
            "providerLaunched": False,
            "browserChatConnected": False,
            "authorityVerified": False,
            "session": session_record(conn, session_id),
        }
        conn.commit()
        return result
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def session_succeed_atomic(conn: sqlite3.Connection, args, *, room_record, session_record, native_grant=None) -> dict:
    """Move registered Doctor staffing and admit a NEW idle Session atomically.

    A terminated prior Session is historical evidence, not a heartbeat.
    No Doctor/Provider process is launched and no permission is granted.
    One local SQLite database provides the transaction boundary; another
    machine or unsynchronized database is outside this guarantee.
    """
    if not args.confirm:
        raise RuntimeError("HOSPITAL SUCCESSION REFUSED // explicit confirmation required")
    room_id = str(args.room_id or "").strip()
    old_session_id = str(args.previous_session_id or "").strip()
    next_session_id = str(args.new_session_id or "").strip()
    old_doctor = str(args.previous_doctor_id or "").strip()
    old_provider = str(args.previous_provider_id or "").strip()
    next_doctor = str(args.successor_doctor_id or "").strip()
    next_provider = str(args.successor_provider_id or "").strip()
    assignment_id = str(args.assignment_id or "").strip()
    repository = str(args.repository or "").strip()
    branch = str(args.branch or "").strip()
    bed_text = str(args.bed_path or "").strip()
    if not all((room_id, old_session_id, next_session_id,
                old_doctor, old_provider, next_doctor, next_provider,
                assignment_id, repository, branch, bed_text)):
        raise RuntimeError("HOSPITAL SUCCESSION REFUSED // missing pinned identity")
    if old_doctor == next_doctor or old_session_id == next_session_id:
        raise RuntimeError("HOSPITAL SUCCESSION REFUSED // successor must be distinct")
    if not assignment_id.isdecimal():
        raise RuntimeError("HOSPITAL SUCCESSION REFUSED // invalid Assignment ID")
    if next_provider == "int1-fake":
        raise RuntimeError("HOSPITAL SUCCESSION REFUSED // fake-only Provider")
    if any(c in name for name in (room_id, old_session_id, next_session_id,
                                    old_doctor, next_doctor) for c in "\r\n\t"):
        raise RuntimeError("HOSPITAL SUCCESSION REFUSED // invalid identity")
    bed = Path(bed_text).expanduser()
    if not bed.is_absolute() or not bed.is_dir():
        raise RuntimeError("HOSPITAL SUCCESSION REFUSED // absolute existing Bed required")
    canonical_bed = bed.resolve(strict=True)
    if native_grant is not None:
        _native_scope(native_grant, grants.SUCCEED, {
            "roomId": room_id, "previousSessionId": old_session_id,
            "newSessionId": next_session_id,
            "previousDoctorId": old_doctor,
            "previousProviderId": old_provider,
            "successorDoctorId": next_doctor,
            "successorProviderId": next_provider,
            "assignmentId": assignment_id, "repository": repository,
            "branch": branch, "bedPath": bed_text,
        })
    try:
        conn.execute("BEGIN IMMEDIATE")
        if native_grant is not None:
            native_grant.consume(
                conn, operation=grants.SUCCEED,
                scope=native_grant.body["scope"])
        room = conn.execute("""
            SELECT r.*, p.repository AS repository
            FROM rooms r LEFT JOIN patients p ON p.patient_id = r.patient_id
            WHERE r.room_id = ?
        """, (room_id,)).fetchone()
        if room is None:
            raise RuntimeError("HOSPITAL SUCCESSION REFUSED // Room not found")
        if (not str(room["patient_id"] or "")
                or str(room["repository"] or "") != repository
                or str(room["branch"] or "") != branch
                or str(room["bed_path"] or "") != bed_text):
            raise RuntimeError("HOSPITAL SUCCESSION REFUSED // Room identity changed")

        assignment = conn.execute("""
            SELECT room_id, patient_id, status FROM assignments
            WHERE assignment_id = ?
        """, (int(assignment_id),)).fetchone()
        if (assignment is None
                or str(assignment["room_id"] or "") != room_id
                or str(assignment["patient_id"] or "") != str(room["patient_id"] or "")
                or str(assignment["status"] or "") != "ACTIVE"
                or str(room["current_assignment_id"] or "") != assignment_id):
            raise RuntimeError("HOSPITAL SUCCESSION REFUSED // linked ACTIVE Assignment changed")

        successor = conn.execute(
            "SELECT status FROM doctors WHERE doctor_id = ?", (next_doctor,)
        ).fetchone()
        if successor is None or str(successor["status"] or "") != "ACTIVE":
            raise RuntimeError("HOSPITAL SUCCESSION REFUSED // successor Doctor not ACTIVE")

        previous = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (old_session_id,)
        ).fetchone()
        if (previous is None or str(previous["room_id"] or "") != room_id
                or str(previous["doctor_id"] or "") != old_doctor
                or str(previous["provider_id"] or "") != old_provider):
            raise RuntimeError("HOSPITAL SUCCESSION REFUSED // previous Session mismatch")
        if str(previous["working_directory"] or "") != bed_text:
            raise RuntimeError(
                "HOSPITAL SUCCESSION REFUSED // previous Session Bed differs from Room"
            )
        if (str(previous["status"] or "") not in ("COMPLETE", "ENDED", "FAILED")
                or previous["ended_at"] is None
                or int(previous["active_pid"] or 0) != 0):
            raise RuntimeError(
                "HOSPITAL SUCCESSION REFUSED // previous Session not explicitly released"
            )

        existing_next = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (next_session_id,)
        ).fetchone()
        if existing_next is not None:
            if (str(room["doctor_id"] or "") != next_doctor
                    or str(room["provider_id"] or "") != next_provider
                    or str(existing_next["room_id"] or "") != room_id
                    or str(existing_next["doctor_id"] or "") != next_doctor
                    or str(existing_next["provider_id"] or "") != next_provider
                    or str(existing_next["working_directory"] or "") != bed_text
                    or str(existing_next["status"] or "") != "IDLE"
                    or existing_next["ended_at"] is not None
                    or int(existing_next["active_pid"] or 0) != 0):
                raise RuntimeError(
                    "HOSPITAL SUCCESSION REFUSED // new Session is not exact idle replay"
                )
            newest = conn.execute(
                "SELECT session_id FROM sessions WHERE room_id = ? "
                "ORDER BY rowid DESC LIMIT 1", (room_id,)
            ).fetchone()
            if newest is None or str(newest["session_id"] or "") != next_session_id:
                raise RuntimeError(
                    "HOSPITAL SUCCESSION REFUSED // successor replay is no longer latest"
                )
            repeat = True
        else:
            if (str(room["doctor_id"] or "") != old_doctor
                    or str(room["provider_id"] or "") != old_provider):
                raise RuntimeError("HOSPITAL SUCCESSION REFUSED // old Room staffing changed")
            newest = conn.execute(
                "SELECT session_id FROM sessions WHERE room_id = ? "
                "ORDER BY rowid DESC LIMIT 1", (room_id,)
            ).fetchone()
            if newest is None or str(newest["session_id"] or "") != old_session_id:
                raise RuntimeError("HOSPITAL SUCCESSION REFUSED // stale previous Session")
            repeat = False

        # No competing registered Session in Room or same canonical Bed.
        # Check even terminal rows whose recorded process PID remains nonzero.
        all_sessions = conn.execute("""
            SELECT s.*, r.bed_path AS occupied_bed
            FROM sessions s JOIN rooms r ON r.room_id = s.room_id
            WHERE (s.ended_at IS NULL
                   AND s.status NOT IN ('COMPLETE', 'ENDED', 'FAILED'))
                OR COALESCE(s.active_pid, 0) != 0
        """).fetchall()
        for session in all_sessions:
            sid = str(session["session_id"] or "")
            other_room = str(session["room_id"] or "")
            if other_room == room_id:
                if repeat and sid == next_session_id:
                    continue
                raise RuntimeError(
                    "HOSPITAL SUCCESSION REFUSED // Room Session already occupies work"
                )
            if str(session["doctor_id"] or "") == next_doctor:
                raise RuntimeError(
                    "HOSPITAL SUCCESSION REFUSED // successor Doctor busy in another Room"
                )
            other_bed = str(session["occupied_bed"] or "")
            if other_bed and Path(other_bed).expanduser().resolve() == canonical_bed:
                raise RuntimeError(
                    "HOSPITAL SUCCESSION REFUSED // Bed occupied by another Room"
                )

        handoff = conn.execute("""
            SELECT report_id FROM room_reports
            WHERE room_id = ? AND UPPER(TRIM(report_kind)) = 'HANDOFF'
            ORDER BY report_id DESC LIMIT 1
        """, (room_id,)).fetchone()
        checkpoint = conn.execute("""
            SELECT checkpoint_id FROM room_checkpoints
            WHERE room_id = ? ORDER BY checkpoint_id DESC LIMIT 1
        """, (room_id,)).fetchone()
        if handoff is None and checkpoint is None:
            raise RuntimeError(
                "HOSPITAL SUCCESSION REFUSED // no durable HANDOFF or checkpoint"
            )

        if not repeat:
            # The old Session remains byte-for-byte historical. The Room's
            # identity and Assignment are never rewritten or recreated.
            conn.execute("""
                UPDATE rooms
                SET doctor_id = ?, provider_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE room_id = ?
            """, (next_doctor, next_provider, room_id))
            conn.execute("""
                INSERT INTO sessions(
                    session_id, room_id, doctor_id, provider_id,
                    status, working_directory
                ) VALUES(?, ?, ?, ?, 'IDLE', ?)
            """, (next_session_id, room_id, next_doctor, next_provider, bed_text))
            conn.execute("""
                INSERT INTO session_events(session_id, event_type, payload_json)
                VALUES(?, 'room.succession.admitted', ?)
            """, (next_session_id, json.dumps({
                "roomId": room_id,
                "previousSessionId": old_session_id,
                "previousDoctorId": old_doctor,
                "successorDoctorId": next_doctor,
                "assignmentId": assignment_id,
                "handoffId": handoff["report_id"] if handoff is not None else None,
                "checkpointId": checkpoint["checkpoint_id"] if checkpoint is not None else None,
            }, sort_keys=True)))

        result = {
            "roomId": room_id, "previousSessionId": old_session_id,
            "previousDoctorId": old_doctor, "previousProviderId": old_provider,
            "sessionId": next_session_id, "doctorId": next_doctor,
            "providerId": next_provider, "assignmentId": assignment_id,
            "mode": "REUSED" if repeat else "CREATED",
            "created": not repeat,
            "handoffId": handoff["report_id"] if handoff is not None else None,
            "checkpointId": checkpoint["checkpoint_id"] if checkpoint is not None else None,
            "room": room_record(conn, room_id),
            "session": session_record(conn, next_session_id),
            "providerLaunched": False, "browserChatConnected": False,
            "authorityVerified": False, "contextDelivered": False,
            "atomicWithinOneDatabase": True,
        }
        conn.commit()
        return result
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise

