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

printf '%s\n' "$*" > "${PX_TOOLBOX_CAPTURE:?}"

printf 'alpha\t/usr/bin/alpha\n'
printf 'toolbox-only\t/usr/bin/toolbox-only\n'
printf 'alpha\t/usr/sbin/alpha\n'
printf 'malformed row without tab\n'
TOOLBOX
chmod +x "$tmp/launcher/toolbox"

export PATH="$tmp/launcher:/usr/bin:/bin"
export PX_HOST_PATH="$tmp/host-a:$tmp/host-b"
export PX_TOOLBOX="devbox"
export PX_TOOLBOX_CAPTURE="$tmp/toolbox.args"

registry="$("$ROOT/bin/px" tools --json)"

jq -e --arg first "$tmp/host-a/alpha" '
  .version == 1
  and .query == ""
  and .counts.host == 3
  and .counts.toolbox == 2
  and .counts.total == 5
  and .counts.matched == 5
  and any(
    .environments[];
    .id == "host"
    and .kind == "native"
    and .status == "READY"
    and .toolCount == 3
  )
  and any(
    .environments[];
    .id == "toolbox:devbox"
    and .kind == "toolbox"
    and .status == "READY"
    and .toolCount == 2
  )
  and any(
    .tools[];
    .name == "alpha"
    and .backend == "native"
    and .environment == "host"
    and .path == $first
  )
  and any(
    .tools[];
    .name == "alpha"
    and .backend == "toolbox"
    and .environment == "toolbox:devbox"
    and .path == "/usr/bin/alpha"
  )
  and any(
    .tools[];
    .name == "toolbox-only"
    and .invocation[-1] == "/usr/bin/toolbox-only"
  )
' <<<"$registry" >/dev/null

# PATH precedence is first-hit-wins inside each environment.
if jq -e --arg shadow "$tmp/host-b/alpha" '
    any(.tools[]; .backend == "native" and .path == $shadow)
' <<<"$registry" >/dev/null; then
    printf 'host PATH shadow unexpectedly survived discovery\n' >&2
    exit 1
fi

# Toolbox discovery receives only sanitized system directories. Shared-home
# wrapper paths such as ~/.local/bin must never be inherited into this scan.
grep -q '/usr/bin' "$tmp/toolbox.args"
if grep -q '\.local/bin' "$tmp/toolbox.args"; then
    printf 'toolbox scan inherited a shared-home wrapper directory\n' >&2
    exit 1
fi

filtered="$("$ROOT/bin/px" tools toolbox-only --json)"
jq -e '
  .counts.total == 5
  and .counts.matched == 1
  and (.tools | length) == 1
  and .tools[0].name == "toolbox-only"
' <<<"$filtered" >/dev/null

human="$("$ROOT/bin/px" tools alpha)"
grep -q '^BACKEND' <<<"$human"
grep -q 'toolbox:devbox' <<<"$human"
grep -q 'host' <<<"$human"

disabled="$(
    PX_TOOLBOX=off     "$ROOT/bin/px" tools --json
)"
jq -e '
  .counts.toolbox == 0
  and any(
    .environments[];
    .kind == "toolbox" and .status == "DISABLED"
  )
' <<<"$disabled" >/dev/null

printf 'PX tool registry self-test: PASS\n'
