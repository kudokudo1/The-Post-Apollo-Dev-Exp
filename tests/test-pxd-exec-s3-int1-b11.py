#!/usr/bin/env python3
"""B11: isolated one-shot inert frame after B1 atomic acceptance.

Fake-only disposable Bubblewrap fixture. No real model, shell tool or live DB.
"""
import json
from pathlib import Path
import unittest

from px_int1_fixture import DisposablePX

REPO = Path(__file__).resolve().parents[1]
ROOM = "B11-ROOM"
SESSION = "b11-session"
FAKE = {"version": 1, "providers": {
    "int1-fake": {"name": "INT1 FAKE", "executionProfile": "EXEC_S3_FAKE_ONLY",
                  "dialect": "exec-s3-fake-only"}
}}


class B11DispatchTests(unittest.TestCase):
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
            "--patient-id", "B11-PATIENT", "--team", "B11",
            "--branch", "b11", "--bed-path", "/fixture/bed",
            "--doctor-id", "B11-DOCTOR",
        ))
        self.ok(self.fx.hospital(
            "session-put", SESSION, "--room-id", ROOM,
            "--doctor-id", "B11-DOCTOR", "--provider-id", "int1-fake",
            "--status", "IDLE",
        ))
        self.ok(self.fx.hospital(
            "session-runtime", SESSION, "--working-directory", "/fixture/bed",
            "--status", "IDLE",
        ))
        assignment = self.ok(self.fx.hospital(
            "assignment-create", "--room-id", ROOM, "--title", "B11 disposable",
            "--goal", "inert synthetic frame only",
            "--permissions-json", '["READ","EDIT"]',
        ))
        self.ok(self.fx.hospital("assignment-activate", assignment["id"]))
        self.ok(self.b1("bootstrap", "--room-id", ROOM, "--session-id", SESSION))
        self.ok(self.b2("install", "--room-id", ROOM, "--session-id", SESSION))
        self.ok(self.b4("install", "--room-id", ROOM, "--session-id", SESSION))

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def run_source(self, path, *args, input=None):
        return self.fx.run("/usr/bin/python3", "-B", path, *args,
                           input=input, timeout=30)

    def b1(self, *args):
        return self.run_source("/source/bin/px_int1_fake_atomic.py", *args)

    def b2(self, *args):
        return self.run_source("/source/bin/px_int1_fake_epoch.py", *args)

    def b4(self, *args):
        return self.run_source("/source/bin/px_int1_fake_continuity.py", *args)

    def dispatch(self, turn, *opts):
        return self.run_source(
            "/source/bin/px_int1_fake_dispatch.py",
            "--room-id", ROOM, "--session-id", SESSION,
            "--turn-id", turn, "--body-stdin", *opts,
            input="NO REAL PROVIDER OR TOOL EXECUTION",
        )

    def recovery(self, command, turn, *options):
        return self.run_source(
            "/source/bin/px_int1_fake_recovery.py",
            command, "--room-id", ROOM, "--session-id", SESSION,
            "--turn-id", turn, *options,
        )

    def close_uncertain(self, turn, *, acknowledgment="I_ACKNOWLEDGE_UNKNOWN_DELIVERY_AND_NO_RETRY",
                        reason="Synthetic supervisor crashed after reservation"):
        return self.recovery(
            "resolve-uncertain", turn,
            "--acknowledge", acknowledgment, "--reason", reason,
        )

    def database(self):
        code = (
            "import json,sqlite3;"
            "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=ro',"
            "uri=True);"
            "print(json.dumps({'turns':[list(x) for x in c.execute("
            "'SELECT turn_id,state FROM int1_fake_accepted_turns ORDER BY turn_id')],"
            "'receipts':[list(x) for x in c.execute("
            "'SELECT turn_id,state,result FROM int1_fake_dispatch_receipts ORDER BY turn_id')]"
            "}))"
        )
        return self.ok(self.fx.run("/usr/bin/python3", "-B", "-c", code))

    def recovery_events(self):
        script = (
            "import sqlite3,json;"
            "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=ro',"
            "uri=True);print(json.dumps(c.execute("
            "'SELECT COUNT(*) FROM session_events WHERE event_type=?',"
            "('turn.dispatch.manual-uncertain-failure',)).fetchone()[0]))"
        )
        return self.ok(self.fx.run("/usr/bin/python3", "-B", "-c", script))

    def messages(self):
        return (self.ok(self.fx.hospital("messages", ROOM, "--limit", "100")),
                self.ok(self.fx.hospital("events", SESSION, "--limit", "100")))

    def test_b11_success_one_fixed_noop_has_receipt_without_model_or_tool(self):
        old = self.messages()
        result = self.ok(self.dispatch("b11-success"))
        self.assertEqual(result["state"], "SYNTHETIC_NOOP_ACKED")
        self.assertEqual(result["syntheticFrames"], 1)
        self.assertTrue(result["brokerOsObserved"])
        self.assertTrue(result["brokerReaped"])
        for key in ("modelCalls", "toolCalls"):
            self.assertEqual(result[key], 0)
        self.assertEqual(self.database(), {
            "turns": [["b11-success", "ACCEPTED_UNDISPATCHED"]],
            "receipts": [["b11-success", "ACKED", "SYNTHETIC_NOOP"]],
        })
        self.assertNotEqual(self.messages(), old)
        before_retry = self.database(), self.messages()
        retry = self.dispatch("b11-success")
        self.assertNotEqual(retry.returncode, 0)
        self.assertIn("no automatic turn replay", retry.stderr)
        self.assertEqual((self.database(), self.messages()), before_retry)

    def test_b11_early_exit_has_no_persisted_turn(self):
        old = self.messages()
        result = self.dispatch("b11-exit", "--scenario", "early-exit")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(old, self.messages())

    def test_b11_revoked_after_reservation_fails_and_cannot_replay(self):
        result = self.dispatch("b11-revoke", "--test-revoke-before-dispatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stale or revoked authority", result.stderr)
        self.assertEqual(self.database(), {
            "turns": [["b11-revoke", "FAILED"]],
            "receipts": [["b11-revoke", "FAILED", ""]],
        })
        self.assertNotEqual(self.dispatch("b11-revoke").returncode, 0)

    def test_b11_wrong_ack_keeps_accepted_turn_failed_not_deleted(self):
        result = self.dispatch("b11-wrong", "--scenario", "gated-malformed-ack")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broker ACK mismatch", result.stderr)
        self.assertEqual(self.database(), {
            "turns": [["b11-wrong", "FAILED"]],
            "receipts": [["b11-wrong", "FAILED", ""]],
        })
        self.assertNotEqual(self.dispatch("b11-wrong").returncode, 0)

    def test_b11_ack_timeout_keeps_failed_acceptance(self):
        result = self.dispatch("b11-timeout", "--scenario", "gated-timeout-ack")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broker ACK deadline exceeded", result.stderr)
        self.assertEqual(self.database(), {
            "turns": [["b11-timeout", "FAILED"]],
            "receipts": [["b11-timeout", "FAILED", ""]],
        })

    def test_b11_missing_continuity_hook_refuses_before_acceptance(self):
        cmd = (
            "import sqlite3;"
            "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
            "uri=True);c.execute('DROP TRIGGER int1_b4_handoff_update_v1');"
            "c.commit()"
        )
        self.ok_no_output(self.fx.run("/usr/bin/python3", "-B", "-c", cmd))
        before = self.messages()
        result = self.dispatch("b11-hook")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing or unexpected continuity hooks", result.stderr)
        self.assertEqual(before, self.messages())

    def ok_no_output(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_b12_crash_preserves_reserved_receipt_then_manual_no_retry(self):
        crashed = self.dispatch("b12-crash", "--test-crash-after-reserve")
        self.assertEqual(crashed.returncode, 77, crashed.stderr)
        self.assertEqual(self.database(), {
            "turns": [["b12-crash", "ACCEPTED_UNDISPATCHED"]],
            "receipts": [["b12-crash", "RESERVED", ""]],
        })
        snapshot = self.ok(self.recovery("inspect", "b12-crash"))
        self.assertTrue(snapshot["requiresExplicitRecovery"])
        self.assertFalse(snapshot["deliveryKnown"])
        self.assertFalse(snapshot["automaticRetryAllowed"])
        self.assertFalse(snapshot["workerTerminationVerified"])
        before = self.database(), self.messages()
        refused = self.dispatch("b12-crash")
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(before, (self.database(), self.messages()))
        closed = self.ok(self.close_uncertain("b12-crash"))
        self.assertEqual(closed["state"], "FAILED_UNCERTAIN_DELIVERY")
        self.assertFalse(closed["automaticRetryAllowed"])
        self.assertTrue(closed["auditEventWritten"])
        self.assertEqual(self.database(), {
            "turns": [["b12-crash", "FAILED"]],
            "receipts": [["b12-crash", "FAILED", "MANUAL_UNCERTAIN_DELIVERY_NO_RETRY"]],
        })
        post = self.ok(self.recovery("inspect", "b12-crash"))
        self.assertFalse(post["requiresExplicitRecovery"])
        self.assertNotEqual(self.dispatch("b12-crash").returncode, 0)
        old = self.database(), self.messages()
        repeated = self.close_uncertain("b12-crash")
        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("only unresolved RESERVED", repeated.stderr)
        self.assertEqual(old, (self.database(), self.messages()))
        self.assertEqual(self.recovery_events(), 1)

    def test_b12_missing_acknowledgment_or_reason_does_not_mutate_reservation(self):
        crashed = self.dispatch("b12-unconfirmed", "--test-crash-after-reserve")
        self.assertEqual(crashed.returncode, 77)
        before = self.database(), self.messages()
        invalid = self.close_uncertain("b12-unconfirmed", acknowledgment="YES")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("explicit no-retry acknowledgment", invalid.stderr)
        invalid_reason = self.close_uncertain("b12-unconfirmed", reason=" ")
        self.assertNotEqual(invalid_reason.returncode, 0)
        self.assertIn("bounded operator reason", invalid_reason.stderr)
        self.assertEqual(before, (self.database(), self.messages()))

    def test_b12_recovery_allowed_after_authority_revocation(self):
        crashed = self.dispatch("b12-revoked", "--test-crash-after-reserve")
        self.assertEqual(crashed.returncode, 77)
        self.ok(self.b1("revoke", "--room-id", ROOM,
                        "--reason", "B12 synthetic authority revoked"))
        result = self.ok(self.close_uncertain("b12-revoked"))
        self.assertEqual(result["state"], "FAILED_UNCERTAIN_DELIVERY")
        self.assertEqual(self.database()["receipts"], [
            ["b12-revoked", "FAILED", "MANUAL_UNCERTAIN_DELIVERY_NO_RETRY"]
        ])

    def test_b12_acked_receipt_cannot_be_rewritten(self):
        self.ok(self.dispatch("b12-acked"))
        before = self.database(), self.messages()
        res = self.close_uncertain("b12-acked")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("only unresolved RESERVED", res.stderr)
        self.assertEqual(before, (self.database(), self.messages()))

    def test_b12_corrupted_hook_blocks_manual_recovery(self):
        crashed = self.dispatch("b12-hook-loss", "--test-crash-after-reserve")
        self.assertEqual(crashed.returncode, 77)
        query = (
            "import sqlite3;"
            "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=rw',"
            "uri=True);c.execute('DROP TRIGGER int1_b4_handoff_update_v1');"
            "c.commit()"
        )
        self.ok_no_output(self.fx.run("/usr/bin/python3", "-B", "-c", query))
        before = self.database(), self.messages()
        result = self.close_uncertain("b12-hook-loss")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing or unexpected continuity hooks", result.stderr)
        self.assertEqual(before, (self.database(), self.messages()))



if __name__ == "__main__":
    unittest.main(verbosity=2)
