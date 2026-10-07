#!/usr/bin/env python3
import json
import os
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

if "FORCE_SESSION_MISMATCH" in prompt:
    session_id = "different-provider-session"

if "SLOW_TURN" in prompt:
    time.sleep(30)

separator = "\nOPERATOR TURN\n"
if separator in prompt:
    operator_prompt = prompt.rsplit(separator, 1)[1].strip()
else:
    operator_prompt = prompt

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
    print(json.dumps(event, sort_keys=True))
