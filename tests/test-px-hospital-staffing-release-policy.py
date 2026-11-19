#!/usr/bin/env python3
"""Hospital staffing writer release policy: offline only, fail-closed tests.

Exercises separate root-controlled staffing-verifier policy parsing and
grant revocation. No installed policy, real production key, protected
socket, native operator consent, or user's Hospital DB is accessed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()):
    raise SystemExit("HOSPITAL_STAFFING_RELEASE_POLICY_HOLD // CI_ONLY")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import px_hospital_staffing_release_policy as policy
import px_hospital_staffing_grants as grants
import px_hospital_staffing_transport as transport

assert policy.PATH == Path(
    "/etc/post-apollo/hospital/staffing-verifier-policy.json")
assert "room-lifecycle" not in str(policy.PATH)
assert not hasattr(policy, "enroll_release")
assert not hasattr(policy, "install")
assert not hasattr(policy, "authorize_operator")

def denied(action, marker):
    try:
        action()
    except policy.StaffingPolicyHold as exc:
        assert marker in str(exc), (marker, str(exc))
        return
    raise AssertionError("UNTRUSTED_RELEASE_POLICY_ACCEPTED")

now = int(time.time())
doc = {
    "schema": policy.SCHEMA,
    "operatorUid": 1001,
    "clientExecutableSha256": "a" * 64,
    "issuerReleaseSha256": "b" * 64,
    "hostId": "c" * 64,
    "policyGeneration": 3,
    "allowedOperations": sorted([grants.ATTACH, grants.SUCCEED]),
    "expiresAt": now + 3600,
}
raw=policy._canonical(doc)
assert policy.parse_policy(raw, now=now) == doc
assert policy.read_installed_policy.__code__.co_argcount == 0

with patch.object(policy, "_read_root_bytes", return_value=raw):
    assert policy.read_installed_policy() == doc

body = {
    "operatorUid": 1001,
    "clientExecutableSha256": "a"*64,
    "issuerReleaseSha256": "b"*64,
    "hostId": "c"*64,
    "policyGeneration": 3,
    "operation": grants.ATTACH,
}
assert policy.check_signed_grant(body, doc) is None

for key, changed in (
    ("hostId", "d"*64),
    ("operatorUid", 1002),
    ("clientExecutableSha256", "e"*64),
    ("issuerReleaseSha256", "f"*64),
    ("policyGeneration", 4),
):
    other = dict(doc, **{key: changed})
    denied(lambda other=other:policy.check_signed_grant(body, other),
           "SIGNED_STAFFING_POLICY_REVOKED_OR_CHANGED")

restricted = dict(doc, allowedOperations=[grants.SUCCEED])
assert policy.parse_policy(policy._canonical(restricted), now=now) == restricted
denied(lambda:policy.check_signed_grant(body,restricted),
       "STAFFING_OPERATION_NOT_ENROLLED")
other = dict(body, operation=grants.SUCCEED)
assert policy.check_signed_grant(other, restricted) is None
denied(lambda:policy.check_signed_grant(None, doc),
       "EXACT_SIGNED_STAFFING_BODY_REQUIRED")

for key, value, reason in (
    ("schema", "postapollo.connections.room-trashing.v1",
     "UNRECOGNIZED_POLICY_FIELDS_OR_SCHEMA"),
    ("operatorUid", True, "INVALID_OPERATOR_OR_GENERATION"),
    ("operatorUid", 0, "INVALID_OPERATOR_OR_GENERATION"),
    ("policyGeneration", True, "INVALID_OPERATOR_OR_GENERATION"),
    ("policyGeneration", 0, "INVALID_OPERATOR_OR_GENERATION"),
    ("hostId", "not a host", "INVALID_POLICY_RELEASE_OR_HOST"),
    ("clientExecutableSha256", "not an ELF hash",
     "INVALID_POLICY_RELEASE_OR_HOST"),
    ("issuerReleaseSha256", "not a release",
     "INVALID_POLICY_RELEASE_OR_HOST"),
    ("allowedOperations", ["TRASH"], "UNTRUSTED_STAFFING_OPERATIONS"),
    ("allowedOperations", [grants.ATTACH, grants.ATTACH],
     "UNTRUSTED_STAFFING_OPERATIONS"),
    ("allowedOperations", [], "UNTRUSTED_STAFFING_OPERATIONS"),
    ("allowedOperations", [grants.SUCCEED,grants.ATTACH],
     "UNTRUSTED_STAFFING_OPERATIONS"),
    ("expiresAt", now - 1, "EXPIRED_OR_UNBOUNDED_RELEASE_POLICY"),
    ("expiresAt", now + 32*24*3600, "EXPIRED_OR_UNBOUNDED_RELEASE_POLICY"),
):
    bad=dict(doc, **{key:value})
    denied(lambda bad=bad:policy.parse_policy(
        policy._canonical(bad),now=now), reason)

denied(lambda:policy.parse_policy(raw+b"\n",now=now),
       "NONCANONICAL_POLICY")
denied(lambda:policy.parse_policy(
    b'{"schema":"x","schema":"y"}',now=now),
    "DUPLICATE_POLICY_FIELD")
denied(lambda:policy.parse_policy(
    b'{"expiresAt":NaN}',now=now), "NONFINITE_POLICY_VALUE")
denied(lambda:policy.parse_policy(b"[]" ,now=now),
       "UNRECOGNIZED_POLICY_FIELDS_OR_SCHEMA")
denied(lambda:policy.parse_policy(raw*100,now=now),
       "BOUNDED_POLICY_REQUIRED")
denied(lambda:policy.parse_policy(raw.replace(
    b'"schema":',b'"schema" :'),now=now),
    "NONCANONICAL_POLICY")
denied(lambda:policy.parse_policy(
    policy._canonical(dict(doc,extraPermission=True)),now=now),
    "UNRECOGNIZED_POLICY_FIELDS_OR_SCHEMA")

# Even a syntactically correct file is NOT trusted when it comes from
# a user-writable directory, is a symlink, or is a hard-linked alias.
# No /etc file is read or created; only CI-owned disposable paths.
with tempfile.TemporaryDirectory(
        prefix="hospital-staffing-policy-",dir=os.environ["RUNNER_TEMP"]) as td:
    t=Path(td)
    filepath=t/"staffing-verifier-policy.json"
    filepath.write_bytes(raw)
    with patch.object(policy,"PATH",filepath):
        denied(policy.read_installed_policy,
               "UNTRUSTED_POLICY_PARENT")
    link=t/"alias.json"
    link.symlink_to(filepath)
    with patch.object(policy,"PATH",link):
        denied(policy.read_installed_policy,
               "UNTRUSTED_POLICY_PARENT")

# The existing protected native transport and staffing actions remain held.
try:
    transport.dispatch_native_request(b"{}")
except transport.NativeStaffingTransportHold as exc:
    assert "NATIVE_STAFFING_SERVICE_NOT_INSTALLED" in str(exc)
else:
    raise AssertionError("UNAPPROVED_NATIVE_TRANSPORT_ENABLED")

print("HOSPITAL STAFFING ROOT RELEASE POLICY // PASS // canonical root-policy schema, operation allowlist, release/operator/generation revocation, expired/forged policy refusal, no service install")
