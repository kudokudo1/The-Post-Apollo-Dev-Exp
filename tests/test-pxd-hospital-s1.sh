#!/usr/bin/env bash
# Isolated PX S1 acceptance; disposable SQLite, Git and mock provider only.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export PX_HOSPITAL_DATA_DIR="$TMP/data"
export PX_AGENT_LOCK_DIR="$TMP/locks"
export PX_AGENT_AUTHORITY_DIR="$TMP/authority"
PX="$ROOT/bin/px"
BED="$TMP/bed"
mkdir -p "$BED"
git -C "$BED" init -q
git -C "$BED" config user.email hospital@example.invalid
git -C "$BED" config user.name "Hospital fixture"
printf 'baseline\n' > "$BED/tracked.txt"
git -C "$BED" add tracked.txt
git -C "$BED" commit -qm baseline
git -C "$BED" checkout -qb feature/s1
git -C "$BED" remote add origin https://github.com/kudokudo1/taskbars-post-apollo.git
cat >"$TMP/providers.json" <<EOF
{"version":1,"providers":{"mock":{
 "name":"MOCK","command":"python3","dialect":"hermes-stream-json",
 "startArgs":["$ROOT/tests/fixtures/mock-hermes-agent.py","chat","--format","stream-json","--query-file","-"],
 "resumeArgs":["$ROOT/tests/fixtures/mock-hermes-agent.py","chat","--resume","{provider_session_id}","--format","stream-json","--query-file","-"]
}}}
EOF
export PX_AGENT_PROVIDER_CONFIG="$TMP/providers.json"
"$PX" hospital init --json >/dev/null
"$PX" hospital room-bind S1 --repository kudokudo1/taskbars-post-apollo \
  --patient-id patient-test --team S1 --branch feature/s1 \
  --bed-path "$BED" --doctor-id doctor-s1 --json >/dev/null
"$PX" hospital room-bind OTHER --repository kudokudo1/taskbars-post-apollo \
  --patient-id patient-test --team OTHER --branch feature/other \
  --bed-path "$TMP/other-bed" --doctor-id doctor-other --json >/dev/null
created="$("$PX" hospital assignment-create --room-id S1 \
  --title "S1 test" --goal "Preserve Assignment continuity." \
  --permissions-json '["READ","EDIT","TEST"]' --json)"
aid="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["id"])' "$created")"
"$PX" hospital assignment-activate "$aid" --json >/dev/null
"$PX" hospital room-bind S1 --repository kudokudo1/taskbars-post-apollo \
  --patient-id patient-test --team S1 --branch feature/s1 \
  --bed-path "$BED" --doctor-id doctor-s1 --json >/dev/null
"$PX" hospital room-put S1 --patient-id patient-test --team S1 \
  --branch feature/s1 --bed-path "$BED" --doctor-id doctor-s1 --json >/dev/null
bound="$("$PX" hospital room S1 --json)"
python3 - "$bound" "$aid" <<'PY'
import json,sys
assert json.loads(sys.argv[1])["assignmentId"] == sys.argv[2]
PY
other="$("$PX" hospital assignment-create --room-id OTHER --title "Other" \
  --goal "Other Room only" --json)"
oid="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["id"])' "$other")"
"$PX" hospital assignment-activate "$oid" --json >/dev/null
if "$PX" hospital room-bind S1 --repository kudokudo1/taskbars-post-apollo \
  --patient-id patient-test --branch feature/s1 --bed-path "$BED" \
  --assignment-id "$oid" --json >/dev/null 2>&1; then
  echo 'FAIL: wrong-Room Assignment accepted' >&2; exit 1
fi
if "$PX" hospital room-put S1 --patient-id patient-test \
  --assignment-id "" --json >/dev/null 2>&1; then
  echo 'FAIL: empty Assignment cleared link' >&2; exit 1
fi

"$PX" agent session-create --room-id S1 --doctor-id doctor-s1 \
  --provider-id mock --working-directory "$BED" \
  --session-id session-s1 --json >/dev/null

# Each negative case must fail before the outbound message is appended.
"$PX" hospital room-bind S1 --repository kudokudo1/taskbars-post-apollo \
  --patient-id patient-test --branch feature/wrong \
  --bed-path "$BED" --doctor-id doctor-s1 --json >/dev/null
if printf BAD_BRANCH | "$PX" agent turn session-s1 --prompt-stdin \
  --timeout 30 --json >"$TMP/branch.out" 2>&1; then
  echo 'FAIL: wrong branch launched' >&2; exit 1
fi
grep -q TARGET_BRANCH_MISMATCH "$TMP/branch.out"

"$PX" hospital room-bind S1 --repository kudokudo1/taskbars-post-apollo \
  --patient-id patient-test --branch feature/s1 \
  --bed-path "$BED" --doctor-id doctor-s1 --json >/dev/null
mkdir "$TMP/override"
if printf BAD_OVERRIDE | "$PX" agent turn session-s1 --prompt-stdin \
  --working-directory "$TMP/override" --timeout 30 \
  --json >"$TMP/override.out" 2>&1; then
  echo 'FAIL: unregistered Bed launched' >&2; exit 1
fi
grep -q TARGET_BED_MISMATCH "$TMP/override.out"

git -C "$BED" remote set-url origin https://github.com/other-owner/wrong-repo.git
if printf BAD_REPO | "$PX" agent turn session-s1 --prompt-stdin \
  --timeout 30 --json >"$TMP/repo.out" 2>&1; then
  echo 'FAIL: wrong repository launched' >&2; exit 1
fi
grep -q PATIENT_REPOSITORY_MISMATCH "$TMP/repo.out"
messages="$("$PX" hospital messages S1 --json)"
python3 - "$messages" <<'PY'
import json,sys
assert json.loads(sys.argv[1]) == [], "A rejected turn wrote Room messages"
PY

git -C "$BED" remote set-url origin https://github.com/kudokudo1/taskbars-post-apollo.git
turn="$(printf MATCHING_TARGET | "$PX" agent turn session-s1 \
  --prompt-stdin --timeout 30 --json)"
python3 - "$turn" <<'PY'
import json,sys
outcome=json.loads(sys.argv[1])
assert outcome["operatorMessageId"] and outcome["assistantMessageId"],outcome
PY
"$PX" hospital assignment-status "$aid" CANCELLED --json >/dev/null
cleared="$("$PX" hospital room S1 --json)"
python3 - "$cleared" <<'PY'
import json,sys
assert json.loads(sys.argv[1])["assignmentId"] == ""
PY
echo 'PX Hospital S1 Assignment and execution-target regression: PASS'
