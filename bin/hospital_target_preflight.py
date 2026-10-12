"""Conservative Room/Bed Git target verifier.

This module is deliberately read-only. The PX provider-launch boundary must
call it using trusted persisted Room/Patient identity, and must independently
enforce Assignment authority and process restrictions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse


@dataclass(frozen=True)
class TargetPreflight:
    ok: bool
    code: str
    evidence: dict[str, str | bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
        check=False,
    )
    if completed.returncode:
        raise ValueError(f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def _github_slug(remote: str) -> str:
    remote = remote.strip()
    if remote.startswith("git@github.com:"):
        path = remote.split(":", 1)[1]
    else:
        url = urlparse(remote)
        if url.scheme not in ("ssh", "http", "https") or url.hostname != "github.com":
            return ""
        path = url.path.lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        return ""
    return path.lower()


def preflight_edit_target(
    *,
    bed_path: str,
    expected_branch: str,
    expected_repository: str = "",
    expected_git_common_dir: str = "",
    expected_head: str = "",
    allow_dirty: bool = False,
) -> TargetPreflight:
    """Fail closed when the persisted Room and actual checkout do not agree.

    A trusted repository anchor is mandatory. This is not an OS sandbox and
    does not prevent changes between the check and provider process creation.
    """
    def reject(code: str, facts=None) -> TargetPreflight:
        return TargetPreflight(False, code, facts or {})

    if not bed_path or not expected_branch:
        return reject("TARGET_UNRESOLVED")
    if not expected_repository and not expected_git_common_dir:
        return reject("TARGET_IDENTITY_UNANCHORED")

    bed = Path(bed_path).expanduser().resolve()
    if not bed.is_dir():
        return reject("BED_MISSING", {"bed": str(bed)})

    try:
        root = Path(_git(bed, "rev-parse", "--show-toplevel")).resolve()
        common = (bed / _git(bed, "rev-parse", "--git-common-dir")).resolve()
        branch = _git(bed, "symbolic-ref", "--quiet", "--short", "HEAD")
        head = _git(bed, "rev-parse", "HEAD")
        dirty = bool(_git(bed, "status", "--porcelain"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return reject("TARGET_GIT_UNRESOLVED", {"bed": str(bed)})

    facts = {
        "bed": str(bed), "git_root": str(root),
        "git_common_dir": str(common), "actual_branch": branch,
        "actual_head": head, "dirty": dirty,
    }
    if root != bed:
        return reject("TARGET_BED_NOT_REPOSITORY_ROOT", facts)

    if expected_git_common_dir:
        expected = Path(expected_git_common_dir).expanduser().resolve()
        if common != expected:
            return reject("PATIENT_WORKTREE_MISMATCH", facts)

    if expected_repository:
        try:
            remote = _git(bed, "remote", "get-url", "origin")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return reject("PATIENT_REPOSITORY_UNVERIFIED", facts)
        actual = _github_slug(remote)
        facts["origin_repository"] = actual
        if not actual:
            return reject("PATIENT_REPOSITORY_UNVERIFIED", facts)
        if actual != expected_repository.strip().lower().removesuffix(".git"):
            return reject("PATIENT_REPOSITORY_MISMATCH", facts)

    if branch != expected_branch.removeprefix("refs/heads/"):
        return reject("TARGET_BRANCH_MISMATCH", facts)
    if expected_head and head != expected_head:
        return reject("TARGET_HEAD_MISMATCH", facts)
    if dirty and not allow_dirty:
        return reject("DIRTY_BED_NEEDS_POLICY", facts)
    return TargetPreflight(True, "TARGET_VERIFIED", facts)
