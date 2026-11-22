"""PX Hospital v12 // Recoverable Room lifecycle, not deletion.

This module is owned by PX. Room rows and all dependent evidence remain in the
same SQLite database. A Trash/Restore operation changes a lifecycle marker
transactionally and stores a minimal receipt; Burn is deliberately unsupported.

CAUTION: An independently issued, pinned Ed25519 one-use grant is mandatory.
The native operator/seat/retention signer is external and NOT supplied here;
no production deployment approval may be inferred from unit tests.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import px_hospital_room_authority as room_authority

ROOM_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_GRAPH_ROWS = 20000

# Table identity is hardcoded, never provided by a CLI caller.
RELATIONS = (
    ("sessions", "room_id = ?", 1),
    ("messages", "room_id = ?", 1),
    ("session_events", "session_id IN "
     "(SELECT session_id FROM sessions WHERE room_id = ?)", 1),
    ("room_checkpoints", "room_id = ?", 1),
    ("room_reports", "room_id = ?", 1),
    ("assignments", "room_id = ?", 1),
    ("chart_entries", "room_id = ? OR source_room_id = ?", 2),
    ("chart_suggestions", "room_id = ? OR source_room_id = ?", 2),
)
# Direct Room references and indirect Session event relationships, even when
# another record is being moved onto a trashed Room, must be rejected.
GUARDED_REFS = (
    ("rooms", ("room_id",)),
    ("sessions", ("room_id",)),
    ("messages", ("room_id",)),
    ("room_checkpoints", ("room_id",)),
    ("room_reports", ("room_id",)),
    ("assignments", ("room_id",)),
    ("chart_entries", ("room_id", "source_room_id")),
    ("chart_suggestions", ("room_id", "source_room_id")),
)

class RoomLifecycleRefused(RuntimeError):
    pass


def _identity(room_id):
    if type(room_id) is not str or not ROOM_PATTERN.fullmatch(room_id):
        raise RoomLifecycleRefused("ROOM_ID_INVALID")
    return room_id


def _tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS room_lifecycle (
            room_id TEXT PRIMARY KEY NOT NULL
                REFERENCES rooms(room_id) ON DELETE RESTRICT,
            state TEXT NOT NULL CHECK(state IN ('ACTIVE', 'TRASHED')),
            revision INTEGER NOT NULL CHECK(revision > 0 AND revision <= 1000000000),
            frozen_digest TEXT NOT NULL,
            trashed_at TEXT,
            restored_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS room_lifecycle_receipts (
            receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE RESTRICT,
            action TEXT NOT NULL CHECK(action IN ('TRASH', 'RESTORE')),
            revision_before INTEGER NOT NULL,
            revision_after INTEGER NOT NULL,
            graph_digest TEXT NOT NULL,
            grant_digest TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(room_id, revision_after)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS room_lifecycle_authorizations (
            nonce TEXT PRIMARY KEY,
            grant_digest TEXT NOT NULL UNIQUE,
            approval_id TEXT NOT NULL UNIQUE,
            room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE RESTRICT,
            operator_id TEXT NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('TRASH', 'RESTORE')),
            revision_before INTEGER NOT NULL,
            graph_digest TEXT NOT NULL,
            consumed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_room_lifecycle_state "
        "ON room_lifecycle(state, room_id)"
    )
    # Failing any operation on a TRASHED graph prevents corruption at the
    # source SQLite boundary, including through ordinary old PX commands.
    for table, columns in GUARDED_REFS:
        for verb in ("INSERT", "UPDATE", "DELETE"):
            aliases = ("NEW",) if verb == "INSERT" else (
                ("OLD",) if verb == "DELETE" else ("OLD", "NEW")
            )
            pieces = [
                "EXISTS (SELECT 1 FROM room_lifecycle l "
                "WHERE l.state='TRASHED' AND ("
                + " OR ".join("l.room_id=" + a + "." + col
                              for col in columns)
                + "))"
                for a in aliases
            ]
            conn.execute(
                "CREATE TRIGGER IF NOT EXISTS room_lifecycle_hold_"
                + table + "_" + verb.lower()
                + " BEFORE " + verb + " ON " + table
                + " WHEN " + " OR ".join(pieces)
                + " BEGIN SELECT RAISE(ABORT,'TRASHED_ROOM_WRITE_REFUSED'); END"
            )
    for verb in ("INSERT", "UPDATE", "DELETE"):
        aliases = ("NEW",) if verb == "INSERT" else (
            ("OLD",) if verb == "DELETE" else ("OLD", "NEW")
        )
        pieces = [
            "EXISTS (SELECT 1 FROM sessions s "
            "JOIN room_lifecycle l ON l.room_id=s.room_id "
            "WHERE l.state='TRASHED' AND s.session_id="
            + a + ".session_id)" for a in aliases
        ]
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS room_lifecycle_hold_session_events_"
            + verb.lower() + " BEFORE " + verb + " ON session_events WHEN "
            + " OR ".join(pieces)
            + " BEGIN SELECT RAISE(ABORT,'TRASHED_ROOM_WRITE_REFUSED'); END"
        )
    # A Patient rename/rebind must not silently alter the preserved identity
    # of a Room while it is hidden. Ordinary patients remain editable.
    for verb in ("UPDATE", "DELETE"):
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS room_lifecycle_hold_patients_"
            + verb.lower() + " BEFORE " + verb + " ON patients WHEN "
            + "EXISTS (SELECT 1 FROM rooms r "
            "JOIN room_lifecycle l ON l.room_id=r.room_id "
            "WHERE l.state='TRASHED' AND r.patient_id=OLD.patient_id)"
            + " BEGIN SELECT RAISE(ABORT,'TRASHED_ROOM_PATIENT_HOLD'); END"
        )


def install_schema_v12(conn):
    """Called under the PX migration owner; no caller-defined table names."""
    if conn.in_transaction:
        raise RoomLifecycleRefused("MIGRATION_TRANSACTION_ALREADY_OPEN")
    try:
        conn.execute("BEGIN IMMEDIATE")
        _tables(conn)
        conn.execute(
            "UPDATE schema_meta SET value='12' WHERE key='schema_version'"
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _rows(conn, query, params):
    values = conn.execute(
        query + " LIMIT ?", (*params, MAX_GRAPH_ROWS + 1)
    ).fetchall()
    if len(values) > MAX_GRAPH_ROWS:
        raise RoomLifecycleRefused("RELATED_GRAPH_TOO_LARGE")
    return [dict(row) for row in values]


def _graph(conn, room_id):
    row = conn.execute(
        "SELECT * FROM rooms WHERE room_id=?", (room_id,)
    ).fetchone()
    if row is None:
        raise RoomLifecycleRefused("ROOM_NOT_FOUND")
    data = {"rooms": [dict(row)]}
    for table, predicate, nargs in RELATIONS:
        data[table] = _rows(
            conn, "SELECT * FROM " + table + " WHERE " + predicate
            + " ORDER BY rowid", tuple([room_id] * nargs)
        )
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return data, digest


def review(conn, room_id):
    """Read-only snapshot and blockers. No message/report body is returned."""
    room_id = _identity(room_id)
    data, digest = _graph(conn, room_id)
    state_row = conn.execute(
        "SELECT state,revision,frozen_digest FROM room_lifecycle "
        "WHERE room_id=?", (room_id,)
    ).fetchone()
    state = str(state_row["state"]) if state_row else "ACTIVE"
    revision = int(state_row["revision"]) if state_row else 0
    blockers = []
    if any(str(a["status"]).upper() not in ("COMPLETE", "CANCELLED")
           for a in data["assignments"]):
        blockers.append("NONTERMINAL_ASSIGNMENT")
    if any(not str(s["ended_at"] or "").strip()
           or str(s["status"]).upper() not in ("COMPLETE", "FAILED")
           or s["active_pid"] is not None
           for s in data["sessions"]):
        blockers.append("SESSION_NOT_PROVEN_TERMINAL")
    linked = str(data["rooms"][0]["current_assignment_id"] or "")
    if linked and not any(str(a["assignment_id"]) == linked
                          for a in data["assignments"]):
        blockers.append("CURRENT_ASSIGNMENT_UNVERIFIED")
    if any(str(x["status"]).upper() == "PENDING"
           for x in data["chart_suggestions"]):
        blockers.append("PENDING_CHART_SUGGESTION")
    if any(str(x["status"]).upper() == "ACTIVE"
           for x in data["chart_entries"]):
        blockers.append("ACTIVE_CHART_DECISION")
    # An unrelated Room's provenance must not lose a visible source Room
    # without an independent dependency review.
    if any(str(x["room_id"] or "") != room_id
           for name in ("chart_entries", "chart_suggestions")
           for x in data[name]
           if str(x["source_room_id"] or "") == room_id):
        blockers.append("FOREIGN_ROOM_DEPENDENCY")
    if state == "TRASHED" and digest != str(state_row["frozen_digest"]):
        blockers.append("TRASHED_GRAPH_CHANGED")
    # Existing evidence is retained unchanged; no hard purge or source copy.
    return {
        "roomId": room_id,
        "state": state,
        "revision": revision,
        "digest": digest,
        "blockers": sorted(set(blockers)),
        "relatedCounts": {
            name: len(rows) for name, rows in data.items() if name != "rooms"
        },
        "canTrash": state == "ACTIVE" and not blockers,
        "canRestore": state == "TRASHED" and not blockers,
        "canBurn": False,
        "deletesOriginal": False,
        "operatorAuthenticated": False,
        "requiresOwnerReview": True,
    }


def trashed_rooms(conn):
    """Bin-facing metadata: no private transcripts or report text."""
    rows = conn.execute(
        """SELECT r.room_id, r.team, r.branch, r.display_name,
                  p.repository, l.state, l.revision, l.trashed_at
           FROM room_lifecycle l
           JOIN rooms r ON r.room_id=l.room_id
           LEFT JOIN patients p ON p.patient_id=r.patient_id
           WHERE l.state='TRASHED'
           ORDER BY l.trashed_at DESC, r.room_id ASC
           LIMIT 2500"""
    ).fetchall()
    return [
        {
            "roomId": str(row["room_id"]),
            "name": str(row["display_name"] or row["team"] or row["room_id"]),
            "repository": str(row["repository"] or ""),
            "branch": str(row["branch"] or ""),
            "state": "TRASHED",
            "revision": int(row["revision"]),
            "trashedAt": str(row["trashed_at"] or ""),
            "kind": "HOSPITAL ROOM",
            "burnAllowed": False,
        } for row in rows
    ]


def transition(conn, room_id, action, expected_revision, expected_digest,
               confirm_room_id, *, authorization=None):
    """Exactly one Room, one revision, one transaction. No original DELETE."""
    room_id = _identity(room_id)
    if action not in ("TRASH", "RESTORE"):
        raise RoomLifecycleRefused("PERMANENT_BURN_UNSUPPORTED")
    if type(expected_revision) is not int or not (
            0 <= expected_revision < 1000000000):
        raise RoomLifecycleRefused("EXPECTED_REVISION_INVALID")
    if type(expected_digest) is not str or not DIGEST_PATTERN.fullmatch(
            expected_digest):
        raise RoomLifecycleRefused("EXPECTED_DIGEST_INVALID")
    # An explicit operator gesture, NOT independent identity/seat proof.
    if confirm_room_id != room_id:
        raise RoomLifecycleRefused("EXACT_ROOM_CONFIRMATION_REQUIRED")
    if not isinstance(authorization, room_authority.VerifiedGrant):
        raise RoomLifecycleRefused("SIGNED_ROOM_AUTHORIZATION_REQUIRED")
    if conn.in_transaction:
        raise RoomLifecycleRefused("OPEN_TRANSACTION_REFUSED")
    try:
        conn.execute("BEGIN IMMEDIATE")
        source = review(conn, room_id)
        if expected_revision != source["revision"]:
            raise RoomLifecycleRefused("STALE_ROOM_REVISION")
        if expected_digest != source["digest"]:
            raise RoomLifecycleRefused("ROOM_GRAPH_CHANGED")
        target = "TRASHED" if action == "TRASH" else "ACTIVE"
        if action == "TRASH":
            if not source["canTrash"]:
                raise RoomLifecycleRefused("ROOM_NOT_ELIGIBLE_FOR_TRASH")
        elif not source["canRestore"]:
            raise RoomLifecycleRefused("ROOM_NOT_ELIGIBLE_FOR_RESTORE")
        room_identity = conn.execute("""
            SELECT r.patient_id, p.repository
            FROM rooms r JOIN patients p ON p.patient_id = r.patient_id
            WHERE r.room_id=?
        """, (room_id,)).fetchone()
        if room_identity is None:
            raise RoomLifecycleRefused("ROOM_PATIENT_IDENTITY_UNVERIFIED")
        operator_id, grant_digest = authorization.consume(
            conn, room_id=room_id,
            patient_id=str(room_identity["patient_id"] or ""),
            repository=str(room_identity["repository"] or ""),
            action=action, revision=source["revision"], digest=source["digest"]
        )
        revision = expected_revision + 1
        if expected_revision == 0:
            conn.execute(
                """INSERT INTO room_lifecycle
                   (room_id,state,revision,frozen_digest,trashed_at)
                   VALUES(?,?,?,?,CURRENT_TIMESTAMP)""",
                (room_id, target, revision, source["digest"])
            )
        else:
            changed = conn.execute(
                """UPDATE room_lifecycle
                   SET state=?, revision=?, frozen_digest=?,
                       trashed_at=CASE WHEN ?='TRASHED'
                                      THEN CURRENT_TIMESTAMP ELSE trashed_at END,
                       restored_at=CASE WHEN ?='ACTIVE'
                                       THEN CURRENT_TIMESTAMP ELSE restored_at END
                   WHERE room_id=? AND revision=? AND state=?""",
                (target, revision, source["digest"], target, target,
                 room_id, expected_revision, source["state"])
            ).rowcount
            if changed != 1:
                raise RoomLifecycleRefused("ROOM_LIFECYCLE_CAS_FAILED")
        conn.execute(
            """INSERT INTO room_lifecycle_receipts
               (room_id,action,revision_before,revision_after,graph_digest,
                grant_digest,operator_id)
               VALUES(?,?,?,?,?,?,?)""",
            (room_id, action, expected_revision, revision, source["digest"],
             grant_digest, operator_id)
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {
        "roomId": room_id,
        "state": target,
        "revision": revision,
        "receiptRecorded": True,
        "originalPreserved": True,
        "burnAllowed": False,
        "operatorAuthenticated": False,
        "grantSignatureVerified": True,
        "authorizationVerified": True,
        "requiresOwnerReview": True,
    }
