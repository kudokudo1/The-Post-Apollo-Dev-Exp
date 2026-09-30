# The Post-Apollo Dev Experience

## PX // TERM EXP

PX is a keyboard-first control layer for the terminal environment.

The current foundation already:

- discovers native commands from `$PATH`;
- discovers system commands inside Fedora Toolbox without re-importing shared-home wrappers;
- merges both execution domains into one registry;
- resolves and launches commands through the correct backend;
- derives the conventional Toolbox name from the host OS instead of hard-coding one machine;
- supports persistent and environment Toolbox overrides;
- builds a semantic action layer on top of raw commands.

The direction is:

```text
commands already on the machine
        +
PX-native actions
        +
known integrations
        ↓
one searchable registry
        ↓
LazyVim-style key menus + fuzzy finding
        ↓
delegate to Lazygit / Neovim / btop / Zellij / ...
```

### Current commands

```bash
px
px doctor
px config

px tools
px tools lazy
px which lazygit
px open lazygit

px actions
px actions git
px do git.ui
```

`px open` is currently a direct resolver test surface. Normal tools should
ultimately keep their normal command names while PX-managed routing handles
execution location underneath them.

### Toolbox configuration

PX checks, in order:

1. `PX_TOOLBOX`;
2. `PX_CONFIG`, `$XDG_CONFIG_HOME/px/config.toml`, or `~/.config/px/config.toml`;
3. a conventional Toolbox name derived from `/etc/os-release` when Toolbox is installed.

Example:

```toml
[toolbox]
enabled = true
name = "fedora-toolbox-44"
```

Temporary override:

```bash
PX_TOOLBOX=my-devbox px doctor
```

Disable Toolbox for one invocation:

```bash
PX_TOOLBOX=off px doctor
```

### First semantic actions

When the matching tools exist, PX currently exposes actions such as:

```text
git.ui             → Lazygit
editor.nvim        → Neovim
system.processes   → btop
terminal.zellij    → Zellij
```

The TUI has not been added yet. Ratatui/Crossterm comes after the registry,
routing, configuration, and action layers are stable enough to become its
single source of truth.
