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

# Import the independently exercised CI-only signed PENDING verifier into
# the actual Session/Doctor source transaction rehearsal. It runs its own
# hostile signature suite first; it provides NO native permissions.
SIGNED_CI = runpy.run_path(
    str(ROOT/"tests"/"test-px-hospital-staffing-signed-history-ci.py"),
    run_name="hospital_signed_source_gate_ci",
)

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
        # A distinct witness store is only a *disposable CI stand-in* for a
        # future independently protected monotonic history. The test cannot
        # enroll a trusted custodian or make two SQLite databases atomic.
        history_floor = {
            "required": False, "witness": None,
            # The write-ahead variant is a disposable experiment, NOT a
            # trusted external process or operator authorization.
            "write_ahead": False, "fixture_lease": None,
            "signed": None,
        }

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
            if history_floor["write_ahead"]:
                independent = history_floor["witness"]
                if independent is None:
                    raise auth.StaffingGrantHold(
                        "HOSPITAL_STAFFING_GRANT_HOLD // "
                        "CI_WRITE_AHEAD_WITNESS_UNAVAILABLE")
                try:
                    reserved=independent.execute(
                        "SELECT commit_sha256,grant_digest,writer_instance,"
                        "status FROM ci_write_ahead_reservations "
                        "WHERE request_nonce=?", (body["requestNonce"],)
                    ).fetchone()
                except sqlite3.Error as exc:
                    raise auth.StaffingGrantHold(
                        "HOSPITAL_STAFFING_GRANT_HOLD // "
                        "CI_WRITE_AHEAD_WITNESS_UNAVAILABLE") from exc
                if reserved is None:
                    raise auth.StaffingGrantHold(
                        "HOSPITAL_STAFFING_GRANT_HOLD // "
                        "CI_WRITE_AHEAD_HISTORY_ABSENT_UNKNOWN")
                if history_floor["signed"] is not None:
                    context=history_floor["signed"]
                    # Bind a signed, externally floor-pinned PENDING packet
                    # to the *actual* grant and Session COMMIT bytes before
                    # calling original source grant.consume. The expected
                    # writer-release pin is supplied outside the packet.
                    expected_signed=dict(
                        requestNonce=body["requestNonce"],
                        scopeDigest=hashlib.sha256(
                            transport.canonical(scope)).hexdigest(),
                        commitDigest=hashlib.sha256(raw).hexdigest(),
                        grantDigest=grant.digest,
                        writerInstance=body["writerInstance"],
                        hostId=body["hostId"],
                        writerReleaseSha256=context["writer_release"],
                        issuerReleaseSha256=body["issuerReleaseSha256"],
                        policyGeneration=body["policyGeneration"],
                    )
                    try:
                        signed_result=SIGNED_CI["verify"](
                            context["packet"],
                            installed_ci_pin=context["pin"],
                            expected=expected_signed,
                            independent_floor=context["floor"],
                        )
                    except SIGNED_CI["HistoryHold"] as exc:
                        raise auth.StaffingGrantHold(
                            "HOSPITAL_STAFFING_GRANT_HOLD // "
                            "CI_SIGNED_HISTORY_EVIDENCE_HOLD: " + str(exc)
                        ) from exc
                    assert signed_result["canExecuteNewGrant"] is False
                    assert signed_result["canDeclareCommitted"] is False
                    assert signed_result["canDeclareRefused"] is False
                    # This PENDING observation grants NO authority; the
                    # separate one-use fixture lease remains mandatory.
                expected=(body["requestNonce"],hashlib.sha256(raw).hexdigest(),
                          grant.digest,body["writerInstance"])
                observed=(body["requestNonce"],reserved[0],reserved[1],
                          reserved[2])
                if (reserved[3]!="PENDING" or observed!=expected
                        or history_floor["fixture_lease"]!=expected):
                    raise auth.StaffingGrantHold(
                        "HOSPITAL_STAFFING_GRANT_HOLD // "
                        "CI_WRITE_AHEAD_ORIGINAL_REQUEST_ALREADY_RESERVED")
                # A *process-local* CI lease is spent before the original
                # grant/Session transaction starts. Restart cannot recreate
                # it. This is NOT an installed trusted issuer/seat mechanism.
                history_floor["fixture_lease"]=None
            if history_floor["required"]:
                independent = history_floor["witness"]
                if independent is None:
                    raise auth.StaffingGrantHold(
                        "HOSPITAL_STAFFING_GRANT_HOLD // "
                        "CI_ONLY_INDEPENDENT_HISTORY_UNAVAILABLE")
                try:
                    found = independent.execute(
                        "SELECT original_commit_sha256 FROM ci_history_floor "
                        "WHERE request_nonce=?", (body["requestNonce"],)
                    ).fetchone()
                except sqlite3.Error as exc:
                    raise auth.StaffingGrantHold(
                        "HOSPITAL_STAFFING_GRANT_HOLD // "
                        "CI_ONLY_INDEPENDENT_HISTORY_UNAVAILABLE") from exc
                # A known historical request must be terminally fenced
                # even after local DB rollback; a missing external witness
                # is likewise NOT proof that this request never committed.
                reason = ("CI_ONLY_SEPARATE_HISTORY_FLOOR_HOLD"
                          if found else "CI_ONLY_HISTORY_ABSENT_UNCERTAIN")
                raise auth.StaffingGrantHold(
                    "HOSPITAL_STAFFING_GRANT_HOLD // " + reason)
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
        # Rollback/lost-history attack after an actual source COMMIT:
        # 1. Back up the disposable Hospital DB immediately *before*
        #    the original signed staffing operation.
        # 2. Commit the original Session, record its identity in a second
        #    disposable WAL file, then restore the old Hospital DB image.
        # 3. Show that an unaudited local-only hook accepts a fresh signed
        #    grant for the SAME request after local history disappears.
        # 4. Restore the old DB again; require a separate-history witness
        #    and prove the fresh grant cannot consume or create a Session.
        #
        # Real external history must be independently enrolled, durable,
        # antirollback-protected and failure-atomic. This fixture is NONE
        # of those things; in particular its witness is recorded *after*
        # the original COMMIT, leaving a real-world crash window.
        rollback_bed,rollback_assignment=room("room-rollback")
        prepared_rooms["room-rollback"]=(rollback_bed,rollback_assignment)
        rollback_db_path=root/"before-commit-rollback-ci.db"
        with closing(sqlite3.connect(
                str(rollback_db_path),isolation_level=None)) as backup:
            db.backup(backup)
            original_case=plan("room-rollback","session-rollback")
            original_receipt=commit(original_case)
            assert original_receipt["fixtureTransactionCommitted"] is True
            original_req=original_case[0]
            original_signed_body=__import__("json").loads(
                original_case[2])["body"]
            original_commit_sha=hashlib.sha256(original_case[3]).hexdigest()
            assert db.execute(
                "SELECT terminal FROM ci_staffing_result_v14_candidate "
                "WHERE request_nonce=?",
                (original_req["requestNonce"],)
            ).fetchone()[0]=="COMMITTED"
            assert db.execute(
                "SELECT session_id FROM sessions WHERE session_id='session-rollback'"
            ).fetchone()[0]=="session-rollback"

            # Separate file, not a signed trust anchor. The test only
            # models what durable independent history could witness.
            witness_path=root/"separate-untrusted-witness-ci.db"
            assert witness_path!=rollback_db_path
            with closing(sqlite3.connect(
                    str(witness_path),isolation_level=None)) as witness:
                witness.execute("PRAGMA journal_mode=WAL")
                witness.execute("PRAGMA synchronous=FULL")
                witness.execute(
                    "CREATE TABLE ci_history_floor("
                    "request_nonce TEXT PRIMARY KEY,"
                    "original_commit_sha256 TEXT NOT NULL)")
                witness.execute(
                    "INSERT INTO ci_history_floor VALUES(?,?)",
                    (original_req["requestNonce"],original_commit_sha))

                backup.backup(db)
                assert db.execute(
                    "SELECT COUNT(*) FROM sessions "
                    "WHERE session_id='session-rollback'"
                ).fetchone()[0]==0
                assert db.execute(
                    "SELECT COUNT(*) FROM ci_staffing_result_v14_candidate "
                    "WHERE request_nonce=?",
                    (original_req["requestNonce"],)
                ).fetchone()[0]==0
                assert db.execute(
                    "SELECT COUNT(*) FROM hospital_staffing_authorizations "
                    "WHERE nonce=?",
                    (original_signed_body["nonce"],)
                ).fetchone()[0]==0

                def different_signed_case():
                    fresh=coordinator.SourceStaffingRehearsal(
                        session_record=original["session_record"],
                        room_record=original["room_record"])
                    reply=fresh.prepare(
                        db,transport.canonical(original_req),
                        kernel_peer=PEER)
                    new_signed=make_grant(original_req,reply)
                    new_body=__import__("json").loads(new_signed)["body"]
                    assert reply["writerInstance"]!=original_case[1]["writerInstance"]
                    assert new_body["nonce"]!=original_signed_body["nonce"]
                    assert new_body["approvalId"]!=original_signed_body["approvalId"]
                    assert new_body["requestNonce"]==original_req["requestNonce"]
                    new_raw=transport.canonical(dict(
                        original_req,kind="commit",
                        writerInstance=reply["writerInstance"],
                        signedEnvelope=b64(new_signed)))
                    return fresh,(original_req,reply,new_signed,new_raw)

                # Deliberate negative control: without independent history,
                # the *real Session source path* accepts a new signed grant
                # once its local journal and grant ledger were rolled back.
                local_restart,local_case=different_signed_case()
                unsafe_replay=commit(
                    local_case,coordinator_instance=local_restart)
                assert unsafe_replay["fixtureTransactionCommitted"] is True
                assert db.execute(
                    "SELECT COUNT(*) FROM sessions "
                    "WHERE session_id='session-rollback'"
                ).fetchone()[0]==1
                assert db.execute(
                    "SELECT COUNT(*) FROM ci_staffing_result_v14_candidate "
                    "WHERE request_nonce=?",
                    (original_req["requestNonce"],)
                ).fetchone()[0]==1

                # Rewind disposable Hospital bytes again. This time the
                # independent floor can veto before the real v13 consume.
                backup.backup(db)
                history_floor["required"]=True
                history_floor["witness"]=witness
                protected_restart,protected_case=different_signed_case()
                denied(lambda:commit(
                    protected_case,coordinator_instance=protected_restart),
                    "CI_ONLY_SEPARATE_HISTORY_FLOOR_HOLD")
                assert db.execute(
                    "SELECT COUNT(*) FROM sessions "
                    "WHERE session_id='session-rollback'"
                ).fetchone()[0]==0
                assert db.execute(
                    "SELECT COUNT(*) FROM hospital_staffing_authorizations "
                    "WHERE room_id='room-rollback'"
                ).fetchone()[0]==0

                # Missing external history is UNKNOWN, not a safe grant.
                witness.execute(
                    "DELETE FROM ci_history_floor WHERE request_nonce=?",
                    (original_req["requestNonce"],))
                missing_restart,missing_case=different_signed_case()
                denied(lambda:commit(
                    missing_case,coordinator_instance=missing_restart),
                    "CI_ONLY_HISTORY_ABSENT_UNCERTAIN")
                # Unreachable or missing custodian also holds instead of
                # interpreting lack of a record as never committed.
                history_floor["witness"]=None
                unavailable_restart,unavailable_case=different_signed_case()
                denied(lambda:commit(
                    unavailable_case,coordinator_instance=unavailable_restart),
                    "CI_ONLY_INDEPENDENT_HISTORY_UNAVAILABLE")
                history_floor["required"]=False
                assert db.execute(
                    "SELECT COUNT(*) FROM sessions "
                    "WHERE session_id='session-rollback'"
                ).fetchone()[0]==0
                assert db.execute(
                    "SELECT COUNT(*) FROM hospital_staffing_authorizations "
                    "WHERE room_id='room-rollback'"
                ).fetchone()[0]==0
                assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
                assert db.execute("PRAGMA foreign_key_check").fetchone() is None

        # WRITE-AHEAD ORDERING REHEARSAL: a second disposable SQLite
        # witness is committed BEFORE the actual Session source transaction.
        # This changes the failure mode from "COMMIT with no witness" into
        # "PENDING witness, COMMIT possibly not performed". A PENDING
        # reservation is terminal for *reissue of the same requestNonce*
        # until an independently authenticated recovery decision exists.
        # It is not evidence of COMMITTED or REFUSED by itself.
        ahead_bed,ahead_assignment=room("room-write-ahead")
        prepared_rooms["room-write-ahead"]=(ahead_bed,ahead_assignment)
        ahead_case=plan("room-write-ahead","session-write-ahead")
        ahead_request,ahead_prepared,ahead_signed,ahead_raw=ahead_case
        ahead_body=__import__("json").loads(ahead_signed)["body"]
        ahead_digest=hashlib.sha256(
            auth.DOMAIN+auth.canonical(ahead_body)).hexdigest()
        ahead_commit_sha=hashlib.sha256(ahead_raw).hexdigest()
        ahead_identity=(ahead_request["requestNonce"],ahead_commit_sha,
                        ahead_digest,ahead_prepared["writerInstance"])
        ahead_backup_path=root/"before-write-ahead-source-ci.db"
        witness_ahead_path=root/"untrusted-write-ahead-witness-ci.db"
        assert ahead_backup_path!=witness_ahead_path
        with closing(sqlite3.connect(
                str(ahead_backup_path),isolation_level=None)) as ahead_backup:
            db.backup(ahead_backup)
            with closing(sqlite3.connect(
                    str(witness_ahead_path),isolation_level=None)) as ahead_witness:
                ahead_witness.execute("PRAGMA journal_mode=WAL")
                ahead_witness.execute("PRAGMA synchronous=FULL")
                ahead_witness.execute(
                    "CREATE TABLE ci_write_ahead_reservations("
                    "request_nonce TEXT PRIMARY KEY,"
                    "commit_sha256 TEXT NOT NULL,"
                    "grant_digest TEXT NOT NULL,"
                    "writer_instance TEXT NOT NULL,"
                    "status TEXT NOT NULL CHECK(status IN ('PENDING',"
                    "'SOURCE_COMMIT_SEEN_CI')))")
                ahead_witness.execute(
                    "INSERT INTO ci_write_ahead_reservations VALUES("
                    "?,?,?,?, 'PENDING')",ahead_identity)
                # Separate connection verifies that reservation survived
                # closure of the write-ahead transaction. Not evidence that
                # the file is independently protected against host rollback.
                with closing(sqlite3.connect(
                        str(witness_ahead_path),
                        isolation_level=None)) as check_witness:
                    assert check_witness.execute(
                        "SELECT status FROM ci_write_ahead_reservations "
                        "WHERE request_nonce=?",
                        (ahead_request["requestNonce"],)
                    ).fetchone()[0]=="PENDING"
                # If the worker dies after durable reservation but BEFORE
                # source COMMIT, PENDING must not permit a new signed grant.
                history_floor["write_ahead"]=True
                history_floor["witness"]=ahead_witness
                history_floor["fixture_lease"]=None
                pre_crash=coordinator.SourceStaffingRehearsal(
                    session_record=original["session_record"],
                    room_record=original["room_record"])
                prepared_again=pre_crash.prepare(
                    db,transport.canonical(ahead_request),kernel_peer=PEER)
                changed_signed=make_grant(ahead_request,prepared_again)
                changed_raw=transport.canonical(dict(
                    ahead_request,kind="commit",
                    writerInstance=prepared_again["writerInstance"],
                    signedEnvelope=b64(changed_signed)))
                denied(lambda:commit(
                    (ahead_request,prepared_again,changed_signed,changed_raw),
                    coordinator_instance=pre_crash),
                    "CI_WRITE_AHEAD_ORIGINAL_REQUEST_ALREADY_RESERVED")
                assert db.execute(
                    "SELECT COUNT(*) FROM sessions "
                    "WHERE session_id='session-write-ahead'"
                ).fetchone()[0]==0

                # Make the CI witness cryptographically bind to the exact
                # grant/COMMIT/scope used by the real source transaction.
                # All key, release and floor values are synthetic and
                # injected by the fixture; this is NOT root enrollment.
                ci_history_signer=Ed25519PrivateKey.generate()
                ci_writer_release="c"*64
                ci_history_expected=dict(
                    requestNonce=ahead_request["requestNonce"],
                    scopeDigest=hashlib.sha256(transport.canonical(
                        ahead_request["intent"])).hexdigest(),
                    commitDigest=ahead_commit_sha,
                    grantDigest=ahead_digest,
                    writerInstance=ahead_prepared["writerInstance"],
                    hostId=ahead_body["hostId"],
                    writerReleaseSha256=ci_writer_release,
                    issuerReleaseSha256=ahead_body["issuerReleaseSha256"],
                    policyGeneration=ahead_body["policyGeneration"],
                )
                ci_history_body=dict(
                    ci_history_expected,
                    schema=SIGNED_CI["SCHEMA"],
                    purpose=SIGNED_CI["PURPOSE"],
                    sequence=31,
                    state="PENDING",
                )
                history_floor["signed"]=dict(
                    packet=SIGNED_CI["issue"](
                        ci_history_signer,ci_history_body),
                    pin=ci_history_signer.public_key(),
                    floor=31,writer_release=ci_writer_release,
                )
                # Only the original fixture writer has a one-use in-memory
                # lease for this PENDING reservation. It is consumed before
                # the actual signed grant and source transaction execute.
                history_floor["fixture_lease"]=ahead_identity
                original_outcome=commit(ahead_case)
                assert original_outcome["fixtureTransactionCommitted"] is True
                assert history_floor["fixture_lease"] is None
                assert db.execute(
                    "SELECT COUNT(*) FROM sessions "
                    "WHERE session_id='session-write-ahead'"
                ).fetchone()[0]==1
                # Deliberately do NOT finalize the second history file:
                # simulate a crash after source COMMIT but before separate
                # witness acknowledgement. PENDING remains conservative.
                assert ahead_witness.execute(
                    "SELECT status FROM ci_write_ahead_reservations "
                    "WHERE request_nonce=?",
                    (ahead_request["requestNonce"],)
                ).fetchone()[0]=="PENDING"

                ahead_backup.backup(db)
                assert db.execute(
                    "SELECT COUNT(*) FROM sessions "
                    "WHERE session_id='session-write-ahead'"
                ).fetchone()[0]==0
                assert db.execute(
                    "SELECT COUNT(*) FROM ci_staffing_result_v14_candidate "
                    "WHERE request_nonce=?",
                    (ahead_request["requestNonce"],)
                ).fetchone()[0]==0
                assert db.execute(
                    "SELECT COUNT(*) FROM hospital_staffing_authorizations "
                    "WHERE nonce=?", (ahead_body["nonce"],)
                ).fetchone()[0]==0
                after_rollback=coordinator.SourceStaffingRehearsal(
                    session_record=original["session_record"],
                    room_record=original["room_record"])
                after_prepared=after_rollback.prepare(
                    db,transport.canonical(ahead_request),kernel_peer=PEER)
                after_signed=make_grant(ahead_request,after_prepared)
                after_body=__import__("json").loads(after_signed)["body"]
                assert after_body["nonce"]!=ahead_body["nonce"]
                assert after_body["approvalId"]!=ahead_body["approvalId"]
                after_raw=transport.canonical(dict(
                    ahead_request,kind="commit",
                    writerInstance=after_prepared["writerInstance"],
                    signedEnvelope=b64(after_signed)))
                # A newly signed grant has a different writer/COMMIT/grant.
                # Even with a structurally valid signed PENDING packet,
                # its *original transaction identity* must not be borrowed.
                denied(lambda:commit(
                    (ahead_request,after_prepared,after_signed,after_raw),
                    coordinator_instance=after_rollback),
                    "CI_SIGNED_HISTORY_EVIDENCE_HOLD")
                # Missing pin and changed independently pinned floor must
                # also block before the source grant ledger can be written.
                history_floor["signed"]["pin"]=None
                no_pin=coordinator.SourceStaffingRehearsal(
                    session_record=original["session_record"],
                    room_record=original["room_record"])
                np_prepared=no_pin.prepare(
                    db,transport.canonical(ahead_request),kernel_peer=PEER)
                np_signed=make_grant(ahead_request,np_prepared)
                np_raw=transport.canonical(dict(
                    ahead_request,kind="commit",
                    writerInstance=np_prepared["writerInstance"],
                    signedEnvelope=b64(np_signed)))
                denied(lambda:commit(
                    (ahead_request,np_prepared,np_signed,np_raw),
                    coordinator_instance=no_pin),
                    "CI_SIGNED_HISTORY_EVIDENCE_HOLD")
                history_floor["signed"]["pin"]=ci_history_signer.public_key()
                history_floor["signed"]["floor"]=32
                stale_floor=coordinator.SourceStaffingRehearsal(
                    session_record=original["session_record"],
                    room_record=original["room_record"])
                sf_prepared=stale_floor.prepare(
                    db,transport.canonical(ahead_request),kernel_peer=PEER)
                sf_signed=make_grant(ahead_request,sf_prepared)
                sf_raw=transport.canonical(dict(
                    ahead_request,kind="commit",
                    writerInstance=sf_prepared["writerInstance"],
                    signedEnvelope=b64(sf_signed)))
                denied(lambda:commit(
                    (ahead_request,sf_prepared,sf_signed,sf_raw),
                    coordinator_instance=stale_floor),
                    "CI_SIGNED_HISTORY_EVIDENCE_HOLD")
                history_floor["signed"]["floor"]=31
                assert db.execute(
                    "SELECT COUNT(*) FROM sessions "
                    "WHERE session_id='session-write-ahead'"
                ).fetchone()[0]==0

                # Unavailable witness, missing row, or corrupted reservation
                # must all hold before any new source or grant is consumed.
                history_floor["witness"]=None
                no_witness=coordinator.SourceStaffingRehearsal(
                    session_record=original["session_record"],
                    room_record=original["room_record"])
                nw_prepared=no_witness.prepare(
                    db,transport.canonical(ahead_request),kernel_peer=PEER)
                nw_signed=make_grant(ahead_request,nw_prepared)
                nw_raw=transport.canonical(dict(
                    ahead_request,kind="commit",
                    writerInstance=nw_prepared["writerInstance"],
                    signedEnvelope=b64(nw_signed)))
                denied(lambda:commit(
                    (ahead_request,nw_prepared,nw_signed,nw_raw),
                    coordinator_instance=no_witness),
                    "CI_WRITE_AHEAD_WITNESS_UNAVAILABLE")

                history_floor["witness"]=ahead_witness
                ahead_witness.execute(
                    "DELETE FROM ci_write_ahead_reservations WHERE "
                    "request_nonce=?", (ahead_request["requestNonce"],))
                deleted=coordinator.SourceStaffingRehearsal(
                    session_record=original["session_record"],
                    room_record=original["room_record"])
                dl_prepared=deleted.prepare(
                    db,transport.canonical(ahead_request),kernel_peer=PEER)
                dl_signed=make_grant(ahead_request,dl_prepared)
                dl_raw=transport.canonical(dict(
                    ahead_request,kind="commit",
                    writerInstance=dl_prepared["writerInstance"],
                    signedEnvelope=b64(dl_signed)))
                denied(lambda:commit(
                    (ahead_request,dl_prepared,dl_signed,dl_raw),
                    coordinator_instance=deleted),
                    "CI_WRITE_AHEAD_HISTORY_ABSENT_UNKNOWN")
                assert db.execute(
                    "SELECT COUNT(*) FROM sessions "
                    "WHERE session_id='session-write-ahead'"
                ).fetchone()[0]==0
                assert db.execute(
                    "SELECT COUNT(*) FROM hospital_staffing_authorizations "
                    "WHERE room_id='room-write-ahead'"
                ).fetchone()[0]==0
                history_floor["witness"]=None
                history_floor["write_ahead"]=False
                history_floor["fixture_lease"]=None
                history_floor["signed"]=None
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
    "local rollback permits fresh signed grant without witness; "
    "separate CI floor blocks reissue and missing/unavailable history; "
    "write-ahead signed PENDING checked within real Session transaction "
    "before grant consumption; rollback, bad pin/floor/new grant HOLD; "
    "no enrolled custodian or atomic two-store commit; native OFF"
)
