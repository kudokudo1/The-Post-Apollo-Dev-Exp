#!/usr/bin/env python3
"""CI-ONLY proposed staffing result-journal/refusal-fence behavioral model.

NOT a Hospital schema migration, protected writer, runtime module, trusted
receipt, installed service, signing authority, or accepted owner decision.
All rows live in a disposable GitHub runner temp directory; this deliberately
uses a *different* ci_model_ table family from Hospital's candidate v13.

This tests security invariants that any owner-approved journal must meet:
one serialized terminal result per reviewed request/grant, same-transaction
source write and result, a durable REFUSED fence, missing evidence => UNKNOWN,
and no replay or claimed native authority.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys
import tempfile

if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("CI") != "true"
        or not os.environ.get("RUNNER_TEMP")
        or not Path(os.environ["RUNNER_TEMP"]).is_dir()
        or not sys.platform.startswith("linux")):
    raise SystemExit("HOSPITAL_RECOVERY_FENCE_MODEL_HOLD // RUNNER_ONLY")

UNKNOWN = "CI_UNKNOWN_NO_DURABLE_PROOF"
MATCH_COMMIT = "CI_MATCHING_COMMIT_ROW_NOT_AUTHENTICATED"
MATCH_REFUSAL = "CI_MATCHING_REFUSAL_ROW_NOT_AUTHENTICATED"
CI_VERSION = "ci-only-contract-model-v1"
DENIED = {
    "nativeInstalled": False,
    "writerAuthenticated": False,
    "writerReleaseProven": False,
    "operatorConsentVerified": False,
    "nativeCommitVerified": False,
    "nativeRefusalVerified": False,
    "canRetrySameGrant": False,
    "canExecuteStaffing": False,
    "productionAuthority": False,
}


class ModelHold(RuntimeError):
    pass


def hold(reason):
    raise ModelHold("HOSPITAL_RECOVERY_FENCE_MODEL_HOLD // " + reason)


def expect_hold(callback, reason):
    try:
        callback()
    except ModelHold as exc:
        assert reason in str(exc), (reason, str(exc))
        return
    raise AssertionError("MODEL_INVARIANT_WAS_NOT_ENFORCED // " + reason)


def open_test_db(path):
    db = sqlite3.connect(str(path), isolation_level=None, timeout=0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=0")
    db.executescript("""
        CREATE TABLE ci_model_meta (
            version TEXT NOT NULL
        );
        INSERT INTO ci_model_meta(version)
        VALUES ('ci-only-contract-model-v1');
        CREATE TABLE ci_model_outcomes (
            request_nonce TEXT PRIMARY KEY,
            grant_nonce TEXT NOT NULL UNIQUE,
            grant_digest TEXT NOT NULL UNIQUE,
            approval_id TEXT NOT NULL UNIQUE,
            commit_sha256 TEXT NOT NULL UNIQUE,
            writer_instance TEXT NOT NULL,
            room_id TEXT NOT NULL,
            operation TEXT NOT NULL CHECK (
                operation IN ('SESSION_ATTACH', 'DOCTOR_SUCCEED')
            ),
            session_id TEXT NOT NULL,
            review_digest TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN ('COMMITTED', 'REFUSED'))
        );
        CREATE TABLE ci_model_source_sessions (
            session_id TEXT PRIMARY KEY,
            request_nonce TEXT NOT NULL UNIQUE
        );
    """)
    return db


IDENTITY = (
    "request_nonce", "grant_nonce", "grant_digest", "approval_id",
    "commit_sha256", "writer_instance", "room_id", "operation", "session_id",
    "review_digest",
)
COLS = ", ".join(IDENTITY)


def subject(name="one", **changes):
    data = {
        "request_nonce": "request-" + name,
        "grant_nonce": "grant-" + name,
        "grant_digest": ("a" if name == "one" else "b") * 64,
        "approval_id": "approval-" + name,
        "commit_sha256": ("c" if name == "one" else "d") * 64,
        "writer_instance": "writer-" + name,
        "room_id": "room-" + name,
        "operation": "SESSION_ATTACH",
        "session_id": "session-" + name,
        "review_digest": "e" * 64,
    }
    data.update(changes)
    return data


def exact_existing(db, original):
    rows = db.execute(
        """SELECT * FROM ci_model_outcomes
           WHERE request_nonce=? OR grant_nonce=? OR grant_digest=?
              OR approval_id=? OR commit_sha256=? LIMIT 6""",
        tuple(original[k] for k in (
            "request_nonce", "grant_nonce", "grant_digest",
            "approval_id", "commit_sha256")),
    ).fetchall()
    if len(rows) > 1:
        hold("SPLIT_DURABLE_IDENTITY_COLLISION")
    if rows and any(rows[0][k] != original[k] for k in IDENTITY):
        hold("CONTRADICTORY_DURABLE_IDENTITY")
    return rows[0] if rows else None


def journal_result(db, original, terminal, *, abort_after_result=False):
    """Synthetic atomic write to a *CI model*, not an installed action."""
    assert terminal in ("COMMITTED", "REFUSED")
    assert set(original) == set(IDENTITY)
    try:
        db.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        raise ModelHold("HOSPITAL_RECOVERY_FENCE_MODEL_HOLD // WRITER_LOCK_NOT_OWNED") from exc
    try:
        if exact_existing(db, original) is not None:
            hold("ONE_USE_REQUEST_OR_GRANT_FENCED")
        values = tuple(original[k] for k in IDENTITY) + (terminal,)
        db.execute(
            "INSERT INTO ci_model_outcomes (" + COLS + ", outcome) VALUES ("
            + ",".join("?" for _ in values) + ")", values,
        )
        if abort_after_result:
            raise RuntimeError("SYNTHETIC_CRASH_BEFORE_SOURCE_COMMIT")
        if terminal == "COMMITTED":
            db.execute(
                "INSERT INTO ci_model_source_sessions(session_id,request_nonce)"
                " VALUES(?,?)",
                (original["session_id"], original["request_nonce"]),
            )
        db.commit()
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise


def observe(db, original):
    """CI-local evidence only; never promote model rows to production status."""
    if (not isinstance(db, sqlite3.Connection)
            or db.in_transaction or db.row_factory is not sqlite3.Row):
        hold("WRONG_DISPOSABLE_READER")
    try:
        meta = db.execute("SELECT version FROM ci_model_meta").fetchall()
        if len(meta) != 1 or meta[0]["version"] != CI_VERSION:
            hold("UNEXPECTED_SCHEMA_OR_ROLLBACK")
        found = exact_existing(db, original)
        if found is None:
            status = UNKNOWN
        elif found["outcome"] == "COMMITTED":
            source = db.execute(
                "SELECT request_nonce FROM ci_model_source_sessions "
                "WHERE session_id=?", (found["session_id"],),
            ).fetchone()
            if source is None or source["request_nonce"] != original["request_nonce"]:
                hold("DURABLE_COMMIT_SOURCE_CONFLICT")
            status = MATCH_COMMIT
        elif found["outcome"] == "REFUSED":
            source = db.execute(
                "SELECT request_nonce FROM ci_model_source_sessions "
                "WHERE request_nonce=? OR session_id=? LIMIT 2",
                (original["request_nonce"], original["session_id"]),
            ).fetchall()
            if source:
                hold("REFUSAL_AND_COMMIT_SOURCE_CONFLICT")
            status = MATCH_REFUSAL
        else:
            hold("UNKNOWN_DURABLE_TERMINAL_STATE")
    except sqlite3.Error as exc:
        raise ModelHold(
            "HOSPITAL_RECOVERY_FENCE_MODEL_HOLD // PROTECTED_EVIDENCE_UNREADABLE"
        ) from exc
    return {"ciOnlyObservation": status, "neverAutoRetryThisGrant": True, **DENIED}


def count(db, table):
    return db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]


with tempfile.TemporaryDirectory(
        prefix="hospital-recovery-fence-ci-",
        dir=os.environ["RUNNER_TEMP"]) as temp:
    db_path = Path(temp) / "disposable-ci-model.db"
    a = open_test_db(db_path)
    b = sqlite3.connect(str(db_path), isolation_level=None, timeout=0)
    b.row_factory = sqlite3.Row
    b.execute("PRAGMA busy_timeout=0")
    try:
        commit = subject("one")
        refusal = subject("two")
        # An attempted journal result that crashes before the source
        # mutation cannot leave COMMITTED or a spent grant behind.
        try:
            journal_result(a, commit, "COMMITTED", abort_after_result=True)
        except RuntimeError as exc:
            assert "SYNTHETIC_CRASH" in str(exc)
        else:
            raise AssertionError("NO_INJECTED_CRASH")
        assert count(a, "ci_model_outcomes") == 0
        assert count(a, "ci_model_source_sessions") == 0
        assert observe(a, commit)["ciOnlyObservation"] == UNKNOWN

        # The writer holds the only SQLite write slot: concurrent REFUSED
        # cannot race a COMMIT to an opposite terminal state.
        a.execute("BEGIN IMMEDIATE")
        expect_hold(lambda:journal_result(b, commit, "REFUSED"),
                    "WRITER_LOCK_NOT_OWNED")
        a.execute("ROLLBACK")
        journal_result(a, commit, "COMMITTED")
        assert count(a, "ci_model_outcomes") == 1
        assert count(a, "ci_model_source_sessions") == 1
        observed = observe(b, commit)
        assert observed["ciOnlyObservation"] == MATCH_COMMIT
        assert all(observed[k] is False for k in DENIED)
        assert observed["neverAutoRetryThisGrant"] is True
        expect_hold(lambda:journal_result(b, commit, "COMMITTED"),
                    "ONE_USE_REQUEST_OR_GRANT_FENCED")
        expect_hold(lambda:journal_result(b, commit, "REFUSED"),
                    "ONE_USE_REQUEST_OR_GRANT_FENCED")

        # Terminal REFUSED must fence a later COMMIT using same nonce,
        # grant, approval and review (never a new mutation).
        journal_result(b, refusal, "REFUSED")
        assert observe(a, refusal)["ciOnlyObservation"] == MATCH_REFUSAL
        assert count(a, "ci_model_source_sessions") == 1
        expect_hold(lambda:journal_result(a, refusal, "COMMITTED"),
                    "ONE_USE_REQUEST_OR_GRANT_FENCED")
        alternate = subject("three", grant_nonce=refusal["grant_nonce"])
        expect_hold(lambda:journal_result(a, alternate, "COMMITTED"),
                    "SPLIT_DURABLE_IDENTITY_COLLISION")
        assert count(a, "ci_model_source_sessions") == 1

        # Even when the database is corrupted to lose a formerly committed
        # result, an absent record is UNKNOWN, not proof of REFUSED.
        a.execute("DELETE FROM ci_model_outcomes WHERE request_nonce=?",
                  (commit["request_nonce"],))
        assert count(a, "ci_model_source_sessions") == 1
        lost = observe(a, commit)
        assert lost["ciOnlyObservation"] == UNKNOWN
        assert lost["canRetrySameGrant"] is False

        # A tampered REFUSED history whose source mutation is present
        # is a hard HOLD rather than a trustable terminal refusal.
        a.execute(
            "INSERT INTO ci_model_source_sessions(session_id,request_nonce)"
            " VALUES(?,?)",
            (refusal["session_id"], refusal["request_nonce"]),
        )
        expect_hold(lambda:observe(a, refusal),
                    "REFUSAL_AND_COMMIT_SOURCE_CONFLICT")

        # A schema rollback/missing history must not be mistaken for a
        # missing application result or a clean failed request.
        a.execute("UPDATE ci_model_meta SET version='ci-obsolete'")
        expect_hold(lambda:observe(a, commit),
                    "UNEXPECTED_SCHEMA_OR_ROLLBACK")
        a.execute("UPDATE ci_model_meta SET version=?", (CI_VERSION,))

        # A forged response or claimed outside status is not input to
        # any model query: observations are derived from durable rows.
        asserted_reply = {"status":"COMMITTED","authenticated":True}
        assert asserted_reply["status"] == "COMMITTED"
        assert observe(a, commit)["ciOnlyObservation"] == UNKNOWN

        # No API in this file accepts an actual unsigned writer receipt,
        # client-supplied trust key, native COMMIT, or host socket.
        assert not hasattr(sys.modules[__name__], "run_native_recovery")
        assert count(a, "ci_model_outcomes") == 1
    finally:
        b.close()
        a.close()

print(
    "HOSPITAL STAFFING JOURNAL/FENCE CI MODEL // PASS // "
    "serialized terminal refusal vs commit; rollback UNKNOWN; "
    "history deletion UNKNOWN; conflicting source HOLD; native OFF"
)
