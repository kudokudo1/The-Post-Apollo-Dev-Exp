#!/usr/bin/env python3
"""B36 isolated fixture-only Hermes recovery/authority gate checks."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b36_hermes_recovery_fence import assess, require_hermes_recovery_admission, SCHEMA


def scope():
    return {"patient": "P", "room": "R", "assignment": "A", "session": "S",
            "turn": "T", "generation": 3}


def fixture(trigger="NEW_MESSAGE", reason="NONE"):
    return {
        "schema": SCHEMA, "provider": "hermes", "trigger": trigger,
        "resumeReason": reason, "scope": scope(),
        "gateway": {"dedicated": True, "sharedGateway": False,
                    "autoContinueDisabled": True, "nativeToolsDisabled": True,
                    "ownerVerified": True, "turnStopVerified": True,
                    "descendantsTerminated": True, "credentialsConfined": True,
                    "revocationFenced": True},
        "cancellation": "NONE",
    }


class HermesB36OfflineFenceTests(unittest.TestCase):
    def denied(self, candidate=None, expected=None, reason=None):
        result = assess(fixture() if candidate is None else candidate,
                        scope() if expected is None else expected)
        self.assertEqual(result["decision"], "DENY")
        self.assertFalse(result["launchAuthorized"])
        self.assertFalse(result["resumeAuthorized"])
        self.assertFalse(result["productionReady"])
        self.assertEqual(result["gatewayCalls"], 0)
        self.assertEqual(result["modelCalls"], 0)
        self.assertEqual(result["hospitalWrites"], 0)
        self.assertEqual(result["toolGrants"], 0)
        self.assertIn("REAL_PROVIDER_PRODUCTION_HOLD", result["reasons"])
        self.assertIn("TRUSTED_HOSPITAL_AUTHORITY_UNAVAILABLE", result["reasons"])
        if reason:
            self.assertIn(reason, result["reasons"])
        return result

    def test_even_synthetic_perfect_explicit_turn_denied(self):
        self.denied()

    def test_startup_resume_forbidden_all_three_reasons(self):
        for reason in ("restart_timeout", "shutdown_timeout", "restart_interrupted"):
            with self.subTest(reason=reason):
                self.denied(fixture("STARTUP_AUTO_RESUME", reason), reason="AUTOMATIC_RESUME_FORBIDDEN")

    def test_platform_reconnect_resume_forbidden(self):
        self.denied(fixture("PLATFORM_RECONNECT", "restart_interrupted"),
                    reason="AUTOMATIC_RESUME_FORBIDDEN")

    def test_manual_recovery_not_new_authority(self):
        self.denied(fixture("MANUAL_RECOVERY", "restart_timeout"),
                    reason="EXPLICIT_NEW_TURN_REQUIRED")

    def test_new_message_cannot_smuggle_pending_recovery(self):
        self.denied(fixture("NEW_MESSAGE", "restart_timeout"),
                    reason="RESTART_RECOVERY_MASQUERADES_AS_NEW_TURN")

    def test_auto_resume_none_reason_refused(self):
        self.denied(fixture("STARTUP_AUTO_RESUME", "NONE"),
                    reason="RECOVERY_REASON_MISMATCH")

    def test_invalid_reasons_and_triggers(self):
        for key, value, reason in (("trigger", "AUTO", "TRIGGER_INVALID"),
                                   ("trigger", None, "TRIGGER_INVALID"),
                                   ("resumeReason", "from_webhook", "RECOVERY_REASON_INVALID"),
                                   ("resumeReason", None, "RECOVERY_REASON_INVALID")):
            rec = fixture()
            rec[key] = value
            with self.subTest(key=key, value=value):
                self.denied(rec, reason=reason)

    def test_cross_room_patient_assignment_session_turn_and_generation(self):
        for field in scope():
            rec = fixture()
            rec["scope"][field] = (8 if field == "generation" else "OTHER")
            with self.subTest(field=field):
                self.denied(rec, reason="AUTHORITY_" + field.upper() + "_MISMATCH")

    def test_stale_and_negative_generation_refused(self):
        for val in (0, -1, True, "3", None):
            rec = fixture()
            rec["scope"]["generation"] = val
            with self.subTest(val=val):
                self.denied(rec, reason="SCOPE_INVALID")

    def test_missing_empty_overlong_scope_fields(self):
        for val in ("", "  ", "X" * 257, None):
            rec = fixture()
            rec["scope"]["room"] = val
            with self.subTest(val=val):
                self.denied(rec, reason="SCOPE_INVALID")

    def test_expected_authority_missing_invalid_or_untrusted(self):
        for val in (None, [], {"patient": "P"}, {**scope(), "generation": False}):
            rec = fixture()
            got = assess(rec, val)
            self.assertIn("EXPECTED_SCOPE_INVALID", got["reasons"])
            self.assertEqual(got["decision"], "DENY")

    def test_shared_gateway_never_accepted(self):
        rec = fixture()
        rec["gateway"]["sharedGateway"] = True
        self.denied(rec, reason="DEDICATED_GATEWAY_UNVERIFIED")

    def test_missing_dedicated_flag_refused(self):
        rec = fixture()
        rec["gateway"]["dedicated"] = False
        self.denied(rec, reason="DEDICATED_GATEWAY_UNVERIFIED")

    def test_auto_continue_enabled_refused(self):
        rec = fixture()
        rec["gateway"]["autoContinueDisabled"] = False
        self.denied(rec, reason="GATEWAY_AUTOCONTINUEDISABLED_UNVERIFIED")

    def test_every_gateway_control_false_is_refused(self):
        for key in fixture()["gateway"]:
            if key in ("sharedGateway", "dedicated"):
                continue
            rec = fixture()
            rec["gateway"][key] = False
            with self.subTest(key=key):
                self.denied(rec, reason="GATEWAY_" + key.upper() + "_UNVERIFIED")

    def test_unrecognized_gateway_options_refused(self):
        rec = fixture()
        rec["gateway"]["allowNativeToolsAnyway"] = True
        self.denied(rec, reason="GATEWAY_SCHEMA")

    def test_all_cancellation_states_except_none_require_reconciliation(self):
        for state in ("REQUESTED", "ACKNOWLEDGED", "TERMINATED_VERIFIED", "UNVERIFIED"):
            rec = fixture()
            rec["cancellation"] = state
            with self.subTest(state=state):
                self.denied(rec, reason="CANCELLATION_RECONCILIATION_REQUIRED")

    def test_bad_cancellation_state_refused(self):
        rec = fixture()
        rec["cancellation"] = "SUCCESS"
        self.denied(rec, reason="CANCELLATION_STATE_INVALID")

    def test_schema_and_provider_spoof_refused(self):
        for key, val, reason in (("schema", "V2", "SCHEMA_VERSION"),
                                 ("provider", "codex", "PROVIDER_IDENTITY")):
            rec = fixture()
            rec[key] = val
            self.denied(rec, reason=reason)

    def test_extra_root_and_missing_sections_refused(self):
        rec = fixture()
        rec["operatorApproved"] = True
        self.denied(rec, reason="SCHEMA_ROOT")
        rec = fixture()
        del rec["gateway"]
        self.denied(rec, reason="GATEWAY_SCHEMA")

    def test_arbitrary_input_stable_bounded_no_sensitive_echo(self):
        val = {"secret_token": "DONT_ECHO", "scope": "bad"}
        result = self.denied(val, reason="SCHEMA_ROOT")
        self.assertNotIn("DONT_ECHO", str(result))
        self.assertEqual(result, self.denied(val))

    def test_input_immutable_and_zero_side_effects(self):
        val = fixture("STARTUP_AUTO_RESUME", "restart_interrupted")
        before = copy.deepcopy(val)
        with patch("subprocess.Popen", side_effect=AssertionError("Popen")):
            with patch("subprocess.run", side_effect=AssertionError("run")):
                with patch("builtins.open", side_effect=AssertionError("open")):
                    with patch("socket.socket", side_effect=AssertionError("socket")):
                        self.denied(val, reason="AUTOMATIC_RESUME_FORBIDDEN")
        self.assertEqual(val, before)

    def test_enforcement_api_always_refuses(self):
        for rec in (fixture(), fixture("STARTUP_AUTO_RESUME", "restart_timeout")):
            with self.assertRaisesRegex(RuntimeError, "REAL_PROVIDER_PRODUCTION_HOLD"):
                require_hermes_recovery_admission(rec, scope())


if __name__ == "__main__":
    unittest.main(verbosity=2)
