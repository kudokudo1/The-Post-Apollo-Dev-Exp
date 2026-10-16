#!/usr/bin/env python3
"""INT1-P1 fixture security regression; no real AI, Fedora or live Hospital."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch

from px_int1_fixture import DisposablePX, FixtureRefusal

ROOT = Path(__file__).resolve().parents[1]

class INT1P1ConfinementTests(unittest.TestCase):
    def test_clean_disposable_environment_runs_actual_hospital_init(self):
        with DisposablePX(ROOT) as fixture:
            self.assertTrue(fixture.assert_safe_environment())
            self.assertEqual(json.loads((fixture.root / "providers/fake.json").read_text())["providers"], {})
            result = fixture.hospital("init")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((fixture.root / "hospital/data/hospital.db").is_file())
            self.assertTrue(fixture.assert_safe_environment())

    def test_inherited_outside_root_database_override_leaves_canary_untouched(self):
        with tempfile.TemporaryDirectory(prefix="int1-canary-", dir="/tmp") as outside:
            canary = Path(outside) / "live-hospital-canary.db"
            with sqlite3.connect(canary) as db:
                db.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
                db.execute("INSERT INTO sentinel(value) VALUES ('never-migrate')")
                db.execute("PRAGMA user_version = 8472")
                db.commit()
            original = canary.read_bytes()
            digest = hashlib.sha256(original).hexdigest()
            before = canary.stat().st_mtime_ns
            listing = sorted(p.name for p in Path(outside).iterdir())
            with patch.dict(os.environ, {
                "PX_HOSPITAL_DB": str(canary),
                "PX_HOSPITAL_DATA_DIR": str(Path(outside)),
                "HOME": str(outside),
                "XDG_DATA_HOME": str(outside),
                "TMPDIR": str(outside),
                "PX_AGENT_LOCK_DIR": str(outside),
                "PX_AGENT_AUTHORITY_DIR": str(outside),
                "PX_AGENT_PROVIDER_CONFIG": str(canary),
                "OPENAI_API_KEY": "DUMMY_NEVER_PASS_TO_CHILD",
                "PYTHONPATH": str(outside),
            }):
                with DisposablePX(ROOT) as fixture:
                    self.assertNotIn(str(canary), fixture.env.values())
                    self.assertNotIn("OPENAI_API_KEY", fixture.env)
                    self.assertNotIn("PYTHONPATH", fixture.env)
                    self.assertEqual(fixture.hospital("init").returncode, 0)
                    self.assertTrue((fixture.root / "hospital/data/hospital.db").exists())
            self.assertEqual(canary.read_bytes(), original)
            self.assertEqual(hashlib.sha256(canary.read_bytes()).hexdigest(), digest)
            self.assertEqual(canary.stat().st_mtime_ns, before)
            with sqlite3.connect(f"file:{canary}?mode=ro&immutable=1", uri=True) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 8472)
                self.assertEqual(db.execute("SELECT value FROM sentinel").fetchone()[0], "never-migrate")
            self.assertEqual(sorted(p.name for p in Path(outside).iterdir()), listing)
            for suffix in ("-wal", "-shm", "-journal"):
                self.assertFalse(Path(str(canary) + suffix).exists())

    def test_symlinked_db_refused_before_process(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as outside:
            target = Path(outside) / "foreign.db"
            target.write_bytes(b"INT1-DO-NOT-TOUCH")
            with DisposablePX(ROOT) as fixture:
                (fixture.root / "hospital/data/hospital.db").symlink_to(target)
                with patch("px_int1_fixture.subprocess.run", side_effect=AssertionError("spawned!")):
                    with self.assertRaises(FixtureRefusal):
                        fixture.hospital("init")
                self.assertEqual(target.read_bytes(), b"INT1-DO-NOT-TOUCH")

    def test_symlinked_db_parent_refused_before_process(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as outside:
            with DisposablePX(ROOT) as fixture:
                p = fixture.root / "hospital/data"
                p.rmdir()
                p.symlink_to(outside, target_is_directory=True)
                with patch("px_int1_fixture.subprocess.run", side_effect=AssertionError("spawned!")):
                    with self.assertRaises(FixtureRefusal):
                        fixture.hospital("init")
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_outside_root_and_hostile_home_registry_and_lock_refused(self):
        with DisposablePX(ROOT) as fixture:
            for key, value in (
                ("PX_HOSPITAL_DB", "/tmp/foreign-hospital.db"),
                ("HOME", "/home/operator"),
                ("XDG_RUNTIME_DIR", "/run/user/operator"),
                ("TMPDIR", "/tmp"),
                ("PX_AGENT_LOCK_DIR", "/tmp/locks"),
                ("PX_AGENT_AUTHORITY_DIR", "/tmp/authority"),
                ("PX_AGENT_PROVIDER_CONFIG", "/tmp/real-providers.json"),
            ):
                with self.subTest(key=key):
                    original = fixture.env[key]
                    fixture.env[key] = value
                    with patch("px_int1_fixture.subprocess.run", side_effect=AssertionError("spawned!")):
                        with self.assertRaises(FixtureRefusal):
                            fixture.hospital("init")
                    fixture.env[key] = original
            self.assertTrue(fixture.assert_safe_environment())

    def test_unexpected_inherited_credential_or_path_is_refused(self):
        with DisposablePX(ROOT) as fixture:
            fixture.env["CODEX_HOME"] = "/home/host/.codex"
            with patch("px_int1_fixture.subprocess.run", side_effect=AssertionError("spawned!")):
                with self.assertRaises(FixtureRefusal):
                    fixture.hospital("init")

    def test_bad_registry_and_unsafe_directory_permissions_refused(self):
        with DisposablePX(ROOT) as fixture:
            registry = fixture.root / "providers/fake.json"
            registry.chmod(0o644)
            with self.assertRaises(FixtureRefusal):
                fixture.assert_safe_environment()
            registry.chmod(0o600)
            home = fixture.root / "home"
            home.chmod(0o755)
            with self.assertRaises(FixtureRefusal):
                fixture.assert_safe_environment()

if __name__ == "__main__":
    unittest.main(verbosity=2)
