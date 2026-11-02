#!/usr/bin/env python3
"""B38-E synthetic model-only SUBPROCESS and HMAC-framed stdio IPC.

OFFLINE TEST FIXTURE ONLY. No provider/HTTP/SDK/Hermes/native tools/broker,
no actual Hospital authority, no OS confinement of the sender, no real auth.
A fresh random *fake* shared key is given to a single child via a private
inherited pipe FD; it is not a provider credential. The child handles exactly
one signed, tool-free fake request and returns fixed prewritten fake text.
"""
import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

# Python -I omits script directories; only add this pinned repository bin path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from px_s3_b37a_tool_free_contract import validate_wire_payload
from px_s3_b37b_sealed_handoff import SealedFixture, verify_fixture
from px_s3_b38c_transport_policy_fixture import (
    default_fake_manifest, prepare_fake_plan, recheck_fake_plan,
)

VERSION = 1
REQUEST = "B38E_FAKE_MODEL_ONLY_REQUEST"
REPLY = "B38E_FAKE_MODEL_ONLY_REPLY"
TEXT = "B38E prewritten synthetic model-only text"
MAX_REQUEST = 15000
MAX_REPLY = 2048
KEY_LEN = 32
NONCE = re.compile(r"[0-9a-f]{32}\Z")
CHILD_ENV = {
    "LANG": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
}


class Refused(RuntimeError):
    """Fixed diagnostics without caller payloads or fake-secret bytes."""


def _deny(code):
    raise Refused("B38E_REFUSED_" + code)


def _json(obj):
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("ascii")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _deny("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _nonfinite(_):
    _deny("NONFINITE_NUMBER")


def _parse(raw, limit):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        _deny("MESSAGE_TYPE_OR_SIZE")
    try:
        data = json.loads(raw.decode("ascii", "strict"),
                          object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (UnicodeError, ValueError, RecursionError):
        _deny("MESSAGE_ENCODING")
    if type(data) is not dict:
        _deny("MESSAGE_SCHEMA")
    return data


def _sign(obj, key):
    if type(key) is not bytes or len(key) != KEY_LEN:
        _deny("FAKE_KEY_INVALID")
    return hmac.new(key, _json(obj), hashlib.sha256).hexdigest()


def _auth(data, expected, key):
    if type(data) is not dict or set(data) != set(expected) | {"mac"}:
        _deny("FRAME_SCHEMA")
    for name, typ in expected.items():
        if type(data[name]) is not typ:
            _deny("FRAME_TYPE")
    mac = data["mac"]
    if type(mac) is not str or len(mac) != 64:
        _deny("FRAME_MAC")
    unsigned = {k: data[k] for k in expected}
    if not hmac.compare_digest(mac, _sign(unsigned, key)):
        _deny("FRAME_AUTH")
    return unsigned


REQUEST_SCHEMA = {
    "kind": str, "version": int, "nonce": str,
    "request_id": str, "payload_b64": str, "scope_sha256": str,
}
REPLY_SCHEMA = {
    "kind": str, "version": int, "nonce": str,
    "request_id": str, "pid": int, "text": str,
}


def build_fake_request(sealed, *, current_binding, nonce, fake_key):
    """Pure signer, not a dispatch authority. Never grants provider access."""
    try:
        verify_fixture(sealed, current_binding=current_binding)
    except Exception:
        _deny("SEALED_FIXTURE_INVALID")
    if type(nonce) is not str or NONCE.fullmatch(nonce) is None:
        _deny("NONCE_INVALID")
    msg = {
        "kind": REQUEST, "version": VERSION, "nonce": nonce,
        "request_id": sealed.client_request_id,
        "payload_b64": base64.b64encode(sealed.payload).decode("ascii"),
        "scope_sha256": hashlib.sha256(sealed.binding_json.encode("ascii")).hexdigest(),
    }
    msg["mac"] = _sign(msg, fake_key)
    out = _json(msg)
    if len(out) > MAX_REQUEST:
        _deny("REQUEST_OVER_BUDGET")
    return out


def parse_child_request(raw, fake_key):
    msg = _auth(_parse(raw, MAX_REQUEST), REQUEST_SCHEMA, fake_key)
    if msg["kind"] != REQUEST or msg["version"] != VERSION:
        _deny("PROTOCOL_VERSION")
    if NONCE.fullmatch(msg["nonce"]) is None:
        _deny("NONCE_INVALID")
    if not msg["request_id"].startswith("b37b.") or len(msg["request_id"]) != 69:
        _deny("REQUEST_ID_INVALID")
    if re.fullmatch(r"[0-9a-f]{64}", msg["scope_sha256"]) is None:
        _deny("SCOPE_DIGEST_INVALID")
    try:
        raw_payload = base64.b64decode(msg["payload_b64"], validate=True)
        if base64.b64encode(raw_payload).decode("ascii") != msg["payload_b64"]:
            _deny("PAYLOAD_ENCODING")
        validate_wire_payload(raw_payload)
    except (ValueError, UnicodeError, TypeError):
        _deny("TOOL_FREE_REQUEST_INVALID")
    return msg


def build_child_reply(msg, fake_key, pid):
    response = {
        "kind": REPLY, "version": VERSION,
        "nonce": msg["nonce"], "request_id": msg["request_id"],
        "pid": pid, "text": TEXT,
    }
    response["mac"] = _sign(response, fake_key)
    return _json(response)


def verify_child_reply(raw, *, fake_key, nonce, request_id, expected_pid):
    reply = _auth(_parse(raw, MAX_REPLY), REPLY_SCHEMA, fake_key)
    if (reply["kind"] != REPLY or reply["version"] != VERSION or
            reply["nonce"] != nonce or reply["request_id"] != request_id or
            reply["pid"] != expected_pid or reply["text"] != TEXT):
        _deny("REPLY_MISMATCH")
    return reply


def _read_key(fd):
    if type(fd) is not int or fd < 3:
        _deny("KEY_DESCRIPTOR_INVALID")
    try:
        chunks = []
        remaining = KEY_LEN + 1
        while remaining:
            piece = os.read(fd, remaining)
            if not piece:
                break
            chunks.append(piece)
            remaining -= len(piece)
    except OSError:
        _deny("KEY_DESCRIPTOR_UNREADABLE")
    finally:
        os.close(fd)
    key = b"".join(chunks)
    if len(key) != KEY_LEN:
        _deny("FAKE_KEY_INVALID")
    return key


def child_main(fd):
    try:
        key = _read_key(fd)
        line = sys.stdin.buffer.readline(MAX_REQUEST + 2)
        if not line.endswith(b"\n"):
            _deny("MESSAGE_TERMINATOR")
        msg = parse_child_request(line[:-1], key)
        answer = build_child_reply(msg, key, os.getpid())
        sys.stdout.buffer.write(answer + b"\n")
        sys.stdout.buffer.flush()
        return 0
    except (Refused, OSError, ValueError, TypeError):
        # Do not echo payload or fake credentials in child output.
        return 9


@dataclass(frozen=True, slots=True)
class FakeProcessReceipt:
    text: str
    request_id: str
    child_pid: int
    provenance: str = "B38E_SEPARATE_PROCESS_SYNTHETIC_ONLY"
    model_calls: int = 0
    tool_calls: int = 0
    network_calls: int = 0
    credential_isolation_certified: bool = False
    sender_os_isolated: bool = False
    launch_authorized: bool = False
    production_ready: bool = False


def exchange_in_separate_fake_process(sealed, *, current_binding):
    """One-shot fake child over signed stdio. Does NOT mutate B37-C ledger."""
    if type(sealed) is not SealedFixture:
        _deny("SEAL_TYPE")
    try:
        plan = prepare_fake_plan(default_fake_manifest(),
                                 sealed=sealed, current_binding=current_binding)
        proof = recheck_fake_plan(plan, default_fake_manifest(),
                                  sealed=sealed, current_binding=current_binding)
        if (proof.get("decision") != "OFFLINE_SHAPE_ONLY" or
                proof.get("transportReady") is not False or
                proof.get("productionReady") is not False):
            _deny("FAKE_POLICY_REFUSED")
    except Refused:
        raise
    except Exception:
        _deny("FAKE_POLICY_REFUSED")

    fake_key = secrets.token_bytes(KEY_LEN)
    nonce = secrets.token_hex(16)
    payload = build_fake_request(sealed, current_binding=current_binding,
                                 nonce=nonce, fake_key=fake_key)
    read_fd, write_fd = os.pipe()
    proc = None
    try:
        cmd = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
               "--child", str(read_fd)]
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, close_fds=True, pass_fds=(read_fd,),
            env=dict(CHILD_ENV), cwd="/",
        )
        os.close(read_fd)
        read_fd = -1
        os.write(write_fd, fake_key)
        os.close(write_fd)
        write_fd = -1
        try:
            stdout, _ = proc.communicate(payload + b"\n", timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            _deny("CHILD_TIMEOUT")
        if proc.returncode != 0:
            _deny("CHILD_REFUSED")
        if len(stdout) > MAX_REPLY + 1 or not stdout.endswith(b"\n"):
            _deny("REPLY_ENCODING")
        reply = verify_child_reply(
            stdout[:-1], fake_key=fake_key, nonce=nonce,
            request_id=sealed.client_request_id, expected_pid=proc.pid,
        )
        return FakeProcessReceipt(text=reply["text"], request_id=reply["request_id"],
                                  child_pid=proc.pid)
    except (OSError, subprocess.SubprocessError):
        _deny("SUBPROCESS_FAILED")
    finally:
        if read_fd != -1:
            os.close(read_fd)
        if write_fd != -1:
            os.close(write_fd)
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()


def require_real_sender(*_args, **_kwargs):
    _deny("REAL_MODEL_PROVIDER_FORBIDDEN")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        try:
            fd = int(sys.argv[2])
        except ValueError:
            raise SystemExit(9)
        raise SystemExit(child_main(fd))
    raise SystemExit(9)
