#!/usr/bin/env python3
"""Hospital native staffing protected PREPARE/COMMIT disposable CI rehearsal.

No installed socket, native seat verifier, live database, private key or
production grant. All runtime issuer functions are mocked ONLY within this
runner-only test and each SQLite database is allocated under RUNNER_TEMP.
"""
from __future__ import annotations

import base64
from contextlib import closing
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

if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()):
    raise SystemExit("HOSPITAL_NATIVE_STAFFING_REHEARSAL_HOLD // CI_ONLY")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import px_hospital_staffing_transport as transport
import px_hospital_staffing_prepare_commit as coordinator
import px_hospital_staffing_grants as auth
import px_hospital_staffing_operator_review as review
import px_hospital_staffing_ledger_recovery as recovery
import px_hospital_staffing_admission as admission
import px_hospital_protected_store_bridge as bridge

assert bridge.route_coverage()
assert "session-attach-atomic" not in bridge.WRITE_COMMANDS
assert "session-succeed-atomic" not in bridge.WRITE_COMMANDS
assert not hasattr(transport, "listen")
assert not hasattr(coordinator, "NativeSocket")
assert auth.DOMAIN != __import__("px_hospital_room_authority").DOMAIN
assert coordinator.PREPARE_TTL_SECONDS <= 45

def denied(call, needle):
    try:
        call()
    except (RuntimeError, sqlite3.Error) as exc:
        assert needle in str(exc), (needle, str(exc))
        return
    raise AssertionError("SECURITY_TEST_UNEXPECTEDLY_ACCEPTED")

def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def sign(private, grant):
    return auth.canonical({
        "body":grant,
        "signature":b64(private.sign(auth.DOMAIN + auth.canonical(grant))),
    })

PEER=(5001,0,1234567)
WRONG_PEER=(6001,0,7654321)
HOST="a"*64

with tempfile.TemporaryDirectory(
        prefix="hospital-staff-plan-", dir=os.environ["RUNNER_TEMP"]) as td:
    root = Path(td)
    original = runpy.run_path(str(ROOT / "bin" / "px-hospital-store"),
                              run_name="staff_coordinator_v12_ci")
    priv = Ed25519PrivateKey.generate()
    forgery = Ed25519PrivateKey.generate()
    with closing(sqlite3.connect(str(root/"hospital.db"), isolation_level=None)
                 ) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        assert original["migrate"](db) == 12
        v13 = (ROOT / "packaging/hospital-trash-restore" /
               "candidate-staffing-ledger-v13.sql").read_text("utf-8")
        db.executescript(v13)
        assert db.execute("SELECT value FROM schema_meta "
                          "WHERE key='schema_version'").fetchone()[0]=="13"
        db.execute("INSERT INTO patients(patient_id,repository)"
                   " VALUES('p','org/project')")
        for doctor in ("doctor-old","doctor-new"):
            db.execute("INSERT INTO doctors(doctor_id,status) "
                       "VALUES(?,'ACTIVE')",(doctor,))
        def room(name):
            bed=root/name
            bed.mkdir()
            db.execute(
                "INSERT INTO rooms(room_id,patient_id,branch,bed_path,"
                "doctor_id,provider_id) VALUES(?,'p','branch/ci',?,"
                "'doctor-old','provider-old')",(name,str(bed))
            )
            aid=db.execute(
                "INSERT INTO assignments(room_id,patient_id,status,goal_md)"
                " VALUES(?,'p','ACTIVE','ci-only')",(name,)
            ).lastrowid
            db.execute("UPDATE rooms SET current_assignment_id=? WHERE room_id=?",
                       (str(aid),name))
            return bed,str(aid)
        bed_a, aid_a = room("room-a")
        bed_b, aid_b = room("room-b")
        planner=coordinator.SourceStaffingRehearsal(
            session_record=original["session_record"],
            room_record=original["room_record"],
        )
        def scope(room_id, bed, assignment, session):
            return dict(roomId=room_id,patientId="p",repository="org/project",
                        branch="branch/ci",bedPath=str(bed),
                        assignmentId=assignment,sessionId=session,
                        doctorId="doctor-old",providerId="provider-old",
                        mode="create")
        def request(operation, intent, nonce=None):
            return dict(schema=transport.SCHEMA,kind="prepare",
                        action=operation,roomId=intent["roomId"],intent=intent,
                        requestNonce=nonce or b64(secrets.token_bytes(32)))
        def prepare(data, peer=PEER):
            return planner.prepare(db,transport.canonical(data),
                                   kernel_peer=peer)
        def grant_for(data, prepared, signer=priv, **changes):
            now=int(time.time())
            body=dict(
                schema=auth.SCHEMA,audience=auth.AUDIENCE,
                operation=data["action"],scope=dict(data["intent"]),
                roomRevision=prepared["expectedRevision"],
                graphDigest=prepared["expectedDigest"],
                operatorId="uid:1001",operatorUid=1001,
                polkitActionId=auth.POLKIT_ACTIONS[data["action"]],
                policyGeneration=3,clientExecutableSha256="a"*64,
                issuerReleaseSha256="b"*64,
                reviewDigest=review.review_digest(
                    data,prepared,operator_uid=1001,
                    seat_id="logind-seat0-ciFixture",
                    client_sha="a"*64,issuer_release_sha="b"*64,
                    policy_generation=3),
                approvalId="approval-"+secrets.token_hex(16),
                seatId="logind-seat0-ciFixture",
                hostId=HOST,
                nonce=b64(secrets.token_bytes(32)),
                requestNonce=data["requestNonce"],
                writerInstance=prepared["writerInstance"],
                issuedAt=now,expiresAt=now+25,
            )
            body.update(changes)
            return sign(signer,body)
        fixture_policy=dict(
            schema=auth.release_policy.SCHEMA,operatorUid=1001,
            clientExecutableSha256="a"*64,issuerReleaseSha256="b"*64,
            hostId=HOST,policyGeneration=3,
            allowedOperations=sorted([auth.ATTACH,auth.SUCCEED]),
            expiresAt=int(time.time())+3600,
        )
        def commit_frame(data,prepared,envelope):
            return dict(data,kind="commit",
                        writerInstance=prepared["writerInstance"],
                        signedEnvelope=b64(envelope))
        def commit(data,prep,envelope,peer=PEER,policy=None):
            with patch.object(auth,"trusted_public_key",
                              return_value=priv.public_key()), \
                 patch.object(auth,"installed_host_binding",
                              return_value=HOST), \
                 patch.object(auth.release_policy,"read_installed_policy",
                              return_value=fixture_policy if policy is None
                              else policy):
                return planner.commit(
                    db,transport.canonical(commit_frame(data,prep,envelope)),
                    kernel_peer=peer)
        def ledger():
            return db.execute(
                "SELECT COUNT(*) FROM hospital_staffing_authorizations"
            ).fetchone()[0]
        def recover_ci(data, prepared, envelope):
            # This fixture verifies real Ed25519 bytes with a generated
            # *caller-selected CI key*, never an installed root issuer.
            body = __import__("json").loads(envelope)["body"]
            candidate = auth._verify_bytes(
                envelope,priv.public_key(),now=body["issuedAt"])
            before = db.total_changes
            outcome = recovery.inspect_ci_only(
                db,original_prepare_raw=transport.canonical(data),
                prepared_raw=transport.canonical(prepared),
                commit_raw=transport.canonical(
                    commit_frame(data,prepared,envelope)),
                previously_verified_fixture_grant=candidate)
            assert db.total_changes == before
            assert outcome["nativeWriterReceiptVerified"] is False
            assert outcome["liveHospitalTransactionVerified"] is False
            assert outcome["canRetrySameGrant"] is False
            return outcome
        denied(lambda:recovery.recover_native_staffing(
            commit_raw=b"{}",admin=True),
            "NATIVE_STAFFING_RECOVERY_NOT_INSTALLED")
        denied(lambda:transport.dispatch_native_request(
            transport.canonical(request(auth.ATTACH,scope(
                "room-a",bed_a,aid_a,"session-unused")))),
            "NATIVE_STAFFING_SERVICE_NOT_INSTALLED")
        denied(lambda:admission.dispatch_native_staffing(
            "SESSION_ATTACH",authorized=True),
            "NATIVE_SESSION_DOCTOR_AUTHORITY_NOT_INSTALLED")

        # Mismatch between kernel-verified peer witnesses spends PREPARE.
        intent=scope("room-b",bed_b,aid_b,"session-wrong-peer")
        prepared_req=request(auth.ATTACH,intent)
        ready=prepare(prepared_req)
        signed=grant_for(prepared_req,ready)
        denied(lambda:commit(prepared_req,ready,signed,WRONG_PEER),
               "PREPARE_COMMIT_IDENTITY_CHANGED")
        denied(lambda:commit(prepared_req,ready,signed),
               "MISSING_EXPIRED_OR_REPLAYED_PREPARE")
        assert ledger()==0

        # Approval must name exactly this request nonce, not another
        # syntactically identical PREPARE of the same Room/Doctor.
        prepared_req=request(auth.ATTACH,scope("room-b",bed_b,aid_b,
                                              "session-wrong-nonce"))
        ready=prepare(prepared_req)
        incorrect=grant_for(prepared_req,ready,
                            requestNonce=b64(secrets.token_bytes(32)))
        denied(lambda:commit(prepared_req,ready,incorrect),
               "SIGNED_PREPARE_MISMATCH")
        assert ledger()==0

        # Signed approval for a different operator review digest is
        # cryptographically valid but not this protected PREPARE.
        prepared_req=request(auth.ATTACH,scope("room-b",bed_b,aid_b,
                                              "session-wrong-review"))
        ready=prepare(prepared_req)
        incorrect=grant_for(prepared_req,ready,reviewDigest="d"*64)
        denied(lambda:commit(prepared_req,ready,incorrect),
               "SIGNED_OPERATOR_REVIEW_CHANGED")
        assert ledger()==0

        # Signing a policy generation for a previous operator review
        # must not silently authorize the current source snapshot.
        prepared_req=request(auth.ATTACH,scope("room-b",bed_b,aid_b,
                                              "session-wrong-generation"))
        ready=prepare(prepared_req)
        incorrect=grant_for(prepared_req,ready,policyGeneration=4)
        denied(lambda:commit(prepared_req,ready,incorrect),
               "SIGNED_STAFFING_POLICY_REVOKED_OR_CHANGED")
        assert ledger()==0

        # Polkit Room Trash authorization is not Doctor or Session
        # attachment authorization, regardless of signer identity.
        prepared_req=request(auth.ATTACH,scope("room-b",bed_b,aid_b,
                                              "session-wrong-polkit"))
        ready=prepare(prepared_req)
        incorrect=grant_for(
            prepared_req,ready,
            polkitActionId="org.postapollo.hospital.room-trash")
        denied(lambda:commit(prepared_req,ready,incorrect),
               "STAFFING_POLKIT_ACTION_MISMATCH")
        assert ledger()==0

        # The *installed writer's* release/operator policy must match
        # the signed grant at COMMIT. An old signed grant is revoked
        # immediately if any operator, release or generation rotates.
        for field, changed, reason in (
            ("policyGeneration",4,"SIGNED_STAFFING_POLICY_REVOKED_OR_CHANGED"),
            ("operatorUid",1002,"SIGNED_STAFFING_POLICY_REVOKED_OR_CHANGED"),
            ("clientExecutableSha256","f"*64,
             "SIGNED_STAFFING_POLICY_REVOKED_OR_CHANGED"),
            ("issuerReleaseSha256","e"*64,
             "SIGNED_STAFFING_POLICY_REVOKED_OR_CHANGED"),
            ("allowedOperations",[auth.SUCCEED],
             "STAFFING_OPERATION_NOT_ENROLLED"),
        ):
            req=request(auth.ATTACH,scope("room-b",bed_b,aid_b,
                                          "session-revoked-"+field))
            ready=prepare(req)
            signed=grant_for(req,ready)
            newer=dict(fixture_policy)
            newer[field]=changed
            denied(lambda req=req,ready=ready,signed=signed,newer=newer:
                   commit(req,ready,signed,policy=newer),reason)
            assert ledger()==0

        # A valid signature from a different key cannot authorize.
        prepared_req=request(auth.ATTACH,scope("room-b",bed_b,aid_b,
                                              "session-wrong-key"))
        ready=prepare(prepared_req)
        incorrect=grant_for(prepared_req,ready,signer=forgery)
        denied(lambda:commit(prepared_req,ready,incorrect),
               "SIGNATURE_MISMATCH")
        assert ledger()==0

        # A process restarted between PREPARE and COMMIT cannot be
        # substituted, even if the signer approved the exact Room.
        prepared_req=request(auth.ATTACH,scope("room-b",bed_b,aid_b,
                                              "session-wrong-writer"))
        ready=prepare(prepared_req)
        another=coordinator.SourceStaffingRehearsal(
            session_record=original["session_record"],
            room_record=original["room_record"],
        )
        assert another.writer_instance != planner.writer_instance
        incorrect=grant_for(prepared_req,ready,
                            writerInstance=another.writer_instance)
        denied(lambda:commit(prepared_req,ready,incorrect),
               "SIGNED_PREPARE_MISMATCH")
        assert ledger()==0

        # PREPARE expiry is independent of a still-valid signed grant.
        # A late COMMIT cannot resurrect an expired in-memory ticket.
        planned=request(auth.ATTACH,scope("room-b",bed_b,aid_b,
                                          "session-expired-prepare"))
        ready=prepare(planned)
        signed=grant_for(planned,ready)
        with patch.object(coordinator.time,"monotonic",
                          return_value=10**18):
            denied(lambda:commit(planned,ready,signed),
                   "MISSING_EXPIRED_OR_REPLAYED_PREPARE")
        assert ledger()==0

        # A changed Room graph after PREPARE is rejected; existing
        # Message content remains intact and no approval is consumed.
        prepared_req=request(auth.ATTACH,scope("room-b",bed_b,aid_b,
                                              "session-stale"))
        ready=prepare(prepared_req)
        signed=grant_for(prepared_req,ready)
        db.execute("INSERT INTO messages(room_id,author_role,direction,body_md)"
                   " VALUES('room-b','DOCTOR','incoming','UNALTERED_HISTORY')")
        denied(lambda:commit(prepared_req,ready,signed),
               "PREPARE_ROOM_GRAPH_CHANGED")
        assert ledger()==0

        # A forced failure AFTER approval consumption must roll back
        # the SQLite ledger and Session together. An old PREPARE cannot
        # be reopened, even though SQLite rolled its nonce back.
        planned=request(auth.ATTACH,scope("room-b",bed_b,aid_b,"session-fail"))
        ready=prepare(planned)
        signed=grant_for(planned,ready)
        db.executescript("""
            CREATE TRIGGER block_ci_session
            BEFORE INSERT ON sessions WHEN NEW.session_id='session-fail'
            BEGIN SELECT RAISE(ABORT,'fixture-failure-after-grant'); END;
        """)
        denied(lambda:commit(planned,ready,signed),
               "fixture-failure-after-grant")
        assert ledger()==0
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]==0
        denied(lambda:prepare(planned),"DUPLICATE_OR_FULL_PENDING")
        denied(lambda:commit(planned,ready,signed),
               "MISSING_EXPIRED_OR_REPLAYED_PREPARE")
        db.execute("DROP TRIGGER block_ci_session")
        # No row after the atomic failure cannot establish live REFUSED.
        failed_observation=recover_ci(planned,ready,signed)
        assert failed_observation["status"]==recovery.UNKNOWN
        assert failed_observation["absentLedgerIsNotProofOfRefusal"] is True
        assert failed_observation["neverAutoRetryThisGrant"] is True

        # Fresh, separately signed approval now allows one Session.
        planned=request(auth.ATTACH,scope("room-a",bed_a,aid_a,"session-a"))
        ready=prepare(planned)
        signed=grant_for(planned,ready)
        receipt=commit(planned,ready,signed)
        assert receipt["fixtureTransactionCommitted"] is True
        assert receipt["operatorAuthenticated"] is False
        assert receipt["nativeInstallationVerified"] is False
        assert receipt["sessionId"]=="session-a"
        assert ledger()==1
        committed_original=(planned,ready,signed)
        observed=recover_ci(*committed_original)
        assert observed["status"]==recovery.MATCH
        assert observed["matchingDisposableLedgerRowObserved"] is True
        assert observed["recoveryRequiresProtectedWriter"] is True
        assert observed["productionAuthority"] is False
        assert observed["requestNonceFromUntrustedFixture"]==planned["requestNonce"]
        # A forged different request, altered PREPARE or signed envelope is
        # not allowed to relabel an unrelated durable ledger entry.
        altered=dict(planned,requestNonce=b64(secrets.token_bytes(32)))
        denied(lambda:recovery.inspect_ci_only(
            db,original_prepare_raw=transport.canonical(altered),
            prepared_raw=transport.canonical(ready),
            commit_raw=transport.canonical(commit_frame(planned,ready,signed)),
            previously_verified_fixture_grant=auth._verify_bytes(
                signed,priv.public_key(),now=int(time.time()))),
            "CHANGED_REQUEST_CONTEXT")
        modified=dict(ready,writerInstance="another-writer-ci-9999")
        denied(lambda:recovery.inspect_ci_only(
            db,original_prepare_raw=transport.canonical(planned),
            prepared_raw=transport.canonical(modified),
            commit_raw=transport.canonical(commit_frame(planned,ready,signed)),
            previously_verified_fixture_grant=auth._verify_bytes(
                signed,priv.public_key(),now=int(time.time()))),
            "CHANGED_WRITER_INSTANCE")
        denied(lambda:recovery.inspect_ci_only(
            db,original_prepare_raw=transport.canonical(planned),
            prepared_raw=transport.canonical(ready),
            commit_raw=transport.canonical(commit_frame(planned,ready,signed)),
            previously_verified_fixture_grant=object()),
            "CI_VERIFIED_GRANT_OBJECT_REQUIRED")
        # The CI ledger is independent of present Session status, but any
        # cross-scope or grant-digest mismatch is a security HOLD.
        db.execute("UPDATE hospital_staffing_authorizations SET graph_digest=? "
                   "WHERE room_id='room-a'",("f"*64,))
        denied(lambda:recover_ci(*committed_original),
               "DURABLE_LEDGER_COLLISION_OR_SCOPE_CONFLICT")
        db.execute("UPDATE hospital_staffing_authorizations SET graph_digest=? "
                   "WHERE room_id='room-a'",(__import__("json").loads(signed)
                                             ["body"]["graphDigest"],))
        assert recover_ci(*committed_original)["status"]==recovery.MATCH
        denied(lambda:commit(planned,ready,signed),
               "MISSING_EXPIRED_OR_REPLAYED_PREPARE")

        # Succession requires current Room graph and previous Doctor
        # handoff, while preserving historical Messages and checkpoints.
        db.execute(
            "INSERT INTO messages(room_id,session_id,author_role,direction,"
            "body_md) VALUES('room-a','session-a','DOCTOR','outgoing',"
            "'PRESERVE_PREVIOUS_TRANSCRIPT')"
        )
        db.execute(
            "INSERT INTO room_reports(room_id,session_id,report_kind,body_md)"
            " VALUES('room-a','session-a','HANDOFF','PRESERVE_HANDOFF')"
        )
        db.execute("UPDATE sessions SET status='FAILED',"
                   "ended_at='2026-11-19',active_pid=0 "
                   "WHERE session_id='session-a'")
        successor=dict(
            roomId="room-a",patientId="p",repository="org/project",
            branch="branch/ci",bedPath=str(bed_a),assignmentId=aid_a,
            previousSessionId="session-a",newSessionId="session-new",
            previousDoctorId="doctor-old",previousProviderId="provider-old",
            successorDoctorId="doctor-new",successorProviderId="provider-new",
        )
        planned=request(auth.SUCCEED,successor)
        ready=prepare(planned)
        signed=grant_for(planned,ready)
        receipt=commit(planned,ready,signed)
        assert receipt["action"]==auth.SUCCEED
        assert receipt["sessionId"]=="session-new"
        assert ledger()==2
        assert recover_ci(planned,ready,signed)["status"]==recovery.MATCH
        # Historical attach remains in the durable ledger even after
        # Doctor succession changes the current Room staffing/graph.
        assert recover_ci(*committed_original)["status"]==recovery.MATCH
        assert db.execute("SELECT doctor_id FROM rooms WHERE room_id='room-a'"
                         ).fetchone()[0]=="doctor-new"
        assert db.execute("SELECT body_md FROM room_reports"
                         ).fetchone()[0]=="PRESERVE_HANDOFF"
        assert db.execute("SELECT body_md FROM messages "
                          "WHERE room_id='room-a' ORDER BY rowid DESC LIMIT 1"
                         ).fetchone()[0]=="PRESERVE_PREVIOUS_TRANSCRIPT"
        assert db.execute("SELECT COUNT(*) FROM session_events "
                          "WHERE session_id='session-new'"
                         ).fetchone()[0]==1
        assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None

print("HOSPITAL STAFFING PREPARE/COMMIT + RECOVERY LEDGER CI // PASS // bounded historical grant observation, altered PREPARE and ledger collision refusal, unknown after rolled-back commit, atomic Session/Doctor, no same-grant retry; NATIVE RPC OFF")
