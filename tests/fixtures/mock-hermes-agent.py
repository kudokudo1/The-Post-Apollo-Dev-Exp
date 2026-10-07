#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import time

args = sys.argv[1:]
session_id = os.environ.get(
    "PX_MOCK_PROVIDER_SESSION_ID",
    "mock-provider-session",
)

if "--resume" in args:
    index = args.index("--resume")
    if index + 1 >= len(args):
        print("missing resume id", file=sys.stderr)
        raise SystemExit(2)
    session_id = args[index + 1]

prompt = sys.stdin.read().strip()
if not prompt:
    print("empty prompt", file=sys.stderr)
    raise SystemExit(3)

separator = "\nOPERATOR TURN\n"
if separator in prompt:
    operator_prompt = prompt.rsplit(separator, 1)[1].strip()
else:
    operator_prompt = prompt

if "FORCE_SESSION_MISMATCH" in operator_prompt:
    session_id = "different-provider-session"

if "SLOW_TURN" in operator_prompt:
    time.sleep(30)

if operator_prompt == "AUTHORITY_PROBE":
    def probe(command):
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }

    reply = json.dumps(
        {
            "authority": os.environ.get(
                "POST_APOLLO_HOSPITAL_AUTHORITY",
                "",
            ),
            "permissions": os.environ.get(
                "POST_APOLLO_HOSPITAL_PERMISSIONS",
                "",
            ),
            "denied": os.environ.get(
                "POST_APOLLO_HOSPITAL_DENIED",
                "",
            ),
            "git_status": probe(["git", "status", "--short"]),
            "git_commit": probe(
                ["git", "commit", "--allow-empty", "-m", "forbidden"]
            ),
            "git_push": probe(["git", "push"]),
            "px_integrate": probe(["px", "integrate"]),
        },
        sort_keys=True,
    )
elif operator_prompt.startswith("QUICK // SUGGEST MEMORY"):
    reply = (
        "MEMORY_SUGGESTION\n"
        "SCOPE: ROOM\n"
        "KIND: DECISION\n"
        "TITLE: Keep the Room authority boundary\n"
        "PRIORITY: 82\n"
        "BODY:\n"
        "Doctors may propose durable memory, but only the operator promotes "
        "a suggestion into the Chart."
    )
else:
    reply = "MOCK: " + operator_prompt

events = [
    {
        "type": "system",
        "subtype": "init",
        "session_id": session_id,
        "model": "mock",
        "hospital_context": (
            "HOSPITAL LIVE CONTEXT // GENERATED" in prompt
        ),
        "patient_chart": "PATIENT CHART // ACTIVE" in prompt,
        "room_chart": "ROOM CHART // ACTIVE" in prompt,
        "recent_transcript": "RECENT CANONICAL TRANSCRIPT" in prompt,
        "supplemental_context": "SUPPLEMENTAL TURN CONTEXT" in prompt,
        "report_feedback_context": (
            "REPORT FEEDBACK // ROOM REPORT" in prompt
        ),
    },
    {
        "type": "text",
        "text": reply,
    },
    {
        "type": "result",
        "session_id": session_id,
        "exit_code": 0,
        "text": reply,
        "tokens": {
            "input": len(prompt.split()),
            "output": len(reply.split()),
            "total": len(prompt.split()) + len(reply.split()),
        },
        "duration_ms": 1,
    },
]

for event in events:
    print(json.dumps(event, sort_keys=True), flush=True)
    if "STREAM_TURN" in operator_prompt and event["type"] == "text":
        time.sleep(1.5)
