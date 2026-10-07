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
    and all(
      .arguments[];
      (.name | type == "string" and length > 0)
      and (.required | type == "boolean")
      and (.kind | type == "string" and length > 0)
      and ((.choices // []) | type == "array")
    )
    and (.mutation | IN("read", "local", "remote", "external"))
    and ((.executionPolicy // "") | IN("", "px-guarded"))
    and (.recovery | IN("NONE", "EVIDENCE_ONLY", "REF_RECOVERABLE", "CONTENT_RECOVERABLE"))
    and (.requires | type == "array")
    and (.keywords | type == "array")
  )
  and any(.actions[]; .id == "github.workflow.run")
  and any(.actions[]; .id == "repository.branches.list")
  and any(.actions[]; .id == "repository.commits.list")
  and any(.actions[]; .id == "repository.audit")
  and any(.actions[]; .id == "hospital.room.status")
  and any(.actions[]; .id == "hospital.integration.integrate")
  and any(.actions[]; .id == "hospital.store.status")
  and any(.actions[]; .id == "hospital.room.report.view")
  and any(.actions[]; .id == "hospital.room.chart.view")
  and any(.actions[]; .id == "ai.providers.list")
  and any(.actions[]; .id == "ai.turn")
  and any(.actions[]; .id == "ai.session.status")
  and any(.actions[]; .id == "ai.session.cancel")
  and any(.actions[]; .id == "ai.quick.pause")
  and any(.actions[]; .id == "px.tool.resolve")
  and any(.actions[]; .id == "px.term.open")
  and any(.actions[]; .id == "px.operations.list")
  and any(.actions[]; .id == "px.operation.view")
  and any(.actions[]; .id == "px.operation.recovery")
' <<<"$registry" >/dev/null


recovery_contract="$(jq -c '
  {
    read_non_none: [.actions[] | select(.mutation == "read" and .recovery != "NONE")] | length,
    mutation_undeclared: [
      .actions[]
      | select(.mutation != "read")
      | select(.recovery == null or .recovery == "")
    ] | length,
    integrate: (
      .actions[]
      | select(.id == "hospital.integration.integrate")
      | .recovery
    )
  }
' <<<"$registry")"
[[ "$recovery_contract" == '{"read_non_none":0,"mutation_undeclared":0,"integrate":"EVIDENCE_ONLY"}' ]]

guarded_remote_contract="$(jq -c '
  {
    ids: (
      [
        .actions[]
        | select((.executionPolicy // "") == "px-guarded")
        | .id
      ]
      | sort
    ),
    invalid: [
      .actions[]
      | select((.executionPolicy // "") == "px-guarded")
      | select(.mutation != "remote" or .recovery != "EVIDENCE_ONLY")
      | .id
    ]
  }
' <<<"$registry")"
[[ "$guarded_remote_contract" == '{"ids":["github.run.cancel","github.run.rerun","github.workflow.run","workflow.delete"],"invalid":[]}' ]]

trigger_choices="$(jq -c '
  .actions[]
  | select(.id == "workflow.create")
  | .arguments[]
  | select(.name == "trigger")
  | .choices
' <<<"$registry")"
[[ "$trigger_choices" == '["manual","push","manual+push"]' ]]


jq -e '
  (
    .actions[]
    | select(.id == "github.run.inspect")
    | .arguments[]
    | select(.name == "run_id")
    | .dependsOn.repository
  ) == "repository"
  and (
    .actions[]
    | select(.id == "hospital.integration.integrate")
    | .arguments[]
    | select(.name == "room_head")
    | .dependsOn.reference
  ) == "branch"
  and (
    .actions[]
    | select(.id == "hospital.integration.integrate")
    | .arguments[]
    | select(.name == "base_head")
    | .dependsOn.reference
  ) == "base"
' <<<"$registry" >/dev/null

repos="$("$ROOT/bin/px" repos --json)"
jq -e '
  .version == 1
  and (.repositories | length > 0)
  and (
    [.repositories[].alias] as $aliases
    | ($aliases | length) == ($aliases | unique | length)
  )
  and all(
    .repositories[];
    (.alias | type == "string" and length > 0)
    and (.repository | type == "string" and contains("/"))
  )
  and any(
    .repositories[];
    .alias == "dev"
    and .repository == "kudokudo1/The-Post-Apollo-Dev-Exp"
  )
' <<<"$repos" >/dev/null

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
