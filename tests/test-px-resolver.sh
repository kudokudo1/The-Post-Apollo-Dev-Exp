#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/host-a" "$tmp/host-b" "$tmp/launcher"

for tool in alpha host-only; do
    printf '#!/usr/bin/env sh\nexit 0\n' > "$tmp/host-a/$tool"
    chmod +x "$tmp/host-a/$tool"
done

for tool in alpha beta; do
    printf '#!/usr/bin/env sh\nexit 0\n' > "$tmp/host-b/$tool"
    chmod +x "$tmp/host-b/$tool"
done

cat > "$tmp/launcher/toolbox" <<'TOOLBOX'
#!/usr/bin/env bash
set -euo pipefail

printf 'alpha\t/usr/bin/alpha\n'
printf 'toolbox-only\t/usr/bin/toolbox-only\n'
TOOLBOX
chmod +x "$tmp/launcher/toolbox"

export PATH="$tmp/launcher:/usr/bin:/bin"
export PX_HOST_PATH="$tmp/host-a:$tmp/host-b"
export PX_TOOLBOX="devbox"

host_result="$("$ROOT/bin/px" which alpha --json)"
jq -e --arg first "$tmp/host-a/alpha" '
  .version == 1
  and .query == "alpha"
  and .status == "FOUND"
  and .reason == "HOST_PATH"
  and .policy.id == "host-first-v1"
  and (.candidates | length) == 2
  and .selected.backend == "native"
  and .selected.environment == "host"
  and .selected.path == $first
' <<<"$host_result" >/dev/null

toolbox_result="$("$ROOT/bin/px" which toolbox-only --json)"
jq -e '
  .status == "FOUND"
  and .reason == "TOOLBOX_FALLBACK"
  and .selected.backend == "toolbox"
  and .selected.environment == "toolbox:devbox"
  and .selected.path == "/usr/bin/toolbox-only"
  and .selected.invocation[-1] == "/usr/bin/toolbox-only"
' <<<"$toolbox_result" >/dev/null

forced_backend="$("$ROOT/bin/px" which alpha --backend toolbox --json)"
jq -e '
  .status == "FOUND"
  and .reason == "FORCED_BACKEND"
  and (.candidates | length) == 1
  and .selected.backend == "toolbox"
  and .selected.path == "/usr/bin/alpha"
' <<<"$forced_backend" >/dev/null

forced_environment="$(
    "$ROOT/bin/px" which alpha --environment toolbox:devbox --json
)"
jq -e '
  .status == "FOUND"
  and .reason == "FORCED_ENVIRONMENT"
  and (.candidates | length) == 1
  and .selected.environment == "toolbox:devbox"
' <<<"$forced_environment" >/dev/null

set +e
missing="$("$ROOT/bin/px" which definitely-missing --json)"
missing_rc=$?
set -e

[[ "$missing_rc" -eq 1 ]]
jq -e '
  .status == "NOT_FOUND"
  and .reason == "NOT_FOUND"
  and .selected == null
  and (.candidates | length) == 0
' <<<"$missing" >/dev/null

human="$("$ROOT/bin/px" which toolbox-only)"
grep -q '^PX TOOL RESOLVER$' <<<"$human"
grep -q '^REASON     TOOLBOX_FALLBACK$' <<<"$human"
grep -q '^SELECTED   toolbox:devbox  /usr/bin/toolbox-only$' <<<"$human"
grep -q '^INVOKE     ' <<<"$human"

printf 'PX tool resolver self-test: PASS\n'
