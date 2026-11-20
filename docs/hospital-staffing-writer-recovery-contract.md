# 🏥💜 Hospital // Protected writer staffing COMMIT recovery contract

**PATIENT:** The-Post-Apollo-Dev-Exp  
**ROOM / ROLE:** Hospital Trash/Restore ↔ Connections Session/Doctor source integration; external Hospital-compatible DOC, live registration unverified  
**ASSIGNMENT:** Define Hospital-owned durable outcome evidence after a lost staffing COMMIT reply. Source-only, do not operate live Hospital.  
**COMPANION:** Connections #2082 merged on main (transport + receipt preflights), Connections #2083 merged to main (unknown result classifier; source-only), Hospital #133 separate protected writer draft  
**RELEASE:** NOT AUTHORIZED / NO native staffing recovery / NO schema migration / NO real receipt / NO host writes

## IMPLEMENTATION // Existing transaction evidence and limits

The current candidate v13 SQLite `hospital_staffing_authorizations` row is inserted inside the *same* `BEGIN IMMEDIATE` transaction that then creates/reuses the reviewed Session or performs Doctor succession. If admission fails, the original atomic handler rolls back the grant ledger and source mutation together. It never publishes a successful *native* response; `px_hospital_staffing_prepare_commit.py` emits a clearly marked **CI fixture receipt** after the owner source transaction has committed in the disposable rehearsal.

The v13 candidate ledger stores **only** `nonce`, `grant_digest`, `approval_id`, `room_id`, `operation`, `operator_id`, `session_id`, `graph_digest` and `consumed_at`. It does **not** durably store `requestNonce`, `writerInstance`, full signed PREPARE scope, historic reviewed identity, an authenticated writer receipt, or an independently protected antirollback history. Thus a local matching ledger row is useful forensic evidence, but it cannot by itself authenticate the original requester, preserve an independently rooted signer history, or attest that a later caller's purported receipt was genuine.

### Source-only implementation, isolated in #133

`bin/px_hospital_staffing_ledger_recovery.py` is a **CI-only, read-only** evidence inspector. It accepts exactly canonical original PREPARE, PREPARED and COMMIT fixture bytes, plus a signed grant verified using a **caller-chosen CI public key**. It requires a candidate v13 database using the existing exact ledger columns, rejects changed Room/action/intent/request nonce/writer instance/review digest and cross-grant nonce/approval/digest collisions, then queries the existing ledger *without modifying it*.

Only these observational outcomes exist:

| CI observation | Meaning | Operational authority |
| --- | --- | --- |
| `CI_LEDGER_ROW_MATCH_OBSERVED_NOT_AUTHENTICATED` | Exact candidate grant identities occur in a **disposable** v13 ledger produced by original atomic source fixture | **NOT** an authenticated production COMMITTED receipt |
| `CI_NO_MATCHING_LEDGER_ROW_OUTCOME_UNKNOWN` | No matching candidate ledger entry was observed on that fixture database | **UNKNOWN**; never proof of refusal or safe retry |
| `HOSPITAL_STAFFING_LEDGER_RECOVERY_HOLD` | Input/identity/collision/schema invalid, or the reader has no allowed CI source context | **STOP**; never alternate action/automatic retry |

All output keeps actual writer identity, production signer, human consent, installed release, protected transaction and native receipt verification explicitly **false**. `recover_native_staffing()` always refuses. No production socket, signing service, migration or on-host file is added.

## HOW TO USE

For current development, the GitHub Actions `Hospital / Universal Connections Signed Trash Restore` workflow runs `tests/test-px-hospital-staffing-prepare-commit.py` with an isolated SQLite v12→candidate-v13 migration under `RUNNER_TEMP`. The test verifies a writer failure after grant insert **rolls back both the Session and ledger**, and is still classified UNKNOWN; a successful Session attachment and Doctor succession leave exact matching ledger evidence; altered PREPARE, changed writer or conflicting durable evidence fails closed. A former Session's ledger row remains useful to inspect after a later Doctor succession changes current Room staffing.

Do NOT run this CI fixture module on the workstation or expose it as a service. It is not an installed native recovery API.

## Pending authenticated **production** query / receipt contract (proposal only)

Before any source or native deployment, the Hospital protected writer owner and Connections issuer owner must agree on:

1. **Independent requester/host evidence:** Reader connects to the owner-approved protected writer service, checks real Linux `SO_PEERCRED` and per-packet `SCM_CREDENTIALS`, pinned UID/GID, stable process birth, root-approved signed executable/Python+unit provenance and an independently enrolled writer release. Root file ownership or a Python interpreter hash alone are insufficient.
2. **Exact challenge and original operation identity:** Recovery queries must be a separate narrow read-only operation with a fresh challenge, the **original** requestNonce, writerInstance, grant nonce/digest, approvalId, Room, action, Session, source revision/graph, original reviewed scope and independent reply channel identity. A user-supplied JSON status or unauthenticated hash is never evidence. The recovery query must never dispatch a new Session/Doctor COMMIT.
3. **Durable atomic outcome journal:** Migrate only under PX owner approval, with a protected transaction record written **within the same transaction** as the Session/Doctor mutation. The record must durably bind requestNonce, writerInstance, original approved scope/review hash, signed grant digest and operation result or durable refusal, writer release identity and unambiguous commit identity. The existing candidate v13 table is **insufficient** by itself. Changes to v13/v14 or any history-witness/antirollback floor require owner-controlled migration, backup, old-writer fencing and rollback.
4. **Authenticated, versioned writer response:** Choose an explicit Hospital-owned receipt schema and required fields in coordination with Connections' **unapproved** 15-field `ci-v1` receipt proposal. Include request and reply protocol version, fresh challenge, precise original source identity, durable transaction record or refusal record, writer release fingerprint / authenticated provenance and anti-replay/antirollback evidence. The new status is not accepted unless independently established as sent by the correctly enrolled protected writer. Do not confuse Connections' shape-only `status` with an authenticated database result.
5. **Recovery decisions (fail closed):**
   - **COMMITTED** only on independently authenticated writer evidence identifying the exact durable source transaction and original approved request.
   - **ALREADY_APPLIED** only on the same durable committed record returned by a *new read-only recovery query*, never by replaying the old COMMIT or grant.
   - **REFUSED** only with an authenticated durable refusal record that unambiguously excludes commitment of that original request. A missing row or lost response is not refusal.
   - **INTERRUPTED / UNKNOWN** whenever source history, proof of refusal, trusted writer origin, durable witness or reply is missing, inconsistent, stale or cannot be verified.
   - **CONFLICT / tampering** is a hard security hold; do not retry, rewrite history, delete the ledger, or treat it as success.
   
A valid human staffing approval does not authorize a separate arbitrary recovery status service. Reading completed operation evidence must not return live signing keys, raw grant material, database handles or unrelated patient records to Connections/UI.

## Proposed durable journal identity // Owner decision required

This is a **candidate contract**, not an approved SQL migration or runnable native service. Hospital's protected-store/PX owner must decide whether to extend candidate v13 or introduce a new versioned journal. The current consumed-grant table is not an authenticated result journal.

| Candidate persisted evidence | Why it matters |
| --- | --- |
| Unique `requestNonce` from original PREPARE and signed grant `nonce` | Distinguish separate approval histories across service restarts |
| Exact `writerInstance` and independently enrolled writer release generation | Prevent a new process from pretending to be the original writer |
| Canonical `commitSha256`, signed `grantDigest`, `approvalId` | Identify exact COMMIT and reviewed authorization, not lookalike requests |
| Full original `scopeDigest`, `reviewDigest`, `roomRevision`, `graphDigest` | Bind Room/Patient/Assignment/Bed and the Session/Doctor transition |
| Source Session outcome and protected transaction ID | Link the journal to the actual source mutation |
| Terminal `COMMITTED` or fenced `REFUSED` state | Prevent contradictory subsequent status for one reviewed request |
| Writer release provenance plus independently held monotonic history head | Permit authenticated proof and rollback detection |

**Atomicity:** A COMMITTED journal record must become durable in the **same SQLite transaction** as the source Session/Doctor mutation and one-use grant consumption. REFUSED is valid only if the protected writer serializes and durably terminalizes the exact request, proves no earlier COMMIT occurred, and fences all later COMMITs using it. Failed/rolled-back transactions, missing records and expired in-memory PREPARE tickets never establish REFUSED. A test row written separately does not prove a committed source mutation.

**Recovery query:** Future RECOVER is an independent, narrow **read-only** request, not a retry or spelling of COMMIT. It must bind a fresh challenge to original PREPARE request nonce, signed grant identity, exact COMMIT hash, independently verified writer/host and release. ALREADY_APPLIED is only an authenticated read-only view of a prior COMMITTED record, not a second write.

**Authenticated response:** Hospital and Connections must approve a versioned canonical receipt containing the fresh challenge, original operation identity, outcome, durable journal identifier and enrolled writer release witness. A self-declared JSON status or unsigned hash cannot prove writer origin. Connections' existing 15-field `ci-v1` receipt remains **unapproved shape-only documentation**; it cannot authorize Session/Doctor staffing or tell whether an unknown COMMIT succeeded.

**Future mandatory adversarial cases:** duplicate request nonce across distinct grants; reused approval after restart; one signed grant with two COMMIT hashes; two writer instances claiming one request; lost response before/after SQLite commit; ledger deletion/rollback; forged COMMITTED or REFUSED; mismatched reply challenge; stale schema; release downgrade; missing independent history anchor; conflicting source identity. **Any uncertain grant stays non-retryable.**

**Owner decisions needed:** (1) Approved durable request identity and versioned schema; (2) terminal refusal fence authority; (3) independent writer enrollment and antirollback custodian; (4) verifiable query/receipt format and private proof channel; (5) migration, WAL backup, old-writer fence and rollback plan before operator acceptance.

## VERIFY // Evidence

- Connections #2082 **MERGED** into `main`; it reconciles eight source-only transport/receipt files from previous stacked branches without production issuer authority.
- Connections #2083 remains **draft**, exactly `02140c9a88bc5c34b0162ba534079cdb1811777f` when reviewed, source-only unknown-outcome classifier; 24 new CI cases and inherited tests passed there according to GitHub. Its arbitrary caller trace/response is never verified Hospital evidence.
- Hospital #133 maintains exclusive source writer and candidate v13 ledger. At source checkpoint `25da3fe79702d492983f338b73f002c895e06d57`, **3/3 GitHub workflows PASS** after negative recovery tests and malformed PREPARED-record hardening. No source changes to other owner branches.

## WATCH OUT FOR

**Neither this document nor the CI inspector authenticates an installed Hospital writer.** In particular, looking up `grant_digest` does not establish a true native receipt or proof of human approval; a caller-chosen CI public key is not a trusted signer. A signed grant can be historically valid but expired by the time recovery occurs; a *new* approval must never overwrite the history of an uncertain old one. Existing source uses candidate version 13 only inside disposable CI, and the true protected writer's production migration still supports v12.

Room Trash/Restore, Bed registration and Hospital Burn remain outside the staffing recovery authority. No service, key, Polkit, logind, systemd, Sway, machine `/etc`, live SQLite or other owner's repository changed.

## CHECKLIST

- [x] Establish source facts and current v13 ledger limits.
- [x] Implement isolated CI-only ledger examination and native denial.
- [x] Test atomic rollback versus durable row, unknown and conflicting evidence.
- [ ] Independent Hospital PX writer-owner decision on durable recovery schema and exact transaction journal.
- [ ] Connections owner agreement on query/receipt challenge, reply proof and protocol version.
- [ ] Approved trusted writer release/provenance, signer/Polkit/seat, schema migration and operational rollback.
- [ ] Native installed source-to-issuer recovery tests; external security review; operator final acceptance.

## NEXT

Ask the two owners to approve or correct the proposed durable result journal and authenticated query/receipt before any native implementation. Do not conflate successful source tests with protected production writer attestation.

## DECISIONS

Hospital #133 remains OPEN/DRAFT/UNMERGED. The authorized scope is source-only evidence and cross-owner coordination. No host activation, production DB access, native permission, PR merge or separate owner assignment transfer occurred.
