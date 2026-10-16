#!/usr/bin/env python3
"""INT1-P1: isolated disposable test subprocess environment, NOT a runtime sandbox.

Construct and verify the fixture root before the FIRST PX/Hospital subprocess.
Does not confer any security guarantee on a production Doctor, and never
copies the caller's environment (especially PX_HOSPITAL_DB).
"""
import json
import os
import shutil
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

class DisposablePX:
    """Fixture-only runner; no subprocess bypasses assert_safe_environment."""
    def __init__(self, repository):
        self.repository = Path(repository).absolute()
        self.root = Path(tempfile.mkdtemp(prefix="px-int1-", dir="/tmp"))
        os.chmod(self.root, 0o700)
        self.env = None
        try:
            for name in [*DIRECTORIES.values(), *EXTRAS, "providers"]:
                (self.root / name).mkdir(mode=0o700, parents=True, exist_ok=True)
            self.env = {
                "PATH": "/usr/bin:/bin",
                "LANG": "C", "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
                **{k: str(self.root / v) for k, v in DIRECTORIES.items()},
                **{k: str(self.root / v) for k, v in FILES.items()},
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
            if self.env[k] != str(self.root / relative):
                raise FixtureRefusal("INT1-P1: destination overridden: " + k)
            _trusted_directory(self.root, self.root / relative)
        for relative in EXTRAS:
            _trusted_directory(self.root, self.root / relative)
        for k, relative in FILES.items():
            f = self.root / relative
            if self.env[k] != str(f):
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

    def run(self, *args, timeout=20, input=None):
        # Validate on every launch, including first init. Never inherit env.
        self.assert_safe_environment()
        def restrict_child_umask():
            # SQLite-created DB and journals must not be world-readable.
            os.umask(0o077)
        return subprocess.run(list(args), env=dict(self.env), cwd=str(self.root),
                              input=input, capture_output=True, text=True,
                              timeout=timeout, check=False,
                              preexec_fn=restrict_child_umask)

    def hospital(self, *args):
        return self.run("/bin/bash", str(self.repository / "bin/px"),
                        "hospital", *args, "--json")

    def close(self):
        # Removal limited to a root still owned by this fixture.
        if self.root.exists() and not self.root.is_symlink() and self.root.is_dir():
            st = os.lstat(self.root)
            if st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == 0o700:
                # Do not traverse symlinks: shutil.rmtree never recursively
                # follows directory symlinks.
                shutil.rmtree(self.root)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
