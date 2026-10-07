#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

printf 'dev\towner/repo\n' > "$tmp/repos.tsv"

cat > "$tmp/gh" <<'GH'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-} ${2:-}" == "repo view" ]]; then
    printf 'main\n'
    exit 0
fi

if [[ "${1:-} ${2:-}" == "workflow list" ]]; then
    printf 'no workflows found\n' >&2
    exit 1
fi

printf 'unexpected gh call:' >&2
printf ' %q' "$@" >&2
printf '\n' >&2
exit 2
GH
chmod +x "$tmp/gh"

export PATH="$tmp:/usr/bin:/bin"
export PX_REPO_REGISTRY="$tmp/repos.tsv"

"$ROOT/bin/px" templates | grep -q '"id": "smoke"'
"$ROOT/bin/px" templates | grep -q '"id": "shell-check"'
"$ROOT/bin/px" templates | grep -q '"id": "script-test"'

empty_workflows="$("$ROOT/bin/px" workflows owner/repo)"
[[ "$empty_workflows" == "[]" ]]

preview="$("$ROOT/bin/px" create dev smoke hello-world manual --preview 2>/dev/null)"
grep -q '^PX WORKFLOW CANDIDATE$' <<<"$preview"
grep -q '^path: .github/workflows/hello-world.yml$' <<<"$preview"
grep -q '^  workflow_dispatch:$' <<<"$preview"
grep -q '^preview only: no repository changes made$' <<<"$preview"

push_preview="$("$ROOT/bin/px" create dev shell-check shell-syntax manual+push --preview 2>/dev/null)"
grep -q '^  push:$' <<<"$push_preview"
grep -q '^      - main$' <<<"$push_preview"
grep -q "find . -type f -name '\\*.sh'" <<<"$push_preview"


script_preview="$("$ROOT/bin/px" create dev script-test hospital-store manual --script=tests/test-px-hospital-store.sh --preview --json)"
jq -e '
  .template == "script-test" and
  .slug == "hospital-store" and
  .script == "tests/test-px-hospital-store.sh" and
  (.yaml | contains("run: bash \"tests/test-px-hospital-store.sh\""))
' <<<"$script_preview" >/dev/null

if "$ROOT/bin/px" create dev script-test bad-script manual --script=../outside.sh --preview >/dev/null 2>&1; then
    printf 'unsafe script path unexpectedly succeeded\n' >&2
    exit 1
fi


direct_preview="$("$ROOT/bin/px" create owner/repo smoke direct-repo manual --preview --json)"
jq -e '
  .repo == "owner/repo" and
  .repository == "owner/repo" and
  .base == "main"
' <<<"$direct_preview" >/dev/null

json_preview="$("$ROOT/bin/px" create dev smoke hello-json manual --preview --json)"
jq -e '
  .repo == "dev" and
  .repository == "owner/repo" and
  .base == "main" and
  .template == "smoke" and
  .slug == "hello-json" and
  .trigger == "manual" and
  .path == ".github/workflows/hello-json.yml" and
  .mode == "preview" and
  .install.requested == false and
  .install.installed == false and
  (.yaml | contains("workflow_dispatch:"))
' <<<"$json_preview" >/dev/null

if "$ROOT/bin/px" create dev smoke 'BAD/SLUG' manual --preview >/dev/null 2>&1; then
    printf 'invalid slug unexpectedly succeeded\n' >&2
    exit 1
fi

printf 'PX workflow factory self-test: PASS\n'
