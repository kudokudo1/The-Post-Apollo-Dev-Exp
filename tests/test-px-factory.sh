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

preview="$("$ROOT/bin/px" create dev smoke hello-world manual --preview 2>/dev/null)"
grep -q '^PX WORKFLOW CANDIDATE$' <<<"$preview"
grep -q '^path: .github/workflows/hello-world.yml$' <<<"$preview"
grep -q '^  workflow_dispatch:$' <<<"$preview"
grep -q '^preview only: no repository changes made$' <<<"$preview"

push_preview="$("$ROOT/bin/px" create dev shell-check shell-syntax manual+push --preview 2>/dev/null)"
grep -q '^  push:$' <<<"$push_preview"
grep -q '^      - main$' <<<"$push_preview"
grep -q "find . -type f -name '\\*.sh'" <<<"$push_preview"

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
