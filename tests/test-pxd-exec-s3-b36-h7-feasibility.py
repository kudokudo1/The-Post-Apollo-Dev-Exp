#!/usr/bin/env python3
"""H7 sanitized H6-only feasibility review; fake tests, no host probing."""
import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import px_s3_b36_h6_readonly_host_inventory as h6
import px_s3_b36_h7_feasibility_from_h6 as h7


def h6_report():
    return h6.assess({
        "sources": {
            "mountinfo": "34 25 0:32 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n",
            "selfCgroup": "0::/fixture/path\n",
            "controllers": "cpu memory pids",
            "status": "NoNewPrivs:\t1\nSeccomp:\t2\n",
            "unprivilegedUserns": "1\n",
            "maxUserns": "100\n",
            "osRelease": "ID=fedora\nVARIANT_ID=silverblue\n",
            "selinuxEnforce": "1\n",
        },
        "namespaces": {n: True for n in h6.NAMESPACE_KINDS},
        "tools": {n: True for n in h6.TOOLS},
        "userBusSocket": True,
    })


class H7FeasibilityTests(unittest.TestCase):
    def denied(self, data=None, reason=None):
        out = h7.assess(h6_report() if data is None else data)
        self.assertEqual(out["decision"], "DENY")
        for key in ("realHermesSupported", "realGatewayLaunched", "hostAttested",
                    "cgroupDelegationVerified", "namespaceIsolationVerified",
                    "nativeToolDenialVerified", "modelOnlyTransportVerified",
                    "authenticatedStopVerified", "descendantTeardownVerified",
                    "networkIsolationVerified", "credentialIsolationVerified",
                    "launchAuthorized", "productionReady"):
            self.assertFalse(out[key])
        for key in ("modelCalls", "gatewayCalls", "toolCalls", "hospitalWrites"):
            self.assertEqual(out[key], 0)
        self.assertIn("REAL_PROVIDER_PRODUCTION_HOLD", out["reasons"])
        self.assertIn("HERMES_TURN_STOP_UNPROVEN", out["reasons"])
        self.assertIn("HERMES_NATIVE_TOOL_DENIAL_UNPROVEN", out["reasons"])
        if reason:
            self.assertIn(reason, out["reasons"])
        self.assertNotIn("observations", out)
        return out

    def test_positive_fake_h6_only_suggests_non_hermes_experiment(self):
        out = self.denied()
        self.assertEqual(out["options"]["systemdUserScope"], "POTENTIAL_FAKE_EXPERIMENT_ONLY")
        self.assertEqual(out["options"]["bubblewrapNamespaces"], "POTENTIAL_FAKE_EXPERIMENT_ONLY")
        self.assertEqual(out["nextReview"], "REVIEW_NON_HERMES_SYSTEMD_SCOPE_PROBE")

    def test_bwrap_is_fallback_when_bus_absent(self):
        fake = h6_report()
        fake["observations"]["userBusSocketPresent"] = False
        out = self.denied(fake)
        self.assertEqual(out["options"]["systemdUserScope"], "PREREQUISITE_NOT_OBSERVED")
        self.assertEqual(out["nextReview"], "REVIEW_NON_HERMES_NAMESPACE_PROBE")

    def test_unknown_bus_never_becomes_positive(self):
        fake = h6_report()
        fake["observations"]["userBusSocketPresent"] = None
        out = self.denied(fake)
        self.assertEqual(out["options"]["systemdUserScope"], "INCOMPLETE_OBSERVATION")

    def test_missing_cgroup_v2_is_not_dedicated_group(self):
        fake = h6_report()
        fake["observations"]["cgroupV2MountedAtStandardPath"] = False
        out = self.denied(fake)
        self.assertEqual(out["options"]["systemdUserScope"], "PREREQUISITE_NOT_OBSERVED")

    def test_missing_pids_controller_blocks_systemd_indication(self):
        fake = h6_report()
        fake["observations"]["visibleCgroupControllers"] = ["cpu", "memory"]
        self.assertEqual(self.denied(fake)["options"]["systemdUserScope"],
                         "PREREQUISITE_NOT_OBSERVED")

    def test_missing_systemd_run_not_assumed_operational(self):
        fake = h6_report()
        fake["observations"]["toolExecutablesPresent"]["systemdRun"] = False
        self.assertEqual(self.denied(fake)["options"]["systemdUserScope"],
                         "PREREQUISITE_NOT_OBSERVED")

    def test_unknown_systemd_tool_metadata_not_positive(self):
        fake = h6_report()
        fake["observations"]["toolExecutablesPresent"]["systemdRun"] = None
        self.assertEqual(self.denied(fake)["options"]["systemdUserScope"],
                         "INCOMPLETE_OBSERVATION")

    def test_unknown_namespace_capability_not_positive(self):
        fake = h6_report()
        fake["observations"]["namespaceLinksPresent"]["mnt"] = None
        self.assertEqual(self.denied(fake)["options"]["bubblewrapNamespaces"],
                         "INCOMPLETE_OBSERVATION")

    def test_missing_bwrap_not_assumed_operational(self):
        fake = h6_report()
        fake["observations"]["toolExecutablesPresent"]["bwrap"] = False
        self.assertEqual(self.denied(fake)["options"]["bubblewrapNamespaces"],
                         "PREREQUISITE_NOT_OBSERVED")

    def test_userns_disabled_blocks_namespace_indication(self):
        fake = h6_report()
        fake["observations"]["unprivilegedUsernsSysctlAllows"] = False
        self.assertEqual(self.denied(fake)["options"]["bubblewrapNamespaces"],
                         "PREREQUISITE_NOT_OBSERVED")

    def test_missing_userns_setting_is_unknown(self):
        fake = h6_report()
        fake["observations"]["unprivilegedUsernsSysctlAllows"] = None
        self.assertEqual(self.denied(fake)["options"]["bubblewrapNamespaces"],
                         "INCOMPLETE_OBSERVATION")

    def test_all_strategies_unavailable_do_not_suggest_launch(self):
        fake = h6_report()
        fake["observations"]["cgroupV2MountedAtStandardPath"] = False
        fake["observations"]["toolExecutablesPresent"]["bwrap"] = False
        out = self.denied(fake)
        self.assertEqual(out["nextReview"], "RESOLVE_HOST_PREREQUISITES_READ_ONLY")

    def test_selinux_enforcing_is_not_gateway_confinement(self):
        self.assertFalse(self.denied()["networkIsolationVerified"])

    def test_no_new_privs_is_process_local_not_proof(self):
        self.assertFalse(self.denied()["credentialIsolationVerified"])

    def test_h6_report_claiming_approval_is_rejected(self):
        fake = h6_report()
        fake["launchAuthorized"] = True
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_h6_report_claiming_kernel_attestation_is_rejected(self):
        fake = h6_report()
        fake["kernelAttested"] = True
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_h6_report_claiming_native_tools_disabled_is_rejected(self):
        fake = h6_report()
        fake["nativeToolsDisabled"] = True
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_h6_nonzero_model_count_is_rejected(self):
        fake = h6_report()
        fake["modelCalls"] = 1
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_int_bool_confusion_denied(self):
        fake = h6_report()
        fake["modelCalls"] = False
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")
        fake = h6_report()
        fake["observations"]["currentProcessSeccompMode"] = True
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_bad_schema_denied(self):
        fake = h6_report()
        fake["schema"] = "H6_FUTURE_WRONG"
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_invalid_h6_snapshot_not_interpreted(self):
        fake = h6.assess(None)
        out = self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")
        self.assertEqual(out["options"]["systemdUserScope"], "UNTRUSTED_REPORT")

    def test_missing_root_field_denied(self):
        fake = h6_report()
        del fake["observations"]
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_extra_root_with_secret_denied_without_echo(self):
        fake = h6_report()
        fake["secret"] = "NO_ECHO_TOKEN_Y48"
        out = self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")
        self.assertNotIn("NO_ECHO_TOKEN_Y48", json.dumps(out))

    def test_unknown_controller_rejected(self):
        fake = h6_report()
        fake["observations"]["visibleCgroupControllers"] = ["cpu", "untrusted"]
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_unsorted_duplicate_controllers_rejected(self):
        fake = h6_report()
        fake["observations"]["visibleCgroupControllers"] = ["pids", "cpu", "pids"]
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_bad_nested_namespace_map_rejected(self):
        fake = h6_report()
        fake["observations"]["namespaceLinksPresent"]["ssh-agent"] = True
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_cyclic_oversized_data_never_copied(self):
        fake = h6_report()
        fake["extra"] = fake
        self.assertLess(len(json.dumps(self.denied(fake))), 2200)

    def test_noncopyable_secret_object_never_touched(self):
        class Hostile:
            def __deepcopy__(self, memo):
                raise AssertionError("deep copy of untrusted input")
            def __repr__(self):
                raise AssertionError("repr of untrusted input")
        fake = h6_report()
        fake["secret"] = Hostile()
        self.denied(fake, "MALFORMED_OR_UNTRUSTED_H6_REPORT")

    def test_report_immutable_and_process_free(self):
        fake = h6_report()
        original = copy.deepcopy(fake)
        with patch("subprocess.Popen", side_effect=AssertionError("process")), \
             patch("subprocess.run", side_effect=AssertionError("process")), \
             patch("socket.socket", side_effect=AssertionError("network")), \
             patch("builtins.open", side_effect=AssertionError("filesystem")):
            self.denied(fake)
        self.assertEqual(fake, original)

    def test_default_cli_does_not_read_stdin(self):
        class ForbiddenInput:
            def read(self, count):
                raise AssertionError("unrequested input read")
        output = io.StringIO()
        with redirect_stdout(output):
            code = h7.main([], ForbiddenInput())
        self.assertEqual(code, 2)
        self.assertIn("EXPLICIT_SANITIZED_H6_STDIN_REQUIRED", output.getvalue())

    def test_opted_in_cli_reads_sanitized_h6_and_never_launches(self):
        stream = io.BytesIO(json.dumps(h6_report()).encode())
        output = io.StringIO()
        with redirect_stdout(output):
            code = h7.main(["--stdin"], stream)
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["decision"], "DENY")
        self.assertFalse(result["launchAuthorized"])
        self.assertNotIn("/fixture/path", output.getvalue())

    def test_duplicate_json_keys_are_rejected(self):
        raw = b'{"schema":"first","schema":"second"}'
        self.assertIsNone(h7._parse_bounded(raw))

    def test_invalid_json_and_invalid_unicode_are_rejected(self):
        for raw in (b'{bad}', b'\xff', b'{"wrong":'):
            with self.subTest(raw=raw):
                self.assertIsNone(h7._parse_bounded(raw))

    def test_excessively_large_json_rejected_without_reading_remainder(self):
        raw = b'{"secret":"' + b"x" * h7.MAX_INPUT_BYTES + b'"}'
        self.assertIsNone(h7._parse_bounded(raw))
        output = io.StringIO()
        with redirect_stdout(output):
            h7.main(["--stdin"], io.BytesIO(raw))
        self.assertIn("MALFORMED_OR_UNTRUSTED_H6_REPORT", output.getvalue())

    def test_bad_cli_argument_never_reads_stdin(self):
        class ForbiddenInput:
            def read(self, count):
                raise AssertionError("unexpected read")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(h7.main(["--read-hermes-secrets"], ForbiddenInput()), 2)

    def test_bad_stdin_type_does_not_echo_errors(self):
        output = io.StringIO()
        with redirect_stdout(output):
            h7.main(["--stdin"], io.StringIO("SENSITIVE_INVALID_INPUT"))
        self.assertNotIn("SENSITIVE_INVALID_INPUT", output.getvalue())

    def test_only_fixed_known_reason_codes_and_no_raw_input(self):
        fake = h6_report()
        serialized = json.dumps(self.denied(fake))
        self.assertNotIn("mountinfo", serialized)
        self.assertNotIn("sysctl", serialized)
        self.assertLess(len(serialized), 2200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
