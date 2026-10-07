#!/usr/bin/env python3
import sys

args = sys.argv[1:]

if "--help" in args:
    print("usage: hermes chat [-q QUERY] [--query-file PATH] [--quiet] [--resume SESSION_ID]")
    print("  -q, --query QUERY")
    print("  --query-file PATH")
    print("  --quiet")
    print("  --resume SESSION_ID")
    raise SystemExit(0)

session_id = "legacy-provider-session"
if "--resume" in args:
    index = args.index("--resume")
    if index + 1 >= len(args):
        print("missing resume id", file=sys.stderr)
        raise SystemExit(2)
    session_id = args[index + 1]

if "--query-file" in args:
    index = args.index("--query-file")
    if index + 1 >= len(args):
        print("missing query file", file=sys.stderr)
        raise SystemExit(2)
    source = args[index + 1]
    if source != "-":
        print("mock only supports stdin query file", file=sys.stderr)
        raise SystemExit(2)
    prompt = sys.stdin.read().strip()
elif "-q" in args:
    index = args.index("-q")
    if index + 1 >= len(args):
        print("missing query", file=sys.stderr)
        raise SystemExit(2)
    prompt = args[index + 1].strip()
else:
    print("missing query", file=sys.stderr)
    raise SystemExit(2)

if not prompt:
    print("empty prompt", file=sys.stderr)
    raise SystemExit(3)

print("LEGACY: " + prompt)
print("session_id: " + session_id, file=sys.stderr)
