use px_core::Tool;

use std::collections::HashSet;
use std::ffi::OsStr;
use std::fs;
use std::io;
use std::path::Path;
use std::process::Command;

#[cfg(unix)]
fn is_executable(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;

    match fs::metadata(path) {
        Ok(metadata) => metadata.is_file() && metadata.permissions().mode() & 0o111 != 0,
        Err(_) => false,
    }
}

pub fn discover_path(path_value: &OsStr) -> io::Result<Vec<Tool>> {
    let mut seen = HashSet::new();
    let mut tools = Vec::new();

    // split_paths preserves PATH directory precedence.
    for directory in std::env::split_paths(path_value) {
        let mut entries = match fs::read_dir(&directory) {
            Ok(entries) => entries.filter_map(Result::ok).collect::<Vec<_>>(),

            Err(error)
                if error.kind() == io::ErrorKind::NotFound
                    || error.kind() == io::ErrorKind::PermissionDenied =>
            {
                continue;
            }

            Err(error) => return Err(error),
        };

        entries.sort_by_key(|entry| entry.file_name());

        for entry in entries {
            let executable = entry.path();

            if !is_executable(&executable) {
                continue;
            }

            let Some(name) = entry.file_name().to_str().map(ToOwned::to_owned) else {
                continue;
            };

            // First occurrence wins, just like PATH resolution.
            if !seen.insert(name.clone()) {
                continue;
            }

            tools.push(Tool::native(name, executable));
        }
    }

    Ok(tools)
}

pub fn discover_environment() -> io::Result<Vec<Tool>> {
    let Some(path) = std::env::var_os("PATH") else {
        return Ok(Vec::new());
    };

    discover_path(&path)
}

pub fn discover_toolbox(toolbox_name: &str) -> io::Result<Vec<Tool>> {
    // Do not inherit the Toolbox view of ~/.local/bin here. Silverblue shares
    // the home directory with Toolbox, so host-side wrappers can otherwise be
    // rediscovered as if they were container-native commands and recurse back
    // into Toolbox.
    const SCRIPT: &str = r#"
for dir in /usr/local/sbin /usr/local/bin /usr/sbin /usr/bin /sbin /bin; do
    [ -d "$dir" ] || continue

    for file in "$dir"/*; do
        [ -f "$file" ] || continue
        [ -x "$file" ] || continue

        printf '%s\t%s\n' "$(basename "$file")" "$file"
    done
done
"#;

    let output = Command::new("toolbox")
        .args(["run", "-c", toolbox_name, "--", "sh", "-c", SCRIPT])
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();

        let message = if stderr.is_empty() {
            format!("toolbox discovery failed with {}", output.status)
        } else {
            format!(
                "toolbox discovery failed with {}: {stderr}",
                output.status
            )
        };

        return Err(io::Error::other(message));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut seen = HashSet::new();
    let mut tools = Vec::new();

    for line in stdout.lines() {
        let Some((name, path)) = line.split_once('\t') else {
            continue;
        };

        if !seen.insert(name.to_owned()) {
            continue;
        }

        tools.push(Tool::toolbox(name, path, toolbox_name));
    }

    Ok(tools)
}
