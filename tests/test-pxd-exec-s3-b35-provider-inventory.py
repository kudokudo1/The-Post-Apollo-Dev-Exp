#!/usr/bin/env python3
"""B35 offline CI: fake executable files, never launch native providers."""
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import px_s3_b35_provider_binary_inventory as b35


class B35OfflineInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="b35-no-provider-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fake-codex-executable"
        self.bytes = b"#!/bin/sh\n# FAKE: tests never execute this\n"
        self.path.write_bytes(self.bytes)
        self.path.chmod(0o755)

    def inspect(self, provider="codex", path="__B35_DEFAULT__"):
        # Unlike None, this dedicated default does not disguise invalid input.
        candidate = str(self.path) if path == "__B35_DEFAULT__" else path
        return b35.inventory_binary(provider, str(candidate) if isinstance(candidate, Path) else candidate)

    def denied(self, provider="codex", path="__B35_DEFAULT__", reason=None):
        with self.assertRaises(b35.InventoryRefusal) as caught:
            self.inspect(provider, path)
        if reason:
            self.assertEqual(str(caught.exception), "B35_REFUSED_" + reason)

    def test_hash_is_actual_bytes_and_no_provider_claim(self):
        result = self.inspect()
        self.assertEqual(result["sha256"], hashlib.sha256(self.bytes).hexdigest())
        self.assertEqual(result["fileKind"], "SHEBANG")
        self.assertEqual(result["provider"], "codex")
        self.assertEqual(result["decision"], "INVENTORY_ONLY")
        self.assertFalse(result["versionObserved"])
        self.assertFalse(result["modelOnlyCertified"])
        self.assertFalse(result["productionReady"])
        self.assertFalse(result["credentialsInspected"])
        self.assertFalse(result["providerStarted"])
        for k in ("modelCalls", "toolCalls", "hospitalWrites"):
            self.assertEqual(result[k], 0)

    def test_both_names_allowed_but_neither_admitted(self):
        for provider in ("codex", "hermes"):
            with self.subTest(provider=provider):
                result = self.inspect(provider)
                self.assertEqual(result["decision"], "INVENTORY_ONLY")
                self.assertFalse(result["modelOnlyCertified"])

    def test_repeated_inventory_stable(self):
        self.assertEqual(self.inspect(), self.inspect())

    def test_symlink_observed_not_treated_as_attestation(self):
        link = Path(self.tmp.name) / "codex-link"
        link.symlink_to(self.path)
        result = self.inspect(path=link)
        self.assertEqual(result["resolvedPath"], str(self.path))
        self.assertTrue(result["symlinkResolved"])
        self.assertFalse(result["productionReady"])

    def test_changed_bytes_change_hash(self):
        first = self.inspect()["sha256"]
        self.path.write_bytes(self.bytes + b"# altered\n")
        self.assertNotEqual(self.inspect()["sha256"], first)

    def test_reject_unrecognized_and_non_str_provider(self):
        for value in ("int1-fake", "openai-api", "", None, 7):
            with self.subTest(value=value):
                self.denied(provider=value, reason="PROVIDER")

    def test_reject_relative_traversal_double_slash_and_null(self):
        for path in ("codex", "", "/tmp/../bin", "/tmp/./bin",
                     "//tmp/codex", "/tmp/\x00codex", None):
            with self.subTest(path=path):
                self.denied(path=path, reason="ABSOLUTE_PATH")

    def test_missing_file_refused_without_path_disclosure(self):
        self.denied(path=Path(self.tmp.name) / "missing", reason="UNREADABLE_PATH")

    def test_directory_refused(self):
        self.denied(path=Path(self.tmp.name), reason="NOT_REGULAR_FILE")

    def test_non_executable_file_refused(self):
        self.path.chmod(0o644)
        self.denied(reason="NOT_EXECUTABLE")

    def test_empty_file_refused(self):
        self.path.write_bytes(b"")
        self.denied(reason="FILE_SIZE")

    def test_oversize_sparse_file_refused_before_hash(self):
        with self.path.open("r+b") as stream:
            stream.truncate(b35.MAX_BINARY_BYTES + 1)
        self.denied(reason="FILE_SIZE")

    def test_unknown_header_is_not_inferred_as_trusted(self):
        self.path.write_bytes(b"opaque executable test content")
        self.assertEqual(self.inspect()["fileKind"], "OTHER_EXECUTABLE")

    def test_metadata_drift_is_refused(self):
        with patch.object(b35, "_identity", side_effect=[(1,), (2,)]):
            self.denied(reason="CHANGED_DURING_READ")

    def test_cli_prints_structured_inventory_no_bytes_or_secrets(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = b35.main(["--provider", "codex", "--binary", str(self.path)])
        self.assertEqual(code, 0)
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed["decision"], "INVENTORY_ONLY")
        self.assertNotIn(self.bytes.decode(), out.getvalue())
        self.assertNotIn("token", parsed)
        self.assertNotIn("apiKey", parsed)
        self.assertFalse(parsed["providerStarted"])

    def test_cli_refusal_is_stable_without_path_echo(self):
        err = io.StringIO()
        missing = str(Path(self.tmp.name) / "does-not-exist")
        with redirect_stderr(err):
            code = b35.main(["--provider", "hermes", "--binary", missing])
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue().strip(), "B35_REFUSED_UNREADABLE_PATH")
        self.assertNotIn(missing, err.getvalue())

    def test_no_process_network_provider_login_or_sdk_import(self):
        # Even a deliberately executable fake payload is only read as bytes.
        with patch.object(subprocess, "Popen", side_effect=AssertionError("Popen")):
            with patch.object(subprocess, "run", side_effect=AssertionError("run")):
                with patch("socket.socket", side_effect=AssertionError("socket")):
                    result = self.inspect()
        self.assertEqual(result["modelCalls"], 0)
        self.assertEqual(result["hospitalWrites"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
