#!/usr/bin/env python3
"""Isolated Git/PX fixtures for the first-Bed atomic claim; no live PX database."""
import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PX = ROOT / "bin" / "px-hospital-store"
REPOSITORY = "kudokudo1/px-bed-fixture"
BRANCH = "fixture/safe"


def command(argv, env=None, good=True):
    result = subprocess.run(
        [str(v) for v in argv], env=env, capture_output=True, text=True,
        timeout=20,
    )
    if good and result.returncode:
        raise AssertionError(f"Command failed: {argv}\n{result.stderr}\n{result.stdout}")
    if not good and result.returncode == 0:
        raise AssertionError(f"Unexpected acceptance: {argv}\n{result.stdout}")
    return result


def git(*argv, cwd=None):
    return command(["git", *argv], good=True).stdout.strip()


def seed(root, name="bed with spaces", origin="git@github.com:kudokudo1/px-bed-fixture.git"):
    bed = root / name
    bed.mkdir(parents=True)
    git("init", "-q", "-b", BRANCH, str(bed))
    git("-C", str(bed), "config", "user.name", "Hospital Fixture")
    git("-C", str(bed), "config", "user.email", "hospital-fixture@example.invalid")
    (bed / "fixture.txt").write_text("synthetic source\n")
    git("-C", str(bed), "add", "fixture.txt")
    git("-C", str(bed), "commit", "-qm", "fixture")
    git("-C", str(bed), "remote", "add", "origin", origin)
    return bed


def px(env, *args, good=True, error=None):
    result = command([sys.executable, PX, *args, "--json"], env=env, good=good)
    if error is not None and error not in (result.stderr + result.stdout):
        raise AssertionError(f"Expected refusal {error!r}, got {result.stderr!r}")
    return json.loads(result.stdout) if good else result


def room(env, room_id):
    return px(env, "room", room_id)


def make_room(env, room_id):
    return px(env, "room-bind", room_id,
              "--repository", REPOSITORY,
              "--patient-id", "fixture-patient")


def claim(env, room_id, bed, *, repository=REPOSITORY, branch=BRANCH,
          confirm=True, good=True, error=None):
    args = ["room-bed-claim-atomic", "--room-id", room_id,
            "--repository", repository, "--branch", branch,
            "--bed-path", str(bed)]
    if confirm:
        args.append("--confirm")
    return px(env, *args, good=good, error=error)


def check_empty(env, room_id):
    value = room(env, room_id)
    assert value["branch"] == ""
    assert value["bedPath"] == ""
    assert value["doctorId"] == ""
    assert value["providerId"] == ""


def main():
    with tempfile.TemporaryDirectory(prefix="px-hospital-bed-fixture-") as temp:
        t = Path(temp)
        env = dict(os.environ, PX_HOSPITAL_DB=str(t / "db" / "hospital.sqlite"),
                   PX_HOSPITAL_DATA_DIR=str(t / "data"),
                   PX_HOSPITAL_BED_CLAIM_TEST_ONLY="1")
        bed = seed(t)
        make_room(env, "fixture-room-a")
        before = room(env, "fixture-room-a")
        check_empty(env, "fixture-room-a")

        claim(env, "fixture-room-a", bed, confirm=False, good=False,
              error="explicit confirmation missing")
        check_empty(env, "fixture-room-a")
        no_fixture_gate = dict(env)
        del no_fixture_gate["PX_HOSPITAL_BED_CLAIM_TEST_ONLY"]
        claim(no_fixture_gate, "fixture-room-a", bed, good=False,
              error="synthetic DB only")
        check_empty(env, "fixture-room-a")

        claim(env, "fixture-room-a", bed,
              repository="different/other", good=False,
              error="GitHub origin mismatch")
        claim(env, "fixture-room-a", bed,
              branch="other/branch", good=False,
              error="branch mismatch")
        claim(env, "fixture-room-a", bed / "subdirectory", good=False,
              error="Bed path missing")
        symlink = t / "alias"
        symlink.symlink_to(bed, target_is_directory=True)
        claim(env, "fixture-room-a", symlink, good=False,
              error="symbolic, relative or nested Bed path")
        (bed / "untracked.txt").write_text("do not disturb\n")
        claim(env, "fixture-room-a", bed, good=False,
              error="Bed has local changes")
        check_empty(env, "fixture-room-a")
        (bed / "untracked.txt").unlink()

        accepted = claim(env, "fixture-room-a", bed)
        assert accepted["recorded"] is True
        assert accepted["operatorAuthenticated"] is False
        assert accepted["testOnly"] is True
        assert accepted["providerLaunched"] is False
        assert accepted["sessionCreated"] is False
        assert accepted["room"]["id"] == "fixture-room-a"
        assert accepted["room"]["branch"] == BRANCH
        assert accepted["room"]["bedPath"] == str(bed)
        assert accepted["git"]["repository"] == REPOSITORY
        assert accepted["git"]["worktreeClean"] is True
        assert len(accepted["git"]["head"]) in (40, 64)
        assert room(env, "fixture-room-a")["assignmentId"] == before["assignmentId"]
        assert px(env, "sessions", "--room-id", "fixture-room-a") == []
        claim(env, "fixture-room-a", bed, good=False,
              error="Room already staffed or configured")

        make_room(env, "fixture-room-b")
        claim(env, "fixture-room-b", bed, good=False,
              error="Bed claimed by another Room")
        check_empty(env, "fixture-room-b")

        # Concurrent first-claim races serialize at BEGIN IMMEDIATE.
        second_bed = seed(t, "second clean bed")
        make_room(env, "fixture-room-c")
        make_room(env, "fixture-room-d")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(claim, env, room_id, second_bed, good=False)
                for room_id in ("fixture-room-c", "fixture-room-d")
            ]
            accepted = []
            rejected = []
            for fut in futures:
                # Both calls are wrapped to permit failure; a successful call
                # triggers AssertionError inside command(..., good=False).
                try:
                    result = fut.result()
                    rejected.append(result)
                except AssertionError as error:
                    if "Unexpected acceptance" not in str(error):
                        raise
                    accepted.append(error)
        assert len(accepted) == 1 and len(rejected) == 1
        assert "Bed claimed by another Room" in rejected[0].stderr
        claims = [room(env, x)["bedPath"] == str(second_bed)
                  for x in ("fixture-room-c", "fixture-room-d")]
        assert claims.count(True) == 1
        assert px(env, "sessions", "--room-id", "fixture-room-c") == []
        assert px(env, "sessions", "--room-id", "fixture-room-d") == []

        # No test flags must ever work against an unstaged / default store.
        no_db_override = dict(env)
        no_db_override.pop("PX_HOSPITAL_DB")
        claim(no_db_override, "fixture-room-b", bed, good=False,
              error="synthetic DB only")
        check_empty(env, "fixture-room-b")

    print("HOSPITAL FIRST GIT BED // PASS // disposable git evidence, atomic conflict and zero provider launch")


if __name__ == "__main__":
    main()
