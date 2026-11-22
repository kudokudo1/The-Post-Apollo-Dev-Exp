-- CI-ONLY Hospital staffing source-linked terminal journal, proposed D1/D2.
-- THIS IS NOT a production migration or a selected schema v14.
-- ONLY tests/test-px-hospital-staffing-real-source-journal-ci.py may apply
-- this file to an isolated, disposable v12 -> candidate-v13 SQLite fixture.
-- The real px-hospital-store schema remains v12; native recovery stays OFF.
--
-- Source Session/Doctor writers currently consume grant nonce inside their
-- BEGIN IMMEDIATE. This separate fixture checks the consequences of a
-- writer-owned journal hook in THAT existing transaction, not a new native
-- permission or accepted signed receipt.
BEGIN IMMEDIATE;
CREATE TEMP TABLE ci_v14_expected_previous (
  previous INTEGER NOT NULL CHECK(previous = 13)
);
INSERT INTO ci_v14_expected_previous(previous)
SELECT CASE WHEN value='13' THEN 13 ELSE -1 END
FROM schema_meta WHERE key='schema_version';

CREATE TABLE ci_staffing_result_v14_candidate (
  request_nonce TEXT NOT NULL PRIMARY KEY,
  grant_nonce TEXT NOT NULL UNIQUE,
  grant_digest TEXT NOT NULL UNIQUE,
  approval_id TEXT NOT NULL UNIQUE,
  commit_sha256 TEXT NOT NULL UNIQUE CHECK(length(commit_sha256)=64),
  writer_instance TEXT NOT NULL,
  room_id TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE RESTRICT,
  operation TEXT NOT NULL CHECK(operation IN ('SESSION_ATTACH','DOCTOR_SUCCEED')),
  session_id TEXT NOT NULL,
  original_scope_sha256 TEXT NOT NULL CHECK(length(original_scope_sha256)=64),
  review_digest TEXT NOT NULL CHECK(length(review_digest)=64),
  graph_digest TEXT NOT NULL CHECK(length(graph_digest)=64),
  terminal TEXT NOT NULL CHECK(terminal IN ('COMMITTED','REFUSED')),
  writer_transaction_id TEXT NOT NULL UNIQUE,
  CHECK(length(grant_digest)=64),
  CHECK(length(request_nonce)=43),
  CHECK(length(grant_nonce)=43)
);
CREATE INDEX ci_staffing_result_room_idx
ON ci_staffing_result_v14_candidate(room_id, operation);

-- The current source function inserts into the v13 grant ledger inside
-- its same BEGIN IMMEDIATE. The CI-only trigger models a terminal refusal
-- fence at that actual insertion point. REFUSED and COMMITTED both fence
-- grant replay; a missing row never implies a trustworthy REFUSED.
CREATE TRIGGER ci_staffing_terminal_fence_before_grant
BEFORE INSERT ON hospital_staffing_authorizations
WHEN EXISTS (
  SELECT 1 FROM ci_staffing_result_v14_candidate r
  WHERE r.grant_nonce=NEW.nonce OR r.grant_digest=NEW.grant_digest
     OR r.approval_id=NEW.approval_id
)
BEGIN SELECT RAISE(ABORT,'CI_ONLY_TERMINAL_STAFFING_FENCE'); END;

UPDATE schema_meta SET value='14' WHERE key='schema_version' AND value='13';
DROP TABLE ci_v14_expected_previous;
COMMIT;
