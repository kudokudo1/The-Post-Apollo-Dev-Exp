#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export PX_HOSPITAL_DATA_DIR="$TMP/hospital-data"

init_json="$("$ROOT/bin/px" hospital init --json)"
status_json="$("$ROOT/bin/px" hospital status --json)"

doctor_json="$("$ROOT/bin/px" hospital doctor-put doctor-t6 --name "T6 DOCTOR" --role "APPLICATION AUDIO DOCTOR" --status ACTIVE --json)"
patient_json="$("$ROOT/bin/px" hospital patient-put patient-taskbars kudokudo1/taskbars-post-apollo --label "TASKBARS" --json)"
room_json="$("$ROOT/bin/px" hospital room-put T6 --patient-id patient-taskbars --team T6 --branch feature/application-audio --bed-path "$TMP/t6-bed" --doctor-id doctor-t6 --json)"
bind_json="$("$ROOT/bin/px" hospital room-bind T7 --repository kudokudo1/taskbars-post-apollo --patient-id patient-taskbars --patient-label "TASKBARS" --team T7 --branch feature/desktop-identity --bed-path "$TMP/t7-bed" --doctor-id doctor-t7 --json)"
session_json="$("$ROOT/bin/px" hospital session-put session-t6-1 --room-id T6 --doctor-id doctor-t6 --provider-id codex --status IDLE --json)"
outgoing_json="$("$ROOT/bin/px" hospital message-append --room-id T6 --session-id session-t6-1 --author-role operator --author-id operator --direction outgoing --body "Inspect Application Audio ownership." --json)"
incoming_json="$(printf '%s' 'I found two remaining presentation bindings.' | "$ROOT/bin/px" hospital message-append --room-id T6 --session-id session-t6-1 --author-role doctor --author-id doctor-t6 --direction incoming --body-stdin --json)"
rooms_json="$("$ROOT/bin/px" hospital rooms --json)"
doctors_json="$("$ROOT/bin/px" hospital doctors --json)"
sessions_json="$("$ROOT/bin/px" hospital sessions --room-id T6 --json)"
messages_json="$("$ROOT/bin/px" hospital messages T6 --limit 100 --json)"
older_json="$("$ROOT/bin/px" hospital messages T6 --limit 1 --before-id 2 --json)"

python3 - \
    "$init_json" \
    "$status_json" \
    "$PX_HOSPITAL_DATA_DIR" \
    "$doctor_json" \
    "$patient_json" \
    "$room_json" \
    "$bind_json" \
    "$session_json" \
    "$outgoing_json" \
    "$incoming_json" \
    "$rooms_json" \
    "$doctors_json" \
    "$sessions_json" \
    "$messages_json" \
    "$older_json" <<'PY'
import json
import pathlib
import sqlite3
import sys

init = json.loads(sys.argv[1])
status = json.loads(sys.argv[2])
data_dir = pathlib.Path(sys.argv[3])
doctor = json.loads(sys.argv[4])
patient = json.loads(sys.argv[5])
room = json.loads(sys.argv[6])
bound = json.loads(sys.argv[7])
session = json.loads(sys.argv[8])
outgoing = json.loads(sys.argv[9])
incoming = json.loads(sys.argv[10])
rooms = json.loads(sys.argv[11])
doctors = json.loads(sys.argv[12])
sessions = json.loads(sys.argv[13])
messages = json.loads(sys.argv[14])
older = json.loads(sys.argv[15])

for payload in (init, status):
    assert payload["status"] == "READY", payload
    assert payload["schema_version"] == 3, payload
    assert payload["counts"] == {
        "patients": 0,
        "rooms": 0,
        "doctors": 0,
        "sessions": 0,
        "messages": 0,
        "session_events": 0,
    }, payload

db = data_dir / "hospital.db"
artifacts = data_dir / "artifacts"

assert db.is_file(), db
assert artifacts.is_dir(), artifacts


assert doctor["id"] == "doctor-t6", doctor
assert doctor["name"] == "T6 DOCTOR", doctor
assert doctor["role"] == "APPLICATION AUDIO DOCTOR", doctor
assert doctor["status"] == "ACTIVE", doctor

assert patient["patient_id"] == "patient-taskbars", patient
assert patient["repository"] == "kudokudo1/taskbars-post-apollo", patient

assert room["id"] == "T6", room
assert room["displayNameInProfile"] == "T6", room
assert room["nickname"] == "feature/application-audio", room
assert room["doctorId"] == "doctor-t6", room

assert bound["id"] == "T7", bound
assert bound["patientId"] == "patient-taskbars", bound
assert bound["repository"] == "kudokudo1/taskbars-post-apollo", bound
assert bound["nickname"] == "feature/desktop-identity", bound
assert bound["bedPath"].endswith("/t7-bed"), bound

assert session["id"] == "session-t6-1", session
assert session["roomId"] == "T6", session
assert session["providerId"] == "codex", session

assert outgoing["direction"] == "outgoing", outgoing
assert outgoing["body"] == "Inspect Application Audio ownership.", outgoing
assert incoming["direction"] == "incoming", incoming
assert incoming["body"] == "I found two remaining presentation bindings.", incoming

assert len(rooms) == 2, rooms
rooms_by_id = {row["id"]: row for row in rooms}
assert rooms_by_id["T6"]["lastMessage"] == incoming["body"], rooms
assert rooms_by_id["T7"]["doctorId"] == "doctor-t7", rooms

assert len(doctors) == 2, doctors
doctors_by_id = {row["id"]: row for row in doctors}
assert doctors_by_id["doctor-t6"]["name"] == "T6 DOCTOR", doctors
assert doctors_by_id["doctor-t7"]["name"] == "doctor-t7", doctors

assert len(sessions) == 1, sessions
assert sessions[0]["id"] == "session-t6-1", sessions

assert [row["direction"] for row in messages] == ["outgoing", "incoming"], messages
assert [row["body"] for row in messages] == [outgoing["body"], incoming["body"]], messages

assert len(older) == 1, older
assert older[0]["id"] == outgoing["id"], older

conn = sqlite3.connect(db)
try:
    version = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    assert version == ("3",), version

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for table in ("patients", "rooms", "doctors", "sessions", "messages", "session_events"):
        assert table in tables, (table, tables)

    session_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(sessions)")
    }
    for column in (
        "provider_session_id",
        "working_directory",
        "last_exit_code",
        "last_error",
    ):
        assert column in session_columns, (column, session_columns)

    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(journal_mode).lower() == "wal", journal_mode
finally:
    conn.close()
PY

printf 'hospital state store: PASS\n'
