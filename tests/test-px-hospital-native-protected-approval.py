#!/usr/bin/env python3
"""Real C5 signer ↔ PX protected Room writer source contract, disposable only.

A fresh SQLite v11 fixture upgrades to v12. Separate request/Ed25519 nonces,
protected PREPARE → signed COMMIT, retained Room, receipts and replay refusal
are exercised using REAL C5-H2 signing code. No installer, key or live DB.
"""
from __future__ import annotations
import base64
from contextlib import closing
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PX=Path(__file__).resolve().parents[1]
APP=PX / "app-source"
C5=APP / "services/connections/hospital"
if not C5.is_dir():
    raise AssertionError("EXACT_C5H2_SOURCE_NOT_CHECKED_OUT")
sys.path.insert(0,str(C5))
sys.path.insert(0,str(PX / "bin"))
import HospitalNativeIssuerCore as signer
import px_hospital_native_approval as native
import px_hospital_room_authority as authority
import px_hospital_room_lifecycle as life

schema=runpy.run_path(str(PX/"bin"/"px-hospital-store"),
                       run_name="px_hospital_source_fixture")
priv=Ed25519PrivateKey.generate()
pub=priv.public_key()
now=int(time.time())
policy={
    "schema":native.POLICY_SCHEMA,
    "policyGeneration":5,
    "expiresAt":now+300,
    "rooms":[{"roomId":"sample-room","patientId":"p",
              "repository":"test/repo","allowTrash":True,
              "allowRestore":True,"legalHold":False}],
}
issuer_policy={"minimumPolicyGeneration":5}

with tempfile.TemporaryDirectory(prefix="hospital-native-protected-") as tmp:
    path=Path(tmp)/"hospital.db"
    def db():
        c=sqlite3.connect(str(path),isolation_level=None,timeout=5)
        c.row_factory=sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c
    with closing(db()) as c:
        for i in range(1,11):
            c.executescript(schema["SCHEMA_V"+str(i)])
        c.execute("ALTER TABLE rooms ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        c.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','11')")
        c.execute("INSERT INTO patients(patient_id,repository) VALUES('p','test/repo')")
        c.execute("INSERT INTO rooms(room_id,patient_id) VALUES('sample-room','p')")
        life.install_schema_v12(c)
    approval=native.ProtectedApproval(db,retention=lambda:policy,now=lambda:int(time.time()))
    def signed_exchange(action):
        nonce=signer.b64(os.urandom(32))
        request={"schema":signer.REQUEST_SCHEMA,"action":action,"roomId":"sample-room"}
        prep={"schema":native.SCHEMA,"kind":"prepare","action":action,
              "roomId":"sample-room","requestNonce":nonce}
        prepared=json.loads(approval.process(native.canonical(prep),peer_uid=0))
        assert prepared["schema"]==signer.PREPARED_SCHEMA
        assert prepared["requestNonce"]==nonce
        assert prepared["retentionApproved"] is True
        assert prepared["legalHold"] is False
        assert prepared["blockers"]==[]
        assert signer.validate_prepared(
            signer.canonical(prepared),request,nonce,
            issuer_policy,int(time.time())
        ) == prepared
        signed=signer.sign_px_grant(
            request=request,prepared=prepared,
            operator_uid=1001,seat_id="synthetic-seat-native",
            host_id="a"*64,private_key=priv,
        )
        # C5 intentionally issues a *new* unique grant nonce, distinct from
        # the prepare request nonce. Both must be protected separately.
        signed_body=json.loads(signed)["body"]
        assert signed_body["nonce"]!=nonce
        commit={
            "schema":native.SCHEMA, "kind":"commit", "action":action,
            "roomId":"sample-room", "requestNonce":nonce,
            "writerInstance":prepared["writerInstance"],
            "signedGrant":signed.decode("ascii"),
        }
        with patch.object(authority,"trusted_public_key",return_value=pub),\
             patch.object(authority,"installed_host_binding",return_value="a"*64):
            receipt=json.loads(approval.process(native.canonical(commit),peer_uid=0))
            assert signer.validate_commit_receipt(
                signer.canonical(receipt),
                request=request,prepared=prepared,
                nonce=nonce,signed_grant=signed,
            )["status"]=="COMMITTED"
            # Same request / grant cannot commit twice.
            try:
                approval.process(native.canonical(commit),peer_uid=0)
                raise AssertionError("PREPARE/COMMIT REPLAY ACCEPTED")
            except native.Refused:
                pass
        return prepared,receipt

    p,r=signed_exchange("TRASH")
    assert r["state"]=="TRASHED" and r["revisionAfter"]==1
    with closing(db()) as conn:
        assert life.review(conn,"sample-room")["state"]=="TRASHED"
        assert conn.execute("SELECT count(*) FROM room_lifecycle_authorizations").fetchone()[0]==1
        assert conn.execute("SELECT count(*) FROM room_lifecycle_receipts").fetchone()[0]==1
    p,r=signed_exchange("RESTORE")
    assert r["state"]=="ACTIVE" and r["revisionAfter"]==2
    with closing(db()) as conn:
        assert life.review(conn,"sample-room")["state"]=="ACTIVE"
        assert conn.execute("SELECT count(*) FROM room_lifecycle_authorizations").fetchone()[0]==2

    # Without root controlled retention file, no PREPARE. A direct desktop
    # caller cannot invoke this protected interface or supply policy.
    invalid={"schema":native.SCHEMA,"kind":"prepare","roomId":"sample-room",
             "action":"TRASH","requestNonce":signer.b64(os.urandom(32))}
    try:
        approval.process(native.canonical(invalid),peer_uid=1001)
        raise AssertionError("NONROOT ISSUER ACCEPTED")
    except native.Refused:
        pass
    try:
        native.ProtectedApproval(db).process(native.canonical(invalid),peer_uid=0)
        raise AssertionError("UNINSTALLED ROOT RETENTION POLICY ACCEPTED")
    except native.Refused:
        pass
    for malformed in (
        b'{"schema":"postapollo.hospital.protected-writer-request.v1","kind":"burn"}',
        native.canonical(dict(invalid, arbitrary=True)),
        native.canonical(dict(invalid,action="BURN")),
        b'{"schema":"x","schema":"x"}',
    ):
        try:
            native.parse(malformed)
            raise AssertionError("MALFORMED FRAME ACCEPTED")
        except native.Refused:
            pass

    # Root policy revocation during Polkit consent denies without spending
    # the signed grant or mutating Room, even with a valid signed frame.
    nonce=signer.b64(os.urandom(32))
    prep=dict(invalid,requestNonce=nonce)
    prepared=json.loads(approval.process(native.canonical(prep),peer_uid=0))
    request={"schema":signer.REQUEST_SCHEMA,"action":"TRASH","roomId":"sample-room"}
    signed=signer.sign_px_grant(
        request=request,prepared=prepared,operator_uid=1001,
        seat_id="synthetic-seat-native",host_id="a"*64,private_key=priv,
    )
    commit=dict(schema=native.SCHEMA,kind="commit",action="TRASH",
                roomId="sample-room",requestNonce=nonce,
                writerInstance=prepared["writerInstance"],
                signedGrant=signed.decode("ascii"))
    policy["policyGeneration"]=6
    with patch.object(authority,"trusted_public_key",return_value=pub),\
         patch.object(authority,"installed_host_binding",return_value="a"*64):
        try:
            approval.process(native.canonical(commit),peer_uid=0)
            raise AssertionError("RETENTION POLICY REVOCATION ACCEPTED")
        except native.Refused:
            pass
    with closing(db()) as conn:
        assert life.review(conn,"sample-room")["state"]=="ACTIVE"
        assert conn.execute("SELECT count(*) FROM room_lifecycle_authorizations").fetchone()[0]==2

print("HOSPITAL SIGNER → PX PROTECTED ROOM → TRASH/RESTORE // PASS // exact signed C5 source, same-DB one-use receipt, replay/revocation fail-closed")
