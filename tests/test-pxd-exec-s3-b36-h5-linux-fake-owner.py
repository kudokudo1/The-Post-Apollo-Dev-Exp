#!/usr/bin/env python3
"""B36-H5 / Linux fake process-group evidence: CI disposable runner only."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from px_s3_b36_h5_linux_fake_owner_probe import (
    parse_proc_stat, exercise_fake_group, _read_identity, PROBE_ENV_FLAG,
)

CI_FAKE_ENABLED = (
    sys.platform.startswith("linux") and
    os.environ.get("GITHUB_ACTIONS") == "true" and
    os.environ.get(PROBE_ENV_FLAG) == "1"
)


def sample(stat_pid=123, comm="fake worker (safe)", state="S",
           parent=1, pgid=123, sid=123, birth=777):
    # proc stat field 22 is starttime, relative to 3rd field it is index 19.
    fields = [state, str(parent), str(pgid), str(sid)] + ["0"] * 15 + [str(birth)]
    return f"{stat_pid} ({comm}) " + " ".join(fields)


class H5ReadOnlyStatParserTests(unittest.TestCase):
    def test_proc_parser_extracts_kernel_identity_fields(self):
        got = parse_proc_stat(sample())
        self.assertEqual(got, {"pid": 123, "state": "S", "ppid": 1,
                               "processGroup": 123, "session": 123,
                               "startTicks": 777})

    def test_proc_parser_handles_nested_parentheses_and_spaces(self):
        got = parse_proc_stat(sample(42, "fake (agent) x) y", "R",
                                          parent=10, pgid=20, sid=30, birth=900))
        self.assertEqual((got["pid"], got["startTicks"], got["session"]),
                         (42, 900, 30))

    def test_proc_parser_rejects_bad_pid_and_truncated_records(self):
        for val in ("", "bad", "oops (worker) S", "5 (worker) S 1 2",
                    sample(0), sample(-1), sample("1X")):
            with self.subTest(value=str(val)[:40]):
                with self.assertRaises(ValueError):
                    parse_proc_stat(val)

    def test_proc_parser_rejects_invalid_birth_and_state(self):
        for val in (sample(birth=-2), sample(state="?"), sample(birth="none")):
            with self.subTest(record=val[:65]):
                with self.assertRaises(ValueError):
                    parse_proc_stat(val)

    def test_proc_parser_caps_record_length(self):
        with self.assertRaises(ValueError):
            parse_proc_stat(sample() + "X" * 70000)

    def test_proc_parser_does_not_mutate_input_or_create_processes(self):
        text = sample()
        with patch("subprocess.Popen", side_effect=AssertionError("unexpected Popen")):
            got = parse_proc_stat(text)
        self.assertEqual(got["startTicks"], 777)
        self.assertEqual(text, sample())

    def test_read_only_observation_of_current_test_process(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux /proc only")
        got = _read_identity(os.getpid())
        self.assertIsNotNone(got)
        self.assertEqual(got["pid"], os.getpid())
        self.assertEqual(got["processGroup"], os.getpgrp())
        self.assertGreater(got["startTicks"], 0)

    def test_unarmed_ci_refuses_without_spawning_anything(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false",
                                     PROBE_ENV_FLAG: "1"}):
            with patch("subprocess.Popen", side_effect=AssertionError("spawn")):
                with self.assertRaisesRegex(RuntimeError, "CI_ONLY"):
                    exercise_fake_group()

    def test_missing_explicit_ci_optin_refuses(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true",
                                     PROBE_ENV_FLAG: "0"}):
            with patch("subprocess.Popen", side_effect=AssertionError("spawn")):
                with self.assertRaisesRegex(RuntimeError, "CI_ONLY"):
                    exercise_fake_group()

    def test_proc_parser_refuses_untrusted_non_string_input(self):
        for value in (None, {}, ["1", "2"], 12, True):
            with self.subTest(type=type(value).__name__):
                with self.assertRaises(ValueError):
                    parse_proc_stat(value)


@unittest.skipUnless(CI_FAKE_ENABLED, "only isolated GitHub CI opt-in can spawn fake Python")
class H5DisposableFakeLinuxProcessTests(unittest.TestCase):
    def test_same_group_descendant_stops_on_group_kill_but_is_not_certified(self):
        report = exercise_fake_group(escaped_descendant=False)
        self.assertEqual(report["kind"], "FAKE_SHARED_PGID")
        self.assertTrue(report["observedSameGroup"])
        self.assertFalse(report["descendantSurvivedGroupKill"])
        self.assertTrue(report["workerExecutionStopped"])
        self.assertFalse(report["completeDescendantTeardownCertified"])

    def test_setsid_descendant_escapes_group_kill_then_is_cleaned_up(self):
        report = exercise_fake_group(escaped_descendant=True)
        self.assertEqual(report["kind"], "FAKE_SETSID_ESCAPE")
        self.assertFalse(report["observedSameGroup"])
        self.assertTrue(report["descendantSurvivedGroupKill"])
        self.assertTrue(report["workerExecutionStopped"])
        self.assertFalse(report["completeDescendantTeardownCertified"])

    def test_no_kernel_network_credential_or_production_admission(self):
        report = exercise_fake_group(escaped_descendant=False)
        self.assertEqual(report["decision"], "DENY")
        for key in ("networkEgressPrevented", "credentialBoundaryCertified",
                    "completeDescendantTeardownCertified", "realHermesLaunched",
                    "productionReady"):
            self.assertFalse(report[key])
        for key in ("gatewayCalls", "modelCalls", "toolCalls", "hospitalWrites"):
            self.assertEqual(report[key], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
