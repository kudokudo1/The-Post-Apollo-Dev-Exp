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


def git(path, *args):
    subprocess.run(["git", "-C", str(path), *args],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=True, timeout=10)


class ActualCliSuccessionTest(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.work = Path(self.t.name)
        self.bed = self.work / "bed"
        self.bed.mkdir()
        git(self.bed, "init", "-q")
        git(self.bed, "config", "user.name", "Hospital test")
        git(self.bed, "config", "user.email", "hospital@example.invalid")
        (self.bed / "tracked.txt").write_text("base\n")
        git(self.bed, "add", "tracked.txt")
        git(self.bed, "commit", "-qm", "baseline")
        git(self.bed, "checkout", "-qb", "feature/succession")
        git(self.bed, "remote", "add", "origin",
            "https://github.com/kudokudo1/taskbars-post-apollo.git")
        self.env = os.environ.copy()
        self.env.update({
            "PX_HOSPITAL_DATA_DIR": str(self.work / "state"),
            "PX_AGENT_LOCK_DIR": str(self.work / "locks"),
            "PX_AGENT_AUTHORITY_DIR": str(self.work / "authority"),
        })
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


if __name__ == "__main__":
    unittest.main()
