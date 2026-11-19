#!/usr/bin/env python3
"""Hospital staffing signed atomic source path, CI-only disposable v12.

The trusted host reader is mocked INSIDE this test interpreter with a
generated Ed25519 fixture key. No caller-provided key or test flag is
supported by installed PX. Native socket/CLI remains unconnected.
"""
from __future__ import annotations
import base64
from contextlib import closing
import json
import os
from pathlib import Path
import runpy
import secrets
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()):
    raise SystemExit("HOSPITAL_STAFFING_ATOMIC_HOLD // CI_ONLY")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "bin"))
import px_hospital_staffing_grants as auth
import px_hospital_staffing_admission as admission
import px_hospital_room_lifecycle as life
import px_hospital_protected_store_bridge as bridge

assert bridge.route_coverage()
assert "session-attach-atomic" not in bridge.WRITE_COMMANDS
assert "session-succeed-atomic" not in bridge.WRITE_COMMANDS

def refused(callback, needle):
    try:
        callback()
    except (RuntimeError,sqlite3.Error) as exc:
        assert needle.lower() in str(exc).lower(), (needle,str(exc))
        return
    raise AssertionError("UNAUTHORIZED_STAFFING_OPERATION")

def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

def sign(priv,body):
    return auth.canonical({
        "body":body,
        "signature":b64(priv.sign(auth.DOMAIN + auth.canonical(body))),
    })

with tempfile.TemporaryDirectory(
        prefix="hospital-staffing-atomic-",dir=os.environ["RUNNER_TEMP"]) as td:
    root = Path(td)
    source = runpy.run_path(str(ROOT/"bin"/"px-hospital-store"),
                            run_name="hospital_staffing_atomic_fixture")
    private = Ed25519PrivateKey.generate()
    host_id = "f"*64
    with closing(sqlite3.connect(str(root/"hospital.db"),
                                 isolation_level=None)) as db:
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        assert source["migrate"](db) == 12
        assert db.execute("SELECT COUNT(*) FROM sqlite_master "
                          "WHERE type='table' AND name='hospital_staffing_authorizations'"
                          ).fetchone()[0] == 0
        # The approval ledger schema is deliberately fixture-only. A
        # separate migration owner must review its production installation.
        db.executescript("""
            CREATE TABLE hospital_staffing_authorizations(
                nonce TEXT PRIMARY KEY,
                grant_digest TEXT NOT NULL UNIQUE,
                approval_id TEXT NOT NULL UNIQUE,
                room_id TEXT NOT NULL REFERENCES rooms(room_id),
                operation TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                graph_digest TEXT NOT NULL
            );
        """)
        db.execute("INSERT INTO patients(patient_id,repository) "
                   "VALUES('p','org/project')")
        for name in ("doctor-old","doctor-new"):
            db.execute("INSERT INTO doctors(doctor_id,status) VALUES(?,'ACTIVE')",
                       (name,))
        def setup(room_id, bed_name):
            bed=root/bed_name
            bed.mkdir()
            db.execute("INSERT INTO rooms(room_id,patient_id,branch,bed_path,"
                       "doctor_id,provider_id) VALUES(?,'p','feature/staff',?,"
                       "'doctor-old','provider-old')",(room_id,str(bed)))
            assignment=db.execute(
                "INSERT INTO assignments(room_id,patient_id,status,goal_md)"
                " VALUES(?,'p','ACTIVE','CI-only goal')",(room_id,)
            ).lastrowid
            db.execute("UPDATE rooms SET current_assignment_id=? WHERE room_id=?",
                       (str(assignment),room_id))
            return bed,str(assignment)

        bed_a,aid_a=setup("room-a","bed-a")
        bed_b,aid_b=setup("room-b","bed-b")

        def body(operation,scope,room):
            state=life.review(db,room)
            return dict(
                schema=auth.SCHEMA,audience=auth.AUDIENCE,
                operation=operation,scope=scope,
                roomRevision=state["revision"],graphDigest=state["digest"],
                operatorId="ci-operator",approvalId="ap-"+secrets.token_hex(16),
                seatId="se-"+secrets.token_hex(16),hostId=host_id,
                nonce=b64(secrets.token_bytes(32)),
                issuedAt=int(time.time()),expiresAt=int(time.time())+25,
            )
        def get_native_grant(payload):
            with patch.object(auth,"trusted_public_key",
                              return_value=private.public_key()), \
                 patch.object(auth,"installed_host_binding",
                              return_value=host_id):
                return auth.verify_native_envelope(sign(private,payload))

        def attach_args(room,bed,aid,sid):
            return SimpleNamespace(
                confirm=True,room_id=room,session_id=sid,
                doctor_id="doctor-old",provider_id="provider-old",
                assignment_id=aid,repository="org/project",
                branch="feature/staff",bed_path=str(bed),mode="create",
            )
        def attach_scope(a):
            return dict(
                roomId=a.room_id,patientId="p",repository=a.repository,
                branch=a.branch,bedPath=a.bed_path,assignmentId=a.assignment_id,
                sessionId=a.session_id,doctorId=a.doctor_id,
                providerId=a.provider_id,mode=a.mode,
            )
        a=attach_args("room-a",bed_a,aid_a,"session-a")
        a_scope=attach_scope(a)
        signed=body(auth.ATTACH,a_scope,"room-a")
        root_grant=get_native_grant(signed)
        assert root_grant.native_verified is True

        # A fixture-verified key alone does not qualify as a native host.
        fake_grant=auth._verify_bytes(sign(private,signed),
                                       private.public_key())
        assert fake_grant.native_verified is False
        refused(lambda:admission.session_attach_atomic(
            db,a,session_record=source["session_record"],
            native_grant=fake_grant),"ROOT_PINNED_STAFFING_GRANT_REQUIRED")
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        refused(lambda:admission.session_attach_atomic(
            db,SimpleNamespace(**dict(vars(a),session_id="changed")),
            session_record=source["session_record"],
            native_grant=root_grant),"NATIVE_STAFFING_REQUEST_SCOPE_CHANGED")
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        refused(lambda:admission.dispatch_native_staffing(
            "SESSION_ATTACH",sign(private,signed),
            native_grant=root_grant),"NATIVE_SESSION_DOCTOR_AUTHORITY_NOT_INSTALLED")

        created=admission.session_attach_atomic(
            db,a,session_record=source["session_record"],
            native_grant=root_grant)
        assert created["created"] and created["session"]["status"]=="IDLE"
        assert created["authorityVerified"] is False  # source routine never claims it
        assert db.execute("SELECT COUNT(*) FROM hospital_staffing_authorizations"
                         ).fetchone()[0] == 1

        # A fresh Room with a forced SQLite failure after the grant is
        # consumed must ROLLBACK the grant and the attempted Session row.
        b=attach_args("room-b",bed_b,aid_b,"session-b")
        b_scope=attach_scope(b)
        b_grant=get_native_grant(body(auth.ATTACH,b_scope,"room-b"))
        db.executescript("""
            CREATE TRIGGER refuse_fixture_session
            BEFORE INSERT ON sessions WHEN NEW.session_id='session-b'
            BEGIN SELECT RAISE(ABORT,'synthetic Session INSERT refusal'); END;
        """)
        refused(lambda:admission.session_attach_atomic(
            db,b,session_record=source["session_record"],
            native_grant=b_grant),"synthetic Session INSERT refusal")
        assert db.execute("SELECT COUNT(*) FROM hospital_staffing_authorizations"
                         ).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM sessions WHERE session_id='session-b'"
                         ).fetchone()[0] == 0
        db.execute("DROP TRIGGER refuse_fixture_session")
        retried=admission.session_attach_atomic(
            db,b,session_record=source["session_record"],
            native_grant=b_grant)
        assert retried["created"]
        assert db.execute("SELECT COUNT(*) FROM hospital_staffing_authorizations"
                         ).fetchone()[0] == 2

        # Prepare Doctor handoff only after the previous Session is
        # terminal. Old transcript and checkpoint remain unchanged.
        db.execute("INSERT INTO messages(room_id,session_id,author_role,"
                   "direction,body_md) VALUES("
                   "'room-a','session-a','DOCTOR','outgoing','PREVIOUS_WORK')")
        db.execute("INSERT INTO room_reports(room_id,session_id,"
                   "report_kind,body_md) VALUES("
                   "'room-a','session-a','HANDOFF','PRESERVE_HANDOFF')")
        db.execute("UPDATE sessions SET status='FAILED',ended_at='2026-11-19',"
                   "active_pid=0 WHERE session_id='session-a'")
        successor_args=SimpleNamespace(
            confirm=True,room_id="room-a",previous_session_id="session-a",
            new_session_id="session-new",previous_doctor_id="doctor-old",
            previous_provider_id="provider-old",
            successor_doctor_id="doctor-new",
            successor_provider_id="provider-new",
            assignment_id=aid_a,repository="org/project",
            branch="feature/staff",bed_path=str(bed_a),
        )
        succeed_scope=dict(
            roomId="room-a",patientId="p",repository="org/project",
            branch="feature/staff",bedPath=str(bed_a),
            assignmentId=aid_a,previousSessionId="session-a",
            newSessionId="session-new",previousDoctorId="doctor-old",
            previousProviderId="provider-old",
            successorDoctorId="doctor-new",successorProviderId="provider-new",
        )
        successor_grant=get_native_grant(body(
            auth.SUCCEED,succeed_scope,"room-a"))
        accepted=admission.session_succeed_atomic(
            db,successor_args,
            room_record=source["room_record"],
            session_record=source["session_record"],
            native_grant=successor_grant)
        assert accepted["created"] and accepted["doctorId"]=="doctor-new"
        assert db.execute("SELECT doctor_id FROM rooms WHERE room_id='room-a'"
                         ).fetchone()[0] == "doctor-new"
        assert db.execute("SELECT body_md FROM messages "
                          "WHERE room_id='room-a'").fetchone()[0] == "PREVIOUS_WORK"
        assert db.execute("SELECT body_md FROM room_reports "
                          "WHERE room_id='room-a'").fetchone()[0] == "PRESERVE_HANDOFF"
        assert db.execute("SELECT COUNT(*) FROM hospital_staffing_authorizations"
                         ).fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM session_events "
                          "WHERE session_id='session-new'").fetchone()[0] == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None

print("HOSPITAL SIGNED STAFFING ATOMIC // PASS // exact native-scoped consent inside original Session and Doctor transactions, rollback of grant + row, retained history; RPC HELD, NO INSTALL")
