#!/usr/bin/env python3
"""Hospital native staffing issuer: real Linux packet evidence CI witness.

Runs ONLY in GitHub Actions. Uses AF_UNIX socketpair and pidfd, not a
listening service, production socket, actual root issuer or real Hospital
database. No local operator/machine configuration or staff grant is written.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from unittest.mock import patch

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or os.name != "posix"
        or not sys.platform.startswith("linux")
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()):
    raise SystemExit("HOSPITAL_KERNEL_STAFFING_WITNESS_HOLD // CI_ONLY")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import px_hospital_staffing_native_peer as peer
import px_hospital_staffing_transport as transport
import px_hospital_staffing_admission as admission
import px_hospital_protected_store_bridge as bridge
import px_hospital_room_writer as room_writer

assert peer.ISSUER_UID == 0
assert hasattr(os, "pidfd_open")
assert hasattr(socket, "SO_PEERCRED")
assert hasattr(socket, "SCM_CREDENTIALS")
assert hasattr(socket, "SO_PASSCRED")
assert hasattr(socket, "SOCK_SEQPACKET")
assert bridge.route_coverage()
assert "session-attach-atomic" not in bridge.WRITE_COMMANDS
assert "session-succeed-atomic" not in bridge.WRITE_COMMANDS
assert "SESSION_ATTACH" not in room_writer._ALLOWED_WRITE
assert "DOCTOR_SUCCEED" not in room_writer._ALLOWED_WRITE


def refuse(call, expected):
    try:
        call()
    except (peer.NativePeerHold, RuntimeError) as exc:
        assert expected in str(exc), (expected, str(exc))
        return
    raise AssertionError("UNTRUSTED_PEER_WAS_ACCEPTED")


def pair():
    a,b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    a.settimeout(2)
    b.settimeout(2)
    # Enable Linux SCM_CREDENTIALS before any client queues a packet.
    # Enabling SO_PASSCRED only after send can yield anonymous/synthetic
    # credentials for a queued packet; rejecting such frames is correct.
    a.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    b.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    return a,b


# A byte-identical request must remain untrusted absent an authenticated
# sender and a separately approved signed staff grant.
data = b'{"kind":"prepare","action":"SESSION_ATTACH"}'
reader, sender = pair()
with reader, sender:
    sender.sendall(data)
    packet, evidence = peer._receive_packet(
        reader, expected_uid=os.getuid()
    )
    assert packet == data
    assert evidence.pid == os.getpid()
    assert evidence.uid == os.getuid()
    assert evidence.gid == os.getgid()
    assert evidence.start_ticks > 0
    assert evidence.packet_length == len(data)
    assert evidence.source == "linux-so-peercred-scm-credentials"
    refuse(lambda:peer.authorize_staffing_from_packet(evidence, data),
           "NATIVE_STAFFING_AUTHORITY_NOT_INSTALLED")
    refuse(lambda:transport.dispatch_native_request(data),
           "NATIVE_STAFFING_SERVICE_NOT_INSTALLED")
    refuse(lambda:admission.dispatch_native_staffing(data),
           "NATIVE_SESSION_DOCTOR_AUTHORITY_NOT_INSTALLED")

# Root-only public admission must refuse an ordinary runner's UID.
if os.getuid() != 0:
    reader,sender=pair()
    with reader,sender:
        sender.sendall(data)
        refuse(lambda:peer.receive_root_issuer_packet(reader),
               "WRONG_NATIVE_ISSUER_IDENTITY")

# Neither peer identity nor claimed process details come from JSON.
reader,sender=pair()
with reader,sender:
    sender.sendall(data)
    refuse(lambda:peer._receive_packet(
        reader, expected_uid=os.getuid()+1),
        "WRONG_NATIVE_ISSUER_IDENTITY")

reader,sender=pair()
with reader,sender:
    sender.sendall(data)
    refuse(lambda:peer._receive_packet(
        reader, expected_uid=-1),"PINNED_ISSUER_UID_REQUIRED")

# Wrong Unix socket type must be denied even with valid kernel UID.
reader,sender = socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
with reader,sender:
    sender.sendall(data)
    refuse(lambda:peer._receive_packet(
        reader,expected_uid=os.getuid()),
        "CONNECTED_UNIX_SEQPACKET_REQUIRED")

reader,sender = socket.socketpair(socket.AF_UNIX,socket.SOCK_DGRAM)
with reader,sender:
    sender.send(data)
    refuse(lambda:peer._receive_packet(
        reader,expected_uid=os.getuid()),
        "CONNECTED_UNIX_SEQPACKET_REQUIRED")

# Full packet boundary: reject anything larger than MAX_PACKET, without
# processing its prefix as a valid operation.
reader,sender=pair()
with reader,sender:
    sender.send(b"a"*(peer.MAX_PACKET+1))
    refuse(lambda:peer._receive_packet(
        reader,expected_uid=os.getuid()),
        "PACKET_TRUNCATED_OR_OUT_OF_BOUNDS")

# Empty/closed peer supplies no valid instruction.
reader,sender=pair()
with reader,sender:
    sender.close()
    refuse(lambda:peer._receive_packet(
        reader,expected_uid=os.getuid()),
        "PACKET_TRUNCATED_OR_OUT_OF_BOUNDS")

# Process birth must be stable from first look through packet receipt.
reader,sender=pair()
with reader,sender:
    sender.sendall(data)
    true_ticks=peer._proc_start_ticks(os.getpid())
    with patch.object(peer,"_proc_start_ticks",
                      side_effect=[true_ticks,true_ticks+1]):
        refuse(lambda:peer._receive_packet(
            reader,expected_uid=os.getuid()),"PROCESS_BIRTH_CHANGED")

# An inherited descriptor can be written by a different process. Linux's
# SO_PEERCRED describes the connected endpoint, while SCM_CREDENTIALS
# describes the actual packet sender. Refuse the forked sender.
if hasattr(os,"fork"):
    reader,sender=pair()
    child=os.fork()
    if child == 0:
        try:
            reader.close()
            sender.sendall(data)
        finally:
            os._exit(0)
    try:
        sender.close()
        with reader:
            refuse(lambda:peer._receive_packet(
                reader,expected_uid=os.getuid()),"PACKET_ISSUER_CHANGED")
    finally:
        waited,status=os.waitpid(child,0)
        assert waited==child
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0

print("HOSPITAL NATIVE ISSUER KERNEL WITNESS // PASS // Linux peer+packet PID/UID/GID, retained pidfd, process-start checks, fork mismatch, truncation, nonroot denial; NO SERVICE OR GRANT")
