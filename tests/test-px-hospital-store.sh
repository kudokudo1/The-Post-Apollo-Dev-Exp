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
bind_json="$("$ROOT/bin/px" hospital room-bind T7 --repository kudokudo1/taskbars-post-apollo --patient-id patient-taskbars --patient-label "TASKBARS" --team T7 --branch feature/desktop-identity --bed-path "$TMP/t7-bed" --doctor-id doctor-t7 --provider-id hermes --json)"
session_json="$("$ROOT/bin/px" hospital session-put session-t6-1 --room-id T6 --doctor-id doctor-t6 --provider-id codex --status IDLE --json)"
outgoing_json="$("$ROOT/bin/px" hospital message-append --room-id T6 --session-id session-t6-1 --author-role operator --author-id operator --direction outgoing --body "Inspect Application Audio ownership." --json)"
incoming_json="$(printf '%s' 'I found two remaining presentation bindings.' | "$ROOT/bin/px" hospital message-append --room-id T6 --session-id session-t6-1 --author-role doctor --author-id doctor-t6 --direction incoming --body-stdin --json)"
checkpoint_json="$(printf '%s' 'Checkpoint: presentation ownership narrowed.' | "$ROOT/bin/px" hospital checkpoint-append --room-id T6 --session-id session-t6-1 --checkpoint-kind MANUAL --body-stdin --json)"
checkpoint_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$checkpoint_json")"
incoming_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$incoming_json")"
report_json="$(printf '%s' 'Doctor note body.' | "$ROOT/bin/px" hospital room-report-append --room-id T6 --session-id session-t6-1 --checkpoint-id "$checkpoint_id" --source-message-id "$incoming_id" --report-kind DOCTOR_NOTE --title "T6 Doctor Note" --branch feature/application-audio --head-sha abc123 --git-evidence-status VERIFIED --dirty --changed-files-json '["widgets/AppControlW.qml"]' --insertions 12 --deletions 3 --body-stdin --json)"
report_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$report_json")"
exact_report_json="$("$ROOT/bin/px" hospital room-report "$report_id" --json)"
checkpoints_json="$("$ROOT/bin/px" hospital checkpoints T6 --limit 50 --json)"
room_reports_json="$("$ROOT/bin/px" hospital room-reports T6 --limit 50 --json)"

patient_chart_json="$(printf '%s' 'Taskbars keeps provider-independent Room identity.' | "$ROOT/bin/px" hospital chart-entry-add --scope PATIENT --patient-id patient-taskbars --entry-kind INVARIANT --title "Room identity" --priority 95 --author-role operator --author-id operator --source-type MANUAL --source-ref architecture-review --body-stdin --json)"
patient_chart_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$patient_chart_json")"

room_chart_old_json="$(printf '%s' 'Preserve the AppControl presentation shim during extraction.' | "$ROOT/bin/px" hospital chart-entry-add --scope ROOM --room-id T6 --entry-kind DECISION --title "Presentation shim" --priority 80 --author-role operator --author-id operator --source-type ROOM_REPORT --source-ref "$report_id" --source-room-id T6 --source-session-id session-t6-1 --source-message-id "$incoming_id" --source-checkpoint-id "$checkpoint_id" --source-report-id "$report_id" --body-stdin --json)"
room_chart_old_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$room_chart_old_json")"

room_chart_new_json="$(printf '%s' 'Move presentation ownership now; the compatibility shim is no longer required.' | "$ROOT/bin/px" hospital chart-entry-add --scope ROOM --room-id T6 --entry-kind DECISION --title "Presentation ownership" --priority 90 --author-role operator --author-id operator --source-type ROOM_REPORT --source-ref "$report_id" --source-room-id T6 --source-session-id session-t6-1 --source-report-id "$report_id" --supersedes-id "$room_chart_old_id" --body-stdin --json)"

room_chart_old_after_json="$("$ROOT/bin/px" hospital chart-entry "$room_chart_old_id" --json)"
patient_chart_active_json="$("$ROOT/bin/px" hospital chart-entries --scope PATIENT --patient-id patient-taskbars --status ACTIVE --json)"
room_chart_active_json="$("$ROOT/bin/px" hospital chart-entries --scope ROOM --room-id T6 --status ACTIVE --json)"
room_chart_all_json="$("$ROOT/bin/px" hospital chart-entries --scope ROOM --room-id T6 --status ALL --json)"
patient_chart_resolved_json="$("$ROOT/bin/px" hospital chart-entry-status "$patient_chart_id" RESOLVED --json)"
patient_chart_active_after_json="$("$ROOT/bin/px" hospital chart-entries --scope PATIENT --patient-id patient-taskbars --status ACTIVE --json)"
"$ROOT/bin/px" hospital room-bind T6 --repository kudokudo1/taskbars-post-apollo --patient-id patient-taskbars --team T6 --branch feature/application-audio --bed-path "$TMP/t6-bed" --doctor-id doctor-t6 --json >/dev/null
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
    "$checkpoint_json" \
    "$checkpoints_json" \
    "$report_json" \
    "$exact_report_json" \
    "$room_reports_json" \
    "$patient_chart_json" \
    "$room_chart_old_json" \
    "$room_chart_new_json" \
    "$room_chart_old_after_json" \
    "$patient_chart_active_json" \
    "$room_chart_active_json" \
    "$room_chart_all_json" \
    "$patient_chart_resolved_json" \
    "$patient_chart_active_after_json" \
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
authority_test = json.loads(sys.argv[7])
authority_push = json.loads(sys.argv[8])
authority_default = json.loads(sys.argv[9])
authority_default_edit = json.loads(sys.argv[10])
bound = json.loads(sys.argv[7])
session = json.loads(sys.argv[8])
outgoing = json.loads(sys.argv[9])
incoming = json.loads(sys.argv[10])
checkpoint = json.loads(sys.argv[11])
checkpoints = json.loads(sys.argv[12])
report = json.loads(sys.argv[13])
exact_report = json.loads(sys.argv[14])
room_reports = json.loads(sys.argv[15])
patient_chart = json.loads(sys.argv[16])
room_chart_old = json.loads(sys.argv[17])
room_chart_new = json.loads(sys.argv[18])
room_chart_old_after = json.loads(sys.argv[19])
patient_chart_active = json.loads(sys.argv[20])
room_chart_active = json.loads(sys.argv[21])
room_chart_all = json.loads(sys.argv[22])
patient_chart_resolved = json.loads(sys.argv[23])
patient_chart_active_after = json.loads(sys.argv[24])
rooms = json.loads(sys.argv[25])
doctors = json.loads(sys.argv[26])
sessions = json.loads(sys.argv[27])
messages = json.loads(sys.argv[28])
older = json.loads(sys.argv[29])

for payload in (init, status):
    assert payload["status"] == "READY", payload
    assert payload["schema_version"] == 10, payload
    assert payload["counts"] == {
        "patients": 0,
        "rooms": 0,
        "doctors": 0,
        "sessions": 0,
        "messages": 0,
        "session_events": 0,
        "room_checkpoints": 0,
        "room_reports": 0,
        "chart_entries": 0,
        "chart_suggestions": 0,
        "assignments": 0,
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

assert checkpoint["roomId"] == "T6", checkpoint
assert checkpoint["sessionId"] == "session-t6-1", checkpoint
assert checkpoint["doctorId"] == "doctor-t6", checkpoint
assert checkpoint["providerId"] == "codex", checkpoint
assert checkpoint["kind"] == "MANUAL", checkpoint
assert checkpoint["body"] == "Checkpoint: presentation ownership narrowed.", checkpoint
assert len(checkpoints) == 1, checkpoints
assert checkpoints[0]["id"] == checkpoint["id"], checkpoints

assert report["roomId"] == "T6", report
assert report["sessionId"] == "session-t6-1", report
assert report["checkpointId"] == checkpoint["id"], report
assert report["sourceMessageId"] == incoming["id"], report
assert report["doctorId"] == "doctor-t6", report
assert report["providerId"] == "codex", report
assert report["kind"] == "DOCTOR_NOTE", report
assert report["title"] == "T6 Doctor Note", report
assert report["repository"] == "kudokudo1/taskbars-post-apollo", report
assert report["branch"] == "feature/application-audio", report
assert report["headSha"] == "abc123", report
assert report["gitEvidenceStatus"] == "VERIFIED", report
assert report["dirty"] is True, report
assert report["changedFiles"] == ["widgets/AppControlW.qml"], report
assert report["changedFileCount"] == 1, report
assert report["insertions"] == 12, report
assert report["deletions"] == 3, report
assert exact_report == report, (exact_report, report)
assert len(room_reports) == 1, room_reports
assert room_reports[0]["id"] == report["id"], room_reports

assert patient_chart["scope"] == "PATIENT", patient_chart
assert patient_chart["patientId"] == "patient-taskbars", patient_chart
assert patient_chart["roomId"] == "", patient_chart
assert patient_chart["kind"] == "INVARIANT", patient_chart
assert patient_chart["priority"] == 95, patient_chart
assert patient_chart["status"] == "ACTIVE", patient_chart
assert patient_chart["authorRole"] == "operator", patient_chart
assert patient_chart["sourceType"] == "MANUAL", patient_chart
assert patient_chart["sourceRef"] == "architecture-review", patient_chart

assert room_chart_old["scope"] == "ROOM", room_chart_old
assert room_chart_old["roomId"] == "T6", room_chart_old
assert room_chart_old["patientId"] == "", room_chart_old
assert room_chart_old["sourceRoomId"] == "T6", room_chart_old
assert room_chart_old["sourceSessionId"] == "session-t6-1", room_chart_old
assert room_chart_old["sourceMessageId"] == incoming["id"], room_chart_old
assert room_chart_old["sourceCheckpointId"] == checkpoint["id"], room_chart_old
assert room_chart_old["sourceReportId"] == report["id"], room_chart_old

assert room_chart_new["status"] == "ACTIVE", room_chart_new
assert room_chart_new["supersedesId"] == room_chart_old["id"], room_chart_new
assert room_chart_new["priority"] == 90, room_chart_new

assert room_chart_old_after["status"] == "SUPERSEDED", room_chart_old_after
assert room_chart_old_after["supersededById"] == room_chart_new["id"], room_chart_old_after
assert room_chart_old_after["body"] == room_chart_old["body"], room_chart_old_after

assert [row["id"] for row in patient_chart_active] == [patient_chart["id"]], patient_chart_active
assert [row["id"] for row in room_chart_active] == [room_chart_new["id"]], room_chart_active
assert [row["id"] for row in room_chart_all] == [
    room_chart_new["id"],
    room_chart_old["id"],
], room_chart_all

assert patient_chart_resolved["status"] == "RESOLVED", patient_chart_resolved
assert patient_chart_resolved["body"] == patient_chart["body"], patient_chart_resolved
assert patient_chart_active_after == [], patient_chart_active_after

assert len(rooms) == 2, rooms
rooms_by_id = {row["id"]: row for row in rooms}
assert rooms_by_id["T6"]["lastMessage"] == incoming["body"], rooms
assert rooms_by_id["T6"]["providerId"] == "codex", rooms
assert rooms_by_id["T7"]["doctorId"] == "doctor-t7", rooms
assert rooms_by_id["T7"]["providerId"] == "hermes", rooms

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
    assert version == ("10",), version

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for table in ("patients", "rooms", "doctors", "sessions", "messages", "session_events", "room_checkpoints", "room_reports", "chart_entries", "chart_suggestions", "assignments"):
        assert table in tables, (table, tables)

    room_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(rooms)")
    }
    assert "provider_id" in room_columns, room_columns

    session_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(sessions)")
    }
    for column in (
        "provider_session_id",
        "working_directory",
        "last_exit_code",
        "last_error",
        "active_pid",
        "turn_started_at",
    ):
        assert column in session_columns, (column, session_columns)

    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(journal_mode).lower() == "wal", journal_mode
finally:
    conn.close()
PY

assignment_json="$("$ROOT/bin/px" hospital assignment-create --room-id T6 --title "Finish Application Audio extraction" --goal "Move shared application audio ownership into the service without breaking APP/WINDOW/TAB consumers." --constraints "Do not invent canonical application identity." --definition-done "Audio service owns discovery and mutations; consumers only read the service." --permissions-json '["READ","EDIT","TEST","COMMIT"]' --checklist "- [ ] service\n- [ ] consumers\n- [ ] tests" --open-questions "Identity contract remains external." --phase IMPLEMENTATION --created-by-role operator --created-by-id operator --json)"
assignment_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$assignment_json")"
assignment_ready_json="$("$ROOT/bin/px" hospital assignment-status "$assignment_id" READY --json)"
assignment_active_json="$("$ROOT/bin/px" hospital assignment-activate "$assignment_id" --json)"
assignment_updated_json="$("$ROOT/bin/px" hospital assignment-update "$assignment_id" --phase VERIFY --checklist "- [x] service\n- [x] consumers\n- [ ] tests" --json)"
assignments_json="$("$ROOT/bin/px" hospital assignments --room-id T6 --status ALL --json)"
room_after_assignment_json="$("$ROOT/bin/px" hospital room T6 --json)"
authority_test_json="$("$ROOT/bin/px" hospital assignment-authority --room-id T6 --permission TEST --json)"
authority_push_json="$("$ROOT/bin/px" hospital assignment-authority --room-id T6 --permission PUSH --json)"
authority_default_json="$("$ROOT/bin/px" hospital assignment-authority --room-id T7 --permission READ --json)"
authority_default_edit_json="$("$ROOT/bin/px" hospital assignment-authority --room-id T7 --permission EDIT --json)"

set +e
authority_require_output="$("$ROOT/bin/px" hospital assignment-authority --room-id T6 --permission PUSH --require --json 2>&1)"
authority_require_status=$?
set -e
[[ "$authority_require_status" -ne 0 ]] || {
    printf 'expected PUSH authority requirement to fail\n' >&2
    exit 1
}
case "$authority_require_output" in
    *"HOSPITAL AUTHORITY REFUSED // PUSH NOT GRANTED"*) ;;
    *)
        printf 'unexpected authority refusal: %s\n' "$authority_require_output" >&2
        exit 1
        ;;
esac

python3 - "$assignment_json" "$assignment_ready_json" "$assignment_active_json" "$assignment_updated_json" "$assignments_json" "$room_after_assignment_json" "$authority_test_json" "$authority_push_json" "$authority_default_json" "$authority_default_edit_json" <<'PY'
import json
import sys

created = json.loads(sys.argv[1])
ready = json.loads(sys.argv[2])
active = json.loads(sys.argv[3])
updated = json.loads(sys.argv[4])
rows = json.loads(sys.argv[5])
room = json.loads(sys.argv[6])

assert created["status"] == "DRAFT", created
assert created["roomId"] == "T6", created
assert created["permissions"] == ["READ", "EDIT", "TEST", "COMMIT"], created
assert ready["status"] == "READY", ready
assert active["assignment"]["status"] == "ACTIVE", active
assert active["room"]["assignmentId"] == created["id"], active
assert updated["phase"] == "VERIFY", updated
assert "- [x] service" in updated["checklist"], updated
assert [row["id"] for row in rows] == [created["id"]], rows
assert room["assignmentId"] == created["id"], room

assert authority_test["allowed"] is True, authority_test
assert authority_test["permission"] == "TEST", authority_test
assert authority_test["source"] == "ACTIVE_ASSIGNMENT", authority_test
assert authority_test["assignmentId"] == created["id"], authority_test
assert authority_push["allowed"] is False, authority_push
assert authority_push["permission"] == "PUSH", authority_push
assert authority_default["allowed"] is True, authority_default
assert authority_default["permissions"] == ["READ"], authority_default
assert authority_default["source"] == "READ_ONLY_DEFAULT", authority_default
assert authority_default_edit["allowed"] is False, authority_default_edit
PY

suggestion_json="$(printf '%s' 'Keep operator authority over durable memory promotion.' | "$ROOT/bin/px" hospital chart-suggestion-add --scope ROOM --room-id T6 --entry-kind DECISION --title "Chart authority" --priority 88 --doctor-id doctor-t6 --provider-id codex --source-room-id T6 --source-session-id session-t6-1 --source-message-id "$incoming_id" --body-stdin --json)"
suggestion_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$suggestion_json")"
pending_suggestions_json="$("$ROOT/bin/px" hospital chart-suggestions --scope ROOM --room-id T6 --status PENDING --json)"
promoted_json="$("$ROOT/bin/px" hospital chart-suggestion-promote "$suggestion_id" --operator-id operator --note "accepted in store test" --json)"
promoted_entry_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["entry"]["id"])' "$promoted_json")"
promoted_entry_json="$("$ROOT/bin/px" hospital chart-entry "$promoted_entry_id" --json)"

reject_json="$(printf '%s' 'This proposal should remain history but never enter the Chart.' | "$ROOT/bin/px" hospital chart-suggestion-add --scope ROOM --room-id T6 --entry-kind NOTE --title "Reject me" --priority 10 --doctor-id doctor-t6 --provider-id codex --source-room-id T6 --source-session-id session-t6-1 --body-stdin --json)"
reject_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$reject_json")"
rejected_json="$("$ROOT/bin/px" hospital chart-suggestion-reject "$reject_id" --operator-id operator --note "not durable" --json)"

python3 - "$suggestion_json" "$pending_suggestions_json" "$promoted_json" "$promoted_entry_json" "$rejected_json" <<'PY'
import json
import sys

suggestion = json.loads(sys.argv[1])
pending = json.loads(sys.argv[2])
promoted = json.loads(sys.argv[3])
entry = json.loads(sys.argv[4])
rejected = json.loads(sys.argv[5])

assert suggestion["status"] == "PENDING", suggestion
assert suggestion["doctorId"] == "doctor-t6", suggestion
assert suggestion["providerId"] == "codex", suggestion
assert suggestion["sourceSessionId"] == "session-t6-1", suggestion
assert [row["id"] for row in pending] == [suggestion["id"]], pending

assert promoted["suggestion"]["status"] == "PROMOTED", promoted
assert promoted["suggestion"]["operatorId"] == "operator", promoted
assert promoted["suggestion"]["promotedEntryId"] == promoted["entry"]["id"], promoted
assert promoted["entry"]["authorRole"] == "operator", promoted
assert promoted["entry"]["sourceType"] == "DOCTOR_SUGGESTION", promoted
assert promoted["entry"]["sourceRef"] == suggestion["id"], promoted
assert entry == promoted["entry"], (entry, promoted)

assert rejected["status"] == "REJECTED", rejected
assert rejected["operatorId"] == "operator", rejected
assert rejected["promotedEntryId"] == "", rejected
PY

printf 'hospital state store: PASS\n'
