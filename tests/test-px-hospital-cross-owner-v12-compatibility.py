#!/usr/bin/env python3
"""Hospital v12 ↔ independent Session, Doctor and Bed source compatibility.

CI-ONLY. Runs a source-identical staged adapter checked against the
original, pinned owners' functions on ONE disposable v12 SQLite store. This is a data/transaction compatibility test,
NOT a protected-runtime route, caller authorization, native signer, or
permission for the synthetic Bed code to execute in production.

Owner routines are staged solely in a non-exposed source adapter; no user DB is opened.
"""
from __future__ import annotations

import base64
from cryptography.hazmat.primitives import serialization
from contextlib import closing
import inspect
from pathlib import Path
import os
import runpy
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("CI") != "true":
    raise SystemExit("HOSPITAL CROSS_OWNER_V12_HOLD // CI_ONLY")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import px_hospital_room_lifecycle as lifecycle
import px_hospital_protected_store_bridge as bridge
import px_hospital_staffing_admission as staffing

SOURCE = {
    "hospital-witness-session": "4c3f0c97c4b6342bc7adb70443afecf65666d3cb",
    "hospital-witness-succession": "4e0fe43c1324c0011dbbdbcbdfc8bddfb06bcdc1",
    "hospital-witness-bed-signed": "a76a7b079bba6cf5733b5be4860d2188028d63e4",
}

def pinned(name: str) -> Path:
    target = ROOT / name
    assert target.is_dir(), "MISSING_OWNER_SOURCE"
    current = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    assert current == SOURCE[name], "OWNER_REVISION_CHANGED"
    return target

def refuse(action, marker=""):
    try:
        action()
    except (RuntimeError, sqlite3.Error) as exc:
        if marker:
            assert marker.lower() in str(exc).lower(), (marker, str(exc))
        return
    raise AssertionError("UNREVIEWED_OPERATION_ACCEPTED")

def make_bed(path: Path, branch="fixture/bed"):
    path.mkdir()
    def git(*args):
        subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True,
            text=True, check=True, timeout=10,
        )
    git("init", "-q", "-b", branch)
    git("config", "user.email", "hospital-test@example.invalid")
    git("config", "user.name", "Hospital CI")
    (path / "fixture.txt").write_text("disposable\\n", encoding="utf-8")
    git("add", "fixture.txt")
    git("commit", "-qm", "disposable checkout")
    git("remote", "add", "origin", "https://github.com/org/project.git")
    head = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True, text=True, capture_output=True,
    ).stdout.strip()
    assert len(head) in (40, 64)
    return head

# runpy loads the source functions but does not launch their command front
# doors or their ordinary user-owned DB. All DB arguments are explicitly
# supplied as the v12 in-memory/temporary fixture below.
session = runpy.run_path(
    str(pinned("hospital-witness-session") / "bin" / "px-hospital-store"),
    run_name="px_hospital_session_owner_fixture",
)
succession = runpy.run_path(
    str(pinned("hospital-witness-succession") / "bin" / "px-hospital-store"),
    run_name="px_hospital_succession_owner_fixture",
)
bed_directory = pinned("hospital-witness-bed-signed") / "bin"
sys.path.insert(0, str(bed_directory))
import hospital_bed_claim as bed_claim
import hospital_bed_signed_intent as signed_bed

v12 = runpy.run_path(
    str(ROOT / "bin" / "px-hospital-store"),
    run_name="px_hospital_v12_compat_fixture",
)
# The atomic routine bodies are byte-for-byte identical to the pinned
# owners after adding explicit record-reader injection at their signatures.
def source_equal(owned, adapted, name, injection):
    old = inspect.getsource(owned)
    exact = old.replace(
        f"def {name}(conn: sqlite3.Connection, args) -> dict:",
        f"def {name}(conn: sqlite3.Connection, args, *, {injection}) -> dict:",
        1,
    )
    assert exact.strip() == inspect.getsource(adapted).strip(), (
        "OWNER_ATOMIC_ROUTINE_DRIFT", name,
    )

source_equal(session["session_attach_atomic"],
             staffing.session_attach_atomic, "session_attach_atomic",
             "session_record")
source_equal(succession["session_succeed_atomic"],
             staffing.session_succeed_atomic, "session_succeed_atomic",
             "room_record, session_record")

def stage_attach(db, args):
    return staffing.session_attach_atomic(
        db, args, session_record=v12["session_record"]
    )

def stage_succeed(db, args):
    return staffing.session_succeed_atomic(
        db, args, room_record=v12["room_record"],
        session_record=v12["session_record"]
    )

refuse(lambda: staffing.dispatch_native_staffing(
    "session-attach-atomic", object(), object()
), "NATIVE_SESSION_DOCTOR_AUTHORITY_NOT_INSTALLED")
refuse(lambda: staffing.dispatch_native_staffing(
    "session-succeed-atomic", object(), object(), authorized=True
), "NATIVE_SESSION_DOCTOR_AUTHORITY_NOT_INSTALLED")

assert bridge.route_coverage()
assert "session-attach-atomic" not in bridge.WRITE_COMMANDS
assert "session-succeed-atomic" not in bridge.WRITE_COMMANDS
assert "room-bed-claim-atomic" not in bridge.WRITE_COMMANDS
assert "room-bed-claim-signed-atomic" not in bridge.WRITE_COMMANDS

with tempfile.TemporaryDirectory(prefix="px-hospital-v12-owners-") as tmp:
    root = Path(tmp)
    dbpath = root / "hospital.db"
    with closing(sqlite3.connect(dbpath, isolation_level=None, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        assert v12["migrate"](db) == 12
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='trigger' AND name LIKE 'room_lifecycle_hold_%'"
        ).fetchone()[0] >= 27
        db.execute(
            "INSERT INTO patients(patient_id,repository) VALUES('p','org/project')"
        )
        for name in ("doc-old", "doc-new"):
            db.execute(
                "INSERT INTO doctors(doctor_id,status) VALUES(?,'ACTIVE')", (name,)
            )

        work_bed = root / "session-bed"
        work_bed.mkdir()
        db.execute(
            "INSERT INTO rooms(room_id,patient_id,branch,bed_path,doctor_id,provider_id) "
            "VALUES('room-session','p','fixture/session',?,'doc-old','mock-old')",
            (str(work_bed),),
        )
        assignment_id = db.execute(
            "INSERT INTO assignments(room_id,patient_id,goal_md,status) "
            "VALUES('room-session','p','work','ACTIVE')"
        ).lastrowid
        db.execute(
            "UPDATE rooms SET current_assignment_id=? WHERE room_id='room-session'",
            (str(assignment_id),),
        )

        attach = SimpleNamespace(
            confirm=True, room_id="room-session", session_id="s-old",
            assignment_id=str(assignment_id), doctor_id="doc-old",
            provider_id="mock-old", repository="org/project",
            branch="fixture/session", bed_path=str(work_bed), mode="create",
        )
        refuse(lambda: stage_attach(
            db, SimpleNamespace(**dict(vars(attach), confirm=False))
        ), "confirmation")
        result = stage_attach(db, attach)
        assert result["created"] is True and result["session"]["status"] == "IDLE"
        assert result["authorityVerified"] is False
        assert stage_attach(db, attach)["created"] is False
        refuse(lambda: stage_attach(
            db, SimpleNamespace(**dict(vars(attach), session_id="s-2"))
        ), "open Session")

        db.execute(
            "INSERT INTO messages(room_id,session_id,author_role,direction,body_md) "
            "VALUES('room-session','s-old','DOCTOR','outgoing','IMMUTABLE_HISTORY')"
        )
        db.execute(
            "INSERT INTO room_checkpoints(room_id,session_id,body_md) "
            "VALUES('room-session','s-old','handoff checkpoint')"
        )
        db.execute(
            "INSERT INTO room_reports(room_id,session_id,report_kind,body_md) "
            "VALUES('room-session','s-old','HANDOFF','handoff report')"
        )
        assert lifecycle.review(db, "room-session")["canTrash"] is False
        db.execute(
            "UPDATE sessions SET status='FAILED',ended_at='2026-11-19' "
            "WHERE session_id='s-old'"
        )
        succeed = SimpleNamespace(
            confirm=True, room_id="room-session",
            previous_session_id="s-old", new_session_id="s-new",
            previous_doctor_id="doc-old", previous_provider_id="mock-old",
            successor_doctor_id="doc-new", successor_provider_id="mock-new",
            assignment_id=str(assignment_id), repository="org/project",
            branch="fixture/session", bed_path=str(work_bed),
        )
        refuse(lambda: stage_succeed(
            db, SimpleNamespace(**dict(vars(succeed), confirm=False))
        ), "confirmation")
        db.execute("""
            CREATE TRIGGER fixture_fail_succession
            BEFORE INSERT ON sessions WHEN NEW.session_id='s-new'
            BEGIN SELECT RAISE(ABORT,'fixture rollback'); END;
        """)
        refuse(lambda: stage_succeed(db, succeed),
               "fixture rollback")
        assert db.execute(
            "SELECT doctor_id FROM rooms WHERE room_id='room-session'"
        ).fetchone()[0] == "doc-old"
        assert db.execute(
            "SELECT COUNT(*) FROM sessions WHERE session_id='s-new'"
        ).fetchone()[0] == 0
        db.execute("DROP TRIGGER fixture_fail_succession")
        moved = stage_succeed(db, succeed)
        assert moved["created"] is True
        assert moved["providerLaunched"] is False
        assert moved["authorityVerified"] is False
        assert stage_succeed(db, succeed)["created"] is False
        assert db.execute(
            "SELECT body_md FROM messages WHERE room_id='room-session'"
        ).fetchone()[0] == "IMMUTABLE_HISTORY"
        assert db.execute(
            "SELECT COUNT(*) FROM room_reports WHERE room_id='room-session'"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM room_checkpoints WHERE room_id='room-session'"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM session_events "
            "WHERE session_id='s-new' AND event_type='room.succession.admitted'"
        ).fetchone()[0] == 1
        assert lifecycle.review(db, "room-session")["canTrash"] is False

        # Bed owner code stays test-only even when called on a v12 DB.
        for room in ("bed-one", "bed-two", "bed-frozen"):
            db.execute(
                "INSERT INTO rooms(room_id,patient_id) VALUES(?,'p')", (room,)
            )
        first = root / "bed-first"
        second = root / "bed-second"
        third = root / "bed-third"
        make_bed(first)
        second_head = make_bed(second)
        third_head = make_bed(third)
        args1 = SimpleNamespace(
            confirm=True, room_id="bed-one", repository="org/project",
            branch="fixture/bed", bed_path=str(first),
        )
        refuse(lambda: bed_claim.claim_first_bed(
            db, args1, v12["room_record"]
        ), "synthetic DB only")
        assert v12["room_record"](db, "bed-one")["bedPath"] == ""

        # The fixture-only environment is used solely in this subprocess.
        os.environ["PX_HOSPITAL_DB"] = str(dbpath)
        os.environ["PX_HOSPITAL_BED_CLAIM_TEST_ONLY"] = "1"
        initial = bed_claim.claim_first_bed(db, args1, v12["room_record"])
        assert initial["recorded"] is True
        assert initial["testOnly"] is True
        assert initial["operatorAuthenticated"] is False

        private = signed_bed.Ed25519PrivateKey.generate()
        public_raw = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        trusted = root / "fixture-key.pub"
        trusted.write_bytes(public_raw)
        os.environ[signed_bed.KEY_ENV] = str(trusted)
        row = v12["room_record"](db, "bed-two")
        now = int(time.time())
        body = {
            "schema": signed_bed.SCHEMA,
            "operation": signed_bed.OPERATION,
            "roomId": "bed-two",
            "patientId": "p",
            "repository": "org/project",
            "branch": "fixture/bed",
            "bedPath": str(second),
            "head": second_head,
            "roomUpdatedAt": row["updatedAt"],
            "operatorId": "ci-operator",
            "nonce": base64.urlsafe_b64encode(
                secrets.token_bytes(32)
            ).rstrip(b"=").decode("ascii"),
            "issuedAt": now,
            "expiresAt": now + 45,
        }
        signed_file = root / "signed-intent.json"
        signed_file.write_bytes(signed_bed.seal_fixture(private, body))
        args2 = SimpleNamespace(
            confirm=True, room_id="bed-two", repository="org/project",
            branch="fixture/bed", bed_path=str(second),
            signed_intent_file=str(signed_file),
        )
        forged_frame = signed_bed._parse(signed_file.read_bytes())
        forged_frame["body"]["operatorId"] = "forged-operator"
        forged_file = root / "forged-intent.json"
        forged_file.write_bytes(signed_bed._canon(forged_frame))
        refuse(lambda: bed_claim.claim_first_bed_signed(
            db, SimpleNamespace(**dict(vars(args2),
                signed_intent_file=str(forged_file))),
            v12["room_record"]
        ), "wrong signer")
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='hospital_bed_intent_consumptions'"
        ).fetchone()[0] == 0, "FORGERY_CREATED_APPROVAL_LEDGER"
        accepted = bed_claim.claim_first_bed_signed(
            db, args2, v12["room_record"]
        )
        assert accepted["recorded"] and accepted["signedIntentVerified"]
        assert accepted["testOnly"] and not accepted["operatorAuthenticated"]
        assert db.execute(
            "SELECT COUNT(*) FROM hospital_bed_intent_consumptions"
        ).fetchone()[0] == 1

        # Existing v12 Room state freeze blocks Bed writes even from the
        # original experimental Bed function with a test fixture flag.
        frozen = lifecycle.review(db, "bed-frozen")
        assert frozen["state"] == "ACTIVE" and frozen["canTrash"] is True
        db.execute(
            "INSERT INTO room_lifecycle(room_id,state,revision,frozen_digest) "
            "VALUES('bed-frozen','TRASHED',1,?)",
            (frozen["digest"],),
        )
        args3 = SimpleNamespace(
            confirm=True, room_id="bed-frozen", repository="org/project",
            branch="fixture/bed", bed_path=str(third),
        )
        refuse(lambda: bed_claim.claim_first_bed(
            db, args3, v12["room_record"]
        ))
        # The signed path must also roll back nonce consumption when
        # v12 rejects the frozen Room mutation after signature verification.
        frozen_row = v12["room_record"](db, "bed-frozen")
        frozen_body = dict(
            body, roomId="bed-frozen", bedPath=str(third),
            head=third_head, roomUpdatedAt=frozen_row["updatedAt"],
            nonce=base64.urlsafe_b64encode(
                secrets.token_bytes(32)
            ).rstrip(b"=").decode("ascii"),
        )
        frozen_intent = root / "frozen-intent.json"
        frozen_intent.write_bytes(
            signed_bed.seal_fixture(private, frozen_body)
        )
        refuse(lambda: bed_claim.claim_first_bed_signed(
            db, SimpleNamespace(**dict(vars(args3),
                signed_intent_file=str(frozen_intent))),
            v12["room_record"],
        ))
        assert db.execute(
            "SELECT COUNT(*) FROM hospital_bed_intent_consumptions"
        ).fetchone()[0] == 1, "FAILED_BED_WRITE_CONSUMED_SIGNED_INTENT"
        assert v12["room_record"](db, "bed-frozen")["bedPath"] == ""
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchone() is None

print(
    "HOSPITAL CROSS-OWNER V12 // PASS // atomic Session attach and Doctor "
    "succession, rollback/history, unsigned and signed synthetic Bed, "
    "v12 frozen Room refusal; ALL commands remain protected-route HOLD; NO INSTALL"
)
