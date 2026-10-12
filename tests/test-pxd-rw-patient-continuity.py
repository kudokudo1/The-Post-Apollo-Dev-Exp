#!/usr/bin/env python3
"""RW-01/RW-02: actual PX source and disposable CLI Patient continuity probes.

No real provider execution. Source unit tests use sqlite3 :memory:; the CLI
uses an isolated temporary Hospital DB and Git Bed. Accepted S2 Room behavior
is inherited as a positive-control regression in the CLI class.
"""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


s2 = load("rw_s2_source_fixture", ROOT / "tests/test-pxd-s2-required-continuity.py")
cli = load("rw_s2_cli_fixture", ROOT / "tests/test-pxd-s2-disposable-cli.py")


class PatientContextSourceTests(unittest.TestCase):
    def setUp(self):
        # Reuse Nurse 2's actual-source P1/S2 fixture without editing it.
        self.s2 = s2.SuccessionContextTests("test_required_text_fully_rendered_below_limit")
        self.s2.setUp()
        self.addCleanup(self.s2.doCleanups)
        self.db = self.s2.db
        self.agent = s2.agent

    def patient(self, title, body, priority=5, role="operator",
                status="ACTIVE", patient="P", source_room=""):
        cur = self.db.execute(
            "INSERT INTO chart_entries(scope_type,patient_id,entry_kind,"
            "title,body_md,priority,status,author_role,source_room_id) "
            "VALUES('PATIENT',?,'DECISION',?,?,?,?,?,?)",
            (patient,title,body,priority,status,role,source_room or None),
        )
        self.db.commit()
        return str(cur.lastrowid)

    def foreign_patient(self):
        self.db.execute(
            "INSERT INTO patients(patient_id,repository,label) "
            "VALUES('Q','foreign/repo','Foreign patient')"
        )
        self.db.execute(
            "INSERT INTO rooms(room_id,patient_id,team,branch,bed_path,doctor_id) "
            "VALUES('C','Q','team-c','feature/c','/tmp/foreign','doctor-C')"
        )
        self.db.commit()

    def context(self):
        return self.s2.context()

    def test_rw01_older_low_priority_patient_decision_survives_six_high(self):
        marker = "RW01-INDEPENDENT-MANDATORY-PATIENT-DECISION"
        old = self.patient("Old active decision", marker, priority=1)
        for i in range(7):
            self.patient("Priority preview " + str(i), "higher ranked", priority=99)
        ctx = self.context()
        self.assertNotIn(old, [v["id"] for v in ctx["patientChart"]])
        self.assertIn(old, [v["id"] for v in ctx["approvedPatientChart"]])
        self.assertIn(marker, self.agent.render_live_context(ctx))
        self.assertIn(old, self.agent.context_summary(ctx)["approvedPatientChartRefs"])

    def test_rw02_exact_1700_char_patient_body_survives_900_preview(self):
        marker = "RW02-ESSENTIAL-INSTRUCTION-NEAR-TAIL"
        body = ("a" * 1400) + marker
        self.patient("Full required instruction", body, priority=1)
        rendered = self.agent.render_live_context(self.context())
        self.assertIn(body, rendered)
        self.assertIn(marker, rendered)
        self.assertIn("REQUIRED PATIENT CONTINUITY", rendered)

    def test_unapproved_and_inactive_not_mandatory(self):
        doctor = self.patient("Unapproved", "DOCTOR DRAFT", role="doctor")
        ended = self.patient("Resolved", "NOT ACTIVE", status="RESOLVED")
        rows = self.context()["approvedPatientChart"]
        self.assertNotIn(doctor, [v["id"] for v in rows])
        self.assertNotIn(ended, [v["id"] for v in rows])

    def test_patient_limit_refuses_instead_of_omitting_lower_priority(self):
        for i in range(self.agent.REQUIRED_PATIENT_CHART_LIMIT + 1):
            self.patient("Approved " + str(i), "required", priority=i % 100)
        with self.assertRaisesRegex(RuntimeError,
                                    "TOO_MANY_APPROVED_PATIENT_CHARTS"):
            self.context()

    def test_oversized_patient_body_refused_without_clipping(self):
        self.patient("Large", "x" * 1850)
        with self.assertRaisesRegex(RuntimeError,
                                    "OVERSIZED_REQUIRED_PATIENT_RECORD"):
            self.context()

    def test_shared_room_and_patient_budget_refuses(self):
        for i in range(8):
            self.s2.report("A", "HANDOFF", "Shift " + str(i), "h" * 1600)
        for i in range(4):
            self.patient("Approved " + str(i), "p" * 1500)
        with self.assertRaisesRegex(RuntimeError,
                                    "REQUIRED_CONTEXT_OVER_BUDGET"):
            self.context()

    def test_foreign_patient_excluded_but_same_patient_room_allowed(self):
        self.foreign_patient()
        same = self.patient("Another same-Patient Room",
                            "SAME PATIENT CROSS ROOM OK", source_room="B")
        self.patient("Other Patient", "FOREIGN PATIENT PRIVATE",
                     patient="Q", source_room="C")
        ctx = self.context()
        rendered = self.agent.render_live_context(ctx)
        self.assertIn(same, [r["id"] for r in ctx["approvedPatientChart"]])
        self.assertIn("SAME PATIENT CROSS ROOM OK", rendered)
        self.assertNotIn("FOREIGN PATIENT PRIVATE", rendered)

    def test_foreign_source_room_for_claimed_patient_refused(self):
        self.foreign_patient()
        self.patient("Bogus provenance", "confidential", source_room="C")
        with self.assertRaisesRegex(RuntimeError,
                                    "FOREIGN_PATIENT_SOURCE_ROOM"):
            self.context()

    def test_tampered_foreign_record_refuses(self):
        original = self.agent.px_hospital
        def tampered(command, *args):
            if command == "chart-entries" and "--author-role" in args and (
                "--scope" in args and args[args.index("--scope")+1] == "PATIENT"
            ):
                return [{"id":"999","scope":"PATIENT","patientId":"Q",
                         "status":"ACTIVE","authorRole":"operator",
                         "title":"foreign","body":"foreign secret"}]
            return original(command, *args)
        self.agent.px_hospital = tampered
        with self.assertRaisesRegex(RuntimeError, "FOREIGN_PATIENT_RECORD"):
            self.context()


class PatientActualCliTests(cli.ActualCliSuccessionTest):
    """Inherited S2 CLI tests also rerun as positive controls."""

    def patient(self, title, body, priority=1, role="operator"):
        return self.px(
            "hospital", "chart-entry-add", "--scope", "PATIENT",
            "--patient-id", "patient-one", "--entry-kind", "DECISION",
            "--title", title, "--priority", str(priority),
            "--author-role", role, "--body", body,
        )

    def test_cli_fresh_doctor_b_receives_older_full_patient_instruction(self):
        marker = "PX-DOCTOR-B-FULL-PATIENT-TAIL-INSTRUCTION"
        body = "z" * 1300 + marker
        old = self.patient("Established Patient decision", body, 1)
        for i in range(8):
            self.patient("New " + str(i), "ranked preview", 99)
        ctx = self.px("agent", "context", "session-B")
        self.assertNotIn(old["id"], [x["id"] for x in ctx["patientChart"]])
        self.assertIn(old["id"], [x["id"] for x in ctx["approvedPatientChart"]])
        self.assertIn(body, ctx["renderedText"])
        self.assertIn("PATIENT_CHART #" + old["id"], ctx["renderedText"])

    def test_cli_patient_overflow_refuses_before_outgoing_or_provider(self):
        for i in range(25):
            self.patient("Decision " + str(i), "required instruction", 5)
        error = self.px(
            "agent", "turn", "session-B", "--prompt", "continue",
            fail=True,
        )
        self.assertIn("TOO_MANY_APPROVED_PATIENT_CHARTS", error)
        self.assertEqual(self.px("hospital", "messages", "R-A", "--limit", "20"), [])
        self.assertEqual(
            self.px("hospital", "session", "session-B")["providerSessionId"], ""
        )

    def test_cli_patient_oversize_refuses_before_outgoing(self):
        self.patient("Long instruction", "n" * 1900)
        error = self.px(
            "agent", "turn", "session-B", "--prompt", "continue",
            fail=True,
        )
        self.assertIn("OVERSIZED_REQUIRED_PATIENT_RECORD", error)
        self.assertEqual(self.px("hospital", "messages", "R-A", "--limit", "20"), [])


if __name__ == "__main__":
    unittest.main()
