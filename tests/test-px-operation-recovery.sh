#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export PX_OPERATION_DB="$TMP/operations.db"
export PX_REPO_REGISTRY="$TMP/repos.tsv"
export GH_RECOVERY_STATE_FILE="$TMP/remote-state"
export GH_RECOVERY_MODE="good"

cat >"$PX_REPO_REGISTRY" <<'EOF'
dev	owner/repo
EOF

yaml_text=$'name: recoverable\non:\n  workflow_dispatch:\n'
export GH_RECOVERY_YAML_B64="$(printf '%s' "$yaml_text" | base64 | tr -d '\n')"
yaml_sha="$(printf '%s' "$yaml_text" | sha256sum | awk '{print $1}')"

install_commit="1111111111111111111111111111111111111111"
verified_head="2222222222222222222222222222222222222222"
live_head="3333333333333333333333333333333333333333"
delete_commit="4444444444444444444444444444444444444444"
after_head="5555555555555555555555555555555555555555"
recorded_blob="blob-recoverable"

printf 'present\n' >"$GH_RECOVERY_STATE_FILE"

cat >"$TMP/gh" <<'GH'
#!/usr/bin/env bash
set -euo pipefail

state_file="${GH_RECOVERY_STATE_FILE:?}"
mode="${GH_RECOVERY_MODE:-good}"
yaml_b64="${GH_RECOVERY_YAML_B64:?}"

if [[ "${1:-}" != "api" ]]; then
    printf 'unsupported gh invocation: %s\n' "$*" >&2
    exit 2
fi
shift

if [[ "${1:-}" == "--method" && "${2:-}" == "DELETE" ]]; then
    endpoint="${3:-}"
    [[ "$endpoint" == "repos/owner/repo/contents/.github/workflows/recoverable.yml" ]] || {
        printf 'unexpected delete endpoint: %s\n' "$endpoint" >&2
        exit 2
    }
    [[ "$(cat "$state_file")" == "present" ]] || {
        printf 'gh: Not Found (HTTP 404)\n' >&2
        exit 1
    }

    expected_sha=""
    for arg in "$@"; do
        case "$arg" in
            sha=*) expected_sha="${arg#sha=}" ;;
        esac
    done
    [[ "$expected_sha" == "blob-recoverable" ]] || {
        printf 'unexpected delete sha: %s\n' "$expected_sha" >&2
        exit 2
    }

    printf 'deleted\n' >"$state_file"
    printf '%s\n' '{"commit":{"sha":"4444444444444444444444444444444444444444"}}'
    exit 0
fi

endpoint="${1:-}"

case "$endpoint" in
    repos/owner/repo/contents/.github/workflows/recoverable.yml?ref=main)
        if [[ "$(cat "$state_file")" == "deleted" ]]; then
            printf 'gh: Not Found (HTTP 404)\n' >&2
            exit 1
        fi

        blob="blob-recoverable"
        content="$yaml_b64"
        if [[ "$mode" == "stale_blob" ]]; then
            blob="blob-changed"
            content="d3JvbmcK"
        fi

        if [[ "${2:-}" == "--jq" ]]; then
            case "${3:-}" in
                .sha) printf '%s\n' "$blob" ;;
                *) printf 'unsupported jq: %s\n' "${3:-}" >&2; exit 2 ;;
            esac
        else
            printf '{"type":"file","sha":"%s","encoding":"base64","content":"%s"}\n' "$blob" "$content"
        fi
        ;;
    repos/owner/repo/commits/main)
        if [[ "$(cat "$state_file")" == "deleted" ]]; then
            printf '5555555555555555555555555555555555555555\n'
        else
            printf '3333333333333333333333333333333333333333\n'
        fi
        ;;
    repos/owner/repo/compare/2222222222222222222222222222222222222222...3333333333333333333333333333333333333333)
        if [[ "$mode" == "diverged" ]]; then
            printf 'diverged\n'
        else
            printf 'ahead\n'
        fi
        ;;
    repos/owner/repo/compare/1111111111111111111111111111111111111111...3333333333333333333333333333333333333333)
        printf 'ahead\n'
        ;;
    repos/owner/repo/compare/3333333333333333333333333333333333333333...5555555555555555555555555555555555555555)
        printf 'ahead\n'
        ;;
    repos/owner/repo/compare/4444444444444444444444444444444444444444...5555555555555555555555555555555555555555)
        printf 'identical\n'
        ;;
    *)
        printf 'unsupported gh api endpoint: %s\n' "$endpoint" >&2
        exit 2
        ;;
esac
GH
chmod +x "$TMP/gh"
export PATH="$TMP:/usr/bin:/bin"

create_source_operation() {
    local slug="$1"
    local path=".github/workflows/recoverable.yml"
    local started source_id after verification

    started="$("$ROOT/bin/px" operation start \
        --action-id workflow.create \
        --title "Create Workflow" \
        --mutation remote \
        --recovery CONTENT_RECOVERABLE \
        --command-json '["create","owner/repo","smoke","recoverable","manual","--install","--json"]' \
        --arguments-json '{"repository":"dev","template":"smoke","slug":"recoverable"}' \
        --before-json '{"armed":true,"preflight":"CREATE WORKFLOW"}' \
        --json)"
    source_id="$(jq -r '.id' <<<"$started")"

    after="$(jq -nc \
        --arg repository "owner/repo" \
        --arg base "main" \
        --arg path "$path" \
        --arg yaml "$yaml_text" \
        --arg commit "$install_commit" \
        '{
            stdout:{
                repository:$repository,
                base:$base,
                path:$path,
                yaml:$yaml,
                install:{installed:true,commit:$commit}
            },
            stderr:""
        }')"
    verification="$(jq -nc \
        --arg blob "$recorded_blob" \
        --arg head "$verified_head" \
        --arg yamlSha "$yaml_sha" \
        '{
            passed:true,
            target:{
                remoteBlobSha:$blob,
                currentBaseSha:$head,
                expectedYamlSha:$yamlSha
            }
        }')"

    "$ROOT/bin/px" operation finish "$source_id" \
        --status COMPLETE \
        --exit-code 0 \
        --verification-status PASSED \
        --after-json "$after" \
        --verification-json "$verification" \
        --result-summary "workflow creation verified" \
        --json >/dev/null

    printf '%s\n' "$source_id"
}

source_id="$(create_source_operation good)"
facts="$("$ROOT/bin/px" operation recovery "$source_id" --json)"
jq -e '
  .strategy == "DELETE_CREATED_WORKFLOW"
  and .planAvailable == true
  and .executorAvailable == true
  and .requiresLiveValidation == true
  and .automaticRecoveryAvailable == false
  and .executionCommand[0:2] == ["operation","recover"]
' <<<"$facts" >/dev/null

result="$("$ROOT/bin/px" operation recover "$source_id" --json)"
recovery_id="$(jq -r '.recoveryOperationId' <<<"$result")"
jq -e \
  --arg source "$source_id" \
  --arg recovery "$recovery_id" '
  .recovered == true
  and .operationId == $source
  and .recoveryOperationId == $recovery
  and .strategy == "DELETE_CREATED_WORKFLOW"
  and .verification == "PASSED"
  and .deleteCommit == "4444444444444444444444444444444444444444"
  and .previousHead == "3333333333333333333333333333333333333333"
  and .currentHead == "5555555555555555555555555555555555555555"
' <<<"$result" >/dev/null

recovery_record="$("$ROOT/bin/px" operation get "$recovery_id" --json)"
jq -e \
  --arg source "$source_id" '
  .actionId == "px.operation.recover.workflow.create"
  and .mutation == "remote"
  and .recovery == "EVIDENCE_ONLY"
  and .status == "COMPLETE"
  and .verificationStatus == "PASSED"
  and .arguments.sourceOperationId == $source
  and .before.strategy == "DELETE_CREATED_WORKFLOW"
  and .before.live.blobSha == "blob-recoverable"
  and .command == [
    "delete-workflow",
    "owner/repo",
    ".github/workflows/recoverable.yml",
    "main",
    "--expect-sha",
    "blob-recoverable",
    "--json"
  ]
  and .verification.fileAbsent == true
' <<<"$recovery_record" >/dev/null

set +e
repeat_output="$("$ROOT/bin/px" operation recover "$source_id" --json 2>&1)"
repeat_status=$?
set -e
[[ "$repeat_status" -ne 0 ]]
jq -e '
  .recovered == false
  and (.reason | contains("target is unavailable"))
' <<<"$repeat_output" >/dev/null

printf 'present\n' >"$GH_RECOVERY_STATE_FILE"
export GH_RECOVERY_MODE="stale_blob"
stale_id="$(create_source_operation stale)"
before_count="$("$ROOT/bin/px" operations --json | jq 'length')"
set +e
stale_output="$("$ROOT/bin/px" operation recover "$stale_id" --json 2>&1)"
stale_status=$?
set -e
after_count="$("$ROOT/bin/px" operations --json | jq 'length')"
[[ "$stale_status" -ne 0 ]]
[[ "$before_count" == "$after_count" ]]
jq -e '
  .recovered == false
  and (.reason | contains("workflow content changed"))
' <<<"$stale_output" >/dev/null

printf 'present\n' >"$GH_RECOVERY_STATE_FILE"
export GH_RECOVERY_MODE="diverged"
diverged_id="$(create_source_operation diverged)"
before_count="$("$ROOT/bin/px" operations --json | jq 'length')"
set +e
diverged_output="$("$ROOT/bin/px" operation recover "$diverged_id" --json 2>&1)"
diverged_status=$?
set -e
after_count="$("$ROOT/bin/px" operations --json | jq 'length')"
[[ "$diverged_status" -ne 0 ]]
[[ "$before_count" == "$after_count" ]]
jq -e '
  .recovered == false
  and (.reason | contains("base history diverged"))
' <<<"$diverged_output" >/dev/null

printf 'PX workflow creation recovery executor: PASS\n'
