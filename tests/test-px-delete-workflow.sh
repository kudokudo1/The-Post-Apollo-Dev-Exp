#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

printf 'dev\towner/repo\n' > "$tmp/repos.tsv"

cat > "$tmp/gh" <<'GH'
#!/usr/bin/env bash
set -euo pipefail

: "${GH_LOG_FILE:?GH_LOG_FILE required}"
{
    printf 'CALL'
    printf '\t%s' "$@"
    printf '\n'
} >> "$GH_LOG_FILE"

if [[ "${1:-} ${2:-}" == "repo view" ]]; then
    printf 'main\n'
    exit 0
fi

if [[ "${1:-}" == "api" && "${2:-}" == repos/owner/repo/contents/.github/workflows/old-check.yml?ref=* ]]; then
    printf '{"type":"file","sha":"abc123"}\n'
    exit 0
fi

if [[ "${1:-} ${2:-} ${3:-}" == "api --method DELETE" ]]; then
    printf '{}\n'
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
export GH_LOG_FILE="$tmp/gh.log"

: > "$GH_LOG_FILE"
output="$("$ROOT/bin/px" delete-workflow dev .github/workflows/old-check.yml)"
grep -q '^deleted workflow: .github/workflows/old-check.yml @ main$' <<<"$output"

grep -Fq $'CALL\trepo\tview\towner/repo\t--json\tdefaultBranchRef\t--jq\t.defaultBranchRef.name' "$GH_LOG_FILE"
grep -Fq $'CALL\tapi\trepos/owner/repo/contents/.github/workflows/old-check.yml?ref=main' "$GH_LOG_FILE"
grep -Fq $'CALL\tapi\t--method\tDELETE\trepos/owner/repo/contents/.github/workflows/old-check.yml\t-f\tmessage=Delete workflow .github/workflows/old-check.yml\t-f\tsha=abc123\t-f\tbranch=main' "$GH_LOG_FILE"

: > "$GH_LOG_FILE"
output="$("$ROOT/bin/px" delete-workflow dev .github/workflows/old-check.yml release)"
grep -q '^deleted workflow: .github/workflows/old-check.yml @ release$' <<<"$output"

if grep -Fq $'CALL\trepo\tview' "$GH_LOG_FILE"; then
    printf 'explicit ref unexpectedly queried default branch\n' >&2
    exit 1
fi

grep -Fq $'CALL\tapi\trepos/owner/repo/contents/.github/workflows/old-check.yml?ref=release' "$GH_LOG_FILE"
grep -Fq $'\t-f\tbranch=release' "$GH_LOG_FILE"

if "$ROOT/bin/px" delete-workflow dev README.md >/dev/null 2>&1; then
    printf 'non-workflow path unexpectedly succeeded\n' >&2
    exit 1
fi

if "$ROOT/bin/px" delete-workflow dev .github/workflows/../evil.yml >/dev/null 2>&1; then
    printf 'parent traversal unexpectedly succeeded\n' >&2
    exit 1
fi

printf 'PX workflow deletion self-test: PASS\n'
