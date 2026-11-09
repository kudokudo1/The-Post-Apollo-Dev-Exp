#!/usr/bin/env python3
"""Disposable real Ed25519 signed Bed intent, atomic one-use consumption and refusal."""
import base64
import concurrent.futures
import copy
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
PX = ROOT / "bin" / "px-hospital-store"
sys.path.insert(0, str(ROOT / "bin"))
from hospital_bed_signed_intent import SCHEMA, OPERATION, seal_fixture

REPOSITORY = "kudokudo1/signed-bed-fixture"
BRANCH = "fixture/signed"

def cmd(argv, env=None, success=True):
    p = subprocess.run(list(map(str, argv)), capture_output=True, text=True,
        env=env, timeout=25)
    if success and p.returncode:
        raise AssertionError("Command failed: " + repr(argv)
                             + "\n" + p.stderr + p.stdout)
    if not success and not p.returncode:
        raise AssertionError("Unexpected acceptance: " + repr(argv)
                             + "\n" + p.stdout)
    return p

def git(*args):
    return cmd(["git", *args]).stdout.strip()

def px(env, *args, success=True, refused=None):
    p = cmd([sys.executable, PX, *args, "--json"], env=env, success=success)
    if refused:
        assert refused in p.stderr + p.stdout, (refused, p.stderr, p.stdout)
    return json.loads(p.stdout) if success else p

def make_bed(t, name):
    bed = t / name
    bed.mkdir()
    git("init", "-q", "-b", BRANCH, str(bed))
    git("-C", str(bed), "config", "user.email", "bed-test@example.invalid")
    git("-C", str(bed), "config", "user.name", "Bed Test")
    (bed / "file.txt").write_text("safe fixture\n")
    git("-C", str(bed), "add", "file.txt")
    git("-C", str(bed), "commit", "-qm", "fixture commit")
    git("-C", str(bed), "remote", "add", "origin",
        "git@github.com:kudokudo1/signed-bed-fixture.git")
    return bed

def make_room(env, id):
    return px(env, "room-bind", id, "--repository", REPOSITORY,
        "--patient-id", "fixture-patient")

def room(env, id):
    return px(env, "room", id)

def nonce():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()

def intent_body(env, id, bed, *, use_nonce=None, **updates):
    state = room(env, id)
    body = dict(
        schema=SCHEMA, operation=OPERATION,
        roomId=id, patientId="fixture-patient", repository=REPOSITORY,
        branch=BRANCH, bedPath=str(bed),
        head=git("-C", str(bed), "rev-parse", "HEAD"),
        roomUpdatedAt=state["updatedAt"], operatorId="fixture-operator",
        nonce=nonce() if use_nonce is None else use_nonce,
        issuedAt=int(time.time()), expiresAt=int(time.time())+60,
    )
    body.update(updates)
    return body

def signed_file(t, private, body, name):
    path = t / name
    path.write_bytes(seal_fixture(private, body))
    return path

def claim(env, id, bed, file, *, success=True, refused=None,
          repository=REPOSITORY, branch=BRANCH):
    return px(env, "room-bed-claim-signed-atomic", "--room-id", id,
        "--repository", repository, "--branch", branch, "--bed-path", str(bed),
        "--signed-intent-file", str(file), "--confirm",
        success=success, refused=refused)

def ensure_blank(env, id):
    value=room(env,id)
    assert not value["branch"] and not value["bedPath"]
    assert not value["doctorId"] and not value["providerId"]

def main():
    with tempfile.TemporaryDirectory(prefix="px-signed-bed-intent-") as td:
        t=Path(td)
        env=dict(os.environ,
            PX_HOSPITAL_DB=str(t / "db" / "hospital.sqlite"),
            PX_HOSPITAL_DATA_DIR=str(t / "data"),
            PX_HOSPITAL_BED_CLAIM_TEST_ONLY="1")
        signer = Ed25519PrivateKey.generate()
        other_signer = Ed25519PrivateKey.generate()
        pinned = t / "trusted-test-only-public-key"
        pinned.write_bytes(signer.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw))
        env["PX_HOSPITAL_BED_INTENT_PINNED_KEY_FIXTURE"]=str(pinned)
        bed = make_bed(t, "fixture first")
        make_room(env, "fixture-room-one")
        original = intent_body(env, "fixture-room-one", bed)
        valid = signed_file(t, signer, original, "valid.json")

        no_trust = dict(env)
        no_trust.pop("PX_HOSPITAL_BED_INTENT_PINNED_KEY_FIXTURE")
        claim(no_trust,"fixture-room-one",bed,valid,
              success=False,refused="receipt/key fixture path")
        no_fake_gate = dict(env)
        no_fake_gate.pop("PX_HOSPITAL_BED_CLAIM_TEST_ONLY")
        claim(no_fake_gate,"fixture-room-one",bed,valid,
              success=False,refused="synthetic DB only")
        no_temp_db=dict(env)
        no_temp_db.pop("PX_HOSPITAL_DB")
        claim(no_temp_db,"fixture-room-one",bed,valid,
              success=False,refused="synthetic DB only")
        ensure_blank(env,"fixture-room-one")

        def refused_body(change, needle):
            changed=copy.deepcopy(original)
            changed.update(change)
            try:
                file=signed_file(t, signer, changed, "refusal.json")
            except Exception:
                # Invalid body is intentionally not signable by the helper.
                return
            claim(env,"fixture-room-one",bed,file,
                  success=False,refused=needle)
            ensure_blank(env,"fixture-room-one")

        forged = signed_file(t, other_signer, original, "forged.json")
        claim(env,"fixture-room-one",bed,forged,
              success=False,refused="wrong signer or tampered intent")
        envelope = json.loads(valid.read_text())
        envelope["body"]["operatorId"]="pretend-operator"
        tampered=t/"tampered.json"
        tampered.write_text(json.dumps(envelope))
        claim(env,"fixture-room-one",bed,tampered,
              success=False,refused="wrong signer or tampered intent")
        duplicate=t/"duplicate-key.json"
        raw=valid.read_text()
        duplicate.write_text(raw.replace('"body":{','"body":{"roomId":"forged",',1))
        claim(env,"fixture-room-one",bed,duplicate,
              success=False,refused="duplicate JSON key")
        malformed=t/"garbage.json"
        malformed.write_text("not json")
        claim(env,"fixture-room-one",bed,malformed,
              success=False,refused="invalid JSON envelope")
        symlink=t/"receipt-link"
        symlink.symlink_to(valid)
        claim(env,"fixture-room-one",bed,symlink,
              success=False,refused="receipt/key file unavailable")

        refused_body(dict(roomId="another-room"), "signed roomId no longer matches")
        refused_body(dict(patientId="other-patient"), "signed patientId no longer matches")
        refused_body(dict(repository="another/repository"), "signed repository no longer matches")
        refused_body(dict(branch="fixture/other"), "signed branch no longer matches")
        refused_body(dict(bedPath="/tmp/other"), "signed bedPath no longer matches")
        refused_body(dict(head="a"*40), "signed head no longer matches")
        refused_body(dict(roomUpdatedAt="2000-01-01"), "signed roomUpdatedAt no longer matches")
        refused_body(dict(issuedAt=int(time.time())-200,expiresAt=int(time.time())-100),
                     "receipt expired")
        refused_body(dict(issuedAt=int(time.time())+20,expiresAt=int(time.time())+60),
                     "receipt issued in the future")
        refused_body(dict(issuedAt=int(time.time()),expiresAt=int(time.time())+180),
                     "receipt lifetime must not exceed 90 seconds")
        ensure_blank(env,"fixture-room-one")

        accepted=claim(env,"fixture-room-one",bed,valid)
        assert accepted["recorded"] is True
        assert accepted["signedIntentVerified"] is True
        assert accepted["operatorAuthenticated"] is False
        assert accepted["testOnly"] is True
        assert accepted["providerLaunched"] is False
        assert accepted["sessionCreated"] is False
        assert accepted["room"]["id"] == "fixture-room-one"
        assert accepted["room"]["bedPath"] == str(bed)
        assert accepted["room"]["branch"] == BRANCH
        assert px(env,"sessions","--room-id","fixture-room-one") == []

        # A different signed payload with an already-consumed nonce cannot
        # authorize a second Bed. The consumed ledger stays in the same DB.
        bed_two=make_bed(t,"fixture second")
        make_room(env,"fixture-room-two")
        same_nonce=intent_body(env,"fixture-room-two",bed_two,
                               use_nonce=original["nonce"])
        collision=signed_file(t,signer,same_nonce,"replayed-nonce.json")
        claim(env,"fixture-room-two",bed_two,collision,
              success=False,refused="signed intent already consumed")
        ensure_blank(env,"fixture-room-two")

        fresh=signed_file(t,signer,intent_body(env,"fixture-room-two",bed_two),
                          "fresh-second.json")
        response=claim(env,"fixture-room-two",bed_two,fresh)
        assert response["signedIntentVerified"] is True

        # Incorrect Git evidence after signing must roll back nonce consumption.
        bed_three=make_bed(t,"fixture third")
        make_room(env,"fixture-room-three")
        third_body=intent_body(env,"fixture-room-three",bed_three)
        third=t/"third.json"
        third.write_bytes(seal_fixture(signer,third_body))
        (bed_three/"unexpected.txt").write_text("dirty\n")
        claim(env,"fixture-room-three",bed_three,third,
              success=False,refused="Bed has local changes")
        (bed_three/"unexpected.txt").unlink()
        assert claim(env,"fixture-room-three",bed_three,third)["signedIntentVerified"] is True

        with sqlite3.connect(env["PX_HOSPITAL_DB"]) as db:
            consumed=db.execute(
                "SELECT COUNT(*) FROM hospital_bed_intent_consumptions"
            ).fetchone()[0]
            assert consumed == 3, consumed
            id_row=db.execute(
                "SELECT room_id FROM hospital_bed_intent_consumptions"
                " WHERE nonce=?", (original["nonce"],)
            ).fetchone()
            assert id_row[0] == "fixture-room-one"
        print("PX SIGNED BED INTENT // PASS // genuine Ed25519, exact intent, atomic one-use replay ledger, synthetic-only")

if __name__ == "__main__":
    main()
