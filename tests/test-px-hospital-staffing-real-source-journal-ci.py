#!/usr/bin/env python3
"""CI-only D1/D2 source-linked candidate journal, NOT a production migration.

This checks REAL Hospital Session attachment source (original PX v12 schema,
source adapter, existing v13 signed grant.consume, BEGIN IMMEDIATE, rollback
and COMMIT) plus an isolated *candidate* SQLite journal hook/trigger. The hook
is TEST-ONLY via unittest.mock; never add it to the installed native writer
or claim approved D1/D2, native writer proof, signer custody or receipt.
"""
from __future__ import annotations

import base64
from contextlib import closing
import hashlib
import os
from pathlib import Path
import runpy
import secrets
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()
        or not sys.platform.startswith("linux")):
    raise SystemExit("HOSPITAL_SOURCE_JOURNAL_CI_HOLD // RUNNER_ONLY")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import px_hospital_staffing_admission as admission
import px_hospital_staffing_grants as auth
import px_hospital_staffing_prepare_commit as coordinator
import px_hospital_staffing_operator_review as review
import px_hospital_staffing_transport as transport

assert admission.dispatch_native_staffing is not None
assert coordinator.SourceStaffingRehearsal.__doc__ is not None
assert not hasattr(coordinator, "NativeSocket")
assert not hasattr(transport, "listen")

PEER = (5001, 0, 1234567)
HOST = "a"*64


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def denied(cb, expected):
    try:
        cb()
    except (RuntimeError, sqlite3.Error) as exc:
        assert expected in str(exc), (expected, str(exc))
        return
    raise AssertionError("HOSPITAL_SOURCE_JOURNAL_CI_HOLD // EXPECTED_" + expected)


with tempfile.TemporaryDirectory(
        prefix="hospital-source-journal-v14-ci-",
        dir=os.environ["RUNNER_TEMP"]) as td:
    root = Path(td)
    original = runpy.run_path(
        str(ROOT/"bin"/"px-hospital-store"), run_name="ci_v14_source_only"
    )
    with closing(sqlite3.connect(
            str(root/"disposable.db"), isolation_level=None)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        assert original["migrate"](db) == 12

        v13 = (ROOT/"packaging"/"hospital-trash-restore"/
               "candidate-staffing-ledger-v13.sql").read_text("utf-8")
        db.executescript(v13)
        assert db.execute("SELECT value FROM schema_meta "
                          "WHERE key='schema_version'").fetchone()[0] == "13"
        # v14 is deliberately placed under tests/fixtures, not packaging
        # or the installed versioned PX migrate() function.
        proposed = (ROOT/"tests"/"fixtures"/
                    "ci-only-staffing-source-journal-v14.sql").read_text("utf-8")
        # An absent, duplicated, or wrong version key must fail the
        # candidate gate before any CI journal table can be installed.
        # This intentionally permits duplicate keys in the hostile
        # miniature schema to test the count guard, even though the real
        # PX schema normally enforces a unique key.
        for history in ((), ("12",), ("13","13"), ("12","13")):
            with closing(sqlite3.connect(
                    ":memory:", isolation_level=None)) as invalid_db:
                invalid_db.execute(
                    "CREATE TABLE schema_meta(key TEXT, value TEXT)")
                for version in history:
                    invalid_db.execute(
                        "INSERT INTO schema_meta(key,value) "
                        "VALUES('schema_version',?)", (version,))
                denied(lambda:invalid_db.executescript(proposed),
                       "CHECK constraint failed")
                if invalid_db.in_transaction:
                    invalid_db.rollback()
                assert invalid_db.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE name='ci_staffing_result_v14_candidate'"
                ).fetchone() is None

        db.executescript(proposed)
        assert db.execute("SELECT value FROM schema_meta "
                          "WHERE key='schema_version'").fetchone()[0] == "13"
        assert db.execute(
            "SELECT contract_version FROM ci_staffing_candidate_contract_meta"
        ).fetchone()[0] == "ci-v14-proposal-only"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

        db.execute("INSERT INTO patients(patient_id,repository) "
                   "VALUES('ci-patient','org/project')")
        db.execute("INSERT INTO doctors(doctor_id,status) "
                   "VALUES('doctor-old','ACTIVE')")

        def room(name):
            bed = root/name
            bed.mkdir()
            db.execute(
                "INSERT INTO rooms(room_id,patient_id,branch,bed_path,"
                "doctor_id,provider_id) VALUES(?,'ci-patient','ci-branch',?,"
                "'doctor-old','provider-old')", (name,str(bed)))
            assignment = db.execute(
                "INSERT INTO assignments(room_id,patient_id,status,goal_md)"
                " VALUES(?,'ci-patient','ACTIVE','isolated-fixture')",
                (name,)).lastrowid
            db.execute(
                "UPDATE rooms SET current_assignment_id=? WHERE room_id=?",
                (str(assignment),name))
            return bed,str(assignment)

        prepared_rooms = {
            name: room(name) for name in ("room-failed","room-success",
                                         "room-refused")
        }
        planner = coordinator.SourceStaffingRehearsal(
            session_record=original["session_record"],
            room_record=original["room_record"])
        private = Ed25519PrivateKey.generate()
        policy = dict(
            schema=auth.release_policy.SCHEMA,
            operatorUid=1001,clientExecutableSha256="a"*64,
            issuerReleaseSha256="b"*64,hostId=HOST,policyGeneration=3,
            allowedOperations=[auth.ATTACH,auth.SUCCEED],
            expiresAt=int(time.time())+3600,
        )

        def original_request(name, session):
            bed,assignment = prepared_rooms[name]
            scope = dict(
                roomId=name,patientId="ci-patient",repository="org/project",
                branch="ci-branch",bedPath=str(bed),
                assignmentId=assignment,sessionId=session,
                doctorId="doctor-old",providerId="provider-old",
                mode="create")
            return dict(schema=transport.SCHEMA,kind="prepare",
                        action=auth.ATTACH,roomId=name,intent=scope,
                        requestNonce=b64(secrets.token_bytes(32)))

        def make_grant(request, prepared):
            now = int(time.time())
            body = dict(
                schema=auth.SCHEMA,audience=auth.AUDIENCE,
                operation=request["action"],scope=request["intent"],
                roomRevision=prepared["expectedRevision"],
                graphDigest=prepared["expectedDigest"],
                operatorId="uid:1001",operatorUid=1001,
                polkitActionId=auth.POLKIT_ACTIONS[request["action"]],
                policyGeneration=3,clientExecutableSha256="a"*64,
                issuerReleaseSha256="b"*64,
                reviewDigest=review.review_digest(
                    request,prepared,operator_uid=1001,
                    seat_id="logind-seat0-ciFixture",
                    client_sha="a"*64,issuer_release_sha="b"*64,
                    policy_generation=3),
                approvalId="approval-"+secrets.token_hex(16),
                seatId="logind-seat0-ciFixture",hostId=HOST,
                nonce=b64(secrets.token_bytes(32)),
                requestNonce=request["requestNonce"],
                writerInstance=prepared["writerInstance"],
                issuedAt=now,expiresAt=now+25,
            )
            return auth.canonical({
                "body":body,
                "signature":b64(private.sign(
                    auth.DOMAIN+auth.canonical(body))),
            })

        def plan(name, session):
            request=original_request(name,session)
            prepared=planner.prepare(
                db,transport.canonical(request),kernel_peer=PEER)
            signed=make_grant(request,prepared)
            commit=dict(request,kind="commit",
                        writerInstance=prepared["writerInstance"],
                        signedEnvelope=b64(signed))
            raw=transport.canonical(commit)
            return request,prepared,signed,raw

        saved_consume=auth.VerifiedStaffingGrant.consume
        active = {}

        def ci_journal_hook(grant, connection, *, operation, scope):
            # This executes INSIDE the actual source-owned BEGIN IMMEDIATE.
            # A Session INSERT failure must roll back this journal and the
            # existing v13 grant consumption in the SAME transaction.
            assert connection is db and connection.in_transaction
            request,prepared,signed,raw=active["case"]
            body=grant.body
            assert body["requestNonce"]==request["requestNonce"]
            assert body["writerInstance"]==prepared["writerInstance"]
            assert body["scope"]==request["intent"]
            assert body["operation"]==operation
            assert hashlib.sha256(
                auth.DOMAIN+auth.canonical(body)).hexdigest()==grant.digest
            # D2 requires the original request identity to be permanently
            # fenced regardless of how many distinct signatures/approvals
            # an issuer generates for that same original PREPARE.
            # This is a CI-only injection inside the real source's
            # BEGIN IMMEDIATE. The existing v13 ledger INSERT lacks this
            # field, so its trigger alone cannot enforce this requirement.
            prior_request=connection.execute(
                "SELECT terminal FROM ci_staffing_result_v14_candidate "
                "WHERE request_nonce=?", (body["requestNonce"],)
            ).fetchone()
            if prior_request is not None:
                raise auth.StaffingGrantHold(
                    "HOSPITAL_STAFFING_GRANT_HOLD // "
                    "CI_ONLY_ORIGINAL_REQUEST_TERMINAL_FENCE")
            original_grant_result=saved_consume(
                grant,connection,operation=operation,scope=scope)
            connection.execute(
                """INSERT INTO ci_staffing_result_v14_candidate(
                   request_nonce,grant_nonce,grant_digest,approval_id,
                   commit_sha256,writer_instance,room_id,operation,session_id,
                   original_scope_sha256,review_digest,graph_digest,terminal,
                   writer_transaction_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (request["requestNonce"],body["nonce"],grant.digest,
                 body["approvalId"],hashlib.sha256(raw).hexdigest(),
                 prepared["writerInstance"],request["roomId"],operation,
                 scope["sessionId"] if operation==auth.ATTACH
                 else scope["newSessionId"],
                 hashlib.sha256(transport.canonical(scope)).hexdigest(),
                 body["reviewDigest"],body["graphDigest"],"COMMITTED",
                 "ci-transaction-"+request["requestNonce"]),
            )
            return original_grant_result

        def commit(case, *, coordinator_instance=None):
            active["case"]=case
            _,_,_,commit_raw=case
            with patch.object(auth,"trusted_public_key",
                              return_value=private.public_key()), \
                 patch.object(auth,"installed_host_binding",
                              return_value=HOST), \
                 patch.object(auth.release_policy,"read_installed_policy",
                              return_value=policy), \
                 patch.object(auth.VerifiedStaffingGrant,"consume",
                              ci_journal_hook):
                return (coordinator_instance or planner).commit(
                    db,commit_raw,kernel_peer=PEER)

        def counts():
            return (
                db.execute("SELECT COUNT(*) FROM ci_staffing_result_v14_candidate"
                           ).fetchone()[0],
                db.execute("SELECT COUNT(*) FROM hospital_staffing_authorizations"
                           ).fetchone()[0],
                db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            )

        # Fail AFTER source grant.consume and CI journal insertion but BEFORE
        # Session insert. All three writes must disappear on rollback.
        failed=plan("room-failed","session-intentionally-failed")
        db.executescript("""
          CREATE TRIGGER ci_abort_source
          BEFORE INSERT ON sessions
          WHEN NEW.session_id='session-intentionally-failed'
          BEGIN SELECT RAISE(ABORT,'CI_SOURCE_INSERT_FAILED'); END;
        """)
        denied(lambda:commit(failed),"CI_SOURCE_INSERT_FAILED")
        assert counts()==(0,0,0),counts()
        denied(lambda:commit(failed),"MISSING_EXPIRED_OR_REPLAYED_PREPARE")
        db.execute("DROP TRIGGER ci_abort_source")

        # Actual approved source handler commits the actual Session, one
        # v13 grant consumption and synthetic journal as a unit.
        success=plan("room-success","session-success")
        source_receipt=commit(success)
        assert source_receipt["fixtureTransactionCommitted"] is True
        assert source_receipt["nativeInstallationVerified"] is False
        assert counts()==(1,1,1),counts()
        ci_journal=db.execute(
            "SELECT * FROM ci_staffing_result_v14_candidate"
            " WHERE request_nonce=?", (success[0]["requestNonce"],)).fetchone()
        assert ci_journal["terminal"]=="COMMITTED"
        assert ci_journal["writer_instance"]==success[1]["writerInstance"]
        assert ci_journal["commit_sha256"]==hashlib.sha256(success[3]).hexdigest()
        assert db.execute(
            "SELECT session_id FROM sessions WHERE session_id='session-success'"
        ).fetchone()["session_id"]=="session-success"
        denied(lambda:commit(success),"MISSING_EXPIRED_OR_REPLAYED_PREPARE")

        # The real atomic DOCTOR_SUCCEED writer shares the same verified
        # one-use grant consumption seam. Historical attachment stays
        # visible even after Room staffing advances to a new Doctor.
        db.execute("INSERT INTO doctors(doctor_id,status) "
                   "VALUES('doctor-new','ACTIVE')")
        db.execute(
            "UPDATE sessions SET status='FAILED',"
            "ended_at='2026-11-21',active_pid=0 "
            "WHERE session_id='session-success'")
        # Hospital's real Doctor source requires an actual durable HANDOFF
        # or checkpoint before succession. Preserve that guard; create the
        # approved *CI fixture* history before taking the PREPARE snapshot.
        db.execute(
            "INSERT INTO room_reports(room_id,session_id,report_kind,body_md)"
            " VALUES('room-success','session-success','HANDOFF',"
            "'CI_ONLY_DURABLE_HANDOFF')")
        next_bed,next_assignment=prepared_rooms["room-success"]
        successor_scope=dict(
            roomId="room-success",patientId="ci-patient",
            repository="org/project",branch="ci-branch",
            bedPath=str(next_bed),assignmentId=next_assignment,
            previousSessionId="session-success",newSessionId="session-next",
            previousDoctorId="doctor-old",
            previousProviderId="provider-old",
            successorDoctorId="doctor-new",
            successorProviderId="provider-new",
        )
        successor_request=dict(
            schema=transport.SCHEMA,kind="prepare",action=auth.SUCCEED,
            roomId="room-success",intent=successor_scope,
            requestNonce=b64(secrets.token_bytes(32)),
        )
        successor_prepared=planner.prepare(
            db,transport.canonical(successor_request),kernel_peer=PEER)
        successor_signed=make_grant(successor_request,successor_prepared)
        successor_raw=transport.canonical(dict(
            successor_request,kind="commit",
            writerInstance=successor_prepared["writerInstance"],
            signedEnvelope=b64(successor_signed)))
        successor_case=(successor_request,successor_prepared,
                        successor_signed,successor_raw)
        successor_receipt=commit(successor_case)
        assert successor_receipt["action"]==auth.SUCCEED
        assert successor_receipt["sessionId"]=="session-next"
        assert successor_receipt["nativeInstallationVerified"] is False
        assert counts()==(2,2,2),counts()
        assert db.execute(
            "SELECT doctor_id FROM rooms WHERE room_id='room-success'"
        ).fetchone()[0]=="doctor-new"
        prior=db.execute(
            "SELECT terminal FROM ci_staffing_result_v14_candidate "
            "WHERE request_nonce=?",(success[0]["requestNonce"],)).fetchone()
        assert prior is not None and prior["terminal"]=="COMMITTED"
        assert db.execute(
            "SELECT terminal FROM ci_staffing_result_v14_candidate "
            "WHERE request_nonce=?",
            (successor_request["requestNonce"],)).fetchone()[0]=="COMMITTED"
        denied(lambda:commit(successor_case),
               "MISSING_EXPIRED_OR_REPLAYED_PREPARE")

        # A trusted REFUSED outcome still needs a PX owner-approved source
        # mechanism. In CI we simulate ONLY the durable terminal row and
        # check that the real grant consumption path respects the SQL fence.
        refused=plan("room-refused","session-refused")
        req,prep,signed,raw=refused
        body=__import__("json").loads(signed)["body"]
        grant_digest=hashlib.sha256(
            auth.DOMAIN+auth.canonical(body)).hexdigest()
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """INSERT INTO ci_staffing_result_v14_candidate(
               request_nonce,grant_nonce,grant_digest,approval_id,
               commit_sha256,writer_instance,room_id,operation,session_id,
               original_scope_sha256,review_digest,graph_digest,terminal,
               writer_transaction_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (req["requestNonce"],body["nonce"],grant_digest,
             body["approvalId"],hashlib.sha256(raw).hexdigest(),
             prep["writerInstance"],req["roomId"],req["action"],
             body["scope"]["sessionId"],
             hashlib.sha256(transport.canonical(req["intent"])).hexdigest(),
             body["reviewDigest"],body["graphDigest"],"REFUSED",
             "ci-terminal-refusal-"+req["requestNonce"]),
        )
        db.commit()
        assert counts()==(3,2,2)
        denied(lambda:commit(refused),
               "CI_ONLY_ORIGINAL_REQUEST_TERMINAL_FENCE")
        assert counts()==(3,2,2),counts()
        # The original v13 trigger also remains a second layer: direct
        # grant consumption with the SAME signed grant is independently
        # stopped by its nonce/digest/approval fence.
        fixture_grant=auth._verify_bytes(
            signed,private.public_key(),now=body["issuedAt"])
        db.execute("BEGIN IMMEDIATE")
        try:
            denied(lambda:saved_consume(
                fixture_grant,db,operation=auth.ATTACH,scope=req["intent"]),
                "REPLAYED_APPROVAL")
        finally:
            if db.in_transaction:
                db.rollback()
        assert counts()==(3,2,2),counts()
        assert db.execute(
            "SELECT COUNT(*) FROM sessions WHERE session_id='session-refused'"
        ).fetchone()[0]==0

        # Critical D2 attack: after issuer/writer coordinator restart, the
        # same original PREPARE nonce is approved again with a DIFFERENT
        # grant nonce, approval ID, grant digest and writer instance.
        # The old v13 trigger cannot see requestNonce, so this is fenced
        # by the proposed same-transaction original-request query, not by
        # accidentally replaying the first signed grant.
        restarted=coordinator.SourceStaffingRehearsal(
            session_record=original["session_record"],
            room_record=original["room_record"])
        new_prepared=restarted.prepare(
            db,transport.canonical(req),kernel_peer=PEER)
        new_signed=make_grant(req,new_prepared)
        changed_body=__import__("json").loads(new_signed)["body"]
        assert changed_body["requestNonce"]==body["requestNonce"]
        assert changed_body["nonce"]!=body["nonce"]
        assert changed_body["approvalId"]!=body["approvalId"]
        assert new_prepared["writerInstance"]!=prep["writerInstance"]
        changed_digest=hashlib.sha256(
            auth.DOMAIN+auth.canonical(changed_body)).hexdigest()
        assert changed_digest!=grant_digest
        new_raw=transport.canonical(dict(
            req,kind="commit",
            writerInstance=new_prepared["writerInstance"],
            signedEnvelope=b64(new_signed)))
        reissued=(req,new_prepared,new_signed,new_raw)
        denied(lambda:commit(reissued,coordinator_instance=restarted),
               "CI_ONLY_ORIGINAL_REQUEST_TERMINAL_FENCE")
        assert counts()==(3,2,2),counts()
        assert db.execute(
            "SELECT terminal FROM ci_staffing_result_v14_candidate "
            "WHERE request_nonce=?", (req["requestNonce"],)
        ).fetchone()[0]=="REFUSED"
        assert db.execute(
            "SELECT COUNT(*) FROM hospital_staffing_authorizations "
            "WHERE nonce=?", (changed_body["nonce"],)
        ).fetchone()[0]==0

        # CI-only observations are not native writer receipts; loss of a
        # committed journal entry must remain UNKNOWN, never REFUSED.
        db.execute(
            "DELETE FROM ci_staffing_result_v14_candidate WHERE request_nonce=?",
            (success[0]["requestNonce"],))
        assert db.execute(
            "SELECT * FROM ci_staffing_result_v14_candidate"
            " WHERE request_nonce=?",(success[0]["requestNonce"],)
        ).fetchone() is None
        assert counts()==(2,2,2)
        # Actual signed grant still cannot be replayed even if a separately
        # maintained history row disappeared.
        denied(lambda:commit(success),"MISSING_EXPIRED_OR_REPLAYED_PREPARE")
        assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        denied(lambda:admission.dispatch_native_staffing(
            "SESSION_ATTACH",approved=True),
            "NATIVE_SESSION_DOCTOR_AUTHORITY_NOT_INSTALLED")

print(
    "HOSPITAL REAL SOURCE D1/D2 CI HOOK // PASS // "
    "real Session+Doctor atomicity + candidate v14 journal rollback, "
    "original-request refusal fence blocks alternate signed grant, "
    "missing/duplicated version guarded, "
    "deleted history remains unauthenticated UNKNOWN; native OFF"
)
