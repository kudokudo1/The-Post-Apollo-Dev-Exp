use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::{path::Path, process::Command};

#[derive(Debug, Deserialize)]
struct OperationRecord {
    id: String,
}

fn run_json<T>(px_path: &Path, args: &[String], label: &str) -> Result<T, String>
where
    T: for<'de> Deserialize<'de>,
{
    let output = Command::new(px_path)
        .args(args)
        .output()
        .map_err(|error| format!("could not launch {label}: {error}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
        let detail = if !stderr.is_empty() { stderr } else { stdout };

        return Err(if detail.is_empty() {
            format!("{label} failed")
        } else {
            detail
        });
    }

    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("{label} returned invalid JSON: {error}"))
}

pub(crate) fn start(
    px_path: &Path,
    action_id: &str,
    title: &str,
    mutation: &str,
    recovery: &str,
    command: &[String],
    arguments: &[(String, String)],
    armed: bool,
    preflight: &str,
) -> Result<String, String> {
    if recovery.trim().is_empty() {
        return Err("mutation has no declared recovery class".to_owned());
    }

    let mut argument_map = Map::new();
    for (name, value) in arguments {
        argument_map.insert(name.clone(), Value::String(value.clone()));
    }

    let before = json!({
        "armed": armed,
        "preflight": preflight,
    });

    let args = vec![
        "operation".to_owned(),
        "start".to_owned(),
        "--action-id".to_owned(),
        action_id.to_owned(),
        "--title".to_owned(),
        title.to_owned(),
        "--mutation".to_owned(),
        mutation.to_owned(),
        "--recovery".to_owned(),
        recovery.to_owned(),
        "--command-json".to_owned(),
        serde_json::to_string(command)
            .map_err(|error| format!("could not encode frozen command: {error}"))?,
        "--arguments-json".to_owned(),
        Value::Object(argument_map).to_string(),
        "--before-json".to_owned(),
        before.to_string(),
        "--json".to_owned(),
    ];

    let record: OperationRecord = run_json(px_path, &args, "PX operation start")?;
    Ok(record.id)
}

fn clipped_text(bytes: &[u8]) -> String {
    const LIMIT: usize = 4096;
    let text = String::from_utf8_lossy(bytes);

    if text.len() <= LIMIT {
        return text.into_owned();
    }

    let mut boundary = LIMIT;
    while !text.is_char_boundary(boundary) {
        boundary -= 1;
    }

    format!("{}\n...[clipped by TERM EXP]", &text[..boundary])
}

pub(crate) fn output_evidence(stdout: &[u8], stderr: &[u8]) -> Value {
    let stdout_text = clipped_text(stdout);
    let stderr_text = clipped_text(stderr);

    let stdout_json = serde_json::from_str::<Value>(stdout_text.trim()).ok();

    json!({
        "stdout": stdout_json.unwrap_or_else(|| Value::String(stdout_text)),
        "stderr": stderr_text,
    })
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn finish(
    px_path: &Path,
    operation_id: &str,
    status: &str,
    exit_code: Option<i32>,
    verification_status: &str,
    after: &Value,
    verification: &Value,
    result_summary: &str,
) -> Result<(), String> {
    let mut args = vec![
        "operation".to_owned(),
        "finish".to_owned(),
        operation_id.to_owned(),
        "--status".to_owned(),
        status.to_owned(),
        "--verification-status".to_owned(),
        verification_status.to_owned(),
        "--after-json".to_owned(),
        after.to_string(),
        "--verification-json".to_owned(),
        verification.to_string(),
        "--result-summary".to_owned(),
        result_summary.chars().take(4096).collect(),
        "--json".to_owned(),
    ];

    if let Some(exit_code) = exit_code {
        let insert_at = args.len() - 1;
        args.splice(
            insert_at..insert_at,
            ["--exit-code".to_owned(), exit_code.to_string()],
        );
    }

    let _: OperationRecord = run_json(px_path, &args, "PX operation finish")?;
    Ok(())
}
