#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export PX_HOSPITAL_DATA_DIR="$TMP/hospital-data"

init_json="$("$ROOT/bin/px" hospital init --json)"
status_json="$("$ROOT/bin/px" hospital status --json)"

python3 - "$init_json" "$status_json" "$PX_HOSPITAL_DATA_DIR" <<'PY'
import json
import pathlib
import sqlite3
import sys

init = json.loads(sys.argv[1])
status = json.loads(sys.argv[2])
data_dir = pathlib.Path(sys.argv[3])

for payload in (init, status):
    assert payload["status"] == "READY", payload
    assert payload["schema_version"] == 1, payload
    assert payload["counts"] == {
        "patients": 0,
        "rooms": 0,
        "sessions": 0,
        "messages": 0,
    }, payload

db = data_dir / "hospital.db"
artifacts = data_dir / "artifacts"

assert db.is_file(), db
assert artifacts.is_dir(), artifacts

conn = sqlite3.connect(db)
try:
    version = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    assert version == ("1",), version

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for table in ("patients", "rooms", "sessions", "messages"):
        assert table in tables, (table, tables)

    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(journal_mode).lower() == "wal", journal_mode
finally:
    conn.close()
PY

printf 'hospital state store: PASS\n'
