# Post-Apollo PX Control Plane v0

PX is the first intentionally small control seam for Post-Apollo desktop automation.

## Shape

```text
Quickshell / Hospital / Git menu
             |
             v
            px
           /  \
          /    \
      local    GitHub
      action   Actions via gh
```

The desktop should not need to know GitHub CLI syntax, repository names, current
working directories, or workflow implementation details. It should call one
stable semantic actuator: **PX**.

Version 0 wraps GitHub Actions inspection and control. Local project commands
and workflow creation can be added after this seam proves useful.

## Principles

- minimum sufficient commitment
- one small actuator with high causal reach
- repository identity is explicit, never inferred from cwd
- machine-readable JSON for desktop consumers
- no Quickshell coupling until the command path is trustworthy
- preview before workflow mutation
- preserve rollback by developing on isolated branches
- GitHub is the backend; Post-Apollo is the control room

## First probes

From the repository checkout:

```bash
./bin/px doctor
./bin/px repos
./bin/px workflows lanmouse
./bin/px runs lanmouse
./bin/px workflows dev
```

`lanmouse` already has GitHub Actions workflows and is useful for proving the
read/control path.

## Bootstrap workflow

`.github/workflows/px-smoke.yml` is the first harmless PX workflow.

On the `automation/px-control-bus-v0` branch it runs automatically when the
PX control files change. Its job is deliberately tiny:

1. check out the repo
2. validate `bin/px` shell syntax
3. run local `px repos` and `px --help`
4. print repo/ref/SHA information

After the workflow lands on the default branch, `workflow_dispatch` can be
used to prove the manual control path:

```bash
./bin/px workflows dev
./bin/px run dev px-smoke.yml
./bin/px runs dev
./bin/px watch dev <run-id>
```

Then test:

```bash
./bin/px rerun dev <run-id>
./bin/px cancel dev <run-id>
```

## Workflow builder roadmap

Once the execution path is proven, PX grows a creator side:

```text
TEMPLATES
    ↓
BUILDER
    ↓
PREVIEW
    ↓
VALIDATE
    ↓
CREATE / EDIT
    ↓
GitHub Actions
```

The desktop can then offer semantic procedures such as HEALTH CHECK, SECURITY
SCAN, BUILD, TEST, RELEASE, DEPLOY, and CUSTOM while PX generates the workflow
YAML underneath.

Raw YAML remains available as the high-resolution camera.

## Naming

The control bus is **PX**. The earlier `pa` name is legacy bootstrap history.
The old branch remains available as a rollback point; active development moves
forward under `automation/px-control-bus-v0`.
