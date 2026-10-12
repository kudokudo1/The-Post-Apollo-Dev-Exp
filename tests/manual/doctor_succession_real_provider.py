#!/usr/bin/env python3
"""Explicitly opt-in real-provider Doctor A -> B continuity acceptance.

Runs ONLY on operator request. Produces private, local evidence, with an
entirely separate disposable Hospital DB and Git Bed. This is NOT a
filesystem sandbox: real providers can still access the launching account.
Never run this in automated CI or with a mock provider.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PX = ROOT / "bin/px"
REPO = "kudokudo1/post-apollo-succession-fixture"
BRANCH = "fixture/doctor-succession"
ROOM = "S3-DOCTOR-ROOM"
FOREIGN = "S3-FOREIGN-ROOM"
A_SESSION = "s3-doctor-A"
B_SESSION = "s3-doctor-B"
MARKER = "pearl cactus harmonic anchor"
DECISION = (
    "OPERATOR-APPROVED TEST FIXTURE: Preserve indigo parity before "
    "checksum C-47; do not EDIT, COMMIT, PUSH, or INTEGRATE."
)
FOREIGN_MARKER = "FOREIGN ROOM ONLY -- NOBODY ELSE MAY RECEIVE THIS"
PROMPT_A = (
    "You are Doctor A in a disposable Hospital continuity exercise. "
    "Do not run tools, edit files, or access the filesystem. Write a short "
    "plain-text handoff (under 1000 characters) for a replacement Doctor. "
    "Include the exact historical phrase 'pearl cactus harmonic anchor', "
    "the unfinished task 'verify checksum C-47', and explain that the "
    "previous reasoning must be checked against fresh Git evidence. "
    "No Markdown tables. This is fictitious test data."
)
PROMPT_B = (
    "You are a NEW Doctor B continuing a fictitious Hospital Room. "
    "Use ONLY the context delivered in this turn. Do not run tools, read "
    "files, or change Git. Without guessing, explain: (1) the Room and "
    "Git branch, (2) Doctor A's older handoff and its unusual exact marker, "
    "(3) the active operator-approved decision, (4) unfinished steps, "
    "(5) allowed and denied permissions, (6) the next safe action. "
    "Cite the numerical Room Report ID and Room Chart ID supporting your "
    "claims. State uncertainty where the evidence is insufficient."
)
WRAPPER = r'''#!/usr/bin/env python3
"""Capture exact stdin then exec the unmodified, selected real provider."""
import os
import sys
real = os.environ["PX_S3_REAL_PROVIDER_BIN"]
target = os.environ.get("PX_S3_CAPTURE_TARGET", "")
args = sys.argv[1:]
if target and "--help" not in args:
    # Only the provider turn itself receives this path. Probes/help bypass.
    with open(target, "x+b") as captured:
        os.fchmod(captured.fileno(), 0o600)
        while True:
            chunk = os.read(0, 65536)
            if not chunk:
                break
            captured.write(chunk)
        captured.flush()
        os.fsync(captured.fileno())
        os.lseek(captured.fileno(), 0, os.SEEK_SET)
        os.dup2(captured.fileno(), 0)
        os.execv(real, [real, *args])
os.execv(real, [real, *args])
'''


def write_private(path, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        if isinstance(data, (dict, list)):
            json.dump(data, out, indent=2, sort_keys=True)
            out.write("\n")
        else:
            out.write(str(data))


def run(argv, *, env=None, stdin=None, timeout=50):
    proc = subprocess.run(
        argv, text=True, input=stdin, capture_output=True,
        env=env, timeout=timeout, check=False,
    )
    if proc.returncode:
        tail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            f"command refused (exit {proc.returncode}): "
            + " ".join(argv[:5]) + "\n" + tail[-1500:]
        )
    return proc.stdout


def px(env, *args, input_text=None, timeout=50):
    raw = run([str(PX), *args, "--json"], env=env,
              stdin=input_text, timeout=timeout)
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise RuntimeError("PX output is not valid JSON") from exc


def git(path, *args):
    return run(["git", "-C", str(path), *args], timeout=15).strip()


def valid_provider(provider_id):
    if provider_id not in ("codex", "hermes"):
        raise RuntimeError("only configured real providers codex or hermes are allowed")
    src = Path(
        os.environ.get("PX_AGENT_PROVIDER_CONFIG", "")
        or ROOT / "config/agent-providers.json"
    ).expanduser()
    registry = json.loads(src.read_text(encoding="utf-8"))
    record = (registry.get("providers") or {}).get(provider_id)
    if not isinstance(record, dict):
        raise RuntimeError("selected real provider is not configured")
    command = str(record.get("command") or "")
    executable = (
        str(Path(command).expanduser()) if "/" in command else shutil.which(command)
    )
    if not executable or not os.access(executable, os.X_OK):
        raise RuntimeError(f"real provider executable unavailable: {command}")
    if "mock" in command.lower() or "fixture" in command.lower():
        raise RuntimeError("mock/fixture provider is not valid for real-provider acceptance")
    if provider_id == "hermes":
        help_result = subprocess.run(
            [executable, "chat", "--help"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        help_text = (help_result.stdout + help_result.stderr).lower()
        if "--query-file" not in help_text:
            raise RuntimeError(
                "Hermes CLI lacks --query-file stdin support; exact provider "
                "input capture is unavailable. Do not claim acceptance."
            )
    return registry, record, str(Path(executable).resolve())


def bootstrap(workspace, provider):
    env = os.environ.copy()
    env.update({
        "PX_HOSPITAL_DATA_DIR": str(workspace / "hospital-state"),
        "PX_AGENT_LOCK_DIR": str(workspace / "session-locks"),
        "PX_AGENT_AUTHORITY_DIR": str(workspace / "authority-shims"),
    })
    reg, selected, executable = valid_provider(provider)
    wrapper = workspace / "capture-real-provider.py"
    write_private(wrapper, WRAPPER)
    wrapper.chmod(0o700)
    reg["providers"] = {provider: dict(selected)}
    reg["providers"][provider]["command"] = str(wrapper)
    if provider == "codex":
        # Bound the demonstration's model-generated tool actions even if
        # the user's global Codex config normally allows workspace writes.
        # No grant to edit, commit, push, or elevate approval privileges.
        reg["providers"][provider]["startArgs"] = [
            "exec", "--sandbox", "read-only",
            "-c", "approval_policy=never", "--json", "-"
        ]
        reg["providers"][provider]["resumeArgs"] = [
            "exec", "resume", "{provider_session_id}",
            "--sandbox", "read-only", "-c", "approval_policy=never",
            "--json", "-"
        ]
    reg_file = workspace / "provider-registry.json"
    write_private(reg_file, reg)
    env["PX_AGENT_PROVIDER_CONFIG"] = str(reg_file)
    env["PX_S3_REAL_PROVIDER_BIN"] = executable

    bed = workspace / "bed"
    bed.mkdir(mode=0o700)
    git(bed, "init", "-q")
    git(bed, "config", "user.name", "PXD Succession Fixture")
    git(bed, "config", "user.email", "succession@example.invalid")
    write_private(
        bed / "fixture.txt",
        "Disposable fictional Doctor succession Bed. No user work here.\n"
    )
    git(bed, "add", "fixture.txt")
    git(bed, "commit", "-qm", "disposable fixture")
    git(bed, "checkout", "-qb", BRANCH)
    git(bed, "remote", "add", "origin", f"https://github.com/{REPO}.git")

    px(env, "hospital", "init")
    for room, doctor in ((ROOM, "doctor-A"), (FOREIGN, "foreign-doctor")):
        px(
            env, "hospital", "room-bind", room,
            "--repository", REPO, "--patient-id", "synthetic-patient",
            "--team", room, "--branch", BRANCH,
            "--bed-path", str(bed), "--doctor-id", doctor,
        )
    assignment = px(
        env, "hospital", "assignment-create",
        "--room-id", ROOM, "--title", "Disposable succession analysis",
        "--goal", "Complete fixture analysis stage gamma.",
        "--constraints", "Only READ and TEST; report uncertainty",
        "--definition-done", "Review checksum C-47 with evidence",
        "--permissions-json", '["READ","TEST"]',
        "--checklist", "- [ ] verify checksum C-47\n- [ ] report provenance",
        "--open-questions", "Inspect historic handoff before action.",
        "--phase", "IMPLEMENTATION",
    )
    px(env, "hospital", "assignment-activate", str(assignment["id"]))
    return env, bed, assignment


def real_turn(env, workspace, session_id, prompt, name, timeout):
    capture = workspace / f"provider-input-{name}.txt"
    extra = dict(env, PX_S3_CAPTURE_TARGET=str(capture))
    result = px(
        extra, "agent", "turn", session_id, "--prompt-stdin",
        "--timeout", str(timeout),
        input_text=prompt, timeout=timeout+60,
    )
    if not capture.is_file() or capture.stat().st_size == 0:
        raise RuntimeError("provider prompt capture missing; cannot claim delivery")
    if not str(result.get("assistant") or "").strip():
        raise RuntimeError("provider returned no usable assistant answer")
    if not str(result.get("providerSessionId") or "").strip():
        raise RuntimeError("provider did not expose a native session ID")
    write_private(workspace / f"turn-{name}.json", result)
    return result


def create_report(env, kind, title, body, *, room=ROOM, session=A_SESSION):
    parts = [
        "hospital", "room-report-append", "--room-id", room,
        "--report-kind", kind, "--title", title, "--body-stdin",
    ]
    if session:
        parts += ["--session-id", session]
    return px(env, *parts, input_text=body)


def create_chart(env, title, body, priority):
    return px(
        env, "hospital", "chart-entry-add", "--scope", "ROOM",
        "--room-id", ROOM, "--entry-kind", "DECISION",
        "--title", title, "--priority", str(priority),
        "--author-role", "operator", "--author-id", "fixture-operator",
        "--body-stdin", input_text=body,
    )


def execute(workspace, provider, timeout):
    os.umask(0o077)
    if workspace.exists():
        raise RuntimeError("workspace already exists; refusing reuse or overwrite")
    if not workspace.parent.is_dir():
        raise RuntimeError("workspace parent does not exist")
    workspace.mkdir(mode=0o700)
    env, bed, assignment = bootstrap(workspace, provider)
    meta = {
        "status": "RUNNING", "checkoutSha": git(ROOT,"rev-parse","HEAD"),
        "fixtureRepo": REPO, "fixtureBranch": BRANCH,
        "bed": str(bed), "provider": provider,
        "roomA": ROOM, "roomX": FOREIGN,
        "assignmentId": assignment["id"],
        "doctorASession": A_SESSION, "doctorBSession": B_SESSION,
        "operatorApproved": "SYNTHETIC FIXTURE ONLY",
        "warning": "Real provider access is not filesystem-sandboxed.",
    }
    write_private(workspace / "identity.json", meta)
    px(
        env, "agent", "session-create",
        "--room-id", ROOM, "--doctor-id", "doctor-A",
        "--provider-id", provider, "--working-directory", str(bed),
        "--session-id", A_SESSION,
    )
    a = real_turn(env, workspace, A_SESSION, PROMPT_A, "A", timeout)
    a_text = str(a["assistant"]).strip()
    if MARKER not in a_text.lower():
        raise RuntimeError(
            "Doctor A did not include the required historical marker. "
            "Evidence retained; do not falsely grade succession."
        )
    if len(a_text) > 1700:
        raise RuntimeError(
            "Doctor A handoff exceeds mandatory record budget. "
            "Evidence retained; manual correction needed."
        )
    a_record = create_report(
        env, "Handoff", "Doctor A historical handoff", a_text
    )
    if a_record["kind"] != "HANDOFF":
        raise RuntimeError("S2-01 normalized HANDOFF was not persisted")
    decision = create_chart(
        env, "Synthetic operator-approved fixture decision", DECISION, 1
    )
    for i in range(11):
        create_chart(
            env, f"Higher priority fixture note {i}",
            f"Unrelated operator fixture reminder {i}", 95
        )
    for i in range(40):
        create_report(
            env, "DOCTOR_NOTE", f"Fixture stage gamma status {i}",
            f"Fixture analysis stage gamma filler {i}"
        )
    for i in range(8):
        px(
            env, "hospital", "message-append", "--room-id", ROOM,
            "--session-id", A_SESSION, "--author-role", "nurse",
            "--author-id", "fixture-filler",
            "--direction", "incoming", "--message-type", "fixture",
            "--body", f"Disposable non-handoff marker {i}",
        )
    create_report(
        env, "handoff", "Foreign Room only", FOREIGN_MARKER,
        room=FOREIGN, session=""
    )
    px(
        env, "agent", "session-create",
        "--room-id", ROOM, "--doctor-id", "doctor-B",
        "--provider-id", provider, "--working-directory", str(bed),
        "--session-id", B_SESSION,
    )
    before = px(env, "hospital", "session", B_SESSION)
    if before.get("providerSessionId"):
        raise RuntimeError("Doctor B inherited a native provider session; refuse")
    context = px(env, "agent", "context", B_SESSION)
    write_private(workspace / "doctor-B-context-before-turn.json", context)
    report_ids = [str(r["id"]) for r in context["requiredHandoffs"]]
    chart_ids = [str(r["id"]) for r in context["approvedRoomChart"]]
    if str(a_record["id"]) not in report_ids or str(decision["id"]) not in chart_ids:
        raise RuntimeError("Doctor B context is missing required source IDs")
    if FOREIGN_MARKER in context["renderedText"]:
        raise RuntimeError("Doctor B context contains foreign Room material")

    b = real_turn(env, workspace, B_SESSION, PROMPT_B, "B", timeout)
    after = px(env, "hospital", "session", B_SESSION)
    b_input = (workspace / "provider-input-B.txt").read_text()
    for value in (MARKER, DECISION, "ROOM_REPORT #" + str(a_record["id"]),
                  "ROOM_CHART #" + str(decision["id"])):
        if value not in b_input:
            raise RuntimeError(
                "Captured provider stdin lacks required context evidence: " + value
            )
    if FOREIGN_MARKER in b_input:
        raise RuntimeError("Captured provider stdin leaked other Room evidence")
    b_text = str(b["assistant"])
    checks = {
        "freshProviderSession": (
            str(a["providerSessionId"]) != str(b["providerSessionId"])
            and str(after.get("providerSessionId") or "")
                == str(b["providerSessionId"])
        ),
        "recoveredOlderHandoffMarker": MARKER in b_text.lower(),
        "recoveredFixtureOperatorDecision": "indigo" in b_text.lower(),
        "recoveredUnfinishedTask": "C-47" in b_text,
        "citedReport": str(a_record["id"]) in b_text,
        "citedChart": str(decision["id"]) in b_text,
        "roomIsolated": FOREIGN_MARKER not in b_input,
        "doctorBNativeSessionWasInitiallyEmpty": True,
        "exactProviderStdinCaptured": True,
    }
    metadata = dict(meta)
    metadata.update({
        "status": "PROVIDER_RESPONSES_CAPTURED",
        "handoffReportId": a_record["id"],
        "approvedChartId": decision["id"],
        "doctorAProviderSessionId": a["providerSessionId"],
        "doctorBProviderSessionId": b["providerSessionId"],
        "contextFingerprint": hashlib.sha256(
            b_input.encode("utf-8")
        ).hexdigest(),
        "checks": checks,
        "automatedPass": all(checks.values()),
        "humanReviewRequired": True,
    })
    write_private(workspace / "result-summary.json", metadata)
    print(json.dumps({
        "evidenceDir": str(workspace),
        "automatedPass": all(checks.values()),
        "humanReviewRequired": True,
        "testChecks": checks,
    }, indent=2))
    if not all(checks.values()):
        raise RuntimeError(
            "Automated checks flagged issues; retain evidence for Nurse 2 review"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Run a private, opt-in REAL AI Doctor A -> B succession test"
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--provider", default="hermes", choices=("hermes", "codex"))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack-provider-access", action="store_true")
    args = parser.parse_args()
    workspace = Path(args.workspace).expanduser()
    if not workspace.is_absolute():
        parser.error("--workspace must be an absolute path")
    if args.timeout < 60 or args.timeout > 1800:
        parser.error("--timeout must be 60 to 1800 seconds")
    if not args.execute:
        print(json.dumps({
            "mode": "DRY_RUN_NO_PROVIDER",
            "workspace": str(workspace),
            "provider": args.provider,
            "realCallsOnExecute": 2,
            "writesOnDryRun": 0,
            "requiredOptIn": "--execute --ack-provider-access",
            "warnings": [
                "provider billing/latency depends on your account",
                "real provider is NOT confined by a filesystem sandbox",
                "the local evidence packet contains full provider prompts/answers",
                "this is fictitious data, not live Hospital production data",
            ],
        }, indent=2))
        return 0
    if not args.ack_provider_access:
        parser.error(
            "real provider operation requires --ack-provider-access; "
            "this is not an OS sandbox and may use paid provider resources"
        )
    try:
        execute(workspace, args.provider, args.timeout)
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("S3 PROVIDER ACCEPTANCE NOT ESTABLISHED // " + str(exc),
              file=sys.stderr)
        if workspace.is_dir():
            print("Partial private evidence: " + str(workspace), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
