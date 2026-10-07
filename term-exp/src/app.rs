#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Mode {
    Home,
    Leader,
    Search,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SearchScope {
    All,
    Actions,
    Category(String),
    Tools,
}

pub struct App {
    pub mode: Mode,
    pub leader_selected: usize,
    pub search_selected: usize,
    pub search_scope: SearchScope,
    pub query: String,
    pub status: Option<String>,
    pub should_quit: bool,
}

impl App {
    pub fn new() -> Self {
        Self {
            mode: Mode::Home,
            leader_selected: 0,
            search_selected: 0,
            search_scope: SearchScope::All,
            query: String::new(),
            status: None,
            should_quit: false,
        }
    }

    pub fn next(selected: &mut usize, count: usize) {
        if count == 0 {
            *selected = 0;
        } else {
            *selected = (*selected + 1) % count;
        }
    }

    pub fn previous(selected: &mut usize, count: usize) {
        if count == 0 {
            *selected = 0;
        } else if *selected == 0 {
            *selected = count - 1;
        } else {
            *selected -= 1;
        }
    }

    pub fn open_leader(&mut self) {
        self.mode = Mode::Leader;
        self.leader_selected = 0;
        self.status = None;
    }

    pub fn open_search(&mut self, scope: SearchScope) {
        self.mode = Mode::Search;
        self.search_scope = scope;
        self.query.clear();
        self.search_selected = 0;
        self.status = None;
    }

    pub fn home(&mut self) {
        self.mode = Mode::Home;
        self.query.clear();
        self.status = None;
    }
}
