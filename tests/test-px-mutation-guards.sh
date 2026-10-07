#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

printf 'dev\towner/repo\n' > "$tmp/repos.tsv"

cat > "$tmp/gh" <<'GH'
#!/usr/bin/env bash
set -euo pipefail

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

export PATH="$tmp:/usr/bin:/bin"
export PX_REPO_REGISTRY="$tmp/repos.tsv"

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

if "$ROOT/bin/px" mutation-preflight github.workflow.run "$arguments" >/dev/null 2>&1; then
    printf 'uncertified workflow dispatch unexpectedly received a mutation preflight policy\n' >&2
    exit 1
fi

printf 'PX guarded mutation self-test: PASS\n'
