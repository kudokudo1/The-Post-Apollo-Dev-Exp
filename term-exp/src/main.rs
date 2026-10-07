mod app;
mod journal;
mod resolver;

use app::{ActionChoiceItem, App, Mode, SearchScope};
use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Wrap},
    Frame, Terminal,
};
use serde::Deserialize;
use std::{
    collections::BTreeMap,
    env,
    io::{self, Stdout},
    path::{Path, PathBuf},
    process::Command,
    time::Duration,
};

const BG: Color = Color::Rgb(0x1B, 0x06, 0x23);
const FG: Color = Color::Rgb(0xDC, 0xF3, 0xFA);
const CYAN: Color = Color::Rgb(0x55, 0xCF, 0xCA);
const ORANGE: Color = Color::Rgb(0xF2, 0xBE, 0x4E);
const MAGENTA: Color = Color::Rgb(0xC7, 0x4E, 0xC7);

type PxTerminal = Terminal<CrosstermBackend<Stdout>>;

#[derive(Debug, Deserialize)]
struct ActionRegistry {
    version: u64,
    #[serde(default)]
    actions: Vec<Action>,
}

#[derive(Debug, Deserialize)]
struct Action {
    id: String,
    title: String,
    category: String,
    summary: String,
    command: Vec<String>,
    #[serde(default)]
    arguments: Vec<ActionArgument>,
    mutation: String,
    #[serde(default)]
    recovery: String,
    #[serde(default, rename = "executionPolicy")]
    execution_policy: String,
    #[serde(default)]
    keywords: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct ActionArgument {
    name: String,
    required: bool,
    kind: String,
    #[serde(default)]
    choices: Vec<String>,
    #[serde(default, rename = "dependsOn")]
    depends_on: BTreeMap<String, String>,
}

#[derive(Debug, Deserialize)]
struct ToolRegistry {
    version: u64,
    counts: ToolCounts,
    #[serde(default)]
    environments: Vec<Environment>,
    #[serde(default)]
    tools: Vec<Tool>,
}

#[derive(Debug, Deserialize)]
struct ToolCounts {
    host: usize,
    toolbox: usize,
    total: usize,
    matched: usize,
}

#[derive(Debug, Deserialize)]
struct Environment {
    id: String,
    kind: String,
    status: String,
    #[serde(rename = "toolCount")]
    tool_count: usize,
    #[serde(default)]
    error: String,
}

#[derive(Debug, Deserialize)]
struct Tool {
    name: String,
    path: String,
    backend: String,
    environment: String,
}

struct Model {
    actions: ActionRegistry,
    tools: ToolRegistry,
    px_path: PathBuf,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum SearchKind {
    Action,
    Tool,
}

#[derive(Clone, Debug)]
struct SearchItem {
    kind: SearchKind,
    key: String,
    title: String,
    subtitle: String,
    score: i64,
}

#[derive(Debug, Deserialize)]
struct ResolveResult {
    status: String,
    selected: Option<ResolvedTool>,
}

#[derive(Debug, Deserialize)]
struct HospitalPrepareResult {
    #[serde(default)]
    action: String,
    #[serde(default)]
    mode: String,
    #[serde(default)]
    branch: String,
    #[serde(default)]
    head: String,
    #[serde(default)]
    base: String,
    #[serde(default, rename = "base_head")]
    base_head: String,
}

#[derive(Debug, Deserialize)]
struct MutationPreflightResult {
    #[serde(default)]
    allowed: bool,
    #[serde(default)]
    summary: String,
    #[serde(default)]
    reason: String,
    #[serde(default)]
    token: String,
}

#[derive(Debug, Deserialize)]
struct ResolvedTool {
    name: String,
    backend: String,
    environment: String,
    invocation: Vec<String>,
}

struct TerminalGuard {
    terminal: PxTerminal,
}

impl TerminalGuard {
    fn enter() -> io::Result<Self> {
        enable_raw_mode()?;

        let mut stdout = io::stdout();
        if let Err(error) = execute!(stdout, EnterAlternateScreen) {
            let _ = disable_raw_mode();
            return Err(error);
        }

        let backend = CrosstermBackend::new(stdout);
        let mut terminal = match Terminal::new(backend) {
            Ok(terminal) => terminal,
            Err(error) => {
                let _ = disable_raw_mode();
                return Err(error);
            }
        };

        terminal.clear()?;
        terminal.hide_cursor()?;

        Ok(Self { terminal })
    }

    fn suspend(&mut self) -> io::Result<()> {
        disable_raw_mode()?;
        execute!(self.terminal.backend_mut(), LeaveAlternateScreen)?;
        self.terminal.show_cursor()?;
        Ok(())
    }

    fn resume(&mut self) -> io::Result<()> {
        enable_raw_mode()?;
        execute!(self.terminal.backend_mut(), EnterAlternateScreen)?;
        self.terminal.hide_cursor()?;
        self.terminal.clear()?;
        Ok(())
    }
}

impl Drop for TerminalGuard {
    fn drop(&mut self) {
        let _ = disable_raw_mode();
        let _ = execute!(self.terminal.backend_mut(), LeaveAlternateScreen);
        let _ = self.terminal.show_cursor();
    }
}

fn main() {
    let code = match run() {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("PX // TERM EXP: {error}");
            1
        }
    };

    std::process::exit(code);
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let px_path = resolve_px_path();
    let actions: ActionRegistry = load_json(&px_path, &["actions", "--json"])?;
    let tools: ToolRegistry = load_json(&px_path, &["tools", "--json"])?;

    let model = Model {
        actions,
        tools,
        px_path,
    };

    let mut app = App::new();
    let mut guard = TerminalGuard::enter()?;

    while !app.should_quit {
        guard.terminal.draw(|frame| draw(frame, &app, &model))?;

        if !event::poll(Duration::from_millis(250))? {
            continue;
        }

        let Event::Key(key) = event::read()? else {
            continue;
        };

        if key.kind != KeyEventKind::Press && key.kind != KeyEventKind::Repeat {
            continue;
        }

        if key.modifiers.contains(KeyModifiers::CONTROL) && key.code == KeyCode::Char('c') {
            app.should_quit = true;
            continue;
        }

        handle_key(&mut guard, &mut app, key, &model)?;
    }

    Ok(())
}

fn handle_key(
    guard: &mut TerminalGuard,
    app: &mut App,
    key: KeyEvent,
    model: &Model,
) -> io::Result<()> {
    match &app.mode {
        Mode::Home => match key.code {
            KeyCode::Char('q') | KeyCode::Esc => app.should_quit = true,
            KeyCode::Char(' ') => app.open_leader(),
            KeyCode::Char('/') => app.open_search(SearchScope::All),
            _ => {}
        },

        Mode::Leader => {
            let entries = leader_entries(model);

            match key.code {
                KeyCode::Esc | KeyCode::Backspace => app.home(),
                KeyCode::Char('/') => app.open_search(SearchScope::All),
                KeyCode::Down | KeyCode::Char('j') => {
                    App::next(&mut app.leader_selected, entries.len())
                }
                KeyCode::Up | KeyCode::Char('k') => {
                    App::previous(&mut app.leader_selected, entries.len())
                }
                KeyCode::Enter => {
                    if let Some((_, scope, _)) = entries.get(app.leader_selected) {
                        app.open_search(scope.clone());
                    }
                }
                KeyCode::Char('a') => app.open_search(SearchScope::Actions),
                KeyCode::Char('t') => app.open_search(SearchScope::Tools),
                KeyCode::Char('p') => {
                    app.open_search(SearchScope::Category("PX".to_owned()))
                }
                KeyCode::Char('h') => {
                    app.open_search(SearchScope::Category("Hospital".to_owned()))
                }
                KeyCode::Char('i') => {
                    app.open_search(SearchScope::Category("AI".to_owned()))
                }
                KeyCode::Char('g') => {
                    app.open_search(SearchScope::Category("GitHub".to_owned()))
                }
                KeyCode::Char('w') => {
                    app.open_search(SearchScope::Category("Workflow".to_owned()))
                }
                KeyCode::Char('q') => app.should_quit = true,
                _ => {}
            }
        }

        Mode::Search => {
            let results = search_results(model, &app.search_scope, &app.query);

            match key.code {
                KeyCode::Esc => app.home(),
                KeyCode::Backspace => {
                    app.query.pop();
                    app.search_selected = 0;
                }
                KeyCode::Down => App::next(&mut app.search_selected, results.len()),
                KeyCode::Up => App::previous(&mut app.search_selected, results.len()),
                KeyCode::Enter => {
                    if let Some(item) = results.get(app.search_selected) {
                        match item.kind {
                            SearchKind::Action => {
                                begin_or_run_action(app, model, &item.key);
                            }
                            SearchKind::Tool => {
                                launch_specialist(guard, app, model, &item.key)?;
                            }
                        }
                    }
                }
                KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                    app.query.clear();
                    app.search_selected = 0;
                }
                KeyCode::Char(character)
                    if !key.modifiers.contains(KeyModifiers::CONTROL)
                        && !key.modifiers.contains(KeyModifiers::ALT) =>
                {
                    app.query.push(character);
                    app.search_selected = 0;
                }
                _ => {}
            }
        }

        Mode::ActionPrompt => {
            let Some(action_id) = app.pending_action_id.clone() else {
                app.back_to_search();
                return Ok(());
            };
            let Some(action) = action_by_id(model, &action_id) else {
                app.status = Some(format!("Action disappeared: {action_id}"));
                app.back_to_search();
                return Ok(());
            };

            match key.code {
                KeyCode::Esc => app.back_to_search(),
                KeyCode::Backspace => {
                    app.prompt_buffer.pop();
                    app.status = None;
                }
                KeyCode::Enter => {
                    if let Some(argument) = action.arguments.get(app.prompt_index) {
                        let value = app.prompt_buffer.trim().to_owned();

                        if argument.required && value.is_empty() {
                            app.status = Some(format!("{} is required", argument.name));
                            return Ok(());
                        }

                        if let Err(error) = validate_typed_argument(argument, &value) {
                            app.status = Some(error);
                            return Ok(());
                        }

                        commit_argument_value(app, model, action, value);
                    }
                }
                KeyCode::Char(character)
                    if !key.modifiers.contains(KeyModifiers::CONTROL)
                        && !key.modifiers.contains(KeyModifiers::ALT) =>
                {
                    app.prompt_buffer.push(character);
                    app.status = None;
                }
                _ => {}
            }
        }

        Mode::ActionChoice => {
            let Some(action_id) = app.pending_action_id.clone() else {
                app.back_to_search();
                return Ok(());
            };
            let Some(action) = action_by_id(model, &action_id) else {
                app.back_to_search();
                app.status = Some(format!("Action disappeared: {action_id}"));
                return Ok(());
            };
            let visible = filtered_choice_indices(app);

            match key.code {
                KeyCode::Esc => app.back_to_search(),
                KeyCode::Backspace => {
                    app.choice_query.pop();
                    app.choice_selected = 0;
                }
                KeyCode::Down => App::next(&mut app.choice_selected, visible.len()),
                KeyCode::Up => App::previous(&mut app.choice_selected, visible.len()),
                KeyCode::Enter => {
                    if let Some(index) = visible.get(app.choice_selected) {
                        if let Some(choice) = app.choice_items.get(*index) {
                            let value = choice.value.clone();
                            commit_argument_value(app, model, action, value);
                        }
                    }
                }
                KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                    app.choice_query.clear();
                    app.choice_selected = 0;
                }
                KeyCode::Char(character)
                    if !key.modifiers.contains(KeyModifiers::CONTROL)
                        && !key.modifiers.contains(KeyModifiers::ALT) =>
                {
                    app.choice_query.push(character);
                    app.choice_selected = 0;
                }
                _ => {}
            }
        }

        Mode::MutationPreview => {
            let Some(action_id) = app.pending_action_id.clone() else {
                app.back_to_search();
                return Ok(());
            };
            let Some(action) = action_by_id(model, &action_id) else {
                app.back_to_search();
                app.status = Some(format!("Action disappeared: {action_id}"));
                return Ok(());
            };

            match key.code {
                KeyCode::Esc | KeyCode::Char('q') => app.back_to_search(),
                KeyCode::Enter => {
                    if mutation_requires_arm(action) {
                        match arm_mutation(app, model, action) {
                            Ok(()) => app.open_mutation_confirm(),
                            Err(error) => {
                                app.mutation_armed = false;
                                app.mutation_preflight.clear();
                                app.status = Some(format!("ARM REFUSED // {error}"));
                            }
                        }
                    } else if mutation_execution_enabled(action) {
                        app.open_mutation_confirm();
                    } else {
                        app.status = Some(format!(
                            "{} mutations are preview-only until their execution policy lands",
                            action.mutation.to_uppercase()
                        ));
                    }
                }
                _ => {}
            }
        }

        Mode::MutationConfirm => {
            let Some(action_id) = app.pending_action_id.clone() else {
                app.back_to_search();
                return Ok(());
            };
            let Some(action) = action_by_id(model, &action_id) else {
                app.back_to_search();
                app.status = Some(format!("Action disappeared: {action_id}"));
                return Ok(());
            };
            let expected = mutation_confirmation_phrase(action);

            match key.code {
                KeyCode::Esc => app.return_to_mutation_preview(),
                KeyCode::Backspace => {
                    app.mutation_confirm_buffer.pop();
                    app.status = None;
                }
                KeyCode::Enter => {
                    if app
                        .mutation_confirm_buffer
                        .trim()
                        .eq_ignore_ascii_case(expected)
                    {
                        run_mutation_action(app, model, action);
                    } else {
                        app.status = Some(format!(
                            "Type {expected} exactly to execute this {} mutation",
                            action.mutation
                        ));
                    }
                }
                KeyCode::Char(character)
                    if !key.modifiers.contains(KeyModifiers::CONTROL)
                        && !key.modifiers.contains(KeyModifiers::ALT) =>
                {
                    app.mutation_confirm_buffer.push(character);
                    app.status = None;
                }
                _ => {}
            }
        }

        Mode::Output => match key.code {
            KeyCode::Esc => app.back_to_search(),
            KeyCode::Char('q') => app.home(),
            KeyCode::Down | KeyCode::Char('j') => {
                app.output_scroll = app.output_scroll.saturating_add(1)
            }
            KeyCode::Up | KeyCode::Char('k') => {
                app.output_scroll = app.output_scroll.saturating_sub(1)
            }
            KeyCode::PageDown => {
                app.output_scroll = app.output_scroll.saturating_add(10)
            }
            KeyCode::PageUp => {
                app.output_scroll = app.output_scroll.saturating_sub(10)
            }
            _ => {}
        },
    }

    Ok(())
}

fn is_specialist_tool(name: &str) -> bool {
    matches!(name, "lazygit" | "nvim" | "btop" | "zellij" | "fzf")
}

fn resolve_tool(model: &Model, name: &str) -> Result<ResolvedTool, String> {
    let output = Command::new(&model.px_path)
        .args(["which", name, "--json"])
        .output()
        .map_err(|error| format!("resolver launch failed: {error}"))?;

    let result: ResolveResult = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("resolver returned invalid JSON: {error}"))?;

    if !output.status.success() || result.status != "FOUND" {
        let detail = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        return Err(if detail.is_empty() {
            format!("PX could not resolve {name}")
        } else {
            detail
        });
    }

    result
        .selected
        .ok_or_else(|| format!("PX resolved {name} without an execution target"))
}

fn launch_specialist(
    guard: &mut TerminalGuard,
    app: &mut App,
    model: &Model,
    name: &str,
) -> io::Result<()> {
    if !is_specialist_tool(name) {
        app.status = Some(format!(
            "{name} is visible in Find Anything, but direct delegation is not enabled yet"
        ));
        return Ok(());
    }

    let resolved = match resolve_tool(model, name) {
        Ok(resolved) => resolved,
        Err(error) => {
            app.status = Some(format!("{name}: {error}"));
            return Ok(());
        }
    };

    let Some((program, args)) = resolved.invocation.split_first() else {
        app.status = Some(format!("{name}: resolver returned an empty invocation"));
        return Ok(());
    };

    guard.suspend()?;
    let launch_result = Command::new(program).args(args).status();
    let resume_result = guard.resume();

    if let Err(error) = resume_result {
        return Err(error);
    }

    app.status = Some(match launch_result {
        Ok(status) if status.success() => format!(
            "{} returned from {}",
            resolved.name, resolved.environment
        ),
        Ok(status) => format!(
            "{} exited with {} through {}",
            resolved.name,
            status
                .code()
                .map(|code| code.to_string())
                .unwrap_or_else(|| "signal".to_owned()),
            resolved.backend
        ),
        Err(error) => format!(
            "{} failed through {}: {}",
            resolved.name, resolved.backend, error
        ),
    });

    Ok(())
}

fn action_by_id<'a>(model: &'a Model, id: &str) -> Option<&'a Action> {
    model.actions.actions.iter().find(|action| action.id == id)
}

fn expand_action_command(action: &Action, values: &[String]) -> Result<Vec<String>, String> {
    let mut by_name = BTreeMap::<&str, &str>::new();

    for (argument, value) in action.arguments.iter().zip(values.iter()) {
        by_name.insert(argument.name.as_str(), value.as_str());
    }

    let mut command = Vec::new();

    for token in &action.command {
        if let Some(name) = token
            .strip_prefix('{')
            .and_then(|value| value.strip_suffix('}'))
        {
            let optional = name.ends_with('?');
            let name = name.trim_end_matches('?');
            let value = by_name.get(name).copied().unwrap_or("");

            if value.is_empty() {
                if optional {
                    continue;
                }

                return Err(format!("missing required argument: {name}"));
            }

            command.push(value.to_owned());
        } else {
            command.push(token.clone());
        }
    }

    Ok(command)
}

fn display_output(stdout: &[u8], stderr: &[u8]) -> String {
    let stdout_text = String::from_utf8_lossy(stdout).trim().to_owned();
    let stderr_text = String::from_utf8_lossy(stderr).trim().to_owned();

    let mut sections = Vec::new();

    if !stdout_text.is_empty() {
        if let Ok(value) = serde_json::from_str::<serde_json::Value>(&stdout_text) {
            sections.push(
                serde_json::to_string_pretty(&value)
                    .unwrap_or_else(|_| stdout_text.clone()),
            );
        } else {
            sections.push(stdout_text);
        }
    }

    if !stderr_text.is_empty() {
        sections.push(format!("STDERR\n{stderr_text}"));
    }

    if sections.is_empty() {
        "(command completed with no output)".to_owned()
    } else {
        sections.join("\n\n")
    }
}

fn run_read_action(app: &mut App, model: &Model, action: &Action, values: &[String]) {
    if action.mutation != "read" {
        app.status = Some(format!(
            "{} is a {} action; TERM EXP will not execute it without a mutation policy",
            action.title, action.mutation
        ));
        return;
    }

    let args = match expand_action_command(action, values) {
        Ok(args) => args,
        Err(error) => {
            app.status = Some(error);
            return;
        }
    };

    let output = match Command::new(&model.px_path).args(&args).output() {
        Ok(output) => output,
        Err(error) => {
            app.open_output(
                format!("{} // ERROR", action.title),
                format!("could not launch PX action: {error}"),
            );
            return;
        }
    };

    let mut text = display_output(&output.stdout, &output.stderr);

    if !output.status.success() {
        let code = output
            .status
            .code()
            .map(|value| value.to_string())
            .unwrap_or_else(|| "signal".to_owned());
        text = format!("EXIT {code}\n\n{text}");
    }

    app.open_output(action.title.clone(), text);
}

fn selected_argument_named<'a>(
    action: &Action,
    values: &'a [String],
    name: &str,
) -> Option<&'a str> {
    action
        .arguments
        .iter()
        .position(|argument| argument.name == name)
        .and_then(|index| values.get(index))
        .map(String::as_str)
        .filter(|value| !value.is_empty())
}

fn argument_dependency_values(
    action: &Action,
    values: &[String],
    argument: &ActionArgument,
) -> BTreeMap<String, String> {
    argument
        .depends_on
        .iter()
        .filter_map(|(role, argument_name)| {
            selected_argument_named(action, values, argument_name)
                .map(|value| (role.clone(), value.to_owned()))
        })
        .collect()
}

fn known_value_choices(
    model: &Model,
    action: &Action,
    values: &[String],
    argument: &ActionArgument,
) -> Result<Option<Vec<ActionChoiceItem>>, String> {
    let dependencies = argument_dependency_values(action, values, argument);
    let repository = dependencies.get("repository").map(String::as_str);
    let room = dependencies.get("room").map(String::as_str);
    let reference = dependencies.get("reference").map(String::as_str);

    match argument.kind.as_str() {
        "repository" => resolver::repository_choices(&model.px_path).map(Some),
        "workflow" => {
            let repository =
                repository.ok_or_else(|| "select a repository first".to_owned())?;
            resolver::workflow_choices(&model.px_path, repository).map(Some)
        }
        "run" => {
            let repository =
                repository.ok_or_else(|| "select a repository first".to_owned())?;
            resolver::run_choices(&model.px_path, repository).map(Some)
        }
        "room" => resolver::room_choices(&model.px_path, repository).map(Some),
        "doctor" => resolver::doctor_choices(&model.px_path).map(Some),
        "provider" => resolver::provider_choices(&model.px_path).map(Some),
        "session" => resolver::session_choices(&model.px_path, room).map(Some),
        "checkpoint" => {
            let room = room.ok_or_else(|| "select a Room first".to_owned())?;
            resolver::checkpoint_choices(&model.px_path, room).map(Some)
        }
        "report" => {
            let room = room.ok_or_else(|| "select a Room first".to_owned())?;
            resolver::report_choices(&model.px_path, room).map(Some)
        }
        "chart_entry" => {
            let room = room.ok_or_else(|| "select a Room first".to_owned())?;
            resolver::chart_entry_choices(&model.px_path, room).map(Some)
        }
        "workflow_template" => resolver::workflow_template_choices(&model.px_path).map(Some),
        "command" => resolver::command_choices(&model.px_path).map(Some),
        "operation" => resolver::operation_choices(&model.px_path).map(Some),
        "branch" | "ref" => {
            let repository =
                repository.ok_or_else(|| "select a repository first".to_owned())?;
            resolver::branch_choices(&model.px_path, repository).map(Some)
        }
        "commit" => {
            let repository =
                repository.ok_or_else(|| "select a repository first".to_owned())?;
            resolver::commit_choices(&model.px_path, repository, reference).map(Some)
        }
        "enum" if !argument.choices.is_empty() => Ok(Some(
            argument
                .choices
                .iter()
                .map(|value| ActionChoiceItem {
                    value: value.clone(),
                    label: value.clone(),
                    detail: String::new(),
                })
                .collect(),
        )),
        _ => Ok(None),
    }
}

fn prepare_current_argument(app: &mut App, model: &Model, action: &Action) {
    let Some(argument) = action.arguments.get(app.prompt_index) else {
        return;
    };

    match known_value_choices(model, action, &app.prompt_values, argument) {
        Ok(Some(mut choices)) if !choices.is_empty() => {
            if !argument.required {
                choices.insert(
                    0,
                    ActionChoiceItem {
                        value: String::new(),
                        label: "(default / none)".to_owned(),
                        detail: "leave this optional value unset".to_owned(),
                    },
                );
            }
            app.open_choice(choices);
        }
        Ok(Some(_)) => {
            app.open_prompt();
            app.status = Some(format!(
                "No known {} values were found; type one manually",
                argument.kind
            ));
        }
        Ok(None) => app.open_prompt(),
        Err(error) => {
            app.open_prompt();
            app.status = Some(format!(
                "Could not load {} choices ({error}); type one manually",
                argument.kind
            ));
        }
    }
}

fn validate_typed_argument(argument: &ActionArgument, value: &str) -> Result<(), String> {
    if value.is_empty() {
        return Ok(());
    }

    match argument.kind.as_str() {
        "integer" => value
            .parse::<i64>()
            .map(|_| ())
            .map_err(|_| format!("{} must be an integer", argument.name)),
        "slug" => {
            let valid = value
                .chars()
                .next()
                .map(|first| first.is_ascii_lowercase() || first.is_ascii_digit())
                .unwrap_or(false)
                && value
                    .chars()
                    .all(|character| character.is_ascii_lowercase()
                        || character.is_ascii_digit()
                        || character == '-');

            if valid {
                Ok(())
            } else {
                Err(format!(
                    "{} must match [a-z0-9][a-z0-9-]*",
                    argument.name
                ))
            }
        }
        _ => Ok(()),
    }
}

fn mutation_requires_hospital_arm(action: &Action) -> bool {
    action.id == "hospital.integration.integrate"
}

fn mutation_uses_px_guard(action: &Action) -> bool {
    action.execution_policy == "px-guarded"
}

fn mutation_requires_arm(action: &Action) -> bool {
    mutation_requires_hospital_arm(action) || mutation_uses_px_guard(action)
}

fn mutation_execution_enabled(action: &Action) -> bool {
    action.mutation == "local" || mutation_requires_arm(action)
}

fn mutation_confirmation_phrase(action: &Action) -> &'static str {
    match action.mutation.as_str() {
        "local" => "LOCAL",
        "remote" => "REMOTE",
        "external" => "EXTERNAL",
        _ => "CONFIRM",
    }
}

fn validate_hospital_prepare(
    action: &Action,
    values: &[String],
    prepare: &HospitalPrepareResult,
) -> Result<String, String> {
    let expected_branch = selected_argument_named(action, values, "branch")
        .ok_or_else(|| "integration branch is missing".to_owned())?;
    let expected_head = selected_argument_named(action, values, "room_head")
        .ok_or_else(|| "integration Room HEAD is missing".to_owned())?;
    let expected_base = selected_argument_named(action, values, "base")
        .ok_or_else(|| "integration base branch is missing".to_owned())?;
    let expected_base_head = selected_argument_named(action, values, "base_head")
        .ok_or_else(|| "integration base HEAD is missing".to_owned())?;

    if !prepare.action.eq_ignore_ascii_case("prepare") {
        return Err(format!(
            "PX Room prepare returned unexpected action {}",
            prepare.action
        ));
    }
    if !prepare.mode.eq_ignore_ascii_case("FAST_FORWARD") {
        return Err(format!(
            "integration is not fast-forwardable (mode {})",
            prepare.mode
        ));
    }
    if prepare.branch != expected_branch {
        return Err("Room branch changed since selection".to_owned());
    }
    if prepare.head != expected_head {
        return Err("Room HEAD changed since selection".to_owned());
    }
    if prepare.base != expected_base {
        return Err("base branch changed since selection".to_owned());
    }
    if prepare.base_head != expected_base_head {
        return Err("base HEAD changed since selection".to_owned());
    }

    Ok(format!(
        "FAST_FORWARD ARMED // {}@{} -> {}@{}",
        expected_branch,
        expected_head.chars().take(8).collect::<String>(),
        expected_base,
        expected_base_head.chars().take(8).collect::<String>()
    ))
}

fn arm_hospital_integration(
    app: &mut App,
    model: &Model,
    action: &Action,
) -> Result<(), String> {
    let repository = selected_argument_named(action, &app.prompt_values, "repository")
        .ok_or_else(|| "integration repository is missing".to_owned())?;
    let team = selected_argument_named(action, &app.prompt_values, "team")
        .ok_or_else(|| "integration Room is missing".to_owned())?;

    let output = Command::new(&model.px_path)
        .args(["room", repository, team, "prepare"])
        .output()
        .map_err(|error| format!("could not run PX Room prepare: {error}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
        return Err(if !stderr.is_empty() {
            stderr
        } else if !stdout.is_empty() {
            stdout
        } else {
            "PX Room prepare failed".to_owned()
        });
    }

    let prepare: HospitalPrepareResult = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("PX Room prepare returned invalid JSON: {error}"))?;
    let summary = validate_hospital_prepare(action, &app.prompt_values, &prepare)?;

    app.mutation_armed = true;
    app.mutation_preflight = summary;
    app.mutation_preflight_token.clear();
    Ok(())
}

fn mutation_arguments_json(action: &Action, values: &[String]) -> String {
    let mut arguments = serde_json::Map::new();

    for (name, value) in mutation_argument_pairs(action, values) {
        arguments.insert(name, serde_json::Value::String(value));
    }

    serde_json::Value::Object(arguments).to_string()
}

fn px_guard_preflight(
    model: &Model,
    action: &Action,
    values: &[String],
) -> Result<MutationPreflightResult, String> {
    resolver::load_choice_json(
        &model.px_path,
        &[
            "mutation-preflight".to_owned(),
            action.id.clone(),
            mutation_arguments_json(action, values),
        ],
        "PX mutation preflight",
    )
}

fn arm_px_guarded_mutation(
    app: &mut App,
    model: &Model,
    action: &Action,
) -> Result<(), String> {
    let preflight = px_guard_preflight(model, action, &app.prompt_values)?;

    if !preflight.allowed {
        return Err(if !preflight.reason.is_empty() {
            preflight.reason
        } else if !preflight.summary.is_empty() {
            preflight.summary
        } else {
            "PX mutation preflight refused execution".to_owned()
        });
    }

    if preflight.token.is_empty() {
        return Err("PX mutation preflight returned no target token".to_owned());
    }

    app.mutation_armed = true;
    app.mutation_preflight = if preflight.summary.is_empty() {
        "PX GUARDED TARGET ARMED".to_owned()
    } else {
        preflight.summary
    };
    app.mutation_preflight_token = preflight.token;
    Ok(())
}

fn arm_mutation(app: &mut App, model: &Model, action: &Action) -> Result<(), String> {
    if mutation_requires_hospital_arm(action) {
        return arm_hospital_integration(app, model, action);
    }

    if mutation_uses_px_guard(action) {
        return arm_px_guarded_mutation(app, model, action);
    }

    Err("mutation has no arming policy".to_owned())
}

fn revalidate_px_guarded_mutation(
    app: &mut App,
    model: &Model,
    action: &Action,
) -> Result<(), String> {
    let preflight = px_guard_preflight(model, action, &app.prompt_values)?;

    if !preflight.allowed {
        return Err(if !preflight.reason.is_empty() {
            preflight.reason
        } else {
            "PX mutation preflight no longer permits execution".to_owned()
        });
    }

    if preflight.token.is_empty()
        || preflight.token != app.mutation_preflight_token
    {
        return Err("PX guarded target identity changed after confirmation".to_owned());
    }

    Ok(())
}

fn px_guard_verification(
    model: &Model,
    action: &Action,
    values: &[String],
) -> Result<serde_json::Value, String> {
    resolver::load_choice_json(
        &model.px_path,
        &[
            "mutation-verify".to_owned(),
            action.id.clone(),
            mutation_arguments_json(action, values),
        ],
        "PX mutation verification",
    )
}

fn hospital_integration_verify_args(
    action: &Action,
    values: &[String],
) -> Result<Vec<String>, String> {
    let repository = selected_argument_named(action, values, "repository")
        .ok_or_else(|| "verification repository is missing".to_owned())?;
    let team = selected_argument_named(action, values, "team")
        .ok_or_else(|| "verification Room is missing".to_owned())?;
    let base = selected_argument_named(action, values, "base")
        .ok_or_else(|| "verification base branch is missing".to_owned())?;
    let room_head = selected_argument_named(action, values, "room_head")
        .ok_or_else(|| "verification Room HEAD is missing".to_owned())?;

    Ok(vec![
        "verify".to_owned(),
        repository.to_owned(),
        team.to_owned(),
        base.to_owned(),
        room_head.to_owned(),
        room_head.to_owned(),
    ])
}

fn prepare_mutation_preview(app: &mut App, action: &Action, values: &[String]) {
    match expand_action_command(action, values) {
        Ok(args) => app.open_mutation_preview(args),
        Err(error) => app.status = Some(error),
    }
}

fn mutation_argument_pairs(action: &Action, values: &[String]) -> Vec<(String, String)> {
    action
        .arguments
        .iter()
        .enumerate()
        .map(|(index, argument)| {
            (
                argument.name.clone(),
                values.get(index).cloned().unwrap_or_default(),
            )
        })
        .collect()
}

fn journal_warning(result: Result<(), String>) -> String {
    match result {
        Ok(()) => String::new(),
        Err(error) => format!("\n\nJOURNAL WARNING\n{error}"),
    }
}

fn run_mutation_action(app: &mut App, model: &Model, action: &Action) {
    if !mutation_execution_enabled(action) {
        app.mode = Mode::MutationPreview;
        app.status = Some(format!(
            "{} execution remains locked for {} mutations",
            action.title, action.mutation
        ));
        return;
    }

    if mutation_requires_arm(action) && !app.mutation_armed {
        app.mode = Mode::MutationPreview;
        app.status = Some("REMOTE EXECUTION REFUSED // action is not armed".to_owned());
        return;
    }

    if mutation_uses_px_guard(action) {
        if let Err(error) = revalidate_px_guarded_mutation(app, model, action) {
            app.mode = Mode::MutationPreview;
            app.mutation_armed = false;
            app.mutation_preflight.clear();
            app.mutation_preflight_token.clear();
            app.status = Some(format!("REMOTE EXECUTION REFUSED // {error}"));
            return;
        }
    }

    let argument_pairs = mutation_argument_pairs(action, &app.prompt_values);
    let operation_id = match journal::start(
        &model.px_path,
        &action.id,
        &action.title,
        &action.mutation,
        &action.recovery,
        &app.mutation_args,
        &argument_pairs,
        app.mutation_armed,
        &app.mutation_preflight,
    ) {
        Ok(operation_id) => operation_id,
        Err(error) => {
            app.mode = Mode::MutationPreview;
            app.status = Some(format!(
                "EXECUTION REFUSED // PX operation journal could not start // {error}"
            ));
            return;
        }
    };

    let output = match Command::new(&model.px_path)
        .args(&app.mutation_args)
        .output()
    {
        Ok(output) => output,
        Err(error) => {
            let after = serde_json::json!({"launchError": error.to_string()});
            let warning = journal_warning(journal::finish(
                &model.px_path,
                &operation_id,
                "FAILED",
                None,
                "NOT_RUN",
                &after,
                &serde_json::json!({}),
                &format!("mutation launch failed: {error}"),
            ));
            app.open_output(
                format!("{} // ERROR", action.title),
                format!(
                    "OPERATION {operation_id}\n\nEXECUTION\ncould not launch PX mutation: {error}{warning}"
                ),
            );
            return;
        }
    };

    let execution_success = output.status.success();
    let execution_exit = output.status.code();
    let execution_evidence = journal::output_evidence(&output.stdout, &output.stderr);
    let mut text = display_output(&output.stdout, &output.stderr);

    if !execution_success {
        let code = execution_exit
            .map(|value| value.to_string())
            .unwrap_or_else(|| "signal".to_owned());
        let warning = journal_warning(journal::finish(
            &model.px_path,
            &operation_id,
            "FAILED",
            execution_exit,
            "NOT_RUN",
            &execution_evidence,
            &serde_json::json!({}),
            &format!("mutation failed with exit {code}"),
        ));
        text = format!(
            "OPERATION {operation_id}\n\nEXECUTION\nEXIT {code}\n\n{text}{warning}"
        );
        app.open_output(
            format!("{} // {} // FAILED", action.title, action.mutation.to_uppercase()),
            text,
        );
        return;
    }

    if mutation_requires_hospital_arm(action) {
        let verify_args = match hospital_integration_verify_args(action, &app.prompt_values) {
            Ok(args) => args,
            Err(error) => {
                let verification = serde_json::json!({"error": error});
                let warning = journal_warning(journal::finish(
                    &model.px_path,
                    &operation_id,
                    "COMPLETE",
                    execution_exit,
                    "UNAVAILABLE",
                    &execution_evidence,
                    &verification,
                    "mutation succeeded; post-op verification arguments were unavailable",
                ));
                text = format!(
                    "OPERATION {operation_id}\n\nEXECUTION\n{text}\n\nPOST-OP VERIFY\nNOT STARTED // {error}{warning}"
                );
                app.open_output(
                    format!("{} // REMOTE // VERIFY FAILED", action.title),
                    text,
                );
                return;
            }
        };

        let verify = match Command::new(&model.px_path).args(&verify_args).output() {
            Ok(output) => output,
            Err(error) => {
                let verification = serde_json::json!({"launchError": error.to_string()});
                let warning = journal_warning(journal::finish(
                    &model.px_path,
                    &operation_id,
                    "COMPLETE",
                    execution_exit,
                    "UNAVAILABLE",
                    &execution_evidence,
                    &verification,
                    "mutation succeeded; post-op verification could not launch",
                ));
                text = format!(
                    "OPERATION {operation_id}\n\nEXECUTION\n{text}\n\nPOST-OP VERIFY\nCOULD NOT LAUNCH // {error}{warning}"
                );
                app.open_output(
                    format!("{} // REMOTE // VERIFY FAILED", action.title),
                    text,
                );
                return;
            }
        };

        let verification_evidence =
            journal::output_evidence(&verify.stdout, &verify.stderr);
        let mut verify_text = display_output(&verify.stdout, &verify.stderr);

        if !verify.status.success() {
            let code = verify
                .status
                .code()
                .map(|value| value.to_string())
                .unwrap_or_else(|| "signal".to_owned());
            let warning = journal_warning(journal::finish(
                &model.px_path,
                &operation_id,
                "COMPLETE",
                execution_exit,
                "FAILED",
                &execution_evidence,
                &verification_evidence,
                &format!("mutation succeeded; post-op verification failed with exit {code}"),
            ));
            verify_text = format!("EXIT {code}\n\n{verify_text}");
            text = format!(
                "OPERATION {operation_id}\n\nEXECUTION\n{text}\n\nPOST-OP VERIFY\n{verify_text}{warning}"
            );
            app.open_output(
                format!("{} // REMOTE // VERIFY FAILED", action.title),
                text,
            );
            return;
        }

        let warning = journal_warning(journal::finish(
            &model.px_path,
            &operation_id,
            "COMPLETE",
            execution_exit,
            "PASSED",
            &execution_evidence,
            &verification_evidence,
            "mutation and post-op verification succeeded",
        ));
        text = format!(
            "OPERATION {operation_id}\n\nEXECUTION\n{text}\n\nPOST-OP VERIFY\n{verify_text}{warning}"
        );
        app.open_output(
            format!("{} // REMOTE // VERIFIED", action.title),
            text,
        );
        return;
    }

    if mutation_uses_px_guard(action) {
        let verification = match px_guard_verification(model, action, &app.prompt_values) {
            Ok(value) => value,
            Err(error) => {
                let verification = serde_json::json!({"error": error});
                let warning = journal_warning(journal::finish(
                    &model.px_path,
                    &operation_id,
                    "COMPLETE",
                    execution_exit,
                    "UNAVAILABLE",
                    &execution_evidence,
                    &verification,
                    "mutation succeeded; PX verification could not complete",
                ));
                text = format!(
                    "OPERATION {operation_id}\n\nEXECUTION\n{text}\n\nPOST-OP VERIFY\nUNAVAILABLE // {error}{warning}"
                );
                app.open_output(
                    format!("{} // REMOTE // VERIFY FAILED", action.title),
                    text,
                );
                return;
            }
        };

        let passed = verification
            .get("passed")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false);
        let summary = verification
            .get("summary")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("PX mutation verification returned no summary");
        let reason = verification
            .get("reason")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("");
        let verify_text = serde_json::to_string_pretty(&verification)
            .unwrap_or_else(|_| verification.to_string());

        if !passed {
            let result_summary = if reason.is_empty() {
                summary.to_owned()
            } else {
                format!("{summary} // {reason}")
            };
            let warning = journal_warning(journal::finish(
                &model.px_path,
                &operation_id,
                "COMPLETE",
                execution_exit,
                "FAILED",
                &execution_evidence,
                &verification,
                &result_summary,
            ));
            text = format!(
                "OPERATION {operation_id}\n\nEXECUTION\n{text}\n\nPOST-OP VERIFY\n{verify_text}{warning}"
            );
            app.open_output(
                format!("{} // REMOTE // VERIFY FAILED", action.title),
                text,
            );
            return;
        }

        let warning = journal_warning(journal::finish(
            &model.px_path,
            &operation_id,
            "COMPLETE",
            execution_exit,
            "PASSED",
            &execution_evidence,
            &verification,
            summary,
        ));
        text = format!(
            "OPERATION {operation_id}\n\nEXECUTION\n{text}\n\nPOST-OP VERIFY\n{verify_text}{warning}"
        );
        app.open_output(
            format!("{} // REMOTE // VERIFIED", action.title),
            text,
        );
        return;
    }

    let warning = journal_warning(journal::finish(
        &model.px_path,
        &operation_id,
        "COMPLETE",
        execution_exit,
        "NOT_RUN",
        &execution_evidence,
        &serde_json::json!({}),
        "mutation completed successfully",
    ));
    app.open_output(
        format!("{} // {}", action.title, action.mutation.to_uppercase()),
        format!("OPERATION {operation_id}\n\n{text}{warning}"),
    );
}

fn commit_argument_value(
    app: &mut App,
    model: &Model,
    action: &Action,
    value: String,
) {
    if let Some(slot) = app.prompt_values.get_mut(app.prompt_index) {
        *slot = value;
    }

    if app.prompt_index + 1 < action.arguments.len() {
        app.prompt_index += 1;
        app.prompt_buffer.clear();
        app.status = None;
        prepare_current_argument(app, model, action);
    } else {
        let values = app.prompt_values.clone();

        if action.mutation == "read" {
            run_read_action(app, model, action, &values);
        } else {
            prepare_mutation_preview(app, action, &values);
        }
    }
}

fn begin_or_run_action(app: &mut App, model: &Model, action_id: &str) {
    let Some(action) = action_by_id(model, action_id) else {
        app.status = Some(format!("Action disappeared: {action_id}"));
        return;
    };

    if action.arguments.is_empty() {
        app.pending_action_id = Some(action.id.clone());

        if action.mutation == "read" {
            run_read_action(app, model, action, &[]);
        } else {
            prepare_mutation_preview(app, action, &[]);
        }
    } else {
        app.begin_action_prompt(action.id.clone(), action.arguments.len());
        prepare_current_argument(app, model, action);
    }
}

fn resolve_px_path() -> PathBuf {
    if let Ok(root) = env::var("PX_RUNTIME_ROOT") {
        let candidate = Path::new(&root).join("bin").join("px");
        if candidate.is_file() {
            return candidate;
        }
    }

    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("term-exp should live under the PX runtime root")
        .join("bin")
        .join("px")
}

fn load_json<T>(px_path: &Path, args: &[&str]) -> Result<T, Box<dyn std::error::Error>>
where
    T: for<'de> Deserialize<'de>,
{
    let output = Command::new(px_path).args(args).output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
        let detail = if !stderr.is_empty() { stderr } else { stdout };
        return Err(format!(
            "{} {} failed: {}",
            px_path.display(),
            args.join(" "),
            if detail.is_empty() {
                output.status.to_string()
            } else {
                detail
            }
        )
        .into());
    }

    Ok(serde_json::from_slice(&output.stdout)?)
}

fn action_categories(actions: &[Action]) -> Vec<(String, usize)> {
    let mut counts = BTreeMap::<String, usize>::new();

    for action in actions {
        *counts.entry(action.category.clone()).or_default() += 1;
    }

    counts.into_iter().collect()
}

fn representative_actions(actions: &[Action]) -> Vec<&Action> {
    let mut representatives = Vec::new();
    let mut seen = BTreeMap::<String, bool>::new();

    for action in actions {
        if seen.insert(action.category.clone(), true).is_none() {
            representatives.push(action);
        }

        if representatives.len() >= 8 {
            break;
        }
    }

    representatives
}

fn leader_entries(model: &Model) -> Vec<(char, SearchScope, String)> {
    let mut entries = vec![
        ('a', SearchScope::Actions, "All Actions".to_owned()),
        ('t', SearchScope::Tools, "Commands".to_owned()),
    ];

    for (key, category) in [
        ('p', "PX"),
        ('h', "Hospital"),
        ('i', "AI"),
        ('g', "GitHub"),
        ('w', "Workflow"),
    ] {
        if model
            .actions
            .actions
            .iter()
            .any(|action| action.category.eq_ignore_ascii_case(category))
        {
            entries.push((
                key,
                SearchScope::Category(category.to_owned()),
                category.to_owned(),
            ));
        }
    }

    entries
}

fn preferred_tools(tools: &[Tool]) -> Vec<&Tool> {
    let mut by_name = BTreeMap::<&str, &Tool>::new();

    for tool in tools {
        by_name
            .entry(tool.name.as_str())
            .and_modify(|current| {
                if tool_rank(tool) < tool_rank(current) {
                    *current = tool;
                }
            })
            .or_insert(tool);
    }

    by_name.into_values().collect()
}

fn tool_rank(tool: &Tool) -> u8 {
    match tool.backend.as_str() {
        "native" => 0,
        "toolbox" => 1,
        "distrobox" => 2,
        _ => 9,
    }
}

fn filtered_choice_indices(app: &App) -> Vec<usize> {
    let query = app.choice_query.trim();

    if query.is_empty() {
        return (0..app.choice_items.len()).collect();
    }

    let mut matches: Vec<(usize, i64)> = app
        .choice_items
        .iter()
        .enumerate()
        .filter_map(|(index, choice)| {
            [
                choice.label.as_str(),
                choice.value.as_str(),
                choice.detail.as_str(),
            ]
            .into_iter()
            .filter_map(|field| search_field_score(query, field))
            .max()
            .map(|score| (index, score))
        })
        .collect();

    matches.sort_by(|left, right| {
        right
            .1
            .cmp(&left.1)
            .then_with(|| app.choice_items[left.0].label.cmp(&app.choice_items[right.0].label))
    });

    matches.into_iter().map(|(index, _)| index).collect()
}

fn search_results(model: &Model, scope: &SearchScope, query: &str) -> Vec<SearchItem> {
    let mut items = Vec::new();

    let allow_actions = !matches!(scope, SearchScope::Tools);
    let allow_tools = matches!(scope, SearchScope::All | SearchScope::Tools);

    if allow_actions {
        for action in &model.actions.actions {
            if let SearchScope::Category(category) = scope {
                if !action.category.eq_ignore_ascii_case(category) {
                    continue;
                }
            }

            let score = action_search_score(action, query);

            if let Some(score) = score {
                items.push(SearchItem {
                    kind: SearchKind::Action,
                    key: action.id.clone(),
                    title: action.title.clone(),
                    subtitle: format!("{} · {}", action.category, action.summary),
                    score,
                });
            }
        }
    }

    if allow_tools && !query.is_empty() {
        for tool in preferred_tools(&model.tools.tools) {
            if let Some(score) = search_field_score(query, &tool.name) {
                items.push(SearchItem {
                    kind: SearchKind::Tool,
                    key: tool.name.clone(),
                    title: tool.name.clone(),
                    subtitle: format!("{} · {}", tool.environment, tool.path),
                    score,
                });
            }
        }
    }

    if matches!(scope, SearchScope::Tools) && query.is_empty() {
        for tool in preferred_tools(&model.tools.tools).into_iter().take(128) {
            items.push(SearchItem {
                kind: SearchKind::Tool,
                key: tool.name.clone(),
                title: tool.name.clone(),
                subtitle: format!("{} · {}", tool.environment, tool.path),
                score: 0,
            });
        }
    }

    items.sort_by(|left, right| {
        right
            .score
            .cmp(&left.score)
            .then_with(|| left.title.cmp(&right.title))
    });

    items.truncate(128);
    items
}

fn action_search_score(action: &Action, query: &str) -> Option<i64> {
    if query.is_empty() {
        return Some(500);
    }

    let mut scores = vec![
        search_field_score(query, &action.title),
        search_field_score(query, &action.id),
        search_field_score(query, &action.category),
    ];

    scores.extend(
        action
            .keywords
            .iter()
            .map(|keyword| search_field_score(query, keyword)),
    );

    let query_lower = query.to_lowercase();
    if action.summary.to_lowercase().contains(&query_lower) {
        scores.push(search_field_score(query, &action.summary).map(|score| score - 250));
    }

    scores.into_iter().flatten().max()
}

fn search_field_score(query: &str, candidate: &str) -> Option<i64> {
    let query_lower = query.to_lowercase();
    let candidate_lower = candidate.to_lowercase();

    if query_lower.is_empty() {
        return Some(0);
    }

    let base = fuzzy_score(&query_lower, &candidate_lower)?;

    if candidate_lower == query_lower {
        Some(base + 2000)
    } else if candidate_lower.starts_with(&query_lower) {
        Some(base + 1400)
    } else if candidate_lower.contains(&query_lower) {
        Some(base + 900)
    } else {
        Some(base)
    }
}

fn fuzzy_score(query: &str, candidate: &str) -> Option<i64> {
    let query = query.to_lowercase();
    let candidate = candidate.to_lowercase();

    if query.is_empty() {
        return Some(0);
    }

    let query_chars: Vec<char> = query.chars().collect();
    let mut query_index = 0usize;
    let mut score = 0i64;
    let mut last_match = None;

    for (index, character) in candidate.chars().enumerate() {
        if query_index >= query_chars.len() {
            break;
        }

        if character != query_chars[query_index] {
            continue;
        }

        score += 20;

        if index == 0 {
            score += 25;
        }

        if let Some(previous) = last_match {
            if index == previous + 1 {
                score += 30;
            } else {
                score -= (index.saturating_sub(previous + 1) as i64).min(10);
            }
        }

        last_match = Some(index);
        query_index += 1;
    }

    if query_index == query_chars.len() {
        score -= candidate.chars().count() as i64 / 8;
        Some(score)
    } else {
        None
    }
}

fn draw(frame: &mut Frame, app: &App, model: &Model) {
    let area = frame.area();
    frame.render_widget(
        Block::default().style(Style::default().bg(BG).fg(FG)),
        area,
    );

    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(1),
            Constraint::Length(3),
        ])
        .split(area);

    draw_header(frame, rows[0], model);

    match &app.mode {
        Mode::Home => draw_body(frame, rows[1], model),
        Mode::Leader => draw_leader(frame, rows[1], app, model),
        Mode::Search => draw_search(frame, rows[1], app, model),
        Mode::ActionPrompt => draw_action_prompt(frame, rows[1], app, model),
        Mode::ActionChoice => draw_action_choice(frame, rows[1], app, model),
        Mode::MutationPreview => draw_mutation_preview(frame, rows[1], app, model),
        Mode::MutationConfirm => draw_mutation_confirm(frame, rows[1], app, model),
        Mode::Output => draw_output(frame, rows[1], app),
    }

    draw_footer(frame, rows[2], app, model);
}

fn draw_header(frame: &mut Frame, area: Rect, model: &Model) {
    let line = Line::from(vec![
        Span::styled(
            " PX // TERM EXP ",
            Style::default().fg(CYAN).add_modifier(Modifier::BOLD),
        ),
        Span::styled(
            format!(
                "  {} actions · {} commands",
                model.actions.actions.len(),
                model.tools.counts.total
            ),
            Style::default().fg(FG),
        ),
    ]);

    frame.render_widget(
        Paragraph::new(line).block(
            Block::default()
                .borders(Borders::BOTTOM)
                .border_style(Style::default().fg(CYAN))
                .style(Style::default().bg(BG).fg(FG)),
        ),
        area,
    );
}

fn draw_body(frame: &mut Frame, area: Rect, model: &Model) {
    if area.width < 88 {
        let rows = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(9),
                Constraint::Length(6),
                Constraint::Length(9),
                Constraint::Min(8),
            ])
            .split(area);

        draw_control_plane(frame, rows[0], model);
        draw_environments(frame, rows[1], model);
        draw_categories(frame, rows[2], model);
        draw_representative_actions(frame, rows[3], model);
        return;
    }

    let columns = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(46), Constraint::Percentage(54)])
        .split(area);

    let left = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(9), Constraint::Min(1)])
        .split(columns[0]);

    let right = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Percentage(46), Constraint::Percentage(54)])
        .split(columns[1]);

    draw_control_plane(frame, left[0], model);
    draw_environments(frame, left[1], model);
    draw_categories(frame, right[0], model);
    draw_representative_actions(frame, right[1], model);
}

fn draw_control_plane(frame: &mut Frame, area: Rect, model: &Model) {
    let lines = vec![
        kv("ACTION REGISTRY", model.actions.actions.len().to_string(), MAGENTA),
        kv("COMMAND REGISTRY", model.tools.counts.total.to_string(), CYAN),
        kv("HOST", model.tools.counts.host.to_string(), FG),
        kv("TOOLBOX", model.tools.counts.toolbox.to_string(), FG),
        kv("PX", model.px_path.display().to_string(), ORANGE),
    ];

    frame.render_widget(
        Paragraph::new(lines).block(panel(" CONTROL PLANE ", CYAN)),
        area,
    );
}

fn draw_environments(frame: &mut Frame, area: Rect, model: &Model) {
    let items: Vec<ListItem> = model
        .tools
        .environments
        .iter()
        .map(|environment| {
            let status_color = if environment.status == "READY" {
                CYAN
            } else {
                ORANGE
            };

            let mut spans = if area.width < 60 {
                vec![
                    Span::styled(
                        format!("{}  ", environment.id),
                        Style::default().fg(FG).add_modifier(Modifier::BOLD),
                    ),
                    Span::styled(
                        format!("{}  ", environment.status),
                        Style::default().fg(status_color),
                    ),
                    Span::styled(
                        environment.tool_count.to_string(),
                        Style::default().fg(ORANGE),
                    ),
                ]
            } else {
                vec![
                    Span::styled(
                        format!("{:<30}", environment.id),
                        Style::default().fg(FG).add_modifier(Modifier::BOLD),
                    ),
                    Span::styled(
                        format!("{:<12}", environment.status),
                        Style::default().fg(status_color),
                    ),
                    Span::styled(
                        format!("{:>6}", environment.tool_count),
                        Style::default().fg(ORANGE),
                    ),
                ]
            };

            if !environment.error.is_empty() {
                spans.push(Span::styled(
                    format!("  {}", environment.error),
                    Style::default().fg(ORANGE),
                ));
            }

            ListItem::new(Line::from(spans))
        })
        .collect();

    frame.render_widget(
        List::new(items).block(panel(" ENVIRONMENTS ", MAGENTA)),
        area,
    );
}

fn draw_categories(frame: &mut Frame, area: Rect, model: &Model) {
    let items: Vec<ListItem> = action_categories(&model.actions.actions)
        .into_iter()
        .map(|(category, count)| {
            ListItem::new(Line::from(vec![
                Span::styled(
                    format!("{:<22}", category),
                    Style::default().fg(CYAN).add_modifier(Modifier::BOLD),
                ),
                Span::styled(format!("{count:>4}"), Style::default().fg(ORANGE)),
            ]))
        })
        .collect();

    frame.render_widget(
        List::new(items).block(panel(" ACTION CATEGORIES ", ORANGE)),
        area,
    );
}

fn draw_representative_actions(frame: &mut Frame, area: Rect, model: &Model) {
    let items: Vec<ListItem> = representative_actions(&model.actions.actions)
        .into_iter()
        .map(|action| {
            ListItem::new(vec![
                Line::from(vec![
                    Span::styled(
                        format!("{:<14}", action.category),
                        Style::default().fg(MAGENTA),
                    ),
                    Span::styled(
                        &action.title,
                        Style::default().fg(FG).add_modifier(Modifier::BOLD),
                    ),
                ]),
                Line::from(Span::styled(
                    format!("  {}  ·  {}", action.id, action.summary),
                    Style::default().fg(Color::DarkGray),
                )),
            ])
        })
        .collect();

    frame.render_widget(
        List::new(items).block(panel(" LIVE SEMANTIC SURFACE ", CYAN)),
        area,
    );
}

fn draw_leader(frame: &mut Frame, area: Rect, app: &App, model: &Model) {
    let entries = leader_entries(model);
    let items: Vec<ListItem> = entries
        .iter()
        .map(|(key, _, title)| {
            ListItem::new(format!(" {key}  {title}"))
        })
        .collect();

    let list = List::new(items)
        .block(panel(" SPACE // COMMANDS ", ORANGE))
        .highlight_symbol("> ")
        .highlight_style(Style::default().fg(BG).bg(ORANGE));

    let mut state = ListState::default();
    if !entries.is_empty() {
        state.select(Some(app.leader_selected.min(entries.len() - 1)));
    }

    frame.render_stateful_widget(list, area, &mut state);
}

fn draw_search(frame: &mut Frame, area: Rect, app: &App, model: &Model) {
    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Min(1)])
        .split(area);

    let input = Paragraph::new(format!(" / {}", app.query))
        .block(panel(" FIND ANYTHING ", CYAN));
    frame.render_widget(input, rows[0]);

    let results = search_results(model, &app.search_scope, &app.query);
    let items: Vec<ListItem> = results
        .iter()
        .map(|item| {
            let kind = match item.kind {
                SearchKind::Action => "ACTION",
                SearchKind::Tool if is_specialist_tool(&item.key) => "SPECIAL",
                SearchKind::Tool => "COMMAND",
            };
            let kind_color = match item.kind {
                SearchKind::Action => MAGENTA,
                SearchKind::Tool if is_specialist_tool(&item.key) => ORANGE,
                SearchKind::Tool => CYAN,
            };

            ListItem::new(vec![
                Line::from(vec![
                    Span::styled(format!("{kind:<8}"), Style::default().fg(kind_color)),
                    Span::styled(
                        &item.title,
                        Style::default().fg(FG).add_modifier(Modifier::BOLD),
                    ),
                ]),
                Line::from(Span::styled(
                    format!("  {}", item.subtitle),
                    Style::default().fg(Color::DarkGray),
                )),
            ])
        })
        .collect();

    let list = List::new(items)
        .block(panel(" RESULTS ", MAGENTA))
        .highlight_symbol("> ")
        .highlight_style(Style::default().fg(BG).bg(ORANGE));

    let mut state = ListState::default();
    if !results.is_empty() {
        state.select(Some(app.search_selected.min(results.len() - 1)));
    }

    frame.render_stateful_widget(list, rows[1], &mut state);
}

fn draw_action_choice(frame: &mut Frame, area: Rect, app: &App, model: &Model) {
    let Some(action_id) = app.pending_action_id.as_deref() else {
        frame.render_widget(
            Paragraph::new("No pending action").block(panel(" SELECT VALUE ", ORANGE)),
            area,
        );
        return;
    };
    let Some(action) = action_by_id(model, action_id) else {
        frame.render_widget(
            Paragraph::new("Action no longer exists").block(panel(" SELECT VALUE ", ORANGE)),
            area,
        );
        return;
    };
    let Some(argument) = action.arguments.get(app.prompt_index) else {
        frame.render_widget(
            Paragraph::new("No remaining arguments").block(panel(" SELECT VALUE ", ORANGE)),
            area,
        );
        return;
    };

    let rows = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(5), Constraint::Min(1)])
        .split(area);

    let filter_text = if app.choice_query.is_empty() {
        "(type to filter)".to_owned()
    } else {
        app.choice_query.clone()
    };

    let heading = Paragraph::new(vec![
        Line::from(vec![
            Span::styled(
                &action.title,
                Style::default().fg(CYAN).add_modifier(Modifier::BOLD),
            ),
            Span::styled(
                format!("  {}", action.id),
                Style::default().fg(Color::DarkGray),
            ),
        ]),
        Line::from(vec![
            Span::styled("Choose ", Style::default().fg(FG)),
            Span::styled(
                format!("{} [{}]", argument.name, argument.kind),
                Style::default().fg(ORANGE).add_modifier(Modifier::BOLD),
            ),
        ]),
        Line::from(vec![
            Span::styled("Filter  ", Style::default().fg(Color::DarkGray)),
            Span::styled(filter_text, Style::default().fg(CYAN)),
        ]),
    ])
    .block(panel(" KNOWN VALUE ", ORANGE));

    frame.render_widget(heading, rows[0]);

    let visible = filtered_choice_indices(app);
    let items: Vec<ListItem> = visible
        .iter()
        .filter_map(|index| app.choice_items.get(*index))
        .map(|choice| {
            ListItem::new(vec![
                Line::from(Span::styled(
                    &choice.label,
                    Style::default().fg(FG).add_modifier(Modifier::BOLD),
                )),
                Line::from(Span::styled(
                    format!("  {}", choice.detail),
                    Style::default().fg(Color::DarkGray),
                )),
            ])
        })
        .collect();

    let list = List::new(items)
        .block(panel(" AVAILABLE ", MAGENTA))
        .highlight_symbol("> ")
        .highlight_style(
            Style::default()
                .fg(BG)
                .bg(ORANGE)
                .add_modifier(Modifier::BOLD),
        );

    let mut state = ListState::default();
    if !visible.is_empty() {
        state.select(Some(
            app.choice_selected.min(visible.len().saturating_sub(1)),
        ));
    }

    frame.render_stateful_widget(list, rows[1], &mut state);
}

fn draw_action_prompt(frame: &mut Frame, area: Rect, app: &App, model: &Model) {
    let Some(action_id) = app.pending_action_id.as_deref() else {
        frame.render_widget(
            Paragraph::new("No pending action").block(panel(" ACTION INPUT ", ORANGE)),
            area,
        );
        return;
    };
    let Some(action) = action_by_id(model, action_id) else {
        frame.render_widget(
            Paragraph::new("Action no longer exists").block(panel(" ACTION INPUT ", ORANGE)),
            area,
        );
        return;
    };
    let Some(argument) = action.arguments.get(app.prompt_index) else {
        frame.render_widget(
            Paragraph::new("No remaining arguments").block(panel(" ACTION INPUT ", ORANGE)),
            area,
        );
        return;
    };

    let mut lines = vec![
        Line::from(vec![
            Span::styled(
                &action.title,
                Style::default().fg(CYAN).add_modifier(Modifier::BOLD),
            ),
            Span::styled(
                format!("  {}", action.id),
                Style::default().fg(Color::DarkGray),
            ),
        ]),
        Line::from(""),
    ];

    for (index, previous) in action.arguments.iter().enumerate().take(app.prompt_index) {
        let value = app.prompt_values.get(index).map(String::as_str).unwrap_or("");
        lines.push(Line::from(vec![
            Span::styled(
                format!("{:<18}", previous.name),
                Style::default().fg(Color::DarkGray),
            ),
            Span::styled(value, Style::default().fg(FG)),
        ]));
    }

    lines.push(Line::from(""));
    lines.push(Line::from(vec![
        Span::styled(
            format!(
                "{}{} [{}]  ",
                argument.name,
                if argument.required { " *" } else { "" },
                argument.kind
            ),
            Style::default().fg(ORANGE).add_modifier(Modifier::BOLD),
        ),
        Span::styled(&app.prompt_buffer, Style::default().fg(FG)),
    ]));

    if let Some(status) = &app.status {
        lines.push(Line::from(""));
        lines.push(Line::from(Span::styled(status, Style::default().fg(ORANGE))));
    }

    frame.render_widget(
        Paragraph::new(lines)
            .block(panel(" ACTION INPUT ", ORANGE))
            .wrap(Wrap { trim: false }),
        area,
    );
}

fn mutation_color(action: &Action) -> Color {
    match action.mutation.as_str() {
        "local" => CYAN,
        "remote" => ORANGE,
        "external" => MAGENTA,
        _ => FG,
    }
}

fn draw_mutation_preview(frame: &mut Frame, area: Rect, app: &App, model: &Model) {
    let Some(action_id) = app.pending_action_id.as_deref() else {
        frame.render_widget(
            Paragraph::new("No pending mutation").block(panel(" MUTATION PREVIEW ", ORANGE)),
            area,
        );
        return;
    };
    let Some(action) = action_by_id(model, action_id) else {
        frame.render_widget(
            Paragraph::new("Mutation action no longer exists")
                .block(panel(" MUTATION PREVIEW ", ORANGE)),
            area,
        );
        return;
    };

    let color = mutation_color(action);
    let executable = mutation_execution_enabled(action);
    let mut lines = vec![
        Line::from(vec![
            Span::styled(
                &action.title,
                Style::default().fg(color).add_modifier(Modifier::BOLD),
            ),
            Span::styled(
                format!("  {}", action.id),
                Style::default().fg(Color::DarkGray),
            ),
        ]),
        Line::from(vec![
            Span::styled("MUTATION  ", Style::default().fg(Color::DarkGray)),
            Span::styled(
                action.mutation.to_uppercase(),
                Style::default().fg(color).add_modifier(Modifier::BOLD),
            ),
            Span::styled(
                if executable {
                    "  EXECUTION ENABLED"
                } else {
                    "  PREVIEW ONLY"
                },
                Style::default().fg(if executable { CYAN } else { ORANGE }),
            ),
        ]),
        Line::from(vec![
            Span::styled("RECOVERY  ", Style::default().fg(Color::DarkGray)),
            Span::styled(
                if action.recovery.is_empty() { "UNDECLARED" } else { &action.recovery },
                Style::default().fg(ORANGE),
            ),
        ]),
        Line::from(""),
        Line::from(Span::styled(
            "RESOLVED ARGUMENTS",
            Style::default().fg(MAGENTA).add_modifier(Modifier::BOLD),
        )),
    ];

    for (index, argument) in action.arguments.iter().enumerate() {
        let value = app
            .prompt_values
            .get(index)
            .map(String::as_str)
            .unwrap_or("");
        lines.push(Line::from(vec![
            Span::styled(
                format!("{:<18}", argument.name),
                Style::default().fg(Color::DarkGray),
            ),
            Span::styled(
                if value.is_empty() { "(default)" } else { value },
                Style::default().fg(FG),
            ),
        ]));
    }

    lines.extend([
        Line::from(""),
        Line::from(Span::styled(
            "FROZEN PX COMMAND",
            Style::default().fg(MAGENTA).add_modifier(Modifier::BOLD),
        )),
        Line::from(Span::styled(
            format!("px {}", app.mutation_args.join(" ")),
            Style::default().fg(FG),
        )),
        Line::from(""),
        Line::from(Span::styled(
            "Nothing has executed yet.",
            Style::default().fg(ORANGE).add_modifier(Modifier::BOLD),
        )),
    ]);

    if mutation_requires_arm(action) {
        lines.push(Line::from(Span::styled(
            if app.mutation_armed {
                format!("ARMED // {}", app.mutation_preflight)
            } else {
                if mutation_requires_hospital_arm(action) {
                    "ARM REQUIRED // Enter runs PX Room prepare against the frozen target".to_owned()
                } else {
                    "ARM REQUIRED // Enter runs PX mutation preflight against the frozen target".to_owned()
                }
            },
            Style::default().fg(if app.mutation_armed { CYAN } else { ORANGE }),
        )));
    }

    if executable {
        lines.push(Line::from(
            "Enter continues to explicit confirmation. Esc cancels.",
        ));
    } else {
        lines.push(Line::from(
            "Execution remains locked until this mutation class has a certified policy.",
        ));
    }

    frame.render_widget(
        Paragraph::new(lines)
            .wrap(Wrap { trim: false })
            .block(panel(" MUTATION PREVIEW ", color)),
        area,
    );
}

fn draw_mutation_confirm(frame: &mut Frame, area: Rect, app: &App, model: &Model) {
    let Some(action_id) = app.pending_action_id.as_deref() else {
        frame.render_widget(
            Paragraph::new("No pending mutation").block(panel(" CONFIRM MUTATION ", ORANGE)),
            area,
        );
        return;
    };
    let Some(action) = action_by_id(model, action_id) else {
        frame.render_widget(
            Paragraph::new("Mutation action no longer exists")
                .block(panel(" CONFIRM MUTATION ", ORANGE)),
            area,
        );
        return;
    };

    let expected = mutation_confirmation_phrase(action);
    let color = mutation_color(action);
    let lines = vec![
        Line::from(Span::styled(
            &action.title,
            Style::default().fg(color).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        Line::from("The exact command shown on the previous screen is frozen."),
        Line::from(vec![
            Span::styled("Type ", Style::default().fg(FG)),
            Span::styled(
                expected,
                Style::default().fg(ORANGE).add_modifier(Modifier::BOLD),
            ),
            Span::styled(" to execute:", Style::default().fg(FG)),
        ]),
        Line::from(""),
        Line::from(Span::styled(
            &app.mutation_confirm_buffer,
            Style::default().fg(CYAN).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        Line::from(Span::styled(
            format!("px {}", app.mutation_args.join(" ")),
            Style::default().fg(Color::DarkGray),
        )),
    ];

    frame.render_widget(
        Paragraph::new(lines)
            .wrap(Wrap { trim: false })
            .block(panel(" CONFIRM MUTATION ", color)),
        area,
    );
}

fn draw_output(frame: &mut Frame, area: Rect, app: &App) {
    let title = if app.output_title.is_empty() {
        " ACTION OUTPUT ".to_owned()
    } else {
        format!(" {} ", app.output_title)
    };

    frame.render_widget(
        Paragraph::new(app.output_text.as_str())
            .block(
                Block::default()
                    .title(title)
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(CYAN))
                    .style(Style::default().bg(BG).fg(FG)),
            )
            .wrap(Wrap { trim: false })
            .scroll((app.output_scroll, 0)),
        area,
    );
}

fn draw_footer(frame: &mut Frame, area: Rect, app: &App, model: &Model) {
    let default = match &app.mode {
        Mode::Home => "SPACE commands   / find anything   q quit",
        Mode::Leader => "j/k move   Enter open   hotkey open   / search   Esc back",
        Mode::Search => "type to search   Up/Down move   Enter open   Esc home",
        Mode::ActionPrompt => "type value   Enter next/run   Backspace edit   Esc cancel",
        Mode::ActionChoice => "type filter   Up/Down move   Enter choose   Backspace edit   Esc cancel",
        Mode::MutationPreview => "Enter preflight/confirm mutation   Esc cancel",
        Mode::MutationConfirm => "type confirmation word   Enter execute   Esc preview",
        Mode::Output => "j/k or PgUp/PgDn scroll   Esc results   q home",
    };
    let message = app.status.as_deref().unwrap_or(default);
    let message_color = if app.status.is_some() { ORANGE } else { FG };

    let line = Line::from(vec![
        Span::styled(
            " LIVE ",
            Style::default()
                .fg(BG)
                .bg(CYAN)
                .add_modifier(Modifier::BOLD),
        ),
        Span::styled(
            format!(
                " a{} c{} ",
                model.actions.actions.len(),
                model.tools.counts.total
            ),
            Style::default().fg(Color::DarkGray),
        ),
        Span::styled(message, Style::default().fg(message_color)),
    ]);

    frame.render_widget(
        Paragraph::new(line).block(
            Block::default()
                .borders(Borders::TOP)
                .border_style(Style::default().fg(Color::DarkGray))
                .style(Style::default().bg(BG).fg(FG)),
        ),
        area,
    );
}

fn panel(title: &'static str, color: Color) -> Block<'static> {
    Block::default()
        .title(title)
        .borders(Borders::ALL)
        .border_style(Style::default().fg(color))
        .style(Style::default().bg(BG).fg(FG))
}

fn kv<'a>(label: &'a str, value: String, color: Color) -> Line<'a> {
    Line::from(vec![
        Span::styled(
            format!("{label:<18}"),
            Style::default().fg(Color::DarkGray),
        ),
        Span::styled(value, Style::default().fg(color)),
    ])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn action(id: &str, category: &str) -> Action {
        Action {
            id: id.to_owned(),
            title: id.to_owned(),
            category: category.to_owned(),
            summary: String::new(),
            command: Vec::new(),
            arguments: Vec::new(),
            mutation: "read".to_owned(),
            recovery: "NONE".to_owned(),
            execution_policy: String::new(),
            keywords: Vec::new(),
        }
    }

    #[test]
    fn category_counts_are_sorted_and_stable() {
        let actions = vec![
            action("z", "GitHub"),
            action("a", "AI"),
            action("h", "Hospital"),
            action("g", "GitHub"),
        ];

        assert_eq!(
            action_categories(&actions),
            vec![
                ("AI".to_owned(), 1),
                ("GitHub".to_owned(), 2),
                ("Hospital".to_owned(), 1),
            ]
        );
    }

    #[test]
    fn representative_actions_keep_first_action_per_category() {
        let actions = vec![
            action("first-git", "Git"),
            action("second-git", "Git"),
            action("first-ai", "AI"),
        ];

        let ids: Vec<_> = representative_actions(&actions)
            .into_iter()
            .map(|action| action.id.as_str())
            .collect();

        assert_eq!(ids, vec!["first-git", "first-ai"]);
    }


    #[test]
    fn fuzzy_match_accepts_subsequence() {
        assert!(fuzzy_score("hosp", "hospital room status").is_some());
        assert!(fuzzy_score("zzz", "hospital room status").is_none());
    }

    #[test]
    fn exact_and_prefix_matches_beat_loose_fuzzy_matches() {
        let exact = search_field_score("lazy", "lazy").unwrap();
        let prefix = search_field_score("lazy", "lazygit").unwrap();
        let fuzzy = search_field_score("lazy", "local analyzer yearly").unwrap();

        assert!(exact > prefix);
        assert!(prefix > fuzzy);
    }

    #[test]
    fn action_expansion_handles_required_and_optional_arguments() {
        let action = Action {
            id: "test".to_owned(),
            title: "Test".to_owned(),
            category: "PX".to_owned(),
            summary: String::new(),
            command: vec![
                "inspect".to_owned(),
                "{repository}".to_owned(),
                "{run_id}".to_owned(),
                "{optional?}".to_owned(),
            ],
            arguments: vec![
                ActionArgument {
                    name: "repository".to_owned(),
                    required: true,
                    kind: "repository".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
                ActionArgument {
                    name: "run_id".to_owned(),
                    required: true,
                    kind: "run".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
                ActionArgument {
                    name: "optional".to_owned(),
                    required: false,
                    kind: "text".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
            ],
            mutation: "read".to_owned(),
            recovery: "NONE".to_owned(),
            execution_policy: String::new(),
            keywords: Vec::new(),
        };

        let values = vec!["dev".to_owned(), "1234".to_owned(), String::new()];
        assert_eq!(
            expand_action_command(&action, &values).unwrap(),
            vec!["inspect", "dev", "1234"]
        );
    }

    #[test]
    fn dependency_values_follow_declared_argument_names() {
        let mut run_dependencies = BTreeMap::new();
        run_dependencies.insert("repository".to_owned(), "target_repo".to_owned());

        let action = Action {
            id: "inspect".to_owned(),
            title: "Inspect".to_owned(),
            category: "GitHub".to_owned(),
            summary: String::new(),
            command: vec![
                "inspect".to_owned(),
                "{target_repo}".to_owned(),
                "{run_id}".to_owned(),
            ],
            arguments: vec![
                ActionArgument {
                    name: "target_repo".to_owned(),
                    required: true,
                    kind: "repository".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
                ActionArgument {
                    name: "run_id".to_owned(),
                    required: true,
                    kind: "run".to_owned(),
                    choices: Vec::new(),
                    depends_on: run_dependencies,
                },
            ],
            mutation: "read".to_owned(),
            recovery: "NONE".to_owned(),
            execution_policy: String::new(),
            keywords: Vec::new(),
        };

        let values = vec!["taskbars".to_owned(), String::new()];
        let dependencies =
            argument_dependency_values(&action, &values, &action.arguments[1]);

        assert_eq!(
            dependencies.get("repository").map(String::as_str),
            Some("taskbars")
        );
    }

    #[test]
    fn typed_argument_validation_rejects_bad_integer_and_slug() {
        let integer = ActionArgument {
            name: "limit".to_owned(),
            required: false,
            kind: "integer".to_owned(),
            choices: Vec::new(),
            depends_on: BTreeMap::new(),
        };
        let slug = ActionArgument {
            name: "slug".to_owned(),
            required: true,
            kind: "slug".to_owned(),
            choices: Vec::new(),
            depends_on: BTreeMap::new(),
        };

        assert!(validate_typed_argument(&integer, "20").is_ok());
        assert!(validate_typed_argument(&integer, "twenty").is_err());
        assert!(validate_typed_argument(&slug, "my-workflow").is_ok());
        assert!(validate_typed_argument(&slug, "My Workflow").is_err());
    }

    #[test]
    fn known_value_filter_matches_label_value_and_detail() {
        let mut app = App::new();
        app.choice_items = vec![
            ActionChoiceItem {
                value: "doctor-t6".to_owned(),
                label: "T6 Doctor".to_owned(),
                detail: "Hospital READY".to_owned(),
            },
            ActionChoiceItem {
                value: "taskbars".to_owned(),
                label: "taskbars".to_owned(),
                detail: "kudokudo1/taskbars-post-apollo".to_owned(),
            },
        ];

        app.choice_query = "hospital".to_owned();
        assert_eq!(filtered_choice_indices(&app), vec![0]);

        app.choice_query = "kudokudo1".to_owned();
        assert_eq!(filtered_choice_indices(&app), vec![1]);

        app.choice_query = "doctor-t6".to_owned();
        assert_eq!(filtered_choice_indices(&app), vec![0]);
    }

    #[test]
    fn display_output_pretty_prints_json_and_preserves_stderr() {
        let output = display_output(br#"{"ok":true}"#, b"warning");
        assert!(output.contains("\"ok\": true"));
        assert!(output.contains("STDERR"));
        assert!(output.contains("warning"));
    }

    fn integration_action() -> Action {
        Action {
            id: "hospital.integration.integrate".to_owned(),
            title: "Integrate Room".to_owned(),
            category: "Hospital".to_owned(),
            summary: String::new(),
            command: vec![
                "integrate".to_owned(),
                "{repository}".to_owned(),
                "{team}".to_owned(),
                "{branch}".to_owned(),
                "{room_head}".to_owned(),
                "{base}".to_owned(),
                "{base_head}".to_owned(),
                "{local_path}".to_owned(),
            ],
            arguments: vec![
                ActionArgument {
                    name: "repository".to_owned(),
                    required: true,
                    kind: "repository".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
                ActionArgument {
                    name: "team".to_owned(),
                    required: true,
                    kind: "room".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
                ActionArgument {
                    name: "branch".to_owned(),
                    required: true,
                    kind: "branch".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
                ActionArgument {
                    name: "room_head".to_owned(),
                    required: true,
                    kind: "commit".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
                ActionArgument {
                    name: "base".to_owned(),
                    required: true,
                    kind: "branch".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
                ActionArgument {
                    name: "base_head".to_owned(),
                    required: true,
                    kind: "commit".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
                ActionArgument {
                    name: "local_path".to_owned(),
                    required: true,
                    kind: "path".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
            ],
            mutation: "remote".to_owned(),
            recovery: "EVIDENCE_ONLY".to_owned(),
            execution_policy: String::new(),
            keywords: Vec::new(),
        }
    }

    #[test]
    fn mutation_execution_policy_only_unlocks_certified_remote_actions() {
        let mut local = action("local", "AI");
        local.mutation = "local".to_owned();
        local.recovery = "EVIDENCE_ONLY".to_owned();
        let mut remote = action("remote", "GitHub");
        remote.mutation = "remote".to_owned();
        remote.recovery = "EVIDENCE_ONLY".to_owned();
        let mut external = action("external", "AI");
        external.mutation = "external".to_owned();
        external.recovery = "EVIDENCE_ONLY".to_owned();
        let integration = integration_action();
        let mut cancel = action("github.run.cancel", "GitHub");
        cancel.mutation = "remote".to_owned();
        cancel.recovery = "EVIDENCE_ONLY".to_owned();
        cancel.execution_policy = "px-guarded".to_owned();

        assert!(mutation_execution_enabled(&local));
        assert!(!mutation_execution_enabled(&remote));
        assert!(!mutation_execution_enabled(&external));
        assert!(mutation_execution_enabled(&integration));
        assert!(mutation_execution_enabled(&cancel));
        assert!(mutation_requires_arm(&integration));
        assert!(mutation_requires_arm(&cancel));
        assert!(mutation_requires_hospital_arm(&integration));
        assert!(!mutation_requires_hospital_arm(&cancel));
        assert!(mutation_uses_px_guard(&cancel));
        assert!(!mutation_requires_arm(&remote));
        assert_eq!(mutation_confirmation_phrase(&local), "LOCAL");
        assert_eq!(mutation_confirmation_phrase(&integration), "REMOTE");
        assert_eq!(mutation_confirmation_phrase(&external), "EXTERNAL");
    }

    #[test]
    fn hospital_prepare_must_match_the_exact_frozen_integration_target() {
        let action = integration_action();
        let values = vec![
            "taskbars".to_owned(),
            "T6".to_owned(),
            "feature/t6".to_owned(),
            "aaaaaaaaaaaaaaaa".to_owned(),
            "main".to_owned(),
            "bbbbbbbbbbbbbbbb".to_owned(),
            "/tmp/taskbars".to_owned(),
        ];
        let prepare = HospitalPrepareResult {
            action: "prepare".to_owned(),
            mode: "FAST_FORWARD".to_owned(),
            branch: "feature/t6".to_owned(),
            head: "aaaaaaaaaaaaaaaa".to_owned(),
            base: "main".to_owned(),
            base_head: "bbbbbbbbbbbbbbbb".to_owned(),
        };

        assert!(validate_hospital_prepare(&action, &values, &prepare).is_ok());

        let moved = HospitalPrepareResult {
            head: "cccccccccccccccc".to_owned(),
            ..prepare
        };
        assert_eq!(
            validate_hospital_prepare(&action, &values, &moved).unwrap_err(),
            "Room HEAD changed since selection"
        );
    }

    #[test]
    fn hospital_integration_verification_uses_the_operated_room_head_as_new_base() {
        let action = integration_action();
        let values = vec![
            "taskbars".to_owned(),
            "T6".to_owned(),
            "feature/t6".to_owned(),
            "aaaaaaaaaaaaaaaa".to_owned(),
            "main".to_owned(),
            "bbbbbbbbbbbbbbbb".to_owned(),
            "/tmp/taskbars".to_owned(),
        ];

        assert_eq!(
            hospital_integration_verify_args(&action, &values).unwrap(),
            vec![
                "verify",
                "taskbars",
                "T6",
                "main",
                "aaaaaaaaaaaaaaaa",
                "aaaaaaaaaaaaaaaa",
            ]
        );
    }

    #[test]
    fn mutation_preview_freezes_the_expanded_px_command() {
        let action = Action {
            id: "test.mutate".to_owned(),
            title: "Test Mutation".to_owned(),
            category: "PX".to_owned(),
            summary: String::new(),
            command: vec![
                "agent".to_owned(),
                "cancel".to_owned(),
                "{session_id}".to_owned(),
                "--reason".to_owned(),
                "{reason?}".to_owned(),
                "--json".to_owned(),
            ],
            arguments: vec![
                ActionArgument {
                    name: "session_id".to_owned(),
                    required: true,
                    kind: "session".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
                ActionArgument {
                    name: "reason".to_owned(),
                    required: false,
                    kind: "text".to_owned(),
                    choices: Vec::new(),
                    depends_on: BTreeMap::new(),
                },
            ],
            mutation: "local".to_owned(),
            recovery: "EVIDENCE_ONLY".to_owned(),
            execution_policy: String::new(),
            keywords: Vec::new(),
        };
        let mut app = App::new();
        let values = vec!["session-123".to_owned(), "OPERATOR".to_owned()];

        prepare_mutation_preview(&mut app, &action, &values);

        assert_eq!(app.mode, Mode::MutationPreview);
        assert_eq!(
            app.mutation_args,
            vec![
                "agent",
                "cancel",
                "session-123",
                "--reason",
                "OPERATOR",
                "--json"
            ]
        );
    }

    #[test]
    fn search_selector_does_not_move_leader_selector() {
        let mut app = App::new();
        app.leader_selected = 3;
        app.open_search(SearchScope::All);
        App::next(&mut app.search_selected, 5);

        assert_eq!(app.leader_selected, 3);
        assert_eq!(app.search_selected, 1);
    }


    #[test]
    fn specialist_allowlist_is_explicit() {
        for name in ["lazygit", "nvim", "btop", "zellij", "fzf"] {
            assert!(is_specialist_tool(name), "{name}");
        }

        assert!(!is_specialist_tool("git"));
        assert!(!is_specialist_tool("rm"));
    }

    #[test]
    fn resolver_payload_keeps_exact_invocation() {
        let payload = r#"{
            "status":"FOUND",
            "selected":{
                "name":"lazygit",
                "backend":"toolbox",
                "environment":"toolbox:fedora-toolbox-44",
                "invocation":[
                    "/usr/bin/toolbox",
                    "run",
                    "-c",
                    "fedora-toolbox-44",
                    "--",
                    "/usr/bin/lazygit"
                ]
            }
        }"#;

        let result: ResolveResult = serde_json::from_str(payload).unwrap();
        let selected = result.selected.unwrap();

        assert_eq!(selected.name, "lazygit");
        assert_eq!(selected.backend, "toolbox");
        assert_eq!(selected.invocation.last().unwrap(), "/usr/bin/lazygit");
    }
}
