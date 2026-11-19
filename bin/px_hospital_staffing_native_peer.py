"""Hospital staffing native caller kernel evidence, source-only, no listener.

This module does not create, bind, connect to, or serve any socket. The
future *separately installed* native issuer must supply an already-connected
AF_UNIX/SOCK_SEQPACKET descriptor, with root-only peer admission. Packet
credentials originate in Linux SCM_CREDENTIALS, never a JSON field.

These checks prove one kernel process supplied a packet on a particular
Unix connection. They do NOT prove the executable's signed release, a
specific active seat, human consent, Polkit approval, authorized Doctor,
or the authenticity of any signing key. None of this module's results is
a staffing authorization; the protected native dispatcher remains CLOSED.

Based on the existing Hospital Connections issuer peer+packet checks.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import select
import socket
import stat
import struct


ISSUER_UID = 0
MAX_PACKET = 16384
_CRED_SIZE = struct.calcsize("3i")


class NativePeerHold(RuntimeError):
    pass


def _hold(reason):
    raise NativePeerHold("HOSPITAL_STAFFING_PEER_HOLD // " + reason)


@dataclass(frozen=True)
class KernelPeerEvidence:
    """Read-only observation; never a token granting Session/Doctor writes."""
    pid: int
    uid: int
    gid: int
    start_ticks: int
    packet_length: int
    source: str = "linux-so-peercred-scm-credentials"


def _connected_seqpacket(sock):
    if (not isinstance(sock, socket.socket)
            or sock.family != socket.AF_UNIX
            or (sock.type & 0xF) != socket.SOCK_SEQPACKET):
        _hold("CONNECTED_UNIX_SEQPACKET_REQUIRED")
    try:
        sock.getpeername()
    except OSError as exc:
        raise NativePeerHold(
            "HOSPITAL_STAFFING_PEER_HOLD // CONNECTED_PEER_REQUIRED"
        ) from exc
    if not all(hasattr(socket, x) for x in
               ("SO_PEERCRED", "SO_PASSCRED", "SCM_CREDENTIALS",
                "MSG_TRUNC", "MSG_CTRUNC")):
        _hold("LINUX_CREDENTIALS_REQUIRED")


def _kernel_peer(sock, uid):
    if type(uid) is not int or uid < 0:
        _hold("PINNED_ISSUER_UID_REQUIRED")
    try:
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _CRED_SIZE)
    except OSError as exc:
        raise NativePeerHold(
            "HOSPITAL_STAFFING_PEER_HOLD // PEER_CREDENTIALS_UNAVAILABLE"
        ) from exc
    if len(raw) != _CRED_SIZE:
        _hold("TRUNCATED_PEER_CREDENTIALS")
    pid, observed_uid, gid = struct.unpack("3i", raw)
    if pid <= 1 or observed_uid != uid or gid < 0:
        _hold("WRONG_NATIVE_ISSUER_IDENTITY")
    return pid, observed_uid, gid


def _proc_start_ticks(pid):
    """Observe process birth independently of the recyclable numeric PID.

    The retained pidfd and repeated /proc start tick close ordinary PID
    reuse and exit races for this bounded observation. This is not signed
    binary provenance or a durable authentication grant.
    """
    if type(pid) is not int or pid <= 1:
        _hold("INVALID_PEER_PID")
    path = "/proc/" + str(pid) + "/stat"
    fd = None
    try:
        fd = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            _hold("PROC_STAT_NOT_REGULAR")
        raw = os.read(fd, 4096)
    except OSError as exc:
        raise NativePeerHold(
            "HOSPITAL_STAFFING_PEER_HOLD // PROCESS_EVIDENCE_UNAVAILABLE"
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)
    try:
        # /proc/<pid>/stat field 2 may contain spaces and closing brackets.
        # Following its *last* ')' is field 3; starttime field 22 is [19].
        tail = raw.decode("utf-8", "strict").rsplit(")", 1)[1].split()
        ticks = int(tail[19])
    except (IndexError, ValueError, UnicodeError) as exc:
        raise NativePeerHold(
            "HOSPITAL_STAFFING_PEER_HOLD // MALFORMED_PROC_IDENTITY"
        ) from exc
    if ticks <= 0:
        _hold("INVALID_PROC_START_TICKS")
    return ticks


def _not_exited(fd):
    poll = select.poll()
    poll.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
    if poll.poll(0):
        _hold("ISSUER_EXITED_DURING_PACKET")


def _receive_packet(sock, *, expected_uid):
    """Private testable kernel observation; UID never comes from a frame.

    The only public production-shaped wrapper hard pins UID 0. A future
    native process must not expose expected_uid to a client/RPC or use
    this function to authorize a database write.
    """
    _connected_seqpacket(sock)
    peer = _kernel_peer(sock, expected_uid)
    if not hasattr(os, "pidfd_open"):
        _hold("PIDFD_UNAVAILABLE")
    try:
        fd = os.pidfd_open(peer[0], 0)
    except OSError as exc:
        raise NativePeerHold(
            "HOSPITAL_STAFFING_PEER_HOLD // PIDFD_CUSTODY_UNAVAILABLE"
        ) from exc
    try:
        _not_exited(fd)
        initial_start = _proc_start_ticks(peer[0])
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        data, ancillary, flags, _address = sock.recvmsg(
            MAX_PACKET + 1, socket.CMSG_SPACE(_CRED_SIZE),
        )
        if (not data or len(data) > MAX_PACKET
                or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC)):
            _hold("PACKET_TRUNCATED_OR_OUT_OF_BOUNDS")
        evidence = [
            struct.unpack("3i", value)
            for level, kind, value in ancillary
            if (level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS
                and len(value) == _CRED_SIZE)
        ]
        if len(evidence) != 1 or evidence[0] != peer:
            _hold("PACKET_ISSUER_CHANGED")
        if _kernel_peer(sock, expected_uid) != peer:
            _hold("CONNECTED_ISSUER_CHANGED")
        if _proc_start_ticks(peer[0]) != initial_start:
            _hold("PROCESS_BIRTH_CHANGED")
        _not_exited(fd)
        return data, KernelPeerEvidence(
            pid=peer[0], uid=peer[1], gid=peer[2],
            start_ticks=initial_start, packet_length=len(data),
        )
    finally:
        os.close(fd)


def receive_root_issuer_packet(sock):
    """Root-only packet inspection, without granting any native action."""
    return _receive_packet(sock, expected_uid=ISSUER_UID)


def authorize_staffing_from_packet(*_args, **_kwargs):
    """Intentionally unimplemented until signed release and seat consent."""
    _hold("NATIVE_STAFFING_AUTHORITY_NOT_INSTALLED")
