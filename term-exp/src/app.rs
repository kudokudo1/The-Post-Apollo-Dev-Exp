#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Mode {
    Home,
    Leader,
    Search,
    ActionPrompt,
    ActionChoice,
    Output,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SearchScope {
    All,
    Actions,
    Category(String),
    Tools,
}

#[derive(Clone, Debug)]
pub struct ActionChoiceItem {
    pub value: String,
    pub label: String,
    pub detail: String,
}

pub struct App {
    pub mode: Mode,
    pub leader_selected: usize,
    pub search_selected: usize,
    pub search_scope: SearchScope,
    pub query: String,
    pub status: Option<String>,
    pub should_quit: bool,

    pub pending_action_id: Option<String>,
    pub prompt_index: usize,
    pub prompt_values: Vec<String>,
    pub prompt_buffer: String,

    pub choice_selected: usize,
    pub choice_items: Vec<ActionChoiceItem>,

    pub output_title: String,
    pub output_text: String,
    pub output_scroll: u16,
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

            pending_action_id: None,
            prompt_index: 0,
            prompt_values: Vec::new(),
            prompt_buffer: String::new(),

            choice_selected: 0,
            choice_items: Vec::new(),

            output_title: String::new(),
            output_text: String::new(),
            output_scroll: 0,
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

    pub fn back_to_search(&mut self) {
        self.mode = Mode::Search;
        self.status = None;
        self.pending_action_id = None;
        self.prompt_index = 0;
        self.prompt_values.clear();
        self.prompt_buffer.clear();
        self.choice_selected = 0;
        self.choice_items.clear();
    }

    pub fn begin_action_prompt(&mut self, action_id: String, argument_count: usize) {
        self.pending_action_id = Some(action_id);
        self.prompt_index = 0;
        self.prompt_values = vec![String::new(); argument_count];
        self.prompt_buffer.clear();
        self.choice_selected = 0;
        self.choice_items.clear();
        self.status = None;
    }

    pub fn open_choice(&mut self, items: Vec<ActionChoiceItem>) {
        self.mode = Mode::ActionChoice;
        self.choice_selected = 0;
        self.choice_items = items;
        self.prompt_buffer.clear();
        self.status = None;
    }

    pub fn open_prompt(&mut self) {
        self.mode = Mode::ActionPrompt;
        self.prompt_buffer.clear();
        self.choice_selected = 0;
        self.choice_items.clear();
        self.status = None;
    }

    pub fn open_output(&mut self, title: String, text: String) {
        self.mode = Mode::Output;
        self.output_title = title;
        self.output_text = text;
        self.output_scroll = 0;
        self.status = None;
    }

    pub fn home(&mut self) {
        self.mode = Mode::Home;
        self.query.clear();
        self.status = None;
        self.pending_action_id = None;
        self.prompt_index = 0;
        self.prompt_values.clear();
        self.prompt_buffer.clear();
        self.choice_selected = 0;
        self.choice_items.clear();
        self.output_title.clear();
        self.output_text.clear();
        self.output_scroll = 0;
    }
}
