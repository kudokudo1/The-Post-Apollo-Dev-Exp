#!/usr/bin/env python3
"""B38-C offline process/credential/transport contract regression tests."""
from dataclasses import FrozenInstanceError, replace
import ast
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import seal_fixture
from px_s3_b38c_transport_policy_fixture import (
    OfflinePlan, Refused, default_fake_manifest,
    prepare_fake_plan, recheck_fake_plan, require_real_transport,
)

BINDING = {
    "room": "fake-room", "patient": "fake-patient",
    "assignment": "fake-assignment", "bed": "fake-bed",
    "turnId": "fake-turn", "generation": 5,
}


class B38CTransportPolicyTests(unittest.TestCase):
    def setUp(self):
        self.binding = dict(BINDING)
        self.request = build_request("PRIVATE_FAKE_INPUT")
        self.sealed = seal_fixture(self.request, binding=self.binding,
                                  attempt_id="fake-attempt")
        self.manifest = default_fake_manifest()

    def prepare(self, manifest=None, sealed=None, binding=None):
        return prepare_fake_plan(
            self.manifest if manifest is None else manifest,
            sealed=self.sealed if sealed is None else sealed,
            current_binding=self.binding if binding is None else binding,
        )

    def check(self, plan, manifest=None, sealed=None, binding=None):
        return recheck_fake_plan(
            plan, self.manifest if manifest is None else manifest,
            sealed=self.sealed if sealed is None else sealed,
            current_binding=self.binding if binding is None else binding,
        )

    def denied(self, code, fn):
        with self.assertRaises(Refused) as cm:
            fn()
        self.assertEqual(str(cm.exception), "B38C_REFUSED_" + code)
        self.assertNotIn("PRIVATE_FAKE_INPUT", str(cm.exception))

    def with_field(self, group, key, value):
        manifest = copy.deepcopy(self.manifest)
        manifest[group][key] = value
        return manifest

    def test_positive_offline_shape_is_never_certification(self):
        plan = self.prepare()
        proof = self.check(plan)
        self.assertIs(type(plan), OfflinePlan)
        self.assertEqual(proof["decision"], "OFFLINE_SHAPE_ONLY")
        self.assertTrue(proof["requestShapeValid"])
        for name in ("credentialBoundaryCertified", "networkPolicyEnforced",
                     "osIsolationVerified", "hospitalAuthorityVerified",
                     "transportReady", "launchAuthorized", "productionReady"):
            self.assertIs(proof[name], False)
        for name in ("modelCalls", "networkCalls", "toolCalls", "hospitalWrites"):
            self.assertEqual(proof[name], 0)
        self.assertNotIn("PRIVATE_FAKE_INPUT", repr(proof))
        self.assertNotIn("PRIVATE_FAKE_INPUT", repr(plan))

    def test_permanent_real_transport_denial(self):
        self.denied("NO_REAL_TRANSPORT_OR_CREDENTIAL_AUTHORITY",
                    lambda: require_real_transport(api_key="private_fake_secret"))

    def test_mutable_caller_manifest_does_not_change_plan(self):
        old = self.prepare()
        original = old.manifest_bytes
        self.manifest["environment"]["names"].append("LC_ALL")
        self.assertEqual(old.manifest_bytes, original)
        self.denied("MANIFEST_CHANGED", lambda: self.check(old))
        self.assertEqual(self.check(old, json.loads(original))["decision"],
                         "OFFLINE_SHAPE_ONLY")

    def test_plan_is_immutable(self):
        plan = self.prepare()
        with self.assertRaises(FrozenInstanceError):
            plan.request_id = "different"

    def test_plan_is_not_an_authorization_token(self):
        plan = self.prepare()
        self.assertFalse(self.check(replace(plan))["launchAuthorized"])
        self.assertEqual(self.check(plan)["networkCalls"], 0)

    def test_extra_root_field_refused(self):
        altered = copy.deepcopy(self.manifest)
        altered["apiKey"] = "private_fake_secret"
        self.denied("POLICY_SCHEMA", lambda: self.prepare(altered))

    def test_missing_root_field_refused(self):
        altered = copy.deepcopy(self.manifest)
        del altered["credentials"]
        self.denied("POLICY_SCHEMA", lambda: self.prepare(altered))

    def test_extra_nested_security_field_refused(self):
        altered = copy.deepcopy(self.manifest)
        altered["credentials"]["token"] = "PRIVATE_FAKE_INPUT"
        self.denied("POLICY_SCHEMA", lambda: self.prepare(altered))

    def test_missing_nested_security_field_refused(self):
        altered = copy.deepcopy(self.manifest)
        del altered["ipc"]["brokerAddressVisible"]
        self.denied("POLICY_SCHEMA", lambda: self.prepare(altered))

    def test_non_dict_and_subclass_manifest_refused(self):
        class Payload(dict):
            pass
        for value in ([], {}, None, Payload(self.manifest)):
            with self.subTest(type=type(value).__name__):
                self.denied("POLICY_SCHEMA", lambda: self.prepare(value))

    def test_secret_and_inherited_host_environment_refused(self):
        for key in ("hostEnvInherited", "argvSecret", "stdinSecret",
                    "toolSecret", "fdsInherited", "socketsInherited",
                    "hostHomeMounted"):
            with self.subTest(key=key):
                self.denied("POLICY_VALUE",
                            lambda: self.prepare(self.with_field("credentials", key, True)))

    def test_any_real_credential_source_refused(self):
        for source in ("API_KEY", "env", "file", "oauth", "/home/operator/.env", None):
            with self.subTest(source=source):
                self.denied("POLICY_VALUE",
                            lambda: self.prepare(self.with_field("credentials", "source", source)))

    def test_any_executable_or_hermes_runtime_refused(self):
        for exe in ("python", "hermes chat", "/usr/bin/python", "codex", "NONE "):
            with self.subTest(exe=exe):
                self.denied("POLICY_VALUE",
                            lambda: self.prepare(self.with_field("process", "executable", exe)))

    def test_native_tool_and_plugin_paths_refused(self):
        for key in ("nativeTools", "plugins", "mcp", "delegation",
                    "shell", "browser", "nativeResume"):
            with self.subTest(key=key):
                self.denied("POLICY_VALUE",
                            lambda: self.prepare(self.with_field("process", key, True)))

    def test_network_endpoints_and_mode_are_fixed_offline(self):
        for group, key, value in (
            ("network", "mode", "HTTPS"),
            ("network", "destination", "api.example.com"),
            ("network", "destination", "http://mock-model.invalid"),
            ("network", "destination", "127.0.0.1"),
            ("network", "tcpEnabled", True),
            ("network", "redirects", True),
            ("network", "proxy", True),
            ("network", "ambientDNS", True),
            ("network", "toolEgress", True),
        ):
            with self.subTest(field=key, value=str(value)):
                self.denied("POLICY_VALUE",
                            lambda: self.prepare(self.with_field(group, key, value)))

    def test_broker_address_and_ipc_access_refused(self):
        for key, value in (("kind", "unix-socket"),
                           ("brokerAddressVisible", True),
                           ("modelCanMintGrant", True),
                           ("toolCanSendRequest", True)):
            self.denied("POLICY_VALUE",
                        lambda: self.prepare(self.with_field("ipc", key, value)))

    def test_wrong_budget_values_refused(self):
        for key, value in (("requestBytes", 8193), ("requestBytes", True),
                           ("frameBytes", 2049), ("frames", 33),
                           ("frames", 32.0)):
            with self.subTest(key=key, value=value):
                self.denied("POLICY_VALUE",
                            lambda: self.prepare(self.with_field("limits", key, value)))

    def test_environment_allowlist_by_names_only(self):
        self.manifest["environment"]["names"] = ["LANG", "LC_ALL", "TZ"]
        self.assertEqual(self.check(self.prepare())["decision"], "OFFLINE_SHAPE_ONLY")
        self.manifest["environment"]["names"] = []
        self.assertEqual(self.check(self.prepare())["decision"], "OFFLINE_SHAPE_ONLY")

    def test_environment_secrets_and_unknown_names_refused(self):
        for names in (["API_KEY"], ["OPENAI_API_KEY"], ["HOME"],
                      ["LD_PRELOAD"], ["PYTHONPATH"], ["LANG", "TZ", "API_KEY"],
                      ["LANG=secret"], [None], [{"secret": "value"}], [1]):
            with self.subTest(names=repr(names)):
                self.denied("ENV_NAMES",
                            lambda: self.prepare(self.with_field("environment", "names", names)))

    def test_duplicate_and_unsorted_env_names_refused(self):
        for names, code in ((["LANG", "LANG"], "ENV_NAMES"),
                            (["TZ", "LANG"], "ENV_ORDER")):
            self.denied(code,
                        lambda: self.prepare(self.with_field("environment", "names", names)))

    def test_environment_values_refused(self):
        self.denied("POLICY_VALUE",
                    lambda: self.prepare(self.with_field("environment", "valuesIncluded", True)))

    def test_env_names_must_be_exact_builtin_list(self):
        self.denied("ENV_NAMES",
                    lambda: self.prepare(self.with_field("environment", "names", ("LANG", "TZ"))))

    def test_tampered_manifest_at_recheck_refused(self):
        plan = self.prepare()
        self.manifest["process"]["nativeTools"] = True
        self.denied("POLICY_VALUE", lambda: self.check(plan))

    def test_tampered_manifest_digest_refused(self):
        plan = self.prepare()
        altered = replace(plan, manifest_sha256="0" * 64)
        self.denied("MANIFEST_HASH_CHANGED", lambda: self.check(altered))

    def test_tampered_manifest_bytes_refused(self):
        plan = self.prepare()
        altered = replace(plan, manifest_bytes=b"forged")
        self.denied("MANIFEST_CHANGED", lambda: self.check(altered))

    def test_stale_or_foreign_binding_refused(self):
        for binding in (dict(self.binding, generation=6),
                        dict(self.binding, assignment="other-assignment"),
                        dict(self.binding, patient="other-patient")):
            self.denied("SEALED_REQUEST_INVALID",
                        lambda: self.check(self.prepare(), binding=binding))

    def test_tampered_sealed_request_refused(self):
        plan = self.prepare()
        altered = replace(self.sealed, client_request_id="fake-forged")
        self.denied("SEALED_REQUEST_INVALID",
                    lambda: self.check(plan, sealed=altered))

    def test_new_sealed_request_invalidates_old_plan(self):
        plan = self.prepare()
        other = seal_fixture(build_request("another private prompt"), binding=self.binding,
                             attempt_id="another-attempt")
        self.denied("SEALED_IDENTITY_CHANGED",
                    lambda: self.check(plan, sealed=other))

    def test_invalid_seal_type_refused(self):
        self.denied("SEAL_TYPE", lambda: self.prepare(sealed={}))

    def test_no_real_process_network_or_secret_reader_imports(self):
        text = (ROOT / "bin" / "px_s3_b38c_transport_policy_fixture.py").read_text()
        tree = ast.parse(text)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(n.name.split(".")[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & {
            "os", "socket", "subprocess", "requests", "urllib", "http", "httpx",
            "aiohttp", "openai", "hermes_cli", "litellm", "run_agent", "model_tools",
            "tools", "ctypes", "pathlib", "ssl", "importlib",
        })
        for token in ("Popen(", "os.environ", "os.system(", "open(", "eval(",
                      "exec(", "create_connection(", "urlopen("):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
