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
}
