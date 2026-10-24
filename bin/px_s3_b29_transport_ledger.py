#!/usr/bin/env python3
"""B29 detached, synthetic-only transport bookkeeping proof.

Caller supplies a DISPOSABLE SQLite connection. This module opens no path,
loads no credential, imports no SDK, sends no HTTP request, runs no tool,
and never accesses real Hospital storage. Mock remote statuses are never
proof of delivery, cancellation or spend. Do not use in production.
"""
import json
import re
import sqlite3

PROFILE = "B29_INERT_TRANSPORT_FIXTURE"
MODES = frozenset(("FOREGROUND_STREAM", "BACKGROUND_POLL"))
STATES_HOLD = frozenset((
    "RESERVED", "SUBMISSION_UNCONFIRMED", "REMOTE_OUTCOME_UNKNOWN",
    "CANCEL_PENDING", "MOCK_CANCELLED_UNVERIFIED", "REVOKED_REMOTE_UNKNOWN",
))
BINDING_KEYS = frozenset(("room", "patient", "assignment", "bed", "turnId", "generation"))
ID = re.compile(r"[A-Za-z0-9_.-]{1,96}\Z")
TABLES = frozenset((
    "b29_fixture_marker", "b29_fixture_budgets", "b29_fixture_attempts",
))
DDL = """
CREATE TABLE b29_fixture_marker (
    identity TEXT PRIMARY KEY CHECK(identity='B29_OFFLINE_ONLY')
);
CREATE TABLE b29_fixture_budgets (
    scope TEXT PRIMARY KEY,
    limit_units INTEGER NOT NULL CHECK(limit_units>0),
    reserved_units INTEGER NOT NULL DEFAULT 0 CHECK(reserved_units>=0),
    used_units INTEGER NOT NULL DEFAULT 0 CHECK(used_units>=0),
    CHECK(used_units+reserved_units<=limit_units)
);
CREATE TABLE b29_fixture_attempts (
    attempt_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL UNIQUE,
    client_request_id TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL REFERENCES b29_fixture_budgets(scope),
    binding_json TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('FOREGROUND_STREAM','BACKGROUND_POLL')),
    reserved_units INTEGER NOT NULL CHECK(reserved_units>0),
    state TEXT NOT NULL,
    response_id TEXT UNIQUE,
    cursor INTEGER NOT NULL DEFAULT -1,
    mock_usage INTEGER,
    CHECK(cursor>=-1)
);
INSERT INTO b29_fixture_marker(identity) VALUES('B29_OFFLINE_ONLY');
"""


class Refused(RuntimeError):
    """Denial with stable, non-secret reason code."""


def _deny(code):
    raise Refused("B29_REFUSED_" + code)


def _id(value):
    return type(value) is str and ID.fullmatch(value) is not None


def _positive(value):
    return type(value) is int and value > 0


def canonical_binding(binding):
    if type(binding) is not dict or set(binding) != BINDING_KEYS:
        _deny("BINDING_SCHEMA")
    for key in BINDING_KEYS - {"generation"}:
        if not _id(binding[key]):
            _deny("BINDING_" + key.upper())
    if not _positive(binding["generation"]):
        _deny("BINDING_GENERATION")
    return json.dumps(binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class SyntheticLedger:
    """Fixture-only SQLite state, supplied by test harness; no host discovery."""

    def __init__(self, connection, *, max_active=2):
        if not isinstance(connection, sqlite3.Connection):
            _deny("CONNECTION_REQUIRED")
        if not _positive(max_active) or max_active > 16:
            _deny("CONCURRENCY_CONFIG")
        self.conn = connection
        self.max_active = max_active
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        # Callers must use autocommit mode; BEGIN IMMEDIATE is authoritative.
        if connection.isolation_level is not None:
            _deny("AUTOCOMMIT_REQUIRED")

    def initialize(self):
        # Never migrate a foreign database, including actual Hospital storage.
        existing = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )}
        if existing == TABLES:
            marker = self.conn.execute(
                "SELECT identity FROM b29_fixture_marker"
            ).fetchall()
            if len(marker) != 1 or marker[0]["identity"] != "B29_OFFLINE_ONLY":
                _deny("FIXTURE_MARKER")
            return
        if existing:
            _deny("FOREIGN_DATABASE")
        self.conn.executescript(DDL)

    def _transaction(self, operation):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
            self.conn.commit()
            return result
        except BaseException:
            self.conn.rollback()
            raise

    def _attempt(self, attempt_id):
        row = self.conn.execute(
            "SELECT * FROM b29_fixture_attempts WHERE attempt_id=?",
            (attempt_id,)
        ).fetchone()
        if row is None:
            _deny("ATTEMPT_MISSING")
        return row

    def _safe(self, row):
        return {
            "attemptId": row["attempt_id"], "turnId": row["turn_id"],
            "clientRequestId": row["client_request_id"],
            "scope": row["scope"], "mode": row["mode"],
            "state": row["state"], "reservedUnits": row["reserved_units"],
            "responseId": row["response_id"], "cursor": row["cursor"],
            "mockUsage": row["mock_usage"],
            "launchAuthorized": False, "toolDispatchAuthorized": False,
            "realStopVerified": False, "realSpendVerified": False,
            "retryAuthorized": False, "realProviderCalls": 0,
            "productionReady": False,
        }

    def state(self, attempt_id):
        if not _id(attempt_id):
            _deny("ATTEMPT_ID")
        return self._safe(self._attempt(attempt_id))

    def budget(self, scope):
        if not _id(scope):
            _deny("SCOPE")
        row = self.conn.execute(
            "SELECT * FROM b29_fixture_budgets WHERE scope=?", (scope,)
        ).fetchone()
        if row is None:
            _deny("BUDGET_MISSING")
        return dict(row)

    def configure_mock_budget(self, scope, limit_units):
        if not _id(scope) or not _positive(limit_units):
            _deny("BUDGET_INPUT")
        def op():
            old = self.conn.execute(
                "SELECT limit_units FROM b29_fixture_budgets WHERE scope=?",
                (scope,)
            ).fetchone()
            if old is not None:
                if old["limit_units"] != limit_units:
                    _deny("BUDGET_RECONFIGURE")
                return self.budget(scope)
            self.conn.execute(
                "INSERT INTO b29_fixture_budgets(scope,limit_units) VALUES (?,?)",
                (scope, limit_units)
            )
            return self.budget(scope)
        return self._transaction(op)

    def reserve(self, *, attempt_id, client_request_id, scope,
                binding, mode, units):
        if not all(_id(x) for x in (attempt_id, client_request_id, scope)):
            _deny("IDENTITY")
        binding_json = canonical_binding(binding)
        turn_id = binding["turnId"]
        if mode not in MODES or not _positive(units):
            _deny("PROFILE_OR_COST")
        def op():
            old = self.conn.execute(
                "SELECT * FROM b29_fixture_attempts WHERE turn_id=?",
                (turn_id,)
            ).fetchone()
            if old is not None:
                if (old["attempt_id"] == attempt_id and
                        old["client_request_id"] == client_request_id and
                        old["scope"] == scope and old["mode"] == mode and
                        old["binding_json"] == binding_json and
                        old["reserved_units"] == units):
                    return self._safe(old)  # Idempotence, not permission to resend.
                _deny("TURN_ALREADY_BOUND")
            budget = self.budget(scope)
            active = self.conn.execute(
                "SELECT COUNT(*) AS n FROM b29_fixture_attempts WHERE scope=? "
                "AND state IN (" + ",".join("?" for _ in STATES_HOLD) + ")",
                (scope, *sorted(STATES_HOLD))
            ).fetchone()["n"]
            if active >= self.max_active:
                _deny("CONCURRENCY_LIMIT")
            if budget["used_units"] + budget["reserved_units"] + units > budget["limit_units"]:
                _deny("BUDGET_EXHAUSTED")
            try:
                self.conn.execute(
                    "INSERT INTO b29_fixture_attempts("
                    "attempt_id,turn_id,client_request_id,scope,binding_json,"
                    "mode,reserved_units,state) VALUES(?,?,?,?,?,?,?,'RESERVED')",
                    (attempt_id, turn_id, client_request_id, scope,
                     binding_json, mode, units)
                )
            except sqlite3.IntegrityError:
                _deny("REUSED_REQUEST_ID")
            self.conn.execute(
                "UPDATE b29_fixture_budgets SET reserved_units=reserved_units+? "
                "WHERE scope=?", (units, scope)
            )
            return self.state(attempt_id)
        return self._transaction(op)

    def mark_submission(self, attempt_id, current_binding):
        current = canonical_binding(current_binding)
        def op():
            row = self._attempt(attempt_id)
            if row["state"] != "RESERVED":
                _deny("ALREADY_SUBMITTED_OR_CLOSED")
            if row["binding_json"] != current:
                _deny("AUTHORITY_CHANGED")
            self.conn.execute(
                "UPDATE b29_fixture_attempts SET state='SUBMISSION_UNCONFIRMED' "
                "WHERE attempt_id=?", (attempt_id,)
            )
            return self.state(attempt_id)
        return self._transaction(op)

    def bind_mock_response(self, attempt_id, response_id):
        if not _id(response_id):
            _deny("RESPONSE_ID")
        def op():
            row = self._attempt(attempt_id)
            if row["state"] not in (
                    "SUBMISSION_UNCONFIRMED", "REMOTE_OUTCOME_UNKNOWN",
                    "CANCEL_PENDING"):
                _deny("RESPONSE_STATE")
            if row["response_id"] is not None and row["response_id"] != response_id:
                _deny("RESPONSE_ID_DRIFT")
            if row["response_id"] is None:
                try:
                    self.conn.execute(
                        "UPDATE b29_fixture_attempts SET response_id=? "
                        "WHERE attempt_id=?", (response_id, attempt_id)
                    )
                except sqlite3.IntegrityError:
                    _deny("RESPONSE_REPLAY_OTHER_TURN")
            return self.state(attempt_id)
        return self._transaction(op)

    def stream_cursor(self, attempt_id, cursor):
        if type(cursor) is not int or cursor < 0:
            _deny("CURSOR")
        def op():
            row = self._attempt(attempt_id)
            if (row["mode"] != "BACKGROUND_POLL" or
                    row["state"] not in ("SUBMISSION_UNCONFIRMED",
                                         "REMOTE_OUTCOME_UNKNOWN") or
                    row["response_id"] is None or cursor <= row["cursor"]):
                _deny("CURSOR_UNBOUND_OR_REPLAY")
            self.conn.execute(
                "UPDATE b29_fixture_attempts SET cursor=? WHERE attempt_id=?",
                (cursor, attempt_id)
            )
            return self.state(attempt_id)
        return self._transaction(op)

    def transport_lost(self, attempt_id):
        def op():
            row = self._attempt(attempt_id)
            if row["state"] not in ("SUBMISSION_UNCONFIRMED",
                                    "REMOTE_OUTCOME_UNKNOWN"):
                _deny("LOSS_STATE")
            self.conn.execute(
                "UPDATE b29_fixture_attempts SET state='REMOTE_OUTCOME_UNKNOWN' "
                "WHERE attempt_id=?", (attempt_id,)
            )
            return self.state(attempt_id)
        return self._transaction(op)

    def cancel(self, attempt_id):
        def op():
            row = self._attempt(attempt_id)
            if row["state"] == "RESERVED":
                # Proven local pre-submission cancellation: no request can exist.
                self.conn.execute(
                    "UPDATE b29_fixture_attempts SET state='ABORTED_PRE_SUBMISSION' "
                    "WHERE attempt_id=?", (attempt_id,)
                )
                self.conn.execute(
                    "UPDATE b29_fixture_budgets SET reserved_units=reserved_units-? "
                    "WHERE scope=?", (row["reserved_units"], row["scope"])
                )
            elif row["state"] in ("SUBMISSION_UNCONFIRMED",
                                  "REMOTE_OUTCOME_UNKNOWN", "CANCEL_PENDING"):
                self.conn.execute(
                    "UPDATE b29_fixture_attempts SET state='CANCEL_PENDING' "
                    "WHERE attempt_id=?", (attempt_id,)
                )
            else:
                _deny("CANCEL_STATE")
            return self.state(attempt_id)
        return self._transaction(op)

    def observe_mock_background_cancel(self, attempt_id, response_id, status):
        if status not in ("cancelling", "cancelled"):
            _deny("CANCEL_STATUS")
        def op():
            row = self._attempt(attempt_id)
            if (row["mode"] != "BACKGROUND_POLL" or
                    row["state"] != "CANCEL_PENDING" or
                    row["response_id"] != response_id or not _id(response_id)):
                _deny("CANCEL_RECEIPT_UNBOUND")
            if status == "cancelled":
                self.conn.execute(
                    "UPDATE b29_fixture_attempts "
                    "SET state='MOCK_CANCELLED_UNVERIFIED' WHERE attempt_id=?",
                    (attempt_id,)
                )
            # Never release budget or assert verified remote stop from mock data.
            return self.state(attempt_id)
        return self._transaction(op)

    def revoke_if_changed(self, attempt_id, current_binding):
        current = canonical_binding(current_binding)
        def op():
            row = self._attempt(attempt_id)
            if row["binding_json"] == current:
                return self.state(attempt_id)
            if row["state"] == "RESERVED":
                self.conn.execute(
                    "UPDATE b29_fixture_attempts SET state='REVOKED_PRE_SUBMISSION' "
                    "WHERE attempt_id=?", (attempt_id,)
                )
                self.conn.execute(
                    "UPDATE b29_fixture_budgets SET reserved_units=reserved_units-? "
                    "WHERE scope=?", (row["reserved_units"], row["scope"])
                )
            elif row["state"] in STATES_HOLD:
                self.conn.execute(
                    "UPDATE b29_fixture_attempts SET state='REVOKED_REMOTE_UNKNOWN' "
                    "WHERE attempt_id=?", (attempt_id,)
                )
            # No attempt can regain authority by restoring an old binding.
            return self.state(attempt_id)
        return self._transaction(op)

    def reconcile_mock_completed(self, attempt_id, response_id, usage_units,
                                 current_binding):
        current = canonical_binding(current_binding)
        if type(usage_units) is not int or usage_units < 0:
            _deny("USAGE")
        def op():
            row = self._attempt(attempt_id)
            if (row["state"] != "SUBMISSION_UNCONFIRMED" or
                    row["binding_json"] != current or
                    row["response_id"] is None or
                    row["response_id"] != response_id or
                    usage_units > row["reserved_units"]):
                _deny("UNTRUSTED_SETTLEMENT")
            self.conn.execute(
                "UPDATE b29_fixture_budgets SET "
                "reserved_units=reserved_units-?, used_units=used_units+? "
                "WHERE scope=?", (row["reserved_units"], usage_units, row["scope"])
            )
            self.conn.execute(
                "UPDATE b29_fixture_attempts SET state='MOCK_COMPLETED', "
                "mock_usage=? WHERE attempt_id=?", (usage_units, attempt_id)
            )
            return self.state(attempt_id)
        return self._transaction(op)
