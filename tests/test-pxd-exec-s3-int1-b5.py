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

    def b7_source_edit(self, hook, statement, values, multiple=False):
        # Test-only independent SQLite actor can bypass one continuity hook,
        # edit data and restore EXACT source SQL before commit. B7 must still
        # reject invalid underlying record/provenance even with clean manifests.
        script = """
import json,sqlite3,sys
sys.path.insert(0,'/source/bin')
from px_int1_fake_continuity import EXPECTED
c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',uri=True)
c.execute('BEGIN IMMEDIATE')
c.execute('DROP TRIGGER ' + """ + repr(hook) + """)
statement=""" + repr(statement) + """
values=""" + repr(values) + """
if """ + ("True" if multiple else "False") + """:
    c.executemany(statement, values)
else:
    c.execute(statement, values)
c.execute(EXPECTED[""" + repr(hook) + """])
c.commit()
print(json.dumps(True))
"""
        self.modify(script)
        state=self.ok(self.b4("inspect","--room-id",ROOM_A))
        self.assertEqual(state["generation"],3)
        self.assertFalse(state["revoked"])

    def assert_b7_reject(self, error, turn):
        before=self.state(ROOM_A)
        count=self.accepted_count()
        request=self.accept(ROOM_A,turn)
        self.assertNotEqual(request.returncode,0)
        self.assertIn(error,request.stderr)
        self.assertEqual(self.state(ROOM_A),before)
        self.assertEqual(self.accepted_count(),count)
        digest=self.b1("context-digest","--room-id",ROOM_A,
                       "--session-id",self.sessions[ROOM_A])
        self.assertNotEqual(digest.returncode,0)
        self.assertIn(error,digest.stderr)

    def test_b7_rejects_13_mandatory_room_handoffs_without_truncation(self):
        self.b7_source_edit("int1_b4_handoff_insert_v1",
            "INSERT INTO room_reports(room_id,report_kind,title,body_md) "
            "VALUES(?,?,?,?)",
            [(ROOM_A,"HANDOFF","extra", "source") for _ in range(12)],
            multiple=True)
        self.assert_b7_reject("TOO_MANY_MANDATORY_HANDOFFS","over-handoff")

    def test_b7_rejects_25_operator_room_charts_without_truncation(self):
        self.b7_source_edit("int1_b4_chart_insert_v1",
            "INSERT INTO chart_entries(scope_type,room_id,author_role,body_md) "
            "VALUES(?,?,?,?)",
            [("ROOM",ROOM_A,"operator","required") for _ in range(24)],
            multiple=True)
        self.assert_b7_reject("TOO_MANY_APPROVED_ROOM_CHARTS","over-room-chart")

    def test_b7_rejects_25_operator_patient_charts_without_truncation(self):
        self.b7_source_edit("int1_b4_chart_insert_v1",
            "INSERT INTO chart_entries(scope_type,patient_id,author_role,body_md) "
            "VALUES(?,?,?,?)",
            [("PATIENT",PATIENT,"operator","required") for _ in range(24)],
            multiple=True)
        self.assert_b7_reject("TOO_MANY_APPROVED_PATIENT_CHARTS","over-patient-chart")

    def test_b7_empty_handoff_body_refuses(self):
        rid=int(self.info(ROOM_A)["handoffIds"][0])
        self.b7_source_edit("int1_b4_handoff_update_v1",
            "UPDATE room_reports SET body_md='  ' WHERE report_id=?", (rid,))
        self.assert_b7_reject("EMPTY_REQUIRED_RECORD","empty-handoff")

    def test_b7_oversized_room_chart_body_refuses(self):
        self.b7_source_edit("int1_b4_chart_update_v1",
            "UPDATE chart_entries SET body_md=? "
            "WHERE scope_type='ROOM' AND room_id=?",
            ("z"*1801,ROOM_A))
        self.assert_b7_reject("OVERSIZED_REQUIRED_RECORD","oversized-chart")

    def test_b7_combined_required_context_budget_refuses(self):
        self.b7_source_edit("int1_b4_handoff_insert_v1",
            "INSERT INTO room_reports(room_id,report_kind,title,body_md) "
            "VALUES(?,?,?,?)",
            [(ROOM_A,"HANDOFF","budget","x"*1700) for _ in range(11)],
            multiple=True)
        self.assert_b7_reject("REQUIRED_CONTEXT_OVER_BUDGET","budget-overflow")

    def test_b7_room_chart_foreign_source_room_refuses(self):
        self.b7_source_edit("int1_b4_chart_update_v1",
            "UPDATE chart_entries SET source_room_id=? "
            "WHERE scope_type='ROOM' AND room_id=?",
            (ROOM_B,ROOM_A))
        self.assert_b7_reject("WRONG_REQUIRED_ROOM_CHART","foreign-room-source")

    def test_b7_patient_chart_foreign_patient_source_room_refuses(self):
        self.b7_source_edit("int1_b4_chart_update_v1",
            "UPDATE chart_entries SET source_room_id=? "
            "WHERE scope_type='PATIENT' AND patient_id=?",
            (OTHER,PATIENT))
        self.assert_b7_reject("FOREIGN_PATIENT_SOURCE_ROOM","foreign-patient")

    def test_b7_patient_chart_source_session_mismatch_refuses(self):
        self.b7_source_edit("int1_b4_chart_update_v1",
            "UPDATE chart_entries SET source_room_id=?, source_session_id=? "
            "WHERE scope_type='PATIENT' AND patient_id=?",
            (ROOM_A,self.sessions[ROOM_B],PATIENT))
        self.assert_b7_reject("PATIENT_SOURCE_MISMATCH","mismatched-session")

    def test_b7_patient_chart_source_session_from_foreign_patient_refuses(self):
        self.b7_source_edit("int1_b4_chart_update_v1",
            "UPDATE chart_entries SET source_room_id=NULL, source_session_id=? "
            "WHERE scope_type='PATIENT' AND patient_id=?",
            (self.sessions[OTHER],PATIENT))
        self.assert_b7_reject("FOREIGN_PATIENT_SOURCE_ROOM","foreign-session")

    def test_b7_already_accepted_turn_replay_refuses_malformed_continuity(self):
        first=self.ok(self.accept(ROOM_A,"before-invalid-record"))
        self.assertEqual(first["state"],"ACCEPTED_UNDISPATCHED")
        original_count=self.accepted_count()
        rid=int(self.info(ROOM_A)["handoffIds"][0])
        self.b7_source_edit("int1_b4_handoff_update_v1",
            "UPDATE room_reports SET body_md=' ' WHERE report_id=?", (rid,))
        before=self.state(ROOM_A)
        rejected=self.accept(ROOM_A,"before-invalid-record")
        self.assertNotEqual(rejected.returncode,0)
        self.assertIn("EMPTY_REQUIRED_RECORD",rejected.stderr)
        self.assertEqual(self.state(ROOM_A),before)
        self.assertEqual(self.accepted_count(),original_count)

    def test_b7_twelve_handoffs_below_budgets_can_still_accept(self):
        # Twelve is the maximum mandatory lane size, not an overflow.
        self.b7_source_edit("int1_b4_handoff_insert_v1",
            "INSERT INTO room_reports(room_id,report_kind,title,body_md) "
            "VALUES(?,?,?,?)",
            [(ROOM_A,"HANDOFF","within limit","valid") for _ in range(11)],
            multiple=True)
        fresh=self.info(ROOM_A)
        self.assertEqual(len(fresh["handoffIds"]),12)
        accepted=self.ok(self.accept(
            ROOM_A,"bounded-complete-continuity",
            digest=fresh["contextHash"]))
        self.assertEqual(accepted["state"],"ACCEPTED_UNDISPATCHED")

    def test_b7_valid_patient_cross_room_source_session_remains_permitted(self):
        self.b7_source_edit("int1_b4_chart_update_v1",
            "UPDATE chart_entries SET source_room_id=?, source_session_id=? "
            "WHERE scope_type='PATIENT' AND patient_id=?",
            (ROOM_B,self.sessions[ROOM_B],PATIENT))
        fresh=self.info(ROOM_A)["contextHash"]
        self.assertNotEqual(fresh,self.digests[ROOM_A])
        self.assert_no_commit(ROOM_A,"stale-source","stale or mismatched continuity digest")
        accepted=self.ok(self.accept(ROOM_A,"valid-same-patient-source",digest=fresh))
        self.assertEqual(accepted["state"],"ACCEPTED_UNDISPATCHED")

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
