#!/usr/bin/env python3
"""EXEC-S3 fake-only integration acceptance: unit negatives + real Bubblewrap smoke."""
import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent


def load(name, key):
    loader = importlib.machinery.SourceFileLoader(key, str(HERE / name))
    spec = importlib.util.spec_from_loader(key, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    loader.exec_module(module)
    return module


s3 = load("px_exec_s3_fake.py", "s3_fake")
s2 = load("test-pxd-exec-s2-credential-boundary.py", "s3_s2")
s1 = load("test-pxd-exec-s1-isolation.py", "s3_s1")


def fixture_root(path):
    root = Path(path).resolve(strict=True)
    root.chmod(0o700)
    for dirname in ("patient", "private", "scratch"):
        (root / dirname).mkdir(mode=0o700)
    (root / "patient" / "fixture.txt").write_text("S3-FAKE-PATIENT")
    token = "S3-FAKE-" + secrets.token_urlsafe(24)
    auth = root / "private" / s2.FAKE_AUTH_FILENAME
    auth.write_text(json.dumps({"kind": "SYNTHETIC_ONLY", "token": token}))
    auth.chmod(0o600)
    return root, s2.FakeModelService(token)


class ControlledFakeBroker:
    """Unit-only stand-in for Stage B; no claim of OS isolation."""
    instances = []
    fail_stage = None

    def __init__(self, root):
        self.root = root
        self.ready = False
        self.stopped = False
        self.dead = False
        self.grants = []
        self.executions = 0
        self.__class__.instances.append(self)

    def start(self):
        if self.fail_stage == "start":
            raise s3.S3Refusal("FAKE: sandbox startup refused")
        self.ready = True

    def assert_alive(self):
        if not self.ready or self.dead or self.stopped:
            raise s3.S3Refusal("FAKE: broker exited after readiness")

    def grant(self, grant):
        self.assert_alive()
        self.grants.append(grant)

    def dispatch(self, grant):
        self.assert_alive()
        if grant not in self.grants:
            raise s3.S3Refusal("FAKE: missing PX grant")
        self.grants.remove(grant)
        self.executions += 1

    def collect(self, grant):
        if self.stopped or self.dead:
            raise s3.S3Refusal("FAKE: revoked broker interrupted")
        if self.fail_stage == "execute":
            raise s3.S3Refusal("FAKE: child failure")
        (self.root / "scratch" / "s3-result.txt").write_text("S3-FAKE-COMPLETE")

    def close(self):
        self.stopped = True
        self.ready = False


class S3PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="px-s3-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root, self.service = fixture_root(self.temp.name)
        self.hospital = s3.FakeHospital()
        ControlledFakeBroker.instances = []
        ControlledFakeBroker.fail_stage = None
        self.sup = s3.FakePXSupervisor(
            self.hospital, self.root, self.service, ControlledFakeBroker)


    def test_h1_broker_exits_after_ready_without_message_persistence(self):
        # Ready remains True: the old ready-flag-only implementation fails.
        def fake_crash():
            ControlledFakeBroker.instances[-1].dead = True
        with self.assertRaisesRegex(s3.S3Refusal, "broker exited after readiness"):
            self.sup.run(on_ready=fake_crash)
        self.assertEqual(self.hospital.outgoing, [])
        self.assertEqual(self.service.calls, 0)
        self.assertNotIn("turn.started", [e["event"] for e in self.hospital.events])
        self.assertIn("isolation.preflight.refused",
                      [e["event"] for e in self.hospital.events])
        self.assertTrue(ControlledFakeBroker.instances[-1].stopped)

    def test_h3_invalid_stage_a_authority_and_resume_are_audited(self):
        cases = (
            ("room", "R-FOREIGN", False),
            ("patient", "FOREIGN-PATIENT", False),
            ("active", False, False),
            ("permissions", {"READ"}, False),
            ("provider_session_id", "OTHER-SESSION", True),
        )
        for field, invalid, resume in cases:
            with self.subTest(field=field):
                prior = getattr(self.hospital, field)
                n = len(self.hospital.events)
                setattr(self.hospital, field, invalid)
                with self.assertRaises(s3.S3Refusal):
                    self.sup.run(resume=resume)
                setattr(self.hospital, field, prior)
                self.assertEqual(self.hospital.events[n:],
                    [{"event": "isolation.preflight.refused",
                      "reason": "static-preflight",
                      "generation": self.hospital.generation}])
                self.assertEqual(self.hospital.outgoing, [])
                self.assertFalse(ControlledFakeBroker.instances)

    def test_h2_direct_hospital_revoke_interrupts_active_broker(self):
        # The supervisor.revoke convenience wrapper is intentionally not used.
        with self.assertRaisesRegex(s3.S3Refusal, "revoked broker interrupted"):
            self.sup.run(on_dispatched=self.hospital.revoke)
        self.assertEqual(ControlledFakeBroker.instances[-1].executions, 1)
        self.assertEqual(self.hospital.state, "FAILED")
        self.assertTrue(self.hospital.paused)
        self.assertEqual(self.hospital.active_brokers, [])
        ev = [e["event"] for e in self.hospital.events]
        self.assertIn("isolation.authority.revoked", ev)
        self.assertIn("isolation.tool.interrupted", ev)
        self.assertNotIn("turn.completed", ev)
        self.assertFalse((self.root / "scratch" / "s3-result.txt").exists())


    def test_h2_direct_revoke_still_kills_tool_when_audit_sink_lost(self):
        def revoke_after_audit_loss():
            self.hospital.audit_enabled = False
            self.hospital.revoke()
        with self.assertRaisesRegex(s3.S3Refusal, "not fully auditable"):
            self.sup.run(on_dispatched=revoke_after_audit_loss)
        self.assertFalse(self.hospital.active)
        self.assertTrue(self.hospital.paused)
        self.assertEqual(self.hospital.state, "FAILED")
        self.assertTrue(ControlledFakeBroker.instances[-1].stopped)
        self.assertEqual(self.hospital.active_brokers, [])
        self.assertNotIn("turn.completed", [e["event"] for e in self.hospital.events])
        self.assertFalse((self.root / "scratch" / "s3-result.txt").exists())

    def test_h2_revoke_during_grant_dispatch_cannot_slip_between(self):
        # A rival thread starts revoking while dispatch still holds h.lock.
        # The update must serialize before or after dispatch, never between
        # the generation check and sending the tool request.
        started = threading.Event()
        finished = threading.Event()
        workers = []
        original = ControlledFakeBroker.dispatch

        def competing_dispatch(broker, grant):
            def revoke_from_other_thread():
                started.set()
                self.hospital.revoke()
                finished.set()
            worker = threading.Thread(target=revoke_from_other_thread, daemon=True)
            workers.append(worker)
            worker.start()
            self.assertTrue(started.wait(2), "synthetic race worker did not start")
            self.assertTrue(self.hospital.active, "revocation overtook locked dispatch")
            return original(broker, grant)

        try:
            with mock.patch.object(ControlledFakeBroker, "dispatch", competing_dispatch):
                with self.assertRaisesRegex(s3.S3Refusal, "revoked broker interrupted"):
                    self.sup.run(on_dispatched=lambda: self.assertTrue(finished.wait(3)))
        finally:
            for worker in workers:
                worker.join(3)
        self.assertTrue(finished.is_set())
        self.assertEqual(self.hospital.generation, 2)
        self.assertEqual(self.hospital.state, "FAILED")
        self.assertNotIn("turn.completed", [e["event"] for e in self.hospital.events])

    def test_h4_popen_failure_closes_both_info_pipe_descriptors(self):
        # Does not rely on local bwrap availability.
        fake_s1 = mock.Mock()
        fake_s1.build_command.return_value = ["/usr/bin/bwrap", "--synthetic"]
        pipe_pairs = []
        original_pipe = os.pipe

        def counted_pipe():
            pair = original_pipe()
            pipe_pairs.append(pair)
            return pair

        with mock.patch.object(s3, "accepted", return_value=fake_s1), \
             mock.patch.object(s3.os, "pipe", side_effect=counted_pipe), \
             mock.patch.object(s3.subprocess, "Popen", side_effect=OSError("synthetic failure")):
            broker = s3.IsolatedBroker(self.root)
            with self.assertRaisesRegex(s3.S3Refusal, "broker launch failed"):
                broker.start()
        self.assertEqual(len(pipe_pairs), 1)
        for fd in pipe_pairs[0]:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_start_then_resume_preserves_identity(self):
        first = self.sup.run()
        self.assertEqual(first["state"], "PASS")
        self.assertFalse(first["productionReady"])
        self.assertEqual(self.sup.run(resume=True)["state"], "PASS")
        self.assertEqual(len(self.hospital.outgoing), 2)
        self.assertEqual(self.service.calls, 2)
        self.assertEqual(self.hospital.provider_session_id, s3.FAKE_SESSION_ID)
        self.assertTrue(all(b.stopped for b in ControlledFakeBroker.instances))

    def test_resume_with_wrong_native_identity_refused_before_start(self):
        self.hospital.provider_session_id = "FOREIGN-S3-ID"
        with self.assertRaisesRegex(s3.S3Refusal, "native session mismatch"):
            self.sup.run(resume=True)
        self.assertFalse(self.hospital.outgoing)
        self.assertEqual(self.service.calls, 0)
        self.assertFalse(ControlledFakeBroker.instances)

    def test_missing_resume_flag_after_session_exists_refused(self):
        self.hospital.provider_session_id = s3.FAKE_SESSION_ID
        with self.assertRaisesRegex(s3.S3Refusal, "requires resume"):
            self.sup.run()
        self.assertFalse(self.hospital.outgoing)

    def test_wrong_patient_room_or_permissions_rejected(self):
        for field, value in (("room", "R-B"), ("patient", "FOREIGN"),
                             ("permissions", {"READ"}), ("active", False),
                             ("paused", True)):
            original = getattr(self.hospital, field)
            setattr(self.hospital, field, value)
            with self.assertRaises(s3.S3Refusal):
                self.sup.run()
            setattr(self.hospital, field, original)
        self.assertFalse(self.hospital.outgoing)
        self.assertFalse(ControlledFakeBroker.instances)

    def test_broker_start_failure_is_before_persistence(self):
        ControlledFakeBroker.fail_stage = "start"
        with self.assertRaisesRegex(s3.S3Refusal, "startup refused"):
            self.sup.run()
        self.assertFalse(self.hospital.outgoing)
        self.assertEqual(self.service.calls, 0)
        self.assertNotIn("turn.started", [x["event"] for x in self.hospital.events])
        self.assertTrue(ControlledFakeBroker.instances[0].stopped)

    def test_revocation_after_readiness_denies_before_persistence(self):
        with self.assertRaisesRegex(s3.S3Refusal, "current Room"):
            self.sup.run(on_ready=self.hospital.revoke)
        self.assertFalse(self.hospital.outgoing)
        self.assertEqual(self.service.calls, 0)
        self.assertNotIn("turn.started", [x["event"] for x in self.hospital.events])

    def test_unavailable_audit_sink_refuses_before_launch(self):
        self.hospital.audit_enabled = False
        with self.assertRaisesRegex(s3.S3Refusal, "audit sink unavailable"):
            self.sup.run()
        self.assertFalse(ControlledFakeBroker.instances)
        self.assertFalse(self.hospital.outgoing)

    def test_unknown_model_task_cannot_reach_broker(self):
        with self.assertRaisesRegex(s3.S3Refusal, "unsupported model tool request"):
            self.sup.run(proposed_task="sh -c 'cat /private/auth'")
        self.assertEqual(len(self.hospital.outgoing), 1)
        self.assertEqual(ControlledFakeBroker.instances[0].executions, 0)
        self.assertEqual(self.hospital.state, "FAILED")

    def test_revoke_queued_request_before_broker_dispatch(self):
        with self.assertRaisesRegex(s3.S3Refusal, "current Room"):
            self.sup.run(before_dispatch=self.hospital.revoke)
        self.assertEqual(ControlledFakeBroker.instances[0].executions, 0)
        self.assertEqual(self.hospital.state, "FAILED")
        self.assertNotIn("turn.completed", [x["event"] for x in self.hospital.events])

    def test_revoke_running_request_discards_result(self):
        with self.assertRaisesRegex(s3.S3Refusal, "revoked broker interrupted"):
            self.sup.run(on_dispatched=self.hospital.revoke)
        self.assertEqual(ControlledFakeBroker.instances[0].executions, 1)
        self.assertEqual(self.hospital.state, "FAILED")
        self.assertEqual(self.hospital.provider_session_id, "")
        self.assertNotIn("turn.completed", [x["event"] for x in self.hospital.events])

    def test_broker_execution_failure_is_failed_accepted_attempt(self):
        ControlledFakeBroker.fail_stage = "execute"
        with self.assertRaisesRegex(s3.S3Refusal, "child failure"):
            self.sup.run()
        self.assertEqual(len(self.hospital.outgoing), 1)
        self.assertEqual(self.hospital.state, "FAILED")
        self.assertEqual(self.hospital.provider_session_id, "")

    def test_sandbox_unavailable_is_fail_closed_before_persistence(self):
        with mock.patch.object(s1, "trusted_bwrap_binary",
                               side_effect=s1.IsolationUnavailable("fake inaccessible")):
            # S3 loads the accepted S1 fixture independently: patch loader seam instead.
            original = s3.accepted
            def replaced(name):
                if name == s3.S1_NAME:
                    return s1
                return original(name)
            with mock.patch.object(s3, "accepted", side_effect=replaced):
                with self.assertRaisesRegex(s3.S3Refusal, "prerequisite refused"):
                    self.sup.run()
        self.assertFalse(self.hospital.outgoing)
        self.assertFalse(ControlledFakeBroker.instances)

    def test_broker_grant_replay_refused(self):
        broker = ControlledFakeBroker(self.root)
        broker.start()
        grant = s3.ToolGrant("FAKE-NONCE-EXAMPLE-123456789", "R-A",
                              "SYNTHETIC-PATIENT", 1, s3.TASK)
        with self.assertRaisesRegex(s3.S3Refusal, "missing PX grant"):
            broker.dispatch(grant)
        broker.grant(grant)
        broker.dispatch(grant)
        broker.collect(grant)
        with self.assertRaisesRegex(s3.S3Refusal, "missing PX grant"):
            broker.dispatch(grant)
        broker.close()

    def test_no_host_environment_leak_to_bwrap_launcher(self):
        source = (HERE / "px_exec_s3_fake.py").read_text()
        self.assertNotIn("os.environ.copy()", source)
        self.assertNotIn("shell=True", source)
        self.assertIn("pass_fds=(write_fd,)", source)
        self.assertIn("close_fds=True", source)
        self.assertEqual(s3.ALLOWED_TASKS, frozenset((s3.TASK, s3.WAIT_TASK)))

    def test_fake_auth_bad_permissions_refused_before_message(self):
        (self.root / "private" / s2.FAKE_AUTH_FILENAME).chmod(0o644)
        with self.assertRaisesRegex(s3.S3Refusal, "prerequisite refused"):
            self.sup.run()
        self.assertEqual(self.service.calls, 0)
        self.assertEqual(self.hospital.outgoing, [])

    def test_patient_fixture_swapped_refused_before_message(self):
        (self.root / "patient" / "fixture.txt").write_text("FOREIGN-PATIENT")
        with self.assertRaisesRegex(s3.S3Refusal, "wrong Patient"):
            self.sup.run()
        self.assertEqual(self.hospital.outgoing, [])


def smoke():
    with tempfile.TemporaryDirectory(prefix="px-exec-s3-real-bwrap-") as temp:
        root, service = fixture_root(temp)
        hospital = s3.FakeHospital()
        supervisor = s3.FakePXSupervisor(hospital, root, service)
        first = supervisor.run()
        second = supervisor.run(resume=True)
        if first["state"] != "PASS" or second["state"] != "PASS":
            raise s3.S3Refusal("S3: start or resume failed")
        if len(hospital.outgoing) != 2 or service.calls != 2:
            raise s3.S3Refusal("S3: accepted turn persistence mismatch")
        if hospital.provider_session_id != s3.FAKE_SESSION_ID:
            raise s3.S3Refusal("S3: fake native session not preserved")
        # The *Hospital itself* revokes a long-running brokered tool;
        # do not route through the supervisor convenience wrapper.
        (root / "scratch" / "s3-result.txt").unlink(missing_ok=True)
        try:
            supervisor.run(resume=True, proposed_task=s3.WAIT_TASK,
                           on_dispatched=hospital.revoke)
        except s3.S3Refusal as exc:
            if hospital.active or not hospital.paused:
                raise s3.S3Refusal(
                    "S3: revocation not reached; prior refusal: " + str(exc)) from exc
        else:
            raise s3.S3Refusal("S3: revocation failed open")
        if (root / "scratch" / "s3-result.txt").exists():
            raise s3.S3Refusal("S3: revoked tool wrote after kill")
        if hospital.state != "FAILED" or service.calls != 3:
            raise s3.S3Refusal(
                "S3: revoked session state unexpected: " +
                hospital.state + ", fake calls=" + str(service.calls))
        if not hospital.paused or hospital.active:
            raise s3.S3Refusal("S3: authority not revoked")
        if len(hospital.outgoing) != 3:
            raise s3.S3Refusal("S3: unexpected outgoing persistence")
        audit_events = [e["event"] for e in hospital.events]
        if ("isolation.authority.revoked" not in audit_events
                or "isolation.tool.interrupted" not in audit_events
                or audit_events.count("turn.completed") != 2
                or hospital.active_brokers):
            raise s3.S3Refusal("S3: direct Hospital revocation audit incomplete")
        if (root / "patient" / "illegal.txt").exists():
            raise s3.S3Refusal("S3: patient mutation observed")
        return {
            "state": "PASS", "profile": "EXEC-S3-OFFLINE-FAKE-PX-SUPERVISOR",
            "fakeModelCalls": service.calls, "acceptedOutgoing": len(hospital.outgoing),
            "startPass": True, "resumePass": True, "activeRevocationPass": True,
            "osReadyFromBwrapInfoFd": True, "independentNamespaceChecks": ["net", "mnt"],
            "realModelCalls": 0, "realCredentialsUsed": False,
            "liveHospitalAccess": False, "productionReady": False,
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    options = ap.add_mutually_exclusive_group(required=True)
    options.add_argument("--unit", action="store_true")
    options.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.unit:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(S3PolicyTests))
        return 0 if result.wasSuccessful() else 1
    try:
        print(json.dumps(smoke(), sort_keys=True, indent=2))
    except (s3.S3Refusal, s2.BoundaryRefusal, s1.IsolationUnavailable, OSError) as exc:
        print("S3 FAKE SMOKE REFUSED: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
