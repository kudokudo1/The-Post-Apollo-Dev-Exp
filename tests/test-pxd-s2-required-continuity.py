#!/usr/bin/env python3
"""S2 guaranteed Doctor succession context on actual PX source.

All storage is sqlite3 :memory:, no provider launch or installed PX access.
This checks delivered context + provenance, not model comprehension.
"""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(file))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


store = load("s2_hospital_store", ROOT / "bin/px-hospital-store")
agent = load("s2_px_agent", ROOT / "bin/px-agent")
p1 = load("s2_p1_fixture", ROOT / "tests/test-pxd-p1-assignment-integrity.py")


class SuccessionContextTests(unittest.TestCase):
    def setUp(self):
        self.db, ids = p1.fixture(store)
        p1.set_link(self.db, ids[0])
        self.original = agent.px_hospital
        self.addCleanup(lambda: setattr(agent, "px_hospital", self.original))
        agent.px_hospital = self.hospital
        agent.select_relevant_room_history = agent.select_relevant_room_history
        agent.collect_git_report_evidence = lambda *args: {"status": "UNAVAILABLE"}

    def hospital(self, command, *args):
        if command == "session":
            return store.session_record(self.db, args[0])
        if command == "room":
            return store.room_record(self.db, args[0])
        if command == "assignment":
            return store.assignment_record(self.db, int(args[0]))
        if command == "room-reports":
            def val(flag, default=""):
                return args[args.index(flag)+1] if flag in args else default
            return store.room_reports_list(
                self.db, args[0], int(val("--limit", "50")),
                int(val("--before-id")) if "--before-id" in args else None,
                val("--report-kind"))
        if command == "chart-entries":
            def val(flag, default=""):
                return args[args.index(flag)+1] if flag in args else default
            from types import SimpleNamespace
            return store.chart_entries_list(self.db, SimpleNamespace(
                scope=val("--scope"), patient_id=val("--patient-id"),
                room_id=val("--room-id"), entry_kind=val("--entry-kind"),
                author_role=val("--author-role"),
                status=val("--status", "ACTIVE"),
                limit=int(val("--limit", "100"))))
        if command == "messages":
            return []
        if command == "checkpoints":
            return []
        raise AssertionError("unexpected hospital command: " + command)

    def report(self, room, kind, title, body):
        cur = self.db.execute(
            "INSERT INTO room_reports(room_id, report_kind, title, body_md) "
            "VALUES (?,?,?,?)", (room, kind, title, body))
        self.db.commit()
        return str(cur.lastrowid)

    def chart(self, room, kind, title, body, priority, author="operator",
              status="ACTIVE"):
        cur = self.db.execute(
            "INSERT INTO chart_entries(scope_type, room_id, entry_kind, title, "
            "body_md, priority, status, author_role) "
            "VALUES ('ROOM',?,?,?,?,?,?,?)",
            (room, kind, title, body, priority, status, author))
        self.db.commit()
        return str(cur.lastrowid)

    def context(self, query="continue the current task"):
        return agent.live_context_payload("fresh-doctor-B", query_text=query)

    def test_old_lexically_distant_handoff_and_chart_crowding(self):
        sentinel = "Obsidian nectar choreography agreed under amber moon."
        older = self.report("A", "HANDOFF", "Earlier shift directions", sentinel)
        for i in range(40):
            self.report("A", "DOCTOR_NOTE", "continue current task "+str(i),
                        "continue current task evidence " + str(i))
        approved_text = "Operator decision: no edit; finish regression C"
        low = self.chart("A", "DECISION", "Approved prior decision",
                         approved_text, 1)
        for i in range(11):
            self.chart("A", "NOTE", "Active operator guidance "+str(i),
                       "Current preference "+str(i), 95)
        self.chart("B", "DECISION", "Foreign operator decision",
                   "TOP SECRET - OTHER ROOM", 100)
        self.report("B", "HANDOFF", "Other Room handoff",
                    "TOP SECRET - OTHER ROOM HANDOFF")
        ctx = self.context()
        rendered = agent.render_live_context(ctx)
        self.assertNotIn(older, [row["id"] for row in ctx["retrievedContext"]])
        self.assertNotIn(low, [row["id"] for row in ctx["roomChart"]])
        self.assertIn(older, [row["id"] for row in ctx["requiredHandoffs"]])
        self.assertIn(low, [row["id"] for row in ctx["approvedRoomChart"]])
        self.assertIn(sentinel, rendered)
        self.assertIn(approved_text, rendered)
        self.assertIn("ROOM_REPORT #"+older, rendered)
        self.assertIn("ROOM_CHART #"+low, rendered)
        self.assertNotIn("TOP SECRET", rendered)
        self.assertEqual(ctx["authority"]["allowed"], ["READ", "TEST"])
        self.assertEqual(ctx["session"]["providerSessionId"], "")
        summary = agent.context_summary(ctx)
        self.assertIn(older, summary["requiredHandoffRefs"])
        self.assertIn(low, summary["approvedRoomChartRefs"])

    def test_low_keyword_rank_cannot_displace_handoff(self):
        handoff = self.report("A", "HANDOFF", "Unaffiliated past report",
                              "Moss-lattice variance requires a revisit.")
        for i in range(12):
            self.report("A", "DOCTOR_NOTE", "continue current task",
                        "continue current task "+str(i))
        ctx = self.context("continue current task")
        self.assertEqual([row["id"] for row in ctx["requiredHandoffs"]],
                         [handoff])
        self.assertNotIn(handoff, [r["id"] for r in ctx["retrievedContext"]])

    def test_nonoperator_note_not_promoted_to_approved_lane(self):
        self.chart("A", "DECISION", "Unapproved draft", "Not approved yet",
                   90, author="doctor")
        ctx = self.context()
        self.assertEqual(ctx["approvedRoomChart"], [])

    def test_resolved_decision_not_in_active_lane(self):
        self.chart("A", "DECISION", "Archived decision", "No longer active",
                   90, status="RESOLVED")
        self.assertEqual(self.context()["approvedRoomChart"], [])

    def test_too_many_handoffs_explicitly_refused(self):
        for i in range(agent.REQUIRED_HANDOFF_LIMIT+1):
            self.report("A", "HANDOFF", "Shift "+str(i), "Required handoff")
        with self.assertRaisesRegex(RuntimeError, "TOO_MANY_MANDATORY_HANDOFFS"):
            self.context()

    def test_too_many_operator_charts_explicitly_refused(self):
        for i in range(agent.APPROVED_ROOM_CHART_LIMIT+1):
            self.chart("A", "DECISION", "Approved "+str(i), "Required decision", 5)
        with self.assertRaisesRegex(RuntimeError, "TOO_MANY_APPROVED_ROOM_CHARTS"):
            self.context()

    def test_long_required_body_explicitly_refused_not_clipped(self):
        self.report("A", "HANDOFF", "Required large packet", "x" * 1900)
        with self.assertRaisesRegex(RuntimeError, "OVERSIZED_REQUIRED_RECORD"):
            self.context()

    def test_invalid_cross_room_store_record_refused(self):
        original = agent.px_hospital
        def tampered(command, *args):
            if command == "room-reports" and "--report-kind" in args:
                return [{"id":"777","roomId":"B","kind":"HANDOFF",
                         "title":"Foreign","body":"foreign-only confidential"}]
            return original(command, *args)
        agent.px_hospital = tampered
        with self.assertRaisesRegex(RuntimeError, "FOREIGN_ROOM_RECORD"):
            self.context()

    def test_store_filters_old_handoff_not_just_newest_thirty(self):
        older = self.report("A", "HANDOFF", "Old", "required evidence")
        for i in range(40):
            self.report("A", "DOCTOR_NOTE", "New "+str(i), "ordinary")
        result = self.hospital("room-reports", "A", "--report-kind", "HANDOFF",
                               "--limit", "13")
        self.assertEqual([x["id"] for x in result], [older])

    def test_legacy_mixed_case_handoffs_deliver_despite_old_age(self):
        # Simulate records written by older installations before write
        # normalization: keep their raw SQLite report_kind values intact.
        handoffs = {}
        for kind in ("handoff", "Handoff", "  hAnDoFf  "):
            handoffs[kind] = self.report(
                "A", kind, "Older handoff " + kind,
                "Required knowledge for " + kind
            )
        self.report("B", "handoff", "Other Room",
                    "FOREIGN ROOM ONLY SOURCE")
        for i in range(40):
            self.report("A", "DOCTOR_NOTE",
                        "irrelevant recent " + str(i), "ordinary message")
        ctx = self.context("unrelated question")
        ids = {row["id"] for row in ctx["requiredHandoffs"]}
        self.assertEqual(ids, set(handoffs.values()))
        rendered = agent.render_live_context(ctx)
        for kind, item_id in handoffs.items():
            self.assertIn("ROOM_REPORT #" + item_id, rendered, kind)
            self.assertIn("Required knowledge for " + kind, rendered)
        self.assertNotIn("FOREIGN ROOM ONLY SOURCE", rendered)
        self.assertTrue(all(
            row["kind"] == "HANDOFF" for row in ctx["requiredHandoffs"]
        ))

    def test_legacy_kind_query_is_case_insensitive(self):
        for kind in ("handoff", "Handoff", "HANDOFF", " handoff "):
            self.report("A", kind, "Prior shift", "Mandatory payload")
        self.report("A", "DOCTOR_NOTE", "Not mandatory", "ordinary")
        low = store.room_reports_list(self.db, "A", 13, None, "handoff")
        upper = store.room_reports_list(self.db, "A", 13, None, "HANDOFF")
        self.assertEqual([row["id"] for row in low],
                         [row["id"] for row in upper])
        self.assertEqual(len(upper), 4)

    def test_required_text_fully_rendered_below_limit(self):
        body = "a" * 1700
        self.report("A", "HANDOFF", "Brief", body)
        ctx = self.context()
        self.assertIn(body, agent.render_live_context(ctx))


if __name__ == "__main__":
    unittest.main()
