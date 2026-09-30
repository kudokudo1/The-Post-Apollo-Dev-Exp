use std::path::PathBuf;

#[derive(Clone, Debug, Eq, PartialEq, Hash)]
pub enum Backend {
    Native,
    Toolbox { name: String },
    Distrobox { name: String },
}

impl Backend {
    pub fn label(&self) -> String {
        match self {
            Self::Native => "native".into(),
            Self::Toolbox { name } => format!("toolbox:{name}"),
            Self::Distrobox { name } => format!("distrobox:{name}"),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Tool {
    pub name: String,
    pub executable: PathBuf,
    pub backend: Backend,
}

impl Tool {
    pub fn native(name: impl Into<String>, executable: impl Into<PathBuf>) -> Self {
        Self {
            name: name.into(),
            executable: executable.into(),
            backend: Backend::Native,
        }
    }

    pub fn toolbox(
        name: impl Into<String>,
        executable: impl Into<PathBuf>,
        toolbox: impl Into<String>,
    ) -> Self {
        Self {
            name: name.into(),
            executable: executable.into(),
            backend: Backend::Toolbox {
                name: toolbox.into(),
            },
        }
    }
}

#[derive(Default)]
pub struct Registry {
    tools: Vec<Tool>,
}

impl Registry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add(&mut self, tool: Tool) {
        if !self.tools.iter().any(|existing| {
            existing.name == tool.name
                && existing.executable == tool.executable
                && existing.backend == tool.backend
        }) {
            self.tools.push(tool);
        }
    }

    pub fn extend(&mut self, tools: impl IntoIterator<Item = Tool>) {
        for tool in tools {
            self.add(tool);
        }
    }

    pub fn len(&self) -> usize {
        self.tools.len()
    }

    pub fn is_empty(&self) -> bool {
        self.tools.is_empty()
    }

    pub fn preferred(&self, name: &str) -> Option<&Tool> {
        self.tools.iter().find(|tool| tool.name == name)
    }

    pub fn search(&self, query: &str) -> Vec<&Tool> {
        let query = query.to_lowercase();

        let mut matches: Vec<_> = self
            .tools
            .iter()
            .filter(|tool| tool.name.to_lowercase().contains(&query))
            .collect();

        matches.sort_by(|a, b| a.name.cmp(&b.name));
        matches
    }

    pub fn iter(&self) -> impl Iterator<Item = &Tool> {
        self.tools.iter()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ActionTarget {
    Tool {
        command: String,
        args: Vec<String>,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Action {
    pub id: String,
    pub title: String,
    pub category: String,
    pub description: String,
    pub keywords: Vec<String>,
    pub target: ActionTarget,
}

impl Action {
    pub fn tool(
        id: impl Into<String>,
        title: impl Into<String>,
        category: impl Into<String>,
        description: impl Into<String>,
        command: impl Into<String>,
    ) -> Self {
        Self {
            id: id.into(),
            title: title.into(),
            category: category.into(),
            description: description.into(),
            keywords: Vec::new(),
            target: ActionTarget::Tool {
                command: command.into(),
                args: Vec::new(),
            },
        }
    }

    pub fn with_keywords<I, S>(mut self, keywords: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        self.keywords = keywords.into_iter().map(Into::into).collect();
        self
    }

    pub fn with_args<I, S>(mut self, args: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        match &mut self.target {
            ActionTarget::Tool {
                args: target_args, ..
            } => {
                *target_args = args.into_iter().map(Into::into).collect();
            }
        }

        self
    }

    fn searchable_text(&self) -> String {
        let mut text = format!(
            "{} {} {} {}",
            self.id, self.title, self.category, self.description
        );

        for keyword in &self.keywords {
            text.push(' ');
            text.push_str(keyword);
        }

        text.to_lowercase()
    }
}

#[derive(Clone, Debug, Default)]
pub struct ActionRegistry {
    actions: Vec<Action>,
}

impl ActionRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add(&mut self, action: Action) {
        if !self.actions.iter().any(|existing| existing.id == action.id) {
            self.actions.push(action);
        }
    }

    pub fn get(&self, id: &str) -> Option<&Action> {
        self.actions.iter().find(|action| action.id == id)
    }

    pub fn search(&self, query: &str) -> Vec<&Action> {
        let query = query.to_lowercase();

        let mut matches: Vec<_> = self
            .actions
            .iter()
            .filter(|action| action.searchable_text().contains(&query))
            .collect();

        matches.sort_by(|left, right| {
            left.category
                .cmp(&right.category)
                .then_with(|| left.title.cmp(&right.title))
        });

        matches
    }

    pub fn iter(&self) -> impl Iterator<Item = &Action> {
        self.actions.iter()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preferred_keeps_registration_order() {
        let mut registry = Registry::new();
        registry.add(Tool::native("git", "/first/git"));
        registry.add(Tool::toolbox("git", "/usr/bin/git", "devbox"));

        assert_eq!(
            registry.preferred("git").unwrap().executable,
            PathBuf::from("/first/git")
        );
    }

    #[test]
    fn search_is_case_insensitive() {
        let mut registry = Registry::new();
        registry.add(Tool::native("LazyGit", "/usr/bin/lazygit"));

        assert_eq!(registry.search("lazy").len(), 1);
    }

    #[test]
    fn action_search_uses_keywords() {
        let mut actions = ActionRegistry::new();
        actions.add(
            Action::tool(
                "git.ui",
                "Open Lazygit",
                "Git",
                "Open the interactive Git interface",
                "lazygit",
            )
            .with_keywords(["commit", "branch", "stage"]),
        );

        assert_eq!(actions.search("branch").len(), 1);
    }
}
