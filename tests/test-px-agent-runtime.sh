#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export PX_HOSPITAL_DATA_DIR="$TMP/hospital-data"
BED="$TMP/t6-bed"
mkdir -p "$BED"

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

providers_json="$("$ROOT/bin/px" agent providers --json)"
created_json="$("$ROOT/bin/px" agent session-create     --room-id T6     --doctor-id doctor-t6     --provider-id mock     --working-directory "$BED"     --session-id session-t6-agent     --json)"

turn_one_frame="$(python3 -c 'import json; print(json.dumps({"prompt": "first task\nwith detail"}))')"
turn_one_json="$(printf '%s\n' "$turn_one_frame" | "$ROOT/bin/px" agent turn session-t6-agent --prompt-json-stdin --timeout 30 --json)"

turn_two_json="$(printf '%s' 'second task' |     "$ROOT/bin/px" agent turn session-t6-agent         --prompt-stdin         --timeout 30         --json)"

session_json="$("$ROOT/bin/px" hospital session session-t6-agent --json)"
messages_json="$("$ROOT/bin/px" hospital messages T6 --limit 100 --json)"
events_json="$("$ROOT/bin/px" hospital events session-t6-agent --limit 200 --json)"

python3 -     "$providers_json"     "$created_json"     "$turn_one_json"     "$turn_two_json"     "$session_json"     "$messages_json"     "$events_json"     "$BED" <<'PY'
import json
import pathlib
import sys

providers = json.loads(sys.argv[1])
created = json.loads(sys.argv[2])
turn_one = json.loads(sys.argv[3])
turn_two = json.loads(sys.argv[4])
session = json.loads(sys.argv[5])
messages = json.loads(sys.argv[6])
events = json.loads(sys.argv[7])
bed = pathlib.Path(sys.argv[8])

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

assert turn_one["assistant"] == "MOCK: first task\nwith detail", turn_one
assert turn_one["providerSessionId"] == "mock-provider-session", turn_one
assert turn_two["assistant"] == "MOCK: second task", turn_two
assert turn_two["providerSessionId"] == "mock-provider-session", turn_two

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
assert types.count("turn.started") == 2, types
assert types.count("turn.completed") == 2, types
assert types.count("provider.system") == 2, types
assert types.count("provider.text") == 2, types
assert types.count("provider.result") == 2, types
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
