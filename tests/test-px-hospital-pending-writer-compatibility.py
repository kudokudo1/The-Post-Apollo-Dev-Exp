#!/usr/bin/env python3
"""Hospital writer compatibility witness against separately owned PX drafts.

Read-only, CI-only source inspection. No external branch code is executed,
no database is opened, and this test DOES NOT grant access to the protected
writer. Branches remain unmerged and independently owned.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

if not (os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("CI") == "true"):
    raise SystemExit("HOSPITAL_WRITER_COMPATIBILITY_HOLD // CI_ONLY")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import px_hospital_native_release_audit as audit
import px_hospital_protected_store_bridge as bridge

# Exact source commits, not moving branches. Their own PR owners retain
# responsibility for the semantics and native authorization of each change.
WITNESSES = {
    "session-attach-atomic": (
        "hospital-witness-session",
        "4c3f0c97c4b6342bc7adb70443afecf65666d3cb",
        "session_attach_atomic",
    ),
    "session-succeed-atomic": (
        "hospital-witness-succession",
        "4e0fe43c1324c0011dbbdbcbdfc8bddfb06bcdc1",
        "session_succeed_atomic",
    ),
    "room-bed-claim-atomic": (
        "hospital-witness-bed-initial",
        "81f626d9efe56089e2fd4117406729c82db58f3e",
        "claim_first_bed",
    ),
    "room-bed-claim-signed-atomic": (
        "hospital-witness-bed-signed",
        "a76a7b079bba6cf5733b5be4860d2188028d63e4",
        "claim_first_bed_signed",
    ),
}
GATEWAY = (
    "hospital-witness-bed-gateway",
    "0dd14de064f2f50adb60b4217da6f2a937f4001c",
)
assert frozenset(WITNESSES) == audit.UNRECONCILED_NATIVE_COMMANDS
assert len(bridge.READ_COMMANDS) == 19
assert len(bridge.WRITE_COMMANDS) == 21
assert bridge.route_coverage(), "Existing PX protected routes have drifted"
assert not (frozenset(WITNESSES)
            & (bridge.READ_COMMANDS | bridge.WRITE_COMMANDS))
assert bridge.READ_COMMANDS.isdisjoint(bridge.WRITE_COMMANDS)
assert bridge.EXCLUDED_COMMANDS.isdisjoint(
    bridge.READ_COMMANDS | bridge.WRITE_COMMANDS
)

def pinned_checkout(directory: str, expected_sha: str) -> Path:
    path = ROOT / directory
    assert path.is_dir(), "PINNED_EXTERNAL_SOURCE_MISSING"
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    assert result.stdout.strip() == expected_sha, (
        "EXTERNAL_OWNER_SOURCE_REVISION_CHANGED"
    )
    return path

def read_tree(path: Path) -> tuple[str, ast.Module]:
    contents = path.read_text(encoding="utf-8")
    return contents, ast.parse(contents, filename=str(path))

def parser_choices(tree: ast.Module) -> set[str]:
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_parser"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and type(node.args[0].value) is str
    }

def function_names(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

for command, (directory, sha, function) in WITNESSES.items():
    checkout = pinned_checkout(directory, sha)
    source, tree = read_tree(checkout / "bin" / "px-hospital-store")
    assert command in parser_choices(tree), "OWNER_COMMAND_NOT_PRESENT"
    assert command in source, "OWNER_DISPATCH_NOT_PRESENT"
    assert "--confirm" in source, "OWNER_CONFIRMATION_SURFACE_MISSING"
    if command.startswith("room-bed-"):
        helper, helper_ast = read_tree(
            checkout / "bin" / "hospital_bed_claim.py"
        )
        assert function in function_names(helper_ast), "BED_FUNCTION_MISSING"
        assert "BEGIN IMMEDIATE" in helper, "BED_TRANSACTION_WITNESS_MISSING"
    else:
        assert function in function_names(tree), "SESSION_FUNCTION_MISSING"
        assert "BEGIN IMMEDIATE" in source, "SESSION_TRANSACTION_WITNESS_MISSING"

    # Even well-formed future command names are NOT allowed into the
    # existing generic protected runtime by merely being registered.
    try:
        bridge.parse_argv([command])
    except bridge.StoreCommandHold as exc:
        assert str(exc) == "COMMAND_NOT_EXPOSED", str(exc)
    else:
        raise AssertionError("UNREVIEWED_WRITER_COMMAND_WAS_GRANTED")

# The signed Bed path accepts a CLI file argument in its owner draft.
# Protected store-command deliberately refuses all file-based grants;
# Bed needs a separate reviewed native authority and transport contract.
bed_checkout = pinned_checkout(*WITNESSES["room-bed-claim-signed-atomic"][:2])
bed_source, _ = read_tree(bed_checkout / "bin" / "px-hospital-store")
assert "--signed-intent-file" in bed_source
assert "room-bed-claim-signed-atomic" not in bridge.WRITE_COMMANDS

gateway_checkout = pinned_checkout(*GATEWAY)
_, gateway_ast = read_tree(
    gateway_checkout / "bin" / "hospital_bed_intent_gateway.py"
)
assert "NativeBedIntentGateway" in {
    item.name for item in gateway_ast.body if isinstance(item, ast.ClassDef)
}
assert "room-bed-claim-signed-atomic" not in bridge.WRITE_COMMANDS

# Neither a source inventory nor a clean /proc scan is installation proof.
fake_config = {
    "schema": audit.SCHEMA, "writerUid": 42010,
    "clientUid": 42011, "runtimeUid": 42012,
    "stateDirectory": "/fixture/hospital",
    "socketDirectory": "/fixture/socket",
}
report = audit.assess_writers(fake_config, [], 0, 1)
assert report["allWriterCompatibilityVerified"] is False
assert report["releaseApproved"] is False
assert set(report["unreconciledHospitalCommands"]) == set(WITNESSES)

print("HOSPITAL WRITER COMPATIBILITY // PASS // exact five owner heads inspected, four new commands denied by protected bridge; RELEASE HOLD remains; NO INSTALL")
