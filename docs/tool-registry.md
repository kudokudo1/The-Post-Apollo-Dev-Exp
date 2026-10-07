# PX Tool Registry v0

PX // TERM EXP needs to see ordinary executables without pretending they all
live in the same environment.

`px tools` is the first discovery contract for that job.

## Commands

```bash
px tools
px tools lazy
px tools --json
px tools git --json
```

Human mode shows environment counts when no query is supplied and matching
tools when a query is supplied. JSON mode returns the complete machine-readable
registry.

## Environments

Version 0 discovers:

- the host PATH, preserving PATH directory precedence;
- one configured Toolbox, using `PX_TOOLBOX` (default
  `fedora-toolbox-44`).

Distrobox and other backends are intentionally deferred until the resolver
contract is proven.

## Shared-home wrapper safety

Fedora Toolbox shares the user's home directory with the host. A normal shell
inside Toolbox can therefore inherit host paths such as `~/.local/bin`.

That is dangerous for PX discovery because host wrapper scripts can look like
container-native commands and recurse back into Toolbox.

Toolbox discovery therefore does **not** scan the inherited Toolbox PATH. It
scans only this sanitized system path by default:

```text
/usr/local/bin
/usr/local/sbin
/usr/bin
/usr/sbin
/bin
/sbin
```

The path can be overridden with `PX_TOOLBOX_SYSTEM_PATH` for testing or an
explicit deployment need.

## Registry record

Each discovered tool records:

- command name;
- executable path;
- backend kind;
- environment identity;
- user/system scope;
- exact invocation prefix required to launch it.

A JSON tool record is intentionally small:

```json
{
  "name": "lazygit",
  "path": "/usr/bin/lazygit",
  "backend": "toolbox",
  "environment": "toolbox:fedora-toolbox-44",
  "scope": "system",
  "invocation": [
    "/usr/bin/toolbox",
    "run",
    "-c",
    "fedora-toolbox-44",
    "--",
    "/usr/bin/lazygit"
  ]
}
```

The registry is discovery-only. It does not yet choose which duplicate command
should win across host and Toolbox. That belongs to the next layer: the PX
resolver.

## Testing hooks

`PX_HOST_PATH` overrides the host discovery PATH without changing the process
PATH used to locate Python or Toolbox.

`PX_TOOLBOX=off` disables Toolbox discovery.

`PX_DISCOVERY_TIMEOUT` controls the Toolbox probe timeout in seconds.
