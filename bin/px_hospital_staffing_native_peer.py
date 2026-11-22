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
import hashlib
import os
import select
import socket
import stat
import struct


ISSUER_UID = 0
MAX_PACKET = 16384
READY_FRAME = (b'{"schema":"postapollo.hospital.native-staffing-ready.v1",'
               b'"status":"READY"}')
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
    executable_sha256: str
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


def _executable_sha(pid):
    """Hash actual root-owned executable inode rather than cmdline or path.

    The result is evidence only, NOT a signed release approval. A native
    issuer must compare it to an independently trusted release manifest.
    """
    if type(pid) is not int or pid <= 1:
        _hold("INVALID_EXECUTABLE_PID")
    fd = None
    max_size = 64 * 1024 * 1024
    try:
        # /proc/PID/exe is a procfs magic link. O_NOFOLLOW rejects the
        # legitimate endpoint; fstat pins the actual opened ELF inode.
        fd = os.open("/proc/%d/exe" % pid, os.O_RDONLY | os.O_CLOEXEC)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or before.st_nlink < 1
                or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or not 4096 <= before.st_size <= max_size):
            _hold("UNTRUSTED_EXECUTABLE_INODE")
        if os.read(fd, 4) != b"\x7fELF":
            _hold("EXECUTABLE_ELF_REQUIRED")
        digest = hashlib.sha256(b"\x7fELF")
        size = 4
        while size <= max_size:
            chunk = os.read(fd, min(65536, max_size + 1 - size))
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(fd)
        if (size != before.st_size
                or (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns)):
            _hold("EXECUTABLE_CHANGED_DURING_HASH")
        if os.readlink("/proc/%d/exe" % pid).endswith(" (deleted)"):
            _hold("UNLINKED_EXECUTABLE_REFUSED")
        return digest.hexdigest()
    except OSError as exc:
        raise NativePeerHold(
            "HOSPITAL_STAFFING_PEER_HOLD // EXECUTABLE_EVIDENCE_UNAVAILABLE"
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)


def _not_exited(fd):
    poll = select.poll()
    poll.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
    if poll.poll(0):
        _hold("ISSUER_EXITED_DURING_PACKET")


def _arm_peer_socket(sock, *, expected_uid):
    """Establish SO_PASSCRED before the peer can send a valid packet.

    This mirrors the existing Connections issuer's READY handshake. It
    does not issue authorization and does not install a listening socket.
    The public production-shaped wrapper never accepts a client UID.
    Clients MUST wait for READY before sending; queued premature frames
    are refused if no valid SCM_CREDENTIALS accompany them.
    """
    _connected_seqpacket(sock)
    _kernel_peer(sock, expected_uid)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        if sock.send(READY_FRAME) != len(READY_FRAME):
            _hold("INCOMPLETE_READY_HANDSHAKE")
    except OSError as exc:
        raise NativePeerHold(
            "HOSPITAL_STAFFING_PEER_HOLD // READY_HANDSHAKE_UNAVAILABLE"
        ) from exc


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
        initial_executable = _executable_sha(peer[0])
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
        if _executable_sha(peer[0]) != initial_executable:
            _hold("EXECUTABLE_CHANGED_DURING_PACKET")
        _not_exited(fd)
        return data, KernelPeerEvidence(
            pid=peer[0], uid=peer[1], gid=peer[2],
            start_ticks=initial_start, executable_sha256=initial_executable,
            packet_length=len(data),
        )
    finally:
        os.close(fd)


def receive_root_issuer_packet(sock):
    """Root-only READY then packet inspection; no staffing authorization."""
    _arm_peer_socket(sock, expected_uid=ISSUER_UID)
    return _receive_packet(sock, expected_uid=ISSUER_UID)


def authorize_staffing_from_packet(*_args, **_kwargs):
    """Intentionally unimplemented until signed release and seat consent."""
    _hold("NATIVE_STAFFING_AUTHORITY_NOT_INSTALLED")
