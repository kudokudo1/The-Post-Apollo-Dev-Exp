#!/usr/bin/env python3
"""Disposable Hospital attach -> explicit Quick -> Provider -> report continuity.

The only provider is repository-owned mock-hermes-agent.py. All records,
worktrees, provider identity, runtime locks and authority files live in a
TemporaryDirectory. This does not use browser ChatGPT or external models.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PX = ROOT / "bin" / "px"
MOCK = ROOT / "tests" / "fixtures" / "mock-hermes-agent.py"


def invoke(env, *args, ok=True):
    proc = subprocess.run([str(PX), *map(str, args)], env=env, text=True,
                          capture_output=True, timeout=50, check=False)
    if ok:
        assert proc.returncode == 0, (args, proc.stderr, proc.stdout)
        return json.loads(proc.stdout)
    assert proc.returncode != 0, (args, proc.stderr, proc.stdout)
    return (proc.stderr + proc.stdout).strip()


def prepare_git_bed(bed):
    bed.mkdir()
    commands = [
        ("init", "-q"),
        ("config", "user.email", "hospital-fixture@example.invalid"),
        ("config", "user.name", "Hospital Fixture"),
        ("add", "tracked.txt"),
        ("commit", "-qm", "disposable baseline"),
        ("checkout", "-qb", "feature/attachment-e2e"),
        ("remote", "add", "origin", "https://github.com/org/project.git"),
    ]
    (bed / "tracked.txt").write_text("disposable test file\n", encoding="utf-8")
    for command in commands:
        proc = subprocess.run(["git", "-C", str(bed), *command],
                              capture_output=True, text=True, check=False)
        assert proc.returncode == 0, (command, proc.stderr)


with tempfile.TemporaryDirectory(prefix="hospital-attach-e2e-") as name:
    root = Path(name)
    bed = root / "worktree"
    prepare_git_bed(bed)
    provider_file = root / "providers.json"
    provider_file.write_text(json.dumps({
        "version": 1,
        "providers": {
            "mock": {
                "name": "DISPOSABLE MOCK",
                "command": sys.executable,
                "dialect": "hermes-stream-json",
                "startArgs": [str(MOCK), "chat", "--format",
                              "stream-json", "--query-file", "-"],
                "resumeArgs": [str(MOCK), "chat", "--resume",
                               "{provider_session_id}", "--format",
                               "stream-json", "--query-file", "-"],
            }
        }
    }), encoding="utf-8")
    env = dict(os.environ,
               PX_HOSPITAL_DATA_DIR=str(root / "hospital"),
               PX_AGENT_PROVIDER_CONFIG=str(provider_file),
               PX_AGENT_LOCK_DIR=str(root / "locks"),
               PX_AGENT_AUTHORITY_DIR=str(root / "authority"))
    invoke(env, "hospital", "init", "--json")
    room = invoke(env, "hospital", "room-bind", "room-e2e",
                  "--repository", "org/project",
                  "--patient-id", "patient-fixture",
                  "--team", "hospital", "--branch", "feature/attachment-e2e",
                  "--bed-path", bed, "--doctor-id", "doctor-fixture", "--json")
    assert room["id"] == "room-e2e"
    assignment = invoke(
        env, "hospital", "assignment-create", "--room-id", "room-e2e",
        "--title", "Exercise worker dispatch",
        "--goal", "Produce mock-only status and reports",
        "--permissions-json", '["READ"]', "--json")
    invoke(env, "hospital", "assignment-activate", assignment["id"], "--json")

    attached = invoke(
        env, "agent", "session-attach", "--room-id", "room-e2e",
        "--session-id", "session-fixture", "--assignment-id", assignment["id"],
        "--doctor-id", "doctor-fixture", "--provider-id", "mock",
        "--repository", "org/project", "--branch", "feature/attachment-e2e",
        "--working-directory", bed, "--mode", "create",
        "--confirm", "--json")
    assert attached["mode"] == "CREATED"
    assert attached["session"]["status"] == "IDLE"
    assert attached["providerLaunched"] is False
    assert attached["authorityVerified"] is False

    status = invoke(env, "agent", "status", "session-fixture", "--json")
    assert status["status"] == "IDLE" and status["activePid"] == 0
    assert invoke(env, "hospital", "messages", "room-e2e", "--json") == []

    # No implicit model start: only this explicit Quick dispatch runs mock.
    first = invoke(env, "agent", "quick", "session-fixture", "GO",
                   "--timeout", "20", "--json")
    assert first["command"] == "CONTINUE"  # PX normalization
    assert first["result"]["assistant"].startswith("MOCK: QUICK // CONTINUE")
    assert first["result"]["providerSessionId"] == "mock-provider-session"
    assert first["result"]["session"]["roomId"] == "room-e2e"
    after_go = invoke(env, "agent", "status", "session-fixture", "--json")
    assert after_go["status"] == "WAITING"
    assert after_go["activePid"] == 0 and not after_go["operating"]
    assert after_go["session"]["lastExitCode"] == 0
    assert after_go["session"]["lastError"] == ""

    # WAITING is normal after success, and a second explicit Quick command
    # must be allowed; a UI that treats all WAITING as blocked is incorrect.
    second = invoke(env, "agent", "quick", "session-fixture", "CONTINUE",
                    "--timeout", "20", "--json")
    assert second["result"]["assistant"].startswith("MOCK: QUICK // CONTINUE")
    assert second["result"]["providerSessionId"] == "mock-provider-session"

    report = invoke(env, "agent", "quick", "session-fixture", "REPORT",
                    "--timeout", "20", "--json")
    assert report["command"] == "REPORT"
    assert report["result"]["assistant"].startswith("MOCK: QUICK // REPORT")
    assert report["checkpoint"]["id"]
    assert report["roomReport"]["id"]
    assert report["roomReport"]["roomId"] == "room-e2e"

    messages = invoke(env, "hospital", "messages", "room-e2e",
                      "--limit", "100", "--json")
    assert len(messages) == 6, messages
    assert len([m for m in messages if m["direction"] == "incoming"]) == 3
    assert len([m for m in messages if m["direction"] == "outgoing"]) == 3
    assert any("QUICK // REPORT" in m["body"] for m in messages)
    events = invoke(env, "hospital", "events", "session-fixture",
                    "--limit", "200", "--json")
    types = [e["type"] for e in events]
    assert types.count("turn.started") == 3, types
    assert types.count("turn.completed") == 3, types
    assert "checkpoint.created" in types, types
    assert "room_report.created" in types, types
    final = invoke(env, "agent", "status", "session-fixture", "--json")
    assert final["status"] == "WAITING"
    assert final["activePid"] == 0 and not final["operating"]
    assert final["session"]["providerSessionId"] == "mock-provider-session"

    # Inject a local mock Provider resume-ID mismatch. PX must report FAILED,
    # retain the original Provider Session identity and publish a failure
    # event without claiming a successful assistant response.
    refused = invoke(
        env, "agent", "turn", "session-fixture",
        "--prompt", "FORCE_SESSION_MISMATCH", "--timeout", "20",
        "--json", ok=False)
    assert "provider resumed with a different session id" in refused, refused
    failed = invoke(env, "agent", "status", "session-fixture", "--json")
    assert failed["status"] == "FAILED", failed
    assert failed["activePid"] == 0 and not failed["operating"]
    assert "different session id" in failed["session"]["lastError"]
    assert failed["session"]["providerSessionId"] == "mock-provider-session"
    failure_events = invoke(env, "hospital", "events", "session-fixture",
                            "--limit", "200", "--json")
    assert any(e["type"] == "turn.failed" for e in failure_events)
    assert not any(m["body"].startswith("MOCK: FORCE_SESSION_MISMATCH")
                   for m in invoke(env, "hospital", "messages", "room-e2e",
                                   "--json"))

    # Paused, review-held, failed or otherwise unknown Sessions must refuse
    # a new provider turn even if there is no recorded PID.
    before = len(invoke(env, "hospital", "messages", "room-e2e", "--json"))
    for state in ("PAUSED", "REVIEW", "FAILED", "THINKING"):
        invoke(env, "hospital", "session-runtime", "session-fixture",
               "--status", state, "--clear-active-pid", "--json")
        error = invoke(env, "agent", "quick", "session-fixture", "CONTINUE",
                       "--timeout", "20", "--json", ok=False)
        assert "SESSION NOT DISPATCHABLE" in error, (state, error)
        current = invoke(env, "hospital", "messages", "room-e2e", "--json")
        assert len(current) == before, state
    assert not (root / "worktree" / "new-provider-output").exists()

print("HOSPITAL ATTACH -> MOCK QUICK -> REPORT // PASS // bounded repeated turns, held states, Room records and no live Provider")
