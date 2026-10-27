#!/usr/bin/env python3
"""B36-H4 cross-boundary refusal tests; no Hermes, kernel or Hospital access."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import px_s3_b36_h4_hermes_cross_boundary as h4
from px_s3_b36_hermes_recovery_fence import SCHEMA as H1_SCHEMA
from px_s3_b36_h2_hermes_owner_lifecycle import (
    new_fixture, assess_transition, SCHEMA as H2_SCHEMA,
)
from px_s3_b36_h3_hermes_supervisor import SCHEMA as H3_SCHEMA


def scope():
    return {"patient": "P", "room": "R", "assignment": "A",
            "session": "S", "turn": "T", "generation": 7}


def provider_fixture():
    return {
        "version": 1, "providerId": "hermes", "profile": "EXEC_S3_MODEL_ONLY_V1",
        "identity": {"absolutePath": "/fixture/provider", "version": "fixture-1",
                     "binarySha256": "a" * 64, "configSha256": "b" * 64,
                     "argsSha256": "c" * 64, "executorPinned": True},
        "tools": {"nativeDisabled": True, "mcpDisabled": True, "hooksDisabled": True,
                  "pluginsDisabled": True, "browserDisabled": True,
                  "delegationDisabled": True},
        "credentials": {"envAllowlisted": True, "noToolSecrets": True,
                        "noHostHome": True, "fdsClosed": True,
                        "noAmbientSockets": True, "toolEgressDenied": True},
        "ownership": {"kind": "PX_DEDICATED_GATEWAY", "sharedGateway": False,
                      "turnStopVerified": True, "descendantsReaped": True,
                      "revocationFenced": True},
        "resume": {"requested": False, "nativeStatePinned": False,
                   "capabilitiesRechecked": False},
        "authority": {"room": "R", "patient": "P", "assignment": "A",
                      "bed": "/fixture/bed", "turnId": "T", "generation": 7},
        "provenance": {"origin": "UNTRUSTED_SYNTHETIC_FIXTURE",
                       "kernelAttested": False, "realProviderObserved": False},
    }


def make_case(kind="RESERVE"):
    state = new_fixture(scope(), "fake-gateway-001")
    ordered = ("RESERVE", "REQUEST_STOP", "ACK_STOP", "OBSERVE_EXIT")
    fake_receipts = {
        "RESERVE": "NONE", "REQUEST_STOP": "NONE",
        "ACK_STOP": "FAKE_GATEWAY_ACK", "OBSERVE_EXIT": "FAKE_KERNEL_CGROUP_EMPTY",
    }
    previous = (
        ordered[:ordered.index(kind)] if kind in ordered else ("RESERVE",)
    )
    for action in previous:
        fake_event = {
            "kind": action, "scope": scope(), "ownerId": state["ownerId"],
            "sequence": state["sequence"] + 1,
            "eventId": "fake-event-" + str(state["sequence"] + 1),
            "receipt": fake_receipts[action],
        }
        transition = assess_transition(state, fake_event)
        if transition["fixtureOutcome"] != "SIMULATED_STEP":
            raise AssertionError("Fixture sequencing failed")
        state = transition["nextState"]

    fake_event = {
        "kind": kind, "scope": scope(), "ownerId": state["ownerId"],
        "sequence": state["sequence"] + 1,
        "eventId": "fake-event-" + str(state["sequence"] + 1),
        "receipt": fake_receipts.get(kind, "NONE"),
    }
    is_auto = kind in h4.AUTO_KINDS
    trigger = ("STARTUP_AUTO_RESUME" if kind == "NATIVE_AUTO_RESUME" else
               "PLATFORM_RECONNECT" if kind == "PLATFORM_RECONNECT" else
               "NEW_MESSAGE")
    needs_ack = kind in ("ACK_STOP", "OBSERVE_EXIT")
    needs_kernel = kind == "OBSERVE_EXIT"
    recover = {
        "schema": H1_SCHEMA, "provider": "hermes",
        "trigger": trigger,
        "resumeReason": "restart_interrupted" if is_auto else "NONE",
        "scope": scope(),
        "gateway": {"dedicated": True, "sharedGateway": False,
                    "autoContinueDisabled": True, "nativeToolsDisabled": True,
                    "ownerVerified": True, "turnStopVerified": True,
                    "descendantsTerminated": True, "credentialsConfined": True,
                    "revocationFenced": True},
        "cancellation": h4.H1_CANCEL[kind],
    }
    sup = {
        "schema": H3_SCHEMA, "provider": "hermes", "scope": scope(),
        "supervisor": {"supervisorId": "px-supervisor-fixture-001",
                       "hospitalAuthorityFresh": True,
                       "authorityGeneration": 7,
                       "dedicatedGateway": True,
                       "gatewayIdentityVerified": True,
                       "restartFenced": True,
                       "nativeToolsDisabled": True,
                       "credentialsConfined": True},
        "stop": {"intent": h4.STOP_INTENT[kind],
                 "requestId": "stop-fixture-001",
                 "gatewayAck": "STOP_ACK" if needs_ack else "NONE",
                 "gatewayAckAuthenticated": needs_ack,
                 "kernelEvidenceId": "kernel-fixture-001" if needs_kernel else "",
                 "descendantsEmpty": needs_kernel,
                 "observedGeneration": 7},
    }
    return {
        "schema": h4.SCHEMA, "recovery": recover,
        "ownerState": state, "ownerEvent": fake_event,
        "supervisor": sup, "providerEvidence": provider_fixture(),
    }


_MISSING = object()


class H4OfflineIntegrationTests(unittest.TestCase):
    def denied(self, case=_MISSING, reason=None, fake=None, expected=None, generation=7):
        result = h4.assess(make_case() if case is _MISSING else case,
                           scope() if expected is None else expected, generation)
        self.assertEqual(result["decision"], "DENY")
        self.assertFalse(result["launchAuthorized"])
        self.assertFalse(result["resumeAuthorized"])
        self.assertFalse(result["terminationVerified"])
        self.assertFalse(result["gatewayAckTrusted"])
        self.assertFalse(result["kernelEvidenceTrusted"])
        self.assertFalse(result["productionReady"])
        for key in ("toolGrants", "modelCalls", "gatewayCalls", "toolCalls", "hospitalWrites"):
            self.assertEqual(result[key], 0)
        for required in ("CROSS_GATEWAY_IDENTITY_BINDING_UNAVAILABLE",
                         "TRUSTED_HOSPITAL_AUTHORITY_UNAVAILABLE",
                         "KERNEL_ATTESTATION_UNAVAILABLE",
                         "REAL_PROVIDER_PRODUCTION_HOLD"):
            self.assertIn(required, result["reasons"])
        if reason:
            self.assertIn(reason, result["reasons"])
        if fake:
            self.assertEqual(result["fakeTransition"], fake)
        self.assertNotIn("candidateSnapshot", result)
        self.assertNotIn("nextState", result)
        return result

    def test_perfectly_consistent_fixture_cannot_execute(self):
        self.denied(fake="SIMULATED_STEP")

    def test_reserve_is_only_fake(self):
        self.denied(make_case("RESERVE"), fake="SIMULATED_STEP")

    def test_request_stop_does_not_require_gateway_ack_yet(self):
        self.denied(make_case("REQUEST_STOP"), fake="SIMULATED_STEP")

    def test_gateway_ack_stage_does_not_mean_kernel_exit(self):
        self.denied(make_case("ACK_STOP"), fake="SIMULATED_STEP")

    def test_fake_kernel_receipt_still_never_proves_real_termination(self):
        self.denied(make_case("OBSERVE_EXIT"),
                    reason="FAKE_CGROUP_RECEIPT_NOT_KERNEL_ATTESTATION",
                    fake="SIMULATED_STEP")

    def test_startup_native_replay_quarantines_fake_owner(self):
        self.denied(make_case("NATIVE_AUTO_RESUME"),
                    reason="AUTOMATIC_NATIVE_REPLAY_FORBIDDEN",
                    fake="SIMULATED_QUARANTINE")

    def test_platform_reconnect_quarantines_fake_owner(self):
        self.denied(make_case("PLATFORM_RECONNECT"),
                    reason="AUTOMATIC_NATIVE_REPLAY_FORBIDDEN",
                    fake="SIMULATED_QUARANTINE")

    def test_recovery_trigger_must_match_replay_kind(self):
        c = make_case("NATIVE_AUTO_RESUME")
        c["recovery"]["trigger"] = "PLATFORM_RECONNECT"
        self.denied(c, reason="RECOVERY_TRIGGER_EVENT_MISMATCH")

    def test_undisclosed_native_replay_trigger_refused(self):
        c = make_case()
        c["recovery"]["trigger"] = "STARTUP_AUTO_RESUME"
        self.denied(c, reason="RECOVERY_TRIGGER_EVENT_MISMATCH")

    def test_wrong_recovery_room(self):
        c = make_case()
        c["recovery"]["scope"]["room"] = "foreign"
        self.denied(c, reason="RECOVERY_SCOPE_MISMATCH")

    def test_wrong_h2_owner_state_patient(self):
        c = make_case()
        c["ownerState"]["scope"]["patient"] = "foreign"
        self.denied(c, reason="OWNER_STATE_SCOPE_MISMATCH")

    def test_wrong_owner_event_assignment(self):
        c = make_case()
        c["ownerEvent"]["scope"]["assignment"] = "foreign"
        self.denied(c, reason="OWNER_EVENT_SCOPE_MISMATCH")

    def test_wrong_h3_supervisor_session(self):
        c = make_case()
        c["supervisor"]["scope"]["session"] = "foreign"
        self.denied(c, reason="SUPERVISOR_SCOPE_MISMATCH")

    def test_expected_scope_invalid(self):
        self.denied(expected={"room": "R"}, reason="EXPECTED_SCOPE_INVALID")

    def test_expected_scope_generation_inconsistent(self):
        self.denied(generation=8, reason="EXPECTED_GENERATION_MISMATCH")

    def test_expected_generation_wrong_type(self):
        self.denied(generation=True, reason="EXPECTED_GENERATION_INVALID")

    def test_owner_identity_mismatch(self):
        c = make_case()
        c["ownerEvent"]["ownerId"] = "fake-gateway-002"
        self.denied(c, reason="OWNER_IDENTITY_MISMATCH")

    def test_owner_state_event_scope_cross_mismatch(self):
        c = make_case()
        c["ownerState"]["scope"]["room"] = "P2"
        self.denied(c, reason="OWNER_EVENT_STATE_SCOPE_MISMATCH")

    def test_duplicate_h2_event_refused(self):
        c = make_case("REQUEST_STOP")
        c["ownerEvent"]["sequence"] = c["ownerState"]["sequence"]
        self.denied(c, reason="OWNER_LIFECYCLE_REFUSED", fake="REFUSED")

    def test_terminal_owner_cannot_restart(self):
        c = make_case("OBSERVE_EXIT")
        c["ownerState"] = assess_transition(c["ownerState"], c["ownerEvent"])["nextState"]
        c["ownerEvent"]["sequence"] += 1
        c["ownerEvent"]["eventId"] = "fake-event-5"
        self.denied(c, reason="TERMINAL_OWNER_REENTRY", fake="REFUSED")

    def test_wrong_stop_intent(self):
        c = make_case("REQUEST_STOP")
        c["supervisor"]["stop"]["intent"] = "NONE"
        self.denied(c, reason="STOP_INTENT_STAGE_MISMATCH")

    def test_wrong_cancellation_stage(self):
        c = make_case("ACK_STOP")
        c["recovery"]["cancellation"] = "REQUESTED"
        self.denied(c, reason="CANCELLATION_STAGE_MISMATCH")

    def test_early_gateway_ack_is_not_valid(self):
        c = make_case("REQUEST_STOP")
        c["supervisor"]["stop"]["gatewayAck"] = "STOP_ACK"
        c["supervisor"]["stop"]["gatewayAckAuthenticated"] = True
        self.denied(c, reason="GATEWAY_ACK_STAGE_MISMATCH")

    def test_missing_gateway_ack_at_ack_stage(self):
        c = make_case("ACK_STOP")
        c["supervisor"]["stop"]["gatewayAck"] = "NONE"
        self.denied(c, reason="GATEWAY_ACK_STAGE_MISMATCH")

    def test_early_kernel_claim_refused(self):
        c = make_case("ACK_STOP")
        c["supervisor"]["stop"]["descendantsEmpty"] = True
        c["supervisor"]["stop"]["kernelEvidenceId"] = "kernel-fixture-001"
        self.denied(c, reason="KERNEL_CLAIM_STAGE_MISMATCH")

    def test_missing_kernel_claim_at_exit_stage(self):
        c = make_case("OBSERVE_EXIT")
        c["supervisor"]["stop"]["descendantsEmpty"] = False
        self.denied(c, reason="KERNEL_CLAIM_STAGE_MISMATCH")

    def test_stale_supervisor_generation(self):
        c = make_case()
        c["supervisor"]["supervisor"]["authorityGeneration"] = 6
        self.denied(c, reason="SUPERVISOR_PRECONDITIONS_UNVERIFIED")

    def test_disabled_native_tool_precondition(self):
        c = make_case()
        c["supervisor"]["supervisor"]["nativeToolsDisabled"] = False
        self.denied(c, reason="SUPERVISOR_PRECONDITIONS_UNVERIFIED")

    def test_credentials_not_confined(self):
        c = make_case()
        c["supervisor"]["supervisor"]["credentialsConfined"] = False
        self.denied(c, reason="SUPERVISOR_PRECONDITIONS_UNVERIFIED")

    def test_missing_restart_fence(self):
        c = make_case()
        c["supervisor"]["supervisor"]["restartFenced"] = False
        self.denied(c, reason="SUPERVISOR_PRECONDITIONS_UNVERIFIED")

    def test_fake_revocation_quarantines(self):
        self.denied(make_case("REVOKE"), fake="SIMULATED_STEP")

    def test_crash_unknown_quarantines_without_retry(self):
        self.denied(make_case("CRASH_UNKNOWN"), fake="SIMULATED_STEP")

    def test_b24_native_tool_claim_refused(self):
        c = make_case()
        c["providerEvidence"]["tools"]["nativeDisabled"] = False
        self.denied(c, reason="PROVIDER_PROFILE_UNVERIFIED")

    def test_b24_shared_gateway_claim_refused(self):
        c = make_case()
        c["providerEvidence"]["ownership"]["sharedGateway"] = True
        self.denied(c, reason="PROVIDER_PROFILE_UNVERIFIED")

    def test_malformed_root_cannot_execute(self):
        self.denied({}, reason="ROOT_SCHEMA", fake="REFUSED")
        self.denied(None, reason="ROOT_SCHEMA", fake="REFUSED")

    def test_secret_input_never_appears_in_diagnostics(self):
        c = make_case()
        secret = "UNTRUSTED_BEARER_SECRET_NEVER_ECHO"
        c["extra"] = {"apiToken": secret}
        c["recovery"]["scope"]["room"] = secret
        result = self.denied(c, reason="ROOT_SCHEMA")
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn("apiToken", json.dumps(result))

    def test_very_large_input_does_not_expand_output(self):
        c = make_case()
        c["extra"] = "x" * 300000
        result = self.denied(c, reason="ROOT_SCHEMA")
        self.assertLess(len(json.dumps(result)), 1800)

    def test_cyclic_untrusted_extension_not_propagated(self):
        c = make_case()
        c["extra"] = c
        result = self.denied(c, reason="ROOT_SCHEMA")
        self.assertLess(len(json.dumps(result)), 1800)

    def test_hostile_untrusted_field_not_copied_or_formatted(self):
        class Hostile:
            def __deepcopy__(self, memo):
                raise AssertionError("Unexpected deep copy")
            def __repr__(self):
                raise AssertionError("Unexpected representation")
        c = make_case()
        c["extra"] = Hostile()
        self.denied(c, reason="ROOT_SCHEMA")

    def test_zero_subprocess_file_socket_and_input_immutability(self):
        c = make_case()
        saved = copy.deepcopy(c)
        with patch("subprocess.Popen", side_effect=AssertionError("Popen")), \
             patch("subprocess.run", side_effect=AssertionError("run")), \
             patch("builtins.open", side_effect=AssertionError("open")), \
             patch("socket.socket", side_effect=AssertionError("socket")):
            self.denied(c)
        self.assertEqual(c, saved)

    def test_real_execution_api_always_raises(self):
        with self.assertRaisesRegex(RuntimeError, "REAL_PROVIDER_PRODUCTION_HOLD"):
            h4.require_real_hermes_execution(make_case(), scope(), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
