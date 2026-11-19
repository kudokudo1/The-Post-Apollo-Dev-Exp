"""PX Hospital protected legacy store client, pinned native-runtime contract.

This module is an unprivileged client; it NEVER opens SQLite or signs grants.
Only a native runtime process with the fixed, root-configured runtime UID may
use the full legacy-command route. An interactive desktop UID is refused.
The client checks the socket server's Linux SO_PEERCRED UID as well.

No CLI option or environment variable can replace the production socket,
database, host config, public key, runtime UID, or service owner.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys

from px_hospital_room_writer import SCHEMA, WriterHold
from px_hospital_protected_store_bridge import parse_argv

HOST_CONFIG = Path("/etc/post-apollo/hospital/room-writer.json")
HOST_SCHEMA = "post-apollo.hospital.protected-room-writer-host.v1"
HOST_FIELDS = frozenset((
    "schema", "writerUid", "clientUid", "runtimeUid",
    "stateDirectory", "socketDirectory",
))
MAX_REQUEST = 65536
MAX_RESPONSE = 1048576
MAX_BODY = 49152


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WriterHold("DUPLICATE_HOST_CONFIG")
        result[key] = value
    return result


def _reject_constant(_value):
    raise WriterHold("INVALID_CONFIG_NUMBER")


def pinned_socket_contract():
    """Verify root-owned host config, actual role UID and server path.

    This is fixed by a native installer, never by a desktop-selected file.
    The caller must be the separately installed PX runtime identity.
    """
    if (os.name != "posix" or os.getuid() != os.geteuid()
            or os.geteuid() <= 0
            or any(os.environ.get(k) for k in (
                "PX_HOSPITAL_DB", "PX_HOSPITAL_DATA_DIR",
                "PX_HOSPITAL_WRITER_SOCKET", "PX_HOSPITAL_SIGNER_KEY",
            ))):
        raise WriterHold("NATIVE_RUNTIME_IDENTITY_OR_OVERRIDE_REFUSED")
    for parent in HOST_CONFIG.parents:
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise WriterHold("UNTRUSTED_HOST_CONFIG_PARENT")
    fd = os.open(
        HOST_CONFIG, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or not 1 <= info.st_size <= 4096):
            raise WriterHold("UNTRUSTED_HOST_CONFIG")
        content = os.read(fd, 4097)
    finally:
        os.close(fd)
    try:
        cfg = json.loads(
            content.decode("utf-8", "strict"),
            object_pairs_hook=_unique, parse_constant=_reject_constant,
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise WriterHold("INVALID_HOST_CONFIG_JSON") from exc
    if (type(cfg) is not dict or set(cfg) != HOST_FIELDS
            or cfg["schema"] != HOST_SCHEMA):
        raise WriterHold("HOST_CONFIG_MISMATCH")
    owner = cfg["writerUid"]
    client = cfg["clientUid"]
    runtime = cfg["runtimeUid"]
    if (any(type(x) is not int or x <= 0 for x in (owner, client, runtime))
            or len({owner, client, runtime}) != 3
            or os.geteuid() != runtime):
        raise WriterHold("RUNTIME_UID_NOT_PINNED")
    directory = cfg["socketDirectory"]
    if (type(directory) is not str or not 1 <= len(directory) <= 256
            or "\x00" in directory):
        raise WriterHold("SOCKET_DIRECTORY_MALFORMED")
    path = Path(directory)
    if not path.is_absolute() or ".." in path.parts:
        raise WriterHold("SOCKET_DIRECTORY_NOT_PINNED")
    for parent in (path, *path.parents):
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode)
                or info.st_uid not in (0, owner)
                or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise WriterHold("SOCKET_DIRECTORY_UNTRUSTED")
    target = path / "hospital-room-writer-v1.sock"
    if len(os.fsencode(target)) >= 100:
        raise WriterHold("UNIX_SOCKET_PATH_TOO_LONG")
    return target, owner


def prepare_argv(raw, *, body_data=None):
    """Mirror the legacy --body-stdin contract without server-side stdin.

    The runtime client reads its own stdin once, bounded and UTF-8 strict,
    then passes the body through the normal validated --body argument.
    """
    if type(raw) not in (tuple, list) or not raw:
        raise WriterHold("COMMAND_ARGUMENTS_REQUIRED")
    args = list(raw)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if args.count("--body-stdin"):
        if args.count("--body-stdin") != 1 or "--body" in args:
            raise WriterHold("BODY_SOURCE_AMBIGUOUS")
        if body_data is None:
            body_data = sys.stdin.buffer.read(MAX_BODY + 1)
        if (type(body_data) is not bytes or len(body_data) > MAX_BODY
                or b"\x00" in body_data):
            raise WriterHold("BODY_EXCEEDS_LIMIT")
        try:
            body = body_data.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise WriterHold("BODY_NOT_UTF8") from exc
        idx = args.index("--body-stdin")
        args[idx:idx + 1] = ["--body", body]
    # The same parser and source authority as the protected service.
    parse_argv(args)
    return args, as_json


def send_command(socket_path: Path, expected_writer_uid: int, argv):
    """Send only one reviewed argv command; server checks actual runtime UID.

    The socket and UID parameters are internal transport boundaries.
    Production main() obtains them exclusively from pinned_socket_contract.
    """
    if (not isinstance(socket_path, Path) or not socket_path.is_absolute()
            or type(expected_writer_uid) is not int
            or expected_writer_uid <= 0):
        raise WriterHold("INVALID_NATIVE_SOCKET")
    info = socket_path.lstat()
    if (not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != expected_writer_uid
            or info.st_mode & stat.S_IWOTH):
        raise WriterHold("SOCKET_OWNER_OR_PERMISSIONS_REFUSED")
    payload = json.dumps(
        {"schema": SCHEMA, "operation": "store-command", "argv": argv},
        separators=(",", ":"), ensure_ascii=True, allow_nan=False,
    ).encode("ascii") + b"\n"
    if len(payload) > MAX_REQUEST:
        raise WriterHold("COMMAND_FRAME_TOO_LARGE")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(3)
        conn.connect(str(socket_path))
        raw_peer = conn.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"),
        )
        server_pid, server_uid, _gid = struct.unpack("3i", raw_peer)
        if server_pid <= 0 or server_uid != expected_writer_uid:
            raise WriterHold("SERVER_NOT_PROTECTED_WRITER_IDENTITY")
        conn.sendall(payload)
        conn.shutdown(socket.SHUT_WR)
        output = bytearray()
        while len(output) <= MAX_RESPONSE:
            part = conn.recv(min(16384, MAX_RESPONSE + 1 - len(output)))
            if not part:
                break
            output.extend(part)
        if len(output) > MAX_RESPONSE or output.count(b"\n") != 1:
            raise WriterHold("INVALID_BOUNDED_SERVICE_REPLY")
    try:
        reply = json.loads(
            bytes(output).decode("utf-8", "strict"),
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise WriterHold("INVALID_SERVICE_REPLY") from exc
    if (type(reply) is not dict or reply.get("ok") is not True
            or set(reply) != {"ok", "data"}):
        raise WriterHold("SERVICE_DENIED_REQUEST")
    return reply["data"]


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    socket_path, owner_uid = pinned_socket_contract()
    arguments, _as_json = prepare_argv(argv)
    # All responses retain JSON shape for scripts and Hospital continuity.
    # There is no unsafe fallback to the desktop-owned original database.
    result = send_command(socket_path, owner_uid, arguments)
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0
