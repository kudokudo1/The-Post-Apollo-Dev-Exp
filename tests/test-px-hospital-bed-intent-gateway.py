#!/usr/bin/env python3
"""Real AF_UNIX -> signed intent -> PX claim. All state is disposable."""
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import subprocess
import sys
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from hospital_bed_intent_gateway import NativeBedIntentGateway, OPERATION, REQUEST_SCHEMA
from hospital_bed_signed_intent import verify_signed_intent

PX = ROOT / "bin" / "px-hospital-store"
REPOSITORY = "kudokudo1/gateway-bed-fixture"
BRANCH = "fixture/safe"


def command(argv, env=None, good=True):
    r = subprocess.run(list(map(str, argv)), capture_output=True, text=True,
                       env=env, timeout=20)
    if good and r.returncode != 0:
        raise AssertionError(f"Command refused {argv}\n{r.stdout}\n{r.stderr}")
    if not good and r.returncode == 0:
        raise AssertionError(f"Unexpected acceptance {argv}\n{r.stdout}")
    return r


def git(*args):
    return command(["git", *args]).stdout.strip()


def px(env, *args, good=True):
    r = command([sys.executable, PX, *args, "--json"], env=env, good=good)
    return json.loads(r.stdout) if good else r


def make_bed(t):
    bed = t / "disposable bed"
    bed.mkdir()
    git("init", "-q", "-b", BRANCH, str(bed))
    git("-C", str(bed), "config", "user.name", "Hospital Fixture")
    git("-C", str(bed), "config", "user.email", "fixture@example.invalid")
    (bed / "fixture.txt").write_text("source fixture\n")
    git("-C", str(bed), "add", "fixture.txt")
    git("-C", str(bed), "commit", "-qm", "synthetic")
    git("-C", str(bed), "remote", "add", "origin",
        "git@github.com:kudokudo1/gateway-bed-fixture.git")
    return bed


def request(bed, **updates):
    data = {
        "schema": REQUEST_SCHEMA, "action": OPERATION,
        "roomId": "gateway-room", "repository": REPOSITORY,
        "branch": BRANCH, "bedPath": str(bed),
        "head": git("-C", str(bed), "rev-parse", "HEAD"),
        "nonce": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
    }
    data.update(updates)
    return data


def send(sock, data):
    frame = (json.dumps(data, separators=(",", ":")).encode() + b"\n"
             if isinstance(data, dict) else data)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(sock))
        client.sendall(frame)
        client.shutdown(socket.SHUT_WR)
        parts = []
        while True:
            packet = client.recv(8192)
            if not packet:
                break
            parts.append(packet)
    return json.loads(b"".join(parts))


def main():
    with tempfile.TemporaryDirectory(prefix="hbg-") as name:
        t = Path(name)
        bed = make_bed(t)
        db = t / "db" / "hospital.sqlite"
        env = dict(os.environ,
                   PX_HOSPITAL_DB=str(db),
                   PX_HOSPITAL_DATA_DIR=str(t / "data"),
                   PX_HOSPITAL_BED_CLAIM_TEST_ONLY="1")
        signer = Ed25519PrivateKey.generate()
        pinned = t / "public-key"
        pinned.write_bytes(signer.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw))
        env["PX_HOSPITAL_BED_INTENT_PINNED_KEY_FIXTURE"] = str(pinned)
        px(env, "room-bind", "gateway-room", "--repository", REPOSITORY,
           "--patient-id", "fixture-patient")
        before = px(env, "room", "gateway-room")
        assert before["branch"] == "" and before["bedPath"] == ""
        runtime = t / "socket"
        runtime.mkdir(mode=0o700)
        gate = {"peer": False, "seat": True, "approve": False, "calls": 0,
                "seen_peer": None, "target": None, "revoke": ""}

        def trust(peer):
            gate["seen_peer"] = peer
            return gate["peer"]

        def seat():
            return gate["seat"]

        def approve(peer, action, target):
            gate["calls"] += 1
            gate["target"] = target
            if not gate["approve"] or action != OPERATION:
                return None
            gate["approve"] = False
            if gate["revoke"] == "seat":
                gate["seat"] = False
            elif gate["revoke"] == "peer":
                gate["peer"] = False
            elif gate["revoke"] == "exception":
                raise RuntimeError("synthetic consent verifier crashed")
            return "fixture-operator"

        try:
            NativeBedIntentGateway(
                runtime_directory=runtime, database=db, signer=signer,
                trusted_peer=None, active_seat=seat, approved_intent=approve)
        except ValueError:
            pass
        else:
            raise AssertionError("Missing trust dependency accepted")

        old = dict(os.environ)
        try:
            os.environ.update(env)
            with NativeBedIntentGateway(
                runtime_directory=runtime, database=db, signer=signer,
                trusted_peer=trust, active_seat=seat, approved_intent=approve
            ) as host:
                sock = host.socket_path
                assert stat.S_ISSOCK(sock.lstat().st_mode)
                assert stat.S_IMODE(sock.lstat().st_mode) == 0o600
                assert send(sock, request(bed)) == {"status": "DENIED"}
                assert gate["calls"] == 0
                gate["peer"] = True
                gate["seat"] = False
                assert send(sock, request(bed)) == {"status": "DENIED"}
                gate["seat"] = True
                for bad in (
                    request(bed, operatorId="forged-operator"),
                    request(bed, approved=True),
                    request(bed, signingKey="untrusted"),
                    request(bed, action="START_PROVIDER"),
                    request(bed, head="a" * 40),
                    request(bed, repository="foreign/project"),
                ):
                    assert send(sock, bad) == {"status": "DENIED"}
                assert send(sock, b'{"schema":"bad","schema":"bad"}\n') == {"status":"DENIED"}
                assert gate["calls"] == 0
                assert gate["seen_peer"].pid == os.getpid()
                assert gate["seen_peer"].uid == os.geteuid()
                assert send(sock, request(bed)) == {"status":"DENIED"}
                assert gate["calls"] == 1
                assert px(env, "room", "gateway-room")["bedPath"] == ""

                # Revoking seat/caller DURING a gesture cannot sign a receipt.
                for lost in ("seat", "peer", "exception"):
                    gate["approve"] = True
                    gate["revoke"] = lost
                    assert send(sock, request(bed)) == {"status":"DENIED"}
                    assert px(env, "room", "gateway-room")["bedPath"] == ""
                    gate["seat"] = True
                    gate["peer"] = True
                assert gate["calls"] == 4
                gate["revoke"] = ""
                gate["approve"] = True
                chosen = request(bed)
                signed = send(sock, chosen)
                assert set(signed) == {"body","signature"}
                assert signed["body"]["operatorId"] == "fixture-operator"
                assert signed["body"]["nonce"] == chosen["nonce"]
                assert signed["body"]["head"] == chosen["head"]
                assert signed["body"]["roomUpdatedAt"] == before["updatedAt"]
                assert gate["target"]["bedPath"] == str(bed)
                assert gate["calls"] == 5
                assert px(env, "room", "gateway-room")["bedPath"] == ""
                assert px(env, "sessions", "--room-id", "gateway-room") == []

                receipt = t / "gateway-receipt.json"
                receipt.write_text(json.dumps(signed))
                assert verify_signed_intent(str(receipt)).body["nonce"] == chosen["nonce"]
                result = px(env, "room-bed-claim-signed-atomic",
                            "--room-id", "gateway-room",
                            "--repository", REPOSITORY, "--branch", BRANCH,
                            "--bed-path", str(bed),
                            "--signed-intent-file", str(receipt), "--confirm")
                assert result["recorded"] is True
                assert result["signedIntentVerified"] is True
                assert result["operatorAuthenticated"] is False
                assert result["testOnly"] is True
                assert result["sessionCreated"] is False
                assert result["providerLaunched"] is False
                room = px(env, "room", "gateway-room")
                assert room["bedPath"] == str(bed) and room["branch"] == BRANCH
                assert px(env, "sessions", "--room-id", "gateway-room") == []

                gate["approve"] = True
                assert send(sock, chosen) == {"status":"DENIED"}
                assert gate["calls"] == 5
                replay = px(env, "room-bed-claim-signed-atomic",
                            "--room-id", "gateway-room",
                            "--repository", REPOSITORY, "--branch", BRANCH,
                            "--bed-path", str(bed),
                            "--signed-intent-file", str(receipt),
                            "--confirm", good=False)
                assert "already staffed or configured" in replay.stderr
            assert not sock.exists()
        finally:
            os.environ.clear()
            os.environ.update(old)

    print("PX NATIVE BED GATEWAY // PASS // real socket, host gates, signed intent, atomic Room claim")


if __name__ == "__main__":
    main()
