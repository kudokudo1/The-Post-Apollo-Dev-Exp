#!/usr/bin/env python3
"""INT1-P1: isolated disposable test subprocess environment, NOT a runtime sandbox.

Construct and verify the fixture root before the FIRST PX/Hospital subprocess.
Does not confer any security guarantee on a production Doctor, and never
copies the caller's environment (especially PX_HOSPITAL_DB).
"""
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

class FixtureRefusal(RuntimeError):
    pass

# Every value below is forced under the newly created 0700 fixture root.
DIRECTORIES = {
    "PX_HOSPITAL_DATA_DIR": "hospital/data",
    "HOME": "home",
    "XDG_DATA_HOME": "xdg/data",
    "XDG_CONFIG_HOME": "xdg/config",
    "XDG_CACHE_HOME": "xdg/cache",
    "XDG_RUNTIME_DIR": "xdg/runtime",
    "TMPDIR": "tmp",
    "PX_AGENT_LOCK_DIR": "locks",
    "PX_AGENT_AUTHORITY_DIR": "authority",
}
FILES = {
    "PX_HOSPITAL_DB": "hospital/data/hospital.db",
    "PX_AGENT_PROVIDER_CONFIG": "providers/fake.json",
}
EXTRAS = ("bed", "scratch", "broker", "artifacts", "logs", "providers")
EXPECTED = frozenset({*DIRECTORIES, *FILES, "PATH", "LANG", "LC_ALL",
                       "PYTHONDONTWRITEBYTECODE"})

def _trusted_directory(root, path):
    """Walk components with O_NOFOLLOW dirfds; reject links/owner/mode."""
    root = Path(root)
    path = Path(path)
    if not path.is_absolute() or path == root or root not in path.parents:
        raise FixtureRefusal("INT1-P1: path outside disposable root")
    if ".." in path.parts:
        raise FixtureRefusal("INT1-P1: traversal")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    current_fd = root_fd
    try:
        root_stat = os.fstat(current_fd)
        if root_stat.st_uid != os.geteuid() or stat.S_IMODE(root_stat.st_mode) != 0o700:
            raise FixtureRefusal("INT1-P1: untrusted fixture root")
        for component in path.relative_to(root).parts:
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         dir_fd=current_fd)
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                os.close(fd)
                raise FixtureRefusal("INT1-P1: wrong directory ownership/mode")
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = fd
    except (OSError, ValueError) as exc:
        raise FixtureRefusal("INT1-P1: symlink or non-directory path") from exc
    finally:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def _remove_tree_fd(directory_fd):
    """Prune file entries only through already pinned directory FDs.

    Descendant directories are opened relative to a pinned parent and with
    O_NOFOLLOW. Directory names are never removed here, because a separate
    identity check and pathname rmdir are not an atomic inode-conditional
    operation. Empty directory hierarchy is deliberately left to be
    discarded with the disposable CI runner.

    A concurrently inserted entry *inside the original fixture inode*
    is not a distinct external path and is outside this synthetic test's
    concurrent malicious-content threat model.
    """
    with os.scandir(directory_fd) as entries:
        for entry in entries:
            name = entry.name
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(before.st_mode):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY |
                             os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=directory_fd)
                try:
                    pinned = os.fstat(fd)
                    if (pinned.st_dev, pinned.st_ino) != (before.st_dev, before.st_ino):
                        raise FixtureRefusal("INT1-P1: descendant replaced before traversal")
                    _remove_tree_fd(fd)
                finally:
                    os.close(fd)
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if (not stat.S_ISDIR(current.st_mode) or
                        (current.st_dev, current.st_ino) !=
                        (before.st_dev, before.st_ino)):
                    raise FixtureRefusal("INT1-P1: descendant changed during cleanup")
                # C2: a post-check directory-name removal is not inode-
                # conditional. Do not remove descendant directory names.
                # Only the already-pinned inode's FILE contents are pruned.
            else:
                # Symlinks are unlinked as links: never followed as directories.
                os.unlink(name, dir_fd=directory_fd)

class DisposablePX:
    """Fixture-only runner; no subprocess bypasses assert_safe_environment."""
    def __init__(self, repository):
        self.repository = Path(repository).absolute()
        self.root = Path(tempfile.mkdtemp(prefix="px-int1-", dir="/tmp"))
        os.chmod(self.root, 0o700)
        st = os.lstat(self.root)
        self._identity = (st.st_dev, st.st_ino)
        self.env = None
        try:
            for name in [*DIRECTORIES.values(), *EXTRAS, "providers"]:
                (self.root / name).mkdir(mode=0o700, parents=True, exist_ok=True)
            # pathlib.mkdir(parents=True) uses default permissions for
            # intermediate directories; explicitly restrict those as well.
            for directory in self.root.rglob("*"):
                if directory.is_dir() and not directory.is_symlink():
                    directory.chmod(0o700)
            self.env = {
                "PATH": "/usr/bin:/bin",
                "LANG": "C", "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
                **{k: "/fixture/" + v for k, v in DIRECTORIES.items()},
                **{k: "/fixture/" + v for k, v in FILES.items()},
            }
            # Create a fake-only registry; never copy real provider records.
            registry = self.root / FILES["PX_AGENT_PROVIDER_CONFIG"]
            fd = os.open(registry, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "providers": {}}, stream)
            self.assert_safe_environment()
        except BaseException:
            self.close()
            raise

    def assert_safe_environment(self):
        if self.env is None or set(self.env) != EXPECTED:
            raise FixtureRefusal("INT1-P1: non-allowlisted child environment")
        if (self.env["PATH"], self.env["LANG"], self.env["LC_ALL"],
                self.env["PYTHONDONTWRITEBYTECODE"]) != ("/usr/bin:/bin", "C", "C", "1"):
            raise FixtureRefusal("INT1-P1: child environment overwritten")
        if self.root.is_symlink() or not self.root.is_dir():
            raise FixtureRefusal("INT1-P1: root redirected")
        if self.root.resolve(strict=True) != self.root:
            raise FixtureRefusal("INT1-P1: root path alias")
        for k, relative in DIRECTORIES.items():
            if self.env[k] != "/fixture/" + relative:
                raise FixtureRefusal("INT1-P1: destination overridden: " + k)
            _trusted_directory(self.root, self.root / relative)
        for relative in EXTRAS:
            _trusted_directory(self.root, self.root / relative)
        for k, relative in FILES.items():
            f = self.root / relative
            if self.env[k] != "/fixture/" + relative:
                raise FixtureRefusal("INT1-P1: file destination overridden: " + k)
            _trusted_directory(self.root, f.parent)
            try:
                st = os.lstat(f)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
                raise FixtureRefusal("INT1-P1: invalid file or symlink: " + k)
        _trusted_directory(self.root, self.root / "providers")
        if (self.root / FILES["PX_AGENT_PROVIDER_CONFIG"]).stat().st_size == 0:
            raise FixtureRefusal("INT1-P1: empty fake registry")
        return True

    def _root_handle(self):
        """Pin the validated physical root, never a mutable pathname."""
        self.assert_safe_environment()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            fd = os.open(self.root, flags)
            st = os.fstat(fd)
            if (st.st_dev, st.st_ino) != self._identity or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o700:
                raise FixtureRefusal("INT1-P1: root identity changed")
            return fd
        except (OSError, FixtureRefusal) as exc:
            if "fd" in locals():
                os.close(fd)
            raise FixtureRefusal("INT1-P1: cannot pin original fixture root") from exc

    def run(self, *args, timeout=20, input=None, after_anchor=None):
        """Launch ONLY through an OS-isolated mount namespace.

        No host pathname is writable in the child except a verified root
        opened as an O_NOFOLLOW directory FD and bind-mounted through that FD.
        SQLite can safely create DB, WAL, SHM and journals only on this mount.
        If namespaces are unavailable, fail closed; there is no host fallback.
        """
        root_fd = self._root_handle()
        try:
            if after_anchor is not None:
                # Test-only adversarial path swap AFTER verification and FD pin.
                after_anchor()
            command = [
                self._trusted_bwrap(),
                "--unshare-all", "--die-with-parent", "--new-session",
                "--cap-drop", "ALL",
                "--ro-bind", "/usr", "/usr",
                "--symlink", "usr/bin", "/bin",
                "--symlink", "usr/lib", "/lib",
                "--symlink", "usr/lib64", "/lib64",
                "--symlink", "usr/sbin", "/sbin",
                "--proc", "/proc", "--dev", "/dev",
                "--dir", "/var", "--dir", "/home", "--dir", "/run",
                "--tmpfs", "/tmp",
                "--dir", "/source", "--dir", "/source/bin",
                # Never mount the entire checkout: Actions .git/config can
                # contain checkout credentials. Only source files necessary
                # for the disposable Hospital init are visible.
                "--ro-bind", str(self.repository / "bin/px"), "/source/bin/px",
                "--ro-bind", str(self.repository / "bin/px-hospital-store"), "/source/bin/px-hospital-store",
                # INT1-A: expose only these additional audited source files.
                # The default no-provider fixture environment is unchanged.
                "--ro-bind", str(self.repository / "bin/px-agent"), "/source/bin/px-agent",
                "--ro-bind", str(self.repository / "bin/hospital_target_preflight.py"),
                "/source/bin/hospital_target_preflight.py",
                "--ro-bind", str(self.repository / "bin/px_int1_fake_guard.py"),
                "/source/bin/px_int1_fake_guard.py",
                # INT1-B1 detached storage proof: never exposes host paths.
                "--ro-bind", str(self.repository / "bin/px_int1_fake_atomic.py"),
                "/source/bin/px_int1_fake_atomic.py",
                # Detached B2 authority-epoch trigger proof, also fixture only.
                "--ro-bind", str(self.repository / "bin/px_int1_fake_epoch.py"),
                "/source/bin/px_int1_fake_epoch.py",
                # Detached B4 continuity epoch hooks, fixture-only.
                "--ro-bind", str(self.repository / "bin/px_int1_fake_continuity.py"),
                "/source/bin/px_int1_fake_continuity.py",
                # B9 idle child source: ro-only, no executable broker grants.
                "--ro-bind", str(self.repository / "bin/px_int1_fake_broker.py"),
                "/source/bin/px_int1_fake_broker.py",
                "--ro-bind", str(self.repository / "bin/px_int1_fake_dispatch.py"),
                "/source/bin/px_int1_fake_dispatch.py",
                "--ro-bind", str(self.repository / "bin/px_int1_fake_recovery.py"),
                "/source/bin/px_int1_fake_recovery.py",
                # The FD refers to the original inode even if the host
                # renames the root or substitutes a symlink after preflight.
                "--bind", "/proc/self/fd/" + str(root_fd), "/fixture",
                "--clearenv",
            ]
            for key, value in self.env.items():
                command.extend(("--setenv", key, value))
            command += ["--chdir", "/fixture", *args]
            def restrict_child_umask():
                os.umask(0o077)
            return subprocess.run(
                command, env={"PATH": "/usr/bin:/bin", "LANG": "C",
                              "PYTHONDONTWRITEBYTECODE": "1"},
                cwd="/", input=input, capture_output=True, text=True,
                timeout=timeout, check=False, close_fds=True,
                pass_fds=(root_fd,), preexec_fn=restrict_child_umask,
            )
        finally:
            os.close(root_fd)

    def _trusted_bwrap(self):
        """Use the same fixed executable policy as EXEC-S1, no PATH fallback."""
        for parent in (Path("/"), Path("/usr"), Path("/usr/bin")):
            s = parent.lstat()
            if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
                raise FixtureRefusal("INT1-P1: untrusted bwrap parent")
        path = Path("/usr/bin/bwrap")
        try:
            s = path.lstat()
        except OSError as exc:
            raise FixtureRefusal("INT1-P1: fixed Bubblewrap missing") from exc
        if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022 or not os.access(path, os.X_OK):
            raise FixtureRefusal("INT1-P1: untrusted fixed Bubblewrap")
        return str(path)

    def hospital(self, *args, after_anchor=None, input=None):
        return self.run("/bin/bash", "/source/bin/px", "hospital",
                        *args, "--json", after_anchor=after_anchor, input=input)

    def agent(self, *args, input=None):
        # The real bin/px-agent Python executable runs directly inside the
        # same protected mount namespace. Avoid adding Bash's _/SHLVL env.
        return self.run("/usr/bin/python3", "-B", "/source/bin/px-agent",
                        *args, "--json", input=input)

    def close(self):
        """Prune only the original disposable inode by anchored descriptors.

        Quarantine separates this fixture from its original public pathname.
        Opening the verified quarantined directory with O_NOFOLLOW pins
        its identity before recursively pruning files. Directory names,
        including the emptied fixture and quarantine directories, are never
        removed: they remain for disposal with the ephemeral CI runner.
        """
        try:
            st = os.lstat(self.root)
        except FileNotFoundError:
            return
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or
                stat.S_IMODE(st.st_mode) != 0o700 or
                (st.st_dev, st.st_ino) != self._identity):
            return
        quarantine = Path(tempfile.mkdtemp(prefix="px-int1-dispose-", dir="/tmp"))
        qfd = os.open(quarantine, os.O_RDONLY | os.O_DIRECTORY |
                      os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            try:
                os.rename(self.root, "fixture", dst_dir_fd=qfd)
            except FileNotFoundError:
                return
            root_fd = os.open("fixture", os.O_RDONLY | os.O_DIRECTORY |
                              os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=qfd)
            try:
                anchored = os.fstat(root_fd)
                if (not stat.S_ISDIR(anchored.st_mode) or
                        (anchored.st_dev, anchored.st_ino) != self._identity):
                    raise FixtureRefusal("INT1-P1: substituted cleanup root")
                # Critical: the recursive walk uses root_fd ONLY. Never call
                # shutil.rmtree(target) after inode verification.
                _remove_tree_fd(root_fd)
                try:
                    current = os.stat("fixture", dir_fd=qfd, follow_symlinks=False)
                except FileNotFoundError as exc:
                    raise FixtureRefusal("INT1-P1: cleanup root disappeared") from exc
                if (not stat.S_ISDIR(current.st_mode) or
                        (current.st_dev, current.st_ino) != self._identity):
                    raise FixtureRefusal("INT1-P1: cleanup root replaced during deletion")
                # C2: a same-UID process could substitute an empty
                # foreign root after this identity verification. Leave
                # the original, now file-pruned tree in quarantine.
                # No pathname-based final removal is attempted.
            finally:
                os.close(root_fd)
        finally:
            os.close(qfd)
            # C2: quarantine.rmdir() would create the same check/delete
            # race. Intentionally leave the empty hierarchy for CI runner
            # disposal instead of deleting a potentially swapped name.

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
