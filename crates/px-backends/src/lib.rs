use px_core::{Backend, Tool};

use std::io;
use std::process::{Command, ExitStatus};

pub fn execute(tool: &Tool, args: &[String]) -> io::Result<ExitStatus> {
    match &tool.backend {
        Backend::Native => Command::new(&tool.executable).args(args).status(),

        Backend::Toolbox { name } => Err(io::Error::new(
            io::ErrorKind::Unsupported,
            format!("Toolbox backend '{name}' is not implemented yet"),
        )),

        Backend::Distrobox { name } => Err(io::Error::new(
            io::ErrorKind::Unsupported,
            format!("Distrobox backend '{name}' is not implemented yet"),
        )),
    }
}
