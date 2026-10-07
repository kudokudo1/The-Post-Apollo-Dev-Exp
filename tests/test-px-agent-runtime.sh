#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export PX_HOSPITAL_DATA_DIR="$TMP/hospital-data"
BED="$TMP/t6-bed"
mkdir -p "$BED"

git -C "$BED" init -q
git -C "$BED" config user.email "hospital-test@example.invalid"
git -C "$BED" config user.name "Hospital Test"
printf 'base\n' >"$BED/tracked.txt"
git -C "$BED" add tracked.txt
git -C "$BED" commit -qm "baseline"

cat > "$TMP/providers.json" <<EOF
{
  "version": 1,
  "providers": {
    "mock": {
      "name": "MOCK",
      "command": "python3",
      "dialect": "hermes-stream-json",
      "startArgs": [
        "$ROOT/tests/fixtures/mock-hermes-agent.py",
        "chat",
        "--format",
        "stream-json",
        "--query-file",
        "-"
      ],
      "resumeArgs": [
        "$ROOT/tests/fixtures/mock-hermes-agent.py",
        "chat",
        "--resume",
        "{provider_session_id}",
        "--format",
        "stream-json",
        "--query-file",
        "-"
      ]
    }
  }
}
EOF

export PX_AGENT_PROVIDER_CONFIG="$TMP/providers.json"

"$ROOT/bin/px" hospital init --json >/dev/null
"$ROOT/bin/px" hospital room-bind T6     --repository kudokudo1/taskbars-post-apollo     --patient-id patient-taskbars     --patient-label TASKBARS     --team T6     --branch feature/application-audio     --bed-path "$BED"     --doctor-id doctor-t6     --json >/dev/null

patient_chart_json="$(printf '%s' 'Provider identity must never replace Room identity.' | "$ROOT/bin/px" hospital chart-entry-add --scope PATIENT --patient-id patient-taskbars --entry-kind INVARIANT --title "Room identity" --priority 95 --author-role operator --author-id operator --body-stdin --json)"
room_chart_json="$(printf '%s' 'Keep Application Audio work inside the T6 Bed and preserve supervised checkpoints.' | "$ROOT/bin/px" hospital chart-entry-add --scope ROOM --room-id T6 --entry-kind CONSTRAINT --title "T6 scope" --priority 90 --author-role operator --author-id operator --body-stdin --json)"
assignment_json="$("$ROOT/bin/px" hospital assignment-create --room-id T6 --title "Application Audio extraction" --goal "Extract shared APP/WINDOW/TAB audio ownership into the reusable service." --constraints "Do not invent canonical application identity." --definition-done "Consumers use the shared audio service and runtime contracts pass." --permissions-json '["READ","EDIT","TEST"]' --checklist "- [ ] service\n- [ ] consumers\n- [ ] tests" --open-questions "Wait for identity authority where necessary." --phase IMPLEMENTATION --json)"
assignment_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$assignment_json")"
assignment_active_json="$("$ROOT/bin/px" hospital assignment-activate "$assignment_id" --json)"

providers_json="$("$ROOT/bin/px" agent providers --json)"
created_json="$("$ROOT/bin/px" agent session-create     --room-id T6     --doctor-id doctor-t6     --provider-id mock     --working-directory "$BED"     --session-id session-t6-agent     --json)"
context_json="$("$ROOT/bin/px" agent context session-t6-agent --json)"

turn_one_frame="$(python3 -c 'import json; print(json.dumps({"prompt": "first task\nwith detail"}))')"
turn_one_json="$(printf '%s\n' "$turn_one_frame" | "$ROOT/bin/px" agent turn session-t6-agent --prompt-json-stdin --timeout 30 --json)"

turn_two_json="$(printf '%s' 'second task' |     "$ROOT/bin/px" agent turn session-t6-agent         --prompt-stdin         --timeout 30         --json)"

session_json="$("$ROOT/bin/px" hospital session session-t6-agent --json)"
messages_json="$("$ROOT/bin/px" hospital messages T6 --limit 100 --json)"
events_json="$("$ROOT/bin/px" hospital events session-t6-agent --limit 200 --json)"

python3 -     "$providers_json"     "$created_json"     "$context_json"     "$patient_chart_json"     "$room_chart_json"     "$assignment_json"     "$assignment_active_json"     "$turn_one_json"     "$turn_two_json"     "$session_json"     "$messages_json"     "$events_json"     "$BED" <<'PY'
import json
import pathlib
import sys

providers = json.loads(sys.argv[1])
created = json.loads(sys.argv[2])
context = json.loads(sys.argv[3])
patient_chart = json.loads(sys.argv[4])
room_chart = json.loads(sys.argv[5])
assignment = json.loads(sys.argv[6])
assignment_active = json.loads(sys.argv[7])
turn_one = json.loads(sys.argv[8])
turn_two = json.loads(sys.argv[9])
session = json.loads(sys.argv[10])
messages = json.loads(sys.argv[11])
events = json.loads(sys.argv[12])
bed = pathlib.Path(sys.argv[13])

assert providers == [
    {
        "id": "mock",
        "name": "MOCK",
        "command": "python3",
        "endpoint": providers[0]["endpoint"],
        "dialect": "hermes-stream-json",
        "available": True,
        "error": "",
    }
], providers
assert providers[0]["endpoint"], providers

assert created["id"] == "session-t6-agent", created
assert created["providerId"] == "mock", created
assert created["workingDirectory"] == str(bed), created
assert created["providerSessionId"] == "", created
assert created["status"] == "IDLE", created

assert context["version"] == 1, context
assert context["session"]["id"] == "session-t6-agent", context
assert context["room"]["id"] == "T6", context
assert context["room"]["patientId"] == "patient-taskbars", context
assert context["room"]["repository"] == "kudokudo1/taskbars-post-apollo", context
assert context["room"]["assignmentId"] == assignment["id"], context
assert context["assignment"]["id"] == assignment["id"], context
assert context["assignment"]["status"] == "ACTIVE", context
assert context["assignment"]["phase"] == "IMPLEMENTATION", context
assert context["assignment"]["permissions"] == ["READ", "EDIT", "TEST"], context
assert "Extract shared APP/WINDOW/TAB audio ownership" in context["renderedText"], context
assert "Do not invent canonical application identity." in context["renderedText"], context
assert assignment_active["room"]["assignmentId"] == assignment["id"], assignment_active
assert context["git"]["status"] == "VERIFIED", context
assert context["git"]["dirty"] is False, context
assert len(context["git"]["headSha"]) == 40, context
assert [row["id"] for row in context["patientChart"]] == [patient_chart["id"]], context
assert [row["id"] for row in context["roomChart"]] == [room_chart["id"]], context
assert context["recentMessages"] == [], context
assert "HOSPITAL LIVE CONTEXT // GENERATED" in context["renderedText"], context
assert "Provider identity must never replace Room identity." in context["renderedText"], context
assert "Keep Application Audio work inside the T6 Bed" in context["renderedText"], context

assert turn_one["assistant"] == "MOCK: first task\nwith detail", turn_one
assert turn_one["providerSessionId"] == "mock-provider-session", turn_one
assert turn_two["assistant"] == "MOCK: second task", turn_two
assert turn_two["providerSessionId"] == "mock-provider-session", turn_two

assert turn_one["context"]["assignmentId"] == assignment["id"], turn_one
assert turn_one["context"]["assignmentStatus"] == "ACTIVE", turn_one
assert turn_one["context"]["assignmentPhase"] == "IMPLEMENTATION", turn_one
assert turn_one["context"]["assignmentPermissions"] == ["READ", "EDIT", "TEST"], turn_one
assert turn_one["context"]["patientChartEntryIds"] == [patient_chart["id"]], turn_one
assert turn_one["context"]["roomChartEntryIds"] == [room_chart["id"]], turn_one
assert turn_one["context"]["recentMessageIds"] == [], turn_one
assert turn_one["context"]["gitEvidenceStatus"] == "VERIFIED", turn_one
assert len(turn_one["context"]["gitHeadSha"]) == 40, turn_one

assert turn_two["context"]["patientChartEntryIds"] == [patient_chart["id"]], turn_two
assert turn_two["context"]["roomChartEntryIds"] == [room_chart["id"]], turn_two
assert len(turn_two["context"]["recentMessageIds"]) == 2, turn_two
assert turn_two["context"]["gitEvidenceStatus"] == "VERIFIED", turn_two

assert session["providerSessionId"] == "mock-provider-session", session
assert session["workingDirectory"] == str(bed), session
assert session["status"] == "WAITING", session
assert session["lastExitCode"] == 0, session
assert session["lastError"] == "", session

assert [row["direction"] for row in messages] == [
    "outgoing",
    "incoming",
    "outgoing",
    "incoming",
], messages
assert [row["body"] for row in messages] == [
    "first task\nwith detail",
    "MOCK: first task\nwith detail",
    "second task",
    "MOCK: second task",
], messages

types = [row["type"] for row in events]
assert types.count("turn.context") == 2, types
assert types.count("turn.started") == 2, types
assert types.count("turn.completed") == 2, types
assert types.count("provider.system") == 2, types
assert types.count("provider.text") == 2, types
assert types.count("provider.result") == 2, types

context_events = [row for row in events if row["type"] == "turn.context"]
assert context_events[0]["payload"]["patientChartEntryIds"] == [patient_chart["id"]], context_events
assert context_events[0]["payload"]["roomChartEntryIds"] == [room_chart["id"]], context_events
assert context_events[0]["payload"]["recentMessageIds"] == [], context_events
assert len(context_events[1]["payload"]["recentMessageIds"]) == 2, context_events

provider_system = [row["payload"] for row in events if row["type"] == "provider.system"]
assert all(row["hospital_context"] is True for row in provider_system), provider_system
assert all(row["patient_chart"] is True for row in provider_system), provider_system
assert all(row["room_chart"] is True for row in provider_system), provider_system
assert all(row["recent_transcript"] is True for row in provider_system), provider_system
PY

CANCEL_BED="$TMP/t8-bed"
mkdir -p "$CANCEL_BED"

"$ROOT/bin/px" hospital room-bind T8 \
    --repository kudokudo1/taskbars-post-apollo \
    --patient-id patient-taskbars \
    --patient-label TASKBARS \
    --team T8 \
    --branch feature/cancel-test \
    --bed-path "$CANCEL_BED" \
    --doctor-id doctor-t8 \
    --json >/dev/null

"$ROOT/bin/px" agent session-create \
    --room-id T8 \
    --doctor-id doctor-t8 \
    --provider-id mock \
    --working-directory "$CANCEL_BED" \
    --session-id session-t8-cancel \
    --json >/dev/null

(
    printf '%s\n' '{"prompt":"SLOW_TURN"}' | \
        "$ROOT/bin/px" agent turn session-t8-cancel \
            --prompt-json-stdin \
            --timeout 60 \
            --json
) >"$TMP/cancel-turn.json" 2>"$TMP/cancel-turn.err" &
turn_pid=$!

operating=false
for _ in $(seq 1 100); do
    status_json="$("$ROOT/bin/px" agent status session-t8-cancel --json)"
    if python3 - "$status_json" <<'PY'
import json
import sys
status = json.loads(sys.argv[1])
raise SystemExit(
    0
    if status["operating"] and status["activePid"] > 0
    else 1
)
PY
    then
        operating=true
        break
    fi
    sleep 0.05
done

if [[ "$operating" != true ]]; then
    printf 'agent turn never entered OPERATING state\n' >&2
    cat "$TMP/cancel-turn.err" >&2 || true
    kill "$turn_pid" 2>/dev/null || true
    wait "$turn_pid" 2>/dev/null || true
    exit 1
fi

cancel_json="$("$ROOT/bin/px" agent cancel session-t8-cancel --reason OPERATOR --json)"
wait "$turn_pid"

cancel_turn_json="$(cat "$TMP/cancel-turn.json")"
cancel_status_json="$("$ROOT/bin/px" agent status session-t8-cancel --json)"
cancel_events_json="$("$ROOT/bin/px" hospital events session-t8-cancel --limit 100 --json)"

python3 - \
    "$cancel_json" \
    "$cancel_turn_json" \
    "$cancel_status_json" \
    "$cancel_events_json" <<'PY'
import json
import sys

cancelled = json.loads(sys.argv[1])
turn = json.loads(sys.argv[2])
status = json.loads(sys.argv[3])
events = json.loads(sys.argv[4])

assert cancelled["cancelled"] is True, cancelled
assert cancelled["reason"] == "OPERATOR", cancelled
assert turn["cancelled"] is True, turn
assert turn["assistant"] == "", turn
assert status["status"] == "PAUSED", status
assert status["operating"] is False, status
assert status["activePid"] == 0, status
assert status["turnStartedAt"] == "", status
assert status["elapsedSeconds"] == 0, status
assert any(row["type"] == "turn.cancelled" for row in events), events
PY

quick_status_json="$("$ROOT/bin/px" agent quick session-t6-agent STATUS --json)"
printf 'change\n' >>"$BED/tracked.txt"
quick_report_json="$("$ROOT/bin/px" agent quick session-t6-agent REPORT --timeout 30 --json)"
quick_report_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["roomReport"]["id"])' "$quick_report_json")"
quick_suggest_json="$("$ROOT/bin/px" agent quick session-t6-agent SUGGEST --timeout 30 --json)"
quick_suggestions_json="$("$ROOT/bin/px" hospital chart-suggestions --scope ROOM --room-id T6 --status PENDING --json)"
feedback_json="$(printf '%s' 'The VERIFY section missed the regression test. Fix that and re-check the Room.' | "$ROOT/bin/px" agent report-feedback session-t6-agent "$quick_report_id" --feedback-stdin --timeout 30 --json)"
feedback_messages_json="$("$ROOT/bin/px" hospital messages T6 --limit 100 --json)"
feedback_events_json="$("$ROOT/bin/px" hospital events session-t6-agent --limit 400 --json)"

(
    printf '%s' 'SLOW_TURN' | \
        "$ROOT/bin/px" agent turn session-t6-agent \
            --prompt-stdin \
            --timeout 60 \
            --json
) >"$TMP/t6-slow-turn.json" 2>"$TMP/t6-slow-turn.err" &
t6_turn_pid=$!

t6_operating=false
for _ in $(seq 1 100); do
    t6_status_json="$("$ROOT/bin/px" agent status session-t6-agent --json)"
    if python3 - "$t6_status_json" <<'PY'
import json
import sys
status = json.loads(sys.argv[1])
raise SystemExit(
    0
    if status["operating"] and status["activePid"] > 0
    else 1
)
PY
    then
        t6_operating=true
        break
    fi
    sleep 0.05
done

if [[ "$t6_operating" != true ]]; then
    printf 'T6 guard turn never entered OPERATING state\n' >&2
    kill "$t6_turn_pid" 2>/dev/null || true
    wait "$t6_turn_pid" 2>/dev/null || true
    exit 1
fi

set +e
feedback_guard_output="$(printf '%s' 'This feedback must be refused while operating.' | \
    "$ROOT/bin/px" agent report-feedback \
        session-t6-agent \
        "$quick_report_id" \
        --feedback-stdin \
        --timeout 30 \
        --json 2>&1)"
feedback_guard_status=$?
set -e

if [[ "$feedback_guard_status" -eq 0 ]]; then
    printf 'expected report feedback concurrency guard to fail\n' >&2
    kill "$t6_turn_pid" 2>/dev/null || true
    wait "$t6_turn_pid" 2>/dev/null || true
    exit 1
fi

case "$feedback_guard_output" in
    *"already operating in this persistent session"*)
        ;;
    *)
        printf 'unexpected report feedback guard failure: %s\n' "$feedback_guard_output" >&2
        kill "$t6_turn_pid" 2>/dev/null || true
        wait "$t6_turn_pid" 2>/dev/null || true
        exit 1
        ;;
esac

"$ROOT/bin/px" agent cancel session-t6-agent --reason TEST_GUARD --json >/dev/null
wait "$t6_turn_pid"

quick_pause_json="$("$ROOT/bin/px" agent quick session-t6-agent PAUSE --json)"
quick_continue_json="$("$ROOT/bin/px" agent quick session-t6-agent CONTINUE --timeout 30 --json)"
quick_checkpoints_json="$("$ROOT/bin/px" hospital checkpoints T6 --limit 50 --json)"
quick_room_reports_json="$("$ROOT/bin/px" hospital room-reports T6 --limit 50 --json)"
quick_events_json="$("$ROOT/bin/px" hospital events session-t6-agent --limit 300 --json)"

python3 - \
    "$quick_status_json" \
    "$quick_report_json" \
    "$feedback_json" \
    "$feedback_messages_json" \
    "$feedback_events_json" \
    "$quick_pause_json" \
    "$quick_continue_json" \
    "$quick_checkpoints_json" \
    "$quick_room_reports_json" \
    "$quick_events_json" \
    "$quick_suggest_json" \
    "$quick_suggestions_json" <<'PY'
import json
import sys

status = json.loads(sys.argv[1])
report = json.loads(sys.argv[2])
feedback = json.loads(sys.argv[3])
feedback_messages = json.loads(sys.argv[4])
feedback_events = json.loads(sys.argv[5])
pause = json.loads(sys.argv[6])
continue_result = json.loads(sys.argv[7])
checkpoints = json.loads(sys.argv[8])
room_reports = json.loads(sys.argv[9])
events = json.loads(sys.argv[10])
suggest = json.loads(sys.argv[11])
suggestions = json.loads(sys.argv[12])

assert status["command"] == "STATUS", status
assert status["status"]["status"] == "WAITING", status

assert report["command"] == "REPORT", report
assert report["result"]["assistant"].startswith(
    "MOCK: QUICK // REPORT"
), report
assert report["result"]["providerSessionId"] == "mock-provider-session", report
assert report["result"]["assistantMessageId"], report
assert report["checkpoint"]["kind"] == "REQUESTED_REPORT", report
assert (
    report["checkpoint"]["sourceMessageId"]
    == report["result"]["assistantMessageId"]
), report
assert report["checkpoint"]["body"] == report["result"]["assistant"], report

for heading in (
    "## IMPLEMENTATION",
    "## HOW TO USE",
    "## VERIFY",
    "## WATCH OUT FOR",
    "## CHECKLIST",
    "## NEXT",
    "## DECISIONS",
):
    assert heading in report["result"]["assistant"], (heading, report)

room_report = report["roomReport"]
assert room_report["roomId"] == "T6", room_report
assert room_report["sessionId"] == "session-t6-agent", room_report
assert room_report["checkpointId"] == report["checkpoint"]["id"], room_report
assert room_report["sourceMessageId"] == report["result"]["assistantMessageId"], room_report
assert room_report["providerId"] == "mock", room_report
assert room_report["kind"] == "DOCTOR_NOTE", room_report
assert room_report["repository"] == "kudokudo1/taskbars-post-apollo", room_report
assert room_report["gitEvidenceStatus"] == "VERIFIED", room_report
assert room_report["dirty"] is True, room_report
assert room_report["changedFiles"] == ["tracked.txt"], room_report
assert room_report["changedFileCount"] == 1, room_report
assert room_report["insertions"] == 1, room_report
assert room_report["deletions"] == 0, room_report
assert len(room_report["headSha"]) == 40, room_report
assert room_report["branch"], room_report

assert report["gitEvidence"]["status"] == "VERIFIED", report
assert report["gitEvidence"]["changedFiles"] == ["tracked.txt"], report
assert report["gitEvidence"]["insertions"] == 1, report

assert feedback["report"]["id"] == room_report["id"], feedback
assert feedback["report"]["sessionId"] == "session-t6-agent", feedback
assert feedback["feedback"].startswith("The VERIFY section missed"), feedback
assert (
    feedback["result"]["providerSessionId"]
    == "mock-provider-session"
), feedback
assert feedback["result"]["session"]["status"] == "WAITING", feedback
assert feedback["result"]["assistant"] == (
    "MOCK: The VERIFY section missed the regression test. "
    "Fix that and re-check the Room."
), feedback

assert feedback_messages[-2]["direction"] == "outgoing", feedback_messages
assert feedback_messages[-2]["messageType"] == "report_feedback", feedback_messages
assert feedback_messages[-2]["body"] == (
    "The VERIFY section missed the regression test. "
    "Fix that and re-check the Room."
), feedback_messages
assert feedback_messages[-1]["direction"] == "incoming", feedback_messages
assert feedback_messages[-1]["body"] == feedback["result"]["assistant"], feedback_messages

feedback_types = [row["type"] for row in feedback_events]
assert "room_report.feedback.started" in feedback_types, feedback_types
assert "room_report.feedback.completed" in feedback_types, feedback_types
assert "turn.context" in feedback_types, feedback_types

feedback_provider_system = [
    row["payload"]
    for row in feedback_events
    if row["type"] == "provider.system"
]
assert any(
    row.get("supplemental_context") is True
    and row.get("report_feedback_context") is True
    for row in feedback_provider_system
), feedback_provider_system

assert len(checkpoints) == 1, checkpoints
assert checkpoints[0]["id"] == report["checkpoint"]["id"], checkpoints
assert checkpoints[0]["sessionId"] == "session-t6-agent", checkpoints
assert checkpoints[0]["providerId"] == "mock", checkpoints

assert len(room_reports) == 1, room_reports
assert room_reports[0]["id"] == room_report["id"], room_reports

types = [row["type"] for row in events]
assert "room_report.created" in types, types
assert "chart_suggestion.created" in types, types

assert suggest["command"] == "SUGGEST", suggest
memory = suggest["memorySuggestion"]
assert memory["status"] == "PENDING", memory
assert memory["scope"] == "ROOM", memory
assert memory["kind"] == "DECISION", memory
assert memory["priority"] == 82, memory
assert memory["doctorId"] == "doctor-t6", memory
assert memory["providerId"] == "mock", memory
assert memory["sourceSessionId"] == "session-t6-agent", memory
assert memory["sourceMessageId"] == suggest["result"]["assistantMessageId"], memory
assert len(suggestions) == 1, suggestions
assert suggestions[0]["id"] == memory["id"], suggestions

assert pause["command"] == "PAUSE", pause
assert pause["result"]["paused"] is True, pause
assert pause["result"]["session"]["status"] == "PAUSED", pause

assert continue_result["command"] == "CONTINUE", continue_result
assert continue_result["result"]["assistant"].startswith(
    "MOCK: QUICK // CONTINUE"
), continue_result
assert (
    continue_result["result"]["providerSessionId"]
    == "mock-provider-session"
), continue_result
assert continue_result["result"]["session"]["status"] == "WAITING", continue_result
PY

set +e
mismatch_output="$(printf '%s' 'FORCE_SESSION_MISMATCH' |     "$ROOT/bin/px" agent turn session-t6-agent         --prompt-stdin         --timeout 30         --json 2>&1)"
mismatch_status=$?
set -e

if [[ "$mismatch_status" -eq 0 ]]; then
    printf 'expected provider session mismatch to fail\n' >&2
    exit 1
fi

case "$mismatch_output" in
    *"provider resumed with a different session id"*)
        ;;
    *)
        printf 'unexpected mismatch failure: %s\n' "$mismatch_output" >&2
        exit 1
        ;;
esac

failed_session_json="$("$ROOT/bin/px" hospital session session-t6-agent --json)"

python3 - "$failed_session_json" <<'PY'
import json
import sys

session = json.loads(sys.argv[1])
assert session["status"] == "FAILED", session
assert "different session id" in session["lastError"], session
PY


cat > "$TMP/providers.json" <<EOF
{
  "version": 1,
  "providers": {
    "legacy": {
      "name": "LEGACY HERMES",
      "command": "python3",
      "dialect": "hermes-auto",
      "startArgs": [
        "$ROOT/tests/fixtures/mock-hermes-legacy.py",
        "chat"
      ],
      "resumeArgs": [
        "$ROOT/tests/fixtures/mock-hermes-legacy.py",
        "chat"
      ]
    }
  }
}
EOF

LEGACY_BED="$TMP/t7-bed"
mkdir -p "$LEGACY_BED"

"$ROOT/bin/px" hospital room-bind T7 \
    --repository kudokudo1/taskbars-post-apollo \
    --patient-id patient-taskbars \
    --patient-label TASKBARS \
    --team T7 \
    --branch feature/legacy-hermes \
    --bed-path "$LEGACY_BED" \
    --doctor-id doctor-t7 \
    --json >/dev/null

legacy_created_json="$("$ROOT/bin/px" agent session-create \
    --room-id T7 \
    --doctor-id doctor-t7 \
    --provider-id legacy \
    --working-directory "$LEGACY_BED" \
    --session-id session-t7-legacy \
    --json)"

legacy_one_json="$(printf '%s\n' '{"prompt":"legacy first"}' | \
    "$ROOT/bin/px" agent turn session-t7-legacy \
        --prompt-json-stdin \
        --timeout 30 \
        --json)"

legacy_two_json="$(printf '%s\n' '{"prompt":"legacy second"}' | \
    "$ROOT/bin/px" agent turn session-t7-legacy \
        --prompt-json-stdin \
        --timeout 30 \
        --json)"

legacy_session_json="$("$ROOT/bin/px" hospital session session-t7-legacy --json)"
legacy_messages_json="$("$ROOT/bin/px" hospital messages T7 --limit 100 --json)"

python3 - \
    "$legacy_created_json" \
    "$legacy_one_json" \
    "$legacy_two_json" \
    "$legacy_session_json" \
    "$legacy_messages_json" <<'PY'
import json
import sys

created = json.loads(sys.argv[1])
turn_one = json.loads(sys.argv[2])
turn_two = json.loads(sys.argv[3])
session = json.loads(sys.argv[4])
messages = json.loads(sys.argv[5])

assert created["providerId"] == "legacy", created
assert turn_one["assistant"] == "LEGACY: legacy first", turn_one
assert turn_one["providerSessionId"] == "legacy-provider-session", turn_one
assert turn_two["assistant"] == "LEGACY: legacy second", turn_two
assert turn_two["providerSessionId"] == "legacy-provider-session", turn_two
assert session["providerSessionId"] == "legacy-provider-session", session
assert session["status"] == "WAITING", session
assert [row["body"] for row in messages] == [
    "legacy first",
    "LEGACY: legacy first",
    "legacy second",
    "LEGACY: legacy second",
], messages
PY

printf 'hospital legacy Hermes compatibility: PASS\n'

printf 'hospital agent runtime: PASS\n'
