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

    def bootstrap_secondary(self, room_id):
        """Give another Room its own B1 grant BEFORE the global B2 install."""
        session_id = room_id.lower() + "-session"
        doctor_id = room_id + "-DOCTOR"
        self.ok(self.fx.hospital(
            "room-bind", room_id,
            "--repository", "kudokudo1/taskbars-post-apollo",
            "--patient-id", room_id + "-PATIENT",
            "--team", room_id + "-TEAM", "--branch", "b2",
            "--bed-path", "/fixture/bed", "--doctor-id", doctor_id,
        ))
        self.ok(self.fx.hospital(
            "session-put", session_id, "--room-id", room_id,
            "--doctor-id", doctor_id, "--provider-id", "int1-fake",
            "--status", "IDLE",
        ))
        self.ok(self.fx.hospital(
            "session-runtime", session_id, "--working-directory",
            "/fixture/bed", "--status", "IDLE",
        ))
        assignment = self.ok(self.fx.hospital(
            "assignment-create", "--room-id", room_id,
            "--title", "B2 MULTI-ROOM", "--goal", "Synthetic only",
            "--permissions-json", '["READ","EDIT"]',
        ))
        self.ok(self.fx.hospital("assignment-activate", assignment["id"]))
        bootstrap = self.ok(self.b1(
            "bootstrap", "--room-id", room_id, "--session-id", session_id,
        ))
        self.assertEqual(bootstrap["generation"], 1)
        return session_id

    def accept_for(self, room_id, session_id, turn_id, generation):
        return self.b1(
            "accept", "--room-id", room_id, "--session-id", session_id,
            "--turn-id", turn_id, "--generation", str(generation),
            "--context-hash", CTX, "--body-stdin", input="fake-only",
        )

    def test_b2_r1_global_install_invalidates_all_prior_rooms_but_not_revoked(self):
        room_b = "B2-BOOTSTRAPPED-B"
        room_c = "B2-REVOKED-C"
        session_b = self.bootstrap_secondary(room_b)
        session_c = self.bootstrap_secondary(room_c)

        snapshot_a = self.ok(self.b1(
            "snapshot", "--room-id", ROOM, "--session-id", SESSION,
        ))
        snapshot_b = self.ok(self.b1(
            "snapshot", "--room-id", room_b, "--session-id", session_b,
        ))
        self.assertEqual(snapshot_a["generation"], 1)
        self.assertEqual(snapshot_b["generation"], 1)
        revoked_c = self.ok(self.b1(
            "revoke", "--room-id", room_c, "--reason", "pre-install hold",
        ))
        self.assertTrue(revoked_c["revoked"])
        self.assertEqual(revoked_c["generation"], 2)
        self.assertEqual(
            self.ok(self.b1(
                "snapshot", "--room-id", room_b, "--session-id", session_b,
            ))["generation"], 1,
        )

        # One global trigger install through A must invalidate the old B grant.
        self.install()
        self.assertEqual(self.current()["generation"], 2)
        current_b = self.ok(self.b2("inspect", "--room-id", room_b))
        current_c = self.ok(self.b2("inspect", "--room-id", room_c))
        self.assertEqual(current_b["generation"], 2)
        self.assertFalse(current_b["revoked"])
        self.assertEqual(current_c["generation"], revoked_c["generation"])
        self.assertTrue(current_c["revoked"])

        for room_id, session_id, turn_id in (
            (ROOM, SESSION, "r1-old-a"),
            (room_b, session_b, "r1-old-b"),
        ):
            prior_messages = self.ok(
                self.fx.hospital("messages", room_id, "--limit", "100")
            )
            prior_events = self.ok(
                self.fx.hospital("events", session_id, "--limit", "100")
            )
            attempt = self.accept_for(room_id, session_id, turn_id, 1)
            self.assertNotEqual(attempt.returncode, 0)
            self.assertIn("stale or revoked authority", attempt.stderr)
            self.assertEqual(
                self.ok(self.fx.hospital("messages", room_id, "--limit", "100")),
                prior_messages,
            )
            self.assertEqual(
                self.ok(self.fx.hospital("events", session_id, "--limit", "100")),
                prior_events,
            )

        # Both valid Rooms can take a NEW snapshot; revoked C cannot.
        self.assertEqual(self.ok(self.b1(
            "snapshot", "--room-id", ROOM, "--session-id", SESSION,
        ))["generation"], 2)
        self.assertEqual(self.ok(self.b1(
            "snapshot", "--room-id", room_b, "--session-id", session_b,
        ))["generation"], 2)
        self.assertEqual(
            self.ok(self.accept_for(ROOM, SESSION, "r1-fresh-a", 2))["state"],
            "ACCEPTED_UNDISPATCHED",
        )
        self.assertEqual(
            self.ok(self.accept_for(room_b, session_b, "r1-fresh-b", 2))["state"],
            "ACCEPTED_UNDISPATCHED",
        )
        refused_c = self.b1(
            "snapshot", "--room-id", room_c, "--session-id", session_c,
        )
        self.assertNotEqual(refused_c.returncode, 0)
        self.assertIn("authority revoked", refused_c.stderr)
        self.assertTrue(self.ok(self.b2("inspect", "--room-id", room_c))["revoked"])

    def test_b2_r1_subsequent_room_mutations_preserve_other_room_epoch(self):
        room_b = "B2-BOOTSTRAPPED-B"
        session_b = self.bootstrap_secondary(room_b)
        self.install()
        self.assertEqual(self.ok(
            self.b2("inspect", "--room-id", room_b)
        )["generation"], 2)
        # Trigger is installed globally, but the subsequent mutation is A-only.
        for doctor in ("B2-DIFFERENT-DOCTOR", DOCTOR):
            self.ok(self.fx.hospital(
                "room-put", ROOM, "--patient-id", "B2-PATIENT",
                "--team", "B2-TEAM", "--branch", "b2",
                "--bed-path", "/fixture/bed", "--doctor-id", doctor,
                "--provider-id", "int1-fake",
            ))
        self.assertTrue(self.current()["revoked"])
        remaining_b = self.ok(self.b2("inspect", "--room-id", room_b))
        self.assertEqual(remaining_b["generation"], 2)
        self.assertFalse(remaining_b["revoked"])
        self.assertEqual(self.ok(
            self.accept_for(room_b, session_b, "b-remains-valid", 2)
        )["state"], "ACCEPTED_UNDISPATCHED")

    def test_b2_r1_failed_install_rolls_back_global_epoch_and_all_triggers(self):
        room_b = "B2-BOOTSTRAPPED-B"
        session_b = self.bootstrap_secondary(room_b)
        # Instrument ONLY the isolated test process. The first authority_row
        # lookup occurs before DDL, the second occurs after all global bumps.
        # Raising at that second lookup tests rollback after BOTH side effects.
        script = """
import json, sys
sys.path.insert(0, '/source/bin')
import px_int1_fake_epoch as b2
original = b2.authority_row
calls = [0]
def inject(conn, room_id):
    calls[0] += 1
    if calls[0] == 2:
        raise RuntimeError('B2-R1 TEST INJECT // after global generation')
    return original(conn, room_id)
b2.authority_row = inject
conn = b2.connect()
try:
    b2.install(conn, 'B2-ROOM', 'b2-session')
except RuntimeError as exc:
    print(json.dumps({'error': str(exc), 'lookups': calls[0]}))
else:
    raise AssertionError('expected injected installation failure')
finally:
    conn.close()
"""
        injected = self.ok(
            self.fx.run("/usr/bin/python3", "-B", "-c", script)
        )
        self.assertIn("TEST INJECT", injected["error"])
        self.assertEqual(injected["lookups"], 2)

        # Independent fresh process confirms DDL AND both epoch increments
        # disappeared, not merely that the installer returned an error.
        for room_id, session_id in ((ROOM, SESSION), (room_b, session_b)):
            snap = self.ok(self.b1(
                "snapshot", "--room-id", room_id, "--session-id", session_id,
            ))
            self.assertEqual(snap["generation"], 1)
        probe = (
            "import json,sqlite3; "
            "c=sqlite3.connect("
            "'file:/fixture/hospital/data/hospital.db?mode=ro',uri=True);"
            "print(json.dumps(c.execute("
            "'SELECT COUNT(*) FROM sqlite_master "
            "WHERE type=\\'trigger\\' AND name LIKE \\'int1_b2_%\\''"
            ").fetchone()[0]))"
        )
        self.assertEqual(
            self.ok(self.fx.run("/usr/bin/python3", "-B", "-c", probe)), 0,
            "failed installation must not leave any global hooks",
        )
        # Correct installation succeeds after the rolled-back attempt.
        self.install()
        self.assertEqual(self.ok(
            self.b2("inspect", "--room-id", room_b)
        )["generation"], 2)

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
