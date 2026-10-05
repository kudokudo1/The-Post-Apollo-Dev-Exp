#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

printf 'dev\towner/repo\n' > "$tmp/repos.tsv"

cat > "$tmp/gh" <<'GH'
#!/usr/bin/env bash
set -euo pipefail

: "${GH_ARGS_FILE:?GH_ARGS_FILE required}"
printf '%s\n' "$@" > "$GH_ARGS_FILE"

if [[ "${1:-} ${2:-}" == "run list" ]]; then
    printf '[{"databaseId":123,"workflowName":"PX / test","status":"completed","conclusion":"success","headBranch":"main","headSha":"0123456789abcdef0123456789abcdef01234567","createdAt":"2026-10-05T00:00:00Z"}]\n'
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
export GH_ARGS_FILE="$tmp/gh-args"

expected_sha="0123456789abcdef0123456789abcdef01234567"

normal="$("$ROOT/bin/px" runs dev 7)"
grep -q "\"headSha\":\"$expected_sha\"" <<<"$normal"

mapfile -t normal_args < "$GH_ARGS_FILE"
expected_normal=(
    run list
    -R owner/repo
    --limit 7
    --json databaseId,workflowName,status,conclusion,headBranch,headSha,createdAt
)

[[ "${#normal_args[@]}" -eq "${#expected_normal[@]}" ]]
for i in "${!expected_normal[@]}"; do
    [[ "${normal_args[$i]}" == "${expected_normal[$i]}" ]]
done

exact="$("$ROOT/bin/px" runs dev 100 "$expected_sha")"
grep -q "\"headSha\":\"$expected_sha\"" <<<"$exact"

mapfile -t exact_args < "$GH_ARGS_FILE"
expected_exact=(
    run list
    -R owner/repo
    --limit 100
    --commit "$expected_sha"
    --json databaseId,workflowName,status,conclusion,headBranch,headSha,createdAt
)

[[ "${#exact_args[@]}" -eq "${#expected_exact[@]}" ]]
for i in "${!expected_exact[@]}"; do
    [[ "${exact_args[$i]}" == "${expected_exact[$i]}" ]]
done

printf 'PX run evidence self-test: PASS\n'
