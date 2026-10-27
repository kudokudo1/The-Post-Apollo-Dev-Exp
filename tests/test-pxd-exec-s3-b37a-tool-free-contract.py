#!/usr/bin/env python3
"""B37-A offline contract regressions: no real provider, auth or network."""
import copy
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b25_responses_fixture import build_fixture_request, FIXTURE_MODEL
from px_s3_b37a_tool_free_contract import (
    MAX_WIRE_BYTES, REQUIRED_KEYS, build_request, inspect_request,
    require_launch_authority, validate_request, validate_wire_payload,
)


class B37AToolFreeTests(unittest.TestCase):
    def setUp(self):
        self.request = build_request("hello fixture")

    def assert_denied(self, changed):
        verdict = inspect_request(changed)
        self.assertEqual(verdict["decision"], "DENY", verdict)
        self.assertFalse(verdict["requestShapeValid"])
        self.assertFalse(verdict["launchAuthorized"])
        self.assertFalse(verdict["productionReady"])
        self.assertFalse(verdict["modelOnlyCertified"])
        self.assertFalse(verdict["retryAuthorized"])
        self.assertEqual(verdict["modelCalls"], 0)
        self.assertEqual(verdict["toolCalls"], 0)
        self.assertEqual(verdict["hospitalWrites"], 0)

    def test_constructor_reuses_b25_fixture_only(self):
        baseline = build_fixture_request("hello fixture")
        self.assertEqual(self.request, dict(baseline, background=False))
        self.assertEqual(set(self.request), REQUIRED_KEYS)
        self.assertEqual(self.request["model"], FIXTURE_MODEL)
        self.assertEqual(self.request["tools"], [])
        self.assertEqual(self.request["tool_choice"], "none")
        self.assertIs(self.request["parallel_tool_calls"], False)
        self.assertIs(self.request["store"], False)
        self.assertIs(self.request["background"], False)
        self.assertIs(self.request["stream"], True)

    def test_positive_shape_still_never_authorizes_launch(self):
        verdict = inspect_request(self.request)
        self.assertEqual(verdict["decision"], "OFFLINE_SHAPE_ONLY")
        self.assertTrue(verdict["requestShapeValid"])
        for key in ("modelOnlyCertified", "launchAuthorized", "productionReady",
                    "providerStarted", "stopVerified", "retryAuthorized"):
            self.assertFalse(verdict[key])
        for key in ("modelCalls", "toolCalls", "hospitalWrites"):
            self.assertEqual(verdict[key], 0)
        self.assertNotIn("input", verdict)
        with self.assertRaisesRegex(RuntimeError, "NO_TRANSPORT_OR_AUTHORITY"):
            require_launch_authority(self.request)

    def test_serialized_and_bytes_round_trip(self):
        wire = json.dumps(self.request)
        self.assertEqual(validate_wire_payload(wire), self.request)
        self.assertEqual(validate_wire_payload(wire.encode("utf-8")), self.request)
        self.assertEqual(inspect_request(wire)["decision"], "OFFLINE_SHAPE_ONLY")

    def test_reject_any_extra_transport_or_authority_fields(self):
        for key, value in (
            ("previous_response_id", "resp_old"),
            ("api_key", "fake-secret"),
            ("Authorization", "Bearer fake-secret"),
            ("base_url", "https://example.invalid"),
            ("endpoint", "/v1/responses"),
            ("metadata", {"room": "foreign"}),
            ("mcp_servers", [{"name": "personal"}]),
            ("include", ["file_search_call.results"]),
            ("instructions", "run shell"),
            ("response_format", {"type": "text"}),
            ("prompt_cache_key", "foreign"),
            ("service_tier", "priority"),
        ):
            with self.subTest(field=key):
                modified = copy.deepcopy(self.request)
                modified[key] = value
                self.assert_denied(modified)

    def test_reject_missing_required_keys(self):
        for key in REQUIRED_KEYS:
            with self.subTest(field=key):
                modified = copy.deepcopy(self.request)
                del modified[key]
                self.assert_denied(modified)

    def test_reject_tool_inventory_and_choice(self):
        for key, value in (
            ("tools", [{"type": "function", "name": "exec"}]),
            ("tools", [{"type": "mcp", "server_url": "https://example.invalid"}]),
            ("tools", "[]"),
            ("tool_choice", "auto"),
            ("tool_choice", {"type": "function", "name": "exec"}),
            ("parallel_tool_calls", True),
        ):
            with self.subTest(field=key, value=str(value)):
                modified = copy.deepcopy(self.request)
                modified[key] = value
                self.assert_denied(modified)

    def test_b25_function_mode_must_not_enter_b37(self):
        modified = build_fixture_request("read data", propose_function=True)
        modified["background"] = False
        self.assert_denied(modified)

    def test_reject_altered_model_even_valid_looking(self):
        for model in ("gpt-6", "codex", "px-other", "", None, 3):
            modified = copy.deepcopy(self.request)
            modified["model"] = model
            self.assert_denied(modified)

    def test_reject_nonimmutable_transport_settings(self):
        for key, value in (
            ("store", True), ("stream", False), ("background", True),
            ("truncation", "auto"), ("max_output_tokens", 513),
            ("max_output_tokens", 512.0), ("max_output_tokens", True),
        ):
            with self.subTest(field=key):
                modified = copy.deepcopy(self.request)
                modified[key] = value
                self.assert_denied(modified)

    def test_reject_input_extra_roles_and_turn_history(self):
        for items in (
            [],
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "old"}],
            [{"role": "system", "content": "fake"}],
            [{"role": "developer", "content": "fake"}],
            [{"role": "tool", "content": "fake"}],
            [{"role": "user", "content": "hi", "name": "foo"}],
            [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
            [{"role": "user"}],
            [{"role": "user", "content": "hi", "tool_call_id": "old"}],
            "prompt",
        ):
            with self.subTest(items=str(items)[:60]):
                modified = copy.deepcopy(self.request)
                modified["input"] = items
                self.assert_denied(modified)

    def test_reject_prompt_invalid_or_excessive(self):
        for prompt in ("", " \n ", "x" * 2049, None, 12, "\ud800"):
            with self.subTest(prompt=repr(prompt)[:24]):
                with self.assertRaises(ValueError):
                    build_request(prompt)
                modified = copy.deepcopy(self.request)
                modified["input"][0]["content"] = prompt
                self.assert_denied(modified)

    def test_prompt_exact_boundary(self):
        self.assertEqual(len(build_request("x" * 2048)["input"][0]["content"]), 2048)

    def test_wire_duplicate_root_and_nested_keys(self):
        raw = json.dumps(self.request)
        self.assert_denied(raw.replace('"model":', '"model": "codex", "model":', 1))
        self.assert_denied(raw.replace('"role":', '"role": "assistant", "role":', 1))

    def test_wire_nonfinite_and_non_json(self):
        wire = json.dumps(self.request)
        for changed in (
            wire.replace("512", "NaN", 1),
            wire.replace("512", "Infinity", 1),
            wire + "garbage",
            "[1, 2, 3]",
            "null",
            "[]",
            "{broken",
        ):
            with self.subTest(raw=changed[:40]):
                self.assert_denied(changed)

    def test_wire_encoding_and_size(self):
        for payload in (b"\xff", "\ud800", b"x" * (MAX_WIRE_BYTES + 1),
                        "x" * (MAX_WIRE_BYTES + 1), 123, None):
            with self.subTest(payload=repr(payload)[:30]):
                self.assert_denied(payload)

    def test_wire_rejects_nested_tool_mutation(self):
        changed = copy.deepcopy(self.request)
        changed["tools"] = [{"type": "shell"}]
        self.assert_denied(json.dumps(changed))

    def test_no_prompt_or_credential_echo_on_denial(self):
        changed = copy.deepcopy(self.request)
        changed["Authorization"] = "Bearer SECRET-CANARY"
        diagnostics = json.dumps(inspect_request(changed))
        self.assertNotIn("SECRET-CANARY", diagnostics)
        self.assertNotIn("hello fixture", diagnostics)

    def test_no_external_calls_during_constructor_and_validation(self):
        with mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
             mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            request = build_request("network is not used")
            validate_request(request)
            validate_wire_payload(json.dumps(request))
            self.assertEqual(inspect_request(request)["modelCalls"], 0)

    def test_no_responses_sdk_or_live_provider_import(self):
        request = build_request("offline")
        self.assertEqual(request["model"], FIXTURE_MODEL)
        self.assertNotIn("openai", sys.modules)

    def test_no_authority_token_returned(self):
        verdict = inspect_request(self.request)
        for forbidden in ("token", "dispatchId", "brokerSocket", "providerSessionId",
                          "launchToken", "apiKey", "requestBody"):
            self.assertNotIn(forbidden, verdict)


if __name__ == "__main__":
    unittest.main()
