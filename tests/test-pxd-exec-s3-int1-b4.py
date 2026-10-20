#!/usr/bin/env python3
"""INT1-B4 detached continuity mutation hooks, never executable Doctor turns."""
import hashlib
import json
from pathlib import Path
import unittest
from px_int1_fixture import DisposablePX

REPO=Path(__file__).resolve().parents[1]
PATIENT="B4-SHARED-PATIENT"
ROOMS=("B4-ROOM-A","B4-ROOM-B")
CTX=hashlib.sha256(b"untrusted synthetic sample; NOT verified continuity").hexdigest()

class B4ContinuityMutationTests(unittest.TestCase):
    def setUp(self):
        self.fx=DisposablePX(REPO)
        self.addCleanup(self.fx.close)
        reg=self.fx.root/"providers/fake.json"
        reg.write_text(json.dumps({"version":1,"providers":{
            "int1-fake":{"name":"INT1 FAKE","executionProfile":"EXEC_S3_FAKE_ONLY",
                        "dialect":"exec-s3-fake-only"}
        }}))
        reg.chmod(0o600)
        self.assertTrue(self.fx.assert_safe_environment())
        self.ok(self.fx.hospital("init"))
        self.sessions={}
        for room in ROOMS:
            self.register(room,PATIENT)
        self.ok(self.b1("bootstrap","--room-id",ROOMS[0],
                        "--session-id",self.sessions[ROOMS[0]]))
        self.ok(self.b1("bootstrap","--room-id",ROOMS[1],
                        "--session-id",self.sessions[ROOMS[1]]))
        installed=self.ok(self.b2("install","--room-id",ROOMS[0],
                                  "--session-id",self.sessions[ROOMS[0]]))
        self.assertEqual(installed["hookCount"],12)
        self.assertEqual(installed["generation"],2)
        for room in ROOMS:
            self.assertEqual(self.snap(room)["generation"],2)

    def register(self,room,patient):
        doctor=room+"-DOCTOR"
        session=room.lower()+"-session"
        self.ok(self.fx.hospital("room-bind",room,"--repository",
            "kudokudo1/taskbars-post-apollo","--patient-id",patient,
            "--team",room+"-TEAM","--branch","b4",
            "--bed-path","/fixture/bed","--doctor-id",doctor))
        self.ok(self.fx.hospital("session-put",session,"--room-id",room,
            "--doctor-id",doctor,"--provider-id","int1-fake","--status","IDLE"))
        self.ok(self.fx.hospital("session-runtime",session,
            "--working-directory","/fixture/bed","--status","IDLE"))
        a=self.ok(self.fx.hospital("assignment-create","--room-id",room,
            "--goal","Fake-only continuity","--title","B4","--permissions-json",
            '["READ","EDIT"]'))
        self.ok(self.fx.hospital("assignment-activate",a["id"]))
        self.sessions[room]=session

    def ok(self,proc):
        self.assertEqual(proc.returncode,0,proc.stderr)
        return json.loads(proc.stdout)

    def script(self,filename,*argv,input=None):
        return self.fx.run("/usr/bin/python3","-B",filename,*argv,input=input,
                           timeout=30)

    def b1(self,*args,input=None):
        return self.script("/source/bin/px_int1_fake_atomic.py",*args,input=input)

    def b2(self,*args):
        return self.script("/source/bin/px_int1_fake_epoch.py",*args)

    def b4(self,*args):
        return self.script("/source/bin/px_int1_fake_continuity.py",*args)

    def install(self):
        r=self.ok(self.b4("install","--room-id",ROOMS[0],
                          "--session-id",self.sessions[ROOMS[0]]))
        self.assertEqual(r["hookCount"],6)
        self.assertEqual(r["generation"],3)
        return r

    def inspect(self,room):
        return self.ok(self.b4("inspect","--room-id",room))

    def snap(self,room):
        return self.ok(self.b1("snapshot","--room-id",room,
                               "--session-id",self.sessions[room]))

    def accept(self,room,turn,generation):
        return self.b1("accept","--room-id",room,
                       "--session-id",self.sessions[room],"--turn-id",turn,
                       "--generation",str(generation),"--context-hash",CTX,
                       "--body-stdin",input="fake-only")

    def report(self,room,kind):
        return self.ok(self.fx.hospital("room-report-append","--room-id",room,
            "--session-id",self.sessions[room],"--report-kind",kind,
            "--title","B4 simulated report","--body","synthetic"))

    def chart(self,scope,target,role="operator",body="synthetic decision"):
        args=["chart-entry-add","--scope",scope,
              "--author-role",role,"--entry-kind","DECISION",
              "--title","B4 fake","--body",body]
        if scope=="PATIENT":
            args+=["--patient-id",target]
        else:
            args+=["--room-id",target]
        return self.ok(self.fx.hospital(*args))

    def state(self,room):
        return (self.ok(self.fx.hospital("messages",room,"--limit","100")),
                self.ok(self.fx.hospital("events",self.sessions[room],"--limit","100")))

    def assert_stale(self,room,old_generation,turn):
        before=self.state(room)
        response=self.accept(room,turn,old_generation)
        self.assertNotEqual(response.returncode,0)
        self.assertIn("stale or revoked authority",response.stderr)
        self.assertEqual(self.state(room),before)

    def test_b4_global_install_invalidates_all_earlier_epochs_and_keeps_revoked(self):
        room_c="B4-REVOKED"
        self.register(room_c,"B4-OTHER-PATIENT")
        self.ok(self.b1("bootstrap","--room-id",room_c,
                        "--session-id",self.sessions[room_c]))
        # Globally installing B2 has already happened; C bootstrap starts at 1.
        prior=self.ok(self.b1("revoke","--room-id",room_c,
                              "--reason","permanent synthetic hold"))
        self.assertTrue(prior["revoked"])
        self.install()
        for room in ROOMS:
            self.assertEqual(self.inspect(room)["generation"],3)
            self.assertFalse(self.inspect(room)["revoked"])
            self.assert_stale(room,2,"before-b4-"+room)
            self.assertEqual(self.snap(room)["generation"],3)
        c=self.inspect(room_c)
        self.assertTrue(c["revoked"])
        self.assertEqual(c["generation"],prior["generation"])
        self.assertEqual(self.ok(self.accept(ROOMS[1],"fresh-b4",3))["state"],
                         "ACCEPTED_UNDISPATCHED")

    def test_handoff_report_revokes_target_room_only(self):
        self.install()
        self.report(ROOMS[0],"HANDOFF")
        self.assertTrue(self.inspect(ROOMS[0])["revoked"])
        self.assertFalse(self.inspect(ROOMS[1])["revoked"])
        self.assert_stale(ROOMS[0],3,"stale-handoff")
        self.assertEqual(self.ok(self.accept(ROOMS[1],"unaffected-b",3))["state"],
                         "ACCEPTED_UNDISPATCHED")

    def test_non_handoff_report_does_not_revoke(self):
        self.install()
        self.report(ROOMS[0],"DOCTOR_NOTE")
        self.assertEqual(self.inspect(ROOMS[0])["generation"],3)
        self.assertFalse(self.inspect(ROOMS[0])["revoked"])

    def test_operator_room_chart_revokes_only_its_room(self):
        self.install()
        self.chart("ROOM",ROOMS[0])
        self.assertTrue(self.inspect(ROOMS[0])["revoked"])
        self.assertFalse(self.inspect(ROOMS[1])["revoked"])
        self.assert_stale(ROOMS[0],3,"stale-room-decision")

    def test_non_operator_room_chart_not_an_approved_decision(self):
        self.install()
        self.chart("ROOM",ROOMS[0],role="doctor")
        self.assertFalse(self.inspect(ROOMS[0])["revoked"])
        self.assertEqual(self.inspect(ROOMS[0])["generation"],3)

    def test_patient_operator_decision_revokes_every_room_of_same_patient(self):
        other="B4-OTHER-PATIENT-ROOM"
        self.register(other,"B4-ANOTHER-PATIENT")
        self.ok(self.b1("bootstrap","--room-id",other,
                        "--session-id",self.sessions[other]))
        self.install()
        other_before=self.snap(other)["generation"]
        self.chart("PATIENT",PATIENT)
        for room in ROOMS:
            self.assertTrue(self.inspect(room)["revoked"])
            self.assert_stale(room,3,"patient-invalid-"+room)
        self.assertFalse(self.inspect(other)["revoked"])
        self.assertEqual(self.inspect(other)["generation"],other_before)

    def test_resolving_existing_approved_chart_invalidates_grant(self):
        record=self.chart("ROOM",ROOMS[0])
        self.install()
        self.ok(self.fx.hospital("chart-entry-status",record["id"],"RESOLVED"))
        self.assertTrue(self.inspect(ROOMS[0])["revoked"])
        self.assert_stale(ROOMS[0],3,"stale-resolved")

    def test_rolled_back_handoff_insert_does_not_revoke(self):
        self.install()
        script=(
            "import sqlite3,json;"
            "d=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
            "uri=True);d.execute('BEGIN IMMEDIATE');"
            "d.execute(\"INSERT INTO room_reports(room_id,report_kind,body_md) "
            "VALUES('B4-ROOM-A','HANDOFF','fake rolled back')\");"
            "d.rollback();print(json.dumps(True))"
        )
        self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))
        self.assertFalse(self.inspect(ROOMS[0])["revoked"])
        self.assertEqual(self.inspect(ROOMS[0])["generation"],3)

    def test_missing_b2_manifest_refuses_b4_install(self):
        before=self.snap(ROOMS[0])["generation"]
        script=(
            "import sqlite3,json;"
            "d=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
            "uri=True);d.execute('DROP TRIGGER int1_b2_rooms_update_v1');"
            "d.commit();print(json.dumps(True))"
        )
        self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))
        refused=self.b4("install","--room-id",ROOMS[0],
                        "--session-id",self.sessions[ROOMS[0]])
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("incomplete or unexpected hook set",refused.stderr)
        self.assertEqual(self.snap(ROOMS[0])["generation"],before)

    def test_missing_b4_hook_is_detected_by_inspector(self):
        self.install()
        script=(
            "import sqlite3,json;"
            "d=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
            "uri=True);d.execute('DROP TRIGGER int1_b4_chart_insert_v1');"
            "d.commit();print(json.dumps(True))"
        )
        self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))
        refused=self.b4("inspect","--room-id",ROOMS[0])
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("missing or unexpected continuity hooks",refused.stderr)

    def test_failed_global_install_rolls_back_all_epochs_and_ddl(self):
        script="""
import json,sys
sys.path.insert(0,'/source/bin')
import px_int1_fake_continuity as b4
original=b4.authority_row
calls=[0]
def fail_after_all_updates(conn,room):
    calls[0]+=1
    if calls[0]==2:
        raise RuntimeError("INT1-B4 TEST INJECT // after global bump")
    return original(conn,room)
b4.authority_row=fail_after_all_updates
conn=b4.connect()
try:
    b4.install(conn,"B4-ROOM-A","b4-room-a-session")
except RuntimeError as exc:
    print(json.dumps({"error":str(exc),"lookups":calls[0]}))
else:
    raise AssertionError("injection did not fire")
finally:
    conn.close()
"""
        response=self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))
        self.assertIn("TEST INJECT",response["error"])
        self.assertEqual(response["lookups"],2)
        for room in ROOMS:
            self.assertEqual(self.snap(room)["generation"],2)
        refused=self.b4("inspect","--room-id",ROOMS[0])
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("missing or unexpected continuity hooks",refused.stderr)
        self.install()

if __name__=="__main__":
    unittest.main(verbosity=2)
