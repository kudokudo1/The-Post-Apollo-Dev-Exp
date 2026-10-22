#!/usr/bin/env python3
"""B11: isolated one-shot inert frame after B1 atomic acceptance.

Fake-only disposable Bubblewrap fixture. No real model, shell tool or live DB.
"""
import json
import concurrent.futures
import time
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

    def receipt_table_exists(self):
        code = (
            "import sqlite3,json;"
            "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=ro',"
            "uri=True);print(json.dumps(bool(c.execute("
            "'SELECT 1 FROM sqlite_master WHERE type=? AND name=?',"
            "('table','int1_fake_dispatch_receipts')).fetchone())))"
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


    def test_b13_fixed_eight_step_task_has_expected_persisted_result(self):
        before = self.messages()
        result = self.ok(self.dispatch("b13-task", "--task", "SUM_1_TO_8",
                                       "--scenario", "gated-task"))
        self.assertEqual(result["state"], "SYNTHETIC_TASK_ACKED")
        self.assertEqual(result["taskResult"], "SYNTHETIC_SUM_36")
        self.assertEqual(result["syntheticFrames"], 1)
        self.assertEqual(result["modelCalls"], 0)
        self.assertEqual(result["toolCalls"], 0)
        self.assertEqual(self.database(), {
            "turns": [["b13-task", "ACCEPTED_UNDISPATCHED"]],
            "receipts": [["b13-task", "ACKED", "SYNTHETIC_SUM_36"]],
        })
        self.assertNotEqual(self.messages(), before)
        snapshot = (self.database(), self.messages())
        self.assertNotEqual(self.dispatch("b13-task", "--task", "SUM_1_TO_8",
                                          "--scenario", "gated-task").returncode, 0)
        self.assertEqual(snapshot, (self.database(), self.messages()))

    def test_b13_forked_synthetic_descendant_terminated_after_success(self):
        result = self.ok(self.dispatch("b13-tree-ok", "--task", "SUM_1_TO_8",
                                       "--scenario", "gated-tree"))
        self.assertEqual(result["taskResult"], "SYNTHETIC_SUM_36")
        self.assertTrue(result["descendantTerminationVerified"])
        self.assertTrue(result["brokerReaped"])
        self.assertEqual(self.database()["receipts"], [
            ["b13-tree-ok", "ACKED", "SYNTHETIC_SUM_36"]
        ])

    def test_b13_timeout_kills_forked_process_tree_and_marks_failed(self):
        result = self.dispatch("b13-tree-timeout", "--task", "SUM_1_TO_8",
                               "--scenario", "gated-tree-timeout")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        # If a descendant survived the cleanup, the verifier overrides this
        # timeout with a distinct process-tree-survival refusal.
        self.assertIn("broker ACK deadline exceeded", result.stderr)
        self.assertNotIn("descendant survived", result.stderr)
        self.assertEqual(self.database()["receipts"], [
            ["b13-tree-timeout", "FAILED", ""]
        ])
        self.assertEqual(self.database()["turns"], [
            ["b13-tree-timeout", "FAILED"]
        ])
        self.assertNotEqual(self.dispatch("b13-tree-timeout", "--task", "SUM_1_TO_8",
                                          "--scenario", "gated-task").returncode, 0)

    def test_b13_task_scenario_mismatch_refuses_before_storage_or_child(self):
        before = self.messages()
        self.assertFalse(self.receipt_table_exists())
        denied = self.dispatch("b13-wrong", "--task", "SUM_1_TO_8",
                               "--scenario", "gated")
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("task/scenario mismatch", denied.stderr)
        self.assertEqual(before, self.messages())
        self.assertFalse(self.receipt_table_exists())

    def test_b13_arbitrary_task_name_is_not_supported(self):
        before = self.messages()
        self.assertFalse(self.receipt_table_exists())
        denied = self.dispatch("b13-shell", "--task", "SHELL",
                               "--scenario", "gated-task")
        self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(before, self.messages())
        self.assertFalse(self.receipt_table_exists())

    def test_b13_two_distinct_forked_turns_leave_no_descendant(self):
        for i in range(2):
            result = self.ok(self.dispatch("b13-repeat-" + str(i),
                                           "--task", "SUM_1_TO_8",
                                           "--scenario", "gated-tree"))
            self.assertTrue(result["descendantTerminationVerified"])
        self.assertEqual(self.database()["receipts"], [
            ["b13-repeat-0", "ACKED", "SYNTHETIC_SUM_36"],
            ["b13-repeat-1", "ACKED", "SYNTHETIC_SUM_36"],
        ])



    def lifecycle(self, command, turn, *options):
        return self.run_source(
            "/source/bin/px_int1_fake_lifecycle.py",
            command, "--room-id", ROOM, "--session-id", SESSION,
            "--turn-id", turn, *options,
            input="Fixed synthetic Hospital Doctor task" if command == "turn" else None,
        )

    def test_b14_doctor_reply_and_status_persist_atomically(self):
        result = self.ok(self.lifecycle("turn", "b14-complete", "--body-stdin"))
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(result["result"], "SYNTHETIC_SUM_36")
        self.assertTrue(result["brokerReaped"])
        status = self.ok(self.lifecycle("status", "b14-complete"))
        self.assertEqual(status["state"], "COMPLETED")
        self.assertFalse(status["automaticRetryAllowed"])
        self.assertEqual(status["doctorMessageId"], result["doctorMessageId"])
        code = (
            "import sqlite3,json;"
            "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=ro',uri=True);"
            "print(json.dumps({'messages':list(c.execute("
            "'SELECT author_role,direction,body_md FROM messages ORDER BY message_id')),"
            "'events':c.execute("
            "'SELECT COUNT(*) FROM session_events WHERE event_type=?',"
            "('turn.completed',)).fetchone()[0],"
            "'status':c.execute('SELECT status FROM sessions').fetchone()[0]}))"
        )
        rows = self.ok(self.fx.run("/usr/bin/python3", "-B", "-c", code))
        self.assertEqual([m[0] for m in rows["messages"]], ["operator", "doctor"])
        self.assertEqual(rows["messages"][1][1], "incoming")
        self.assertEqual(rows["messages"][1][2], result["doctorReply"])
        self.assertEqual(rows["events"], 1)
        self.assertEqual(rows["status"], "IDLE")
        self.assertEqual(status["syntheticSessionStatus"], "WAITING")

    def test_b14_completed_turn_refuses_replay_and_second_reply(self):
        self.ok(self.lifecycle("turn", "b14-once", "--body-stdin"))
        before = self.messages()
        denied = self.lifecycle("turn", "b14-once", "--body-stdin")
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("no automatic turn replay", denied.stderr)
        self.assertEqual(before, self.messages())

    def test_b14_two_turns_share_a_session_without_revoking_the_grant(self):
        first = self.ok(self.lifecycle("turn", "b14-one", "--body-stdin"))
        second = self.ok(self.lifecycle("turn", "b14-two", "--body-stdin"))
        self.assertEqual(first["state"], "COMPLETED")
        self.assertEqual(second["state"], "COMPLETED")
        self.assertNotEqual(first["doctorMessageId"], second["doctorMessageId"])
        self.assertEqual(
            self.ok(self.lifecycle("status", "b14-one"))["state"], "COMPLETED"
        )
        self.assertEqual(
            self.ok(self.lifecycle("status", "b14-two"))["state"], "COMPLETED"
        )

    def test_b14_unknown_status_is_read_only_without_receipt_table(self):
        before = self.messages()
        result = self.ok(self.lifecycle("status", "b14-unknown"))
        self.assertEqual(result["state"], "NOT_FOUND")
        self.assertEqual(before, self.messages())
        self.assertFalse(self.receipt_table_exists())

    def test_b14_accepted_unreserved_manual_failure_no_retry(self):
        digest = self.ok(self.b1(
            "context-digest", "--room-id", ROOM, "--session-id", SESSION
        ))
        accepted = self.run_source(
            "/source/bin/px_int1_fake_atomic.py", "accept",
            "--room-id", ROOM, "--session-id", SESSION,
            "--turn-id", "b14-unreserved",
            "--generation", str(digest["generation"]),
            "--context-hash", digest["contextHash"], "--body-stdin",
            input="Synthetic accepted prompt",
        )
        self.ok(accepted)
        status = self.ok(self.lifecycle("status", "b14-unreserved"))
        self.assertEqual(status["state"], "ACCEPTED_UNRESERVED")
        before = self.messages()
        denied = self.lifecycle(
            "resolve-incomplete", "b14-unreserved",
            "--acknowledge", "invalid", "--reason", "Test closure",
        )
        self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(before, self.messages())
        self.ok(self.lifecycle(
            "resolve-incomplete", "b14-unreserved",
            "--acknowledge", "I_ACKNOWLEDGE_INCOMPLETE_SYNTHETIC_TURN_NO_RETRY",
            "--reason", "Accepted without dispatch reservation",
        ))
        self.assertEqual(self.ok(self.lifecycle("status", "b14-unreserved"))["state"],
                         "FAILED")
        self.assertNotEqual(self.lifecycle(
            "resolve-incomplete", "b14-unreserved",
            "--acknowledge", "I_ACKNOWLEDGE_INCOMPLETE_SYNTHETIC_TURN_NO_RETRY",
            "--reason", "Repeated closure must be refused",
        ).returncode, 0)

    def test_b14_acked_without_reply_cannot_auto_complete(self):
        self.ok(self.dispatch("b14-acked", "--task", "SUM_1_TO_8",
                              "--scenario", "gated-task"))
        status = self.ok(self.lifecycle("status", "b14-acked"))
        self.assertEqual(status["state"], "ACKED_UNFINALIZED")
        self.assertTrue(status["needsExplicitRecovery"])
        self.assertFalse(status["automaticRetryAllowed"])
        self.ok(self.lifecycle(
            "resolve-incomplete", "b14-acked",
            "--acknowledge", "I_ACKNOWLEDGE_INCOMPLETE_SYNTHETIC_TURN_NO_RETRY",
            "--reason", "Orphaned ACK cannot prove terminated children",
        ))
        self.assertEqual(self.ok(self.lifecycle("status", "b14-acked"))["state"],
                         "FAILED")
        self.assertNotEqual(self.lifecycle(
            "turn", "b14-acked", "--body-stdin").returncode, 0)

    def test_b14_reserved_crash_stays_with_b12_recovery(self):
        crashed = self.dispatch("b14-reserved-crash", "--test-crash-after-reserve")
        self.assertEqual(crashed.returncode, 77, crashed.stderr)
        status = self.ok(self.lifecycle("status", "b14-reserved-crash"))
        self.assertEqual(status["state"], "DELIVERY_UNCERTAIN")
        denied = self.lifecycle(
            "resolve-incomplete", "b14-reserved-crash",
            "--acknowledge", "I_ACKNOWLEDGE_INCOMPLETE_SYNTHETIC_TURN_NO_RETRY",
            "--reason", "Reserved delivery must follow B12",
        )
        self.assertNotEqual(denied.returncode, 0)
        self.ok(self.close_uncertain("b14-reserved-crash"))
        self.assertEqual(self.ok(self.lifecycle(
            "status", "b14-reserved-crash"))["state"], "FAILED")


    def test_b14_active_revoke_interrupts_synthetic_tree(self):
        probe = (
            "import sqlite3;"
            "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=ro',"
            "uri=True,timeout=.2);"
            "exists=c.execute(\"SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='int1_fake_dispatch_receipts'\").fetchone();"
            "print('1' if exists and c.execute("
            "\"SELECT 1 FROM int1_fake_dispatch_receipts "
            "WHERE turn_id='b14-cancel' AND state='RESERVED'\").fetchone() "
            "else '0')"
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                self.lifecycle, "turn", "b14-cancel", "--body-stdin",
                "--cancel-demo",
            )
            for _ in range(100):
                check = self.fx.run("/usr/bin/python3", "-B", "-c", probe)
                if check.returncode == 0 and check.stdout.strip() == "1":
                    break
                time.sleep(.025)
            else:
                self.fail("synthetic dispatch never produced RESERVED receipt")
            # The synthetic child forks after receipt, then pins its pidfd.
            time.sleep(.4)
            pending_state = self.ok(self.lifecycle("status", "b14-cancel"))
            self.assertEqual(pending_state["state"], "DELIVERY_UNCERTAIN")
            self.ok(self.b1("revoke", "--room-id", ROOM,
                            "--reason", "B14 synthetic active cancellation"))
            refused = pending.result(timeout=12)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("revoked", refused.stderr.lower())
        self.assertNotIn("descendant survived", refused.stderr)
        self.assertEqual(
            self.ok(self.lifecycle("status", "b14-cancel"))["state"], "FAILED"
        )
        self.assertEqual(self.database()["receipts"],
                         [["b14-cancel", "FAILED", ""]])
        code = (
            "import sqlite3;"
            "c=sqlite3.connect('file:/fixture/hospital/data/hospital.db?mode=ro',uri=True);"
            "print(c.execute(\"SELECT COUNT(*) FROM messages "
            "WHERE author_role='doctor'\").fetchone()[0])"
        )
        self.assertEqual(self.ok(self.fx.run(
            "/usr/bin/python3", "-B", "-c", code
        )), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
