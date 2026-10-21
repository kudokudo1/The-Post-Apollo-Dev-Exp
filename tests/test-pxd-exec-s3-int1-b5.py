#!/usr/bin/env python3
"""INT1-B5/B6: disposable-only continuity manifest and source digest acceptance.

Real Hospital state, broker/provider execution, installed Fedora and real
credentials are never accessed by this test suite.
"""
import hashlib
import json
from pathlib import Path
import unittest

from px_int1_fixture import DisposablePX

REPO=Path(__file__).resolve().parents[1]
ROOM_A="B6-ROOM-A"
ROOM_B="B6-ROOM-B"
OTHER="B6-OTHER-PATIENT"
PATIENT="B6-SHARED"
INVALID=hashlib.sha256(b"caller-controlled forged context").hexdigest()

class B5B6ContinuityAcceptanceTests(unittest.TestCase):
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
        self.sessions={}
        for room,patient in ((ROOM_A,PATIENT),(ROOM_B,PATIENT),(OTHER,OTHER)):
            self.create_room(room,patient)
        for room in self.sessions:
            self.ok(self.b1("bootstrap","--room-id",room,
                            "--session-id",self.sessions[room]))
        # Explicitly preinstall authority-proven continuity inputs, so the
        # first digest must include actual source-owned rows.
        self.report("HANDOFF",ROOM_A,body="original source handoff")
        self.chart("ROOM",ROOM_A,body="original approved room decision")
        self.chart("PATIENT",PATIENT,body="original approved patient decision")
        self.ok(self.b2("install","--room-id",ROOM_A,
                        "--session-id",self.sessions[ROOM_A]))
        self.ok(self.b4("install","--room-id",ROOM_A,
                        "--session-id",self.sessions[ROOM_A]))
        self.assertEqual(self.info(ROOM_A)["generation"],3)
        self.assertEqual(self.info(ROOM_B)["generation"],3)
        self.digests={room:self.info(room)["contextHash"] for room in self.sessions}

    def ok(self,r):
        self.assertEqual(r.returncode,0,r.stderr)
        return json.loads(r.stdout)

    def tool(self,filename,*args,input=None):
        return self.fx.run("/usr/bin/python3","-B",filename,*args,
                           input=input,timeout=30)

    def b1(self,*args,input=None):
        return self.tool("/source/bin/px_int1_fake_atomic.py",*args,input=input)

    def b2(self,*args):
        return self.tool("/source/bin/px_int1_fake_epoch.py",*args)

    def b4(self,*args):
        return self.tool("/source/bin/px_int1_fake_continuity.py",*args)

    def create_room(self,room,patient):
        session=room.lower()+"-session"
        self.ok(self.fx.hospital(
            "room-bind",room,"--repository","kudokudo1/taskbars-post-apollo",
            "--patient-id",patient,"--team",room+"-TEAM","--branch","b6",
            "--bed-path","/fixture/bed","--doctor-id",room+"-DOCTOR"))
        self.ok(self.fx.hospital("session-put",session,
            "--room-id",room,"--doctor-id",room+"-DOCTOR",
            "--provider-id","int1-fake","--status","IDLE"))
        self.ok(self.fx.hospital("session-runtime",session,
            "--working-directory","/fixture/bed","--status","IDLE"))
        assignment=self.ok(self.fx.hospital("assignment-create",
            "--room-id",room,"--title","B6 fake","--goal","Synthetic only",
            "--permissions-json",'["READ","EDIT"]'))
        self.ok(self.fx.hospital("assignment-activate",assignment["id"]))
        self.sessions[room]=session

    def report(self,kind,room,body="synthetic note"):
        return self.ok(self.fx.hospital(
            "room-report-append","--room-id",room,
            "--session-id",self.sessions[room],"--report-kind",kind,
            "--title","B6 report","--body",body))

    def chart(self,scope,target,role="operator",body="synthetic decision"):
        args=["chart-entry-add","--scope",scope,"--author-role",role,
              "--entry-kind","DECISION","--title","B6 Chart","--body",body]
        args+=(["--room-id",target] if scope=="ROOM" else ["--patient-id",target])
        return self.ok(self.fx.hospital(*args))

    def info(self,room):
        return self.ok(self.b1("context-digest","--room-id",room,
                               "--session-id",self.sessions[room]))

    def accept(self,room,turn,digest=None,generation=3,fail_after=None):
        args=["accept","--room-id",room,"--session-id",self.sessions[room],
              "--turn-id",turn,"--generation",str(generation),
              "--context-hash",digest or self.digests[room],"--body-stdin"]
        if fail_after:
            args+=["--fail-after",fail_after]
        return self.b1(*args,input="disposable prompt")

    def state(self,room):
        return (self.ok(self.fx.hospital("messages",room,"--limit","100")),
                self.ok(self.fx.hospital("events",self.sessions[room],
                                        "--limit","100")))

    def accepted_count(self):
        probe=("import sqlite3,json;"
               "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=ro',"
               "uri=True);print(json.dumps(c.execute("
               "'SELECT COUNT(*) FROM int1_fake_accepted_turns').fetchone()[0]))")
        return self.ok(self.fx.run("/usr/bin/python3","-B","-c",probe))

    def modify(self,script):
        return self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))

    def assert_no_commit(self,room,turn,expected,**kwargs):
        before=self.state(room)
        count=self.accepted_count()
        refused=self.accept(room,turn,**kwargs)
        self.assertNotEqual(refused.returncode,0)
        self.assertIn(expected,refused.stderr)
        self.assertEqual(self.state(room),before)
        self.assertEqual(self.accepted_count(),count)

    def test_source_derived_context_digest_separates_rooms_and_patient(self):
        a,b,c=self.info(ROOM_A),self.info(ROOM_B),self.info(OTHER)
        self.assertEqual(len(a["handoffIds"]),1)
        self.assertEqual(len(a["chartIds"]),2)
        self.assertEqual(len(b["handoffIds"]),0)
        self.assertEqual(len(b["chartIds"]),1)
        self.assertEqual(len(c["chartIds"]),0)
        self.assertEqual(len({a["contextHash"],b["contextHash"],c["contextHash"]}),3)
        self.assertEqual(a["contextHash"],self.info(ROOM_A)["contextHash"])

    def test_matching_stored_digest_accepts_and_replays_only_once(self):
        a=self.ok(self.accept(ROOM_A,"canonical"))
        self.assertEqual(a["state"],"ACCEPTED_UNDISPATCHED")
        self.assertFalse(a["replayed"])
        same=self.ok(self.accept(ROOM_A,"canonical"))
        self.assertTrue(same["replayed"])
        self.assertEqual(a["messageId"],same["messageId"])
        self.assertEqual(self.accepted_count(),1)

    def test_forged_formatted_digest_refuses_with_zero_writes(self):
        self.assert_no_commit(ROOM_A,"wrong-hash",
                              "stale or mismatched continuity digest",
                              digest=INVALID)

    def test_missing_b4_trigger_refuses_new_and_existing_replay(self):
        self.ok(self.accept(ROOM_A,"before-drop"))
        script=("import sqlite3,json;"
                "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
                "uri=True);c.execute('DROP TRIGGER int1_b4_handoff_update_v1');"
                "c.commit();print(json.dumps(True))")
        self.modify(script)
        for turn in ("after-drop","before-drop"):
            with self.subTest(turn=turn):
                self.assert_no_commit(ROOM_A,turn,
                    "missing or unexpected continuity hooks")

    def test_modified_b4_trigger_definition_refuses(self):
        script=("import sqlite3,json;"
                "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
                "uri=True);c.executescript("
                "'DROP TRIGGER int1_b4_chart_update_v1;"
                "CREATE TRIGGER int1_b4_chart_update_v1 "
                "AFTER UPDATE ON chart_entries BEGIN SELECT 1; END;');"
                "print(json.dumps(True))")
        self.modify(script)
        self.assert_no_commit(ROOM_A,"modified-hook",
                              "changed continuity hook definition")

    def test_extra_prefixed_b4_trigger_refuses(self):
        script=("import sqlite3,json;"
                "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
                "uri=True);c.execute("
                "'CREATE TRIGGER int1_b4_extra AFTER UPDATE ON rooms "
                "BEGIN SELECT 1; END');c.commit();print(json.dumps(True))")
        self.modify(script)
        self.assert_no_commit(ROOM_A,"extra-hook",
                              "missing or unexpected continuity hooks")

    def test_direct_handoff_mutation_with_restored_hooks_is_detected_by_digest(self):
        # Adversarial same-UID, test-only SQL: temporarily drop the UPDATE
        # hook, alter stored context, reinstall EXACT source definition and
        # commit the entire change. Epoch stays unchanged; both B2/B4
        # manifests inspect clean. The independent digest MUST still refuse.
        script="""
import json,sqlite3,sys
sys.path.insert(0,'/source/bin')
from px_int1_fake_continuity import EXPECTED
c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',uri=True)
c.execute('BEGIN IMMEDIATE')
c.execute('DROP TRIGGER int1_b4_handoff_update_v1')
c.execute("UPDATE room_reports SET body_md='changed without trigger' "
          "WHERE room_id='B6-ROOM-A' AND UPPER(report_kind)='HANDOFF'")
c.execute(EXPECTED['int1_b4_handoff_update_v1'])
c.commit()
print(json.dumps(True))
"""
        self.modify(script)
        self.assertEqual(self.ok(self.b4("inspect","--room-id",ROOM_A))["generation"],3)
        new=self.info(ROOM_A)
        self.assertNotEqual(new["contextHash"],self.digests[ROOM_A])
        self.assert_no_commit(ROOM_A,"stale-record","stale or mismatched continuity digest")
        # Only a NEW digest computed from the changed source is accepted,
        # still storage-only; external tampering is NOT generally solved.
        ok=self.ok(self.accept(ROOM_A,"fresh-record",digest=new["contextHash"]))
        self.assertEqual(ok["state"],"ACCEPTED_UNDISPATCHED")

    def test_patient_chart_change_revokes_same_patient_not_other_patient(self):
        self.chart("PATIENT",PATIENT,body="new policy")
        for room in (ROOM_A,ROOM_B):
            self.assert_no_commit(room,"old-patient-"+room,
                                  "stale or revoked authority")
        self.assertFalse(self.ok(self.b4("inspect","--room-id",OTHER))["revoked"])
        other=self.ok(self.accept(OTHER,"other-patient"))
        self.assertEqual(other["state"],"ACCEPTED_UNDISPATCHED")

    def test_handoff_change_and_restore_cannot_replay_old_grant(self):
        report_id=self.info(ROOM_A)["handoffIds"][0]
        for body in ("interim decision","original source handoff"):
            sql=("import json,sqlite3;"
                 "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
                 "uri=True);c.execute("
                 "'UPDATE room_reports SET body_md=? WHERE report_id=?',"
                 +repr((body,int(report_id)))+");c.commit();print(json.dumps(True))")
            self.modify(sql)
        self.assert_no_commit(ROOM_A,"restore-report","stale or revoked authority")
        self.assertFalse(self.ok(self.b4("inspect","--room-id",ROOM_B))["revoked"])

    def test_irrelevant_note_and_unapproved_chart_do_not_alter_digest(self):
        self.report("DOCTOR_NOTE",ROOM_A,body="ignored note")
        self.chart("ROOM",ROOM_A,role="doctor",body="unapproved")
        self.assertEqual(self.info(ROOM_A)["contextHash"],self.digests[ROOM_A])
        self.assertEqual(self.ok(self.accept(ROOM_A,"no-false-revoke"))["state"],
                         "ACCEPTED_UNDISPATCHED")

    def test_rollback_after_context_event_with_valid_digest_leaves_zero_turns(self):
        self.assert_no_commit(ROOM_A,"fail-after-context",
                              "TEST INJECT // rollback after context",
                              fail_after="context")
        self.assertEqual(self.accepted_count(),0)

if __name__=="__main__":
    unittest.main(verbosity=2)
