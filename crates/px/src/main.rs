use px_core::Registry;

use std::env;
use std::process;

fn build_registry() -> Registry {
    let mut registry = Registry::new();

    match px_discovery::discover_environment() {
        Ok(tools) => registry.extend(tools),

        Err(error) => {
            eprintln!("PX: PATH discovery failed: {error}");
        }
    }

    registry
}

fn header() {
    println!("PX // TERM EXP");
}

fn home(registry: &Registry) {
    header();

    println!();
    println!("Foundation online.");
    println!("Discovered commands: {}", registry.len());

    println!();
    println!("Try:");

    println!("  px tools lazy");
    println!("  px which lazygit");
    println!("  px doctor");

    println!();
    println!(
        "LazyVim-style interface comes after \
         discovery + routing are proven."
    );
}

fn doctor(registry: &Registry) {
    header();

    println!();
    println!("DOCTOR");

    println!("  native backend       READY");
    println!("  commands discovered  {}", registry.len());

    println!();

    for name in ["git", "lazygit", "nvim", "btop", "fzf", "rg", "fd"] {
        match registry.preferred(name) {
            Some(tool) => println!(
                "  {:<12} {:<10} {}",
                name,
                tool.backend.label(),
                tool.executable.display()
            ),

            None => println!("  {:<12} not found", name),
        }
    }
}

fn tools(registry: &Registry, query: Option<&str>) {
    let tools: Vec<_> = match query {
        Some(query) => registry.search(query),
        None => registry.iter().collect(),
    };

    for tool in tools {
        println!(
            "{:<28} {:<12} {}",
            tool.name,
            tool.backend.label(),
            tool.executable.display()
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

fn help() {
    header();

    println!();
    println!("px");
    println!("px doctor");
    println!("px tools [query]");
    println!("px which <command>");
    println!("px open <command> [args...]");
}

fn main() {
    let registry = build_registry();

    let args: Vec<String> = env::args().skip(1).collect();

    let code = match args.as_slice() {
        [] => {
            home(&registry);
            0
        }

        [cmd] if cmd == "doctor" || cmd == "d" => {
            doctor(&registry);
            0
        }

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
