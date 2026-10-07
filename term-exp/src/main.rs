mod app;

use app::{App, Mode, SearchScope};
use crossterm::{
    event::{self, Event, KeyCode, KeyEventKind, KeyModifiers},
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
    collections::{BTreeMap, HashSet},
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

        handle_key(&mut app, key, &model);
    }

    Ok(())
}

fn handle_key(app: &mut App, key: KeyEvent, model: &Model) {
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
                        app.status = Some(match item.kind {
                            SearchKind::Action => format!(
                                "Selected action {} — execution is the next lane",
                                item.key
                            ),
                            SearchKind::Tool => format!(
                                "Selected tool {} — delegation is the next lane",
                                item.key
                            ),
                        });
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
        ('t', SearchScope::Tools, "Tools".to_owned()),
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

            let searchable = format!(
                "{} {} {} {}",
                action.id, action.title, action.category, action.summary
            );

            let score = if query.is_empty() {
                Some(1000)
            } else {
                fuzzy_score(query, &searchable).map(|score| score + 1000)
            };

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
            let searchable = format!(
                "{} {} {} {}",
                tool.name, tool.path, tool.backend, tool.environment
            );

            if let Some(score) = fuzzy_score(query, &searchable) {
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

    match app.mode {
        Mode::Home => draw_body(frame, rows[1], model),
        Mode::Leader => draw_leader(frame, rows[1], app, model),
        Mode::Search => draw_search(frame, rows[1], app, model),
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
                "  {} actions · {} tools",
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
        kv("TOOL REGISTRY", model.tools.counts.total.to_string(), CYAN),
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

            let mut spans = vec![
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
            ];

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

fn draw_footer(frame: &mut Frame, area: Rect, app: &App, model: &Model) {
    let default = match app.mode {
        Mode::Home => "SPACE commands   / find anything   q quit",
        Mode::Leader => "j/k move   Enter open   hotkey open   / search   Esc back",
        Mode::Search => "type to search   Up/Down move   Enter select   Esc back",
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
                " a{} t{} ",
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
}
