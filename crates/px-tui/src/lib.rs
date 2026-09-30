use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use px_core::{ActionRegistry, ActionTarget, Registry, Tool};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Clear, List, ListItem, ListState, Paragraph, Wrap},
    Frame, Terminal,
};
use std::{
    io::{self, Stdout},
    time::Duration,
};

const BG: Color = Color::Rgb(0x1B, 0x06, 0x23);
const FG: Color = Color::Rgb(0xDC, 0xF3, 0xFA);
const CYAN: Color = Color::Rgb(0x55, 0xCF, 0xCA);
const ORANGE: Color = Color::Rgb(0xF2, 0xBE, 0x4E);
const MAGENTA: Color = Color::Rgb(0xC7, 0x4E, 0xC7);

type PxTerminal = Terminal<CrosstermBackend<Stdout>>;

#[derive(Clone, Debug, Eq, PartialEq)]
enum Mode {
    Home,
    Leader,
    Group(String),
    Search,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum PaletteKind {
    Action,
    Tool,
}

#[derive(Clone, Debug)]
struct PaletteItem {
    kind: PaletteKind,
    key: String,
    title: String,
    subtitle: String,
    score: i64,
}

struct App {
    mode: Mode,
    home_selected: usize,
    group_selected: usize,
    search_selected: usize,
    query: String,
    status: Option<String>,
    should_quit: bool,
}

impl App {
    fn new() -> Self {
        Self {
            mode: Mode::Home,
            home_selected: 0,
            group_selected: 0,
            search_selected: 0,
            query: String::new(),
            status: None,
            should_quit: false,
        }
    }

    fn next(selected: &mut usize, count: usize) {
        if count == 0 {
            *selected = 0;
        } else {
            *selected = (*selected + 1) % count;
        }
    }

    fn previous(selected: &mut usize, count: usize) {
        if count == 0 {
            *selected = 0;
        } else if *selected == 0 {
            *selected = count - 1;
        } else {
            *selected -= 1;
        }
    }

    fn enter_search(&mut self) {
        self.mode = Mode::Search;
        self.query.clear();
        self.search_selected = 0;
    }
}

struct TerminalGuard {
    terminal: PxTerminal,
}

impl TerminalGuard {
    fn enter() -> io::Result<Self> {
        enable_raw_mode()?;
        let mut stdout = io::stdout();
        execute!(stdout, EnterAlternateScreen)?;

        let backend = CrosstermBackend::new(stdout);
        let mut terminal = Terminal::new(backend)?;
        terminal.clear()?;

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

pub fn run(registry: &Registry, actions: &ActionRegistry) -> io::Result<()> {
    let mut guard = TerminalGuard::enter()?;
    let mut app = App::new();

    while !app.should_quit {
        guard
            .terminal
            .draw(|frame| draw(frame, &app, registry, actions))?;

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

        handle_key(&mut guard, &mut app, key, registry, actions)?;
    }

    Ok(())
}

fn handle_key(
    guard: &mut TerminalGuard,
    app: &mut App,
    key: KeyEvent,
    registry: &Registry,
    actions: &ActionRegistry,
) -> io::Result<()> {
    match &app.mode {
        Mode::Home => handle_home_key(guard, app, key, registry, actions),
        Mode::Leader => {
            handle_leader_key(app, key);
            Ok(())
        }
        Mode::Group(category) => {
            let category = category.clone();
            handle_group_key(guard, app, key, &category, registry, actions)
        }
        Mode::Search => handle_search_key(guard, app, key, registry, actions),
    }
}

fn handle_home_key(
    guard: &mut TerminalGuard,
    app: &mut App,
    key: KeyEvent,
    registry: &Registry,
    actions: &ActionRegistry,
) -> io::Result<()> {
    let quick = quick_actions(actions);

    match key.code {
        KeyCode::Char('q') => app.should_quit = true,
        KeyCode::Char(' ') => {
            app.mode = Mode::Leader;
        }
        KeyCode::Char('/') => app.enter_search(),
        KeyCode::Down | KeyCode::Char('j') => App::next(&mut app.home_selected, quick.len()),
        KeyCode::Up | KeyCode::Char('k') => App::previous(&mut app.home_selected, quick.len()),
        KeyCode::Enter => {
            if let Some(id) = quick.get(app.home_selected) {
                execute_action(guard, app, registry, actions, id)?;
            }
        }
        _ => {}
    }

    Ok(())
}

fn handle_leader_key(app: &mut App, key: KeyEvent) {
    match key.code {
        KeyCode::Esc => {
            app.mode = Mode::Home;
        }
        KeyCode::Char('/') => app.enter_search(),
        KeyCode::Char('g') => enter_group(app, "Git"),
        KeyCode::Char('e') => enter_group(app, "Editor"),
        KeyCode::Char('s') => enter_group(app, "System"),
        KeyCode::Char('t') => enter_group(app, "Terminal"),
        KeyCode::Char('a') => enter_group(app, "*"),
        KeyCode::Char('q') => app.should_quit = true,
        _ => {}
    }
}

fn enter_group(app: &mut App, category: &str) {
    app.mode = Mode::Group(category.to_owned());
    app.group_selected = 0;
}

fn handle_group_key(
    guard: &mut TerminalGuard,
    app: &mut App,
    key: KeyEvent,
    category: &str,
    registry: &Registry,
    actions: &ActionRegistry,
) -> io::Result<()> {
    let group = group_actions(actions, category);

    match key.code {
        KeyCode::Esc | KeyCode::Backspace => {
            app.mode = Mode::Leader;
        }
        KeyCode::Char('/') => app.enter_search(),
        KeyCode::Down | KeyCode::Char('j') => App::next(&mut app.group_selected, group.len()),
        KeyCode::Up | KeyCode::Char('k') => App::previous(&mut app.group_selected, group.len()),
        KeyCode::Enter => {
            if let Some(id) = group.get(app.group_selected) {
                execute_action(guard, app, registry, actions, id)?;
            }
        }
        _ => {}
    }

    Ok(())
}

fn handle_search_key(
    guard: &mut TerminalGuard,
    app: &mut App,
    key: KeyEvent,
    registry: &Registry,
    actions: &ActionRegistry,
) -> io::Result<()> {
    let results = palette_results(&app.query, registry, actions);

    match key.code {
        KeyCode::Esc => {
            app.mode = Mode::Home;
            app.query.clear();
        }
        KeyCode::Backspace => {
            app.query.pop();
            app.search_selected = 0;
        }
        KeyCode::Down => App::next(&mut app.search_selected, results.len()),
        KeyCode::Up => App::previous(&mut app.search_selected, results.len()),
        KeyCode::Enter => {
            if let Some(item) = results.get(app.search_selected) {
                let item = (*item).clone();
                execute_palette_item(guard, app, registry, actions, item)?;
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

    Ok(())
}

fn execute_palette_item(
    guard: &mut TerminalGuard,
    app: &mut App,
    registry: &Registry,
    actions: &ActionRegistry,
    item: PaletteItem,
) -> io::Result<()> {
    match item.kind {
        PaletteKind::Action => execute_action(guard, app, registry, actions, &item.key),
        PaletteKind::Tool => {
            let Some(tool) = registry.preferred(&item.key).cloned() else {
                app.status = Some(format!("Tool disappeared: {}", item.key));
                return Ok(());
            };

            execute_tool(guard, app, &tool, &[])
        }
    }
}

fn execute_action(
    guard: &mut TerminalGuard,
    app: &mut App,
    registry: &Registry,
    actions: &ActionRegistry,
    id: &str,
) -> io::Result<()> {
    let Some(action) = actions.get(id) else {
        app.status = Some(format!("Action disappeared: {id}"));
        return Ok(());
    };

    match action.target.clone() {
        ActionTarget::Tool { command, args } => {
            let Some(tool) = registry.preferred(&command).cloned() else {
                app.status = Some(format!("Missing tool for {}: {command}", action.title));
                return Ok(());
            };

            execute_tool(guard, app, &tool, &args)
        }
    }
}

fn execute_tool(
    guard: &mut TerminalGuard,
    app: &mut App,
    tool: &Tool,
    args: &[String],
) -> io::Result<()> {
    guard.suspend()?;
    let result = px_backends::execute(tool, args);
    guard.resume()?;

    match result {
        Ok(status) if status.success() => {
            app.status = Some(format!("{} returned successfully", tool.name));
        }
        Ok(status) => {
            app.status = Some(format!(
                "{} exited with {}",
                tool.name,
                status
                    .code()
                    .map(|code| code.to_string())
                    .unwrap_or_else(|| "signal".into())
            ));
        }
        Err(error) => {
            app.status = Some(format!("{} failed: {error}", tool.name));
        }
    }

    app.mode = Mode::Home;
    Ok(())
}

fn quick_actions(actions: &ActionRegistry) -> Vec<String> {
    actions
        .iter()
        .take(8)
        .map(|action| action.id.clone())
        .collect()
}

fn group_actions(actions: &ActionRegistry, category: &str) -> Vec<String> {
    actions
        .iter()
        .filter(|action| category == "*" || action.category.eq_ignore_ascii_case(category))
        .map(|action| action.id.clone())
        .collect()
}

fn palette_results(
    query: &str,
    registry: &Registry,
    actions: &ActionRegistry,
) -> Vec<PaletteItem> {
    let mut items = Vec::new();

    for action in actions.iter() {
        let searchable = format!(
            "{} {} {} {} {}",
            action.id,
            action.title,
            action.category,
            action.description,
            action.keywords.join(" ")
        );

        let score = if query.is_empty() {
            Some(1000)
        } else {
            fuzzy_score(query, &searchable).map(|score| score + 1000)
        };

        if let Some(score) = score {
            items.push(PaletteItem {
                kind: PaletteKind::Action,
                key: action.id.clone(),
                title: action.title.clone(),
                subtitle: format!("{} · {}", action.category, action.description),
                score,
            });
        }
    }

    if !query.is_empty() {
        for tool in registry.iter() {
            let searchable = format!(
                "{} {} {}",
                tool.name,
                tool.backend.label(),
                tool.executable.display()
            );

            if let Some(score) = fuzzy_score(query, &searchable) {
                items.push(PaletteItem {
                    kind: PaletteKind::Tool,
                    key: tool.name.clone(),
                    title: tool.name.clone(),
                    subtitle: format!("{} · {}", tool.backend.label(), tool.executable.display()),
                    score,
                });
            }
        }
    }

    items.sort_by(|left, right| {
        right
            .score
            .cmp(&left.score)
            .then_with(|| left.title.cmp(&right.title))
    });

    items.truncate(64);
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
        score -= candidate.len() as i64 / 8;
        Some(score)
    } else {
        None
    }
}

fn draw(frame: &mut Frame, app: &App, registry: &Registry, actions: &ActionRegistry) {
    let area = frame.area();
    frame.render_widget(Block::default().style(Style::default().bg(BG).fg(FG)), area);

    let layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(1),
            Constraint::Length(2),
        ])
        .split(area);

    draw_header(frame, layout[0], registry, actions);

    match &app.mode {
        Mode::Home => draw_home(frame, layout[1], app, actions),
        Mode::Leader => {
            draw_modal_backdrop(frame, layout[1]);
            draw_leader(frame, area);
        }
        Mode::Group(category) => {
            draw_modal_backdrop(frame, layout[1]);
            draw_group(frame, area, app, category, actions);
        }
        Mode::Search => {
            draw_modal_backdrop(frame, layout[1]);
            draw_search(frame, area, app, registry, actions);
        }
    }

    draw_footer(frame, layout[2], app);
}

fn draw_header(frame: &mut Frame, area: Rect, registry: &Registry, actions: &ActionRegistry) {
    let block = Block::default()
        .borders(Borders::BOTTOM)
        .border_style(Style::default().fg(CYAN))
        .style(Style::default().bg(BG).fg(FG));

    let title = Line::from(vec![
        Span::styled(
            " PX // TERM EXP ",
            Style::default().fg(CYAN).add_modifier(Modifier::BOLD),
        ),
        Span::styled(
            format!(
                "  {} tools · {} actions",
                registry.len(),
                actions.iter().count()
            ),
            Style::default().fg(FG),
        ),
    ]);

    frame.render_widget(Paragraph::new(title).block(block), area);
}

fn draw_home(frame: &mut Frame, area: Rect, app: &App, actions: &ActionRegistry) {
    let quick = quick_actions(actions);
    let items: Vec<ListItem> = quick
        .iter()
        .filter_map(|id| actions.get(id))
        .map(|action| {
            ListItem::new(Line::from(vec![
                Span::styled(
                    format!("{:<12}", action.category),
                    Style::default().fg(MAGENTA),
                ),
                Span::styled(&action.title, Style::default().fg(FG)),
                Span::styled(
                    format!("  {}", action.description),
                    Style::default().fg(Color::DarkGray),
                ),
            ]))
        })
        .collect();

    let list = List::new(items)
        .block(
            Block::default()
                .title(" Quick Actions ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(CYAN)),
        )
        .highlight_symbol("▸ ")
        .highlight_style(
            Style::default()
                .fg(BG)
                .bg(ORANGE)
                .add_modifier(Modifier::BOLD),
        );

    let mut state = ListState::default();
    if !quick.is_empty() {
        state.select(Some(app.home_selected.min(quick.len() - 1)));
    }

    frame.render_stateful_widget(list, area, &mut state);
}

fn draw_modal_backdrop(frame: &mut Frame, area: Rect) {
    // Ratatui uses a retained terminal buffer. Merely stopping draw_home()
    // does not erase the symbols that were already painted in the previous
    // frame; changing a Block's style also does not blank those cells.
    //
    // Clear the whole content region first so Quick Actions cannot survive
    // behind a modal as stale terminal cells.
    frame.render_widget(Clear, area);

    frame.render_widget(
        Block::default()
            .borders(Borders::ALL)
            .border_style(Style::default().fg(Color::DarkGray))
            .style(Style::default().bg(BG).fg(Color::DarkGray))
            .title(" PX "),
        area,
    );
}

fn draw_leader(frame: &mut Frame, area: Rect) {
    let popup = centered_rect(56, 52, area);
    frame.render_widget(Clear, popup);

    let lines = vec![
        leader_line("g", "Git", "Git actions / Lazygit"),
        leader_line("e", "Editor", "Editor actions / Neovim"),
        leader_line("s", "System", "Processes and system tools"),
        leader_line("t", "Terminal", "Sessions and terminal tools"),
        leader_line("a", "All Actions", "Everything PX understands semantically"),
        leader_line("/", "Find Anything", "Fuzzy search actions + installed commands"),
    ];

    let widget = Paragraph::new(lines)
        .block(
            Block::default()
                .title(" SPACE // COMMANDS ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(ORANGE))
                .style(Style::default().bg(BG).fg(FG)),
        )
        .wrap(Wrap { trim: true });

    frame.render_widget(widget, popup);
}

fn leader_line<'a>(key: &'a str, title: &'a str, description: &'a str) -> Line<'a> {
    Line::from(vec![
        Span::styled(
            format!(" {key:<3}"),
            Style::default().fg(ORANGE).add_modifier(Modifier::BOLD),
        ),
        Span::styled(format!("{title:<16}"), Style::default().fg(CYAN)),
        Span::styled(description, Style::default().fg(FG)),
    ])
}

fn draw_group(
    frame: &mut Frame,
    area: Rect,
    app: &App,
    category: &str,
    actions: &ActionRegistry,
) {
    let popup = centered_rect(68, 60, area);
    frame.render_widget(Clear, popup);

    let ids = group_actions(actions, category);
    let items: Vec<ListItem> = ids
        .iter()
        .filter_map(|id| actions.get(id))
        .map(|action| {
            ListItem::new(vec![
                Line::from(Span::styled(
                    &action.title,
                    Style::default().fg(CYAN).add_modifier(Modifier::BOLD),
                )),
                Line::from(Span::styled(
                    &action.description,
                    Style::default().fg(FG),
                )),
            ])
        })
        .collect();

    let title = if category == "*" {
        " ALL ACTIONS ".to_owned()
    } else {
        format!(" {} ", category.to_uppercase())
    };

    let list = List::new(items)
        .block(
            Block::default()
                .title(title)
                .borders(Borders::ALL)
                .border_style(Style::default().fg(ORANGE))
                .style(Style::default().bg(BG).fg(FG)),
        )
        .highlight_symbol("▸ ")
        .highlight_style(
            Style::default()
                .fg(BG)
                .bg(ORANGE)
                .add_modifier(Modifier::BOLD),
        );

    let mut state = ListState::default();
    if !ids.is_empty() {
        state.select(Some(app.group_selected.min(ids.len() - 1)));
    }

    frame.render_stateful_widget(list, popup, &mut state);
}

fn draw_search(
    frame: &mut Frame,
    area: Rect,
    app: &App,
    registry: &Registry,
    actions: &ActionRegistry,
) {
    let popup = centered_rect(82, 76, area);
    frame.render_widget(Clear, popup);

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Min(1)])
        .split(popup);

    let input = Paragraph::new(Line::from(vec![
        Span::styled(" / ", Style::default().fg(ORANGE).add_modifier(Modifier::BOLD)),
        Span::styled(&app.query, Style::default().fg(FG)),
    ]))
    .block(
        Block::default()
            .title(" FIND ANYTHING ")
            .borders(Borders::ALL)
            .border_style(Style::default().fg(CYAN))
            .style(Style::default().bg(BG).fg(FG)),
    );

    frame.render_widget(input, chunks[0]);

    let results = palette_results(&app.query, registry, actions);
    let items: Vec<ListItem> = results
        .iter()
        .map(|item| {
            let kind = match item.kind {
                PaletteKind::Action => "ACTION",
                PaletteKind::Tool => "TOOL",
            };

            ListItem::new(Line::from(vec![
                Span::styled(
                    format!("{kind:<8}"),
                    Style::default().fg(if item.kind == PaletteKind::Action {
                        MAGENTA
                    } else {
                        CYAN
                    }),
                ),
                Span::styled(
                    format!("{:<26}", item.title),
                    Style::default().fg(FG).add_modifier(Modifier::BOLD),
                ),
                Span::styled(&item.subtitle, Style::default().fg(Color::DarkGray)),
            ]))
        })
        .collect();

    let list = List::new(items)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_style(Style::default().fg(CYAN))
                .style(Style::default().bg(BG).fg(FG)),
        )
        .highlight_symbol("▸ ")
        .highlight_style(
            Style::default()
                .fg(BG)
                .bg(ORANGE)
                .add_modifier(Modifier::BOLD),
        );

    let mut state = ListState::default();
    if !results.is_empty() {
        state.select(Some(app.search_selected.min(results.len() - 1)));
    }

    frame.render_stateful_widget(list, chunks[1], &mut state);
}

fn draw_footer(frame: &mut Frame, area: Rect, app: &App) {
    let status = app
        .status
        .as_deref()
        .unwrap_or("SPACE commands   / find anything   j/k move   Enter open   q quit");

    let color = if app.status.is_some() { ORANGE } else { FG };

    frame.render_widget(
        Paragraph::new(status).style(Style::default().bg(BG).fg(color)),
        area,
    );
}

fn centered_rect(percent_x: u16, percent_y: u16, area: Rect) -> Rect {
    let vertical = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Percentage((100 - percent_y) / 2),
            Constraint::Percentage(percent_y),
            Constraint::Percentage((100 - percent_y) / 2),
        ])
        .split(area);

    Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage((100 - percent_x) / 2),
            Constraint::Percentage(percent_x),
            Constraint::Percentage((100 - percent_x) / 2),
        ])
        .split(vertical[1])[1]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fuzzy_match_accepts_subsequence() {
        assert!(fuzzy_score("lg", "lazygit").is_some());
        assert!(fuzzy_score("branch", "open branch manager").is_some());
    }

    #[test]
    fn fuzzy_match_rejects_wrong_order() {
        assert!(fuzzy_score("zg", "git zellij").is_none());
    }

    #[test]
    fn consecutive_match_scores_higher() {
        let tight = fuzzy_score("git", "git status").unwrap();
        let loose = fuzzy_score("git", "great interface tool").unwrap();

        assert!(tight > loose);
    }

    #[test]
    fn search_selection_does_not_move_home_selection() {
        let mut app = App::new();
        app.home_selected = 2;

        app.enter_search();
        App::next(&mut app.search_selected, 5);

        assert_eq!(app.home_selected, 2);
        assert_eq!(app.search_selected, 1);
    }

    #[test]
    fn overlays_are_distinct_from_home_mode() {
        assert_ne!(Mode::Search, Mode::Home);
        assert_ne!(Mode::Leader, Mode::Home);
        assert_ne!(Mode::Group("Git".into()), Mode::Home);
    }
}
