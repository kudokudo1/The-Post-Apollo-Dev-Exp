#!/usr/bin/env python3
"""P1 provider-boundary verification on real PX source and disposable Git/DB.

Never launches a provider: outgoing message append is intercepted before any
spawn, and no live Hospital state or installed PX files are accessed.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))


def load(name, filename):
    loader = importlib.machinery.SourceFileLoader(name, str(filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


store = load("p1_boundary_store", ROOT / "bin/px-hospital-store")
agent = load("p1_boundary_agent", ROOT / "bin/px-agent")
source_fixture = load(
    "p1_nurse2_source_fixture", ROOT / "tests/test-pxd-p1-assignment-integrity.py"
)


def git(path, *args):
    subprocess.check_output(
        ["git", "-C", str(path), *args],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


class P1DispatchBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bed = Path(self.temp.name) / "bed"
        self.bed.mkdir()
        git(self.bed, "init", "-q")
        git(self.bed, "config", "user.email", "hospital@example.invalid")
        git(self.bed, "config", "user.name", "Hospital test")
        (self.bed / "tracked.txt").write_text("hello\n")
        git(self.bed, "add", "tracked.txt")
        git(self.bed, "commit", "-qm", "baseline")
        git(self.bed, "checkout", "-qb", "feature/a")
        git(self.bed, "remote", "add", "origin",
            "https://github.com/test/repo.git")
        self.db, self.ids = source_fixture.fixture(store)
        self.db.execute(
            "UPDATE rooms SET bed_path = ?, branch = ? WHERE room_id = 'A'",
            (str(self.bed), "feature/a")
        )
        self.db.commit()
        self.appends = []
        self.issued_context = []
        self.env_calls = []

        def fake_hospital(command, *values, **kwargs):
            if command == "session":
                return store.session_record(self.db, values[0])
            if command == "room":
                return store.room_record(self.db, values[0])
            if command == "assignment":
                return store.assignment_record(self.db, int(values[0]))
            if command in (
                    "chart-entries", "messages", "checkpoints", "room-reports"
            ):
                return []
            if command == "message-append":
                self.appends.append((values, kwargs))
                raise RuntimeError("P1_TEST_MESSAGE_APPEND_BOUNDARY")
            raise AssertionError("Unexpected PX Hospital command: " + command)

        def fake_env(session_id, assignment):
            self.env_calls.append(assignment)
            return {}, {"allowed": ["READ"]}

        agent.px_hospital = fake_hospital
        agent.provider_record = lambda provider_id: {
            "command": "python3", "dialect": "hermes-stream-json",
            "startArgs": ["chat"], "resumeArgs": ["chat"]
        }
        agent.resolve_command = lambda command: sys.executable
        agent.select_relevant_room_history = lambda *args: []
        agent.collect_git_report_evidence = lambda *args: {"status":"UNAVAILABLE"}
        agent.provider_prompt_for_turn = lambda prompt, context, extra: (
            self.issued_context.append(context) or prompt
        )
        agent.provider_authority_environment = fake_env

    def args(self):
        return SimpleNamespace(
            session_id="fresh-doctor-B",
            working_directory=str(self.bed),
            prompt_json_stdin=False, prompt_stdin=False,
            prompt="test safety", author_id="operator", message_type="chat",
            supplemental_context=""
        )

    def set_link(self, link):
        source_fixture.set_link(self.db, link)

    def assert_blocked(self, link, code):
        self.set_link(link)
        with self.assertRaisesRegex(RuntimeError, code):
            agent._run_turn_unlocked(self.args())
        self.assertEqual(self.appends, [],
                         "Invalid link must not persist an outgoing message")
        self.assertEqual(self.env_calls, [],
                         "Invalid link must not construct provider environment")
        self.assertEqual(self.issued_context, [],
                         "Invalid link must not construct provider prompt")

    def test_foreign_active_blocked_before_message(self):
        self.assert_blocked(self.ids[1], "FOREIGN_ROOM")

    def test_paused_link_blocked_before_message(self):
        self.assert_blocked(self.ids[2], "NONACTIVE_LINK")

    def test_dangling_link_blocked_before_message(self):
        self.assert_blocked(999999, "MISSING_ASSIGNMENT")

    def test_invalid_link_blocked_before_message(self):
        self.assert_blocked("abc", "INVALID_LINK_ID")

    def test_valid_active_room_reaches_append_not_provider(self):
        self.set_link(self.ids[0])
        with self.assertRaisesRegex(RuntimeError, "P1_TEST_MESSAGE_APPEND_BOUNDARY"):
            agent._run_turn_unlocked(self.args())
        self.assertEqual(len(self.appends), 1)
        self.assertEqual(len(self.env_calls), 1)
        self.assertEqual(str(self.env_calls[0]["roomId"]), "A")
        self.assertEqual(self.issued_context[0]["room"]["id"], "A")

    def test_genuinely_unassigned_reaches_append_read_only(self):
        self.set_link(None)
        with self.assertRaisesRegex(RuntimeError, "P1_TEST_MESSAGE_APPEND_BOUNDARY"):
            agent._run_turn_unlocked(self.args())
        self.assertEqual(len(self.appends), 1)
        self.assertEqual(self.env_calls[0], {})
        self.assertEqual(self.issued_context[0]["authority"]["allowed"], ["READ"])


if __name__ == "__main__":
    unittest.main()
