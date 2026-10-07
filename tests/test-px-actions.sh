#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

registry="$("$ROOT/bin/px" actions --json)"

jq -e '
  .version == 1
  and (.actions | length >= 20)
  and (
    [.actions[].id] as $ids
    | ($ids | length) == ($ids | unique | length)
  )
  and all(
    .actions[];
    (.id | type == "string" and length > 0)
    and (.title | type == "string" and length > 0)
    and (.category | type == "string" and length > 0)
    and (.summary | type == "string" and length > 0)
    and (.command | type == "array" and length > 0)
    and (.arguments | type == "array")
    and (.mutation | IN("read", "local", "remote", "external"))
    and (.requires | type == "array")
    and (.keywords | type == "array")
  )
  and any(.actions[]; .id == "github.workflow.run")
  and any(.actions[]; .id == "repository.audit")
  and any(.actions[]; .id == "hospital.room.status")
  and any(.actions[]; .id == "hospital.integration.integrate")
  and any(.actions[]; .id == "hospital.store.status")
  and any(.actions[]; .id == "ai.providers.list")
  and any(.actions[]; .id == "ai.turn")
  and any(.actions[]; .id == "ai.session.status")
  and any(.actions[]; .id == "ai.session.cancel")
  and any(.actions[]; .id == "ai.quick.pause")
' <<<"$registry" >/dev/null

hospital="$("$ROOT/bin/px" actions hospital --json)"
jq -e '
  (.actions | length > 0)
  and all(
    .actions[];
    (
      [
        .id,
        .title,
        .category,
        .summary,
        ((.keywords // []) | join(" "))
      ]
      | join(" ")
      | ascii_downcase
      | contains("hospital")
    )
  )
' <<<"$hospital" >/dev/null

human="$("$ROOT/bin/px" actions github)"
grep -q $'^ID\tCATEGORY\tTITLE$' <<<"$human"
grep -q $'^github.workflow.run\tGitHub\tRun Workflow$' <<<"$human"

printf 'PX action registry self-test: PASS\n'
