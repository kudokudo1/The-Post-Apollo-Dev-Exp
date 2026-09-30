use px_core::{Backend, Tool};

use std::ffi::OsString;
use std::io;
use std::process::{Command, ExitStatus};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Invocation {
    pub program: OsString,
    pub args: Vec<OsString>,
}

impl Invocation {
    fn into_command(self) -> Command {
        let mut command = Command::new(self.program);
        command.args(self.args);
        command
    }
}

pub fn resolve(tool: &Tool, args: &[String]) -> io::Result<Invocation> {
    match &tool.backend {
        Backend::Native => Ok(Invocation {
            program: tool.executable.as_os_str().to_owned(),
            args: args.iter().map(OsString::from).collect(),
        }),

        Backend::Toolbox { name } => {
            let mut resolved_args = vec![
                OsString::from("run"),
                OsString::from("-c"),
                OsString::from(name),
                OsString::from("--"),
                tool.executable.as_os_str().to_owned(),
            ];

            resolved_args.extend(args.iter().map(OsString::from));

            Ok(Invocation {
                program: OsString::from("toolbox"),
                args: resolved_args,
            })
        }

        Backend::Distrobox { name } => Err(io::Error::new(
            io::ErrorKind::Unsupported,
            format!("Distrobox backend '{name}' is not implemented yet"),
        )),
    }
}

pub fn execute(tool: &Tool, args: &[String]) -> io::Result<ExitStatus> {
    resolve(tool, args)?.into_command().status()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_invocation_preserves_arguments() {
        let tool = Tool::native("echo", "/usr/bin/echo");
        let args = vec!["hello world".to_owned(), "--literal".to_owned()];

        let invocation = resolve(&tool, &args).unwrap();

        assert_eq!(invocation.program, OsString::from("/usr/bin/echo"));
        assert_eq!(
            invocation.args,
            vec![OsString::from("hello world"), OsString::from("--literal")]
        );
    }

    #[test]
    fn toolbox_invocation_keeps_backend_boundary_explicit() {
        let tool = Tool::toolbox("lazygit", "/usr/bin/lazygit", "fedora-toolbox-44");
        let args = vec!["--version".to_owned()];

        let invocation = resolve(&tool, &args).unwrap();

        assert_eq!(invocation.program, OsString::from("toolbox"));
        assert_eq!(
            invocation.args,
            vec![
                OsString::from("run"),
                OsString::from("-c"),
                OsString::from("fedora-toolbox-44"),
                OsString::from("--"),
                OsString::from("/usr/bin/lazygit"),
                OsString::from("--version"),
            ]
        );
    }
}
