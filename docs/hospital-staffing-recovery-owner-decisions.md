# 🏥💜 Hospital ↔ Connections // Staffing Recovery Owner Decision Record

**Status:** OWNER AGREEMENT REQUESTED · ALL PROPOSALS UNAPPROVED · PRODUCTION HOLD  
**Patient / owner:** The-Post-Apollo-Dev-Exp / Hospital PX protected writer  
**Counterpart:** The-Post-Apollo-Project / Connections native staffing issuer  
**Room:** Hospital staffing Session/Doctor · protected COMMIT recovery  
**Role:** External Hospital-compatible DOC, live Hospital registration unverified  
**Source checkpoint:** Hospital #133 `fb771ba70731cafda7e40cbb8619ecee55cf6cc8` (NRS-2 scoped source PASS, 3/3 workflows)  
**Upstream:** Connections #2082 and #2083 merged to main, but recovery remains CI-only and deny-by-default

## IMPLEMENTATION // Decisions awaiting the respective owners

This is an **approval worksheet** that narrows the questions in `docs/hospital-staffing-writer-recovery-contract.md`. It is not approval by the operator, Hospital PX owner, Connections issuer owner, or Nurse 2. Nothing in this file enables authority, installs a service, migrates the database, or changes any accepted wire format.

### D1 // Durable journal version and owner

**Hospital PX writer owner decides.**

Proposed choice: create a separately versioned result journal/migration (candidate v14), **unless** PX explicitly accepts replacing the uninstalled candidate v13 design first. A separate schema provides an explicit cutover gate and avoids silently interpreting the existing consumed-grant v13 row as an authenticated result.

Required persisted identity fields, at minimum:

| Evidence | Required binding |
| --- | --- |
| `requestNonce`, independent signed grant `nonce`, `approvalId`, `grantDigest` | Unique original PREPARE and one-use authorization, separately indexed; duplicates or split keys are a HOLD |
| `writerInstance`, authenticated protected writer release identity, host identity | Preserve the exact writer/release instance that committed; a process restart cannot impersonate history |
| `commitSha256`, `scopeDigest`, `reviewDigest` | Identify exact canonical COMMIT, original full reviewed scope and approved human-visible intent |
| `roomId`, operation, resulting Session and Doctor identities, source graph digest/revision | Tie the journal to the actual Room/Patient/Assignment/Bed state reviewed |
| Source transaction ID/outcome and durable journal sequence | Bind one terminal outcome to the original atomic Session/Doctor mutation |
| External independently durable history/witness reference | Detect rollback or replacement of the writer's local journal |

**Nonnegotiable invariant:** the COMMITTED journal row, existing grant one-use ledger row, and original Session/Doctor source mutation must be committed in the **same SQLite transaction**. Any failure must roll back all three. A missing or corrupted journal row after a lost reply remains UNKNOWN/HOLD; it never becomes REFUSED or permission to retry.

Hospital must review any SQLite migration, exclusive-writer process fencing, backup/WAL restoration, old-writer cutover and rollback **before** updating canonical `bin/px-hospital-store`. This decision record changes none of those files.

### D2 // Durable refusal fencing

**Hospital PX writer owner decides.**

Proposed conservative rule: do **not** expose a terminal REFUSED status unless an authenticated protected writer creates a durable terminal refusal record, serialized against any COMMIT of the *same original request and grant*, and fences all later attempts under the original nonce.

A local validation failure, missing record, process restart, expired in-memory PREPARE, or rollback **does not** itself prove an irreversible refusal. If the owner cannot prove the terminal fence through atomic source ownership and independently durable history, return UNKNOWN (or hard security HOLD on conflict), and keep the original grant non-retryable.

A previously COMMITTED transaction can be reported as ALREADY_APPLIED **only by an authenticated read-only query to that same historical committed record**. It must not execute COMMIT again.

### D3 // Recovery query protocol and response trust

**Connections issuer owner and Hospital writer owner both decide.**

Proposed protocol is a **new, read-only, separately versioned RECOVER action** with no grant consumption, Session/Doctor write, or automatic retry. The request must be bound to the original PREPARE requestNonce, action/Room/Session identity, original writerInstance, signed grant identifier and exact COMMIT hash, plus a fresh independently verified one-use challenge.

The reply must include exact original operation identity, challenge, explicit protocol/schema versions, durable transaction outcome ID, writer release and host provenance, plus independently verifiable origin and replay resistance. A response from a caller-chosen fixture key, a bare hash, a self-described `COMMITTED` JSON field, or a Linux peer UID alone is **not** trusted native writer evidence.

The current Connections 15-field `postapollo.connections.hospital.staffing-receipt-proposal.ci-v1` is a **CI proposal**, not a Hospital-approved native receipt. Neither owner may silently reinterpret it as production status.

### D4 // Independent signer, history and operator consent custody

**Connections issuer owner, Hospital protected-writer owner and designated custodian decide within their existing authority.**

The signed staffing *grant issuer*, signed protected *writer result* and independent *antirollback history/witness* need explicit custody, enrollment, rotation, revocation and release provenance decisions. Do not reuse Room Trash/Restore issuer credentials for staffing or let a caller pass its own trust key.

For any eventual native path, verify actual installed Python entrypoint/modules and unit provenance as well as process/kernel credentials; an interpreter ELF hash alone is insufficient. Actual local active unlocked login1 seat, noncached staffing-specific human intent and effective Polkit agent/rules must be separately proven for the original mutation. RECOVER is read-only; it does not recreate missing human consent.

### D5 // Protocol results and release gate

**Both owners decide the wire semantics; operator alone accepts deployment.**

| Result | Required evidence | Safe client action |
| --- | --- | --- |
| `COMMITTED` | Authenticated writer + exact original durable committed transaction | Display confirmed outcome; **never resend COMMIT** |
| `ALREADY_APPLIED` | Authenticated read-only query of the same historical COMMITTED row | Display history; **never resend COMMIT** |
| `REFUSED` | Durable authenticated terminal refusal with a proven no-commit fence | Display refusal; **do not reuse same grant** |
| `UNKNOWN` / `INTERRUPTED` | Any uncertain/missing/incomplete response or journal history | Keep status unresolved; no automatic retry |
| `CONFLICT` | Contradictory identities, duplicate keys, historical rollback, invalid writer proof | Security HOLD; no retry or source mutation |

Before any implementation on a real host: independent NRS-2 review, exact-head CI with crash tests, old-writer cutover/fencing, protected DB backup/rollback, provisioned root policy and release anchors, real human-visible consent acceptance, and separate operator merge/install/activation approval.

## HOW TO USE // Owner responses (GitHub)

**Hospital PX writer owner:** Reply to Hospital #133 with `D1 ACCEPT/REVISE/HOLD`, `D2 ACCEPT/REVISE/HOLD`, selected owner-controlled schema version and durable refusal fence mechanism. State the scope of any source authorization separately from install authority.

**Connections issuer owner:** Reply on the corresponding Connections recovery PR/coordination record with `D3 ACCEPT/REVISE/HOLD`, `D4 ACCEPT/REVISE/HOLD`, exact protocol/query version and native writer attestation mechanism. Identify any fields that require changing the Hospital contract.

**Joint reconciliation:** Agree on `D5` only once both sets of decisions are recorded. No silence, CI success or external DOC comment counts as owner acceptance. If either owner holds, preserve source-only status and make no live dependency assumptions.

## VERIFY

NRS-2 reviewed Hospital #133 at source SHA `fb771ba70731cafda7e40cbb8619ecee55cf6cc8` and gave a scoped CI/source PASS. The actual current candidate v13 grant-consumption ledger does not contain the original request nonce, writer instance, COMMIT hash or a trusted result witness. Connections #2083 classifies post-send uncertainty without trusting a caller-provided result. Both are correct **within their existing deny-only scopes** and insufficient for native authenticated recovery.

## WATCH OUT FOR

This file is not executable migration code, an accepted source receipt, a signed policy, a live Hospital assignment, or a verified independent custodian. It does not grant write permission to existing PX owner branches. In particular, the term `REFUSED` is withheld until its fencing contract is proven; `UNKNOWN` is not evidence of no commit.

## CHECKLIST

- [x] Exact current source facts, owner roles and NRS-2 checkpoint reconciled
- [x] Concrete D1-D5 decision boundaries and safe default behaviors specified
- [ ] Hospital PX owner accepts/revises D1 + D2
- [ ] Connections issuer owner accepts/revises D3 + D4
- [ ] Joint owner reconciliation of D5, schema and native receipt
- [ ] Separately authorized code, independent review and operator release acceptance

## NEXT

Capture explicit owner decisions on GitHub. Once agreed, implement the approved isolated journal schema and native status query under separate owner review. Until then, retain only CI-only recovery evidence and the hard native recovery denial.

## DECISIONS

**No approval implied.** Hospital draft #133 and its existing owner branches remain unmerged; native Session/Doctor COMMIT recovery, Room Burn, production credentials, host configuration and database migrations remain disabled.
