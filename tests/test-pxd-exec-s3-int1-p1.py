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
            observed = fixture.run("/usr/bin/env")
            self.assertEqual(observed.returncode, 0, observed.stderr)
            effective = dict(line.split("=", 1) for line in observed.stdout.splitlines())
            self.assertEqual(effective.pop("PWD", ""), "/fixture", "namespace-chdir PWD must be sandbox-owned")
            self.assertEqual(effective, fixture.env, "child must see exactly the allowlist")
            self.assertNotIn("PX_INT1_FAKE_PRODUCTION", effective)
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

    def test_os_namespace_hides_host_and_allows_only_fixture_writes(self):
        with DisposablePX(ROOT) as fixture:
            host_marker = "/tmp/INT1-OUTSIDE-MUST-NOT-BE-READABLE"
            code = (
                "import json,os,pathlib,socket;"
                "p=pathlib.Path;"
                "v={'host_hidden':not p('/home/runner').exists() and not p('/etc/passwd').exists(),"
                "'repo_metadata_hidden':not p('/source/.git').exists(),"
                "'provider_paths_hidden':not p('/source/config').exists() and not p('/source/bin/px-agent').exists(),"
                "'fixture_write':False};"
                "v['fixture_write']=(p('/fixture/scratch/probe.txt').write_text('ok')==2);"
                "print(json.dumps(v))"
            )
            result = fixture.run("/usr/bin/python3", "-B", "-c", code)
            self.assertEqual(result.returncode, 0, result.stderr)
            assertions = json.loads(result.stdout)
            self.assertTrue(assertions["host_hidden"])
            self.assertTrue(assertions["repo_metadata_hidden"])
            self.assertTrue(assertions["provider_paths_hidden"])
            self.assertTrue(assertions["fixture_write"])
            self.assertEqual((fixture.root / "scratch/probe.txt").read_text(), "ok")
            self.assertFalse(Path(host_marker).exists())

    def test_root_replacement_after_preflight_writes_only_to_fd_anchored_root(self):
        with tempfile.TemporaryDirectory(prefix="int1-race-canary-") as outside:
            foreign = Path(outside) / "hostile-root"
            foreign.mkdir(mode=0o700)
            canary = foreign / "hospital.db"
            canary.write_bytes(b"HOST-CANARY-NO-OPEN")
            before = canary.read_bytes()
            with DisposablePX(ROOT) as fixture:
                original = fixture.root
                detached = Path(outside) / "original-root-detached"
                def replace_after_anchor():
                    original.rename(detached)
                    original.symlink_to(foreign, target_is_directory=True)
                result = fixture.hospital("init", after_anchor=replace_after_anchor)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((detached / "hospital/data/hospital.db").is_file())
                self.assertEqual(canary.read_bytes(), before)
                self.assertEqual(sorted(p.name for p in foreign.iterdir()), ["hospital.db"])
            # Cleanup must not traverse the hostile symlink.
            self.assertEqual(canary.read_bytes(), before)
            original.unlink()  # remove ONLY the detached fixture's substituted symlink

    def test_database_parent_swapped_after_preflight_cannot_open_host_canary(self):
        with tempfile.TemporaryDirectory(prefix="int1-parent-swap-") as outside:
            canary = Path(outside) / "hospital.db"
            canary.write_bytes(b"FOREIGN-SQLITE-CANARY")
            with DisposablePX(ROOT) as fixture:
                data = fixture.root / "hospital/data"
                def swap_parent_after_anchor():
                    data.rmdir()
                    data.symlink_to(outside, target_is_directory=True)
                result = fixture.hospital("init", after_anchor=swap_parent_after_anchor)
                self.assertNotEqual(result.returncode, 0, "swapped DB parent must fail closed")
                self.assertEqual(canary.read_bytes(), b"FOREIGN-SQLITE-CANARY")
                self.assertEqual(sorted(p.name for p in Path(outside).iterdir()), ["hospital.db"])

    def test_cleanup_refuses_different_inode_same_permission_replacement(self):
        with tempfile.TemporaryDirectory(prefix="int1-cleanup-swap-") as outside:
            with DisposablePX(ROOT) as fixture:
                original = fixture.root
                preserved = Path(outside) / "original"
                replacement = Path(outside) / "replacement"
                replacement.mkdir(mode=0o700)
                sentinel = replacement / "preserve.txt"
                sentinel.write_text("NO DELETE")
                original.rename(preserved)
                replacement.rename(original)
            self.assertEqual((original / "preserve.txt").read_text(), "NO DELETE")
            # Restore host-side test names for TemporaryDirectory cleanup.
            original.rename(replacement)

    def test_cleanup_root_swap_before_quarantine_check_keeps_foreign_data(self):
        with tempfile.TemporaryDirectory(prefix="int1-cleanup-race-") as outside:
            with DisposablePX(ROOT) as fixture:
                root = fixture.root
                preserved = Path(outside) / "original-fixture"
                foreign = Path(outside) / "foreign"
                foreign.mkdir(mode=0o700)
                (foreign / "hospital.db").write_bytes(b"FOREIGN-DO-NOT-DELETE")
                original_rename = os.rename
                swapped = []
                def swap_on_quarantine(src, dst, **kwargs):
                    if not swapped and Path(src) == root and dst == "fixture":
                        qfd = kwargs["dst_dir_fd"]
                        quarantine = Path(os.readlink("/proc/self/fd/" + str(qfd)))
                        original_rename(root, preserved)
                        original_rename(foreign, root)
                        swapped.append(quarantine / "fixture")
                    return original_rename(src, dst, **kwargs)
                with patch("px_int1_fixture.os.rename", side_effect=swap_on_quarantine):
                    with self.assertRaisesRegex(FixtureRefusal, "substituted cleanup root"):
                        fixture.close()
                self.assertEqual(len(swapped), 1)
                self.assertEqual((swapped[0] / "hospital.db").read_bytes(),
                                 b"FOREIGN-DO-NOT-DELETE")
            self.assertEqual((swapped[0] / "hospital.db").read_bytes(),
                             b"FOREIGN-DO-NOT-DELETE")
            swapped[0].rename(foreign)
            swapped[0].parent.rmdir()

    def test_cleanup_post_identity_swap_never_recursively_deletes_foreign(self):
        """C1: foreign substitution AFTER fstat, BEFORE the recursive walk."""
        import px_int1_fixture
        with tempfile.TemporaryDirectory(prefix="int1-after-check-") as outside:
            foreign = Path(outside) / "foreign"
            foreign.mkdir(mode=0o700)
            canary = foreign / "hospital.db"
            canary.write_bytes(b"FOREIGN-CANARY-MUST-SURVIVE")
            before = canary.read_bytes()
            with DisposablePX(ROOT) as fixture:
                root = fixture.root
                detached = Path(outside) / "original-root"
                actual_prune = px_int1_fixture._remove_tree_fd
                substitutions = []
                def inject_after_verified_fd(directory_fd):
                    if substitutions:
                        return actual_prune(directory_fd)
                    target = Path(os.readlink("/proc/self/fd/" + str(directory_fd)))
                    # The verified root FD was opened from this target.
                    # A concurrent same-UID process now replaces its name.
                    os.rename(target, detached)
                    os.rename(foreign, target)
                    substitutions.append(target)
                    return actual_prune(directory_fd)
                with patch("px_int1_fixture._remove_tree_fd", side_effect=inject_after_verified_fd):
                    with self.assertRaisesRegex(
                            FixtureRefusal, "cleanup root replaced during deletion"):
                        fixture.close()
                self.assertEqual(len(substitutions), 1)
                self.assertEqual((substitutions[0] / "hospital.db").read_bytes(), before)
                self.assertTrue((detached / "hospital/data").is_dir(),
                                "C2 deliberately retains original empty directory")
                self.assertFalse((detached / "hospital/data/hospital.db").exists(),
                                 "pinned pruning still removes files from original inode")
            self.assertEqual((substitutions[0] / "hospital.db").read_bytes(), before)
            substitutions[0].rename(foreign)
            substitutions[0].parent.rmdir()
            self.assertEqual(canary.read_bytes(), before)

    def test_c2_descendant_empty_foreign_replaced_after_identity_check_survives(self):
        """Inject exactly AFTER the second descendant stat, where rmdir used to run."""
        with tempfile.TemporaryDirectory(prefix="int1-c2-descendant-") as outside:
            foreign = Path(outside) / "foreign-empty"
            foreign.mkdir(mode=0o700)
            foreign_id = (foreign.stat().st_dev, foreign.stat().st_ino)
            with DisposablePX(ROOT) as fixture:
                original_stat = os.stat
                observed = []
                counts = []
                detached = Path(outside) / "original-data"
                def substitute_after_verified_stat(path, *args, **kwargs):
                    value = original_stat(path, *args, **kwargs)
                    if path == "data" and "dir_fd" in kwargs:
                        counts.append(1)
                        if len(counts) == 2:
                            parent_fd = kwargs["dir_fd"]
                            os.rename("data", detached, src_dir_fd=parent_fd)
                            os.rename(foreign, "data", dst_dir_fd=parent_fd)
                            parent_path = Path(os.readlink(
                                "/proc/self/fd/" + str(parent_fd)))
                            observed.append(parent_path / "data")
                    return value
                with patch("px_int1_fixture.os.stat",
                           side_effect=substitute_after_verified_stat):
                    with patch("px_int1_fixture.os.rmdir",
                               side_effect=AssertionError("unsafe descendant rmdir attempted")):
                        fixture.close()
                self.assertEqual(len(observed), 1)
                # This replacement is EMPTY: the legacy rmdir would have
                # deleted it without errors. Verify the very SAME foreign
                # inode is still present at the substituted target.
                self.assertTrue(observed[0].is_dir())
                survivor = observed[0].stat()
                self.assertEqual((survivor.st_dev, survivor.st_ino), foreign_id)
                self.assertEqual(list(observed[0].iterdir()), [])
                self.assertEqual(list(detached.iterdir()), [])
                self.assertFalse(foreign.exists(), "foreign was moved into quarantine")
                self.assertTrue(detached.is_dir())
                self.assertFalse(fixture.root.exists())

    def test_c2_empty_foreign_root_substituted_after_identity_check_survives(self):
        """An empty substitute is not protected by 'rmdir only when empty'."""
        with tempfile.TemporaryDirectory(prefix="int1-c2-root-") as outside:
            foreign = Path(outside) / "foreign-empty"
            foreign.mkdir(mode=0o700)
            foreign_id = (foreign.stat().st_dev, foreign.stat().st_ino)
            old = Path(outside) / "original-root"
            with DisposablePX(ROOT) as fixture:
                actual_stat = os.stat
                location = []
                def substitute_after_root_stat(name, *args, **kwargs):
                    value = actual_stat(name, *args, **kwargs)
                    if name == "fixture" and "dir_fd" in kwargs and not location:
                        qfd = kwargs["dir_fd"]
                        qpath = Path(os.readlink("/proc/self/fd/" + str(qfd)))
                        os.rename("fixture", old, src_dir_fd=qfd)
                        os.rename(foreign, "fixture", dst_dir_fd=qfd)
                        location.append(qpath / "fixture")
                    return value
                with patch("px_int1_fixture.os.stat",
                           side_effect=substitute_after_root_stat):
                    with patch("px_int1_fixture.os.rmdir",
                               side_effect=AssertionError("unsafe final rmdir attempted")):
                        fixture.close()
                self.assertEqual(len(location), 1)
                self.assertTrue(location[0].is_dir(),
                                "empty foreign root must survive after check")
                survivor = location[0].stat()
                self.assertEqual((survivor.st_dev, survivor.st_ino), foreign_id)
                self.assertEqual(list(location[0].iterdir()), [])
                self.assertTrue(old.is_dir(), "original pinned root remains")
                location[0].rename(foreign)
                self.assertTrue(foreign.is_dir())
                # Quarantine parent is also deliberately retained, not rmdir'ed.

    def test_c2_normal_cleanup_never_removes_unverified_directory_names(self):
        """Destructive directory-name operations are absent, not just prechecked."""
        with DisposablePX(ROOT) as fixture:
            test_root = fixture.root
            with patch("px_int1_fixture.os.rmdir",
                       side_effect=AssertionError("unsafe directory rmdir")):
                fixture.close()
            self.assertFalse(test_root.exists())
            # This is a documented fail-closed tradeoff: the empty
            # quarantine tree remains for disposal with the CI runner.

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
