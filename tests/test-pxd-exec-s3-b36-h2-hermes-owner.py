#!/usr/bin/env python3
"""B36-H2 disposable fake-owner lifecycle; never launch Hermes."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import px_s3_b36_h2_hermes_owner_lifecycle as h2


def scope():
    return {"patient": "Patient-A", "room": "Room-A", "assignment": "Assign-A",
            "session": "Session-A", "turn": "Turn-A", "generation": 2}


def seed():
    return h2.new_fixture(scope(), "fake-gateway-A")


def event(kind, state, receipt="NONE"):
    seq = state["sequence"] + 1
    return {"kind": kind, "scope": copy.deepcopy(state["scope"]),
            "ownerId": state["ownerId"], "sequence": seq,
            "eventId": f"fake-event-{seq}", "receipt": receipt}


def step(state, kind, receipt="NONE"):
    return h2.assess_transition(state, event(kind, state, receipt))


class B36H2Tests(unittest.TestCase):
    def no_real(self, result):
        self.assertEqual(result["decision"], "DENY")
        for key in ("realGatewayLaunched", "realGatewayStopped", "terminationVerified",
                    "launchAuthorized", "resumeAuthorized", "productionReady"):
            self.assertFalse(result[key])
        for key in ("modelCalls", "toolCalls", "gatewayCalls", "hospitalWrites"):
            self.assertEqual(result[key], 0)
        for reason in ("REAL_PROVIDER_PRODUCTION_HOLD", "TRUSTED_HOSPITAL_OWNER_UNAVAILABLE"):
            self.assertIn(reason, result["reasons"])

    def advanced(self, state, kind, receipt="NONE", phase=None):
        r = step(state, kind, receipt)
        self.no_real(r)
        self.assertEqual(r["fixtureOutcome"], "SIMULATED_STEP")
        if phase is not None:
            self.assertEqual(r["nextState"]["phase"], phase)
        return r["nextState"]

    def test_seed_is_idle(self):
        self.assertEqual((seed()["phase"], seed()["sequence"]), ("UNALLOCATED", 0))

    def test_seed_scope_is_copied(self):
        s = scope()
        f = h2.new_fixture(s, "fake-gateway-A")
        s["room"] = "attacker"
        self.assertEqual(f["scope"]["room"], "Room-A")

    def test_invalid_seed_scope(self):
        for s in ({}, None, {**scope(), "generation": True}):
            with self.subTest(s=s), self.assertRaises(ValueError):
                h2.new_fixture(s, "fake-gateway-A")

    def test_real_owner_and_empty_fake_owner_rejected(self):
        for owner in ("hermes-gateway.service", "1493", "", None, "fake-gateway-"):
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                h2.new_fixture(scope(), owner)

    def test_reserve_simulates_not_launches(self):
        state = seed()
        new = self.advanced(state, "RESERVE", phase="RESERVED_FAKE")
        self.assertEqual(state["phase"], "UNALLOCATED")
        self.assertEqual(new["sequence"], 1)

    def test_ordered_stop_flow_remains_fake(self):
        state = seed()
        for kind, receipt, phase in (
            ("RESERVE", "NONE", "RESERVED_FAKE"),
            ("REQUEST_STOP", "NONE", "STOP_REQUESTED_FAKE"),
            ("ACK_STOP", "FAKE_GATEWAY_ACK", "ACK_OBSERVED_FAKE"),
            ("OBSERVE_EXIT", "FAKE_KERNEL_CGROUP_EMPTY", "CLOSED_FAKE"),
        ):
            state = self.advanced(state, kind, receipt, phase)
        self.assertEqual(state["sequence"], 4)

    def test_ack_before_request_denied(self):
        f = self.advanced(seed(), "RESERVE")
        r = step(f, "ACK_STOP", "FAKE_GATEWAY_ACK")
        self.assertIn("LIFECYCLE_ORDER", r["reasons"])
        self.assertEqual(r["nextState"], f)

    def test_exit_before_ack_denied(self):
        f = self.advanced(self.advanced(seed(), "RESERVE"), "REQUEST_STOP")
        self.assertIn("LIFECYCLE_ORDER", step(f, "OBSERVE_EXIT", "FAKE_KERNEL_CGROUP_EMPTY")["reasons"])

    def test_ack_is_not_stop_proof(self):
        f = self.advanced(self.advanced(seed(), "RESERVE"), "REQUEST_STOP")
        r = step(f, "ACK_STOP", "FAKE_GATEWAY_ACK")
        self.assertEqual(r["nextState"]["phase"], "ACK_OBSERVED_FAKE")
        self.assertFalse(r["terminationVerified"])

    def test_ack_without_receipt_refused(self):
        f = self.advanced(self.advanced(seed(), "RESERVE"), "REQUEST_STOP")
        self.assertIn("RECEIPT_MISMATCH", step(f, "ACK_STOP")["reasons"])

    def test_exit_with_ack_receipt_refused(self):
        f = seed()
        for k, receipt in (("RESERVE", "NONE"), ("REQUEST_STOP", "NONE"), ("ACK_STOP", "FAKE_GATEWAY_ACK")):
            f = self.advanced(f, k, receipt)
        self.assertIn("RECEIPT_MISMATCH", step(f, "OBSERVE_EXIT", "FAKE_GATEWAY_ACK")["reasons"])

    def test_closed_never_reenters(self):
        f = seed()
        for k, receipt in (("RESERVE", "NONE"), ("REQUEST_STOP", "NONE"),
                           ("ACK_STOP", "FAKE_GATEWAY_ACK"), ("OBSERVE_EXIT", "FAKE_KERNEL_CGROUP_EMPTY")):
            f = self.advanced(f, k, receipt)
        self.assertIn("TERMINAL_FIXTURE_NO_REENTRY", step(f, "RESERVE")["reasons"])

    def test_revocation_quarantines_not_stops(self):
        f = self.advanced(seed(), "RESERVE")
        r = step(f, "REVOKE")
        self.assertEqual(r["nextState"]["phase"], "QUARANTINED_FAKE")
        self.assertFalse(r["terminationVerified"])

    def test_crash_unknown_quarantines(self):
        f = self.advanced(seed(), "RESERVE")
        r = step(f, "CRASH_UNKNOWN")
        self.assertEqual(r["nextState"]["phase"], "QUARANTINED_FAKE")
        self.no_real(r)

    def test_native_auto_resume_forbidden_and_quarantined(self):
        f = self.advanced(seed(), "RESERVE")
        r = step(f, "NATIVE_AUTO_RESUME")
        self.assertEqual(r["fixtureOutcome"], "SIMULATED_QUARANTINE")
        self.assertIn("NATIVE_AUTOMATIC_REPLAY_FORBIDDEN", r["reasons"])
        self.assertEqual(r["nextState"]["phase"], "QUARANTINED_FAKE")

    def test_platform_reconnect_forbidden_and_quarantined(self):
        r = step(self.advanced(seed(), "RESERVE"), "PLATFORM_RECONNECT")
        self.assertIn("NATIVE_AUTOMATIC_REPLAY_FORBIDDEN", r["reasons"])
        self.assertEqual(r["nextState"]["phase"], "QUARANTINED_FAKE")

    def test_quarantine_is_terminal(self):
        f = step(seed(), "REVOKE")["nextState"]
        self.assertIn("TERMINAL_FIXTURE_NO_REENTRY", step(f, "RESERVE")["reasons"])

    def test_scope_mismatch_six_fields(self):
        f = seed()
        for key in scope():
            e = event("RESERVE", f)
            e["scope"][key] = (3 if key == "generation" else "foreign")
            with self.subTest(key=key):
                r = h2.assess_transition(f, e)
                self.assertIn("HOSPITAL_SCOPE_MISMATCH", r["reasons"])
                self.assertEqual(r["nextState"], f)

    def test_different_owner_refused(self):
        f = seed()
        e = event("RESERVE", f)
        e["ownerId"] = "fake-gateway-B"
        self.assertIn("OWNER_IDENTITY_MISMATCH", h2.assess_transition(f, e)["reasons"])

    def test_duplicate_sequence_and_event_id(self):
        f = self.advanced(seed(), "RESERVE")
        e = event("REQUEST_STOP", f)
        e["sequence"] = f["sequence"]
        e["eventId"] = f["lastEventId"]
        r = h2.assess_transition(f, e)
        self.assertIn("SEQUENCE_REPLAY_OR_GAP", r["reasons"])
        self.assertIn("EVENT_REPLAY", r["reasons"])

    def test_sequence_gap_refused(self):
        f = seed()
        e = event("RESERVE", f)
        e["sequence"] = 7
        self.assertIn("SEQUENCE_REPLAY_OR_GAP", h2.assess_transition(f, e)["reasons"])

    def test_invalid_prior_state_refused(self):
        f = seed()
        f["sequence"] = True
        r = h2.assess_transition(f, event("RESERVE", seed()))
        self.assertIn("INVALID_PRIOR_FIXTURE", r["reasons"])
        self.assertIsNone(r["nextState"])

    def test_forged_phase_without_lifecycle_event_refused(self):
        f = seed()
        f["phase"] = "RESERVED_FAKE"
        out = h2.assess_transition(f, event("REQUEST_STOP", seed()))
        self.assertIn("INVALID_PRIOR_FIXTURE", out["reasons"])
        self.assertIsNone(out["nextState"])

    def test_bad_event_schema_receipt_and_kind(self):
        f = seed()
        for change, why in (({"extra": "x"}, "EVENT_SCHEMA"),
                            ({"receipt": "REAL_KERNEL_PROOF"}, "RECEIPT_KIND"),
                            ({"kind": "RUN_HERMES"}, "EVENT_KIND")):
            e = event("RESERVE", f)
            e.update(change)
            with self.subTest(change=change):
                self.assertIn(why, h2.assess_transition(f, e)["reasons"])

    def test_no_process_files_network_secrets_mutation(self):
        f = seed()
        e = event("RESERVE", f)
        a, b = copy.deepcopy(f), copy.deepcopy(e)
        with patch("subprocess.Popen", side_effect=AssertionError("Popen")):
            with patch("subprocess.run", side_effect=AssertionError("run")):
                with patch("builtins.open", side_effect=AssertionError("open")):
                    with patch("socket.socket", side_effect=AssertionError("socket")):
                        r = h2.assess_transition(f, e)
        self.no_real(r)
        self.assertEqual((f, e), (a, b))

    def test_real_gateway_admission_always_denied(self):
        with self.assertRaisesRegex(RuntimeError, "REAL_PROVIDER_PRODUCTION_HOLD"):
            h2.require_real_gateway_owner(seed(), event("RESERVE", seed()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
