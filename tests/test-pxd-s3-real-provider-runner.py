#!/usr/bin/env python3
"""Offline S3 runner contract checks. NEVER launches a real AI provider."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests/manual/doctor_succession_real_provider.py"


class RealProviderRunnerSafetyTests(unittest.TestCase):
    def script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True, capture_output=True, timeout=10, check=False
        )

    def test_dry_run_creates_nothing_and_never_contacts_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "not-created"
            p = self.script("--workspace", str(dest), "--provider", "hermes")
            self.assertEqual(p.returncode, 0, p.stderr)
            result = json.loads(p.stdout)
            self.assertEqual(result["mode"], "DRY_RUN_NO_PROVIDER")
            self.assertEqual(result["writesOnDryRun"], 0)
            self.assertFalse(dest.exists())

    def test_real_launch_requires_explicit_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "not-created"
            p = self.script("--workspace", str(dest), "--execute")
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("--ack-provider-access", p.stderr)
            self.assertFalse(dest.exists())

    def test_mock_cannot_be_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "not-created"
            p = self.script("--workspace", str(dest), "--provider", "mock")
            self.assertNotEqual(p.returncode, 0)
            self.assertFalse(dest.exists())

    def test_relative_destination_rejected_without_side_effect(self):
        p = self.script("--workspace", "relative-test-bed")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("absolute path", p.stderr)

    def test_wrapper_captures_exact_stdin_and_execs_real_binary(self):
        spec = importlib.util.spec_from_file_location("s3runner", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = Path(tmp) / "wrapper.py"
            wrapper.write_text(module.WRAPPER)
            capture = Path(tmp) / "stdin.txt"
            payload = "Exact Doctor B test input\nROOM_REPORT #42\n"
            import os
            env = dict(os.environ, PX_S3_REAL_PROVIDER_BIN=sys.executable,
                       PX_S3_CAPTURE_TARGET=str(capture))
            p = subprocess.run([
                sys.executable, str(wrapper), "-c",
                "import sys; print(sys.stdin.read(), end='')",
            ], input=payload, text=True, capture_output=True,
               env=env, timeout=10, check=False)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout, payload)
            self.assertEqual(capture.read_text(), payload)
            self.assertEqual(capture.stat().st_mode & 0o777, 0o600)

    def test_required_evidence_and_no_default_real_execution(self):
        src = SCRIPT.read_text()
        for required in (
            "provider-input-A.txt", "provider-input-B.txt",
            "requiredHandoffs", "approvedRoomChart",
            "turn-A.json", "turn-B.json",
            "providerSessionId", "--ack-provider-access",
        ):
            # Capture/turn paths are formed through parameterized suffixes;
            # verify exact patterns rather than the instantiated filename.
            if required.startswith(("provider-input-", "turn-")):
                continue
            self.assertIn(required, src)
        self.assertIn('workspace / f"provider-input-{name}.txt"', src)
        self.assertIn('workspace / f"turn-{name}.json"', src)
        self.assertIn('if not args.execute:', src)
        self.assertIn("humanReviewRequired", src)


if __name__ == "__main__":
    unittest.main()
