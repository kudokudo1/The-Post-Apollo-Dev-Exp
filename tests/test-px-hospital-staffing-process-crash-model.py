#!/usr/bin/env python3
"""Actual Linux process-death test of a PROPOSED Hospital recovery journal.

CI ONLY. This is a synthetic SQLite WAL fixture in RUNNER_TEMP, with no
installed Hospital DB, no PX migration, no real staffing operation, no
native response, no signing or operator consent. It verifies that abruptly
killing a *separate writer process* before vs. after SQLite COMMIT has
different durable results, but neither case permits retransmitting the
original staffing grant or claiming authenticated production outcome.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import sqlite3
import sys
import tempfile

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()
        or not sys.platform.startswith("linux")
        or not hasattr(os, "fork")):
    raise SystemExit("HOSPITAL_PROCESS_CRASH_MODEL_HOLD // RUNNER_ONLY")

PROPOSED = "postapollo.hospital.staffing-process-crash-ci-only.v1"
UNKNOWN = "CI_UNKNOWN_NOT_PROOF_OF_REFUSAL"
MATCH = "CI_DURABLE_ROW_OBSERVED_NOT_WRITER_AUTHENTICATED"
HOLD = "HOSPITAL_PROCESS_CRASH_MODEL_HOLD"
DENIED = {
    "nativeWriterAuthenticated": False,
    "realSourceTransactionVerified": False,
    "operatorConsentVerified": False,
    "installedRecoveryEndpoint": False,
    "canReplayCommit": False,
    "canRetrySameGrant": False,
    "canDeclareProductionCommitted": False,
    "canDeclareProductionRefused": False,
    "productionAuthority": False,
}


def connect(dbpath):
    db = sqlite3.connect(str(dbpath), timeout=0.0, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=0")
    db.execute("PRAGMA synchronous=FULL")
    return db


def initialize(dbpath):
    with connect(dbpath) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE ci_os_meta (version TEXT NOT NULL);
            INSERT INTO ci_os_meta VALUES
            ('postapollo.hospital.staffing-process-crash-ci-only.v1');
            CREATE TABLE ci_os_terminal (
                request_nonce TEXT NOT NULL PRIMARY KEY,
                grant_nonce TEXT NOT NULL UNIQUE,
                grant_digest TEXT NOT NULL UNIQUE,
                approval_id TEXT NOT NULL UNIQUE,
                commit_digest TEXT NOT NULL UNIQUE,
                writer_instance TEXT NOT NULL,
                review_digest TEXT NOT NULL,
                source_session TEXT NOT NULL UNIQUE,
                terminal TEXT NOT NULL CHECK (
                    terminal IN ('COMMITTED', 'REFUSED'))
            );
            CREATE TABLE ci_os_session (
                source_session TEXT NOT NULL PRIMARY KEY,
                request_nonce TEXT NOT NULL UNIQUE
            );
        """)


def identity(tag):
    return {
        "request_nonce": "original-request-" + tag,
        "grant_nonce": "signed-once-" + tag,
        "grant_digest": (("a" if tag == "A" else "b") * 64),
        "approval_id": "original-approval-" + tag,
        "commit_digest": (("c" if tag == "A" else "d") * 64),
        "writer_instance": "original-writer-" + tag,
        "review_digest": "e" * 64,
        "source_session": "session-" + tag,
    }


KEYS = (
    "request_nonce", "grant_nonce", "grant_digest", "approval_id",
    "commit_digest", "writer_instance", "review_digest", "source_session",
)


def writer(dbpath, original, terminal, crash_point):
    """Child has its OWN connection; never inherits a parent DB handle."""
    db = connect(dbpath)
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            """SELECT request_nonce FROM ci_os_terminal
               WHERE request_nonce=? OR grant_nonce=? OR grant_digest=?
                  OR approval_id=? OR commit_digest=? LIMIT 2""",
            tuple(original[k] for k in KEYS[:5]),
        ).fetchall()
        if existing:
            # This is a terminal fence, never a second source mutation.
            db.rollback()
            return 41
        params = tuple(original[k] for k in KEYS) + (terminal,)
        db.execute(
            "INSERT INTO ci_os_terminal (" + ",".join(KEYS)
            + ",terminal) VALUES (" + ",".join("?" for _ in params)
            + ")", params,
        )
        if terminal == "COMMITTED":
            db.execute(
                "INSERT INTO ci_os_session(source_session,request_nonce)"
                " VALUES(?,?)",
                (original["source_session"], original["request_nonce"]),
            )
        if crash_point == "before_sqlite_commit":
            os.kill(os.getpid(), signal.SIGKILL)
        db.commit()
        if crash_point == "after_sqlite_commit_before_reply":
            os.kill(os.getpid(), signal.SIGKILL)
        return 0
    finally:
        db.close()


def child_run(dbpath, original, terminal, crash_point):
    pid = os.fork()
    if pid == 0:
        try:
            code = writer(dbpath, original, terminal, crash_point)
        except BaseException:
            os._exit(90)
        os._exit(code)
    waited, status = os.waitpid(pid, 0)
    assert waited == pid
    if crash_point in ("before_sqlite_commit",
                       "after_sqlite_commit_before_reply"):
        assert os.WIFSIGNALED(status), status
        assert os.WTERMSIG(status) == signal.SIGKILL, status
        return "KERNEL_KILLED_CHILD"
    assert os.WIFEXITED(status)
    return os.WEXITSTATUS(status)


def inspect(dbpath, original):
    with connect(dbpath) as db:
        version = db.execute("SELECT version FROM ci_os_meta").fetchall()
        if len(version) != 1 or version[0][0] != PROPOSED:
            raise RuntimeError(HOLD + " // CANDIDATE_SCHEMA_CHANGED")
        matching = db.execute(
            """SELECT * FROM ci_os_terminal
               WHERE request_nonce=? OR grant_nonce=? OR grant_digest=?
                  OR approval_id=? OR commit_digest=? LIMIT 6""",
            tuple(original[k] for k in KEYS[:5]),
        ).fetchall()
        if len(matching) > 1:
            raise RuntimeError(HOLD + " // IDENTITY_SPLIT")
        if matching and any(matching[0][k] != original[k] for k in KEYS):
            raise RuntimeError(HOLD + " // IDENTITY_CHANGED")
        if not matching:
            # Absence of a local row is NOT a durable terminal refusal.
            return {"ciObservation": UNKNOWN,
                    "missingEvidenceIsNotProofOfRefusal": True, **DENIED}
        row = matching[0]
        source = db.execute(
            "SELECT request_nonce FROM ci_os_session WHERE "
            "request_nonce=? OR source_session=?",
            (original["request_nonce"], original["source_session"]),
        ).fetchall()
        if row["terminal"] == "COMMITTED":
            if len(source) != 1 or source[0][0] != original["request_nonce"]:
                raise RuntimeError(HOLD + " // COMMIT_WITHOUT_SOURCE")
        elif row["terminal"] == "REFUSED":
            if source:
                raise RuntimeError(HOLD + " // REFUSAL_WITH_SOURCE")
        else:
            raise RuntimeError(HOLD + " // UNKNOWN_TERMINAL")
        return {"ciObservation": MATCH,
                "ciRecordedTerminalNotProduction": row["terminal"],
                "missingEvidenceIsNotProofOfRefusal": True, **DENIED}


def counts(dbpath):
    with connect(dbpath) as db:
        return (
            db.execute("SELECT COUNT(*) FROM ci_os_terminal").fetchone()[0],
            db.execute("SELECT COUNT(*) FROM ci_os_session").fetchone()[0],
        )


with tempfile.TemporaryDirectory(
    prefix="hospital-staffing-os-crash-", dir=os.environ["RUNNER_TEMP"]
) as temp:
    path = Path(temp) / "synthetic-journal.db"
    initialize(path)
    a, b = identity("A"), identity("B")

    # The OS terminates the writer with SQLite's transaction still open.
    # WAL rollback must discard BOTH the terminal record and source row.
    assert child_run(path, a, "COMMITTED", "before_sqlite_commit") == "KERNEL_KILLED_CHILD"
    assert counts(path) == (0, 0)
    uncertain = inspect(path, a)
    assert uncertain["ciObservation"] == UNKNOWN
    assert uncertain["canRetrySameGrant"] is False
    assert uncertain["canDeclareProductionRefused"] is False

    # A fresh, *different* signed fixture (never retransmit uncertain A)
    # is allowed to prove the recovered SQLite writer lock is usable.
    assert child_run(path, b, "REFUSED", "after_sqlite_commit_before_reply") == "KERNEL_KILLED_CHILD"
    assert counts(path) == (1, 0)
    refused = inspect(path, b)
    assert refused["ciObservation"] == MATCH
    assert refused["ciRecordedTerminalNotProduction"] == "REFUSED"
    assert all(refused[k] is False for k in DENIED)
    # After process death, the SQLite durable terminal refusal still fences
    # attempted COMMIT of the exact SAME grant.
    assert child_run(path, b, "COMMITTED", "no_crash") == 41
    assert counts(path) == (1, 0)

    # Another independent fixture confirms COMMITTED+source survive actual
    # process death *after* the database commit but *before* any reply.
    c = dict(identity("A"), **{
        "request_nonce": "original-request-C",
        "grant_nonce": "signed-once-C",
        "grant_digest": "f"*64,
        "approval_id": "original-approval-C",
        "commit_digest": "0"*64,
        "writer_instance": "original-writer-C",
        "source_session": "session-C",
    })
    assert child_run(path, c, "COMMITTED", "after_sqlite_commit_before_reply") == "KERNEL_KILLED_CHILD"
    assert counts(path) == (2, 1)
    committed = inspect(path, c)
    assert committed["ciObservation"] == MATCH
    assert committed["ciRecordedTerminalNotProduction"] == "COMMITTED"
    assert committed["canDeclareProductionCommitted"] is False
    assert child_run(path, c, "REFUSED", "no_crash") == 41

    # Even if a history row disappears, a source row alone cannot attest
    # trusted COMMITTED or REFUSED. No safe replay is produced.
    with connect(path) as db:
        db.execute("DELETE FROM ci_os_terminal WHERE request_nonce=?",
                   (c["request_nonce"],))
    lost = inspect(path, c)
    assert lost["ciObservation"] == UNKNOWN
    assert lost["canRetrySameGrant"] is False

    # Tampering after a recorded REFUSED to insert a contradictory Session
    # must produce HOLD, never a trusted refusal.
    with connect(path) as db:
        db.execute(
            "INSERT INTO ci_os_session(source_session,request_nonce)"
            " VALUES(?,?)",
            (b["source_session"], b["request_nonce"]),
        )
    try:
        inspect(path, b)
    except RuntimeError as exc:
        assert "REFUSAL_WITH_SOURCE" in str(exc)
    else:
        raise AssertionError("REFUSAL_SOURCE_CONFLICT_NOT_HELD")
    with connect(path) as db:
        db.execute("UPDATE ci_os_meta SET version='ci-old'")
    try:
        inspect(path, b)
    except RuntimeError as exc:
        assert "CANDIDATE_SCHEMA_CHANGED" in str(exc)
    else:
        raise AssertionError("SCHEMA_DOWNGRADE_NOT_HELD")

print(
    "HOSPITAL STAFFING OS-PROCESS CRASH CI // PASS // "
    "SIGKILL before/after WAL commit; refusal fence survives writer death; "
    "missing history UNKNOWN; signer/receipt/native OFF"
)
