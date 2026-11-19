#!/usr/bin/env python3
"""Hospital staffing grants: isolated signed, one-use source contract tests.

Only disposable v12 SQLite under RUNNER_TEMP; no real key, UID, socket,
Polkit agent, service, Room or direct Hospital DB is touched. Passing
does NOT authorize native Session/Doctor actions or their CLI entrypoints.
"""
from __future__ import annotations

import base64
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import runpy
import secrets
import sqlite3
import sys
import tempfile
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()):
    raise SystemExit("HOSPITAL_STAFFING_GRANTS_HOLD // CI_ONLY")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import px_hospital_room_lifecycle as life
import px_hospital_protected_store_bridge as bridge
import px_hospital_staffing_admission as adapter
import px_hospital_staffing_grants as auth

assert bridge.route_coverage()
assert auth.ATTACH not in bridge.WRITE_COMMANDS
assert auth.SUCCEED not in bridge.WRITE_COMMANDS
assert "session-attach-atomic" not in bridge.WRITE_COMMANDS
assert "session-succeed-atomic" not in bridge.WRITE_COMMANDS
assert not hasattr(auth, "seal_fixture")
assert str(auth.KEY_PATH) == "/etc/post-apollo/hospital/staffing-issuer.pub"
assert auth.DOMAIN != __import__("px_hospital_room_authority").DOMAIN

def refused(action, reason=None):
    try:
        action()
    except (auth.StaffingGrantHold, adapter.NativeStaffingHold) as exc:
        if reason:
            assert reason in str(exc), (reason, str(exc))
        return
    raise AssertionError("UNAUTHORIZED_STAFFING_ACTION_ACCEPTED")

def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

def issue(priv, body):
    data = auth.DOMAIN + auth.canonical(body)
    return auth.canonical({"body":body,"signature":b64(priv.sign(data))})

with tempfile.TemporaryDirectory(
        prefix="hospital-staffing-auth-", dir=os.environ["RUNNER_TEMP"]) as td:
    root = Path(td)
    v12 = runpy.run_path(str(ROOT / "bin" / "px-hospital-store"),
                        run_name="hospital_staff_grant_fixture")
    path = root / "hospital.db"
    with closing(sqlite3.connect(str(path), isolation_level=None)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        assert v12["migrate"](db) == 12
        db.execute("INSERT INTO patients(patient_id,repository) "
                   "VALUES('patient-a','org/project')")
        for doc in ("old-doc", "new-doc"):
            db.execute("INSERT INTO doctors(doctor_id,status) "
                       "VALUES(?,'ACTIVE')",(doc,))
        bed = root / "first-bed"
        bed.mkdir()
        db.execute(
            "INSERT INTO rooms(room_id,patient_id,branch,bed_path,"
            "doctor_id,provider_id) VALUES(?,?,?,?,?,?)",
            ("room-a","patient-a","feature/native",str(bed),
             "old-doc","provider-old")
        )
        aid = db.execute(
            "INSERT INTO assignments(room_id,patient_id,status,goal_md) "
            "VALUES('room-a','patient-a','ACTIVE','fixture goal')"
        ).lastrowid
        db.execute("UPDATE rooms SET current_assignment_id=? "
                   "WHERE room_id='room-a'",(str(aid),))
        snap = life.review(db, "room-a")
        assert snap["state"] == "ACTIVE" and snap["revision"] == 0
        assert snap["digest"] and len(snap["digest"]) == 64
        scope = dict(
            roomId="room-a",patientId="patient-a",repository="org/project",
            branch="feature/native",bedPath=str(bed),assignmentId=str(aid),
            sessionId="session-a",doctorId="old-doc",
            providerId="provider-old",mode="create",
        )
        private = Ed25519PrivateKey.generate()
        other = Ed25519PrivateKey.generate()
        now = int(time.time())
        def make_body(operation=auth.ATTACH, selected=scope, **changes):
            value = dict(
                schema=auth.SCHEMA,audience=auth.AUDIENCE,
                operation=operation,scope=copy.deepcopy(selected),
                roomRevision=snap["revision"],graphDigest=snap["digest"],
                operatorId="operator-a",approvalId="approve-"+secrets.token_hex(16),
                seatId="seat-"+secrets.token_hex(12),
                hostId="a"*64,nonce=b64(secrets.token_bytes(32)),
                issuedAt=now,expiresAt=now+25,
            )
            value.update(changes)
            return value
        body = make_body()
        raw = issue(private, body)
        verified = auth._verify_bytes(raw, private.public_key())
        assert verified.body["operation"] == auth.ATTACH
        assert len(verified.digest) == 64
        assert type(verified) is auth.VerifiedStaffingGrant

        # Invalid signer, rewritten scope, duplicate fields, wrong domain.
        refused(lambda:auth._verify_bytes(raw,other.public_key()),
                "SIGNATURE_MISMATCH")
        forged = copy.deepcopy(body)
        forged["scope"]["doctorId"] = "new-doc"
        altered = json.loads(raw)
        altered["body"] = forged
        refused(lambda:auth._verify_bytes(auth.canonical(altered),
                                           private.public_key()),
                "SIGNATURE_MISMATCH")
        refused(lambda:auth._verify_bytes(
            b'{"body":{},"body":{},"signature":"x"}',private.public_key()),
            "DUPLICATE_FIELD")
        refused(lambda:auth._verify_bytes(raw+b"\n",private.public_key()),
                "NONCANONICAL_ENVELOPE")
        refused(lambda:auth._verify_bytes(
            issue(private,make_body(audience="px-hospital-room-lifecycle-v12")),
            private.public_key()),"WRONG_SIGNING_DOMAIN")
        refused(lambda:auth._verify_bytes(
            issue(private,make_body(expiresAt=now-1,issuedAt=now-25)),
            private.public_key()),"EXPIRED_GRANT")
        refused(lambda:auth._verify_bytes(
            issue(private,make_body(expiresAt=now+300)),
            private.public_key()),"INVALID_GRANT_LIFETIME")
        refused(lambda:auth._verify_bytes(
            issue(private,make_body(scope=dict(scope, mode="garbage"))),
            private.public_key()),"INVALID_ATTACH_MODE")
        refused(lambda:auth._verify_bytes(
            issue(private,make_body(scope=dict(scope, assignmentId="0003"))),
            private.public_key()),"INVALID_ASSIGNMENT")
        refused(lambda:auth._verify_bytes(
            issue(private,make_body(scope=dict(scope, bedPath="/tmp/../bad"))),
            private.public_key()),"INVALID_CANONICAL_BED")
        refused(lambda:auth._verify_bytes(
            issue(private,make_body(scope=dict(scope, unexpected=True))),
            private.public_key()),"EXACT_STAFFING_SCOPE_REQUIRED")
        refused(lambda:auth.VerifiedStaffingGrant(body,"a"*64),
                "UNVERIFIED_GRANT_INSTANCE")
        refused(lambda:adapter.dispatch_native_staffing(
            "SESSION_ATTACH",raw,authorized=True),
                "NATIVE_SESSION_DOCTOR_AUTHORITY_NOT_INSTALLED")

        # Consumption is not a pre-write authorization token and must
        # run with a live source write transaction.
        refused(lambda:verified.consume(
            db,operation=auth.ATTACH,scope=scope),
                "ATOMIC_WRITER_TRANSACTION_REQUIRED")
        db.execute("BEGIN IMMEDIATE")
        refused(lambda:verified.consume(
            db,operation=auth.SUCCEED,scope=scope),"SIGNED_OPERATION_CHANGED")
        refused(lambda:verified.consume(
            db,operation=auth.ATTACH,scope=dict(scope,doctorId="new-doc")),
                "SIGNED_SCOPE_CHANGED")
        refused(lambda:verified.consume(
            db,operation=auth.ATTACH,scope=scope),"LEDGER_NOT_MIGRATED")
        db.rollback()
        assert db.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' "
            "AND name='hospital_staffing_authorizations'"
        ).fetchone()[0] == 0

        # This ledger DDL is CI-only preparation. PX v12 migration does
        # not install it: real protected use must remain HOLD.
        db.executescript("""
          CREATE TABLE hospital_staffing_authorizations (
            nonce TEXT PRIMARY KEY,
            grant_digest TEXT NOT NULL UNIQUE,
            approval_id TEXT NOT NULL UNIQUE,
            room_id TEXT NOT NULL REFERENCES rooms(room_id),
            operation TEXT NOT NULL CHECK (
              operation IN ('SESSION_ATTACH','DOCTOR_SUCCEED')),
            operator_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            graph_digest TEXT NOT NULL
          );
        """)
        db.execute("BEGIN IMMEDIATE")
        received = verified.consume(db,operation=auth.ATTACH,scope=scope)
        assert received["roomId"] == "room-a"
        assert received["operation"] == auth.ATTACH
        db.commit()
        assert db.execute("SELECT count(*) FROM hospital_staffing_authorizations"
                         ).fetchone()[0] == 1
        db.execute("BEGIN IMMEDIATE")
        refused(lambda:verified.consume(
            db,operation=auth.ATTACH,scope=scope),"REPLAYED_APPROVAL")
        db.rollback()

        # An identical signed object changed AFTER verification must not
        # be trusted because the signer only approved the original bytes.
        mutated = auth._verify_bytes(issue(private,make_body()),
                                     private.public_key())
        mutated.body["scope"]["doctorId"] = "new-doc"
        db.execute("BEGIN IMMEDIATE")
        refused(lambda:mutated.consume(
            db,operation=auth.ATTACH,scope=mutated.body["scope"]),
            "VERIFIED_GRANT_MUTATED")
        db.rollback()

        # Failed transactions may not spend the nonce.
        trial = auth._verify_bytes(issue(private,make_body()),
                                   private.public_key())
        db.execute("BEGIN IMMEDIATE")
        trial.consume(db,operation=auth.ATTACH,scope=scope)
        db.rollback()
        assert db.execute("SELECT count(*) FROM hospital_staffing_authorizations"
                         ).fetchone()[0] == 1
        db.execute("BEGIN IMMEDIATE")
        trial.consume(db,operation=auth.ATTACH,scope=scope)
        db.commit()
        assert db.execute("SELECT count(*) FROM hospital_staffing_authorizations"
                         ).fetchone()[0] == 2

        # Doctor succession is distinct, with old and new worker identity
        # bound into the approval and checked against the current Room.
        succeed_scope = dict(
            roomId="room-a",patientId="patient-a",repository="org/project",
            branch="feature/native",bedPath=str(bed),assignmentId=str(aid),
            previousSessionId="session-old",newSessionId="session-new",
            previousDoctorId="old-doc",previousProviderId="provider-old",
            successorDoctorId="new-doc",successorProviderId="provider-new",
        )
        successor = auth._verify_bytes(
            issue(private,make_body(auth.SUCCEED,succeed_scope)),
            private.public_key())
        db.execute("BEGIN IMMEDIATE")
        sucess_receipt = successor.consume(
            db,operation=auth.SUCCEED,scope=succeed_scope)
        db.commit()
        assert sucess_receipt["operation"] == auth.SUCCEED
        refused(lambda:auth._verify_bytes(
            issue(private,make_body(auth.SUCCEED,
                 dict(succeed_scope, previousDoctorId="new-doc",
                      successorDoctorId="new-doc"))),
            private.public_key()),"SAME_SESSION_OR_DOCTOR")

        # A changed source graph cannot accept stale signed consent.
        stale = auth._verify_bytes(issue(private,make_body()),
                                   private.public_key())
        db.execute("INSERT INTO messages(room_id,author_role,direction,body_md)"
                   " VALUES('room-a','DOCTOR','outgoing','fixture message')")
        db.execute("BEGIN IMMEDIATE")
        refused(lambda:stale.consume(
            db,operation=auth.ATTACH,scope=scope),"STALE_ROOM_GRAPH")
        db.rollback()

        # Signing this grant does NOT authenticate a user or install a
        # root-owned signer. No staff Session or Doctor is changed here.
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        assert db.execute("SELECT doctor_id FROM rooms WHERE room_id='room-a'"
                         ).fetchone()[0] == "old-doc"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None

print("HOSPITAL STAFFING GRANTS // PASS // distinct Ed25519 domain, exact Session/Doctor identities, immutable signer, transaction nonce, graph/refusal checks; NO NATIVE DISPATCH OR INSTALL")
