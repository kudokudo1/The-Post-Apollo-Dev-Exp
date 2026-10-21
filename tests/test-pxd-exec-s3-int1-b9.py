#!/usr/bin/env python3
"""INT1-B9: idle synthetic broker OS-readiness and failure cleanup probes.

All processes execute in the accepted disposable Bubblewrap fixture. There is
no real credential, Hospital production DB, model, tool or broker dispatch.
"""
import json
from pathlib import Path
import unittest

from px_int1_fixture import DisposablePX

REPO = Path(__file__).resolve().parents[1]
ROOM = "B9-ROOM"
SESSION = "b9-session"
FAKE = {"version": 1, "providers": {
    "int1-fake": {"name": "INT1 FAKE", "executionProfile": "EXEC_S3_FAKE_ONLY",
                  "dialect": "exec-s3-fake-only"}
}}


class B9IdleBrokerTests(unittest.TestCase):
    def setUp(self):
        self.fx = DisposablePX(REPO)
        self.addCleanup(self.fx.close)
        registry = self.fx.root / "providers/fake.json"
        registry.write_text(json.dumps(FAKE))
        registry.chmod(0o600)
        self.assertTrue(self.fx.assert_safe_environment())
        self.ok(self.fx.hospital("init"))
        self.ok(self.fx.hospital(
            "room-bind", ROOM, "--repository", "kudokudo1/taskbars-post-apollo",
            "--patient-id", "B9-SYNTHETIC-PATIENT", "--team", "B9",
            "--branch", "b9", "--bed-path", "/fixture/bed",
            "--doctor-id", "B9-DOCTOR",
        ))
        self.ok(self.fx.hospital(
            "session-put", SESSION, "--room-id", ROOM,
            "--doctor-id", "B9-DOCTOR", "--provider-id", "int1-fake",
            "--status", "IDLE",
        ))
        self.ok(self.fx.hospital(
            "session-runtime", SESSION, "--working-directory", "/fixture/bed",
            "--status", "IDLE",
        ))
        assignment = self.ok(self.fx.hospital(
            "assignment-create", "--room-id", ROOM,
            "--title", "B9 fake readiness", "--goal", "No actual execution",
            "--permissions-json", '["READ","EDIT"]',
        ))
        self.ok(self.fx.hospital("assignment-activate", assignment["id"]))
        self.ok(self.b1("bootstrap", "--room-id", ROOM, "--session-id", SESSION))
        self.ok(self.b2("install", "--room-id", ROOM, "--session-id", SESSION))
        self.ok(self.b4("install", "--room-id", ROOM, "--session-id", SESSION))
        self.ok(self.b1("context-digest", "--room-id", ROOM, "--session-id", SESSION))

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def run_module(self, module, *args):
        return self.fx.run(
            "/usr/bin/python3", "-B", module, *args, timeout=25,
        )

    def b1(self, *args):
        return self.run_module("/source/bin/px_int1_fake_atomic.py", *args)

    def b2(self, *args):
        return self.run_module("/source/bin/px_int1_fake_epoch.py", *args)

    def b4(self, *args):
        return self.run_module("/source/bin/px_int1_fake_continuity.py", *args)

    def probe(self, *options):
        return self.run_module(
            "/source/bin/px_int1_fake_broker.py",
            "probe", "--room-id", ROOM, "--session-id", SESSION, *options,
        )

    def count(self):
        script = ("import sqlite3,json;"
                  "db=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=ro',"
                  "uri=True);print(json.dumps(db.execute("
                  "'SELECT COUNT(*) FROM int1_fake_accepted_turns').fetchone()[0]))")
        return self.ok(self.fx.run("/usr/bin/python3", "-B", "-c", script))

    def state(self):
        return (self.ok(self.fx.hospital("messages", ROOM, "--limit", "100")),
                self.ok(self.fx.hospital("events", SESSION, "--limit", "100")),
                self.ok(self.fx.hospital("session", SESSION)),
                self.count())

    def assert_denied_unchanged(self, *args, expected=None):
        before = self.state()
        result = self.probe(*args)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        if expected:
            self.assertIn(expected, result.stderr)
        self.assertEqual(before, self.state())
        return result

    def test_ready_broker_has_kernel_observed_isolation_and_is_reaped(self):
        old = self.state()
        result = self.ok(self.probe())
        self.assertEqual(result["state"], "IDLE_BROKER_PROBED_AND_REAPED")
        self.assertTrue(result["readinessObservedByOS"])
        self.assertTrue(result["brokerStarted"])
        self.assertTrue(result["brokerReaped"])
        self.assertFalse(result["productionReady"])
        for key in ("messagesAccepted", "eventsAccepted",
                    "modelCalls", "toolCalls", "dispatches"):
            self.assertEqual(result[key], 0, key)
        os_evidence = result["osEvidence"]
        self.assertEqual(set(os_evidence["namespaces"]), {
            "mnt", "net", "pid", "ipc", "user",
        })
        self.assertEqual(os_evidence["childFds"], [0, 1, 2])
        self.assertEqual(set(os_evidence["childEnvironmentKeys"]), {
            "PATH", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE",
        })
        self.assertEqual(old, self.state())

    def test_early_exit_fails_closed_without_turn_records(self):
        self.assert_denied_unchanged("--scenario", "early-exit")

    def test_malformed_readiness_fails_closed_without_turn_records(self):
        self.assert_denied_unchanged(
            "--scenario", "malformed", expected="broker readiness mismatch",
        )

    def test_readiness_timeout_fails_closed_without_turn_records(self):
        self.assert_denied_unchanged(
            "--scenario", "timeout", "--timeout", "0.2",
            expected="readiness deadline exceeded",
        )

    def test_revocation_after_readiness_prevents_positive_result(self):
        before = self.state()
        result = self.probe("--test-revoke-at-readiness")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("authority revoked", result.stderr)
        self.assertEqual(before, self.state())
        inspect = self.ok(self.b4("inspect", "--room-id", ROOM))
        self.assertTrue(inspect["revoked"])

    def test_missing_continuity_hook_refuses_before_broker_start(self):
        script = ("import sqlite3,json;"
                  "db=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
                  "uri=True);db.execute('DROP TRIGGER int1_b4_handoff_update_v1');"
                  "db.commit();print(json.dumps(True))")
        self.ok(self.fx.run("/usr/bin/python3", "-B", "-c", script))
        self.assert_denied_unchanged(
            expected="missing or unexpected continuity hooks",
        )

    def test_command_bearing_registry_refuses_before_broker_start(self):
        registry = self.fx.root / "providers/fake.json"
        hostile = json.loads(json.dumps(FAKE))
        hostile["providers"]["int1-fake"]["command"] = "/usr/bin/true"
        registry.write_text(json.dumps(hostile))
        registry.chmod(0o600)
        self.assert_denied_unchanged(expected="unsupported synthetic-only provider")


if __name__ == "__main__":
    unittest.main(verbosity=2)
