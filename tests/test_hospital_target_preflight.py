"""Isolated Git fixtures; no installed PX state or live worktree is touched.

python3 -m unittest discover -s tests -p test_hospital_target_preflight.py -v
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hospital_target_preflight", ROOT / "bin" / "hospital_target_preflight.py"
)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


class HospitalTargetPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name) / "bed"
        self.work.mkdir()
        git(self.work, "init", "-q")
        git(self.work, "config", "user.name", "Hospital fixture")
        git(self.work, "config", "user.email", "hospital@example.invalid")
        (self.work / "tracked.txt").write_text("baseline\n")
        git(self.work, "add", "tracked.txt")
        git(self.work, "commit", "-qm", "baseline")
        git(self.work, "checkout", "-qb", "feature/A")
        self.anchor = str(
            (self.work / git(self.work, "rev-parse", "--git-common-dir")).resolve()
        )

    def check(self, **overrides):
        kw = dict(
            bed_path=str(self.work), expected_branch="feature/A",
            expected_git_common_dir=self.anchor,
        )
        kw.update(overrides)
        return mod.preflight_edit_target(**kw)

    def test_matching_target_passes(self):
        result = self.check()
        self.assertTrue(result.ok, result)
        self.assertEqual(result.code, "TARGET_VERIFIED")
        self.assertTrue(result.evidence["actual_head"])

    def test_wrong_branch_fails(self):
        self.assertEqual(self.check(expected_branch="main").code, "TARGET_BRANCH_MISMATCH")

    def test_override_to_other_worktree_fails(self):
        other = Path(self.temp.name) / "other"
        git(self.work, "worktree", "add", "-qb", "feature/B", str(other))
        self.assertEqual(self.check(bed_path=str(other)).code, "TARGET_BRANCH_MISMATCH")

    def test_foreign_repository_fails(self):
        other = Path(self.temp.name) / "foreign"
        other.mkdir()
        git(other, "init", "-q")
        git(other, "config", "user.name", "Hospital fixture")
        git(other, "config", "user.email", "hospital@example.invalid")
        (other / "tracked.txt").write_text("different\n")
        git(other, "add", "tracked.txt")
        git(other, "commit", "-qm", "baseline")
        git(other, "checkout", "-qb", "feature/A")
        self.assertEqual(self.check(bed_path=str(other)).code, "PATIENT_WORKTREE_MISMATCH")

    def test_missing_anchor_fails(self):
        self.assertEqual(self.check(expected_git_common_dir="").code, "TARGET_IDENTITY_UNANCHORED")

    def test_missing_bed_fails(self):
        self.assertEqual(self.check(bed_path=str(self.work / "missing")).code, "BED_MISSING")

    def test_non_git_bed_fails(self):
        other = Path(self.temp.name) / "nongit"
        other.mkdir()
        self.assertEqual(self.check(bed_path=str(other)).code, "TARGET_GIT_UNRESOLVED")

    def test_stale_head_fails(self):
        self.assertEqual(self.check(expected_head="0" * 40).code, "TARGET_HEAD_MISMATCH")

    def test_dirty_requires_explicit_policy(self):
        (self.work / "tracked.txt").write_text("modified\n")
        self.assertEqual(self.check().code, "DIRTY_BED_NEEDS_POLICY")
        self.assertTrue(self.check(allow_dirty=True).ok)

    def test_github_origin_must_match_patient(self):
        git(self.work, "remote", "add", "origin", "git@github.com:kudokudo1/The-Post-Apollo-Dev-Exp.git")
        self.assertTrue(self.check(expected_repository="kudokudo1/The-Post-Apollo-Dev-Exp").ok)
        self.assertEqual(
            self.check(expected_repository="other-owner/other").code,
            "PATIENT_REPOSITORY_MISMATCH",
        )

    def test_no_origin_fails_if_repository_claimed(self):
        self.assertEqual(
            self.check(expected_repository="kudokudo1/The-Post-Apollo-Dev-Exp").code,
            "PATIENT_REPOSITORY_UNVERIFIED",
        )

    def test_nested_directory_not_a_registered_bed(self):
        child = self.work / "subdir"
        child.mkdir()
        self.assertEqual(
            self.check(bed_path=str(child)).code,
            "TARGET_BED_NOT_REPOSITORY_ROOT",
        )


if __name__ == "__main__":
    unittest.main()
