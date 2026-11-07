#!/usr/bin/env python3
"""Disposable PX Session attachment integration, including concurrent claims."""
import concurrent.futures
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PX = ROOT / "bin" / "px"


def command(env, *args, ok=True):
    proc = subprocess.run([str(PX), *map(str, args)], env=env,
                          text=True, capture_output=True)
    if ok and proc.returncode:
        raise AssertionError(f"FAILED {args}: {proc.stderr}\n{proc.stdout}")
    if not ok:
        assert proc.returncode != 0, args
        return (proc.stderr + proc.stdout).strip()
    return json.loads(proc.stdout)


def setup_room(env, room, bed, branch="feature/map", doctor="doc-1"):
    command(env, "hospital", "room-bind", room,
            "--repository", "org/project", "--patient-id", "patient-1",
            "--team", "map", "--branch", branch,
            "--bed-path", str(bed), "--doctor-id", doctor, "--json")
    a = command(env, "hospital", "assignment-create", "--room-id", room,
                "--title", "Map implementation", "--goal", "Bounded map work",
                "--permissions-json", '["READ","EDIT"]', "--json")
    command(env, "hospital", "assignment-activate", a["id"], "--json")
    return str(a["id"])


def make_bed(path):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "checkout", "-qb", "feature/map"],
                   check=True)


def args(room, assignment, bed, session, doctor="doc-1", provider="mock", mode="create"):
    return ("agent", "session-attach",
            "--room-id", room, "--session-id", session,
            "--assignment-id", assignment, "--doctor-id", doctor,
            "--provider-id", provider, "--repository", "org/project",
            "--branch", "feature/map", "--working-directory", str(bed),
            "--mode", mode, "--confirm", "--json")


with tempfile.TemporaryDirectory(prefix="px-hospital-atomic-") as tmp:
    base = Path(tmp)
    env = dict(os.environ, PX_HOSPITAL_DATA_DIR=str(base / "db"),
               PX_AGENT_PROVIDER_CONFIG=str(base / "providers.json"))
    (base / "providers.json").write_text(json.dumps({
        "version": 1,
        "providers": {
            "mock": {"name": "MOCK", "command": sys.executable,
                     "dialect": "hermes-stream-json", "startArgs": []},
        }
    }), encoding="utf-8")
    bed = base / "main-bed"
    make_bed(bed)
    command(env, "hospital", "init", "--json")
    aid = setup_room(env, "room-main", bed)
    command(env, "hospital", "doctor-put", "doc-2",
            "--name", "Second Doctor", "--status", "ACTIVE", "--json")
    before = command(env, "hospital", "sessions", "--json")
    assert not before
    missing_confirm = list(args("room-main", aid, bed, "session-one"))
    missing_confirm.remove("--confirm")
    assert "confirmation" in command(env, *missing_confirm, ok=False)
    assert not command(env, "hospital", "sessions", "--json")

    result = command(env, *args("room-main", aid, bed, "session-one"))
    assert result["mode"] == "CREATED" and result["created"]
    assert not result["providerLaunched"] and not result["authorityVerified"]
    assert not result["browserChatConnected"]
    assert result["session"]["workingDirectory"] == str(bed)
    assert result["session"]["status"] == "IDLE"
    room = command(env, "hospital", "room", "room-main", "--json")
    assert room["doctorId"] == "doc-1" and room["providerId"] == "mock"

    # Repeated operator click/retry does not reset timestamps or overwrite.
    again = command(env, *args("room-main", aid, bed, "session-one"))
    assert again["mode"] == "REUSED" and not again["created"]
    reuse = command(env, *args("room-main", aid, bed, "session-one",
                               mode="reuse"))
    assert not reuse["created"]
    assert "already has open Session" in command(
        env, *args("room-main", aid, bed, "different-id"), ok=False)
    assert "open Session" in command(
        env, *args("room-main", aid, bed, "nonexistent",
                   mode="reuse"), ok=False)
    assert "mismatch" in command(
        env, *args("room-main", aid, bed, "session-one", doctor="doc-2"),
        ok=False).lower()
    assert "unknown agent provider" in command(
        env, *args("room-main", aid, bed, "session-one",
                   provider="unregistered"), ok=False)
    wrong_branch = list(args("room-main", aid, bed, "session-one"))
    wrong_branch[wrong_branch.index("--branch") + 1] = "wrong-branch"
    assert "branch" in command(env, *wrong_branch, ok=False).lower()
    bad_session_id = list(args("room-main", aid, bed, "bad\nid"))
    bad_id_error = command(env, *bad_session_id, ok=False)
    assert "invalid Session ID" in bad_id_error, bad_id_error

    # Same physical Bed via symlink cannot be claimed by a second Room.
    alias = base / "bed-alias"
    alias.symlink_to(bed, target_is_directory=True)
    other_aid = setup_room(env, "room-other", alias)
    assert "Bed owned" in command(
        env, *args("room-other", other_aid, alias, "session-other"),
        ok=False)
    assert len(command(env, "hospital", "sessions", "--json")) == 1

    race_bed = base / "race-bed"
    make_bed(race_bed)
    race_aid = setup_room(env, "room-race", race_bed)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        # Submit raw subprocesses since one of two must succeed.
        futures = [
            pool.submit(subprocess.run,
                        [str(PX), *args("room-race", race_aid, race_bed,
                                       f"race-{n}")],
                        env=env, capture_output=True, text=True)
            for n in (1, 2)
        ]
        contenders = [x.result() for x in futures]
    success = [x for x in contenders if x.returncode == 0]
    rejected = [x for x in contenders if x.returncode != 0]
    assert len(success) == 1 and len(rejected) == 1, contenders
    assert "already has open Session" in rejected[0].stderr
    race_rows = command(env, "hospital", "sessions",
                        "--room-id", "room-race", "--json")
    assert len(race_rows) == 1
    assert race_rows[0]["id"] in ("race-1", "race-2")
    assert len(command(env, "hospital", "sessions", "--json")) == 2

    # Failed requests did not create duplicate Sessions or change ownership.
    with sqlite3.connect(base / "db" / "hospital.db") as conn:
        ids = conn.execute("SELECT session_id FROM sessions").fetchall()
        assert len(ids) == 2 and len(set(ids)) == 2

print("HOSPITAL ATOMIC ATTACH // PASS // intent, exact identity, idempotence, Bed alias, concurrent CLI admission, no launch")
