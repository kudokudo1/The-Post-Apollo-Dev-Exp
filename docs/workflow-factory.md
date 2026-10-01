# PX Workflow Factory v0

PX can now describe, preview, validate, and install small GitHub Actions workflows without using the GitHub web UI.

## Contract

```text
intent
  ↓
px create
  ↓
template + repo + trigger
  ↓
render candidate YAML
  ↓
preview
  ↓
actionlint when available
  ↓
--install (explicit approval)
  ↓
new automation branch
  ↓
workflow file
  ↓
pull request
```

Generated workflows are never written directly to the repository's default branch. `--install` creates a new `automation/px-workflow-*` branch and opens a pull request.

## Templates

```bash
px templates
```

Factory v0 contains two deliberately small templates:

- `smoke` — checkout plus execution identity; proves the runner is alive.
- `shell-check` — runs `bash -n` over every `*.sh` file found in the repository.

Both templates request only `contents: read` permissions.

## Preview first

Preview is the default behavior:

```bash
px create dev smoke my-first-action
px create dev shell-check shell-syntax manual+push --preview
```

PX prints the target repository, default branch, workflow path, and complete generated YAML before performing validation. No repository mutation occurs during preview.

Supported trigger choices in v0:

```text
manual
push
manual+push
```

## Validation

PX uses `actionlint` when it is available on the host. If it is not on the host, PX also checks the toolbox named by `PX_TOOLBOX` (default: `fedora-toolbox-44`).

If actionlint cannot be found, PX clearly reports that semantic validation was skipped instead of pretending the candidate was validated.

## Install

Installation requires an explicit `--install`:

```bash
px create dev shell-check shell-syntax manual --install
```

PX then:

1. resolves the repo alias and default branch;
2. refuses to overwrite an existing workflow of the same slug;
3. creates a new remote automation branch;
4. writes only `.github/workflows/<slug>.yml`;
5. opens a pull request;
6. prints the branch and PR URL.

The PR remains the human approval seam before the workflow reaches the default branch.

## Current boundary

Factory v0 creates new workflows only. Editing/deleting existing workflows, arbitrary custom commands, secrets, environments, deployment permissions, matrices, artifacts, and reusable workflows remain outside this first seam.
