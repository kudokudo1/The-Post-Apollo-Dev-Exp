#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

printf 'dev\towner/repo\n' > "$tmp/repos.tsv"

cat > "$tmp/gh" <<'GH'
#!/usr/bin/env bash
set -euo pipefail


if [[ "${1:-} ${2:-}" == "workflow list" ]]; then
    state="${GH_WORKFLOW_STATE:-active}"
    printf '[{"id":77,"name":"PX / deploy","path":".github/workflows/deploy.yml","state":"%s"}]\n' "$state"
    exit 0
fi

if [[ "${1:-} ${2:-}" == "repo view" ]]; then
    printf 'main\n'
    exit 0
fi

if [[ "${1:-} ${2:-} ${3:-}" == "api --method DELETE" ]]; then
    endpoint="${4:-}"
    [[ "$endpoint" == "repos/owner/repo/contents/.github/workflows/deploy.yml" ]] || {
        printf 'unexpected delete endpoint: %s\n' "$endpoint" >&2
        exit 2
    }
    printf '{}\n'
    exit 0
fi

if [[ "${1:-} ${2:-} ${3:-}" == "api --method PUT" ]]; then
    endpoint="${4:-}"
    case "$endpoint" in
        repos/owner/repo/contents/.github/workflows/new-workflow.yml|repos/owner/repo/contents/.github/workflows/hospital-store.yml)
            printf 'cccccccccccccccccccccccccccccccccccccccc\n'
            exit 0
            ;;
        *)
            printf 'unexpected create endpoint: %s\n' "$endpoint" >&2
            exit 2
            ;;
    esac
fi

if [[ "${1:-}" == "api" ]]; then
    case "${2:-}" in
        repos/owner/repo/commits/main)
            if [[ -n "${GH_CREATE_STATE:-}" ]]; then
                case "${GH_CREATE_STATE}" in
                    base_moved|created|wrong_content)
                        printf 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
                        ;;
                    *)
                        printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n'
                        ;;
                esac
            else
                case "${GH_DELETE_STATE:-baseline}" in
                    deleted) printf 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n' ;;
                    *) printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' ;;
                esac
            fi
            exit 0
            ;;
        repos/owner/repo/contents/.github/workflows/deploy.yml?ref=main)
            case "${GH_DELETE_STATE:-baseline}" in
                deleted)
                    printf 'gh: Not Found (HTTP 404)\n' >&2
                    exit 1
                    ;;
                changed_blob)
                    blob='blob-deploy-changed'
                    ;;
                *)
                    blob='blob-deploy-main'
                    ;;
            esac

            for arg in "$@"; do
                if [[ "$arg" == "--jq" ]]; then
                    printf '%s\n' "$blob"
                    exit 0
                fi
            done

            printf '{"type":"file","sha":"%s"}\n' "$blob"
            exit 0
            ;;
        repos/owner/repo/contents/.github/workflows/new-workflow.yml?ref=main|repos/owner/repo/contents/.github/workflows/hospital-store.yml?ref=main)
            case "${GH_CREATE_STATE:-baseline}" in
                existing)
                    printf '%s\n' '{"type":"file","sha":"blob-existing","encoding":"base64","content":"ZXhpc3RpbmcK"}'
                    exit 0
                    ;;
                created)
                    printf '{"type":"file","sha":"blob-created","encoding":"base64","content":"%s"}\n' "${GH_CREATED_CONTENT_B64:-}"
                    exit 0
                    ;;
                wrong_content)
                    printf '%s\n' '{"type":"file","sha":"blob-created","encoding":"base64","content":"d3JvbmcK"}'
                    exit 0
                    ;;
                baseline|base_moved)
                    printf 'gh: Not Found (HTTP 404)\n' >&2
                    exit 1
                    ;;
                *)
                    printf 'unknown GH_CREATE_STATE: %s\n' "${GH_CREATE_STATE:-}" >&2
                    exit 2
                    ;;
            esac
            ;;
    esac
fi

if [[ "${1:-} ${2:-}" == "run list" ]]; then
    old='{"attempt":1,"databaseId":900,"workflowName":"PX / deploy","status":"completed","conclusion":"success","headBranch":"main","headSha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","event":"workflow_dispatch","createdAt":"2026-10-07T00:00:00Z","url":"https://example.invalid/run/900"}'
    new1='{"attempt":1,"databaseId":901,"workflowName":"PX / deploy","status":"queued","conclusion":"","headBranch":"main","headSha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","event":"workflow_dispatch","createdAt":"2026-10-07T00:01:00Z","url":"https://example.invalid/run/901"}'
    new2='{"attempt":1,"databaseId":902,"workflowName":"PX / deploy","status":"queued","conclusion":"","headBranch":"main","headSha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","event":"workflow_dispatch","createdAt":"2026-10-07T00:01:01Z","url":"https://example.invalid/run/902"}'

    case "${GH_DISPATCH_STATE:-baseline}" in
        baseline)
            printf '[%s]\n' "$old"
            ;;
        new_one)
            printf '[%s,%s]\n' "$old" "$new1"
            ;;
        new_two)
            printf '[%s,%s,%s]\n' "$old" "$new1" "$new2"
            ;;
        *)
            printf 'unknown GH_DISPATCH_STATE: %s\n' "${GH_DISPATCH_STATE:-}" >&2
            exit 2
            ;;
    esac
    exit 0
fi

if [[ "${1:-} ${2:-}" == "run view" ]]; then
    case "${GH_RUN_STATE:-in_progress}" in
        in_progress)
            printf '%s\n' '{"attempt":1,"databaseId":123,"workflowName":"PX / test","status":"in_progress","conclusion":"","headBranch":"main","headSha":"0123456789abcdef0123456789abcdef01234567","event":"workflow_dispatch","createdAt":"2026-10-07T00:00:00Z","startedAt":"2026-10-07T00:00:01Z","updatedAt":"2026-10-07T00:00:02Z","url":"https://example.invalid/run/123"}'
            ;;
        queued)
            printf '%s\n' '{"attempt":1,"databaseId":123,"workflowName":"PX / test","status":"queued","conclusion":"","headBranch":"main","headSha":"0123456789abcdef0123456789abcdef01234567","event":"workflow_dispatch","createdAt":"2026-10-07T00:00:00Z","startedAt":"","updatedAt":"2026-10-07T00:00:02Z","url":"https://example.invalid/run/123"}'
            ;;
        completed_cancelled)
            printf '%s\n' '{"attempt":1,"databaseId":123,"workflowName":"PX / test","status":"completed","conclusion":"cancelled","headBranch":"main","headSha":"0123456789abcdef0123456789abcdef01234567","event":"workflow_dispatch","createdAt":"2026-10-07T00:00:00Z","startedAt":"2026-10-07T00:00:01Z","updatedAt":"2026-10-07T00:00:10Z","url":"https://example.invalid/run/123"}'
            ;;
        completed_success)
            printf '%s\n' '{"attempt":1,"databaseId":123,"workflowName":"PX / test","status":"completed","conclusion":"success","headBranch":"main","headSha":"0123456789abcdef0123456789abcdef01234567","event":"workflow_dispatch","createdAt":"2026-10-07T00:00:00Z","startedAt":"2026-10-07T00:00:01Z","updatedAt":"2026-10-07T00:00:10Z","url":"https://example.invalid/run/123"}'
            ;;
        rerun_attempt2)
            printf '%s\n' '{"attempt":2,"databaseId":123,"workflowName":"PX / test","status":"queued","conclusion":"","headBranch":"main","headSha":"0123456789abcdef0123456789abcdef01234567","event":"workflow_dispatch","createdAt":"2026-10-07T00:00:00Z","startedAt":"","updatedAt":"2026-10-07T00:00:12Z","url":"https://example.invalid/run/123"}'
            ;;
        changed_head)
            printf '%s\n' '{"attempt":1,"databaseId":123,"workflowName":"PX / test","status":"in_progress","conclusion":"","headBranch":"main","headSha":"fedcba9876543210fedcba9876543210fedcba98","event":"workflow_dispatch","createdAt":"2026-10-07T00:00:00Z","startedAt":"2026-10-07T00:00:01Z","updatedAt":"2026-10-07T00:00:04Z","url":"https://example.invalid/run/123"}'
            ;;
        *)
            printf 'unknown GH_RUN_STATE: %s\n' "${GH_RUN_STATE:-}" >&2
            exit 2
            ;;
    esac
    exit 0
fi

printf 'unexpected gh call:' >&2
printf ' %q' "$@" >&2
printf '\n' >&2
exit 2
GH
chmod +x "$tmp/gh"

cat > "$tmp/actionlint" <<'ACTIONLINT'
#!/usr/bin/env bash
set -euo pipefail
[[ -n "${1:-}" ]] || exit 2
[[ -f "${1:-}" ]] || exit 2
exit 0
ACTIONLINT
chmod +x "$tmp/actionlint"

export PATH="$tmp:/usr/bin:/bin"
export PX_REPO_REGISTRY="$tmp/repos.tsv"
export PX_HOSPITAL_DATA_DIR="$tmp/hospital-data"

doctor_bed="$tmp/doctor-bed"
mkdir -p "$doctor_bed"

"$ROOT/bin/px" hospital init --json >/dev/null
"$ROOT/bin/px" hospital doctor-put doctor-ext \
    --name "TERM EXP Doctor" --role DOCTOR --status ACTIVE --json >/dev/null
"$ROOT/bin/px" hospital room-put room-ext \
    --team EXT --branch main --bed-path "$doctor_bed" \
    --doctor-id doctor-ext --provider-id mock --json >/dev/null
"$ROOT/bin/px" hospital session-put session-ext \
    --room-id room-ext --doctor-id doctor-ext --provider-id mock \
    --status WAITING --json >/dev/null
"$ROOT/bin/px" hospital session-runtime session-ext \
    --working-directory "$doctor_bed" --status WAITING --json >/dev/null

arguments='{"repository":"dev","run_id":"123"}'

export GH_RUN_STATE=in_progress
preflight="$("$ROOT/bin/px" mutation-preflight github.run.cancel "$arguments")"
jq -e '
  .version == 1
  and .actionId == "github.run.cancel"
  and .allowed == true
  and (.token | type == "string" and length > 0)
  and .target.databaseId == 123
  and .target.status == "in_progress"
  and (.summary | contains("CANCEL // PX / test // #123"))
' <<<"$preflight" >/dev/null

export GH_RUN_STATE=queued
queued="$("$ROOT/bin/px" mutation-preflight github.run.cancel "$arguments")"
jq -e '
  .allowed == true
  and .target.status == "queued"
  and .token == $token
' --arg token "$(jq -r '.token' <<<"$preflight")" <<<"$queued" >/dev/null

export GH_RUN_STATE=rerun_attempt2
cancel_attempt2="$("$ROOT/bin/px" mutation-preflight github.run.cancel "$arguments")"
[[ "$(jq -r '.token' <<<"$cancel_attempt2")" != "$(jq -r '.token' <<<"$preflight")" ]]

export GH_RUN_STATE=completed_success
completed="$("$ROOT/bin/px" mutation-preflight github.run.cancel "$arguments")"
jq -e '
  .allowed == false
  and (.reason | contains("RUN ALREADY COMPLETED"))
' <<<"$completed" >/dev/null

export GH_RUN_STATE=completed_cancelled
verified="$("$ROOT/bin/px" mutation-verify github.run.cancel "$arguments")"
jq -e '
  .passed == true
  and .target.status == "completed"
  and .target.conclusion == "cancelled"
  and (.summary | contains("CANCEL VERIFIED"))
' <<<"$verified" >/dev/null

export GH_RUN_STATE=completed_success
not_verified="$("$ROOT/bin/px" mutation-verify github.run.cancel "$arguments")"
jq -e '
  .passed == false
  and (.reason | contains("COMPLETED AS SUCCESS"))
' <<<"$not_verified" >/dev/null

export GH_RUN_STATE=in_progress
rerun_active="$("$ROOT/bin/px" mutation-preflight github.run.rerun "$arguments")"
jq -e '
  .allowed == false
  and (.reason | contains("MUST BE COMPLETED BEFORE RERUN"))
' <<<"$rerun_active" >/dev/null

export GH_RUN_STATE=completed_success
rerun_preflight="$("$ROOT/bin/px" mutation-preflight github.run.rerun "$arguments")"
rerun_token="$(jq -r '.token' <<<"$rerun_preflight")"
jq -e '
  .allowed == true
  and .target.attempt == 1
  and (.token | fromjson | .attempt) == 1
  and (.summary | contains("RERUN // PX / test // #123 // ATTEMPT 1"))
' <<<"$rerun_preflight" >/dev/null

export GH_RUN_STATE=rerun_attempt2
rerun_verified="$("$ROOT/bin/px" mutation-verify github.run.rerun "$arguments" "$rerun_token")"
jq -e '
  .passed == true
  and .target.attempt == 2
  and .target.status == "queued"
  and (.summary | contains("RERUN VERIFIED"))
' <<<"$rerun_verified" >/dev/null

dispatch_arguments='{"repository":"dev","workflow":".github/workflows/deploy.yml","ref":""}'

export GH_WORKFLOW_STATE=active
export GH_DISPATCH_STATE=baseline
dispatch_preflight="$("$ROOT/bin/px" mutation-preflight github.workflow.run "$dispatch_arguments")"
dispatch_token="$(jq -r '.token' <<<"$dispatch_preflight")"
jq -e '
  .allowed == true
  and .frozenCommand == ["run","owner/repo",".github/workflows/deploy.yml","main"]
  and (.token | fromjson | .workflowPath) == ".github/workflows/deploy.yml"
  and (.token | fromjson | .ref) == "main"
  and (.token | fromjson | .refSha) == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  and (.token | fromjson | .workflowBlobSha) == "blob-deploy-main"
  and (.token | fromjson | .beforeRunIds) == [900]
  and (.summary | contains("DISPATCH // PX / deploy"))
' <<<"$dispatch_preflight" >/dev/null

export GH_DISPATCH_STATE=new_one
dispatch_verified="$("$ROOT/bin/px" mutation-verify github.workflow.run "$dispatch_arguments" "$dispatch_token")"
jq -e '
  .passed == true
  and .target.databaseId == 901
  and .target.event == "workflow_dispatch"
  and (.summary | contains("DISPATCH VERIFIED"))
' <<<"$dispatch_verified" >/dev/null

export GH_DISPATCH_STATE=new_two
dispatch_ambiguous="$("$ROOT/bin/px" mutation-verify github.workflow.run "$dispatch_arguments" "$dispatch_token")"
jq -e '
  .passed == false
  and (.reason | contains("AMBIGUOUS"))
' <<<"$dispatch_ambiguous" >/dev/null

export GH_DISPATCH_STATE=baseline
export GH_WORKFLOW_STATE=disabled_manually
dispatch_disabled="$("$ROOT/bin/px" mutation-preflight github.workflow.run "$dispatch_arguments")"
jq -e '
  .allowed == false
  and (.reason | contains("WORKFLOW IS NOT ACTIVE"))
' <<<"$dispatch_disabled" >/dev/null

delete_arguments='{"repository":"dev","workflow_path":".github/workflows/deploy.yml","ref":""}'

export GH_DELETE_STATE=baseline
delete_preflight="$("$ROOT/bin/px" mutation-preflight workflow.delete "$delete_arguments")"
delete_token="$(jq -r '.token' <<<"$delete_preflight")"
jq -e '
  .allowed == true
  and .frozenCommand == [
    "delete-workflow",
    "owner/repo",
    ".github/workflows/deploy.yml",
    "main",
    "--expect-sha",
    "blob-deploy-main"
  ]
  and (.token | fromjson | .workflowPath) == ".github/workflows/deploy.yml"
  and (.token | fromjson | .workflowBlobSha) == "blob-deploy-main"
  and (.token | fromjson | .ref) == "main"
  and (.token | fromjson | .refSha) == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  and (.summary | contains("DELETE WORKFLOW"))
' <<<"$delete_preflight" >/dev/null

export GH_DELETE_STATE=changed_blob
delete_changed="$("$ROOT/bin/px" mutation-preflight workflow.delete "$delete_arguments")"
[[ "$(jq -r '.token' <<<"$delete_changed")" != "$delete_token" ]]

if "$ROOT/bin/px" delete-workflow dev .github/workflows/deploy.yml main --expect-sha blob-deploy-main >/dev/null 2>&1; then
    printf 'workflow delete unexpectedly accepted a changed blob SHA\n' >&2
    exit 1
fi

export GH_DELETE_STATE=baseline
"$ROOT/bin/px" delete-workflow dev .github/workflows/deploy.yml main --expect-sha blob-deploy-main >/dev/null

delete_still_present="$("$ROOT/bin/px" mutation-verify workflow.delete "$delete_arguments" "$delete_token")"
jq -e '
  .passed == false
  and .target.exists == true
  and (.reason | contains("WORKFLOW STILL EXISTS"))
' <<<"$delete_still_present" >/dev/null

export GH_DELETE_STATE=deleted
delete_verified="$("$ROOT/bin/px" mutation-verify workflow.delete "$delete_arguments" "$delete_token")"
jq -e '
  .passed == true
  and .target.exists == false
  and .target.previousBlobSha == "blob-deploy-main"
  and .target.previousRefSha == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  and .target.currentRefSha == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  and (.summary | contains("DELETE VERIFIED"))
' <<<"$delete_verified" >/dev/null

create_arguments='{"repository":"dev","template":"smoke","slug":"new-workflow","trigger":"manual","script_path":""}'

unset GH_DELETE_STATE
export GH_CREATE_STATE=baseline
create_preflight="$("$ROOT/bin/px" mutation-preflight workflow.create "$create_arguments")"
create_token="$(jq -r '.token' <<<"$create_preflight")"
create_yaml_sha="$(jq -r '.token | fromjson | .yamlSha' <<<"$create_preflight")"
create_yaml_b64="$(jq -r '.token | fromjson | .yamlBase64' <<<"$create_preflight")"

jq -e '
  .allowed == true
  and .target.workflowPath == ".github/workflows/new-workflow.yml"
  and .target.validation.status == "pass"
  and (.token | fromjson | .base) == "main"
  and (.token | fromjson | .baseSha) == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  and (.token | fromjson | .yamlSha | length) == 64
  and .frozenCommand[0:5] == ["create","owner/repo","smoke","new-workflow","manual"]
  and (.frozenCommand | index("--install")) != null
  and (.frozenCommand | index("--json")) != null
  and (.frozenCommand | index("--expect-base=main")) != null
  and (.frozenCommand | index("--expect-base-sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")) != null
  and (.summary | contains("CREATE WORKFLOW"))
' <<<"$create_preflight" >/dev/null

export GH_CREATE_STATE=existing
create_existing="$("$ROOT/bin/px" mutation-preflight workflow.create "$create_arguments")"
jq -e '
  .allowed == false
  and (.reason | contains("TARGET ALREADY EXISTS"))
' <<<"$create_existing" >/dev/null

export GH_CREATE_STATE=base_moved
create_moved="$("$ROOT/bin/px" mutation-preflight workflow.create "$create_arguments")"
[[ "$(jq -r '.token' <<<"$create_moved")" != "$create_token" ]]

if "$ROOT/bin/px" create owner/repo smoke new-workflow manual \
    --install --json \
    --expect-base=main \
    --expect-base-sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    --expect-yaml-sha="$create_yaml_sha" >/dev/null 2>&1; then
    printf 'workflow create unexpectedly accepted a moved base SHA\n' >&2
    exit 1
fi

export GH_CREATE_STATE=baseline
create_install="$("$ROOT/bin/px" create owner/repo smoke new-workflow manual \
    --install --json \
    --expect-base=main \
    --expect-base-sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    --expect-yaml-sha="$create_yaml_sha")"
jq -e '
  .install.requested == true
  and .install.installed == true
  and .install.branch == "main"
  and .install.commit == "cccccccccccccccccccccccccccccccccccccccc"
' <<<"$create_install" >/dev/null

export GH_CREATED_CONTENT_B64="$create_yaml_b64"
export GH_CREATE_STATE=created
create_verified="$("$ROOT/bin/px" mutation-verify workflow.create "$create_arguments" "$create_token")"
jq -e '
  .passed == true
  and .target.workflowPath == ".github/workflows/new-workflow.yml"
  and .target.previousBaseSha == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  and .target.currentBaseSha == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  and .target.remoteYamlSha == .target.expectedYamlSha
  and (.summary | contains("CREATE VERIFIED"))
' <<<"$create_verified" >/dev/null

export GH_CREATE_STATE=wrong_content
create_wrong="$("$ROOT/bin/px" mutation-verify workflow.create "$create_arguments" "$create_token")"
jq -e '
  .passed == false
  and (.reason | contains("CONTENT DOES NOT MATCH FROZEN YAML"))
' <<<"$create_wrong" >/dev/null

script_arguments='{"repository":"dev","template":"script-test","slug":"hospital-store","trigger":"manual","script_path":"tests/test-px-hospital-store.sh"}'
export GH_CREATE_STATE=baseline
script_preflight="$("$ROOT/bin/px" mutation-preflight workflow.create "$script_arguments")"
jq -e '
  .allowed == true
  and (.frozenCommand | index("--script=tests/test-px-hospital-store.sh")) != null
  and (.token | fromjson | .scriptPath) == "tests/test-px-hospital-store.sh"
' <<<"$script_preflight" >/dev/null

external_arguments='{"session_id":"session-ext","prompt":"Inspect the selected Room and report the next safe action."}'

external_preflight="$("$ROOT/bin/px" mutation-preflight ai.turn "$external_arguments")"
external_token="$(jq -r '.token' <<<"$external_preflight")"
jq -e '
  .allowed == true
  and .frozenCommand == [
    "agent",
    "turn",
    "session-ext",
    "--prompt",
    "Inspect the selected Room and report the next safe action.",
    "--json"
  ]
  and (.token | fromjson | .roomId) == "room-ext"
  and (.token | fromjson | .doctorId) == "doctor-ext"
  and (.token | fromjson | .providerId) == "mock"
  and (.token | fromjson | .baselineEventId) == 0
  and (.summary | contains("MESSAGE DOCTOR"))
' <<<"$external_preflight" >/dev/null

"$ROOT/bin/px" hospital session-runtime session-ext \
    --status OPERATING --active-pid 4242 --json >/dev/null
external_busy="$("$ROOT/bin/px" mutation-preflight ai.turn "$external_arguments")"
jq -e '
  .allowed == false
  and (.reason | contains("DOCTOR ALREADY OPERATING"))
' <<<"$external_busy" >/dev/null

"$ROOT/bin/px" hospital session-runtime session-ext \
    --status WAITING --clear-active-pid --clear-turn-started --json >/dev/null
external_preflight="$("$ROOT/bin/px" mutation-preflight ai.turn "$external_arguments")"
external_token="$(jq -r '.token' <<<"$external_preflight")"

"$ROOT/bin/px" hospital event-append \
    --session-id session-ext --event-type turn.started --payload '{}' --json >/dev/null
"$ROOT/bin/px" hospital event-append \
    --session-id session-ext --event-type turn.completed --payload '{"exitCode":0}' --json >/dev/null

external_verified="$("$ROOT/bin/px" mutation-verify ai.turn "$external_arguments" "$external_token")"
jq -e '
  .passed == true
  and .target.session.status == "WAITING"
  and .target.counts.started == 1
  and .target.counts.completed == 1
  and .target.counts.failed == 0
  and .target.counts.cancelled == 0
  and (.summary | contains("MESSAGE DOCTOR VERIFIED"))
' <<<"$external_verified" >/dev/null

ambiguous_preflight="$("$ROOT/bin/px" mutation-preflight ai.turn "$external_arguments")"
ambiguous_token="$(jq -r '.token' <<<"$ambiguous_preflight")"
for _ in 1 2; do
    "$ROOT/bin/px" hospital event-append \
        --session-id session-ext --event-type turn.started --payload '{}' --json >/dev/null
    "$ROOT/bin/px" hospital event-append \
        --session-id session-ext --event-type turn.completed --payload '{"exitCode":0}' --json >/dev/null
done

external_ambiguous="$("$ROOT/bin/px" mutation-verify ai.turn "$external_arguments" "$ambiguous_token")"
jq -e '
  .passed == false
  and (.reason | contains("ACTIVITY IS AMBIGUOUS"))
  and .target.counts.started == 2
  and .target.counts.completed == 2
' <<<"$external_ambiguous" >/dev/null

report_arguments='{"session_id":"session-ext"}'
report_preflight="$("$ROOT/bin/px" mutation-preflight ai.quick.report "$report_arguments")"
report_token="$(jq -r '.token' <<<"$report_preflight")"
jq -e '
  .allowed == true
  and .frozenCommand == ["agent","quick","session-ext","REPORT","--json"]
  and (.summary | contains("QUICK REPORT"))
' <<<"$report_preflight" >/dev/null

"$ROOT/bin/px" hospital event-append \
    --session-id session-ext --event-type turn.started --payload '{}' --json >/dev/null
"$ROOT/bin/px" hospital event-append \
    --session-id session-ext --event-type turn.completed --payload '{"exitCode":0}' --json >/dev/null
"$ROOT/bin/px" hospital event-append \
    --session-id session-ext --event-type checkpoint.created --payload '{"checkpointId":"1"}' --json >/dev/null
"$ROOT/bin/px" hospital event-append \
    --session-id session-ext --event-type room_report.created --payload '{"reportId":"1"}' --json >/dev/null

report_verified="$("$ROOT/bin/px" mutation-verify ai.quick.report "$report_arguments" "$report_token")"
jq -e '
  .passed == true
  and .target.counts.started == 1
  and .target.counts.completed == 1
  and .target.counts.checkpoints == 1
  and .target.counts.reports == 1
  and (.summary | contains("QUICK REPORT VERIFIED"))
' <<<"$report_verified" >/dev/null

report_missing_preflight="$("$ROOT/bin/px" mutation-preflight ai.quick.report "$report_arguments")"
report_missing_token="$(jq -r '.token' <<<"$report_missing_preflight")"
"$ROOT/bin/px" hospital event-append \
    --session-id session-ext --event-type turn.started --payload '{}' --json >/dev/null
"$ROOT/bin/px" hospital event-append \
    --session-id session-ext --event-type turn.completed --payload '{"exitCode":0}' --json >/dev/null

report_missing="$("$ROOT/bin/px" mutation-verify ai.quick.report "$report_arguments" "$report_missing_token")"
jq -e '
  .passed == false
  and (.reason | contains("CHECKPOINT AND ROOM REPORT"))
' <<<"$report_missing" >/dev/null

printf 'PX guarded mutation self-test: PASS\n'
