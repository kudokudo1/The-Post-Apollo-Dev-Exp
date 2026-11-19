#!/usr/bin/env python3
"""Hospital Trash/Restore / native startup templates and protocol contract.

Static source-only unit contract. Does not generate an installable package,
render user accounts, modify systemd or read the operator's host.
"""
import configparser
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/"packaging/hospital-trash-restore"
APP=ROOT/"app-source"
def content(name):
    p=DIR/name
    assert p.is_file(),name
    return p.read_text()

units=[
    "post-apollo-hospital-writer.service.in",
    "post-apollo-hospital-consent.socket.in",
    "post-apollo-hospital-consent.service.in",
    "post-apollo-hospital-issuer.socket.in",
    "post-apollo-hospital-issuer.service.in",
]
raw={name:content(name) for name in units}
tmpfiles=content("post-apollo-hospital-tmpfiles.conf.in")
conf={}
for name,data in raw.items():
    assert data.startswith("# SOURCE TEMPLATE ONLY")
    assert "[Install]" in data
    assert "WantedBy=" not in data and "RequiredBy=" not in data
    # Unapproved template must NOT be a directly installable release.
    if name.endswith(".service.in") and not name.endswith("issuer.service.in"):
        assert "@PROTECTED_WRITER_USER@" in data
    assert "ExecStartPre=" not in data
    assert "ExecStartPost=" not in data
    assert "ExecStopPost=" not in data
    assert "Environment=PX_HOSPITAL_" not in data
    assert "chown " not in data and "chmod " not in data
    assert "--signed-authorization-file" not in data
    assert "BURN" not in data
    parser=configparser.ConfigParser(strict=False,interpolation=None)
    parser.read_string(data)
    assert parser.has_section("Unit")
    conf[name]=parser

writer=conf[units[0]]["Service"]
consent_sock=conf[units[1]]["Socket"]
consent=conf[units[2]]["Service"]
issuer_sock=conf[units[3]]["Socket"]
issuer=conf[units[4]]["Service"]
assert writer["User"]=="@PROTECTED_WRITER_USER@"
assert consent["User"]==writer["User"]
assert issuer["User"]=="root"
for s in (writer,consent):
    assert s["ProtectSystem"]=="strict"
    assert s["ProtectHome"]=="yes"
    assert s["NoNewPrivileges"]=="yes"
    assert s["UMask"]=="0077"
    assert s["Restart"]=="no"
    assert s["CapabilityBoundingSet"]==""
    assert s["AmbientCapabilities"]==""
    assert s["RestrictAddressFamilies"]=="AF_UNIX"
    assert s["ReadWritePaths"].startswith("@PROTECTED_DB_DIR@")
assert writer["ReadWritePaths"].endswith("@PROTECTED_STREAM_SOCKET_DIR@")
assert issuer["ProtectSystem"]=="strict"
assert issuer["ProtectHome"]=="yes"
assert issuer["Restart"]=="no"
assert issuer["RuntimeMaxSec"]=="90s"

assert consent_sock["ListenSequentialPacket"]=="/run/post-apollo/hospital/px-writer.sock"
assert consent_sock["SocketUser"]=="@PROTECTED_WRITER_USER@"
assert consent_sock["SocketMode"]=="0600"
assert consent_sock["Accept"]=="no"
assert consent_sock["Service"]=="post-apollo-hospital-consent.service"
assert issuer_sock["ListenSequentialPacket"]=="/run/post-apollo/hospital/issuer.sock"
assert issuer_sock["SocketUser"]=="root"
assert issuer_sock["SocketGroup"]=="@OPERATOR_APPROVAL_GROUP@"
assert issuer_sock["SocketMode"]=="0660"
assert issuer_sock["Accept"]=="no"
assert issuer_sock["Service"]=="post-apollo-hospital-issuer.service"
assert "d /run/post-apollo/hospital 0755 root root -" in tmpfiles

assert writer["ExecStart"]==(
    "/usr/bin/python3 /usr/libexec/post-apollo/hospital/px-hospital-room-writerd")
assert consent["ExecStart"]==(
    "/usr/bin/python3 /usr/libexec/post-apollo/hospital/px-hospital-consent-writerd")
assert issuer["ExecStart"]==(
    "/usr/bin/python3 /usr/libexec/post-apollo/hospital/HospitalNativeIssuerService.py")
assert "room-retention-decisions.json" in raw[units[2]]
assert "issuer-runtime-policy.json" in raw[units[4]]
assert "room-lifecycle-issuer.pub" in raw[units[4]]
assert "@PROTECTED_DB_DIR@/hospital.db" in raw[units[0]]

# Confirm filenames, socket modes and policy names against the actual
# merged Connections and PX source, not a guessed app transport.
assert APP.is_dir(),"MERGED_CONNECTIONS_CHECKOUT_REQUIRED"
px_consent=(ROOT/"bin/px_hospital_connections_consent.py").read_text()
px_writer=(ROOT/"bin/px_hospital_room_writer.py").read_text()
px_runner=(ROOT/"bin/px-hospital-consent-writerd").read_text()
app_issuer=(APP/"services/connections/hospital/HospitalNativeIssuerService.py").read_text()
app_core=(APP/"services/connections/hospital/HospitalNativeIssuerCore.py").read_text()
app_client=(APP/"services/hospital/native/hospital_room_request_client.c").read_text()
assert 'CONSENT_SOCKET = Path("/run/post-apollo/hospital/px-writer.sock")' in px_consent
assert 'POLICY_PATH = Path("/etc/post-apollo/hospital/room-retention-decisions.json")' in px_consent
assert 'socket.SOCK_SEQPACKET' in px_runner
assert 'SERVICE_SOCKET = "/run/post-apollo/hospital/issuer.sock"' in app_issuer
assert 'POLICY_PATH = "/etc/post-apollo/hospital/issuer-runtime-policy.json"' in app_core
assert '#define ISSUER_SOCKET "/run/post-apollo/hospital/issuer.sock"' in app_client
assert 'hospital-room-writer-v1.sock' in px_writer
assert "SocketMode=0666" not in "\n".join(raw.values())
# Source package is not a privileged installer and cannot backfill root
# security policy, change database ownership or fence older commands.
for name,data in raw.items():
    assert re.search(r"^# SOURCE TEMPLATE ONLY",data,re.MULTILINE)
    assert "@PROTECTED_DB_DIR@" in raw[units[0]]
assert "ROOT-created" in raw[units[1]]
assert "SOURCE HOLD" in raw[units[0]]
print("HOSPITAL NATIVE STARTUP PACKAGE // PASS // dedicated DB UID, root consent/issuer sockets, no autostart, no migration, CI-only")
