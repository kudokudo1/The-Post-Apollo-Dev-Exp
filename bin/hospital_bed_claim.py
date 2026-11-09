"""PX Hospital // first Git Bed claim: synthetic-only atomic DB transaction.

Never creates a worktree, changes a branch, starts a provider, or modifies
an existing Room owner. Git evidence is verified twice; filesystem/SQLite
transactions cannot be made jointly atomic. Caller authentication is NOT
implemented; the writer is restricted to disposable DB fixtures.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_HTTPS = re.compile(
    r"^https://github[.]com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:[.]git)?/?$", re.I
)
_SSH = re.compile(
    r"^(?:git@github[.]com:|ssh://git@github[.]com/)"
    r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:[.]git)?/?$", re.I
)


def _repository(text):
    source = str(text or "").strip()
    match = _HTTPS.fullmatch(source) or _SSH.fullmatch(source)
    if match:
        return match.group(1).lower()
    if _REPO.fullmatch(source):
        return source.lower()
    return ""


def _run_git(bed: Path, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(bed), *args],
            capture_output=True, text=True, timeout=8, check=False, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("HOSPITAL BED HOLD // Git evidence unavailable")
    if result.returncode != 0:
        raise RuntimeError("HOSPITAL BED HOLD // Git " + args[0] + " not verified")
    return result.stdout.strip()


def verify_bed(bed_text, repository, branch):
    """Read only: refuse aliases, live Quickshell, detached or dirty Beds."""
    path_text = str(bed_text or "").strip()
    expected_repo = _repository(repository)
    target_branch = str(branch or "").strip()
    if not expected_repo or not target_branch or target_branch == "DETACHED":
        raise RuntimeError("HOSPITAL BED HOLD // repository or branch invalid")
    if not path_text or not Path(path_text).is_absolute() or any(
        char in path_text for char in ("\x00", "\r", "\n")
    ):
        raise RuntimeError("HOSPITAL BED HOLD // Bed must be a literal absolute path")
    bed = Path(path_text)
    try:
        actual = bed.resolve(strict=True)
    except OSError:
        raise RuntimeError("HOSPITAL BED HOLD // Bed path missing")
    if not bed.is_dir() or str(actual) != path_text:
        raise RuntimeError("HOSPITAL BED HOLD // symbolic, relative or nested Bed path")
    live = (Path.home() / ".config" / "quickshell").resolve()
    if actual == live:
        raise RuntimeError("HOSPITAL BED HOLD // live Quickshell worktree refused")
    if _run_git(bed, "rev-parse", "--show-toplevel") != str(actual):
        raise RuntimeError("HOSPITAL BED HOLD // Bed is not the Git worktree root")
    if _run_git(bed, "rev-parse", "--is-inside-work-tree") != "true":
        raise RuntimeError("HOSPITAL BED HOLD // not a Git working tree")
    actual_branch = _run_git(bed, "symbolic-ref", "--quiet", "--short", "HEAD")
    if actual_branch != target_branch:
        raise RuntimeError("HOSPITAL BED HOLD // branch mismatch")
    origin = _run_git(bed, "remote", "get-url", "origin")
    if _repository(origin) != expected_repo:
        raise RuntimeError("HOSPITAL BED HOLD // GitHub origin mismatch")
    head = _run_git(bed, "rev-parse", "--verify", "HEAD")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", head):
        raise RuntimeError("HOSPITAL BED HOLD // HEAD not verified")
    if _run_git(bed, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("HOSPITAL BED HOLD // Bed has local changes")
    return {"path": str(actual), "repository": expected_repo,
            "branch": actual_branch, "head": head.lower(), "origin": origin,
            "worktreeClean": True}


def _fixture_gate():
    """No authenticated operator service yet. Refuse production databases."""
    db_text = os.environ.get("PX_HOSPITAL_DB", "").strip()
    if os.environ.get("PX_HOSPITAL_BED_CLAIM_TEST_ONLY") != "1" or not db_text:
        raise RuntimeError("HOSPITAL BED HOLD // synthetic DB only; authority not connected")
    db = Path(db_text).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not db.is_relative_to(temp_root) or db == temp_root:
        raise RuntimeError("HOSPITAL BED HOLD // disposable DB path required")


def claim_first_bed(conn, args, record_fn):
    if not args.confirm:
        raise RuntimeError("HOSPITAL BED HOLD // explicit confirmation missing")
    _fixture_gate()
    room_id = str(args.room_id or "").strip()
    repository = str(args.repository or "").strip()
    branch = str(args.branch or "").strip()
    bed_text = str(args.bed_path or "").strip()
    if not room_id or not _repository(repository):
        raise RuntimeError("HOSPITAL BED HOLD // Room or Patient missing")
    evidence = verify_bed(bed_text, repository, branch)

    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""
            SELECT r.*, p.repository AS patient_repository
            FROM rooms r
            JOIN patients p ON p.patient_id = r.patient_id
            WHERE r.room_id = ?
        """, (room_id,)).fetchone()
        if row is None:
            raise RuntimeError("HOSPITAL BED HOLD // unknown Room / Patient")
        if _repository(row["patient_repository"]) != _repository(repository):
            raise RuntimeError("HOSPITAL BED HOLD // Room Patient changed")
        if any(str(row[key] or "").strip()
               for key in ("branch", "bed_path", "doctor_id", "provider_id")):
            raise RuntimeError("HOSPITAL BED HOLD // Room already staffed or configured")
        if conn.execute("SELECT 1 FROM sessions WHERE room_id = ? LIMIT 1",
                        (room_id,)).fetchone():
            raise RuntimeError("HOSPITAL BED HOLD // Room already has Session history")
        for other in conn.execute(
                "SELECT room_id, bed_path FROM rooms WHERE room_id != ?"
                " AND bed_path != ''", (room_id,)).fetchall():
            previous = str(other["bed_path"] or "").strip()
            if previous and str(Path(previous).expanduser().resolve()) == evidence["path"]:
                raise RuntimeError("HOSPITAL BED HOLD // Bed claimed by another Room")
        assigned_id = str(row["current_assignment_id"] or "").strip()
        if assigned_id:
            assignment = conn.execute(
                "SELECT room_id, patient_id, status FROM assignments"
                " WHERE assignment_id = ?", (assigned_id,)
            ).fetchone()
            if (assignment is None or assignment["room_id"] != room_id
                    or assignment["patient_id"] != row["patient_id"]
                    or assignment["status"] != "ACTIVE"):
                raise RuntimeError("HOSPITAL BED HOLD // Room Assignment not ACTIVE")
        fresh = verify_bed(bed_text, repository, branch)
        if fresh != evidence:
            raise RuntimeError("HOSPITAL BED HOLD // Git evidence changed before commit")
        written = conn.execute("""
            UPDATE rooms
            SET branch = ?, bed_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE room_id = ? AND branch = '' AND bed_path = ''
              AND doctor_id = '' AND provider_id = ''
        """, (branch, evidence["path"], room_id))
        if written.rowcount != 1:
            raise RuntimeError("HOSPITAL BED HOLD // concurrent Room change")
        room = record_fn(conn, room_id)
        conn.commit()
        return {"room": room, "git": fresh, "recorded": True,
                "providerLaunched": False, "sessionCreated": False,
                "operatorAuthenticated": False, "testOnly": True}
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
