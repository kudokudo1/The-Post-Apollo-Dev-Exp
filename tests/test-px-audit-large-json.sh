#!/usr/bin/env bash
set -euo pipefail
# Synthetic, disposable GH fixture: no provider credentials or Hospital DB.
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/fixture"

python3 - "$tmp/fixture" <<'PY'
import json
from pathlib import Path
import sys
folder = Path(sys.argv[1])
large = [
    {"id": i, "name": "audit-fixture-" + str(i) + ("x" * 110),
     "path": f".github/workflows/fixture-{i}.yml", "state": "active"}
    for i in range(2600)
]
data = json.dumps(large, separators=(",", ":"))
assert len(data.encode()) > 200000
(folder / "workflows.json").write_text(data)
(folder / "runs.json").write_text(json.dumps([{
    "databaseId": 11, "workflowName": "audit smoke",
    "status": "completed", "conclusion": "success",
    "headBranch": "main", "headSha": "abc", "createdAt": "2026-10-16T00:00:00Z"
}]))
PY
cat > "$tmp/bin/gh" <<'GH'
#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
    "repo view")
        printf '%s\n' '{"nameWithOwner":"example/audit-fixture","defaultBranchRef":{"name":"main"},"isPrivate":false,"isArchived":false,"url":"https://github.com/example/audit-fixture"}'
        ;;
    "workflow list")
        cat "$PX_AUDIT_FIXTURE/workflows.json"
        ;;
    "run list")
        cat "$PX_AUDIT_FIXTURE/runs.json"
        ;;
    "api --paginate")
        printf 'main\tabc\nfeature/audit\tdef\n'
        ;;
    *)
        echo "UNEXPECTED GH READ: $*" >&2
        exit 31
        ;;
esac
GH
chmod +x "$tmp/bin/gh"

PATH="$tmp/bin:$PATH" PX_AUDIT_FIXTURE="$tmp/fixture" \
    "$ROOT/bin/px" audit example/audit-fixture > "$tmp/out.json"
python3 - "$tmp/out.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
assert payload["repository"] == "example/audit-fixture", payload.get("repository")
assert payload["status"] == "PASS", payload.get("status")
assert payload["workflows"]["count"] == 2600, payload["workflows"]["count"]
assert payload["workflows"]["active"] == 2600
assert len(payload["workflows"]["items"]) == 2600
assert payload["runs"]["count"] == 1, payload["runs"]["count"]
assert payload["rooms"]["count"] == 1, payload["rooms"]
assert payload["rooms"]["items"][0]["branch"] == "feature/audit"
print("PX AUDIT LARGE JSON // FILE INPUT + EXACT RESULT PASS")
PY
