#!/usr/bin/env python3
"""INT1-B8 candidate: compare detached eligibility with the real, non-executing PX context.

Only the accepted disposable Bubblewrap fixture is used. No provider or broker
starts, and this test does not claim actual dispatch-time context equivalence.
"""
import json
from pathlib import Path
import unittest

from px_int1_fixture import DisposablePX

REPO = Path(__file__).resolve().parents[1]
ROOM_A = "B8-ROOM-A"
ROOM_B = "B8-ROOM-B"
ROOM_C = "B8-ROOM-C"
PATIENT = "B8-PATIENT"
OTHER_PATIENT = "B8-OTHER-PATIENT"
FAKE = {"version": 1, "providers": {
    "int1-fake": {"name": "INT1 FAKE", "executionProfile": "EXEC_S3_FAKE_ONLY",
                  "dialect": "exec-s3-fake-only"}
}}


class B8ContextParityTests(unittest.TestCase):
    def setUp(self):
        self.fx = DisposablePX(REPO)
        self.addCleanup(self.fx.close)
        registry = self.fx.root / "providers/fake.json"
        registry.write_text(json.dumps(FAKE))
        registry.chmod(0o600)
        self.assertTrue(self.fx.assert_safe_environment())
        (self.fx.root / "bed/tracked.txt").write_text("synthetic only\n")
        for command in (
            ("/usr/bin/git", "-C", "/fixture/bed", "init", "-q"),
            ("/usr/bin/git", "-C", "/fixture/bed", "add", "tracked.txt"),
            ("/usr/bin/git", "-C", "/fixture/bed", "-c", "user.name=Fixture",
             "-c", "user.email=fixture@example.invalid", "commit", "-qm", "base"),
            ("/usr/bin/git", "-C", "/fixture/bed", "checkout", "-qb", "b8"),
            ("/usr/bin/git", "-C", "/fixture/bed", "remote", "add", "origin",
             "https://github.com/kudokudo1/taskbars-post-apollo.git"),
        ):
            result = self.fx.run(*command)
            self.assertEqual(result.returncode, 0, (command, result.stderr))
        self.ok(self.fx.hospital("init"))
        self.sessions = {}
        for room, patient in ((ROOM_A, PATIENT), (ROOM_B, PATIENT),
                              (ROOM_C, OTHER_PATIENT)):
            self.register(room, patient)

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def run_module(self, filename, *argv, input=None):
        return self.fx.run("/usr/bin/python3", "-B", filename, *argv,
                           input=input, timeout=45)

    def b1(self, *args, input=None):
        return self.run_module("/source/bin/px_int1_fake_atomic.py", *args,
                               input=input)

    def b2(self, *args):
        return self.run_module("/source/bin/px_int1_fake_epoch.py", *args)

    def b4(self, *args):
        return self.run_module("/source/bin/px_int1_fake_continuity.py", *args)

    def register(self, room, patient):
        session = room.lower() + "-session"
        doctor = room + "-DOCTOR"
        self.ok(self.fx.hospital(
            "room-bind", room, "--repository", "kudokudo1/taskbars-post-apollo",
            "--patient-id", patient, "--team", room + "-TEAM",
            "--branch", "b8", "--bed-path", "/fixture/bed",
            "--doctor-id", doctor,
        ))
        self.ok(self.fx.hospital(
            "session-put", session, "--room-id", room, "--doctor-id", doctor,
            "--provider-id", "int1-fake", "--status", "IDLE",
        ))
        self.ok(self.fx.hospital(
            "session-runtime", session, "--working-directory", "/fixture/bed",
            "--status", "IDLE",
        ))
        assignment = self.ok(self.fx.hospital(
            "assignment-create", "--room-id", room,
            "--title", "B8 synthetic", "--goal", "Compare required continuity",
            "--permissions-json", '["READ","EDIT"]',
        ))
        self.ok(self.fx.hospital("assignment-activate", assignment["id"]))
        self.sessions[room] = session

    def handoff(self, room, body):
        return self.ok(self.fx.hospital(
            "room-report-append", "--room-id", room,
            "--session-id", self.sessions[room], "--report-kind", "HANDOFF",
            "--title", "B8 HANDOFF", "--body", body,
        ))

    def chart(self, scope, target, body, role="operator"):
        args = ["chart-entry-add", "--scope", scope, "--entry-kind", "DECISION",
                "--title", "B8 CHART", "--author-role", role, "--body", body]
        args += ["--room-id", target] if scope == "ROOM" else ["--patient-id", target]
        return self.ok(self.fx.hospital(*args))

    def install(self):
        for room in self.sessions:
            self.ok(self.b1("bootstrap", "--room-id", room,
                            "--session-id", self.sessions[room]))
        for tool in (self.b2, self.b4):
            self.ok(tool("install", "--room-id", ROOM_A,
                         "--session-id", self.sessions[ROOM_A]))

    def digest(self, room):
        return self.b1("context-digest", "--room-id", room,
                       "--session-id", self.sessions[room])

    def context(self, room):
        return self.fx.agent("context", self.sessions[room])

    def state(self, room):
        return (self.ok(self.fx.hospital("messages", room, "--limit", "100")),
                self.ok(self.fx.hospital(
                    "events", self.sessions[room], "--limit", "100")))

    def assert_parity(self, room):
        digest = self.ok(self.digest(room))
        actual = self.ok(self.context(room))
        def ids(rows):
            return {str(r["id"]) for r in rows}
        handoffs = actual["requiredHandoffs"]
        room_charts = actual["approvedRoomChart"]
        patient_charts = actual["approvedPatientChart"]
        self.assertEqual(set(digest["handoffIds"]), ids(handoffs))
        self.assertEqual(set(digest["chartIds"]), ids(room_charts) | ids(patient_charts))
        self.assertEqual(len(digest["handoffIds"]), len(handoffs))
        self.assertEqual(len(digest["chartIds"]), len(room_charts) + len(patient_charts))
        text = actual["renderedText"]
        for row in [*handoffs, *room_charts, *patient_charts]:
            self.assertIn(row["body"], text, "mandatory source body not delivered")
        return digest, actual

    def test_multi_room_digest_selection_matches_actual_context_and_rendered_bodies(self):
        self.handoff(ROOM_A, "A-UNIQUE-MANDATORY-HANDOFF")
        self.handoff(ROOM_B, "B-UNIQUE-MANDATORY-HANDOFF")
        self.chart("ROOM", ROOM_A, "A-UNIQUE-ROOM-CONSTRAINT")
        self.chart("ROOM", ROOM_B, "B-UNIQUE-ROOM-CONSTRAINT")
        self.chart("PATIENT", PATIENT, "SHARED-PATIENT-CONSTRAINT")
        self.chart("PATIENT", OTHER_PATIENT, "OTHER-PATIENT-CONSTRAINT")
        self.install()
        a, a_ctx = self.assert_parity(ROOM_A)
        b, b_ctx = self.assert_parity(ROOM_B)
        c, c_ctx = self.assert_parity(ROOM_C)
        self.assertEqual(len(a_ctx["approvedPatientChart"]), 1)
        self.assertEqual(len(b_ctx["approvedPatientChart"]), 1)
        self.assertEqual(len(c_ctx["approvedPatientChart"]), 1)
        self.assertNotEqual(a["contextHash"], b["contextHash"])
        self.assertNotEqual(a["contextHash"], c["contextHash"])
        self.assertNotIn("OTHER-PATIENT-CONSTRAINT", a_ctx["renderedText"])
        self.assertNotIn("A-UNIQUE-MANDATORY-HANDOFF", b_ctx["renderedText"])

    def test_boundary_twelve_handoffs_matches_both_paths(self):
        for i in range(12):
            self.handoff(ROOM_A, "B8-BOUNDARY-%02d" % i)
        self.install()
        info, agent = self.assert_parity(ROOM_A)
        self.assertEqual(len(info["handoffIds"]), 12)
        self.assertEqual(len(agent["requiredHandoffs"]), 12)

    def test_thirteen_handoffs_refuse_both_paths_with_no_turn_mutation(self):
        for i in range(13):
            self.handoff(ROOM_A, "B8-OVERFLOW-%02d" % i)
        self.install()
        before = self.state(ROOM_A)
        source = self.digest(ROOM_A)
        rendered = self.context(ROOM_A)
        self.assertNotEqual(source.returncode, 0)
        self.assertIn("TOO_MANY_MANDATORY_HANDOFFS", source.stderr)
        self.assertNotEqual(rendered.returncode, 0)
        self.assertIn("TOO_MANY_MANDATORY_HANDOFFS", rendered.stderr)
        self.assertEqual(self.state(ROOM_A), before)

    def test_foreign_patient_source_room_refuses_both_paths(self):
        entry = self.chart("PATIENT", PATIENT, "B8-FOREIGN-PROVENANCE")
        # The persistent author/source field is not authenticated; stage this
        # malformed row BEFORE installing B2/B4, then compare both read paths.
        sql = ("import json,sqlite3;"
               "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
               "uri=True);c.execute("
               "'UPDATE chart_entries SET source_room_id=? WHERE entry_id=?',"
               + repr((ROOM_C, int(entry["id"])))
               + ");c.commit();print(json.dumps(True))")
        self.ok(self.fx.run("/usr/bin/python3", "-B", "-c", sql))
        self.install()
        before = self.state(ROOM_A)
        digest = self.digest(ROOM_A)
        actual = self.context(ROOM_A)
        self.assertNotEqual(digest.returncode, 0)
        self.assertIn("FOREIGN_PATIENT_SOURCE_ROOM", digest.stderr)
        self.assertNotEqual(actual.returncode, 0)
        self.assertIn("FOREIGN_PATIENT_SOURCE_ROOM", actual.stderr)
        self.assertEqual(self.state(ROOM_A), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
