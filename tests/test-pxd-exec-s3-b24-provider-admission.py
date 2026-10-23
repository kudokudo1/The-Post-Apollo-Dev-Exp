#!/usr/bin/env python3
"""B24 provider policy: synthetic input only, never native providers."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_provider_admission import assess, require_secure_admission


def synthetic(provider="codex", resume=False):
    return {
        "version": 1, "providerId": provider, "profile": "EXEC_S3_MODEL_ONLY_V1",
        "identity": {"absolutePath": "/fixture/provider", "version": "fixture-1",
                     "binarySha256": "a"*64, "configSha256": "b"*64,
                     "argsSha256": "c"*64, "executorPinned": True},
        "tools": {"nativeDisabled": True, "mcpDisabled": True,
                  "hooksDisabled": True, "pluginsDisabled": True,
                  "browserDisabled": True, "delegationDisabled": True},
        "credentials": {"envAllowlisted": True, "noToolSecrets": True,
                        "noHostHome": True, "fdsClosed": True,
                        "noAmbientSockets": True, "toolEgressDenied": True},
        "ownership": {"kind": "PX_TURN_SCOPED", "sharedGateway": False,
                      "turnStopVerified": True, "descendantsReaped": True,
                      "revocationFenced": True},
        "resume": {"requested": resume, "nativeStatePinned": resume,
                   "capabilitiesRechecked": resume},
        "authority": {"room": "R", "patient": "P", "assignment": "A",
                      "bed": "/fixture/bed", "turnId": "T", "generation": 1},
        "provenance": {"origin": "UNTRUSTED_SYNTHETIC_FIXTURE",
                       "kernelAttested": False, "realProviderObserved": False},
    }


class B24DefaultDenyTests(unittest.TestCase):
    def denied(self, document, reason=None):
        proof = assess(document)
        self.assertEqual(proof["decision"], "DENY")
        self.assertFalse(proof["launchAuthorized"])
        self.assertFalse(proof["productionReady"])
        self.assertEqual(proof["modelCalls"], 0)
        self.assertEqual(proof["toolCalls"], 0)
        self.assertEqual(proof["hospitalWrites"], 0)
        self.assertIn("REAL_PROVIDER_PRODUCTION_HOLD", proof["reasons"])
        if reason:
            self.assertIn(reason, proof["reasons"])
        return proof

    def test_perfect_synthetic_codex_stays_denied(self):
        self.assertEqual(self.denied(synthetic())["reasons"],
                         ["REAL_PROVIDER_PRODUCTION_HOLD"])

    def test_perfect_synthetic_hermes_stays_denied(self):
        self.assertEqual(self.denied(synthetic("hermes"))["reasons"],
                         ["REAL_PROVIDER_PRODUCTION_HOLD"])

    def test_fully_pinned_resume_is_still_denied(self):
        self.assertEqual(self.denied(synthetic(resume=True))["reasons"],
                         ["REAL_PROVIDER_PRODUCTION_HOLD"])

    def test_unknown_and_fake_provider_not_promotable(self):
        for provider in ("int1-fake", "fake", "", "codex-v2"):
            with self.subTest(provider=provider):
                self.denied(synthetic(provider), "UNKNOWN_PROVIDER")

    def test_unknown_schema_and_operator_override_denied(self):
        record = synthetic()
        record["operatorApproved"] = True
        self.denied(record, "SCHEMA_ROOT")
        record = synthetic()
        record["version"] = 2
        self.denied(record, "SCHEMA_VERSION")

    def test_missing_and_extended_nested_sections_denied(self):
        record = synthetic()
        record.pop("identity")
        self.denied(record, "SCHEMA_IDENTITY")
        record = synthetic()
        record["tools"]["nativeBrowserExtra"] = True
        self.denied(record, "SCHEMA_TOOLS")

    def test_unpinned_binary_config_args_and_executor_denied(self):
        for key in ("binarySha256", "configSha256", "argsSha256"):
            with self.subTest(field=key):
                record = synthetic()
                record["identity"][key] = "a" * 12
                self.denied(record, "PIN_" + key.upper())
        record = synthetic()
        record["identity"]["executorPinned"] = False
        self.denied(record, "EXECUTOR_IDENTITY")

    def test_missing_or_unsafe_executable_path_denied(self):
        for value in ("relative", "/", "/bed/../host", "/bed//host", ""):
            with self.subTest(value=value):
                record = synthetic()
                record["identity"]["absolutePath"] = value
                self.denied(record, "EXECUTABLE_PATH")

    def test_version_missing_or_malformed_denied(self):
        record = synthetic()
        record["identity"]["version"] = ""
        self.denied(record, "BINARY_VERSION")

    def test_native_tool_mcp_hooks_plugins_browser_delegation_denied(self):
        for field in synthetic()["tools"]:
            with self.subTest(field=field):
                record = synthetic()
                record["tools"][field] = False
                self.denied(record, "NATIVE_TOOL_" + field.upper())

    def test_credential_env_fd_socket_network_denied(self):
        for field in synthetic()["credentials"]:
            with self.subTest(field=field):
                record = synthetic()
                record["credentials"][field] = 1
                self.denied(record, "CREDENTIAL_" + field.upper())

    def test_shared_gateway_rejected(self):
        record = synthetic("hermes")
        record["ownership"]["sharedGateway"] = True
        self.denied(record, "SHARED_GATEWAY")

    def test_unknown_owner_rejected(self):
        record = synthetic("hermes")
        record["ownership"]["kind"] = "SHARED_SYSTEMD_GATEWAY"
        self.denied(record, "EXECUTION_OWNER")

    def test_cancel_descendant_and_revocation_negative_cases(self):
        for key in ("turnStopVerified", "descendantsReaped", "revocationFenced"):
            with self.subTest(field=key):
                record = synthetic()
                record["ownership"][key] = False
                self.denied(record, "CANCEL_" + key.upper())

    def test_resume_capability_or_state_drift_denied(self):
        for key in ("nativeStatePinned", "capabilitiesRechecked"):
            with self.subTest(field=key):
                record = synthetic(resume=True)
                record["resume"][key] = False
                self.denied(record, "RESUME_" + key.upper())

    def test_unrequested_resume_grants_denied(self):
        record = synthetic()
        record["resume"]["nativeStatePinned"] = True
        self.denied(record, "RESUME_NATIVESTATEPINNED")

    def test_authority_room_patient_assignment_bed_turn_generation_denied(self):
        for field in ("room", "patient", "assignment", "bed", "turnId"):
            with self.subTest(field=field):
                record = synthetic()
                record["authority"][field] = ""
                self.denied(record, "AUTHORITY_" + field.upper())
        record = synthetic()
        record["authority"]["generation"] = 0
        self.denied(record, "AUTHORITY_GENERATION")

    def test_self_claimed_kernel_attestation_is_not_authoritative(self):
        for key,value in (("origin","VENDOR_SIGNED"),
                          ("kernelAttested", True),
                          ("realProviderObserved", True)):
            with self.subTest(key=key):
                record = synthetic()
                record["provenance"][key] = value
                self.denied(record, "UNTRUSTED_ATTESTATION")

    def test_dispatch_api_always_raises(self):
        for provider in ("codex","hermes"):
            with self.subTest(provider=provider):
                with self.assertRaisesRegex(RuntimeError, "PRODUCTION_HOLD"):
                    require_secure_admission(synthetic(provider))

    def test_pure_no_process_no_filesystem_no_mutation(self):
        record = synthetic()
        original = copy.deepcopy(record)
        with patch("subprocess.Popen", side_effect=AssertionError("Popen")):
            with patch("subprocess.run", side_effect=AssertionError("run")):
                with patch("builtins.open", side_effect=AssertionError("open")):
                    first = self.denied(record)
                    self.assertEqual(first, self.denied(record))
        self.assertEqual(record, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
