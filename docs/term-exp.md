# PX // TERM EXP shell v0

This is the rebuilt terminal frontend for the current PX control plane.

It is intentionally **not** the old `feature/px-foundation` backend. The old
Ratatui work is donor material only. The living frontend reads the current
machine contracts:

```text
px actions --json
px tools --json
```

That keeps Hospital, GitHub, AI, workflows, and ordinary executable discovery
behind one source of truth.

## Open

```bash
px term
# alias:
px tui
```

Until the later installer/runtime lane installs a compiled `px-term-exp`
binary, `bin/px-term` launches the crate through Cargo from the runtime tree.

## v0 surface

The first shell proves:

- current PX action registry loads successfully;
- current host + Toolbox tool registry loads successfully;
- the live action/tool counts are visible;
- backend environments and readiness are visible;
- action categories are derived from the registry rather than hard-coded;
- representative semantic actions are rendered from the live registry;
- terminal raw/alternate-screen cleanup is guarded on exit.

The first interaction model is now live:

- `SPACE` opens a command/category menu;
- `/` opens Find Anything;
- leader and search selectors are independent;
- fuzzy search spans semantic PX actions and preferred host/Toolbox commands;
- narrow terminals stack the dashboard vertically instead of crushing the
  two-column layout;
- `q`, `Esc`, and `Ctrl-C` preserve clean terminal exit behavior.

Tool selection can now delegate a guarded specialist set:

- Lazygit;
- Neovim;
- btop;
- Zellij;
- fzf.

TERM EXP re-resolves the selected specialist through `px which --json` at
launch time, suspends raw/alternate-screen mode, runs the exact resolved
invocation, and restores TERM EXP when the specialist exits.

Find Anything now labels results by role:

- `ACTION` — a semantic PX capability;
- `SPECIAL` — an approved interactive specialist that TERM EXP can delegate
  to directly;
- `COMMAND` — an executable discovered on the host or in Toolbox. These are
  real programs, but TERM EXP does not pretend every low-level CLI is an
  interactive app.

Read-only PX actions are executable in TERM EXP. Actions with no arguments run
immediately and render their output in-app. Actions with arguments open a
typed input sequence first; for example, Inspect Workflow Run asks for the
repository and run ID before calling PX.

Mutation actions remain locked until explicit mutation/confirmation policy is
implemented.

## Architecture

```text
PX // TERM EXP
      |
      +-- px actions --json
      |      semantic control plane
      |
      +-- px tools --json
             ordinary executable universe
```

TERM EXP is therefore a frontend to current PX. It does not recreate the old
Rust-side discovery, backend, or semantic action registries.
