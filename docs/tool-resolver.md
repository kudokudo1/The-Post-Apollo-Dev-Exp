# PX Tool Resolver v0

PX // TERM EXP needs one deterministic answer to a simple question:

> If I ask for `lazygit`, what should PX actually launch?

The discovery registry can report several tools with the same command name across
different environments. The resolver chooses one candidate without hiding the
alternatives.

## Commands

```bash
px which lazygit
px which git --json
px which git --backend toolbox --json
px which git --environment toolbox:fedora-toolbox-44 --json
```

## Default policy

Version 0 uses `host-first-v1`:

1. preserve normal host PATH behavior when the command exists on the host;
2. otherwise fall back to Toolbox;
3. reserve Distrobox as the next backend tier.

Host PATH precedence has already been resolved by `px tools`, so the host
candidate is the same executable the shell would normally find first.

This preserves ordinary command behavior. Existing host wrappers remain valid
host commands instead of PX silently bypassing them.

## Explicit override

`--backend` restricts resolution to one backend kind.

`--environment` restricts resolution to one exact environment identity.

These are escape hatches for cases where the operator explicitly wants the
container copy even though a host command exists.

## JSON result

```json
{
  "version": 1,
  "query": "lazygit",
  "status": "FOUND",
  "reason": "TOOLBOX_FALLBACK",
  "policy": {
    "id": "host-first-v1",
    "backendPriority": ["native", "toolbox", "distrobox"]
  },
  "selected": {
    "name": "lazygit",
    "backend": "toolbox",
    "environment": "toolbox:fedora-toolbox-44",
    "path": "/usr/bin/lazygit",
    "invocation": [
      "/usr/bin/toolbox",
      "run",
      "-c",
      "fedora-toolbox-44",
      "--",
      "/usr/bin/lazygit"
    ]
  },
  "candidates": []
}
```

The real result retains every matching candidate in `candidates`; the shortened
example above focuses on the selected execution target.

## Boundary

The resolver does **not** execute the selected tool yet.

That is intentional. Discovery answers *what exists*. Resolution answers *which
one PX means*. Specialist delegation will later answer *launch it, suspend the
PX surface, and return cleanly afterward*.
