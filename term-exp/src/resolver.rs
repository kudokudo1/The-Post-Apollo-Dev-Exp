use crate::app::ActionChoiceItem;
use serde::Deserialize;
use std::{path::Path, process::Command};

#[derive(Debug, Deserialize)]
struct RepositoryRegistry {
    #[serde(default)]
    repositories: Vec<RepositoryRecord>,
}

#[derive(Debug, Deserialize)]
struct RepositoryRecord {
    alias: String,
    repository: String,
}

#[derive(Debug, Deserialize)]
struct RunRecord {
    #[serde(rename = "databaseId")]
    database_id: u64,
    #[serde(rename = "workflowName")]
    workflow_name: Option<String>,
    status: String,
    conclusion: Option<String>,
    #[serde(rename = "headBranch")]
    head_branch: Option<String>,
    #[serde(rename = "createdAt")]
    created_at: String,
}

#[derive(Debug, Deserialize)]
struct WorkflowRecord {
    #[serde(default)]
    name: String,
    #[serde(default)]
    path: String,
    #[serde(default)]
    state: String,
}

#[derive(Debug, Deserialize)]
struct RoomRecord {
    id: String,
    #[serde(default)]
    team: String,
    #[serde(default)]
    branch: String,
    #[serde(default)]
    repository: String,
    #[serde(default, rename = "doctorId")]
    doctor_id: String,
    #[serde(default, rename = "providerId")]
    provider_id: String,
}

#[derive(Debug, Deserialize)]
struct DoctorRecord {
    id: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    role: String,
    #[serde(default)]
    status: String,
}

#[derive(Debug, Deserialize)]
struct ProviderRecord {
    id: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    dialect: String,
    #[serde(default)]
    available: bool,
}

#[derive(Debug, Deserialize)]
struct SessionRecord {
    id: String,
    #[serde(default, rename = "roomId")]
    room_id: String,
    #[serde(default, rename = "doctorId")]
    doctor_id: String,
    #[serde(default, rename = "providerId")]
    provider_id: String,
    #[serde(default, rename = "workingDirectory")]
    working_directory: String,
    #[serde(default)]
    status: String,
}

#[derive(Debug, Deserialize)]
struct WorkflowTemplateRecord {
    id: String,
    #[serde(default)]
    summary: String,
}

#[derive(Debug, Deserialize)]
struct CheckpointRecord {
    id: String,
    #[serde(default, rename = "roomId")]
    room_id: String,
    #[serde(default, rename = "sessionId")]
    session_id: String,
    #[serde(default, rename = "doctorId")]
    doctor_id: String,
    #[serde(default)]
    kind: String,
    #[serde(default)]
    body: String,
    #[serde(default, rename = "createdAt")]
    created_at: String,
}

#[derive(Debug, Deserialize)]
struct RoomReportRecord {
    id: String,
    #[serde(default, rename = "sessionId")]
    session_id: String,
    #[serde(default, rename = "doctorId")]
    doctor_id: String,
    #[serde(default)]
    kind: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    branch: String,
    #[serde(default, rename = "headSha")]
    head_sha: String,
    #[serde(default, rename = "gitEvidenceStatus")]
    git_evidence_status: String,
    #[serde(default, rename = "createdAt")]
    created_at: String,
}

#[derive(Debug, Deserialize)]
struct ChartEntryRecord {
    id: String,
    #[serde(default)]
    kind: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    priority: i64,
    #[serde(default)]
    status: String,
    #[serde(default, rename = "createdAt")]
    created_at: String,
}

#[derive(Debug, Deserialize)]
struct BranchRegistry {
    #[serde(default, rename = "defaultBranch")]
    default_branch: String,
    #[serde(default)]
    branches: Vec<BranchRecord>,
}

#[derive(Debug, Deserialize)]
struct BranchRecord {
    name: String,
    #[serde(default)]
    head: String,
    #[serde(default)]
    protected: bool,
    #[serde(default, rename = "default")]
    is_default: bool,
    #[serde(default)]
    source: String,
}

#[derive(Debug, Deserialize)]
struct CommitRecord {
    sha: String,
    #[serde(default)]
    message: String,
    #[serde(default)]
    author: String,
    #[serde(default)]
    date: String,
}

#[derive(Debug, Deserialize)]
struct OperationRecord {
    id: String,
    #[serde(default, rename = "actionId")]
    action_id: String,
    #[serde(default)]
    mutation: String,
    #[serde(default)]
    recovery: String,
    #[serde(default)]
    status: String,
    #[serde(default, rename = "verificationStatus")]
    verification_status: String,
    #[serde(default, rename = "startedAt")]
    started_at: String,
}

#[derive(Debug, Deserialize)]
struct ToolChoiceRegistry {
    #[serde(default)]
    tools: Vec<ToolChoiceRecord>,
}

#[derive(Debug, Deserialize)]
struct ToolChoiceRecord {
    name: String,
    #[serde(default)]
    path: String,
    #[serde(default)]
    backend: String,
    #[serde(default)]
    environment: String,
}

pub(crate) fn repository_registry(px_path: &Path) -> Result<RepositoryRegistry, String> {
    load_choice_json(
        px_path,
        &["repos".to_owned(), "--json".to_owned()],
        "repository registry",
    )
}

pub(crate) fn repository_choices(px_path: &Path) -> Result<Vec<ActionChoiceItem>, String> {
    let registry = repository_registry(px_path)?;

    Ok(registry
        .repositories
        .into_iter()
        .map(|repository| ActionChoiceItem {
            value: repository.alias.clone(),
            label: repository.alias,
            detail: repository.repository,
        })
        .collect())
}

pub(crate) fn repository_slug(px_path: &Path, value: &str) -> Result<String, String> {
    let registry = repository_registry(px_path)?;

    Ok(registry
        .repositories
        .into_iter()
        .find(|repository| repository.alias == value)
        .map(|repository| repository.repository)
        .unwrap_or_else(|| value.to_owned()))
}

pub(crate) fn load_choice_json<T>(
    px_path: &Path,
    args: &[String],
    description: &str,
) -> Result<T, String>
where
    T: for<'de> Deserialize<'de>,
{
    let output = Command::new(px_path)
        .args(args)
        .output()
        .map_err(|error| format!("could not load {description}: {error}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
        let detail = if !stderr.is_empty() { stderr } else { stdout };

        return Err(if detail.is_empty() {
            format!("PX could not load {description}")
        } else {
            detail
        });
    }

    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("{description} returned invalid JSON: {error}"))
}

pub(crate) fn workflow_choices(px_path: &Path, repository: &str) -> Result<Vec<ActionChoiceItem>, String> {
    let rows: Vec<WorkflowRecord> = load_choice_json(
        px_path,
        &["workflows".to_owned(), repository.to_owned()],
        "workflows",
    )?;

    Ok(rows
        .into_iter()
        .map(|workflow| {
            let value = if workflow.path.is_empty() {
                workflow.name.clone()
            } else {
                workflow.path.clone()
            };
            let label = if workflow.name.is_empty() {
                value.clone()
            } else {
                workflow.name
            };
            let detail = if workflow.state.is_empty() {
                workflow.path
            } else if workflow.path.is_empty() {
                workflow.state
            } else {
                format!("{}  {}", workflow.path, workflow.state)
            };

            ActionChoiceItem {
                value,
                label,
                detail,
            }
        })
        .filter(|choice| !choice.value.is_empty())
        .collect())
}

pub(crate) fn run_choices(px_path: &Path, repository: &str) -> Result<Vec<ActionChoiceItem>, String> {
    let runs: Vec<RunRecord> = load_choice_json(
        px_path,
        &[
            "runs".to_owned(),
            repository.to_owned(),
            "20".to_owned(),
        ],
        "workflow runs",
    )?;

    Ok(runs
        .into_iter()
        .map(|run| {
            let workflow = run
                .workflow_name
                .unwrap_or_else(|| format!("Run {}", run.database_id));
            let conclusion = run.conclusion.unwrap_or_else(|| "-".to_owned());
            let branch = run.head_branch.unwrap_or_else(|| "-".to_owned());

            ActionChoiceItem {
                value: run.database_id.to_string(),
                label: workflow,
                detail: format!(
                    "#{}  {} / {}  {}  {}",
                    run.database_id, run.status, conclusion, branch, run.created_at
                ),
            }
        })
        .collect())
}

pub(crate) fn room_choices(
    px_path: &Path,
    repository: Option<&str>,
) -> Result<Vec<ActionChoiceItem>, String> {
    let rows: Vec<RoomRecord> = load_choice_json(
        px_path,
        &[
            "hospital".to_owned(),
            "rooms".to_owned(),
            "--json".to_owned(),
        ],
        "Hospital rooms",
    )?;
    let repository = match repository {
        Some(value) => Some(repository_slug(px_path, value)?),
        None => None,
    };

    Ok(rows
        .into_iter()
        .filter(|room| {
            repository
                .as_deref()
                .map(|wanted| room.repository.is_empty() || room.repository == wanted)
                .unwrap_or(true)
        })
        .map(|room| {
            let label = if room.team.is_empty() {
                room.id.clone()
            } else {
                room.team.clone()
            };
            let mut details = Vec::new();

            if !room.repository.is_empty() {
                details.push(room.repository);
            }
            if !room.branch.is_empty() {
                details.push(room.branch);
            }
            if !room.doctor_id.is_empty() {
                details.push(format!("doctor {}", room.doctor_id));
            }
            if !room.provider_id.is_empty() {
                details.push(format!("provider {}", room.provider_id));
            }

            ActionChoiceItem {
                value: room.id,
                label,
                detail: details.join("  "),
            }
        })
        .collect())
}

pub(crate) fn doctor_choices(px_path: &Path) -> Result<Vec<ActionChoiceItem>, String> {
    let rows: Vec<DoctorRecord> = load_choice_json(
        px_path,
        &[
            "hospital".to_owned(),
            "doctors".to_owned(),
            "--json".to_owned(),
        ],
        "Hospital doctors",
    )?;

    Ok(rows
        .into_iter()
        .map(|doctor| {
            let label = if doctor.name.is_empty() {
                doctor.id.clone()
            } else {
                doctor.name
            };
            let detail = [doctor.role, doctor.status]
                .into_iter()
                .filter(|value| !value.is_empty())
                .collect::<Vec<_>>()
                .join("  ");

            ActionChoiceItem {
                value: doctor.id,
                label,
                detail,
            }
        })
        .collect())
}

pub(crate) fn provider_choices(px_path: &Path) -> Result<Vec<ActionChoiceItem>, String> {
    let rows: Vec<ProviderRecord> = load_choice_json(
        px_path,
        &[
            "agent".to_owned(),
            "providers".to_owned(),
            "--json".to_owned(),
        ],
        "AI providers",
    )?;

    Ok(rows
        .into_iter()
        .map(|provider| {
            let label = if provider.name.is_empty() {
                provider.id.clone()
            } else {
                provider.name
            };
            let availability = if provider.available {
                "READY"
            } else {
                "UNAVAILABLE"
            };
            let detail = if provider.dialect.is_empty() {
                availability.to_owned()
            } else {
                format!("{availability}  {}", provider.dialect)
            };

            ActionChoiceItem {
                value: provider.id,
                label,
                detail,
            }
        })
        .collect())
}

pub(crate) fn session_choices(
    px_path: &Path,
    room: Option<&str>,
) -> Result<Vec<ActionChoiceItem>, String> {
    let mut args = vec!["hospital".to_owned(), "sessions".to_owned()];

    if let Some(room) = room.filter(|value| !value.is_empty()) {
        args.extend(["--room-id".to_owned(), room.to_owned()]);
    }

    args.push("--json".to_owned());

    let rows: Vec<SessionRecord> = load_choice_json(px_path, &args, "Doctor sessions")?;

    Ok(rows
        .into_iter()
        .map(|session| {
            let mut details = Vec::new();

            if !session.room_id.is_empty() {
                details.push(format!("room {}", session.room_id));
            }
            if !session.doctor_id.is_empty() {
                details.push(format!("doctor {}", session.doctor_id));
            }
            if !session.provider_id.is_empty() {
                details.push(format!("provider {}", session.provider_id));
            }
            if !session.status.is_empty() {
                details.push(session.status);
            }
            if !session.working_directory.is_empty() {
                details.push(session.working_directory);
            }

            ActionChoiceItem {
                value: session.id.clone(),
                label: session.id,
                detail: details.join("  "),
            }
        })
        .collect())
}

pub(crate) fn workflow_template_choices(px_path: &Path) -> Result<Vec<ActionChoiceItem>, String> {
    let rows: Vec<WorkflowTemplateRecord> = load_choice_json(
        px_path,
        &["templates".to_owned()],
        "workflow templates",
    )?;

    Ok(rows
        .into_iter()
        .map(|template| ActionChoiceItem {
            value: template.id.clone(),
            label: template.id,
            detail: template.summary,
        })
        .collect())
}

pub(crate) fn checkpoint_choices(px_path: &Path, room: &str) -> Result<Vec<ActionChoiceItem>, String> {
    let rows: Vec<CheckpointRecord> = load_choice_json(
        px_path,
        &[
            "hospital".to_owned(),
            "checkpoints".to_owned(),
            room.to_owned(),
            "--limit".to_owned(),
            "50".to_owned(),
            "--json".to_owned(),
        ],
        "Room checkpoints",
    )?;

    Ok(rows
        .into_iter()
        .rev()
        .map(|checkpoint| {
            let mut details = Vec::new();

            if !checkpoint.kind.is_empty() {
                details.push(checkpoint.kind.clone());
            }
            if !checkpoint.doctor_id.is_empty() {
                details.push(format!("doctor {}", checkpoint.doctor_id));
            }
            if !checkpoint.session_id.is_empty() {
                details.push(format!("session {}", checkpoint.session_id));
            }
            if !checkpoint.created_at.is_empty() {
                details.push(checkpoint.created_at);
            }

            let preview = checkpoint.body.lines().next().unwrap_or("").trim();
            let label = if preview.is_empty() {
                format!("#{}", checkpoint.id)
            } else {
                format!("#{}  {}", checkpoint.id, preview)
            };

            ActionChoiceItem {
                value: checkpoint.id,
                label,
                detail: details.join("  "),
            }
        })
        .collect())
}

pub(crate) fn report_choices(px_path: &Path, room: &str) -> Result<Vec<ActionChoiceItem>, String> {
    let rows: Vec<RoomReportRecord> = load_choice_json(
        px_path,
        &[
            "hospital".to_owned(),
            "room-reports".to_owned(),
            room.to_owned(),
            "--limit".to_owned(),
            "50".to_owned(),
            "--json".to_owned(),
        ],
        "Room reports",
    )?;

    Ok(rows
        .into_iter()
        .rev()
        .map(|report| {
            let title = if report.title.is_empty() {
                report.kind.clone()
            } else {
                report.title
            };
            let mut details = Vec::new();

            if !report.doctor_id.is_empty() {
                details.push(format!("doctor {}", report.doctor_id));
            }
            if !report.session_id.is_empty() {
                details.push(format!("session {}", report.session_id));
            }
            if !report.branch.is_empty() {
                details.push(report.branch);
            }
            if !report.head_sha.is_empty() {
                details.push(report.head_sha.chars().take(8).collect());
            }
            if !report.git_evidence_status.is_empty() {
                details.push(report.git_evidence_status);
            }
            if !report.created_at.is_empty() {
                details.push(report.created_at);
            }

            ActionChoiceItem {
                value: report.id.clone(),
                label: format!("#{}  {}", report.id, title),
                detail: details.join("  "),
            }
        })
        .collect())
}

pub(crate) fn chart_entry_choices(px_path: &Path, room: &str) -> Result<Vec<ActionChoiceItem>, String> {
    let rows: Vec<ChartEntryRecord> = load_choice_json(
        px_path,
        &[
            "hospital".to_owned(),
            "chart-entries".to_owned(),
            "--scope".to_owned(),
            "ROOM".to_owned(),
            "--room-id".to_owned(),
            room.to_owned(),
            "--status".to_owned(),
            "ALL".to_owned(),
            "--limit".to_owned(),
            "200".to_owned(),
            "--json".to_owned(),
        ],
        "Room Chart entries",
    )?;

    Ok(rows
        .into_iter()
        .map(|entry| {
            let label_text = if entry.title.is_empty() {
                entry.kind.clone()
            } else {
                entry.title
            };
            let mut details = vec![
                entry.kind,
                format!("P{}", entry.priority),
                entry.status,
            ];

            if !entry.created_at.is_empty() {
                details.push(entry.created_at);
            }

            ActionChoiceItem {
                value: entry.id.clone(),
                label: format!("#{}  {}", entry.id, label_text),
                detail: details
                    .into_iter()
                    .filter(|value| !value.is_empty())
                    .collect::<Vec<_>>()
                    .join("  "),
            }
        })
        .collect())
}

pub(crate) fn branch_choices(px_path: &Path, repository: &str) -> Result<Vec<ActionChoiceItem>, String> {
    let registry: BranchRegistry = load_choice_json(
        px_path,
        &["branches".to_owned(), repository.to_owned()],
        "repository branches",
    )?;
    let default_branch = registry.default_branch;

    Ok(registry
        .branches
        .into_iter()
        .map(|branch| {
            let mut details = Vec::new();

            if branch.is_default || branch.name == default_branch {
                details.push("DEFAULT".to_owned());
            }
            if branch.protected {
                details.push("PROTECTED".to_owned());
            }
            if !branch.source.is_empty() {
                details.push(branch.source.to_uppercase());
            }
            if !branch.head.is_empty() {
                details.push(branch.head.chars().take(8).collect());
            }

            ActionChoiceItem {
                value: branch.name.clone(),
                label: branch.name,
                detail: details.join("  "),
            }
        })
        .collect())
}

pub(crate) fn commit_choices(
    px_path: &Path,
    repository: &str,
    reference: Option<&str>,
) -> Result<Vec<ActionChoiceItem>, String> {
    let mut args = vec!["commits".to_owned(), repository.to_owned()];

    if let Some(reference) = reference.filter(|value| !value.is_empty()) {
        args.push(reference.to_owned());
    } else {
        args.push(String::new());
    }

    args.push("30".to_owned());

    let rows: Vec<CommitRecord> = load_choice_json(px_path, &args, "repository commits")?;

    Ok(rows
        .into_iter()
        .map(|commit| {
            let short: String = commit.sha.chars().take(8).collect();
            let mut details = Vec::new();

            if !commit.author.is_empty() {
                details.push(commit.author);
            }
            if !commit.date.is_empty() {
                details.push(commit.date);
            }

            ActionChoiceItem {
                value: commit.sha,
                label: if commit.message.is_empty() {
                    short
                } else {
                    format!("{short}  {}", commit.message)
                },
                detail: details.join("  "),
            }
        })
        .collect())
}


pub(crate) fn operation_choices(px_path: &Path) -> Result<Vec<ActionChoiceItem>, String> {
    let rows: Vec<OperationRecord> = load_choice_json(
        px_path,
        &[
            "operations".to_owned(),
            "--limit".to_owned(),
            "100".to_owned(),
            "--json".to_owned(),
        ],
        "PX operation journal",
    )?;

    Ok(rows
        .into_iter()
        .map(|operation| {
            let mut details = Vec::new();

            if !operation.status.is_empty() {
                details.push(operation.status);
            }
            if !operation.mutation.is_empty() {
                details.push(operation.mutation.to_uppercase());
            }
            if !operation.recovery.is_empty() {
                details.push(operation.recovery);
            }
            if !operation.verification_status.is_empty()
                && operation.verification_status != "NOT_RUN"
            {
                details.push(format!("VERIFY {}", operation.verification_status));
            }
            if !operation.started_at.is_empty() {
                details.push(operation.started_at);
            }

            ActionChoiceItem {
                value: operation.id.clone(),
                label: if operation.action_id.is_empty() {
                    operation.id
                } else {
                    format!("{}  {}", operation.id, operation.action_id)
                },
                detail: details.join("  "),
            }
        })
        .collect())
}

pub(crate) fn command_choices(px_path: &Path) -> Result<Vec<ActionChoiceItem>, String> {
    let registry: ToolChoiceRegistry = load_choice_json(
        px_path,
        &["tools".to_owned(), "--json".to_owned()],
        "tool registry",
    )?;
    let mut by_name = std::collections::BTreeMap::<String, ToolChoiceRecord>::new();

    for tool in registry.tools {
        let rank = |backend: &str| match backend {
            "native" => 0,
            "toolbox" => 1,
            "distrobox" => 2,
            _ => 9,
        };

        match by_name.get(&tool.name) {
            Some(current) if rank(&current.backend) <= rank(&tool.backend) => {}
            _ => {
                by_name.insert(tool.name.clone(), tool);
            }
        }
    }

    Ok(by_name
        .into_values()
        .map(|tool| {
            let detail = [tool.backend, tool.environment, tool.path]
                .into_iter()
                .filter(|value| !value.is_empty())
                .collect::<Vec<_>>()
                .join("  ");

            ActionChoiceItem {
                value: tool.name.clone(),
                label: tool.name,
                detail,
            }
        })
        .collect())
}
