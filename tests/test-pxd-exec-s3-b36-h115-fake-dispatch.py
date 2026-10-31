#!/usr/bin/env python3
"""B36-H11.5 negative dispatch tests: no Hermes, OS, network or Hospital access."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from pxd_b36_h115_fake_dispatch import FakeAuthority, FakeBroker, FAKE_TOOL


class H115OfflineFakeDispatchTests(unittest.TestCase):
    def setUp(self):
        self.authority = FakeAuthority()
        self.broker = FakeBroker(self.authority)

    def queue(self, **changes):
        params = {"tool": FAKE_TOOL, "claimed_scope": self.authority.current_scope()}
        params.update(changes)
        return self.broker.trusted_queue_fixture(**params)

    def assert_denied(self, result, reason):
        self.assertEqual(result["decision"], "DENY")
        self.assertEqual(result["reason"], reason)
        self.assertEqual(result["fakeHandlerCalls"], 0)
        self.assertFalse(result["launchAuthorized"])
        self.assertFalse(result["productionReady"])
        for k in ("modelCalls", "providerCalls", "hospitalWrites"):
            self.assertEqual(result[k], 0)
        self.assertEqual(set(result), {"decision", "reason", "fakeHandlerCalls",
                                       "launchAuthorized", "productionReady",
                                       "modelCalls", "providerCalls", "hospitalWrites"})

    def test_positive_control_only_inert_counter(self):
        ticket = self.queue()
        outcome = self.broker.trusted_dispatch_fixture(ticket)
        self.assertEqual(outcome["decision"], "OFFLINE_FAKE_EXECUTED")
        self.assertEqual(outcome["reason"], "FIXTURE_COUNTER_ONLY")
        self.assertEqual(outcome["fakeHandlerCalls"], 1)
        self.assertFalse(outcome["launchAuthorized"])
        self.assertFalse(outcome["productionReady"])
        self.assertEqual(self.broker.fake_handler_calls, 1)

    def test_native_direct_dispatch_no_handler(self):
        self.assert_denied(self.broker.from_model_or_native("terminal", {"command": "example"}),
                           "UNTRUSTED_DISPATCH_ORIGIN")

    def test_hidden_tool_or_plugin_bypass_no_handler(self):
        for name in ("terminal", "write_file", "browser_click", "delegate_task",
                     "mcp_arbitrary", "tool_call", "fixture_counter"):
            self.assert_denied(self.broker.from_model_or_native(name),
                               "UNTRUSTED_DISPATCH_ORIGIN")

    def test_alleged_model_grant_is_not_authority(self):
        ticket = self.queue()
        self.assert_denied(self.broker.from_model_or_native(FAKE_TOOL, alleged_grant=ticket),
                           "UNTRUSTED_DISPATCH_ORIGIN")
        self.assertEqual(self.broker.fake_handler_calls, 0)

    def test_unknown_tool_cannot_be_granted(self):
        self.assert_denied(self.queue(tool="terminal"), "TOOL_NOT_GRANTED")

    def test_foreign_patient_scope_refused(self):
        scope = self.authority.current_scope()
        scope["patient"] = "another-patient"
        self.assert_denied(self.queue(claimed_scope=scope), "STALE_OR_FOREIGN_AUTHORITY")

    def test_foreign_room_scope_refused(self):
        scope = self.authority.current_scope()
        scope["room"] = "another-room"
        self.assert_denied(self.queue(claimed_scope=scope), "STALE_OR_FOREIGN_AUTHORITY")

    def test_malformed_scope_refused(self):
        for scope in ({"patient": "p"}, {**self.authority.current_scope(), "extra": "x"},
                      {**self.authority.current_scope(), "generation": True},
                      {**self.authority.current_scope(), "turn": ""}):
            self.assert_denied(self.queue(claimed_scope=scope), "SCOPE_INVALID")

    def test_pause_after_queue_prevents_launch(self):
        ticket = self.queue()
        self.authority.pause()
        self.assert_denied(self.broker.trusted_dispatch_fixture(ticket),
                           "STALE_OR_FOREIGN_AUTHORITY")

    def test_permission_withdrawal_after_queue_prevents_launch(self):
        ticket = self.queue()
        self.authority.revoke_tool()
        self.assert_denied(self.broker.trusted_dispatch_fixture(ticket),
                           "STALE_OR_FOREIGN_AUTHORITY")

    def test_assignment_change_after_queue_prevents_launch(self):
        ticket = self.queue()
        self.authority.change_assignment()
        self.assert_denied(self.broker.trusted_dispatch_fixture(ticket),
                           "STALE_OR_FOREIGN_AUTHORITY")

    def test_replayed_ticket_does_not_execute_twice(self):
        ticket = self.queue()
        self.assertEqual(self.broker.trusted_dispatch_fixture(ticket)["decision"],
                         "OFFLINE_FAKE_EXECUTED")
        self.assertEqual(self.broker.trusted_dispatch_fixture(ticket)["reason"],
                         "GRANT_NOT_ISSUED_OR_REPLAYED")
        self.assertEqual(self.broker.fake_handler_calls, 1)

    def test_forged_copy_rejected_even_if_fields_match(self):
        ticket = self.queue()
        self.assert_denied(self.broker.trusted_dispatch_fixture(replace(ticket)),
                           "GRANT_NOT_ISSUED_OR_REPLAYED")
        self.assertEqual(self.broker.fake_handler_calls, 0)

    def test_resume_needs_fresh_validation_and_pinned_identity(self):
        self.assert_denied(self.queue(mode="REQUESTED_RESUME",
                                      resume_identity="fake-provider-session"),
                           "RESUME_NOT_REVALIDATED")
        self.authority.mark_resume_revalidated()
        self.assert_denied(self.queue(mode="REQUESTED_RESUME",
                                      resume_identity="foreign-session"),
                           "RESUME_NOT_REVALIDATED")
        ticket = self.queue(mode="REQUESTED_RESUME",
                            resume_identity="fake-provider-session")
        self.assertEqual(self.broker.trusted_dispatch_fixture(ticket)["decision"],
                         "OFFLINE_FAKE_EXECUTED")

    def test_native_auto_resume_and_reconnect_never_mint_grants(self):
        for mode in ("NATIVE_AUTO_RESUME", "PLATFORM_RECONNECT", "RESTART_REPLAY"):
            self.assert_denied(self.queue(mode=mode), "NATIVE_REPLAY_OR_MODE_DENIED")

    def test_restart_invalidates_queued_grant(self):
        ticket = self.queue()
        self.authority.restart()
        self.assert_denied(self.broker.trusted_dispatch_fixture(ticket),
                           "RESTART_INVALIDATED_GRANT")

    def test_revoked_authority_cannot_queue_again(self):
        self.authority.revoke_tool()
        self.assert_denied(self.queue(), "AUTHORITY_REVOKED")

    def test_paused_authority_cannot_queue_again(self):
        self.authority.pause()
        self.assert_denied(self.queue(), "AUTHORITY_REVOKED")

    def test_untrusted_payload_not_reflected_in_refusal(self):
        secret = "fake-secret-sentinel-NEVER-ECHO"
        result = self.broker.from_model_or_native(secret, {"key": secret})
        self.assertNotIn(secret, repr(result))
        self.assert_denied(result, "UNTRUSTED_DISPATCH_ORIGIN")

    def test_bad_ticket_type_does_not_reach_handler(self):
        for ticket in (None, {}, "ticket", 7, True):
            self.assert_denied(self.broker.trusted_dispatch_fixture(ticket),
                               "GRANT_NOT_ISSUED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
