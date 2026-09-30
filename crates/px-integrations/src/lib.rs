use px_core::{Action, ActionRegistry, Registry};

pub fn actions_for(registry: &Registry) -> ActionRegistry {
    let mut actions = ActionRegistry::new();

    if registry.preferred("lazygit").is_some() {
        actions.add(
            Action::tool(
                "git.ui",
                "Open Lazygit",
                "Git",
                "Open the interactive Git interface",
                "lazygit",
            )
            .with_keywords(["git", "commit", "branch", "stage", "diff"]),
        );
    }

    if registry.preferred("nvim").is_some() {
        actions.add(
            Action::tool(
                "editor.nvim",
                "Open Neovim",
                "Editor",
                "Open the terminal editor",
                "nvim",
            )
            .with_keywords(["vim", "editor", "code", "edit"]),
        );
    }

    if registry.preferred("btop").is_some() {
        actions.add(
            Action::tool(
                "system.processes",
                "Open btop",
                "System",
                "Open the interactive process and resource monitor",
                "btop",
            )
            .with_keywords(["process", "cpu", "memory", "system", "monitor"]),
        );
    }

    if registry.preferred("zellij").is_some() {
        actions.add(
            Action::tool(
                "terminal.zellij",
                "Open Zellij",
                "Terminal",
                "Open the terminal workspace manager",
                "zellij",
            )
            .with_keywords(["session", "tabs", "panes", "terminal"]),
        );
    }

    actions
}

#[cfg(test)]
mod tests {
    use super::*;
    use px_core::Tool;

    #[test]
    fn only_builds_actions_for_available_tools() {
        let mut registry = Registry::new();
        registry.add(Tool::native("lazygit", "/usr/bin/lazygit"));

        let actions = actions_for(&registry);

        assert!(actions.get("git.ui").is_some());
        assert!(actions.get("editor.nvim").is_none());
    }
}
