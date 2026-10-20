#!/usr/bin/env python3
"""INT1-B2 detached authority mutation proof under disposable Ubuntu CI only."""
import hashlib
import json
from pathlib import Path
import unittest
from px_int1_fixture import DisposablePX

REPO=Path(__file__).resolve().parents[1]
ROOM="B2-ROOM"
SESSION="b2-session"
DOCTOR="B2-DOCTOR"
CTX=hashlib.sha256(b"NOT A REAL CONTINUITY DIGEST").hexdigest()

class B2EpochMutationTests(unittest.TestCase):
    def setUp(self):
        self.fx=DisposablePX(REPO)
        self.addCleanup(self.fx.close)
        registry=self.fx.root/"providers/fake.json"
        registry.write_text(json.dumps({"version":1,"providers":{
            "int1-fake":{"name":"INT1 FAKE","executionProfile":"EXEC_S3_FAKE_ONLY",
                         "dialect":"exec-s3-fake-only"}
        }}))
        registry.chmod(0o600)
        self.assertTrue(self.fx.assert_safe_environment())
        self.ok(self.fx.hospital("init"))
        self.ok(self.fx.hospital(
            "room-bind",ROOM,"--repository","kudokudo1/taskbars-post-apollo",
            "--patient-id","B2-PATIENT","--team","B2-TEAM","--branch","b2",
            "--bed-path","/fixture/bed","--doctor-id",DOCTOR,
        ))
        self.ok(self.fx.hospital(
            "session-put",SESSION,"--room-id",ROOM,
            "--doctor-id",DOCTOR,"--provider-id","int1-fake","--status","IDLE",
        ))
        self.ok(self.fx.hospital(
            "session-runtime",SESSION,"--working-directory","/fixture/bed",
            "--status","IDLE",
        ))
        a=self.ok(self.fx.hospital(
            "assignment-create","--room-id",ROOM,"--title","B2-ONLY",
            "--goal","Synthetic authority check",
            "--permissions-json",'["READ","EDIT"]',
        ))
        self.assignment_id=a["id"]
        self.ok(self.fx.hospital("assignment-activate",self.assignment_id))
        self.ok(self.b1("bootstrap","--room-id",ROOM,"--session-id",SESSION))
        self.old_generation=1

    def ok(self,proc):
        self.assertEqual(proc.returncode,0,proc.stderr)
        return json.loads(proc.stdout)

    def b1(self,*argv,input=None):
        return self.fx.run("/usr/bin/python3","-B",
                           "/source/bin/px_int1_fake_atomic.py",
                           *argv,input=input,timeout=30)

    def b2(self,*argv):
        return self.fx.run("/usr/bin/python3","-B",
                           "/source/bin/px_int1_fake_epoch.py",*argv,timeout=30)

    def install(self):
        result=self.ok(self.b2("install","--room-id",ROOM,"--session-id",SESSION))
        self.assertEqual(result["hookCount"],12)
        self.assertEqual(result["generation"],2)
        self.assertFalse(result["revoked"])
        return result

    def current(self):
        return self.ok(self.b2("inspect","--room-id",ROOM))

    def accept(self,turn,generation):
        return self.b1("accept","--room-id",ROOM,"--session-id",SESSION,
                       "--turn-id",turn,"--generation",str(generation),
                       "--context-hash",CTX,"--body-stdin",input="fake-only")

    def state(self):
        return (self.ok(self.fx.hospital("messages",ROOM,"--limit","100")),
                self.ok(self.fx.hospital("events",SESSION,"--limit","100")))

    def assert_revoked_and_refuses(self,generation,old):
        info=self.current()
        self.assertTrue(info["revoked"])
        self.assertGreater(info["generation"],generation)
        attempt=self.accept("post-authority-change",generation)
        self.assertNotEqual(attempt.returncode,0)
        self.assertIn("stale or revoked authority",attempt.stderr)
        self.assertEqual(self.state(),old,"mutation must not accept any fake turn")

    def test_install_invalidates_prior_snapshot_and_allows_fresh_storage_proof(self):
        self.install()
        self.assertEqual(self.current()["generation"],2)
        before=self.state()
        refused=self.accept("stale-pre-install",self.old_generation)
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("stale or revoked authority",refused.stderr)
        self.assertEqual(self.state(),before)
        accepted=self.ok(self.accept("still-undispatched",2))
        self.assertEqual(accepted["state"],"ACCEPTED_UNDISPATCHED")
        self.assertFalse(accepted["replayed"])
        self.assertEqual(self.current()["generation"],2)
        self.assertFalse(self.current()["revoked"],
                         "bookkeeping room updated_at must not revoke")

    def test_ordinary_room_rebind_change_restore_cannot_resurrect_grant(self):
        self.install()
        before=self.state()
        for doctor in ("B2-OTHER",DOCTOR):
            self.ok(self.fx.hospital(
                "room-put",ROOM,"--patient-id","B2-PATIENT",
                "--team","B2-TEAM","--branch","b2",
                "--bed-path","/fixture/bed","--doctor-id",doctor,
                "--provider-id","int1-fake",
            ))
        self.assertEqual(
            self.ok(self.fx.hospital("room",ROOM))["doctorId"],DOCTOR
        )
        self.assert_revoked_and_refuses(2,before)

    def test_ordinary_session_identity_change_restore_revokes(self):
        self.install()
        before=self.state()
        for doctor in ("B2-FOREIGN",DOCTOR):
            self.ok(self.fx.hospital(
                "session-put",SESSION,"--room-id",ROOM,"--doctor-id",doctor,
                "--provider-id","int1-fake","--status","IDLE",
            ))
        self.assert_revoked_and_refuses(2,before)

    def test_ordinary_assignment_pause_reactivate_revokes(self):
        self.install()
        before=self.state()
        self.ok(self.fx.hospital("assignment-status",self.assignment_id,"PAUSED"))
        self.ok(self.fx.hospital("assignment-activate",self.assignment_id))
        self.assert_revoked_and_refuses(2,before)

    def test_assignment_permission_downgrade_upgrade_is_not_grant_recovery(self):
        self.install()
        before=self.state()
        for permission in ('["READ"]','["READ","EDIT"]'):
            self.ok(self.fx.hospital(
                "assignment-update",self.assignment_id,
                "--permissions-json",permission,
            ))
        self.assert_revoked_and_refuses(2,before)

    def test_registered_doctor_status_change_revokes(self):
        self.install()
        before=self.state()
        self.ok(self.fx.hospital(
            "doctor-put",DOCTOR,"--name",DOCTOR,"--status","INACTIVE"
        ))
        self.assert_revoked_and_refuses(2,before)

    def test_unrelated_room_mutation_does_not_revoke_other_room(self):
        self.install()
        self.ok(self.fx.hospital(
            "room-bind","B2-OTHER-ROOM",
            "--repository","kudokudo1/taskbars-post-apollo",
            "--patient-id","OTHER-PATIENT","--team","OTHER",
            "--branch","other","--bed-path","/fixture/bed",
            "--doctor-id","OTHER-DOCTOR",
        ))
        self.ok(self.fx.hospital(
            "room-put","B2-OTHER-ROOM","--patient-id","OTHER-PATIENT",
            "--team","CHANGED","--branch","other",
            "--bed-path","/fixture/bed","--doctor-id","OTHER-DOCTOR"
        ))
        self.assertEqual(self.current()["generation"],2)
        self.assertFalse(self.current()["revoked"])
        self.ok(self.accept("untouched-room",2))

    def test_rolled_back_legacy_mutation_does_not_revoke_epoch(self):
        self.install()
        script=("import sqlite3,json; "
                "d=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
                "uri=True);d.execute('BEGIN IMMEDIATE');"
                "d.execute(\"UPDATE rooms SET doctor_id='TEMP' "
                "WHERE room_id='B2-ROOM'\");d.rollback();print(json.dumps(True))")
        self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))
        self.assertEqual(self.current()["generation"],2)
        self.assertFalse(self.current()["revoked"])
        self.assertEqual(self.ok(self.fx.hospital("room",ROOM))["doctorId"],DOCTOR)
        self.ok(self.accept("not-mutated",2))

    def test_changed_trigger_definition_is_detected_by_inspector(self):
        self.install()
        script=("import sqlite3,json; "
                "d=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
                "uri=True);d.execute('DROP TRIGGER int1_b2_rooms_update_v1');"
                "d.commit();print(json.dumps(True))")
        self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))
        bad=self.b2("inspect","--room-id",ROOM)
        self.assertNotEqual(bad.returncode,0)
        self.assertIn("incomplete or unexpected hook set",bad.stderr)
        # A detached B1 accept does NOT require hook presence; this is an
        # explicit security limitation requiring resolution before dispatch.

    def test_install_refuses_rearm_of_previously_revoked_authority(self):
        self.ok(self.b1("revoke","--room-id",ROOM,"--reason","fake-stop"))
        bad=self.b2("install","--room-id",ROOM,"--session-id",SESSION)
        self.assertNotEqual(bad.returncode,0)
        self.assertIn("revoked room cannot rearm",bad.stderr)

if __name__=="__main__":
    unittest.main(verbosity=2)
