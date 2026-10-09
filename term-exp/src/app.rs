#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Mode {
    Home,
    Leader,
    Search,
    ActionPrompt,
    ActionChoice,
    MutationPreview,
    MutationConfirm,
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
    pub choice_query: String,

    pub mutation_args: Vec<String>,
    pub mutation_confirm_buffer: String,
    pub mutation_armed: bool,
    pub mutation_preflight: String,
    pub mutation_preflight_token: String,

    pub output_title: String,
    pub output_text: String,
    pub output_scroll: u16,
    pub output_operation_id: Option<String>,
    pub output_source_operation_id: Option<String>,
    pub output_recovery_operation_ids: Vec<String>,
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
            choice_query: String::new(),

            mutation_args: Vec::new(),
            mutation_confirm_buffer: String::new(),
            mutation_armed: false,
            mutation_preflight: String::new(),
            mutation_preflight_token: String::new(),

            output_title: String::new(),
            output_text: String::new(),
            output_scroll: 0,
            output_operation_id: None,
            output_source_operation_id: None,
            output_recovery_operation_ids: Vec::new(),
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
        self.choice_query.clear();
        self.mutation_args.clear();
        self.mutation_confirm_buffer.clear();
        self.mutation_armed = false;
        self.mutation_preflight.clear();
        self.mutation_preflight_token.clear();
        self.output_operation_id = None;
        self.output_source_operation_id = None;
        self.output_recovery_operation_ids.clear();
    }

    pub fn begin_action_prompt(&mut self, action_id: String, argument_count: usize) {
        self.pending_action_id = Some(action_id);
        self.prompt_index = 0;
        self.prompt_values = vec![String::new(); argument_count];
        self.prompt_buffer.clear();
        self.choice_selected = 0;
        self.choice_items.clear();
        self.choice_query.clear();
        self.mutation_args.clear();
        self.mutation_confirm_buffer.clear();
        self.mutation_armed = false;
        self.mutation_preflight.clear();
        self.mutation_preflight_token.clear();
        self.status = None;
    }

    pub fn open_choice(&mut self, items: Vec<ActionChoiceItem>) {
        self.mode = Mode::ActionChoice;
        self.choice_selected = 0;
        self.choice_items = items;
        self.choice_query.clear();
        self.prompt_buffer.clear();
        self.status = None;
    }

    pub fn open_prompt(&mut self) {
        self.mode = Mode::ActionPrompt;
        self.prompt_buffer.clear();
        self.choice_selected = 0;
        self.choice_items.clear();
        self.choice_query.clear();
        self.status = None;
    }

    pub fn open_mutation_preview(&mut self, args: Vec<String>) {
        self.mode = Mode::MutationPreview;
        self.mutation_args = args;
        self.mutation_confirm_buffer.clear();
        self.mutation_armed = false;
        self.mutation_preflight.clear();
        self.mutation_preflight_token.clear();
        self.status = None;
    }

    pub fn return_to_mutation_preview(&mut self) {
        self.mode = Mode::MutationPreview;
        self.mutation_confirm_buffer.clear();
        self.status = None;
    }

    pub fn open_mutation_confirm(&mut self) {
        self.mode = Mode::MutationConfirm;
        self.mutation_confirm_buffer.clear();
        self.status = None;
    }

    pub fn open_output(&mut self, title: String, text: String) {
        self.mode = Mode::Output;
        self.output_title = title;
        self.output_text = text;
        self.output_scroll = 0;
        self.output_operation_id = None;
        self.output_source_operation_id = None;
        self.output_recovery_operation_ids.clear();
        self.status = None;
    }

    pub fn open_operation_output(
        &mut self,
        title: String,
        text: String,
        operation_id: String,
        source_operation_id: Option<String>,
        recovery_operation_ids: Vec<String>,
    ) {
        self.mode = Mode::Output;
        self.output_title = title;
        self.output_text = text;
        self.output_scroll = 0;
        self.output_operation_id = Some(operation_id);
        self.output_source_operation_id = source_operation_id;
        self.output_recovery_operation_ids = recovery_operation_ids;
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
        self.choice_query.clear();
        self.mutation_args.clear();
        self.mutation_confirm_buffer.clear();
        self.mutation_armed = false;
        self.mutation_preflight.clear();
        self.mutation_preflight_token.clear();
        self.output_title.clear();
        self.output_text.clear();
        self.output_scroll = 0;
        self.output_operation_id = None;
        self.output_source_operation_id = None;
        self.output_recovery_operation_ids.clear();
    }
}
