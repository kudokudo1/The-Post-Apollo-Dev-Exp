# Post-Apollo Control Plane v0

This is the first intentionally small control seam for desktop automation.

## Shape

```text
Quickshell button later
        |
        v
       pa
      /  \
     /    \
 local    GitHub
 action   Actions via gh
```

The desktop should not need to know GitHub CLI syntax, repository names, or
current working directories. It should call one stable semantic actuator.

Version 0 only wraps GitHub Actions inspection and control. Local project
commands can be added after this seam proves useful.

## Principles

- minimum sufficient commitment
- one small actuator with high causal reach
- repository identity is explicit, never inferred from cwd
- machine-readable JSON for desktop consumers
- no Quickshell coupling yet
- no automatic mutation of other repositories
- preserve rollback by developing on an isolated branch

## First probes

From the repository checkout:

```bash
./bin/pa doctor
./bin/pa repos
./bin/pa workflows lanmouse
./bin/pa runs lanmouse
./bin/pa workflows dev
```

`lanmouse` already has GitHub Actions workflows, so it is useful for proving
the read/control path. `dev` intentionally has none yet; its empty result is
also a valid test.

## Next seam

After the command shape is proven:

1. install or symlink `pa` into `~/.local/bin`
2. add one harmless `workflow_dispatch` workflow to the Dev Experience repo
3. trigger it through `pa run dev ...`
4. only then expose the commands as Quickshell buttons

The UI remains a consumer, not the owner of automation semantics.
