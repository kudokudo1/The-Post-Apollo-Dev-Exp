#!/usr/bin/env python3
"""B35 offline-only executable fingerprint inventory.

Accepts an EXPLICIT absolute path. Does not discover/install/execute a provider,
inspect login state, read a provider configuration, use network, or contact
Hospital. SHA-256 identifies observed bytes; it is NOT provider attestation,
isolation, or launch permission. Local execution is operator-initiated only.
"""
import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

PROVIDERS = frozenset(("codex", "hermes"))
MAX_BINARY_BYTES = 128 * 1024 * 1024
CHUNK = 1024 * 1024


class InventoryRefusal(ValueError):
    """Stable, non-sensitive failure reason; never include provider output."""


def _refuse(reason):
    raise InventoryRefusal("B35_REFUSED_" + reason)


def _identity(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def inventory_binary(provider, absolute_path):
    """Read and fingerprint an explicitly named executable, never run it."""
    if type(provider) is not str or provider not in PROVIDERS:
        _refuse("PROVIDER")
    if (type(absolute_path) is not str or not absolute_path.startswith("/")
            or "\x00" in absolute_path or "//" in absolute_path
            or any(x in (".", "..") for x in absolute_path.split("/"))):
        _refuse("ABSOLUTE_PATH")
    try:
        resolved = Path(absolute_path).resolve(strict=True)
        # No final symlink following after resolution. O_NONBLOCK prevents a
        # swapped-in FIFO/device from hanging before fstat checks its type.
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(str(resolved), flags)
    except (OSError, RuntimeError, ValueError):
        _refuse("UNREADABLE_PATH")

    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _refuse("NOT_REGULAR_FILE")
        if not (before.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
            _refuse("NOT_EXECUTABLE")
        if not 0 < before.st_size <= MAX_BINARY_BYTES:
            _refuse("FILE_SIZE")
        digest = hashlib.sha256()
        length = 0
        prefix = b""
        while True:
            part = os.read(fd, CHUNK)
            if not part:
                break
            if length == 0:
                prefix = part[:4]
            length += len(part)
            if length > MAX_BINARY_BYTES:
                _refuse("FILE_SIZE")
            digest.update(part)
        after = os.fstat(fd)
        if length != before.st_size or _identity(before) != _identity(after):
            _refuse("CHANGED_DURING_READ")
        file_kind = ("ELF" if prefix == b"\x7fELF"
                     else "SHEBANG" if prefix.startswith(b"#!")
                     else "OTHER_EXECUTABLE")
        return {
            "schema": "B35_READ_ONLY_BINARY_INVENTORY_V1",
            "provider": provider,
            "inputPath": absolute_path,
            "resolvedPath": str(resolved),
            "symlinkResolved": absolute_path != str(resolved),
            "fileKind": file_kind,
            "sizeBytes": length,
            "sha256": digest.hexdigest(),
            "fileDevice": before.st_dev,
            "fileInode": before.st_ino,
            "fileMtimeNs": before.st_mtime_ns,
            "versionObserved": False,
            "providerStarted": False,
            "credentialsInspected": False,
            "toolCalls": 0,
            "modelCalls": 0,
            "hospitalWrites": 0,
            "modelOnlyCertified": False,
            "productionReady": False,
            "decision": "INVENTORY_ONLY",
        }
    except OSError:
        _refuse("UNREADABLE_PATH")
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline Codex/Hermes executable hash only; no launch."
    )
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--binary", required=True,
                        help="Explicit absolute executable path (no PATH lookup)")
    args = parser.parse_args(argv)
    try:
        result = inventory_binary(args.provider, args.binary)
    except InventoryRefusal as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
