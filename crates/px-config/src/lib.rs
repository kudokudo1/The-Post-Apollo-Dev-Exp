use std::env;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ConfigSource {
    Environment,
    File(PathBuf),
    Detected,
    Disabled,
}

impl ConfigSource {
    pub fn label(&self) -> String {
        match self {
            Self::Environment => "environment".into(),
            Self::File(path) => format!("file:{}", path.display()),
            Self::Detected => "detected".into(),
            Self::Disabled => "disabled".into(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ToolboxConfig {
    pub enabled: bool,
    pub name: Option<String>,
    pub source: ConfigSource,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PxConfig {
    pub toolbox: ToolboxConfig,
}

impl PxConfig {
    pub fn load() -> Result<Self, String> {
        if let Ok(value) = env::var("PX_TOOLBOX") {
            return Ok(Self {
                toolbox: toolbox_from_environment(&value),
            });
        }

        if let Some(path) = config_path()
            && path.exists()
        {
            let contents = fs::read_to_string(&path)
                .map_err(|error| format!("failed to read {}: {error}", path.display()))?;

            return Ok(Self {
                toolbox: toolbox_from_file(&path, &contents)?,
            });
        }

        if command_exists("toolbox")
            && let Some(name) = detect_default_toolbox_name()
        {
            return Ok(Self {
                toolbox: ToolboxConfig {
                    enabled: true,
                    name: Some(name),
                    source: ConfigSource::Detected,
                },
            });
        }

        Ok(Self {
            toolbox: ToolboxConfig {
                enabled: false,
                name: None,
                source: ConfigSource::Disabled,
            },
        })
    }
}

fn toolbox_from_environment(value: &str) -> ToolboxConfig {
    let value = value.trim();

    if value.is_empty()
        || value.eq_ignore_ascii_case("none")
        || value.eq_ignore_ascii_case("off")
        || value.eq_ignore_ascii_case("disabled")
    {
        return ToolboxConfig {
            enabled: false,
            name: None,
            source: ConfigSource::Environment,
        };
    }

    ToolboxConfig {
        enabled: true,
        name: Some(value.to_owned()),
        source: ConfigSource::Environment,
    }
}

fn toolbox_from_file(path: &Path, contents: &str) -> Result<ToolboxConfig, String> {
    let parsed = parse_toolbox_section(contents)?;

    if parsed.enabled == Some(false) {
        return Ok(ToolboxConfig {
            enabled: false,
            name: None,
            source: ConfigSource::File(path.to_path_buf()),
        });
    }

    match parsed.name {
        Some(name) if !name.is_empty() => Ok(ToolboxConfig {
            enabled: true,
            name: Some(name),
            source: ConfigSource::File(path.to_path_buf()),
        }),

        _ if parsed.enabled == Some(true) => Err(format!(
            "{} enables Toolbox but does not set toolbox.name",
            path.display()
        )),

        _ => Ok(ToolboxConfig {
            enabled: false,
            name: None,
            source: ConfigSource::File(path.to_path_buf()),
        }),
    }
}

#[derive(Default)]
struct ParsedToolbox {
    enabled: Option<bool>,
    name: Option<String>,
}

fn parse_toolbox_section(contents: &str) -> Result<ParsedToolbox, String> {
    let mut parsed = ParsedToolbox::default();
    let mut in_toolbox = false;

    for (index, raw_line) in contents.lines().enumerate() {
        let line_number = index + 1;
        let line = raw_line.split('#').next().unwrap_or("").trim();

        if line.is_empty() {
            continue;
        }

        if line.starts_with('[') && line.ends_with(']') {
            in_toolbox = line == "[toolbox]";
            continue;
        }

        if !in_toolbox {
            continue;
        }

        let Some((key, value)) = line.split_once('=') else {
            return Err(format!("invalid config syntax on line {line_number}"));
        };

        let key = key.trim();
        let value = value.trim();

        match key {
            "enabled" => {
                parsed.enabled = Some(match value {
                    "true" => true,
                    "false" => false,
                    _ => {
                        return Err(format!(
                            "toolbox.enabled must be true or false on line {line_number}"
                        ));
                    }
                });
            }

            "name" => {
                parsed.name = Some(parse_string(value).ok_or_else(|| {
                    format!("toolbox.name must be a quoted string on line {line_number}")
                })?);
            }

            _ => {}
        }
    }

    Ok(parsed)
}

fn parse_string(value: &str) -> Option<String> {
    if value.len() < 2 {
        return None;
    }

    let bytes = value.as_bytes();
    let quoted = (bytes[0] == b'"' && bytes[value.len() - 1] == b'"')
        || (bytes[0] == b'\'' && bytes[value.len() - 1] == b'\'');

    quoted.then(|| value[1..value.len() - 1].to_owned())
}

fn config_path() -> Option<PathBuf> {
    if let Some(path) = env::var_os("PX_CONFIG") {
        return Some(PathBuf::from(path));
    }

    if let Some(base) = env::var_os("XDG_CONFIG_HOME") {
        return Some(PathBuf::from(base).join("px/config.toml"));
    }

    env::var_os("HOME").map(|home| PathBuf::from(home).join(".config/px/config.toml"))
}

fn command_exists(command: &str) -> bool {
    let Some(path) = env::var_os("PATH") else {
        return false;
    };

    env::split_paths(&path).any(|directory| directory.join(command).is_file())
}

fn detect_default_toolbox_name() -> Option<String> {
    let contents = fs::read_to_string("/etc/os-release").ok()?;
    detect_toolbox_name_from_os_release(&contents)
}

fn detect_toolbox_name_from_os_release(contents: &str) -> Option<String> {
    let mut id = None;
    let mut version = None;

    for raw_line in contents.lines() {
        let Some((key, value)) = raw_line.split_once('=') else {
            continue;
        };

        let value = value.trim_matches('"').trim_matches('\'');

        match key {
            "ID" => id = Some(value.to_owned()),
            "VERSION_ID" => version = Some(value.to_owned()),
            _ => {}
        }
    }

    Some(format!("{}-toolbox-{}", id?, version?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_toolbox_name() {
        let parsed = parse_toolbox_section(
            r#"
[toolbox]
enabled = true
name = "fedora-toolbox-44"
"#,
        )
        .unwrap();

        assert_eq!(parsed.enabled, Some(true));
        assert_eq!(parsed.name.as_deref(), Some("fedora-toolbox-44"));
    }

    #[test]
    fn ignores_other_sections() {
        let parsed = parse_toolbox_section(
            r#"
[theme]
name = "post-apollo"

[toolbox]
name = "devbox"
"#,
        )
        .unwrap();

        assert_eq!(parsed.name.as_deref(), Some("devbox"));
    }

    #[test]
    fn derives_default_toolbox_name_from_os_release() {
        let name = detect_toolbox_name_from_os_release(
            r#"
NAME="Fedora Linux"
ID=fedora
VERSION_ID=44
"#,
        );

        assert_eq!(name.as_deref(), Some("fedora-toolbox-44"));
    }

    #[test]
    fn environment_can_disable_toolbox() {
        let config = toolbox_from_environment("off");

        assert!(!config.enabled);
        assert_eq!(config.name, None);
    }
}
