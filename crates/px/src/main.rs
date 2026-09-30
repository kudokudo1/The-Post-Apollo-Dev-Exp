use px_config::PxConfig;
use px_core::{ActionRegistry, ActionTarget, Registry};

use std::env;
use std::process;

fn build_registry(config: &PxConfig) -> Registry {
    let mut registry = Registry::new();

    match px_discovery::discover_environment() {
        Ok(tools) => registry.extend(tools),

        Err(error) => {
            eprintln!("PX: PATH discovery failed: {error}");
        }
    }

    if config.toolbox.enabled
        && let Some(toolbox_name) = config.toolbox.name.as_deref()
    {
        match px_discovery::discover_toolbox(toolbox_name) {
            Ok(tools) => registry.extend(tools),

            Err(error) => {
                eprintln!("PX: Toolbox discovery failed for '{toolbox_name}': {error}");
            }
        }
    }

    registry
}

fn header() {
    println!("PX // TERM EXP");
}

fn home(registry: &Registry, actions: &ActionRegistry) {
    header();

    println!();
    println!("Foundation online.");
    println!("Discovered commands: {}", registry.len());
    println!("Semantic actions:    {}", actions.iter().count());

    println!();
    println!("Try:");
    println!("  px actions");
    println!("  px actions git");
    println!("  px do git.ui");
    println!("  px tools lazy");
    println!("  px which lazygit");
    println!("  px doctor");
    println!("  px config");
}

fn doctor(config: &PxConfig, registry: &Registry, actions: &ActionRegistry) {
    header();

    println!();
    println!("DOCTOR");
    println!("  native backend       READY");

    match (&config.toolbox.enabled, config.toolbox.name.as_deref()) {
        (true, Some(name)) => println!("  toolbox backend      {name}"),
        _ => println!("  toolbox backend      disabled"),
    }

    println!("  toolbox source       {}", config.toolbox.source.label());
    println!("  commands discovered  {}", registry.len());
    println!("  semantic actions     {}", actions.iter().count());

    println!();

    for name in [
        "git", "lazygit", "nvim", "btop", "fzf", "rg", "fd", "gh", "gitleaks", "act",
    ] {
        match registry.preferred(name) {
            Some(tool) => println!(
                "  {:<12} {:<24} {}",
                name,
                tool.backend.label(),
                tool.executable.display()
            ),

            None => println!("  {:<12} not found", name),
        }
    }
}

fn show_config(config: &PxConfig) {
    header();

    println!();
    println!("CONFIG");
    println!(
        "  toolbox enabled      {}",
        if config.toolbox.enabled { "yes" } else { "no" }
    );
    println!(
        "  toolbox name         {}",
        config.toolbox.name.as_deref().unwrap_or("-")
    );
    println!("  toolbox source       {}", config.toolbox.source.label());

    println!();
    println!("Override with:");
    println!("  PX_TOOLBOX=<name> px ...");
    println!("  PX_TOOLBOX=off px ...");
    println!();
    println!("Persistent config:");
    println!("  ~/.config/px/config.toml");
}

fn tools(registry: &Registry, query: Option<&str>) {
    let tools: Vec<_> = match query {
        Some(query) => registry.search(query),
        None => registry.iter().collect(),
    };

    for tool in tools {
        println!(
            "{:<28} {:<24} {}",
            tool.name,
            tool.backend.label(),
            tool.executable.display()
        );
    }
}

fn actions(actions: &ActionRegistry, query: Option<&str>) {
    let matches: Vec<_> = match query {
        Some(query) => actions.search(query),
        None => actions.iter().collect(),
    };

    for action in matches {
        println!(
            "{:<20} {:<12} {:<24} {}",
            action.id, action.category, action.title, action.description
        );
    }
}

fn which(registry: &Registry, command: &str) -> i32 {
    match registry.preferred(command) {
        Some(tool) => {
            println!("command: {}", tool.name);
            println!("backend: {}", tool.backend.label());
            println!("path:    {}", tool.executable.display());

            0
        }

        None => {
            eprintln!("PX: command not found: {command}");
            127
        }
    }
}

fn open(registry: &Registry, command: &str, args: &[String]) -> i32 {
    let Some(tool) = registry.preferred(command) else {
        eprintln!("PX: command not found: {command}");
        return 127;
    };

    match px_backends::execute(tool, args) {
        Ok(status) => status.code().unwrap_or(1),

        Err(error) => {
            eprintln!(
                "PX: could not launch '{}' through {}: {error}",
                tool.name,
                tool.backend.label()
            );
            1
        }
    }
}

fn execute_action(registry: &Registry, actions: &ActionRegistry, id: &str) -> i32 {
    let Some(action) = actions.get(id) else {
        eprintln!("PX: action not found: {id}");
        return 127;
    };

    match &action.target {
        ActionTarget::Tool { command, args } => open(registry, command, args),
    }
}

fn help() {
    header();

    println!();
    println!("px");
    println!("px doctor");
    println!("px config");
    println!("px actions [query]");
    println!("px do <action-id>");
    println!("px tools [query]");
    println!("px which <command>");
    println!("px open <command> [args...]");
}

fn main() {
    let config = match PxConfig::load() {
        Ok(config) => config,
        Err(error) => {
            eprintln!("PX: configuration error: {error}");
            process::exit(2);
        }
    };

    let registry = build_registry(&config);
    let actions_registry = px_integrations::actions_for(&registry);
    let args: Vec<String> = env::args().skip(1).collect();

    let code = match args.as_slice() {
        [] => {
            home(&registry, &actions_registry);
            0
        }

        [cmd] if cmd == "doctor" || cmd == "d" => {
            doctor(&config, &registry, &actions_registry);
            0
        }

        [cmd] if cmd == "config" => {
            show_config(&config);
            0
        }

        [cmd] if cmd == "actions" || cmd == "a" => {
            actions(&actions_registry, None);
            0
        }

        [cmd, query] if cmd == "actions" || cmd == "a" => {
            actions(&actions_registry, Some(query));
            0
        }

        [cmd, id] if cmd == "do" => execute_action(&registry, &actions_registry, id),

        [cmd] if cmd == "tools" || cmd == "t" => {
            tools(&registry, None);
            0
        }

        [cmd, query] if cmd == "tools" || cmd == "t" => {
            tools(&registry, Some(query));
            0
        }

        [cmd, target] if cmd == "which" => which(&registry, target),

        [cmd, target, rest @ ..] if cmd == "open" => open(&registry, target, rest),

        [cmd] if cmd == "help" || cmd == "--help" || cmd == "-h" => {
            help();
            0
        }

        _ => {
            help();
            2
        }
    };

    process::exit(code);
}
