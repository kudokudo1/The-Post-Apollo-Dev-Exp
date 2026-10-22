#!/usr/bin/env python3
"""INT1-A: actual PX turn preflight, NEVER an accepted/started Doctor turn.

Tests run inside the accepted INT1-P1 Bubblewrap fixture. No real providers,
no host repository execution, no live Hospital and no production writes.
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
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

    def test_i1_mismatched_session_doctor_refused_without_turn_mutation(self):
        """The unmodified Hospital store permits a foreign session Doctor."""
        self.ok(self.fx.hospital(
            "session-put", "int1-fake-session",
            "--room-id", "S3-INT1",
            "--doctor-id", "S3-FOREIGN-DOCTOR",
            "--provider-id", "int1-fake", "--status", "IDLE",
        ))
        room = self.ok(self.fx.hospital("room", "S3-INT1"))
        original = self.before()
        self.assertEqual(room["doctorId"], "S3-FAKE-DOCTOR")
        self.assertEqual(original[2]["doctorId"], "S3-FOREIGN-DOCTOR")
        attempt = self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--prompt", "REFUSE FOREIGN DOCTOR",
        )
        self.assertNotEqual(attempt.returncode, 0)
        self.assertIn("INT1-A REFUSED // DOCTOR_ROOM_MISMATCH", attempt.stderr)
        self.assertNotIn("PREFLIGHT_ONLY", attempt.stdout)
        self.assert_no_turn_mutation(original)

    def test_i1_missing_session_doctor_refused_without_turn_mutation(self):
        """Empty identities cannot impersonate an unassigned Room."""
        self.ok(self.fx.hospital(
            "session-put", "int1-fake-session",
            "--room-id", "S3-INT1", "--doctor-id", "",
            "--provider-id", "int1-fake", "--status", "IDLE",
        ))
        original = self.before()
        self.assertEqual(original[2]["doctorId"], "")
        attempt = self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--prompt", "REFUSE UNKNOWN DOCTOR",
        )
        self.assertNotEqual(attempt.returncode, 0)
        self.assertIn("INT1-A REFUSED // DOCTOR_ROOM_IDENTITY_UNRESOLVED", attempt.stderr)
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

    def test_reject_wrong_synthetic_resume_identity_before_persistence(self):
        self.ok(self.fx.hospital(
            "session-runtime", "int1-fake-session",
            "--provider-session-id", "UNAPPROVED-RESUME",
            "--status", "IDLE",
        ))
        original = self.before()
        attempt = self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--prompt", "NO WRONG RESUME",
        )
        self.assertNotEqual(attempt.returncode, 0)
        self.assertIn("synthetic resume identity mismatch", attempt.stderr)
        self.assert_no_turn_mutation(original)

    def test_forged_fixture_env_cannot_replace_os_mount_boundary(self):
        # Pure in-process security unit test on disposable GitHub CI, not
        # a PX/Hospital or model process launched outside the fixture.
        import importlib.util
        source = REPO / "bin/px_int1_fake_guard.py"
        spec = importlib.util.spec_from_file_location("int1_fake_guard_probe", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fake_host_env = {**module.ENV_PATHS, **module.ENV_STATIC, "PWD": "/fixture"}
        with patch.dict(os.environ, fake_host_env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OS fixture boundary absent"):
                module.require_fixture()

    def test_wrong_bed_override_refused_before_persistence(self):
        original = self.before()
        result = self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--working-directory", "/fixture/home", "--prompt", "NO FOREIGN BED",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("synthetic Bed outside disposable fixture", result.stderr)
        self.assert_no_turn_mutation(original)


    def install_b15_authority(self):
        assignment = self.ok(self.fx.hospital(
            "assignment-create", "--room-id", "S3-INT1",
            "--title", "B15 synthetic", "--goal", "Bounded fake turn",
            "--permissions-json", '["READ","EDIT"]',
        ))
        self.ok(self.fx.hospital("assignment-activate", assignment["id"]))
        for path, cmd in (
            ("/source/bin/px_int1_fake_atomic.py", "bootstrap"),
            ("/source/bin/px_int1_fake_epoch.py", "install"),
            ("/source/bin/px_int1_fake_continuity.py", "install"),
        ):
            self.ok(self.fx.run(
                "/usr/bin/python3", "-B", path, cmd,
                "--room-id", "S3-INT1", "--session-id", "int1-fake-session",
            ))

    def b15_turn(self, turn_id, *, prompt="SYNTHETIC_SUM_1_TO_8"):
        return self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-turn",
            "--exec-s3-fake-turn-id", turn_id, "--prompt", prompt,
        )

    def b15_status(self, turn_id):
        return self.fx.agent(
            "status", "int1-fake-session", "--exec-s3-fake-turn-id", turn_id,
        )

    def test_b15_actual_agent_turn_persists_verified_reply_and_status(self):
        self.ok(self.fx.hospital(
            "room-report-append", "--room-id", "S3-INT1",
            "--session-id", "int1-fake-session", "--report-kind", "HANDOFF",
            "--title", "B15 source", "--body", "B15 REQUIRED HANDOFF",
        ))
        self.ok(self.fx.hospital(
            "chart-entry-add", "--scope", "PATIENT",
            "--patient-id", "S3-SYNTHETIC-PATIENT", "--entry-kind", "INVARIANT",
            "--title", "B15 patient", "--author-role", "operator",
            "--body", "B15 PATIENT SOURCE",
        ))
        self.install_b15_authority()
        result = self.ok(self.b15_turn("b15-first"))
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(result["assistant"], result["doctorReply"])
        self.assertEqual(result["modelCalls"], 0)
        self.assertEqual(result["toolCalls"], 0)
        self.assertTrue(result["sourceDigestChecked"])
        self.assertEqual(len(result["requiredHandoffIds"]), 1)
        self.assertEqual(len(result["approvedPatientChartIds"]), 1)
        status = self.ok(self.b15_status("b15-first"))
        self.assertEqual(status["state"], "COMPLETED")
        self.assertEqual(status["doctorMessageId"], result["assistantMessageId"])
        self.assertEqual(status["syntheticSessionStatus"], "WAITING")
        messages = self.ok(self.fx.hospital("messages", "S3-INT1", "--limit", "10"))
        self.assertEqual([x["authorRole"] for x in messages], ["operator", "doctor"])

    def test_b15_actual_agent_two_turns_and_replay_refusal(self):
        self.install_b15_authority()
        a = self.ok(self.b15_turn("b15-one"))
        b = self.ok(self.b15_turn("b15-two"))
        self.assertNotEqual(a["assistantMessageId"], b["assistantMessageId"])
        before = self.before()
        refused = self.b15_turn("b15-one")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("no automatic turn replay", refused.stderr)
        self.assertEqual(self.before(), before)

    def test_b15_no_fake_flag_refuses_even_after_authority_install(self):
        self.install_b15_authority()
        old = self.before()
        refused = self.fx.agent(
            "turn", "int1-fake-session", "--prompt", "SYNTHETIC_SUM_1_TO_8",
            "--exec-s3-fake-turn-id", "b15-bypass",
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.before(), old)

    def test_b15_unsupported_task_does_not_accept_messages(self):
        self.install_b15_authority()
        before = self.before()
        denied = self.b15_turn("b15-shell", prompt="SHELL")
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("fixed synthetic task only", denied.stderr)
        self.assertEqual(self.before(), before)

    def test_b15_missing_bootstrap_or_hooks_refuses_without_message(self):
        before = self.before()
        denied = self.b15_turn("b15-uninitialized")
        self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(self.before(), before)

    def test_b15_revoked_grant_refuses_another_turn(self):
        self.install_b15_authority()
        self.ok(self.b15_turn("b15-before-revoke"))
        self.ok(self.fx.run(
            "/usr/bin/python3", "-B",
            "/source/bin/px_int1_fake_atomic.py",
            "revoke", "--room-id", "S3-INT1",
            "--reason", "B15 synthetic revocation",
        ))
        before = self.before()
        denied = self.b15_turn("b15-after-revoke")
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("revoked", denied.stderr.lower())
        self.assertEqual(self.before(), before)


    def b16_cancel(self, turn_id, reason="B16 synthetic cancellation request"):
        return self.fx.agent(
            "cancel", "int1-fake-session",
            "--exec-s3-fake-turn-id", turn_id, "--reason", reason,
        )

    def test_b16_real_agent_cancel_interrupts_running_synthetic_child(self):
        self.install_b15_authority()
        # One known fake worker plus exactly one forked test descendant.
        # The supervisor owns the kernel pidfd and independently proves exit.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.fx.agent,
                "turn", "int1-fake-session", "--exec-s3-fake-turn",
                "--exec-s3-fake-turn-id", "b16-running",
                "--exec-s3-fake-cancel-demo",
                "--prompt", "SYNTHETIC_SUM_1_TO_8")
            for _ in range(120):
                status = self.b15_status("b16-running")
                if status.returncode == 0:
                    if self.ok(status)["state"] == "DELIVERY_UNCERTAIN":
                        break
                time.sleep(.04)
            else:
                self.fail("B16 synthetic reservation not observed")
            time.sleep(.4)  # Allow the fixed descendant to fork and be tracked.
            old = self.before()
            implicit = self.fx.agent("cancel", "int1-fake-session")
            self.assertNotEqual(implicit.returncode, 0)
            self.assertIn("explicit --exec-s3-fake-turn-id", implicit.stderr)
            self.assertEqual(self.before(), old)
            denied = self.b15_turn("b16-running")
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("already operating", denied.stderr)
            requested = self.ok(self.b16_cancel("b16-running"))
            self.assertTrue(requested["cancelRequested"])
            self.assertFalse(requested["roomAuthorityRevoked"])
            self.assertTrue(requested["turnCancellationScoped"])
            self.assertFalse(requested["workerTerminationVerified"])
            self.assertFalse(requested["automaticRetryAllowed"])
            failed = pending.result(timeout=18)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("cancellation requested", failed.stderr.lower())
        self.assertNotIn("descendant survived", failed.stderr)
        end = self.ok(self.b15_status("b16-running"))
        self.assertEqual(end["state"], "FAILED")
        self.assertFalse(end["automaticRetryAllowed"])
        # B19: cancellation request is not termination evidence. Only the
        # surviving supervisor's completed cleanup can write this receipt.
        self.assertTrue(end["supervisorTeardownEvidenceRecorded"])
        self.assertTrue(end["wrapperReapedVerified"])
        self.assertTrue(end["knownDescendantPidfdExitVerified"])
        self.assertFalse(end["workerTerminationVerifiedAfterCrash"])
        entries = self.ok(self.fx.hospital("events", "int1-fake-session",
                                           "--limit", "100"))
        cancelled = [event for event in entries
                     if event["type"] == "turn.cancel.requested"]
        self.assertEqual(len(cancelled), 1)
        self.assertFalse(cancelled[0]["payload"]["workerTerminationVerified"])
        msgs = self.ok(self.fx.hospital("messages", "S3-INT1",
                                        "--limit", "100"))
        self.assertEqual([row["authorRole"] for row in msgs], ["operator"])
        second = self.b16_cancel("b16-running")
        self.assertNotEqual(second.returncode, 0)
        another = self.ok(self.b15_turn("b16-after"))
        self.assertEqual(another["state"], "COMPLETED")

    def test_b16_completed_turn_cannot_be_cancelled(self):
        self.install_b15_authority()
        self.ok(self.b15_turn("b16-done"))
        before = self.before()
        denied = self.b16_cancel("b16-done")
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("reserved synthetic turn", denied.stderr)
        self.assertEqual(before, self.before())
        self.ok(self.b15_turn("b16-still-authorized"))

    def test_b16_nonexistent_turn_or_bad_reason_refuses_without_revocation(self):
        self.install_b15_authority()
        before = self.before()
        unknown = self.b16_cancel("b16-not-found")
        self.assertNotEqual(unknown.returncode, 0)
        blank = self.b16_cancel("b16-not-found", reason=" ")
        self.assertNotEqual(blank.returncode, 0)
        self.assertEqual(before, self.before())
        self.ok(self.b15_turn("b16-fresh"))

    def test_b16_native_session_cannot_use_synthetic_cancel_flag(self):
        self.ok(self.fx.hospital(
            "session-put", "b16-native",
            "--room-id", "S3-INT1", "--doctor-id", "S3-FAKE-DOCTOR",
            "--provider-id", "codex", "--status", "IDLE",
        ))
        self.ok(self.fx.hospital(
            "session-runtime", "b16-native",
            "--working-directory", "/fixture/bed", "--status", "IDLE",
        ))
        before = self.before()
        refused = self.fx.agent(
            "cancel", "b16-native", "--exec-s3-fake-turn-id", "b16-native-turn",
            "--reason", "Native provider cannot impersonate fake profile",
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.before(), before)

    def test_b16_demo_flag_without_explicit_fake_turn_refuses(self):
        before = self.before()
        refused = self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-cancel-demo",
            "--prompt", "SYNTHETIC_SUM_1_TO_8",
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("demo needs fake turn", refused.stderr)
        self.assertEqual(before, self.before())



    def test_b17_peer_session_keeps_same_room_grant_during_cancellation(self):
        # Create second Session BEFORE B2 triggers are installed. B2 correctly
        # revokes on actual Session creation after authorization.
        self.ok(self.fx.agent(
            "session-create", "--room-id", "S3-INT1",
            "--doctor-id", "S3-FAKE-DOCTOR", "--provider-id", "int1-fake",
            "--working-directory", "/fixture/bed",
            "--session-id", "b17-peer-session",
        ))
        self.install_b15_authority()
        with ThreadPoolExecutor(max_workers=1) as pool:
            active = pool.submit(self.fx.agent, "turn", "int1-fake-session",
                "--exec-s3-fake-turn", "--exec-s3-fake-turn-id", "b17-target",
                "--exec-s3-fake-cancel-demo", "--prompt", "SYNTHETIC_SUM_1_TO_8")
            for _ in range(120):
                progress = self.b15_status("b17-target")
                if progress.returncode == 0 and self.ok(progress)["state"] == "DELIVERY_UNCERTAIN":
                    break
                time.sleep(.04)
            else:
                self.fail("B17 target reservation not observed")
            # Peer operates through the same Room and fake grant while target
            # is still running. Its result must survive the target cancellation.
            peer = self.ok(self.fx.agent(
                "turn", "b17-peer-session", "--exec-s3-fake-turn",
                "--exec-s3-fake-turn-id", "b17-peer-before",
                "--prompt", "SYNTHETIC_SUM_1_TO_8",
            ))
            self.assertEqual(peer["state"], "COMPLETED")
            time.sleep(.3)
            cancel = self.ok(self.b16_cancel("b17-target"))
            self.assertTrue(cancel["turnCancellationScoped"])
            self.assertFalse(cancel["roomAuthorityRevoked"])
            self.assertTrue(cancel["cancelRequested"])
            state = self.ok(self.b15_status("b17-target"))["state"]
            self.assertIn(state, ("CANCELLATION_REQUESTED", "FAILED"))
            failed = active.result(timeout=18)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("cancellation requested", failed.stderr.lower())
        self.assertEqual(self.ok(self.b15_status("b17-target"))["state"], "FAILED")
        self.assertEqual(self.ok(self.fx.agent(
            "status", "b17-peer-session",
            "--exec-s3-fake-turn-id", "b17-peer-before",
        ))["state"], "COMPLETED")
        after = self.ok(self.fx.agent(
            "turn", "b17-peer-session", "--exec-s3-fake-turn",
            "--exec-s3-fake-turn-id", "b17-peer-after",
            "--prompt", "SYNTHETIC_SUM_1_TO_8",
        ))
        self.assertEqual(after["state"], "COMPLETED")
        # The cancelled Session itself can take a NEW turn under same grant.
        self.assertEqual(self.ok(self.b15_turn("b17-new-turn"))["state"], "COMPLETED")

    def test_b17_orphaned_cancel_requires_manual_b12_recovery(self):
        self.install_b15_authority()
        # Deliberate supervisor crash AFTER durable reservation, before frame.
        crash = self.fx.run(
            "/usr/bin/python3", "-B", "/source/bin/px_int1_fake_dispatch.py",
            "--room-id", "S3-INT1", "--session-id", "int1-fake-session",
            "--turn-id", "b17-orphan", "--body-stdin",
            "--test-crash-after-reserve", input="synthetic crashed turn",
        )
        self.assertEqual(crash.returncode, 77, crash.stderr)
        self.assertEqual(self.ok(self.b15_status("b17-orphan"))["state"],
                         "DELIVERY_UNCERTAIN")
        cancel = self.ok(self.b16_cancel("b17-orphan"))
        self.assertFalse(cancel["workerTerminationVerified"])
        uncertain = self.ok(self.b15_status("b17-orphan"))
        self.assertEqual(uncertain["state"], "CANCELLATION_REQUESTED")
        self.assertTrue(uncertain["needsExplicitRecovery"])
        self.assertFalse(uncertain["automaticRetryAllowed"])
        repeat = self.b16_cancel("b17-orphan")
        self.assertNotEqual(repeat.returncode, 0)
        self.assertIn("already requested", repeat.stderr)
        closed = self.ok(self.fx.run(
            "/usr/bin/python3", "-B", "/source/bin/px_int1_fake_recovery.py",
            "resolve-uncertain", "--room-id", "S3-INT1",
            "--session-id", "int1-fake-session", "--turn-id", "b17-orphan",
            "--acknowledge", "I_ACKNOWLEDGE_UNKNOWN_DELIVERY_AND_NO_RETRY",
            "--reason", "B17 supervisor crashed before dispatch",
        ))
        self.assertEqual(closed["state"], "FAILED_UNCERTAIN_DELIVERY")
        self.assertFalse(closed["workerTerminationVerified"])
        self.assertEqual(self.ok(self.b15_status("b17-orphan"))["state"], "FAILED")
        attempt = self.b15_turn("b17-orphan")
        self.assertNotEqual(attempt.returncode, 0)
        self.assertEqual(self.ok(self.b15_turn("b17-next"))["state"], "COMPLETED")

    def test_b17_other_session_cannot_cancel_foreign_turn(self):
        self.ok(self.fx.agent(
            "session-create", "--room-id", "S3-INT1",
            "--doctor-id", "S3-FAKE-DOCTOR", "--provider-id", "int1-fake",
            "--working-directory", "/fixture/bed",
            "--session-id", "b17-other-session",
        ))
        self.install_b15_authority()
        crashed = self.fx.run(
            "/usr/bin/python3", "-B", "/source/bin/px_int1_fake_dispatch.py",
            "--room-id", "S3-INT1", "--session-id", "int1-fake-session",
            "--turn-id", "b17-protected", "--body-stdin",
            "--test-crash-after-reserve", input="orphaned protected task",
        )
        self.assertEqual(crashed.returncode, 77, crashed.stderr)
        old = self.before()
        fake_cancel = self.fx.agent(
            "cancel", "b17-other-session",
            "--exec-s3-fake-turn-id", "b17-protected",
            "--reason", "Must not cross session boundary",
        )
        self.assertNotEqual(fake_cancel.returncode, 0)
        self.assertIn("reserved synthetic turn", fake_cancel.stderr)
        self.assertEqual(old, self.before())
        self.assertEqual(self.ok(self.b15_status("b17-protected"))["state"],
                         "DELIVERY_UNCERTAIN")
        self.assertEqual(self.ok(self.b15_turn("b17-clean"))["state"], "COMPLETED")


    def test_b21_preflight_reports_only_closed_fake_capability(self):
        before = self.before()
        result = self.ok(self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--prompt", "B21 source-owned capability",
        ))
        proof = result["capability"]
        self.assertTrue(proof["capabilityValidatedInFixture"])
        self.assertEqual(proof["capabilityProfile"], "FIXED_SYNTHETIC_ONLY")
        self.assertEqual(proof["contractVersion"], 1)
        self.assertEqual(len(proof["sourceDigest"]), 64)
        self.assertEqual(proof["sourceEvidence"], "READ_ONLY_FIXTURE_BYTES_NOT_SIGNED")
        self.assertFalse(proof["modelOnlyCertified"])
        self.assertFalse(proof["realProviderCertified"])
        self.assertFalse(proof["credentialsAvailable"])
        self.assertFalse(proof["nativeToolsAllowed"])
        self.assertFalse(proof["gatewayActive"])
        self.assertFalse(proof["productionReady"])
        self.assertEqual(proof["realModelCalls"], 0)
        self.assert_no_turn_mutation(before)

    def test_b21_contract_reinspection_is_deterministic_and_read_only(self):
        before = self.before()
        a = self.ok(self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--prompt", "First fixed capability inspection",
        ))
        b = self.ok(self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--prompt", "Second fixed capability inspection",
        ))
        self.assertEqual(a["capability"], b["capability"])
        self.assert_no_turn_mutation(before)

    def test_b21_closed_contract_rejects_escalation_and_new_schema(self):
        script = r"""
import copy,json,sys
sys.path.insert(0, '/source/bin')
from px_int1_fake_capability import FAKE_CONTRACT,require_fake_capability
provider = {'name':'INT1 FAKE','executionProfile':'EXEC_S3_FAKE_ONLY',
            'dialect':'exec-s3-fake-only'}
registry = {'version':1,'providers':{'int1-fake':provider}}
bad = [
    {'contractVersion':2},
    {'providerId':'codex'},
    {'providerBinary':'/usr/bin/codex'},
    {'nativeModelTransport':'CODEX_EXEC'},
    {'credentialMode':'INHERITED_HOST'},
    {'nativeTools':['shell']},
    {'modelOnlyCertified':True},
    {'modelOnlyCertified':1},
    {'externalToolCallsAllowed':True},
    {'toolProtocol':'UNRESTRICTED'},
    {'executionOwner':'HERMES_GATEWAY'},
    {'cancellationOwner':'KILL_CLIENT_PID'},
    {'gateway':'PERSISTENT'},
    {'nativeResume':True},
    {'crashRecovery':'AUTO_RETRY'},
    {'unknownCapability':'UPGRADE'},
]
count = 0
for mutation in bad:
    candidate = copy.deepcopy(FAKE_CONTRACT)
    candidate.update(mutation)
    try:
        require_fake_capability('int1-fake',provider,registry,candidate=candidate)
    except RuntimeError as e:
        assert 'unsupported or escalated' in str(e), str(e)
        count += 1
    else:
        raise AssertionError('unsafe candidate accepted: '+str(mutation))
print(json.dumps({'denied':count,'total':len(bad)}))
"""
        before = self.before()
        proof = self.ok(self.fx.run("/usr/bin/python3", "-B", "-c", script))
        self.assertEqual(proof["denied"], 16)
        self.assertEqual(proof["total"], 16)
        self.assert_no_turn_mutation(before)

    def test_b21_fake_contract_cannot_certify_native_provider_ids(self):
        script = r"""
import json,sys
sys.path.insert(0,'/source/bin')
from px_int1_fake_capability import require_fake_capability,FAKE_CONTRACT
provider = {'name':'INT1 FAKE','executionProfile':'EXEC_S3_FAKE_ONLY',
            'dialect':'exec-s3-fake-only'}
registry={'version':1,'providers':{'int1-fake':provider}}
blocked=[]
for name in ('codex','hermes','unregistered'):
    try:
        require_fake_capability(name, provider, registry,
                                candidate=FAKE_CONTRACT)
    except RuntimeError:
        blocked.append(name)
    else:
        raise AssertionError('native provider accepted')
print(json.dumps({'blocked':blocked}))
"""
        before = self.before()
        proof = self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))
        self.assertEqual(proof["blocked"], ["codex","hermes","unregistered"])
        self.assert_no_turn_mutation(before)

    def test_b21_turn_proves_contract_without_model_or_native_tools(self):
        self.install_b15_authority()
        result = self.ok(self.b15_turn("b21-turn"))
        self.assertEqual(result["state"], "COMPLETED")
        cap = result["capability"]
        self.assertTrue(cap["capabilityValidatedInFixture"])
        self.assertFalse(cap["modelOnlyCertified"])
        self.assertFalse(cap["nativeToolsAllowed"])
        self.assertFalse(cap["credentialsAvailable"])
        self.assertFalse(cap["productionReady"])
        self.assertEqual(result["modelCalls"], 0)
        self.assertEqual(result["toolCalls"], 0)
        second = self.ok(self.b15_turn("b21-resumed"))
        self.assertEqual(second["capability"]["sourceDigest"], cap["sourceDigest"])

    def test_b21_fixture_capability_denies_untrusted_source_context(self):
        script = r"""
import json,sys
sys.path.insert(0,'/source/bin')
import px_int1_fake_capability as c
try:
    original = c.SOURCE_PATHS
    c.SOURCE_PATHS = ('/fixture/bed/tracked.txt',)
    try:
        c._source_digest()
    except RuntimeError as e:
        assert 'not pinned read-only' in str(e),str(e)
        print(json.dumps({'denied':True}))
    else:
        raise AssertionError('writable Bed source admitted')
finally:
    c.SOURCE_PATHS = original
"""
        original = self.before()
        verdict = self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))
        self.assertTrue(verdict["denied"])
        self.assert_no_turn_mutation(original)


    def test_b22_preflight_has_reviewed_fake_source_version(self):
        original = self.before()
        result = self.ok(self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--prompt", "B22 version evidence only",
        ))
        record = result["sourcePin"]
        self.assertTrue(record["versionPinnedInFixture"])
        self.assertEqual(record["pinVersion"], 1)
        self.assertEqual(len(record["manifestSha256"]), 64)
        self.assertEqual(record["observedSourceSha256"],
                         result["capability"]["sourceDigest"])
        self.assertEqual(record["provenance"],
                         "SOURCE_OWNED_GIT_BLOB_IDS_NOT_SIGNED")
        self.assertFalse(record["realProviderVersionVerified"])
        self.assertFalse(record["hostBinaryInspected"])
        self.assertFalse(record["modelOnlyCertified"])
        self.assertFalse(record["productionReady"])
        self.assert_no_turn_mutation(original)

    def test_b22_fake_turn_version_matches_preflight_and_restart(self):
        preflight = self.ok(self.fx.agent(
            "turn", "int1-fake-session", "--exec-s3-fake-preflight",
            "--prompt", "Inspect source baseline",
        ))
        self.install_b15_authority()
        result = self.ok(self.b15_turn("b22-first"))
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(result["sourcePin"], preflight["sourcePin"])
        self.assertEqual(result["modelCalls"], 0)
        self.assertEqual(result["toolCalls"], 0)
        second = self.ok(self.b15_turn("b22-second"))
        self.assertEqual(second["sourcePin"], result["sourcePin"])

    def test_b22_stale_manifest_fails_before_acceptance(self):
        script = r"""
import json,sys
sys.path.insert(0, '/source/bin')
import px_int1_fake_version_pin as pin
from px_int1_fake_capability import require_fake_capability
provider={'name':'INT1 FAKE','executionProfile':'EXEC_S3_FAKE_ONLY',
          'dialect':'exec-s3-fake-only'}
registry={'version':1,'providers':{'int1-fake':provider}}
cap=require_fake_capability('int1-fake',provider,registry)
old=pin.PINNED_GIT_BLOBS
try:
    changed=dict(old)
    changed['/source/bin/px_int1_fake_broker.py']='0'*40
    pin.PINNED_GIT_BLOBS=changed
    try:
        pin.require_source_pin(cap)
    except RuntimeError as e:
        assert 'source version drift' in str(e),str(e)
        print(json.dumps({'refused':True}))
    else:
        raise AssertionError('unapproved source version accepted')
finally:
    pin.PINNED_GIT_BLOBS=old
"""
        old = self.before()
        proof = self.ok(self.fx.run("/usr/bin/python3", "-B", "-c", script))
        self.assertTrue(proof["refused"])
        self.assert_no_turn_mutation(old)

    def test_b22_provider_spoofing_and_capability_escalation_refused(self):
        script = r"""
import json,sys
sys.path.insert(0,'/source/bin')
from px_int1_fake_capability import require_fake_capability
from px_int1_fake_version_pin import require_source_pin
provider={'name':'INT1 FAKE','executionProfile':'EXEC_S3_FAKE_ONLY',
          'dialect':'exec-s3-fake-only'}
registry={'version':1,'providers':{'int1-fake':provider}}
cap=require_fake_capability('int1-fake',provider,registry)
count=0
for key,value in (('providerId','codex'),
                  ('providerId','hermes'),
                  ('credentialsAvailable',True),
                  ('nativeToolsAllowed',True),
                  ('modelOnlyCertified',True),
                  ('realProviderCertified',True),
                  ('productionReady',True),
                  ('contractVersion',2)):
    bad=dict(cap)
    bad[key]=value
    try:
        require_source_pin(bad)
    except RuntimeError as e:
        assert 'invalid synthetic capability' in str(e),str(e)
        count += 1
    else:
        raise AssertionError('unsafe provider accepted')
print(json.dumps({'refusals':count}))
"""
        before = self.before()
        result = self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))
        self.assertEqual(result["refusals"], 8)
        self.assert_no_turn_mutation(before)

    def test_b22_writable_source_manifest_cannot_upgrade_fixture(self):
        script = r"""
import json,sys
sys.path.insert(0,'/source/bin')
import px_int1_fake_version_pin as pin
from px_int1_fake_capability import require_fake_capability
provider={'name':'INT1 FAKE','executionProfile':'EXEC_S3_FAKE_ONLY',
          'dialect':'exec-s3-fake-only'}
registry={'version':1,'providers':{'int1-fake':provider}}
cap=require_fake_capability('int1-fake',provider,registry)
old=pin.PINNED_GIT_BLOBS
try:
    pins=dict(old)
    pins['/fixture/bed/tracked.txt']=pins.pop(
        '/source/bin/px_int1_fake_broker.py')
    pin.PINNED_GIT_BLOBS=pins
    try:
        pin.require_source_pin(cap)
    except RuntimeError as e:
        assert 'invalid pinned source manifest' in str(e),str(e)
        print(json.dumps({'refused':True}))
    else:
        raise AssertionError('writable fixture source accepted')
finally:
    pin.PINNED_GIT_BLOBS=old
"""
        original = self.before()
        result = self.ok(self.fx.run("/usr/bin/python3","-B","-c",script))
        self.assertTrue(result["refused"])
        self.assert_no_turn_mutation(original)

if __name__ == "__main__":
    unittest.main(verbosity=2)
