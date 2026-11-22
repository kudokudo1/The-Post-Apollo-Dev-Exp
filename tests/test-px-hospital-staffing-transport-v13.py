#!/usr/bin/env python3
"""Hospital typed staffing frames + candidate v13 ledger: offline-only rehearsal.

The owner PX source remains v12 and must reject this proposed v13 until a
separate migration/old-writer cutover is approved. This CI test does NOT
install, sign, launch a native host, mutate operator data or expose an RPC.
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

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()):
    raise SystemExit("HOSPITAL_STAFFING_TRANSPORT_V13_HOLD // CI_ONLY")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import px_hospital_staffing_transport as transport
import px_hospital_staffing_grants as auth
import px_hospital_staffing_admission as admission
import px_hospital_protected_store_bridge as legacy_bridge
import px_hospital_room_writer as existing_writer

SOURCE = runpy.run_path(
    str(ROOT / "bin" / "px-hospital-store"),
    run_name="px_hospital_candidate_v13_fixture",
)
SQL = (ROOT / "packaging" / "hospital-trash-restore" /
       "candidate-staffing-ledger-v13.sql").read_text("utf-8")


def refused(action, marker):
    try:
        action()
    except (transport.NativeStaffingTransportHold,
            admission.NativeStaffingHold, RuntimeError, sqlite3.Error) as exc:
        assert marker in str(exc), (marker, str(exc))
        return
    raise AssertionError("UNREVIEWED_NATIVE_OPERATION_ACCEPTED")


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


intent = dict(
    roomId="room-1", patientId="patient-1", repository="org/project",
    branch="feature/fixture", bedPath="/tmp/hospital-fixture",
    assignmentId="1", sessionId="session-new", doctorId="doc-old",
    providerId="mock", mode="create",
)
req = {
    "schema": transport.SCHEMA,
    "kind": "prepare",
    "action": auth.ATTACH,
    "roomId": "room-1",
    "intent": intent,
    "requestNonce": b64(secrets.token_bytes(32)),
}
frame = transport.canonical(req)
assert transport.parse_request(frame) == req
assert transport.SCHEMA != existing_writer.SCHEMA
assert transport.SCHEMA != __import__("px_hospital_connections_consent").REQUEST_SCHEMA
assert not any(x in legacy_bridge.WRITE_COMMANDS for x in (
    "session-attach-atomic", "session-succeed-atomic",
    "room-bed-claim-atomic", "room-bed-claim-signed-atomic"))
assert legacy_bridge.route_coverage()
assert not hasattr(existing_writer, "NativeStaffingTransport")
refused(lambda: transport.dispatch_native_request(frame),
        "NATIVE_STAFFING_SERVICE_NOT_INSTALLED")
refused(lambda: transport.dispatch_native_request(
    frame, authorized=True, uid=0, operatorApproved=True),
    "NATIVE_STAFFING_SERVICE_NOT_INSTALLED")

commit = dict(req, kind="commit",
              writerInstance="writer-" + secrets.token_hex(12),
              signedEnvelope=b64(b'{"body":{},"signature":"x"}'))
assert transport.parse_request(transport.canonical(commit)) == commit
refused(lambda:transport.dispatch_native_request(transport.canonical(commit)),
        "NATIVE_STAFFING_SERVICE_NOT_INSTALLED")
successor = dict(
    roomId="room-1", patientId="patient-1", repository="org/project",
    branch="feature/fixture", bedPath="/tmp/hospital-fixture",
    assignmentId="1", previousSessionId="session-old",
    newSessionId="session-next", previousDoctorId="doc-old",
    previousProviderId="mock", successorDoctorId="doc-new",
    successorProviderId="mock-next",
)
succeed = dict(req, action=auth.SUCCEED, intent=successor)
assert transport.parse_request(transport.canonical(succeed)) == succeed
succeed_commit = dict(succeed,kind="commit",
                      writerInstance=commit["writerInstance"],
                      signedEnvelope=commit["signedEnvelope"])
assert transport.parse_request(
    transport.canonical(succeed_commit)) == succeed_commit

for broken, expected in (
    (dict(req, action="TRASH"),"UNKNOWN_OR_CROSS_SYSTEM_OPERATION"),
    (dict(req, action="RESTORE"),"UNKNOWN_OR_CROSS_SYSTEM_OPERATION"),
    (dict(req, action="FIRST_BED_REGISTER"),"UNKNOWN_OR_CROSS_SYSTEM_OPERATION"),
    (dict(req, schema="postapollo.hospital.protected-writer-request.v1"),
     "WRONG_PROTOCOL_DOMAIN"),
    (dict(req, kind="execute"),"UNSUPPORTED_PHASE"),
    (dict(req, roomId="different-room"),"CONFLICTING_ROOM_IDS"),
    (dict(req, requestNonce="x"),"INVALID_REQUEST_NONCE"),
    (dict(req, requestNonce="z"*43),"NONCANONICAL_BINARY"),
    (dict(req, intent=dict(intent, mode="admin")),"INVALID_INTENT"),
    (dict(req, intent=dict(intent, assignmentId="001")),"INVALID_INTENT"),
    (dict(req, intent=dict(intent, repository="not-a-repository")),"INVALID_INTENT"),
    (dict(req, intent=dict(intent, signedKey="/tmp/key")),"INVALID_INTENT"),
    (dict(req, argv=["room-put","room-1"]),"EXACT_PREPARE_FIELDS_REQUIRED"),
    (dict(req, signedEnvelope=commit["signedEnvelope"]),"EXACT_PREPARE_FIELDS_REQUIRED"),
    (dict(commit, writerInstance="../writer"),"INVALID_WRITER_INSTANCE"),
    (dict(commit, signedEnvelope="broken!"),"INVALID_CANONICAL_BINARY"),
    (dict(commit, signedEnvelope=b64(b"not-json")),"INVALID_ENVELOPE_BYTES"),
    (dict(commit, signedEnvelope=b64(b"{"*9000)),"NONCANONICAL_BINARY"),
):
    refused(lambda broken=broken:transport.parse_request(
        transport.canonical(broken)),expected)
refused(lambda:transport.parse_request(frame+b"\n"),"NONCANONICAL_FRAME")
refused(lambda:transport.parse_request(
    b'{"schema":"bad","schema":"bad"}'),"DUPLICATE_REQUEST_FIELD")
refused(lambda:transport.parse_request(
    b'{"x":NaN}'),"NONFINITE_REQUEST_VALUE")
refused(lambda:transport.parse_request(frame*100),"BOUNDED_REQUEST_REQUIRED")
refused(lambda:transport.parse_request(b"[]"),"NONCANONICAL_FRAME")
refused(lambda:transport.parse_request(frame.replace(
    b'"kind":"prepare"',b'"kind": "prepare"')),"NONCANONICAL_FRAME")

with tempfile.TemporaryDirectory(
        prefix="hospital-ledger-v13-", dir=os.environ["RUNNER_TEMP"]) as td:
    root = Path(td)

    def new_v12(filename):
        db = sqlite3.connect(str(root / filename), isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        assert SOURCE["migrate"](db) == 12
        return db

    with closing(new_v12("hospital.db")) as db:
        db.execute("INSERT INTO patients(patient_id,repository) "
                   "VALUES('patient-1','org/project')")
        db.execute("INSERT INTO rooms(room_id,patient_id,branch,bed_path) "
                   "VALUES('room-1','patient-1','feature/fixture',"
                   "'/tmp/hospital-fixture')")
        db.execute("INSERT INTO messages(room_id,author_role,direction,body_md) "
                   "VALUES('room-1','DOCTOR','incoming','PRESERVED_HISTORY')")
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1

        backup_path = root / "before-v13.db"
        with closing(sqlite3.connect(backup_path)) as backup:
            db.backup(backup)

        # Candidate migration has an atomic schema-version guard. No PX
        # owner code has been changed; this script is not a release install.
        db.executescript(SQL)
        assert db.execute("SELECT value FROM schema_meta "
                          "WHERE key='schema_version'").fetchone()[0] == "13"
        columns = {row["name"] for row in db.execute(
            "PRAGMA table_info(hospital_staffing_authorizations)")}
        assert columns >= {
            "nonce","grant_digest","approval_id","room_id","operation",
            "operator_id","session_id","graph_digest","consumed_at",
        }
        assert db.execute("SELECT body_md FROM messages").fetchone()[0] == (
            "PRESERVED_HISTORY")
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        refused(lambda:SOURCE["migrate"](db),
                "newer than PX supports (12)")

        ledger = (
            b64(secrets.token_bytes(32)), "a"*64, "approval-"+secrets.token_hex(16),
            "room-1", auth.ATTACH, "ci-operator", "session-new", "b"*64,
        )
        sql = ("INSERT INTO hospital_staffing_authorizations "
               "(nonce,grant_digest,approval_id,room_id,operation,"
               "operator_id,session_id,graph_digest) VALUES(?,?,?,?,?,?,?,?)")
        db.execute(sql, ledger)
        assert db.execute(
            "SELECT COUNT(*) FROM hospital_staffing_authorizations"
        ).fetchone()[0] == 1
        for duplicate in (
            ledger,
            (b64(secrets.token_bytes(32)),ledger[1],
             "approval-"+secrets.token_hex(16),*ledger[3:]),
            (b64(secrets.token_bytes(32)),"c"*64,
             ledger[2],*ledger[3:]),
        ):
            refused(lambda duplicate=duplicate: db.execute(sql,duplicate),
                    "UNIQUE constraint failed")
        refused(lambda:db.execute(sql,(
            b64(secrets.token_bytes(32)),"d"*64,
            "approval-"+secrets.token_hex(16),"nonexistent",
            auth.SUCCEED,"ci-operator","new-session","e"*64,
        )), "FOREIGN KEY constraint failed")
        refused(lambda:db.execute(sql,(
            b64(secrets.token_bytes(32)),"d"*64,
            "approval-"+secrets.token_hex(16),"room-1",
            "TRASH","ci-operator","new-session","e"*64,
        )), "CHECK constraint failed")

        # Only a reviewed offline backup restore can downgrade a v13 DB
        # to v12. Do not issue a reverse schema migration against a live DB.
        with closing(sqlite3.connect(backup_path)) as source_backup:
            source_backup.backup(db)
        assert db.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == "12"
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE name='hospital_staffing_authorizations'"
        ).fetchone()[0] == 0
        assert db.execute("SELECT body_md FROM messages").fetchone()[0] == (
            "PRESERVED_HISTORY")
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None

    # Candidate must refuse an older or already-modified store rather
    # than silently creating a mixed schema; failed DDL remains atomic.
    with closing(new_v12("wrong-version.db")) as wrong:
        wrong.execute("UPDATE schema_meta SET value='11' "
                      "WHERE key='schema_version'")
        refused(lambda:wrong.executescript(SQL),"CHECK constraint failed")
        assert wrong.execute("SELECT value FROM schema_meta "
                             "WHERE key='schema_version'").fetchone()[0] == "11"
        assert wrong.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE name='hospital_staffing_authorizations'"
        ).fetchone()[0] == 0
    with closing(new_v12("unexpected-table.db")) as conflict:
        conflict.execute("CREATE TABLE hospital_staffing_authorizations "
                         "(unreviewed_column TEXT)")
        refused(lambda:conflict.executescript(SQL),"already exists")
        assert conflict.execute("SELECT value FROM schema_meta "
                                "WHERE key='schema_version'").fetchone()[0] == "12"
        assert conflict.execute("PRAGMA table_info(hospital_staffing_authorizations)"
                                ).fetchone()["name"] == "unreviewed_column"

print("HOSPITAL TYPED STAFFING V13 CANDIDATE // PASS // bounded separate prepare/commit frames, denied native handler, atomic migration witness, replay/foreign-key checks, old-code refusal and WAL backup restore; NO INSTALL")
