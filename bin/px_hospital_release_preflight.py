"""Hospital Trash & Restore // read-only release evidence, NOT an installer.

Source-side preflight for an independently opened SQLite connection. It does
not open a host path, allocate a service identity, modify the DB, create
backups, authorize a Room, start services or claim host quiescence.

The caller/installer must prove process fencing, source provenance, a
recoverable backup, migration, protected ownership, and native consent
separately. A positive report is ONLY a bounded database witness.
"""
from __future__ import annotations

import sqlite3

class ReleaseHold(RuntimeError):
    pass

TABLES = (
    "patients", "rooms", "doctors", "sessions", "messages",
    "session_events", "room_checkpoints", "room_reports",
    "chart_entries", "chart_suggestions", "assignments",
)

def inspect_readonly(conn: sqlite3.Connection):
    if not isinstance(conn, sqlite3.Connection):
        raise ReleaseHold("SQLITE_CONNECTION_REQUIRED")
    if conn.in_transaction:
        raise ReleaseHold("OPEN_TRANSACTION_REFUSED")
    # Do not permit accidentally attaching a writable in-process read
    # witness to a migration plan. No DB path or SQL is accepted as input.
    conn.execute("PRAGMA query_only=ON")
    try:
        version_row=conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        if not version_row:
            raise ReleaseHold("SCHEMA_VERSION_NOT_FOUND")
        version=int(version_row[0])
    except (sqlite3.Error, TypeError, ValueError) as exc:
        raise ReleaseHold("SOURCE_SCHEMA_UNREADABLE") from exc
    if version not in (10, 11, 12):
        raise ReleaseHold("SOURCE_VERSION_NOT_REVIEWED")
    if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ReleaseHold("SOURCE_INTEGRITY_CHECK_FAILED")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ReleaseHold("SOURCE_FOREIGN_KEY_CHECK_FAILED")
    found={
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if not set(TABLES).issubset(found):
        raise ReleaseHold("HOSPITAL_TABLES_MISSING")
    counts={
        name:int(conn.execute("SELECT count(*) FROM " + name).fetchone()[0])
        for name in TABLES
    }
    # This is only a SOURCE-level indicator. No SQLite query can prove
    # all other writers have been stopped or that an external process is
    # not about to attach. A real installer still needs a separate fence.
    sessions=int(conn.execute(
        "SELECT count(*) FROM sessions "
        "WHERE active_pid IS NOT NULL OR ended_at IS NULL "
        "OR trim(ended_at)='' "
    ).fetchone()[0])
    active_assignments=int(conn.execute(
        "SELECT count(*) FROM assignments WHERE status='ACTIVE'"
    ).fetchone()[0])
    pending_charts=int(conn.execute(
        "SELECT count(*) FROM chart_suggestions WHERE status='PENDING'"
    ).fetchone()[0])
    return {
        "schemaVersion":version,
        "recordCounts":counts,
        "openSessions":sessions,
        "activeAssignments":active_assignments,
        "pendingChartSuggestions":pending_charts,
        "databaseIntegrityObserved":True,
        "externalWritersStopped":False,
        "verifiedRecoverableBackup":False,
        "approvedToMigrate":False,
        "sourceQuiescenceObserved":sessions==0 and active_assignments==0,
        "requiresIndependentOperatorAcceptance":True,
    }
