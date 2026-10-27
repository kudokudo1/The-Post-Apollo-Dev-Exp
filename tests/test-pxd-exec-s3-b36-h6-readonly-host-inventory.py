#!/usr/bin/env python3
"""B36-H6 offline fake snapshot tests: zero real host reads or provider actions."""
import copy
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import px_s3_b36_h6_readonly_host_inventory as h6


def fixture():
    return {
        "sources": {
            "mountinfo": "34 25 0:32 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n",
            "selfCgroup": "0::/safe/fake/path\n",
            "controllers": "cpu memory pids io unsupported-controller",
            "status": "Name:\tsandbox\nNoNewPrivs:\t1\nSeccomp:\t2\n",
            "unprivilegedUserns": "1\n",
            "maxUserns": "123\n",
            "osRelease": 'NAME="Fedora Linux"\nID=fedora\nVARIANT_ID=silverblue\n',
        },
        "namespaces": {name: True for name in h6.NAMESPACE_KINDS},
        "tools": {name: True for name in h6.TOOLS},
        "userBusSocket": True,
    }


class H6OfflineInventoryTests(unittest.TestCase):
    def checked(self, snapshot=None, bad=False):
        report = h6.assess(fixture() if snapshot is None else snapshot)
        self.assertEqual(report["decision"], "DENY")
        self.assertTrue(report["inventoryOnly"])
        self.assertFalse(report["kernelAttested"])
        for key in ("credentialBoundaryCertified", "nativeToolsDisabled",
                    "networkEgressDenied", "cgroupDelegationCertified",
                    "gatewayStopAuthenticated", "descendantTeardownCertified",
                    "launchAuthorized", "productionReady"):
            self.assertFalse(report[key])
        for key in ("modelCalls", "gatewayCalls", "toolCalls", "hospitalWrites"):
            self.assertEqual(report[key], 0)
        self.assertIn("REAL_PROVIDER_PRODUCTION_HOLD", report["reasons"])
        self.assertNotIn("raw", report)
        if bad:
            self.assertIn("INVALID_INVENTORY_SNAPSHOT", report["reasons"])
        return report

    def test_synthetic_positive_capabilities_still_deny(self):
        report = self.checked()
        obs = report["observations"]
        self.assertTrue(obs["cgroupV2MountedAtStandardPath"])
        self.assertTrue(obs["selfCgroupV2Member"])
        self.assertTrue(obs["fedoraSilverblueReported"])
        self.assertTrue(obs["unprivilegedUsernsSysctlAllows"])
        self.assertTrue(obs["maxUserNamespacesPositive"])
        self.assertTrue(obs["currentProcessNoNewPrivs"])
        self.assertEqual(obs["currentProcessSeccompMode"], 2)
        self.assertEqual(obs["visibleCgroupControllers"], ["cpu", "io", "memory", "pids"])

    def test_missing_cgroup_v2_mount_is_not_safety_grant(self):
        sample = fixture()
        sample["sources"]["mountinfo"] = "34 25 0:32 / /foo rw - ext4 /dev/loop rw"
        self.assertFalse(self.checked(sample)["observations"]["cgroupV2MountedAtStandardPath"])

    def test_missing_proc_cgroup_entry(self):
        sample = fixture()
        sample["sources"]["selfCgroup"] = "1:cpu:/fake\n"
        self.assertFalse(self.checked(sample)["observations"]["selfCgroupV2Member"])

    def test_missing_cgroup_file_unknown(self):
        sample = fixture()
        sample["sources"]["mountinfo"] = None
        self.assertIsNone(self.checked(sample)["observations"]["cgroupV2MountedAtStandardPath"])

    def test_controllers_allowlist_unknown_ignored(self):
        sample = fixture()
        sample["sources"]["controllers"] = "new_future_controller misc hugeTLB cpu cpu"
        self.assertEqual(self.checked(sample)["observations"]["visibleCgroupControllers"],
                         ["cpu", "misc"])

    def test_seccomp_and_nonewprivs_absent_unknown(self):
        sample = fixture()
        sample["sources"]["status"] = "Name:\tfake\n"
        obs = self.checked(sample)["observations"]
        self.assertIsNone(obs["currentProcessNoNewPrivs"])
        self.assertIsNone(obs["currentProcessSeccompMode"])

    def test_seccomp_zero_is_observation_not_confinement(self):
        sample = fixture()
        sample["sources"]["status"] = "NoNewPrivs: 0\nSeccomp: 0\n"
        obs = self.checked(sample)["observations"]
        self.assertFalse(obs["currentProcessNoNewPrivs"])
        self.assertEqual(obs["currentProcessSeccompMode"], 0)
        self.assertFalse(self.checked(sample)["networkEgressDenied"])

    def test_userns_disabled_by_sysctl(self):
        sample = fixture()
        sample["sources"]["unprivilegedUserns"] = "0"
        self.assertFalse(self.checked(sample)["observations"]["unprivilegedUsernsSysctlAllows"])

    def test_userns_max_count_zero(self):
        sample = fixture()
        sample["sources"]["maxUserns"] = "0"
        self.assertFalse(self.checked(sample)["observations"]["maxUserNamespacesPositive"])

    def test_unknown_sysctl_contents_are_not_guesswork(self):
        sample = fixture()
        sample["sources"]["maxUserns"] = "five"
        sample["sources"]["unprivilegedUserns"] = None
        obs = self.checked(sample)["observations"]
        self.assertIsNone(obs["maxUserNamespacesPositive"])
        self.assertIsNone(obs["unprivilegedUsernsSysctlAllows"])

    def test_non_silverblue_os_release(self):
        sample = fixture()
        sample["sources"]["osRelease"] = "ID=ubuntu\n"
        self.assertFalse(self.checked(sample)["observations"]["fedoraSilverblueReported"])

    def test_missing_os_release_is_unknown(self):
        sample = fixture()
        sample["sources"]["osRelease"] = None
        self.assertIsNone(self.checked(sample)["observations"]["fedoraSilverblueReported"])

    def test_absent_tools_and_namespace_links_are_not_certs(self):
        sample = fixture()
        sample["namespaces"]["net"] = False
        sample["tools"]["bwrap"] = False
        obs = self.checked(sample)["observations"]
        self.assertFalse(obs["namespaceLinksPresent"]["net"])
        self.assertFalse(obs["toolExecutablesPresent"]["bwrap"])
        self.assertFalse(self.checked(sample)["descendantTeardownCertified"])

    def test_bad_root_input_denies(self):
        for val in (None, [], {}, {"sources": "oops"}, "secret"):
            with self.subTest(value=type(val).__name__):
                result = self.checked(val if val is not None else {"sources": []}, bad=True)
                self.assertIsNone(result["observations"]["cgroupV2MountedAtStandardPath"])

    def test_extra_secret_fields_never_echoed(self):
        sample = fixture()
        sample["personal_token"] = "SECRET_UNTRUSTED_TOKEN_DO_NOT_ECHO"
        result = self.checked(sample, bad=True)
        self.assertNotIn("SECRET_UNTRUSTED_TOKEN_DO_NOT_ECHO", json.dumps(result))

    def test_oversized_raw_file_suppressed(self):
        sample = fixture()
        sample["sources"]["mountinfo"] = "SECRET" * 60000
        result = self.checked(sample, bad=True)
        self.assertLess(len(json.dumps(result)), 2100)

    def test_nonstring_source_denied(self):
        sample = fixture()
        sample["sources"]["controllers"] = ["cpu", "memory"]
        self.checked(sample, bad=True)

    def test_hostile_nested_extra_not_copied(self):
        class Hostile:
            def __repr__(self):
                raise AssertionError("secret must not be printed")
            def __deepcopy__(self, memo):
                raise AssertionError("secret must not be copied")
        sample = fixture()
        sample["malicious"] = Hostile()
        self.checked(sample, bad=True)

    def test_recursive_extension_not_serialized(self):
        sample = fixture()
        sample["cyclic"] = sample
        result = self.checked(sample, bad=True)
        self.assertLess(len(json.dumps(result)), 2100)

    def test_fixture_not_modified(self):
        sample = fixture()
        original = copy.deepcopy(sample)
        self.checked(sample)
        self.assertEqual(sample, original)

    def test_default_main_refuses_before_any_host_read(self):
        output = io.StringIO()
        with patch.object(h6, "collect_host_readonly", side_effect=AssertionError("HOST ACCESS")):
            with redirect_stdout(output):
                rc = h6.main([])
        self.assertEqual(rc, 2)
        self.assertIn("EXPLICIT_HOST_READONLY_OPT_IN_REQUIRED", output.getvalue())
        self.assertIn('"hostReads": 0', output.getvalue())

    def test_malformed_cli_option_refuses_before_any_host_read(self):
        with patch.object(h6, "collect_host_readonly", side_effect=AssertionError("HOST ACCESS")):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(h6.main(["--host-readonly", "--dump-secrets"]), 2)

    def test_opted_in_main_only_outputs_bounded_diagnostics(self):
        output = io.StringIO()
        with patch.object(h6, "collect_host_readonly", return_value=fixture()):
            with redirect_stdout(output):
                self.assertEqual(h6.main(["--host-readonly"]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["decision"], "DENY")
        self.assertNotIn("/safe/fake/path", output.getvalue())

    def test_opted_in_read_failure_still_denies_without_error_echo(self):
        output = io.StringIO()
        with patch.object(h6, "collect_host_readonly",
                          side_effect=RuntimeError("SECRET_EXCEPTION_CREDENTIAL_PATH")):
            with redirect_stdout(output):
                self.assertEqual(h6.main(["--host-readonly"]), 0)
        data = json.loads(output.getvalue())
        self.assertIn("INVALID_INVENTORY_SNAPSHOT", data["reasons"])
        self.assertNotIn("SECRET_EXCEPTION", output.getvalue())

    def test_public_fixed_host_source_allowlist(self):
        self.assertEqual(set(h6.HOST_SOURCES), set(fixture()["sources"]))
        for path in h6.HOST_SOURCES.values():
            self.assertTrue(path.startswith(("/proc/", "/sys/", "/etc/")))
            self.assertNotIn("/home/", path)
        self.assertEqual(set(h6.TOOLS), set(fixture()["tools"]))

    def test_collector_uses_exact_allowlisted_paths_and_no_process_launch(self):
        sources = []
        tool_paths = []
        ns_names = []
        with patch.object(h6, "_read_bounded", side_effect=lambda p: sources.append(p) or None), \
             patch.object(h6, "_fixed_tool_executable",
                          side_effect=lambda p: tool_paths.append(p) or False), \
             patch.object(h6, "_fixed_namespace_exists",
                          side_effect=lambda name: ns_names.append(name) or False), \
             patch.object(h6, "_fixed_bus_socket", return_value=False), \
             patch("subprocess.Popen", side_effect=AssertionError("UNEXPECTED SPAWN")), \
             patch("socket.socket", side_effect=AssertionError("NETWORK")):
            sample = h6.collect_host_readonly() if sys.platform == "linux" else None
        if sample is None:
            self.skipTest("Linux only")
        self.assertEqual(sources, list(h6.HOST_SOURCES.values()))
        self.assertEqual(tool_paths, list(h6.TOOLS.values()))
        self.assertEqual(ns_names, list(h6.NAMESPACE_KINDS))
        self.assertFalse(sample["userBusSocket"])

    def test_static_parsers_do_not_start_subprocesses(self):
        with patch("subprocess.Popen", side_effect=AssertionError("Popen")), \
             patch("subprocess.run", side_effect=AssertionError("run")), \
             patch("builtins.open", side_effect=AssertionError("open")), \
             patch("socket.socket", side_effect=AssertionError("socket")):
            self.checked()

    def test_missing_namespace_flag_reports_unknown(self):
        sample = fixture()
        sample["namespaces"]["pid"] = None
        self.assertIsNone(self.checked(sample)["observations"]["namespaceLinksPresent"]["pid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
