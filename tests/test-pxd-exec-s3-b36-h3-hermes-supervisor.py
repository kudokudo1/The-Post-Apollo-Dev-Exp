#!/usr/bin/env python3
"""B36-H3 trusted-supervisor offline gate tests."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b36_h3_hermes_supervisor import assess, require_supervisor_admission, SCHEMA


def scope():
    return {"patient": "P", "room": "R", "assignment": "A", "session": "S",
            "turn": "T", "generation": 7}


def candidate(intent="CANCEL_CURRENT_TURN"):
    has_stop = intent != "NONE"
    return {
        "schema": SCHEMA,
        "provider": "hermes",
        "scope": scope(),
        "supervisor": {
            "supervisorId": "px-supervisor-fixture-001",
            "hospitalAuthorityFresh": True,
            "authorityGeneration": 7,
            "dedicatedGateway": True,
            "gatewayIdentityVerified": True,
            "restartFenced": True,
            "nativeToolsDisabled": True,
            "credentialsConfined": True,
        },
        "stop": {
            "intent": intent,
            "requestId": "stop-fixture-001",
            "gatewayAck": "STOP_ACK" if has_stop else "NONE",
            "gatewayAckAuthenticated": has_stop,
            "kernelEvidenceId": "kernel-fixture-001" if has_stop else "",
            "descendantsEmpty": has_stop,
            "observedGeneration": 7,
        },
    }


class HermesH3SupervisorOfflineTests(unittest.TestCase):
    def denied(self, rec=None, expected=None, generation=7, reason=None):
        got = assess(candidate() if rec is None else rec,
                     scope() if expected is None else expected,
                     generation)
        self.assertEqual(got["decision"], "DENY")
        self.assertFalse(got["launchAuthorized"])
        self.assertFalse(got["resumeAuthorized"])
        self.assertFalse(got["terminationVerified"])
        self.assertFalse(got["gatewayAckTrusted"])
        self.assertFalse(got["kernelEvidenceTrusted"])
        self.assertFalse(got["productionReady"])
        self.assertEqual(got["modelCalls"], 0)
        self.assertEqual(got["toolCalls"], 0)
        self.assertEqual(got["gatewayCalls"], 0)
        self.assertEqual(got["hospitalWrites"], 0)
        self.assertIn("TRUSTED_SUPERVISOR_RUNTIME_UNAVAILABLE", got["reasons"])
        self.assertIn("KERNEL_ATTESTATION_UNAVAILABLE", got["reasons"])
        self.assertIn("REAL_PROVIDER_PRODUCTION_HOLD", got["reasons"])
        if reason:
            self.assertIn(reason, got["reasons"])
        return got

    def test_synthetic_perfect_supervisor_still_denied(self):
        self.denied()

    def test_none_stop_intent_is_also_denied(self):
        self.denied(candidate("NONE"))

    def test_all_six_hospital_scope_mismatches(self):
        for key in scope():
            rec = candidate()
            rec["scope"][key] = 8 if key == "generation" else "OTHER"
            with self.subTest(key=key):
                self.denied(rec, reason="AUTHORITY_" + key.upper() + "_MISMATCH")

    def test_expected_scope_invalid(self):
        self.denied(expected={"patient": "P"}, reason="EXPECTED_SCOPE_INVALID")

    def test_expected_generation_invalid(self):
        for val in (0, -1, True, "7", None):
            with self.subTest(val=val):
                self.denied(generation=val, reason="EXPECTED_GENERATION_INVALID")

    def test_supervisor_generation_mismatch(self):
        rec = candidate()
        rec["supervisor"]["authorityGeneration"] = 6
        self.denied(rec, reason="SUPERVISOR_GENERATION_MISMATCH")

    def test_observed_generation_mismatch(self):
        rec = candidate()
        rec["stop"]["observedGeneration"] = 6
        self.denied(rec, reason="OBSERVED_GENERATION_MISMATCH")

    def test_fresh_hospital_authority_required(self):
        rec = candidate()
        rec["supervisor"]["hospitalAuthorityFresh"] = False
        self.denied(rec, reason="HOSPITAL_AUTHORITY_NOT_FRESH")

    def test_supervisor_identity_required(self):
        rec = candidate()
        rec["supervisor"]["supervisorId"] = "gateway-1"
        self.denied(rec, reason="SUPERVISOR_IDENTITY")

    def test_dedicated_gateway_required(self):
        rec = candidate()
        rec["supervisor"]["dedicatedGateway"] = False
        self.denied(rec, reason="DEDICATED_GATEWAY_UNVERIFIED")

    def test_gateway_identity_required(self):
        rec = candidate()
        rec["supervisor"]["gatewayIdentityVerified"] = False
        self.denied(rec, reason="GATEWAY_IDENTITY_UNVERIFIED")

    def test_restart_fence_required(self):
        rec = candidate()
        rec["supervisor"]["restartFenced"] = False
        self.denied(rec, reason="RESTART_FENCE_UNVERIFIED")

    def test_native_tools_must_be_disabled(self):
        rec = candidate()
        rec["supervisor"]["nativeToolsDisabled"] = False
        self.denied(rec, reason="NATIVE_TOOLS_UNVERIFIED")

    def test_credentials_must_be_confined(self):
        rec = candidate()
        rec["supervisor"]["credentialsConfined"] = False
        self.denied(rec, reason="CREDENTIALS_UNVERIFIED")

    def test_stop_ack_required_for_cancel(self):
        rec = candidate()
        rec["stop"]["gatewayAck"] = "NONE"
        self.denied(rec, reason="STOP_ACK_MISSING")

    def test_stop_ack_must_be_authenticated(self):
        rec = candidate()
        rec["stop"]["gatewayAckAuthenticated"] = False
        self.denied(rec, reason="STOP_ACK_UNAUTHENTICATED")

    def test_kernel_evidence_id_required(self):
        rec = candidate()
        rec["stop"]["kernelEvidenceId"] = ""
        self.denied(rec, reason="KERNEL_EVIDENCE_ID_INVALID")

    def test_descendants_must_be_verified_empty(self):
        rec = candidate()
        rec["stop"]["descendantsEmpty"] = False
        self.denied(rec, reason="DESCENDANTS_NOT_VERIFIED_EMPTY")

    def test_ack_without_stop_intent_refused(self):
        rec = candidate("NONE")
        rec["stop"]["gatewayAck"] = "STOP_ACK"
        self.denied(rec, reason="ACK_WITHOUT_STOP_INTENT")

    def test_kernel_claim_without_stop_intent_refused(self):
        rec = candidate("NONE")
        rec["stop"]["descendantsEmpty"] = True
        self.denied(rec, reason="KERNEL_EVIDENCE_WITHOUT_STOP_INTENT")

    def test_schema_spoof_and_extra_fields_refused(self):
        rec = candidate()
        rec["schema"] = "V2"
        self.denied(rec, reason="SCHEMA_VERSION")
        rec = candidate()
        rec["supervisor"]["autoApprove"] = True
        self.denied(rec, reason="SUPERVISOR_SCHEMA")

    def test_provider_spoof_refused(self):
        rec = candidate()
        rec["provider"] = "codex"
        self.denied(rec, reason="PROVIDER_IDENTITY")

    def test_input_immutable_and_zero_side_effects(self):
        rec = candidate()
        before = copy.deepcopy(rec)
        with patch("subprocess.Popen", side_effect=AssertionError("Popen")):
            with patch("subprocess.run", side_effect=AssertionError("run")):
                with patch("builtins.open", side_effect=AssertionError("open")):
                    with patch("socket.socket", side_effect=AssertionError("socket")):
                        self.denied(rec)
        self.assertEqual(rec, before)

    def test_diagnostics_never_echo_sensitive_candidate_data(self):
        rec = candidate()
        secret = "SENSITIVE_UNTRUSTED_TOKEN_NEVER_EXPOSE"
        rec["untrustedExtra"] = {"bearerToken": secret}
        rec["stop"]["requestId"] = "stop-" + secret
        rec["scope"]["room"] = secret
        result = self.denied(rec, reason="SCHEMA_ROOT")
        self.assertNotIn("candidateSnapshot", result)
        self.assertNotIn(secret, str(result))
        self.assertNotIn("bearerToken", str(result))

    def test_diagnostics_have_only_fixed_bounded_fields(self):
        rec = candidate()
        rec["maliciousPayload"] = "SENSITIVE_LONG_" + ("x" * 250000)
        result = self.denied(rec, reason="SCHEMA_ROOT")
        self.assertEqual(set(result), {
            "schema", "decision", "reasons", "launchAuthorized",
            "resumeAuthorized", "terminationVerified", "gatewayAckTrusted",
            "kernelEvidenceTrusted", "modelCalls", "toolCalls",
            "gatewayCalls", "hospitalWrites", "productionReady",
        })
        self.assertLess(len(str(result)), 1500)

    def test_noncopyable_untrusted_extension_is_not_traversed(self):
        class Hostile:
            def __deepcopy__(self, memo):
                raise AssertionError("Untrusted content must not be deep-copied")
            def __repr__(self):
                raise AssertionError("Untrusted content must not be formatted")

        rec = candidate()
        rec["untrustedExtra"] = Hostile()
        result = self.denied(rec, reason="SCHEMA_ROOT")
        self.assertNotIn("candidateSnapshot", result)

    def test_recursive_untrusted_input_never_escapes_into_output(self):
        rec = candidate()
        rec["untrustedExtra"] = rec
        result = self.denied(rec, reason="SCHEMA_ROOT")
        self.assertNotIn("candidateSnapshot", result)
        import json
        encoded = json.dumps(result)
        self.assertLess(len(encoded), 1500)

    def test_enforcement_api_always_refuses(self):
        with self.assertRaisesRegex(RuntimeError, "REAL_PROVIDER_PRODUCTION_HOLD"):
            require_supervisor_admission(candidate(), scope(), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
