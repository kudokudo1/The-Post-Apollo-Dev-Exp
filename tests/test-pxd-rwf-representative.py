#!/usr/bin/env python3
"""End-to-end PX CLI continuity with disposable real SQLite/Git.

Two distinct persisted Doctor Sessions (A/B), mock provider configured but
NEVER launched in the success path; refusal path must fail before provider.
This verifies delivery wiring, NOT fresh AI Doctor comprehension.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PX = ROOT / "bin/px"


def staging_environment(work):
    """Allowlist environment before Git Bed creation or any PX init/migration.

    Never copy inherited PX_HOSPITAL_DB (nor HOME/XDG/PX overrides) from the
    operator environment. All SQLite and mutable test paths are inside work.
    """
    root = Path(work).resolve(strict=True)
    for sub in ("state", "home", "tmp", "xdg-data", "xdg-config",
                "xdg-cache", "xdg-runtime", "locks", "authority"):
        (root / sub).mkdir(mode=0o700, exist_ok=True)
    env = {
        "HOME": str(root / "home"), "USER": "rwf-staging",
        "LOGNAME": "rwf-staging", "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": str(root / "tmp"),
        "XDG_DATA_HOME": str(root / "xdg-data"),
        "XDG_CONFIG_HOME": str(root / "xdg-config"),
        "XDG_CACHE_HOME": str(root / "xdg-cache"),
        "XDG_RUNTIME_DIR": str(root / "xdg-runtime"),
        "PX_HOSPITAL_DATA_DIR": str(root / "state"),
        "PX_HOSPITAL_DB": str(root / "state" / "hospital.db"),
        "PX_AGENT_LOCK_DIR": str(root / "locks"),
        "PX_AGENT_AUTHORITY_DIR": str(root / "authority"),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    validate_staging_environment(root, env)
    return env


def validate_staging_environment(work, env):
    """Fail closed before *every* subprocess, including px hospital init.

    Reject symlink/relative-path tricks and post-setup environment tampering.
    An unsafe override must never reach PX's SQLite connect/migrate code.
    """
    root = Path(work).resolve(strict=True)
    expected = {
        "HOME": root / "home", "TMPDIR": root / "tmp",
        "PX_HOSPITAL_DB": root / "state" / "hospital.db",
        "PX_HOSPITAL_DATA_DIR": root / "state",
        "PX_AGENT_LOCK_DIR": root / "locks",
        "PX_AGENT_AUTHORITY_DIR": root / "authority",
        "XDG_DATA_HOME": root / "xdg-data",
        "XDG_CONFIG_HOME": root / "xdg-config",
        "XDG_CACHE_HOME": root / "xdg-cache",
        "XDG_RUNTIME_DIR": root / "xdg-runtime",
    }
    for key, expected_path in expected.items():
        value = env.get(key, "")
        path = Path(value).expanduser()
        if (not value or not path.is_absolute()
                or path.resolve() != expected_path.resolve()
                or not path.resolve().is_relative_to(root)):
            raise RuntimeError("RWF-H1 STAGING_DB_OUTSIDE_ROOT // " + key)
    provider_path = env.get("PX_AGENT_PROVIDER_CONFIG", "")
    if provider_path:
        config = Path(provider_path).expanduser()
        if not config.is_absolute() or not config.resolve().is_relative_to(root):
            raise RuntimeError("RWF-H1 STAGING_DB_OUTSIDE_ROOT // PX_AGENT_PROVIDER_CONFIG")
    return expected["PX_HOSPITAL_DB"]


def git(path, *args, env=None):
    subprocess.run(["git", "-C", str(path), *args],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env=env, check=True, timeout=10)


class ActualCliSuccessionTest(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.work = Path(self.t.name)
        # RWF-H1: sanitize before Git setup and, critically, before PX init.
        self.env = staging_environment(self.work)
        self.bed = self.work / "bed"
        self.bed.mkdir()
        git(self.bed, "init", "-q", env=self.env)
        git(self.bed, "config", "user.name", "Hospital test", env=self.env)
        git(self.bed, "config", "user.email", "hospital@example.invalid", env=self.env)
        (self.bed / "tracked.txt").write_text("base\n")
        git(self.bed, "add", "tracked.txt", env=self.env)
        git(self.bed, "commit", "-qm", "baseline", env=self.env)
        git(self.bed, "checkout", "-qb", "feature/succession", env=self.env)
        git(self.bed, "remote", "add", "origin",
            "https://github.com/kudokudo1/taskbars-post-apollo.git", env=self.env)
        provider_config = self.work / "providers.json"
        mock = ROOT / "tests/fixtures/mock-hermes-agent.py"
        provider_config.write_text(json.dumps({
            "version": 1,
            "providers": {
                "mock": {
                    "name": "MOCK",
                    "command": "python3",
                    "dialect": "hermes-stream-json",
                    "startArgs": [str(mock),"chat","--format","stream-json","--query-file","-"],
                    "resumeArgs": [str(mock),"chat","--resume","{provider_session_id}",
                                   "--format","stream-json","--query-file","-"]
                }
            }
        }))
        self.env["PX_AGENT_PROVIDER_CONFIG"] = str(provider_config)
        self.px("hospital", "init")
        self.px("hospital","room-bind","R-A","--repository",
                "kudokudo1/taskbars-post-apollo","--patient-id","patient-one",
                "--team","team-A","--branch","feature/succession",
                "--bed-path",str(self.bed),"--doctor-id","doctor-A")
        self.px("hospital","room-bind","R-X","--repository",
                "kudokudo1/taskbars-post-apollo","--patient-id","patient-one",
                "--team","team-X","--branch","feature/succession",
                "--bed-path",str(self.bed),"--doctor-id","doctor-X")
        order=self.px("hospital","assignment-create","--room-id","R-A",
                      "--title","Scoped succession","--goal","Finish task C",
                      "--permissions-json",'["READ","TEST"]',
                      "--checklist","- [ ] regression C")
        self.px("hospital","assignment-activate",str(order["id"]))
        self.px("agent","session-create","--room-id","R-A","--doctor-id",
                "doctor-A","--provider-id","mock","--working-directory",
                str(self.bed),"--session-id","session-A")
        self.px("agent","session-create","--room-id","R-A","--doctor-id",
                "doctor-B","--provider-id","mock","--working-directory",
                str(self.bed),"--session-id","session-B")

    def px(self,*args,stdin=None,fail=False):
        validate_staging_environment(self.work, self.env)
        p=subprocess.run([str(PX),*args,"--json"],env=self.env,input=stdin,
                         text=True,capture_output=True,timeout=15)
        if fail:
            self.assertNotEqual(p.returncode,0,p.stdout)
            return p.stderr + p.stdout
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(p.stdout)

    def report(self,kind,title,body,room="R-A",session="session-A"):
        return self.px("hospital","room-report-append","--room-id",room,
                       *([] if not session else ["--session-id",session]),
                       "--report-kind",kind,"--title",title,"--body",body)

    def chart(self,title,body,priority,role="operator"):
        return self.px("hospital","chart-entry-add","--scope","ROOM",
                       "--room-id","R-A","--entry-kind","DECISION",
                       "--title",title,"--priority",str(priority),
                       "--author-role",role,"--body",body)

    def test_succession_across_all_four_omissions(self):
        report=self.report("HANDOFF","Former shift",
                           "Handoff sentinel: sapphire river maps to task C")
        for i in range(40):
            self.report("DOCTOR_NOTE","continue task C "+str(i),
                        "continue task C high-scoring context "+str(i))
        approved=self.chart("Operator approved old decision",
                            "Preserve cyan contract before finishing task C",1)
        for i in range(11):
            self.chart("Recent priority decision "+str(i),
                       "Another active operator note "+str(i),99)
        self.report("HANDOFF","Foreign evidence","CROSS ROOM SECRET",
                    room="R-X",session="")
        session=self.px("hospital","session","session-B")
        self.assertEqual(session["providerSessionId"],"")
        self.assertEqual(session["doctorId"],"doctor-B")
        context=self.px("agent","context","session-B")
        rendered=context["renderedText"]
        self.assertEqual(context["room"]["id"],"R-A")
        self.assertEqual(context["authority"]["allowed"],["READ","TEST"])
        self.assertIn(report["id"],[r["id"] for r in context["requiredHandoffs"]])
        self.assertIn(approved["id"],[r["id"] for r in context["approvedRoomChart"]])
        self.assertNotIn(approved["id"],[r["id"] for r in context["roomChart"]])
        self.assertIn("sapphire river maps to task C",rendered)
        self.assertIn("Preserve cyan contract",rendered)
        self.assertNotIn("CROSS ROOM SECRET",rendered)
        self.assertEqual(context["assignment"]["checklist"],"- [ ] regression C")
        self.assertIn("ROOM_REPORT #"+report["id"],rendered)
        self.assertIn("ROOM_CHART #"+approved["id"],rendered)

    def test_mixed_case_handoff_writes_deliver_to_fresh_doctor_b(self):
        accepted = {}
        for kind in ("handoff", "Handoff", "  hAnDoFf  "):
            marker = "Legacy capitalization: " + kind
            report = self.report(kind, "Required shift", marker)
            self.assertEqual(report["kind"], "HANDOFF")
            accepted[report["id"]] = marker
        for i in range(40):
            self.report("DOCTOR_NOTE", "New filler " + str(i),
                        "No handoff instruction here")
        self.report("handoff", "Other room evidence", "OTHER ROOM SECRET",
                    room="R-X", session="")
        context = self.px("agent", "context", "session-B")
        delivered = {row["id"] for row in context["requiredHandoffs"]}
        self.assertEqual(delivered, set(accepted))
        rendered = context["renderedText"]
        for report_id, marker in accepted.items():
            self.assertIn("ROOM_REPORT #" + report_id, rendered)
            self.assertIn(marker, rendered)
        self.assertNotIn("OTHER ROOM SECRET", rendered)

    def test_lowercase_handoff_overflow_still_refuses_provider_turn(self):
        for i in range(13):
            self.report("handoff", "Required lowcase " + str(i),
                        "Do not silently omit this handoff")
        error = self.px(
            "agent", "turn", "session-B", "--prompt",
            "Proceed even though Room has too many handoffs", fail=True
        )
        self.assertIn("TOO_MANY_MANDATORY_HANDOFFS", error)
        self.assertEqual(
            self.px("hospital", "messages", "R-A", "--limit", "20"), []
        )
        self.assertEqual(
            self.px("hospital", "session", "session-B")["providerSessionId"],
            ""
        )

    def test_overflow_prevents_outgoing_message_or_provider(self):
        for i in range(13):
            self.report("HANDOFF","Shift "+str(i),"Required packet")
        error=self.px("agent","turn","session-B","--prompt",
                      "Proceed despite missing context",fail=True)
        self.assertIn("TOO_MANY_MANDATORY_HANDOFFS",error)
        messages=self.px("hospital","messages","R-A","--limit","20")
        self.assertEqual(messages,[])
        session=self.px("hospital","session","session-B")
        self.assertEqual(session["providerSessionId"],"")



# RWF representative staging: accepted independent ten-case contract.
# Only these 10 tests are run. Original S2 fixture above is deliberately reused.
import importlib.machinery
import importlib.util
import sqlite3
from types import SimpleNamespace
from unittest import mock

APPROVED = "3e0f047c3c7297c45a4cadd1367c6e906bd27dd6"
CASE_DIR = os.environ.get("PX_RWF_EVIDENCE_DIR", "").strip()

def load_agent():
    path = ROOT / "bin" / "px-agent"
    sys.path.insert(0, str(ROOT / "bin"))
    loader = importlib.machinery.SourceFileLoader("rwf_actual_agent", str(path))
    spec = importlib.util.spec_from_loader("rwf_actual_agent", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    loader.exec_module(mod)
    return mod

class RWFRepresentative(unittest.TestCase):
    def setUp(self):
        # Exact executable blob comparison allows unrelated concurrent docs-only main changes.
        for f in ("bin/px", "bin/px-agent", "bin/px-hospital-store", "bin/hospital_target_preflight.py",
                  "config/agent-providers.json"):
            approved = subprocess.check_output(["git","-C",str(ROOT),"rev-parse",APPROVED+":"+f],text=True).strip()
            local = subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD:"+f],text=True).strip()
            self.assertEqual(local, approved, "Approved PX source changed: "+f)
        self.fx = self.fresh()
        self.ev = {"case": "RWF-"+self._testMethodName.split("_")[2], "status":"RUNNING",
                   "approvedExecutableSource":APPROVED,"evidence":[],"liveStateWrites":0,
                   "realProviderCalls":0,"synthetic":True}
        self.assertEqual(self.fx.px("hospital","status")["schema_version"],10)

    def fresh(self):
        fx=ActualCliSuccessionTest("test_succession_across_all_four_omissions")
        fx.setUp()
        self.addCleanup(fx.doCleanups)
        validate_staging_environment(fx.work, fx.env)
        assert Path(fx.env["PX_HOSPITAL_DB"]).resolve() == (fx.work/"state"/"hospital.db").resolve()
        marker=fx.work/"PROVIDER_WAS_LAUNCHED"
        guard=fx.work/"forbidden_provider.py"
        guard.write_text("from pathlib import Path\nPath("+repr(str(marker))+").write_text('INVALID DISPATCH')\nraise SystemExit(99)\n")
        registry=fx.work/"guard-providers.json"
        registry.write_text(json.dumps({"version":1,"providers":{"mock":{
            "name":"MOCK-DISABLED","command":sys.executable,"dialect":"hermes-stream-json",
            "startArgs":[str(guard)],"resumeArgs":[str(guard),"{provider_session_id}"]}}}))
        fx.env["PX_AGENT_PROVIDER_CONFIG"]=str(registry)
        fx.guard=guard
        fx.marker=marker
        return fx

    def good(self,label,ok,detail=None):
        self.assertTrue(ok,label)
        self.ev["evidence"].append({"name":label,"pass":True,"detail":detail or {}})

    def tearDown(self):
        self.ev["status"]="PASS" if self._outcome.success else "FAIL"
        if CASE_DIR:
            out=Path(CASE_DIR)
            out.mkdir(parents=True,exist_ok=True)
            (out/(self.ev["case"]+".json")).write_text(json.dumps(self.ev,indent=2)+"\n")

    def patient(self,fx,body="PATIENT P MANDATORY",patient="patient-one",priority=1,title="Patient decision"):
        return fx.px("hospital","chart-entry-add","--scope","PATIENT","--patient-id",patient,
                     "--entry-kind","DECISION","--title",title,"--priority",str(priority),
                     "--author-role","operator","--body",body)

    def room_decision(self,fx,body="ROOM A MANDATORY",priority=1,title="Room decision"):
        return fx.px("hospital","chart-entry-add","--scope","ROOM","--room-id","R-A",
                     "--entry-kind","DECISION","--title",title,"--priority",str(priority),
                     "--author-role","operator","--body",body)

    def make_q(self,fx):
        fx.px("hospital","room-bind","Q-X","--repository","synthetic/foreign-q",
              "--patient-id","patient-Q","--team","team-Q",
              "--branch","feature/succession","--bed-path",str(fx.bed),"--doctor-id","doctor-Q")
        fx.px("agent","session-create","--room-id","Q-X","--doctor-id","new-doctor-Q",
              "--provider-id","mock","--working-directory",str(fx.bed),"--session-id","session-Q")

    def refuse(self,fx,reason,label=None):
        # First: genuine installed CLI, real scratch SQLite and Git Bed.
        err=fx.px("agent","turn","session-B","--prompt","synthetic continuation",fail=True)
        self.assertIn(reason,err)
        self.assertEqual(fx.px("hospital","messages","R-A","--limit","100"),[])
        self.assertEqual(fx.px("hospital","session","session-B")["providerSessionId"],"")
        self.assertFalse(fx.marker.exists())
        # Second: instrument the actual agent's dispatch order. A context refusal
        # must precede both provider prompt building and Popen provider dispatch.
        agent=load_agent()
        constructed=[]
        spawn=[]
        original=subprocess.Popen
        def deny_prompt(*args,**kwargs):
            constructed.append(True)
            raise AssertionError("provider prompt constructed despite refusal")
        def watch_popen(argv,*args,**kwargs):
            values=argv if isinstance(argv,(list,tuple)) else [argv]
            if str(fx.guard) in [str(v) for v in values]:
                spawn.append(True)
                raise AssertionError("forbidden provider spawned")
            return original(argv,*args,**kwargs)
        args=SimpleNamespace(session_id="session-B",working_directory="",prompt="synthetic continuation",
            prompt_stdin=False,prompt_json_stdin=False,supplemental_context="",
            author_id="operator",message_type="chat",timeout=15)
        with mock.patch.dict(os.environ,fx.env,clear=True):
            with mock.patch.object(agent,"provider_prompt_for_turn",side_effect=deny_prompt):
                with mock.patch.object(subprocess,"Popen",side_effect=watch_popen):
                    with self.assertRaisesRegex(RuntimeError,reason):
                        agent._run_turn_unlocked(args)
        self.assertFalse(constructed)
        self.assertFalse(spawn)
        self.assertFalse(fx.marker.exists())
        self.assertEqual(fx.px("hospital","messages","R-A","--limit","100"),[])
        self.ev["evidence"].append({"name":label or reason,"pass":True,
              "detail":{"reason":reason,"realCLITurnRefused":True,"promptConstructed":False,
                        "outgoingMessages":0,"providerSpawnAttempts":0}})

    def test_rwf_01(self):
        # RWF-H1 negative canary: deliberately inject a fake inherited live-like
        # DB location. The outside file is deliberately NOT a SQLite database.
        # If PX init ever inherits it, this test fails before accepting staging.
        with tempfile.TemporaryDirectory(prefix="rwf-h1-outside-") as outside:
            canary = Path(outside) / "OUTSIDE_CANARY_DO_NOT_OPEN.db"
            marker = b"RWF-H1-OUTSIDE-ROOT-CANARY-NEVER-TOUCH"
            canary.write_bytes(marker)
            stat_before = canary.stat()
            with mock.patch.dict(os.environ, {
                "PX_HOSPITAL_DB": str(canary),
                "PX_HOSPITAL_DATA_DIR": str(Path(outside)),
                "PX_AGENT_LOCK_DIR": str(Path(outside)),
                "PX_AGENT_AUTHORITY_DIR": str(Path(outside)),
            }):
                sanitized = self.fresh()  # invokes px hospital init internally
            self.good("h1_canary_preserved_before_and_after_init",
                canary.read_bytes() == marker and
                canary.stat().st_mtime_ns == stat_before.st_mtime_ns)
            self.good("h1_inherited_db_override_removed_pre_init",
                sanitized.env["PX_HOSPITAL_DB"] == str(sanitized.work.resolve()/"state"/"hospital.db")
                and str(canary) not in sanitized.env.values())
            # A post-setup attempt to repoint the DB must fail before any
            # subprocess can be invoked, not merely fail inside SQLite.
            safe_db = sanitized.env["PX_HOSPITAL_DB"]
            sanitized.env["PX_HOSPITAL_DB"] = str(canary)
            try:
                with mock.patch.object(subprocess, "run") as forbidden_subprocess:
                    with self.assertRaisesRegex(RuntimeError, "STAGING_DB_OUTSIDE_ROOT"):
                        sanitized.px("hospital", "status")
                    forbidden_subprocess.assert_not_called()
                self.good("h1_post_setup_outside_db_rejected_before_subprocess",
                    canary.read_bytes() == marker)
            finally:
                sanitized.env["PX_HOSPITAL_DB"] = safe_db
        x=self.fx.px("agent","context","session-B")
        self.good("correct_active_assignment",x["assignment"]["status"]=="ACTIVE" and x["assignment"]["roomId"]=="R-A")
        self.good("read_test_only",x["authority"]["allowed"]==["READ","TEST"])
        self.good("no_mutation_authority",not set(["EDIT","COMMIT","PUSH","OPEN_PR","INTEGRATE"]) & set(x["authority"]["allowed"]))
        self.good("fresh_doctor_b",x["session"]["doctorId"]=="doctor-B" and not x["session"]["providerSessionId"])
        self.good("unfinished_checklist","regression C" in x["assignment"]["checklist"])

    def test_rwf_02(self):
        fx=self.fx
        body="RWF02 former shift\nstage gamma unfinished\nsecond line\nFINAL HANDOFF SENTINEL"
        old=fx.report("HANDOFF","oldest synthetic HANDOFF",body)
        for i in range(40):
            fx.report("DOCTOR_NOTE","newer "+str(i),"continue task C "+str(i))
        c=fx.px("agent","context","session-B")
        rows=[r for r in c["requiredHandoffs"] if r["id"]==old["id"]]
        self.good("historical_handoff_id_in_required_lane",len(rows)==1,{"newerReports":40,"id":old["id"]})
        self.good("exact_multiline_required_body",rows[0]["body"]==body)
        self.good("rendered_exact_multiline_body",body.replace("\n","\n  ") in c["renderedText"])
        self.good("rendered_full_tail","FINAL HANDOFF SENTINEL" in c["renderedText"])
        self.good("source_ref_delivered","ROOM_REPORT #"+old["id"] in c["renderedText"])

    def test_rwf_03(self):
        old=self.room_decision(self.fx,body="RWF03 FIRST OPERATOR ROOM DECISION")
        for i in range(11):
            self.room_decision(self.fx,title="newer "+str(i),body="high priority",priority=99)
        c=self.fx.px("agent","context","session-B")
        self.good("older_missing_from_preview",old["id"] not in [r["id"] for r in c["roomChart"]])
        self.good("older_in_required_lane",old["id"] in [r["id"] for r in c["approvedRoomChart"]])
        self.good("older_decision_rendered","RWF03 FIRST OPERATOR ROOM DECISION" in c["renderedText"])

    def test_rwf_04(self):
        body=("z"*1450)+"\nRWF04-PATIENT-TAIL-INSTRUCTION"
        self.good("full_length_range",1300<=len(body)<=1700,{"chars":len(body)})
        old=self.patient(self.fx,body=body)
        for i in range(7):
            self.patient(self.fx,title="new priority "+str(i),body="priority preview",priority=99)
        c=self.fx.px("agent","context","session-B")
        self.good("old_not_in_six_preview",old["id"] not in [r["id"] for r in c["patientChart"]])
        self.good("old_in_required_patient_lane",old["id"] in [r["id"] for r in c["approvedPatientChart"]])
        self.good("exact_unclipped_source_body",any(r["id"]==old["id"] and r["body"]==body for r in c["approvedPatientChart"]))
        self.good("full_multiline_render",body.replace("\n","\n  ") in c["renderedText"])
        self.good("patient_ref_rendered","PATIENT_CHART #"+old["id"] in c["renderedText"])

    def test_rwf_05(self):
        fx=self.fx
        fx.px("agent","session-create","--room-id","R-X","--doctor-id","doctor-X-next",
              "--provider-id","mock","--working-directory",str(fx.bed),"--session-id","session-X")
        old=self.patient(fx,body="RWF05 PATIENT P SHARED")
        self.room_decision(fx,body="RWF05 ROOM A EXCLUSIVE")
        fx.report("HANDOFF","Room A handoff","RWF05 ROOM A SECRET HANDOFF")
        c=fx.px("agent","context","session-X")
        self.good("patient_p_cross_room_shared",old["id"] in [r["id"] for r in c["approvedPatientChart"]] and "RWF05 PATIENT P SHARED" in c["renderedText"])
        self.good("room_a_chart_isolated","RWF05 ROOM A EXCLUSIVE" not in c["renderedText"])
        self.good("room_a_handoff_isolated","RWF05 ROOM A SECRET HANDOFF" not in c["renderedText"])
        self.good("room_a_assignment_not_shared",not c["assignment"] and c["authority"]["allowed"]==["READ"])

    def test_rwf_06(self):
        fx=self.fx
        self.make_q(fx)
        self.patient(fx,body="RWF06 PATIENT P CONFIDENTIAL")
        self.patient(fx,patient="patient-Q",body="RWF06 PATIENT Q CONFIDENTIAL")
        fx.report("HANDOFF","P Room handoff","RWF06 P ROOM SECRET")
        fx.px("hospital","room-report-append","--room-id","Q-X","--report-kind","HANDOFF",
              "--title","Q Room handoff","--body","RWF06 Q ROOM SECRET")
        p=fx.px("agent","context","session-B")
        q=fx.px("agent","context","session-Q")
        self.good("p_excludes_q","RWF06 PATIENT Q CONFIDENTIAL" not in p["renderedText"] and "RWF06 Q ROOM SECRET" not in p["renderedText"])
        self.good("q_excludes_p","RWF06 PATIENT P CONFIDENTIAL" not in q["renderedText"] and "RWF06 P ROOM SECRET" not in q["renderedText"])
        self.good("patient_refs_distinct",p["room"]["patientId"]!=q["room"]["patientId"])
        self.good("foreign_patient_authority_isolated",
                  not q["assignment"] and q["authority"]["allowed"] == ["READ"]
                  and p["authority"]["allowed"] == ["READ","TEST"]
                  and "regression C" not in q["renderedText"])

    def test_rwf_07(self):
        for mode,reason in [("malformed","INVALID_LINK_ID"),("foreign","FOREIGN_ROOM"),("paused","NONACTIVE_LINK")]:
            fx=self.fresh()
            if mode=="malformed":
                link="  not-an-id "
            elif mode=="foreign":
                order=fx.px("hospital","assignment-create","--room-id","R-X","--title","Other","--goal","Only other Room")
                fx.px("hospital","assignment-activate",str(order["id"]))
                link=str(order["id"])
            else:
                link=fx.px("hospital","room","R-A")["assignmentId"]
                fx.px("hospital","assignment-status",str(link),"PAUSED")
            with sqlite3.connect(fx.work/"state"/"hospital.db") as conn:
                conn.execute("UPDATE rooms SET current_assignment_id=? WHERE room_id='R-A'",(link,))
            self.refuse(fx,reason)

    def test_rwf_08(self):
        for mode in ("foreign_room","foreign_session"):
            fx=self.fresh()
            self.make_q(fx)
            field,value=("source_room_id","Q-X") if mode=="foreign_room" else ("source_session_id","session-Q")
            with sqlite3.connect(fx.work/"state"/"hospital.db") as conn:
                conn.execute("INSERT INTO chart_entries(scope_type,patient_id,entry_kind,title,body_md,status,author_role,"+field+") VALUES('PATIENT','patient-one','DECISION','bad origin','refuse foreign provenance','ACTIVE','operator',?)",(value,))
            self.refuse(fx,"FOREIGN_PATIENT_SOURCE_ROOM",label="RWF08_"+mode+"_refusal")

    def test_rwf_09(self):
        for lane,count,reason in [("handoff",13,"TOO_MANY_MANDATORY_HANDOFFS"),
                                  ("patient",25,"TOO_MANY_APPROVED_PATIENT_CHARTS"),
                                  ("room",25,"TOO_MANY_APPROVED_ROOM_CHARTS")]:
            fx=self.fresh()
            for i in range(count):
                if lane=="handoff":
                    fx.report("HANDOFF","shift "+str(i),"mandatory handoff")
                elif lane=="patient":
                    self.patient(fx,title="Patient "+str(i),body="required")
                else:
                    self.room_decision(fx,title="Room "+str(i),body="required")
            self.refuse(fx,reason)

    def test_rwf_10(self):
        for mode,reason in [("long_handoff","OVERSIZED_REQUIRED_RECORD"),
                            ("long_patient","OVERSIZED_REQUIRED_PATIENT_RECORD"),
                            ("combined","REQUIRED_CONTEXT_OVER_BUDGET")]:
            fx=self.fresh()
            if mode=="long_handoff":
                fx.report("HANDOFF","too long","h"*1810)
            elif mode=="long_patient":
                self.patient(fx,title="too long",body="p"*1810)
            else:
                for i in range(8):
                    fx.report("HANDOFF","required "+str(i),"h"*1550)
                for i in range(4):
                    self.patient(fx,title="required "+str(i),body="p"*1550)
            self.refuse(fx,reason)

if __name__ == "__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(RWFRepresentative)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() and result.testsRun==10 else 1)
