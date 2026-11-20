#!/usr/bin/env python3
"""Hospital + Universal Connections: actual signed PREPARE/COMMIT source test.

The source loaded from app-source is the MERGED C5-H2 issuer core, not a
hand-written mock protocol. All Room changes use a new disposable SQLite
database. Generated fixture private key and injected root retention policy
NEVER appear in the production CLI/daemon.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "bin" / "px-hospital-store"
APP_CORE = ROOT / "app-source" / "services" / "connections" / "hospital"
assert APP_CORE.is_dir(), "PINNED_MERGED_UNIVERSAL_CONNECTIONS_SOURCE_REQUIRED"
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(APP_CORE))

import HospitalNativeIssuerCore as connections
import px_hospital_room_authority as authority
import px_hospital_room_lifecycle as lifecycle
from px_hospital_room_writer import ProtectedRoomWriter
import px_hospital_connections_consent as consent

def expect_hold(action, label):
    try:
        action()
    except (consent.ConsentHold, lifecycle.RoomLifecycleRefused,
            authority.GrantRefused, sqlite3.IntegrityError):
        return
    raise AssertionError("UNAUTHORIZED_HOSPITAL_ACTION_ACCEPTED // " + label)

def px(env, *args):
    p = subprocess.run([sys.executable,str(STORE),*args,"--json"], env=env,
                       text=True,capture_output=True,timeout=25)
    assert p.returncode==0,(args,p.stderr,p.stdout)
    return json.loads(p.stdout)

with tempfile.TemporaryDirectory(prefix="hospital-connections-native-") as tmp:
    base=Path(tmp)
    state=base/"private-hospital"
    state.mkdir(mode=0o700)
    sockdir=base/"socket-dir"
    sockdir.mkdir(mode=0o711)
    env=dict(os.environ,PX_HOSPITAL_DATA_DIR=str(state))
    assert px(env,"status")["schema_version"]==12
    px(env,"patient-put","fixture-p","fixture/repo")
    px(env,"room-put","room-consent-test","--patient-id","fixture-p")
    dbfile=state/"hospital.db"
    os.chmod(dbfile,0o600)

    uid=os.geteuid()
    assert uid != 0, "NONROOT_DISPOSABLE_RUNNER_REQUIRED"
    writer=ProtectedRoomWriter(
        state_directory=state,socket_directory=sockdir,
        client_uid=uid+40,runtime_uid=uid+41,
    )
    with closing(writer._connect()) as db:
        snapshot=lifecycle.review(db,"room-consent-test")
    assert snapshot["canTrash"] and snapshot["revision"]==0

    private=Ed25519PrivateKey.generate()
    public=private.public_key()
    def fixture_verify(encoded):
        # The production default NEVER accepts this verifier injection.
        return authority._verify_bytes(encoded.encode("utf-8"),public)

    policy_state={}
    def configure(action, *, approved=True, held=False, room="room-consent-test"):
        with closing(writer._connect()) as db:
            snap=lifecycle.review(db,room)
        document={
            "schema":consent.POLICY_SCHEMA,
            "policyGeneration":7,
            "expiresAt":int(time.time())+1800,
            "decisions":[{
                "roomId":room, "action":action,
                "expectedRevision":snap["revision"],
                "expectedDigest":snap["digest"],
                "retentionApproved":approved, "legalHold":held,
            }]
        }
        raw=consent.canonical(document)
        policy_state["document"]=document
        policy_state["digest"]=hashlib.sha256(raw).hexdigest()
        return snap

    coordinator=consent.ConsentCoordinator(
        writer, policy_loader=lambda:(
            policy_state["document"],policy_state["digest"]),
        grant_verifier=fixture_verify,
    )
    assert connections.PREPARED_SCHEMA==consent.PREPARED_SCHEMA
    assert connections.RECEIPT_SCHEMA==consent.RECEIPT_SCHEMA
    assert connections.WRITER_SOCKET==str(consent.CONSENT_SOCKET)

    def request(action,kind,nonce,**extra):
        return {
            "schema":consent.REQUEST_SCHEMA, "kind":kind,
            "action":action, "roomId":"room-consent-test",
            "requestNonce":nonce, **extra
        }

    def prepare(action,nonce):
        raw=consent.canonical(request(action,"prepare",nonce))
        return coordinator.dispatch(raw,peer_uid=0)

    def commit(action,nonce,prepared,grant):
        req=request(
            action,"commit",nonce,
            writerInstance=prepared["writerInstance"],
            signedGrant=grant.decode("ascii"),
        )
        return coordinator.dispatch(consent.canonical(req),peer_uid=0)

    def sign(action,prepared):
        req={"action":action,"roomId":"room-consent-test"}
        assert connections.validate_prepared(
            connections.canonical(prepared),req,prepared["requestNonce"],
            {"minimumPolicyGeneration":1},int(time.time())
        )==prepared
        return connections.sign_px_grant(
            request=req,prepared=prepared,operator_uid=1001,
            seat_id="logind-seat0-fixture",
            host_id="a"*64,
            private_key=private,
        )

    def exercise(action):
        configure(action)
        nonce=connections.b64(os.urandom(32))
        prepared=prepare(action,nonce)
        signed=sign(action,prepared)
        result=commit(action,nonce,prepared,signed)
        response=connections.validate_commit_receipt(
            connections.canonical(result),
            request={"action":action,"roomId":"room-consent-test"},
            prepared=prepared,nonce=nonce,signed_grant=signed
        )
        assert response["status"]=="COMMITTED",response
        assert response["roomId"]=="room-consent-test"
        assert response["action"]==action
        assert response["burnAllowed"] is False
        assert response["originalPreserved"] is True
        return nonce,prepared,signed,response

    # The server rejects every unscoped caller. Neither the desktop nor
    # the ordinary PX runtime UID can ask for a legal-hold clearance.
    nonce=connections.b64(os.urandom(32))
    raw=consent.canonical(request("TRASH","prepare",nonce))
    expect_hold(lambda:coordinator.dispatch(raw,peer_uid=uid),"desktop peer")
    expect_hold(lambda:coordinator.dispatch(raw,peer_uid=uid+41),"PX runtime peer")
    expect_hold(lambda:coordinator.dispatch(
        consent.canonical(request("BURN","prepare",nonce)),peer_uid=0),"burn")
    expect_hold(lambda:coordinator.dispatch(
        consent.canonical({**request("TRASH","prepare",nonce),
                           "writerUid":0}),peer_uid=0),"caller-supplied authority")
    expect_hold(lambda:coordinator.dispatch(
        b'{"action":"TRASH","action":"RESTORE"}',peer_uid=0),"duplicate keys")
    expect_hold(lambda:coordinator.dispatch(
        b'{"action":"TRASH","roomId":"notcanonical"}\n',peer_uid=0),
        "noncanonical packet")
    assert coordinator.pending == {}

    # A missing or held root retention policy must refuse BEFORE human
    # consent, independent of the source Room's business eligibility.
    configure("TRASH",approved=False)
    expect_hold(lambda:prepare("TRASH",nonce),"retention not granted")
    configure("TRASH",held=True)
    expect_hold(lambda:prepare("TRASH",nonce),"legal hold")
    assert coordinator.pending == {}

    # Root-controlled policy is rechecked after human consent, INSIDE the
    # exact source database transaction. Rotated policy invalidates grant.
    configure("TRASH")
    prepared=prepare("TRASH",nonce)
    signed=sign("TRASH",prepared)
    policy_state["document"]["decisions"][0]["legalHold"]=True
    policy_state["digest"]=hashlib.sha256(consent.canonical(
        policy_state["document"])).hexdigest()
    expect_hold(lambda:commit("TRASH",nonce,prepared,signed),
                "legal hold added during consent")
    with closing(writer._connect()) as db:
        assert lifecycle.review(db,"room-consent-test")["state"]=="ACTIVE"
        assert db.execute("SELECT count(*) FROM room_lifecycle_authorizations").fetchone()[0]==0
    expect_hold(lambda:commit("TRASH",nonce,prepared,signed),
                "replay after denied policy")

    # Stale Room contents under an otherwise unchanged signed approval must
    # never be silently trashed. PREPARE is single-use and restart-scoped.
    configure("TRASH")
    nonce=connections.b64(os.urandom(32))
    prepared=prepare("TRASH",nonce)
    signed=sign("TRASH",prepared)
    with closing(writer._connect()) as db:
        db.execute("UPDATE rooms SET team='graph-changed' WHERE room_id='room-consent-test'")
    expect_hold(lambda:commit("TRASH",nonce,prepared,signed),
                "graph changed between review and approval")
    with closing(writer._connect()) as db:
        assert lifecycle.review(db,"room-consent-test")["state"]=="ACTIVE"
    expect_hold(lambda:commit("TRASH",nonce,prepared,signed),"replay after source change")

    # Full issuer-created canonical PREPARE / signed COMMIT, actual protected
    # Room write, source Bin and RESTORE across new database connections.
    nonce,prepared,signed,committed=exercise("TRASH")
    with closing(writer._connect()) as db:
        assert lifecycle.review(db,"room-consent-test")["state"]=="TRASHED"
        rows=lifecycle.trashed_rooms(db)
        assert len(rows)==1 and rows[0]["roomId"]=="room-consent-test"
        assert rows[0]["burnAllowed"] is False
        assert db.execute("SELECT count(*) FROM room_lifecycle_receipts").fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM room_lifecycle_authorizations").fetchone()[0]==1
    expect_hold(lambda:commit("TRASH",nonce,prepared,signed),"same signed operation replay")
    restarted=consent.ConsentCoordinator(
        writer,policy_loader=lambda:(
            policy_state["document"],policy_state["digest"]),
        grant_verifier=fixture_verify,
    )
    expect_hold(lambda:restarted.dispatch(
        consent.canonical(request("TRASH","commit",nonce,
            writerInstance=prepared["writerInstance"],
            signedGrant=signed.decode("ascii"))),peer_uid=0),
        "restart cannot replay approval")

    # A separate explicit RESTORE approval and retention decision is required.
    configure("RESTORE")
    nonce2,prepared2,signed2,restored=exercise("RESTORE")
    with closing(writer._connect()) as db:
        assert lifecycle.review(db,"room-consent-test")["state"]=="ACTIVE"
        assert lifecycle.trashed_rooms(db)==[]
        assert db.execute("SELECT count(*) FROM room_lifecycle_receipts").fetchone()[0]==2
        assert db.execute("SELECT count(*) FROM room_lifecycle_authorizations").fetchone()[0]==2
    assert committed["revision"]==1 and restored["revision"]==2

    # No installed root-owned policy/socket exists in this disposable test;
    # daemon startup cannot pass with user-selected config.
    assert str(consent.CONSENT_SOCKET)=="/run/post-apollo/hospital/px-writer.sock"
    assert str(consent.POLICY_PATH)=="/etc/post-apollo/hospital/room-retention-decisions.json"
    left,right=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
    with left,right:
        expect_hold(lambda:consent.kernel_peer(left),"nonroot native caller")

print("HOSPITAL + UNIVERSAL CONNECTIONS // PASS // exact native prepare/commit, signed one-use Trash → Bin → Restore, revocation, replays, no Burn")


# The systemd-created endpoint is ROOT-created, but SocketUser must be the
# non-root protected PX writer UID. The merged Connections signer verifies
# that exact UID. Exercise positive/negative ownership without touching /run.
from types import SimpleNamespace as _FakeStat
from unittest.mock import patch as _patch
import stat as _stat
def _fake_socket_lstat(self):
    if self == consent.CONSENT_SOCKET:
        return _FakeStat(st_mode=_stat.S_IFSOCK | 0o660,
                         st_uid=_socket_owner[0])
    if self in (consent.CONSENT_SOCKET.parent,
                consent.CONSENT_SOCKET.parent.parent):
        return _FakeStat(st_mode=_stat.S_IFDIR | 0o755, st_uid=0)
    raise AssertionError("Unexpected socket path: " + str(self))

if os.geteuid() != 0:
    _socket_owner=[os.geteuid()]
    with _patch.object(Path, "lstat", _fake_socket_lstat):
        assert consent.verify_root_socket() is None
        # This is the ACTUAL merged Universal Connections issuer's
        # socket-ownership verifier, not a hand-authored approximation.
        import HospitalNativeIssuerService as _merged_issuer
        observed = _merged_issuer._socket_root_path(
            str(consent.CONSENT_SOCKET), os.geteuid())
        assert observed.st_uid == os.geteuid()
        _socket_owner[0]=0
        expect_hold(consent.verify_root_socket, "ROOT_OWNED_SOCKET_CONFLICTS_WITH_C5")
        _socket_owner[0]=os.geteuid()+1
        expect_hold(consent.verify_root_socket, "FOREIGN_SOCKET_OWNER_REFUSED")
