#!/usr/bin/env python3
"""B38-E signed fake process protocol tests. NO network, provider or real auth."""
import base64
from dataclasses import FrozenInstanceError, replace
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import seal_fixture
from px_s3_b38e_fake_process_ipc import (
    CHILD_ENV, KEY_LEN, REPLY, REQUEST, VERSION, TEXT, Refused,
    _auth, _json, _parse, _read_key, _sign, build_fake_request,
    build_child_reply, exchange_in_separate_fake_process,
    parse_child_request, require_real_sender, verify_child_reply,
)

BINDING = {
    "room": "ipcRoom", "patient": "ipcPatient", "assignment": "ipcAssignment",
    "bed": "ipcBed", "turnId": "ipcTurn", "generation": 3,
}


class B38EFakeIpcTests(unittest.TestCase):
    def setUp(self):
        self.binding = dict(BINDING)
        self.sealed = seal_fixture(build_request("FAKE_PRIVATE_INPUT"),
                                   binding=self.binding, attempt_id="fakeAttemptIPC")
        self.key = b"K" * KEY_LEN
        self.nonce = "f" * 32
        self.request = build_fake_request(
            self.sealed, current_binding=self.binding,
            nonce=self.nonce, fake_key=self.key,
        )

    def deny(self, code, thunk):
        with self.assertRaises(Refused) as caught:
            thunk()
        self.assertEqual(str(caught.exception), "B38E_REFUSED_" + code)
        self.assertNotIn("FAKE_PRIVATE_INPUT", str(caught.exception))
        self.assertNotIn("K" * KEY_LEN, str(caught.exception))

    def signed(self, **replace_fields):
        doc = json.loads(self.request)
        doc.pop("mac")
        doc.update(replace_fields)
        doc["mac"] = _sign(doc, self.key)
        return _json(doc)

    def test_real_subprocess_returns_fixed_fake_only_receipt(self):
        result = exchange_in_separate_fake_process(
            self.sealed, current_binding=self.binding,
        )
        self.assertEqual(result.text, TEXT)
        self.assertEqual(result.request_id, self.sealed.client_request_id)
        self.assertGreater(result.child_pid, 1)
        self.assertNotEqual(result.child_pid, os.getpid())
        self.assertEqual(result.provenance, "B38E_SEPARATE_PROCESS_SYNTHETIC_ONLY")
        for name in ("credential_isolation_certified", "sender_os_isolated",
                     "launch_authorized", "production_ready"):
            self.assertIs(getattr(result, name), False)
        for name in ("model_calls", "tool_calls", "network_calls"):
            self.assertEqual(getattr(result, name), 0)
        self.assertNotIn("FAKE_PRIVATE_INPUT", repr(result))

    def test_real_subprocess_receipt_immutable(self):
        result = exchange_in_separate_fake_process(
            self.sealed, current_binding=self.binding,
        )
        with self.assertRaises(FrozenInstanceError):
            result.production_ready = True

    def test_real_provider_denied(self):
        self.deny("REAL_MODEL_PROVIDER_FORBIDDEN", lambda: require_real_sender("fake-key"))

    def test_authenticated_request_roundtrip_in_memory(self):
        doc = parse_child_request(self.request, self.key)
        self.assertEqual(doc["request_id"], self.sealed.client_request_id)
        self.assertEqual(doc["nonce"], self.nonce)
        reply = build_child_reply(doc, self.key, 12345)
        self.assertEqual(
            verify_child_reply(reply, fake_key=self.key, nonce=self.nonce,
                               request_id=self.sealed.client_request_id,
                               expected_pid=12345)["text"], TEXT
        )

    def test_wrong_shared_key_rejected(self):
        self.deny("FRAME_AUTH", lambda: parse_child_request(self.request, b"J" * KEY_LEN))

    def test_forged_mac_rejected(self):
        raw = json.loads(self.request)
        raw["mac"] = "0" * 64
        self.deny("FRAME_AUTH", lambda: parse_child_request(_json(raw), self.key))

    def test_tampered_request_body_rejected(self):
        raw = json.loads(self.request)
        raw["nonce"] = "a" * 32
        self.deny("FRAME_AUTH", lambda: parse_child_request(_json(raw), self.key))

    def test_extra_or_missing_fields_rejected(self):
        self.deny("FRAME_SCHEMA",
                  lambda: parse_child_request(self.signed(extra="shell"), self.key))
        doc = json.loads(self.request)
        doc.pop("payload_b64")
        self.deny("FRAME_SCHEMA", lambda: parse_child_request(_json(doc), self.key))

    def test_missing_or_wrong_version_refused(self):
        self.deny("PROTOCOL_VERSION", lambda: parse_child_request(
            self.signed(version=2), self.key))
        self.deny("FRAME_TYPE", lambda: parse_child_request(
            self.signed(version=True), self.key))

    def test_wrong_nonce_and_scope_digest_refused(self):
        self.deny("NONCE_INVALID",
                  lambda: parse_child_request(self.signed(nonce="bad"), self.key))
        self.deny("SCOPE_DIGEST_INVALID",
                  lambda: parse_child_request(self.signed(scope_sha256="bad"), self.key))

    def test_wrong_request_id_refused(self):
        self.deny("REQUEST_ID_INVALID", lambda: parse_child_request(
            self.signed(request_id="foreign"), self.key))

    def test_child_refuses_tool_capable_signed_payload(self):
        forged_request = build_request("fake tool request")
        forged_request["tools"] = [{"type": "function", "name": "shell"}]
        raw = json.dumps(forged_request, separators=(",", ":")).encode("ascii")
        altered = base64.b64encode(raw).decode("ascii")
        self.deny("TOOL_FREE_REQUEST_INVALID",
                  lambda: parse_child_request(
                      self.signed(payload_b64=altered), self.key))

    def test_child_refuses_extra_provider_fields(self):
        forged_request = build_request("fake prompt")
        forged_request["endpoint"] = "https://not-a-provider.invalid"
        raw = json.dumps(forged_request, separators=(",", ":")).encode("ascii")
        self.deny("TOOL_FREE_REQUEST_INVALID", lambda: parse_child_request(
            self.signed(payload_b64=base64.b64encode(raw).decode("ascii")), self.key))

    def test_invalid_base64_refused(self):
        self.deny("TOOL_FREE_REQUEST_INVALID",
                  lambda: parse_child_request(
                      self.signed(payload_b64="%%%"), self.key))

    def test_duplicate_json_keys_refused(self):
        raw = self.request.decode("ascii").replace(
            '"kind":', '"kind":"DUPLICATE", "kind":', 1
        ).encode("ascii")
        self.deny("DUPLICATE_JSON_KEY", lambda: parse_child_request(raw, self.key))

    def test_response_replay_nonce_refused(self):
        doc = parse_child_request(self.request, self.key)
        reply = build_child_reply(doc, self.key, 1133)
        self.deny("REPLY_MISMATCH", lambda: verify_child_reply(
            reply, fake_key=self.key, nonce="a" * 32,
            request_id=self.sealed.client_request_id, expected_pid=1133))

    def test_reply_other_process_pid_refused(self):
        doc = parse_child_request(self.request, self.key)
        reply = build_child_reply(doc, self.key, 1133)
        self.deny("REPLY_MISMATCH", lambda: verify_child_reply(
            reply, fake_key=self.key, nonce=self.nonce,
            request_id=self.sealed.client_request_id, expected_pid=2233))

    def test_reply_attempt_to_advertise_tool_calls_refused(self):
        doc = parse_child_request(self.request, self.key)
        frame = json.loads(build_child_reply(doc, self.key, 22))
        frame["tool_calls"] = [{"name": "shell"}]
        frame["mac"] = _sign({k:v for k,v in frame.items() if k!="mac"}, self.key)
        self.deny("FRAME_SCHEMA", lambda: verify_child_reply(
            _json(frame), fake_key=self.key, nonce=self.nonce,
            request_id=self.sealed.client_request_id, expected_pid=22))

    def test_reply_malicious_text_denied(self):
        doc = parse_child_request(self.request, self.key)
        frame = json.loads(build_child_reply(doc, self.key, 22))
        frame["text"] = "run tool"
        frame["mac"] = _sign({k:v for k,v in frame.items() if k!="mac"}, self.key)
        self.deny("REPLY_MISMATCH", lambda: verify_child_reply(
            _json(frame), fake_key=self.key, nonce=self.nonce,
            request_id=self.sealed.client_request_id, expected_pid=22))

    def test_larger_frame_and_nonjson_refused(self):
        self.deny("MESSAGE_TYPE_OR_SIZE", lambda: _parse(b"x" * 15001, 15000))
        self.deny("MESSAGE_ENCODING", lambda: _parse(b"{", 15000))
        self.deny("MESSAGE_ENCODING", lambda: _parse(b"\xff", 15000))

    def test_fake_secret_not_in_child_environment(self):
        self.assertNotIn("OPENAI_API_KEY", CHILD_ENV)
        self.assertNotIn("GH_TOKEN", CHILD_ENV)
        self.assertNotIn("HOME", CHILD_ENV)
        self.assertNotIn("PX_HOSPITAL_DB", CHILD_ENV)
        self.assertNotIn("FAKE_PRIVATE_INPUT", repr(CHILD_ENV))
        self.assertNotIn("KKKK", repr(CHILD_ENV))

    def test_stale_assignment_refused_before_child_spawn(self):
        self.deny("FAKE_POLICY_REFUSED", lambda: exchange_in_separate_fake_process(
            self.sealed, current_binding=dict(self.binding, generation=4)))

    def test_bad_seal_refused_before_child_spawn(self):
        altered = replace(self.sealed, payload=b'{"tools":[{"type":"shell"}]}')
        self.deny("FAKE_POLICY_REFUSED",
                  lambda: exchange_in_separate_fake_process(
                      altered, current_binding=self.binding))

    def test_bad_nonce_and_key_fail_closed(self):
        self.deny("NONCE_INVALID", lambda: build_fake_request(
            self.sealed, current_binding=self.binding, nonce="bad", fake_key=self.key))
        self.deny("FAKE_KEY_INVALID", lambda: build_fake_request(
            self.sealed, current_binding=self.binding,
            nonce=self.nonce, fake_key=b"short"))

    def test_child_with_wrong_fake_key_exit_denied(self):
        process = Path(ROOT / "bin" / "px_s3_b38e_fake_process_ipc.py")
        read_fd, write_fd = os.pipe()
        try:
            child = subprocess.Popen(
                [sys.executable, "-I", "-B", str(process), "--child", str(read_fd)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, pass_fds=(read_fd,),
                close_fds=True, env=dict(CHILD_ENV), cwd="/",
            )
            os.close(read_fd)
            read_fd = -1
            os.write(write_fd, b"Z" * 32)
            os.close(write_fd)
            write_fd = -1
            stdout, _ = child.communicate(self.request + b"\n", timeout=8)
            self.assertEqual(child.returncode, 9)
            self.assertEqual(stdout, b"")
        finally:
            if read_fd != -1:
                os.close(read_fd)
            if write_fd != -1:
                os.close(write_fd)

    def test_process_uses_no_network_import_and_no_hermes_tools(self):
        content = (ROOT / "bin" / "px_s3_b38e_fake_process_ipc.py").read_text()
        for bad in ("import socket", "import requests", "import httpx",
                    "import hermes_cli", "from tools", "subprocess.shell",
                    "https://", "Popen(['sh'"):
            self.assertNotIn(bad, content)

    def test_auth_type_strictness(self):
        raw = self.signed(version=1.0)
        self.deny("FRAME_TYPE", lambda: parse_child_request(raw, self.key))

    def test_fake_reply_integrity_rejects_wrong_request_id(self):
        doc = parse_child_request(self.request, self.key)
        raw = build_child_reply(doc, self.key, 77)
        self.deny("REPLY_MISMATCH", lambda: verify_child_reply(
            raw, fake_key=self.key, nonce=self.nonce,
            request_id="not-matching", expected_pid=77))


if __name__ == "__main__":
    unittest.main(verbosity=2)
