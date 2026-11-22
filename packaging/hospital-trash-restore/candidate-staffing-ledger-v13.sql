-- PX Hospital / candidate schema v13: signed staffing approval ledger
--
-- DRAFT / NOT APPROVED FOR NATIVE INSTALLATION.
-- The PX owner of bin/px-hospital-store currently supports v12 only.
-- This candidate must be independently accepted and integrated with the
-- owner-controlled versioned migrate() implementation BEFORE any native
-- service can read/write it. Do NOT apply to user data or a live database.
-- CI tests this script ONLY against disposable v12 SQLite fixtures.
--
-- Transaction guard: an interrupted operation must not leave either
-- a table without the schema version, or a version without the table.
BEGIN IMMEDIATE;

CREATE TEMP TABLE hospital_staffing_v13_migration_guard (
    previous_version INTEGER NOT NULL CHECK(previous_version = 12)
);
INSERT INTO hospital_staffing_v13_migration_guard(previous_version)
VALUES((
    SELECT CASE WHEN value = '12' THEN 12 ELSE -1 END
    FROM schema_meta WHERE key = 'schema_version'
));

CREATE TABLE hospital_staffing_authorizations (
    nonce TEXT NOT NULL PRIMARY KEY,
    grant_digest TEXT NOT NULL UNIQUE,
    approval_id TEXT NOT NULL UNIQUE,
    room_id TEXT NOT NULL
        REFERENCES rooms(room_id) ON DELETE RESTRICT,
    operation TEXT NOT NULL
        CHECK(operation IN ('SESSION_ATTACH', 'DOCTOR_SUCCEED')),
    operator_id TEXT NOT NULL CHECK(length(operator_id) BETWEEN 1 AND 160),
    session_id TEXT NOT NULL CHECK(length(session_id) BETWEEN 1 AND 160),
    graph_digest TEXT NOT NULL CHECK(length(graph_digest) = 64),
    consumed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(length(nonce) = 43),
    CHECK(length(grant_digest) = 64),
    CHECK(length(approval_id) BETWEEN 12 AND 128)
);

CREATE INDEX idx_hospital_staffing_authorizations_room
    ON hospital_staffing_authorizations(room_id, consumed_at DESC);

UPDATE schema_meta SET value = '13'
WHERE key = 'schema_version' AND value = '12';

DROP TABLE hospital_staffing_v13_migration_guard;
COMMIT;
