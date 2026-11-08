#!/usr/bin/env python3
"""Hospital Doctor A -> B succession with one disposable PX database and Git Bed.

No real Provider process is launched. Explicit --confirm is a CLI intent
signal, not remote operator authentication or production authorization.
"""
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

def raw(env, *args):
    return subprocess.run([str(PX), *map(str, args)], env=env,
                          capture_output=True, text=True, timeout=30)

def call(env, *args, accept=True):
    result = raw(env, *args)
    if accept:
        assert result.returncode == 0, (args, result.stderr, result.stdout)
        return json.loads(result.stdout)
    assert result.returncode != 0, (args, result.stdout)
    return (result.stderr + result.stdout).strip()

def args(room, previous, new, assignment, bed, doctor="doc-new",
         provider="mock-next"):
    return ("agent", "session-succeed",
            "--room-id", room, "--previous-session-id", previous,
            "--new-session-id", new, "--previous-doctor-id", "doc-old",
            "--previous-provider-id", "mock-old",
            "--successor-doctor-id", doctor,
            "--successor-provider-id", provider,
            "--assignment-id", assignment,
            "--repository", "org/project",
            "--branch", "feature/succession",
            "--working-directory", str(bed),
            "--confirm", "--json")

def setup(env, base, room, with_handoff=True):
    bed = base / ("bed-" + room)
    bed.mkdir()
    subprocess.run(["git", "init", "-q", str(bed)], check=True)
    subprocess.run(["git", "-C", str(bed), "checkout", "-qb", "feature/succession"], check=True)
    subprocess.run(["git", "-C", str(bed), "remote", "add", "origin",
                    "https://github.com/org/project.git"], check=True)
    call(env, "hospital", "room-bind", room, "--repository", "org/project",
         "--patient-id", "patient-fixture", "--doctor-id", "doc-old",
         "--provider-id", "mock-old", "--team", "backend",
         "--branch", "feature/succession", "--bed-path", bed, "--json")
    assignment = call(env, "hospital", "assignment-create",
        "--room-id", room, "--title", "Persistent work",
        "--goal", "Continue without copying the old chat",
        "--checklist", "- [x] First milestone\n- [ ] Successor verification",
        "--permissions-json", '["READ"]', "--json")
    call(env, "hospital", "assignment-activate", assignment["id"], "--json")
    old = room + "-old"
    call(env, "agent", "session-attach", "--room-id", room,
         "--session-id", old, "--assignment-id", assignment["id"],
         "--doctor-id", "doc-old", "--provider-id", "mock-old",
         "--repository", "org/project", "--branch", "feature/succession",
         "--working-directory", bed, "--mode", "create",
         "--confirm", "--json")
    call(env, "hospital", "message-append", "--room-id", room,
         "--session-id", old, "--author-role", "doctor",
         "--direction", "outgoing", "--body", "Prior work remains saved", "--json")
    if with_handoff:
        call(env, "hospital", "room-report-append",
             "--room-id", room, "--session-id", old,
             "--report-kind", "HANDOFF", "--title", "Doctor A to B",
             "--body", "Preserve the verified work and pending checklist",
             "--json")
    call(env, "hospital", "checkpoint-append", "--room-id", room,
         "--session-id", old, "--checkpoint-kind", "HANDOFF",
         "--body", "Last safe commit recorded; Bed unchanged", "--json")
    return bed, str(assignment["id"]), old

with tempfile.TemporaryDirectory(prefix="px-succession-atomic-") as temp:
    base = Path(temp)
    provider_config = base / "providers.json"
    provider_config.write_text(json.dumps({"version": 1, "providers": {
        "mock-old": {"name": "OLD", "command": sys.executable,
                     "dialect": "hermes-stream-json", "startArgs": []},
        "mock-next": {"name": "NEXT", "command": sys.executable,
                      "dialect": "hermes-stream-json", "startArgs": []}
    }}))
    env = dict(os.environ, PX_HOSPITAL_DATA_DIR=str(base / "db"),
               PX_AGENT_PROVIDER_CONFIG=str(provider_config))
    call(env, "hospital", "init", "--json")
    call(env, "hospital", "doctor-put", "doc-new", "--name", "Successor",
         "--status", "ACTIVE", "--json")
    bed, aid, old = setup(env, base, "room-main")
    success_args = args("room-main", old, "session-new", aid, bed)

    without_confirmation = list(success_args)
    without_confirmation.remove("--confirm")
    assert "confirmation" in call(env, *without_confirmation, accept=False)
    assert call(env, "hospital", "room", "room-main", "--json")["doctorId"] == "doc-old"
    assert "not explicitly released" in call(
        env, *success_args, accept=False)

    call(env, "hospital", "session-runtime", old, "--status", "FAILED",
         "--active-pid", "31415", "--ended", "--json")
    assert "not explicitly released" in call(env, *success_args, accept=False)
    call(env, "hospital", "session-runtime", old, "--clear-active-pid", "--json")

    wrong_branch = list(success_args)
    wrong_branch[wrong_branch.index("--branch")+1] = "wrong"
    assert "branch mismatch" in call(env, *wrong_branch, accept=False)
    subprocess.run(["git", "-C", str(bed), "remote", "set-url", "origin",
                    "https://github.com/elsewhere/repository.git"], check=True)
    assert "Patient origin mismatch" in call(env, *success_args, accept=False)
    subprocess.run(["git", "-C", str(bed), "remote", "set-url", "origin",
                    "git@github.com:org/project.git"], check=True)

    # Inject a failure after Room UPDATE but before Session insertion:
    # rollback must preserve Room staffing and every prior record.
    database = base / "db" / "hospital.db"
    with sqlite3.connect(database) as conn:
        conn.executescript("""
        CREATE TRIGGER fail_successor_insert
        BEFORE INSERT ON sessions WHEN NEW.session_id = 'session-new'
        BEGIN SELECT RAISE(ABORT, 'synthetic INSERT interruption'); END;
        """)
    error = call(env, *success_args, accept=False)
    assert "synthetic INSERT interruption" in error, error
    state = call(env, "hospital", "room", "room-main", "--json")
    assert state["doctorId"] == "doc-old" and state["providerId"] == "mock-old"
    assert len(call(env, "hospital", "sessions", "--room-id", "room-main",
                    "--json")) == 1
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TRIGGER fail_successor_insert")
        conn.commit()

    accepted = call(env, *success_args)
    assert accepted["mode"] == "CREATED" and accepted["created"]
    assert not accepted["providerLaunched"] and not accepted["contextDelivered"]
    assert not accepted["browserChatConnected"] and not accepted["authorityVerified"]
    assert accepted["assignmentId"] == aid
    assert accepted["previousSessionId"] == old
    assert accepted["sessionId"] == "session-new"
    assert accepted["session"]["status"] == "IDLE"
    assert accepted["session"]["providerSessionId"] == ""
    after = call(env, "hospital", "room", "room-main", "--json")
    assert after["id"] == "room-main" and after["patientId"] == "patient-fixture"
    assert after["assignmentId"] == aid and after["doctorId"] == "doc-new"
    assert after["providerId"] == "mock-next"
    old_record = call(env, "hospital", "session", old, "--json")
    assert old_record["doctorId"] == "doc-old" and old_record["status"] == "FAILED"
    assert old_record["endedAt"]
    msgs = call(env, "hospital", "messages", "room-main", "--json")
    assert len(msgs) == 1 and msgs[0]["body"] == "Prior work remains saved"
    report = call(env, "hospital", "room-reports", "room-main", "--json")
    assert len(report) == 1 and report[0]["kind"] == "HANDOFF"
    checkpoint = call(env, "hospital", "checkpoints", "room-main", "--json")
    assert len(checkpoint) == 1
    events = call(env, "hospital", "events", "session-new", "--json")
    assert len(events) == 1 and events[0]["type"] == "room.succession.admitted"
    assert events[0]["payload"]["previousSessionId"] == old

    # The successor gets a fresh context assembled from the SAME Room:
    # required handoffs and the untouched assignment, not copied chat text.
    context = call(env, "agent", "context", "session-new", "--json")
    assert context["room"]["id"] == "room-main"
    assert str(context["assignment"]["id"]) == aid
    assert any("Preserve the verified work" in item["body"]
               for item in context["requiredHandoffs"])
    assert context["session"]["doctorId"] == "doc-new"
    assert not call(env, "hospital", "events", old, "--json")

    again = call(env, *success_args)
    assert again["mode"] == "REUSED" and not again["created"]
    assert len(call(env, "hospital", "events", "session-new", "--json")) == 1
    # After succession the old staffing guard fails closed before the
    # competing-open-Session guard: either way no third Session is created.
    assert "old Room staffing changed" in call(
        env, *args("room-main", old, "different-new", aid, bed), accept=False)
    assert "not exact idle replay" in call(
        env, *args("room-main", old, "session-new", aid, bed,
                   provider="mock-old"), accept=False)

    # A second terminal Room can have only one winner from two simultaneous
    # operator attempts. The losing request must preserve the original state.
    bed2, aid2, old2 = setup(env, base, "room-race")
    call(env, "hospital", "doctor-put", "doc-race", "--name", "Race successor",
         "--status", "ACTIVE", "--json")
    call(env, "hospital", "session-runtime", old2, "--status", "FAILED",
         "--ended", "--json")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(raw, env, *args("room-race", old2,
                            "race-" + str(n), aid2, bed2,
                            doctor="doc-race")) for n in (1,2)]
        race = [f.result() for f in futures]
    assert sum(proc.returncode == 0 for proc in race) == 1, race
    assert sum(proc.returncode != 0 for proc in race) == 1, race
    assert len(call(env,"hospital","sessions","--room-id","room-race","--json")) == 2
    assert call(env,"hospital","room","room-race","--json")["doctorId"] == "doc-race"

    # A Doctor already owning another open Room cannot be admitted twice.
    bed_busy, aid_busy, old_busy = setup(env, base, "room-busy-doctor")
    call(env, "hospital", "session-runtime", old_busy, "--status", "FAILED",
         "--ended", "--json")
    blocked_doctor = call(env, *args("room-busy-doctor", old_busy,
        "busy-successor", aid_busy, bed_busy, doctor="doc-new"), accept=False)
    assert "successor Doctor busy in another Room" in blocked_doctor, blocked_doctor

    call(env, "hospital", "doctor-put", "doc-free", "--name", "Available successor",
         "--status", "ACTIVE", "--json")
    bed_missing, aid_missing, old_missing = setup(
        env, base, "room-missing-evidence", with_handoff=False)
    call(env, "hospital", "session-runtime", old_missing, "--status", "FAILED",
         "--ended", "--json")
    with sqlite3.connect(database) as conn:
        conn.execute("DELETE FROM room_checkpoints WHERE room_id = ?",
                     ("room-missing-evidence",))
        conn.commit()
    missing = call(env, *args("room-missing-evidence", old_missing,
        "missing-successor", aid_missing, bed_missing,
        doctor="doc-free"), accept=False)
    assert "no durable HANDOFF or checkpoint" in missing, missing

    # Rebinding a Room to another Bed after its predecessor worked elsewhere
    # does not silently carry over that predecessor's history.
    original_bed, aid_shared, old_shared = setup(env, base, "room-shared-bed")
    call(env, "hospital", "session-runtime", old_shared, "--status", "FAILED",
         "--ended", "--json")
    call(env, "hospital", "room-bind", "room-shared-bed",
         "--repository", "org/project", "--patient-id", "patient-fixture",
         "--doctor-id", "doc-old", "--provider-id", "mock-old",
         "--team", "backend", "--branch", "feature/succession",
         "--bed-path", bed, "--json")
    shared_args = args("room-shared-bed", old_shared, "shared-successor",
                       aid_shared, bed, doctor="doc-free")
    assert "previous Session Bed differs" in call(
        env, *shared_args, accept=False)
    call(env, "hospital", "session-runtime", old_shared,
         "--working-directory", bed, "--json")
    assert "Bed occupied by another Room" in call(
        env, *shared_args, accept=False)

    # A later terminated historical Session supersedes an older source ID.
    bed_stale, aid_stale, old_stale = setup(env, base, "room-stale")
    call(env, "hospital", "session-runtime", old_stale, "--status", "FAILED",
         "--ended", "--json")
    call(env, "hospital", "session-put", "later-terminated",
         "--room-id", "room-stale", "--doctor-id", "doc-old",
         "--provider-id", "mock-old", "--status", "FAILED", "--json")
    call(env, "hospital", "session-runtime", "later-terminated",
         "--working-directory", bed_stale, "--ended", "--json")
    assert "stale previous Session" in call(env,
         *args("room-stale", old_stale, "stale-successor", aid_stale,
               bed_stale, doctor="doc-free"), accept=False)

    # Every rejected attempt must leave the previous Room staffing unchanged.
    for unchanged in ("room-busy-doctor", "room-missing-evidence",
                      "room-shared-bed", "room-stale"):
        room_record = call(env, "hospital", "room", unchanged, "--json")
        assert room_record["doctorId"] == "doc-old", unchanged

print("HOSPITAL DOCTOR SUCCESSION // PASS // exact ownership, released prior Session, atomic rollback, replay, collision, preserved Assignment and successor context")
