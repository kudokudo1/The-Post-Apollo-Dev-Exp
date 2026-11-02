#!/usr/bin/env python3
"""B38-A: fake-only PX model client; no credentials, Hermes or network."""
from dataclasses import FrozenInstanceError, replace
import ast
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from px_s3_b31_evidence_boundary import TestOnlyEvidenceIssuer
from px_s3_b37c_atomic_recovery_fixture import AtomicOfflineFixture
from px_s3_b37a_tool_free_contract import build_request
from px_s3_b37b_sealed_handoff import reserve_mock, seal_fixture
from px_s3_b38a_model_only_mock_client import (
    FakeTextStream, FakeTextReply, Refused, exchange_mock, require_real_send,
)

BINDING = {
    "room": "fake-room", "patient": "fake-patient",
    "assignment": "fake-assignment", "bed": "fake-bed",
    "turnId": "fake-turn", "generation": 7,
}


def frame(event, seq, **kwargs):
    return json.dumps(dict(type=event, seq=seq, **kwargs),
                      ensure_ascii=True, separators=(",", ":")).encode("ascii")


class B38AMockModelOnlyTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.conn.close)
        self.atomic = AtomicOfflineFixture(self.conn, TestOnlyEvidenceIssuer())
        self.ledger = self.atomic.ledger
        self.atomic.configure_mock_budget("fake-budget-scope", 20)
        self.binding = dict(BINDING)
        self.request = build_request("fake prompt secret marker")
        self.sealed = seal_fixture(self.request, binding=self.binding,
                                  attempt_id="fakeAttempt1")
        self.reserve()

    def reserve(self):
        return self.atomic.register_mock(self.sealed, scope="fake-budget-scope",
                                         units=3, current_binding=self.binding)

    def stream(self, frames=None, **changes):
        params = dict(request_id=self.sealed.client_request_id,
                      offered_bytes=self.sealed.payload,
                      frames=(frame("mock.text.delta", 0, text="fixture hello"),
                              frame("mock.text.completed", 1)))
        if frames is not None:
            params["frames"] = frames
        params.update(changes)
        return FakeTextStream(**params)

    def exchange(self, stream=None, **changes):
        params = dict(atomic=self.atomic, sealed=self.sealed,
                      current_binding=self.binding,
                      stream=self.stream() if stream is None else stream)
        params.update(changes)
        return exchange_mock(**params)

    def denied(self, code, call):
        with self.assertRaises(Refused) as cm:
            call()
        self.assertEqual(str(cm.exception), "B38A_REFUSED_" + code)
        self.assertNotIn("fake prompt secret marker", str(cm.exception))
        self.assertNotIn("fixture hello", str(cm.exception))

    def test_positive_control_is_fully_fake_text(self):
        result = self.exchange()
        self.assertIs(type(result), FakeTextReply)
        self.assertEqual(result.text, "fixture hello")
        self.assertEqual(result.client_request_id, self.sealed.client_request_id)
        self.assertEqual(result.provenance, "SYNTHETIC_IN_MEMORY_TEXT_ONLY")
        for field in ("launch_authorized", "real_model_called",
                      "real_transport_used", "production_ready"):
            self.assertIs(getattr(result, field), False)
        self.assertEqual(self.ledger.state(self.sealed.attempt_id)["state"],
                         "SUBMISSION_UNCONFIRMED")

    def test_multiple_text_deltas_are_collected_in_order(self):
        frames = (frame("mock.text.delta", 0, text="one"),
                  frame("mock.text.delta", 1, text="two"),
                  frame("mock.text.completed", 2))
        self.assertEqual(self.exchange(self.stream(frames)).text, "onetwo")

    def test_text_mentioning_tools_is_never_interpreted_as_tool_call(self):
        result = self.exchange(self.stream((
            frame("mock.text.delta", 0, text='{"type":"shell","command":"not executed"}'),
            frame("mock.text.completed", 1))))
        self.assertIn('"type":"shell"', result.text)
        self.assertIs(result.real_model_called, False)

    def test_real_send_is_unconditionally_refused(self):
        self.denied("NO_REAL_TRANSPORT_OR_PROVIDER_AUTHORITY",
                    lambda: require_real_send(self.sealed, key="fake"))
        self.assertEqual(self.ledger.state(self.sealed.attempt_id)["state"], "RESERVED")

    def test_reject_fake_transport_subclasses_and_arbitrary_callbacks(self):
        class Untrusted(FakeTextStream):
            pass
        self.denied("IN_MEMORY_STREAM_REQUIRED",
                    lambda: self.exchange(Untrusted(**{
                        "request_id": self.sealed.client_request_id,
                        "offered_bytes": self.sealed.payload,
                        "frames": self.stream().frames,
                    })))
        self.denied("IN_MEMORY_STREAM_REQUIRED",
                    lambda: self.exchange(stream=lambda: self.stream()))

    def test_tool_mcp_delegate_plugin_and_native_frames_refused(self):
        for event in ("response.output_item.added", "function_call",
                      "mock.tool.call", "mcp.tool_call", "browser.navigate",
                      "plugin_hook", "delegate_task", "memory.write",
                      "session_search", "context.engine", "cron.start",
                      "terminal", "response.completed"):
            with self.subTest(event=event):
                self.denied("NON_TEXT_EVENT",
                            lambda: self.exchange(self.stream((
                                frame("mock.text.delta", 0, text="hello"),
                                frame(event, 1)))))
                self.assertEqual(self.ledger.state(self.sealed.attempt_id)["state"],
                                 "RESERVED")

    def test_excess_fields_on_text_frame_refused(self):
        for field_name in ("tool_calls", "function_call", "mcp_servers",
                           "plugin", "headers", "authorization", "endpoint"):
            with self.subTest(field=field_name):
                f = frame("mock.text.delta", 0, text="hello", **{field_name: "fake"})
                self.denied("FRAME_SCHEMA", lambda: self.exchange(self.stream((
                    f, frame("mock.text.completed", 1)))))

    def test_completed_frame_extra_fields_refused(self):
        self.denied("FRAME_SCHEMA", lambda: self.exchange(self.stream((
            frame("mock.text.delta", 0, text="hello"),
            frame("mock.text.completed", 1, tools=[])))))

    def test_unordered_and_duplicate_sequence_refused(self):
        for frames in (
            (frame("mock.text.delta", 2, text="hello"), frame("mock.text.completed", 3)),
            (frame("mock.text.delta", 0, text="hello"), frame("mock.text.completed", 0)),
        ):
            self.denied("FRAME_ORDER", lambda: self.exchange(self.stream(frames)))

    def test_boolean_and_negative_sequence_refused(self):
        for value in (True, -1, 1.5, "0"):
            self.denied("SEQUENCE_INVALID", lambda: self.exchange(self.stream((
                frame("mock.text.delta", value, text="hello"),
                frame("mock.text.completed", 1)))))

    def test_no_completion_or_early_completion_refused(self):
        self.denied("COMPLETION_REQUIRED", lambda: self.exchange(self.stream((
            frame("mock.text.delta", 0, text="one"),
            frame("mock.text.delta", 1, text="two")))))
        self.denied("COMPLETION_ORDER", lambda: self.exchange(self.stream((
            frame("mock.text.completed", 0),
            frame("mock.text.delta", 1, text="two")))))

    def test_text_invalid_or_surrogate_refused(self):
        for value in ("", None, False, {}, 2):
            self.denied("TEXT_INVALID", lambda: self.exchange(self.stream((
                frame("mock.text.delta", 0, text=value),
                frame("mock.text.completed", 1)))))
        self.denied("TEXT_ENCODING", lambda: self.exchange(self.stream((
            frame("mock.text.delta", 0, text="\ud800"),
            frame("mock.text.completed", 1)))))

    def test_duplicate_keys_refused(self):
        raw = b'{"type":"mock.text.delta","seq":0,"text":"hi","text":"evil"}'
        self.denied("DUPLICATE_FRAME_KEY", lambda: self.exchange(self.stream((
            raw, frame("mock.text.completed", 1)))))

    def test_malformed_json_nonfinite_and_non_utf8_refused(self):
        for raw, reason in (
            (b"\xff", "FRAME_ENCODING_OR_JSON"),
            (b"{no", "FRAME_ENCODING_OR_JSON"),
            (b'{"type":"mock.text.delta","seq":0,"text":NaN}', "NONFINITE_FRAME_VALUE"),
        ):
            self.denied(reason, lambda: self.exchange(self.stream((
                raw, frame("mock.text.completed", 1)))))

    def test_reject_nonbytes_and_oversized_frame(self):
        for raw in ("not bytes", {}, b"", b"x" * 2049):
            self.denied("FRAME_TYPE_OR_SIZE", lambda: self.exchange(self.stream((
                raw, frame("mock.text.completed", 1)))))

    def test_reject_overlong_total_text(self):
        frames = tuple(frame("mock.text.delta", i, text="a" * 1050)
                       for i in range(4)) + (frame("mock.text.completed", 4),)
        self.denied("TEXT_OVER_BUDGET",
                    lambda: self.exchange(self.stream(frames)))

    def test_reject_missing_or_excessive_frames(self):
        for frames in ((), (frame("mock.text.completed", 0),),
                       tuple(frame("mock.text.delta", i, text="a")
                             for i in range(33)), [b"fake", b"fake"]):
            self.denied("FRAME_COUNT", lambda: self.exchange(self.stream(frames)))

    def test_request_identity_and_offered_bytes_mismatch(self):
        self.denied("REQUEST_ID_MISMATCH",
                    lambda: self.exchange(self.stream(request_id="foreign-id")))
        self.denied("OFFERED_BYTES_MISMATCH",
                    lambda: self.exchange(self.stream(offered_bytes=b'{"tools":[]}')))

    def test_modified_original_request_does_not_change_seal(self):
        original = self.sealed.payload
        self.request["tools"].append({"type": "terminal"})
        self.request["input"][0]["content"] = "fake altered"
        self.assertEqual(self.sealed.payload, original)
        self.assertEqual(self.exchange().text, "fixture hello")

    def test_reject_tampered_seal(self):
        altered = replace(self.sealed, payload=b'{"tools":[{"type":"shell"}]}')
        self.denied("SEALED_REQUEST_INVALID",
                    lambda: self.exchange(sealed=altered))

    def test_reject_stale_hospital_fixture_binding(self):
        foreign = dict(self.binding, generation=8)
        self.denied("SEALED_REQUEST_INVALID",
                    lambda: self.exchange(current_binding=foreign))

    def test_reject_unreserved_and_replayed_mock_handoff(self):
        self.ledger.mark_submission(self.sealed.attempt_id, self.binding)
        self.denied("B37C_ATOMIC_HANDOFF_DENIED", lambda: self.exchange())

    def test_replay_after_single_success_denied(self):
        self.assertEqual(self.exchange().text, "fixture hello")
        self.denied("B37C_ATOMIC_HANDOFF_DENIED", lambda: self.exchange())

    def test_never_accepts_real_ledger_or_stream_or_subclasses(self):
        self.denied("B37C_ATOMIC_FIXTURE_REQUIRED", lambda: self.exchange(atomic={}))
        self.denied("FAKE_SEAL_REQUIRED", lambda: self.exchange(sealed={}))
        self.denied("IN_MEMORY_STREAM_REQUIRED", lambda: self.exchange(stream={}))

    def test_fake_reply_is_immutable(self):
        reply = self.exchange()
        with self.assertRaises(FrozenInstanceError):
            reply.production_ready = True

    def test_module_has_no_hermes_native_or_network_imports(self):
        source = (ROOT / "bin" / "px_s3_b38a_model_only_mock_client.py").read_text()
        tree = ast.parse(source)
        imports = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imports.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                imports.add(n.module.split(".")[0])
        self.assertFalse(imports & {
            "hermes_cli", "run_agent", "model_tools", "tools", "socket",
            "subprocess", "requests", "urllib", "http", "httpx", "aiohttp",
            "openai", "litellm", "ctypes",
        })
        self.assertIn("px_s3_b37b_sealed_handoff", imports)
        self.assertIn("px_s3_b37c_atomic_recovery_fixture", imports)
        for keyword in ("os.system", "eval(", "exec(", "Popen(", "create_connection("):
            self.assertNotIn(keyword, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
