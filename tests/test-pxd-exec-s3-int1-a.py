#!/usr/bin/env python3
"""INT1-A: actual PX turn preflight, NEVER an accepted/started Doctor turn.

Tests run inside the accepted INT1-P1 Bubblewrap fixture. No real providers,
no host repository execution, no live Hospital and no production writes.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from px_int1_fixture import DisposablePX

REPO = Path(__file__).resolve().parents[1]
FAKE = {"version": 1, "providers": {
    "int1-fake": {"name": "INT1 FAKE", "executionProfile": "EXEC_S3_FAKE_ONLY",
                  "dialect": "exec-s3-fake-only"}
}}

class INT1AActualAgentTests(unittest.TestCase):
    def setUp(self):
        self.fx = DisposablePX(REPO)
        self.addCleanup(self.fx.close)
        registry = self.fx.root / "providers/fake.json"
        registry.write_text(json.dumps(FAKE))
        registry.chmod(0o600)
        self.assertTrue(self.fx.assert_safe_environment())
        for command in (
            ("/usr/bin/git", "-C", "/fixture/bed", "init", "-q"),
            ("/usr/bin/git", "-C", "/fixture/bed", "add", "tracked.txt"),
            ("/usr/bin/git", "-C", "/fixture/bed", "-c", "user.name=Fixture",
             "-c", "user.email=fixture@example.invalid", "commit", "-qm", "baseline"),
            ("/usr/bin/git", "-C", "/fixture/bed", "checkout", "-qb", "s3-fake"),
            ("/usr/bin/git", "-C", "/fixture/bed", "remote", "add",
             "origin", "https://github.com/kudokudo1/taskbars-post-apollo.git"),
        ):
            if "add" in command and "tracked.txt" in command:
                (self.fx.root / "bed/tracked.txt").write_text("fake-only\n")
            run = self.fx.run(*command)
            self.assertEqual(run.returncode, 0, (command, run.stderr))
        self.ok(self.fx.hospital("init"))
        self.ok(self.fx.hospital(
            "room-bind", "S3-INT1",
            "--repository", "kudokudo1/taskbars-post-apollo",
            "--patient-id", "S3-SYNTHETIC-PATIENT",
            "--patient-label", "OFFLINE",
            "--team", "S3-INT1", "--branch", "s3-fake",
            "--bed-path", "/fixture/bed", "--doctor-id", "S3-FAKE-DOCTOR",
        ))
        self.ok(self.fx.agent(
            "session-create",
            "--room-id", "S3-INT1", "--doctor-id", "S3-FAKE-DOCTOR",
            "--provider-id", "int1-fake", "--working-directory", "/fixture/bed",
            "--session-id", "int1-fake-session",
        ))

    def ok(self, response):
        self.assertEqual(response.returncode, 0, response.stderr)
        return json.loads(response.stdout)

    def before(self):
        return (
            self.ok(self.fx.hospital("messages", "S3-INT1", "--limit", "100")),
            self.ok(self.fx.hospital("events", "int1-fake-session", "--limit", "100")),
            self.ok(self.fx.hospital("session", "int1-fake-session")),
        )

    def assert_no_turn_mutation(self, old):
        new = self.before()
        self.assertEqual(new, old, "Stage A must not persist or change runtime identity")

    def test_valid_actual_agent_preflight_keeps_messages_events_and_session_intact(self):
        self.ok(self.fx.hospital(
            "chart-entry-add", "--scope", "PATIENT",
            "--patient-id", "S3-SYNTHETIC-PATIENT", "--entry-kind", "INVARIANT",
            "--title", "Patient scope", "--author-role", "operator",
            "--author-id", "operator", "--body-stdin", input="MANDATORY PATIENT CONTINUITY",
        ))
        self.ok(self.fx.hospital(
            "chart-entry-add", "--scope", "ROOM", "--room-id", "S3-INT1",
            "--entry-kind", "CONSTRAINT", "--title", "Room scope",
            "--author-role", "operator", "--author-id", "operator",
            "--body-stdin", input="MANDATORY ROOM CONTINUITY",
        ))
        self.ok(self.fx.hospital(
            "room-report-append", "--room-id", "S3-INT1", "--session-id",
            "int1-fake-session", "--report-kind", "HANDOFF",
            "--title", "Synthetic handoff", "--git-evidence-status", "UNAVAILABLE",
            "--body-stdin", input="MANDATORY HANDOFF CONTINUITY",
        ))
        original = self.before()
        result = self.ok(self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--prompt", "offline fixture context", "--timeout", "10",
        ))
        self.assertEqual(result["state"], "PREFLIGHT_ONLY")
        self.assertEqual(result["profile"], "EXEC_S3_FAKE_ONLY")
        self.assertEqual(result["messagesAccepted"], 0)
        self.assertEqual(result["eventsAccepted"], 0)
        self.assertFalse(result["brokerStarted"])
        self.assertFalse(result["productionReady"])
        self.assertEqual(result["modelCalls"], 0)
        self.assertEqual(result["toolCalls"], 0)
        for field in ("requiredHandoffIds", "approvedRoomChartIds",
                      "approvedPatientChartIds"):
            self.assertEqual(len(result[field]), 1, field)
        self.assert_no_turn_mutation(original)

    def test_fake_provider_requires_explicit_preflight_flag(self):
        original = self.before()
        result = self.fx.agent("turn", "int1-fake-session", "--prompt", "NO LAUNCH")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit fake-only preflight required", result.stderr)
        self.assert_no_turn_mutation(original)

    def test_fake_preflight_rejects_native_provider_id_without_launch(self):
        self.ok(self.fx.hospital(
            "session-put", "native-session", "--room-id", "S3-INT1",
            "--doctor-id", "S3-FAKE-DOCTOR", "--provider-id", "codex",
            "--status", "IDLE",
        ))
        self.ok(self.fx.hospital(
            "session-runtime", "native-session", "--working-directory",
            "/fixture/bed", "--status", "IDLE",
        ))
        original = self.before()
        result = self.fx.agent(
            "turn", "native-session", "--exec-s3-fake-preflight",
            "--prompt", "NO NATIVE PROVIDER",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_turn_mutation(original)

    def test_fake_registry_command_injection_refused_before_persistence(self):
        registry = self.fx.root / "providers/fake.json"
        hostile = json.loads(json.dumps(FAKE))
        hostile["providers"]["int1-fake"]["command"] = "/usr/bin/true"
        registry.write_text(json.dumps(hostile))
        registry.chmod(0o600)
        original = self.before()
        result = self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--prompt", "NO EXECUTE",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported synthetic-only provider", result.stderr)
        self.assert_no_turn_mutation(original)

    def test_wrong_bed_override_refused_before_persistence(self):
        original = self.before()
        result = self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--working-directory", "/fixture/home", "--prompt", "NO FOREIGN BED",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("synthetic Bed outside disposable fixture", result.stderr)
        self.assert_no_turn_mutation(original)

if __name__ == "__main__":
    unittest.main(verbosity=2)
