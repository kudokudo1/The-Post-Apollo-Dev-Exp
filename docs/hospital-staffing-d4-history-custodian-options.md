# 🏥💜 Hospital // D4 permanent original-request history custody options

**PATIENT:** `The-Post-Apollo-Dev-Exp` · **ROOM:** Hospital Staffing · Protected Writer Recovery · **ROLE:** external Hospital-compatible DOC, live attachment not verified.  
**SOURCE:** [Hospital draft #133](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/133), dependent on separately owned protected PX backend [#130](https://github.com/kudokudo1/The-Post-Apollo-Dev-Exp/pull/130) and Connections/Identity custody.  
**STATUS:** Decision aid and test acceptance criteria only. No D1/D2/D3/D4/D5 owner acceptance, installed root, native signer, release, schema or production activation.

## IMPLEMENTATION // Physical mechanism and trust boundary

The Hospital writer stores `Session`, `Doctor` and one-use grant history in **SQLite files**. If a whole older database image is restored, a formerly committed request and its local grant fence disappear together. A newly signed grant for the **same original request nonce** can then appear new. Hospital's real Session source in #133 reproduces that failure in a disposable GitHub runner.

An independent witness must hold enough *original-request identity and monotonic history* **outside the same rollback authority** to detect that loss. Signing a historical packet only proves the bytes matched a key. If the same adversary can restore the signing key, floor, database and enrollment policy to older versions, the old signature can be perfectly valid while the history is wrong.

**Required invariant:** A previously RESERVED/PENDING original `requestNonce` must remain fenced for every later writer/grant, even after local Hospital database rollback, a process restart, a new signed approval, or an interrupted source reply. No absence/timeout may authorize retransmission. A PENDING witness does **not** prove COMMITTED or REFUSED.

## D4 ownership options for operator and custodians

| Candidate custody | What it actually isolates | Critical risk | Production design position |
| --- | --- | --- | --- |
| **A. Hospital SQLite with signed rows** | Detects accidental editing of rows that survive | DB rollback erases rows and any locally stored floor | **Reject as sole D4 custodian** |
| **B. Separate local root-owned daemon and database** | Isolates app/desktop UIDs and process crashes if correctly installed | Host root, whole-machine backup or snapshot rollback may restore both stores; local signer/floor can roll back | **Insufficient alone**; useful front end only with independently anchored monotonic history |
| **C. Separate protected monotonic/append-only authority** | Can retain original request identity beyond Hospital's backup/rollback domain | Provisioning, attestation, liveness/availability, compromised remote root and consistency proof complexity | **Preferred architecture to evaluate**, not selected or approved; may use an independently administered remote witness or hardware-rooted monotonic anchor if actually supported and measured |

A TPM-backed counter is not automatically a complete transaction ledger: the counter would need an independently verifiable authenticated mapping from each request nonce to its original reservation and an antirollback history root. Actual hardware availability, write endurance, provisioning and compromise behavior are **unverified**. A remote authority likewise needs separate credentials, release enrollment, authenticated durable append and consistency/non-equivocation checks. No claim is made that either is installed or fit for this host.

### Required custodian API contract (proposal)

- **RESERVE(original identity):** Independently attest the installed original protected writer release and requester audience; verify human consent at the original operation boundary. Atomically reserve the exact request nonce, scope hash, signed grant digest, original COMMIT hash, policy generation, writer instance/host and signer role under a monotonic history position. **Durable acknowledgement must precede source COMMIT.** Repeated RESERVE for the same original request must not create a new lease; a changed grant is a conflict.
- **CONSUME_ORIGINAL_LEASE:** Only the enrolled original writer can use a **one-time narrow lease** tied to that reservation and source transaction. Reject fresh coordinator/altered grant after process restart. If no independently authenticated, durable reservation or lease state is available, **HOLD without source mutation**. This is not implemented by an in-memory Boolean in production.
- **SOURCE_COMMIT:** In one actual Hospital SQLite `BEGIN IMMEDIATE`, write the signed-grant consumption, original Session/Doctor source mutation and COMMITTED journal. The external reservation remains PENDING until independently reconciled.
- **READ_HISTORY / RECONCILE:** Authentic read-only query with a new one-use challenge and separately trusted enrolled writer/custodian evidence. A historical PENDING is not resolved by timeout or a caller's JSON. Only exact authenticated durable source history can support COMMITTED/ALREADY_APPLIED, and only a provable no-commit terminal fence can support REFUSED. Split histories, rollback and contradictory records produce UNKNOWN/CONFLICT/HOLD.
- **RECOVERY/OPERATOR:** Human-visible, narrowly authorized manual reconciliation for unresolved PENDING; never a silent second COMMIT. Every installed release/key rotation needs independent enrollment and revocation; a stale or unavailable custodian denies protected mutations.

### Monotonic floor versus per-request history

The current #133 signed-history CI fixture requires the signed `sequence` to equal the independently supplied test floor. This establishes **single-record fixture equality**, not a production append-only history protocol. As a *real* global counter moves forward, older valid PENDING reservations must still be retrievable with authenticated inclusion/consistency evidence. Merely rejecting all prior sequence numbers would preserve safety by refusing indefinitely but could break recovery and liveness. Advancing the floor must not erase or un-fence older original nonces.

A production design needs an independently pinned **current head** and authenticated historical membership or nonmembership proof for the request against that head, with explicit behavior for stale forks and unavailable custody. A valid old signed packet with no current consistency proof is not adequate.

## VERIFY // Exact existing evidence, without promoting authority

- Hospital #133 real Session/Doctor CI rollback checks have demonstrated that a locally committed grant/source/journal can be replayed after restoring an earlier Hospital database and reissuing a new grant.
- The same draft's source-linked write-ahead CI stores PENDING in a separate **untrusted** disposable SQLite witness **before** source COMMIT and denies reissue after crash, absent history or local rollback. It does not provide independent custody or atomic two-store commit.
- At Hospital #133 `6ea2877be2badb010e2680a603b284881f93ced9`, CI signed PENDING verification is called **inside the real source Session transaction before signed grant consumption**; a different signed grant, missing CI key and stale floor are denied. The key and floor still come from disposable fixtures.
- Connections merged [#2103](https://github.com/kudokudo1/The-Post-Apollo-Project/pull/2103) provides a **source-only, read-only RECOVER query shape**, not signed native COMMITTED/REFUSED receipts.
- Connections merged [#2107](https://github.com/kudokudo1/The-Post-Apollo-Project/pull/2107) checks TimeW/Hospital purpose isolation with disposable signer roles. Its referenced `tests/connections/c3e_release_trust/C3eAFSignedRoleEnrollment.py` explicitly says its enrollment root is supplied by CI, **not an operator/HSM/independent production authority**. Do not repurpose an Identity-only role enrollment as a Hospital history signer without a separate owner-approved enrollment.

## Source-only historical membership follow-up (not owner acceptance)

The standalone [historical-membership CI test](../tests/test-px-hospital-staffing-history-membership-ci.py) now models a **signed current head** over an ordered hash-linked **full history prefix**. An original signed PENDING at sequence 1 remains observable when unrelated requests advance the trusted current head to sequence 4. It checks exact request nonce, original signed packet bytes, contiguous sequence positions and a separately supplied expected head/release; missing, truncated, reordered, duplicated, forged or altered history is denied. A distinct new request at sequence 4 is also independently observable as PENDING, **not authorized to execute**.

This is a bounded `MAX_RECORDS=32` educational fixture, **not** an efficiently indexed Merkle tree, installed append-only ledger, independent non-equivocation service, secure hardware anchor or genuine persisted counter. Its key, head and external-looking expected inputs originate in the same disposable runner; source rollback and head rollback cannot be ruled out merely by validating the old signed bytes. A real custodian must supply an independently trusted *current* head, authenticated membership/consistency proof for arbitrary historical requests, fork/revocation evidence and availability rules. Its membership proof must remain verifiable as more requests append, without treating old PENDING as COMMITTED/REFUSED.

The [real Session transaction CI test](../tests/test-px-hospital-staffing-real-source-journal-ci.py) also now refuses **unsigned PENDING history** in write-ahead mode, even with a matching local reservation and one-use fixture lease. This is test-hook mandatory enforcement only. Other legacy/native grant paths remain unintegrated and unapproved.

### Historical membership now exercised inside the source transaction (CI only)

At the follow-up source-only checkpoint, the [original Session/Doctor source CI test](../tests/test-px-hospital-staffing-real-source-journal-ci.py) now calls the standalone [historical-membership verifier](../tests/test-px-hospital-staffing-history-membership-ci.py) **inside the original Session source `BEGIN IMMEDIATE`, before `VerifiedStaffingGrant.consume`**. The exact old PENDING packet occupies sequence 1 in the test history, while three unrelated synthetic requests advance the signed global head to sequence 4. The verifier compares exact original signed packet bytes, original grant/COMMIT/scope identity, history membership, the purpose-specific current-head signature, and a **separately supplied CI head anchor and sequence**. Only after this succeeds can the original *fixture-only* lease and original source checks proceed. Matching history **never itself authorizes** execution or determines COMMITTED/REFUSED.

After restoring an older Hospital SQLite backup, the same real source path must HOLD for (a) a missing membership context even when a new packet matches the new signed grant, (b) a tampered independently supplied CI head, and (c) a different newly signed PENDING/grant that is **not a member** of the original current history. These hostile attempts use fresh synthetic coordinators, leave source Session/grant counts unchanged, and never restore the spent original one-use lease. The previous missing-signature, missing-witness and stale-pin failures remain exercised.

**Limits:** This only combines **two disposable CI fixtures** at a monkeypatched source transaction seam. The `MAX_RECORDS=32` full-prefix hash-chain, both signing keys, test head anchor, file and in-process lease are not protected by an independent custodian. The separate witness file is untrusted, and a signed current head alone proves nothing about whether its anchor was rolled back or replaced. A legitimate old historical PENDING still cannot supply COMMITTED/REFUSED, permit COMMIT retry, or bypass the original C5 active-seat permission. Production selection, all-path enforcement, native authority, operator acceptance, root enrollment, scalable historical proofs and rollback/power-loss resistance all remain unimplemented.

## WATCH OUT FOR // Release gates and adversarial acceptance tests

1. **Independent rollback:** Rewind Hospital's SQLite DB, then reboot/restart issuer and original writer. Every historical original nonce must remain fenced under a separately trusted current history head. Rewind the proposed custodian store too; the independently anchored head must detect or hold on the downgrade.
2. **Interrupted ordering:** Crash before reservation durable ACK; after durable PENDING but before source; during source SQLite COMMIT; after source but before witness outcome ACK; after signed outcome. No second grant may execute, regardless of local/remote mismatch.
3. **Two-writer races:** Two writer releases and different signed grants for the same original request concurrently attempt reserve/consume. Exactly one original lease can be valid; any ambiguous or duplicated outcome is HOLD, not a second Session.
4. **Proof substitution:** New or revoked issuer, mismatched writer/host/release/scope/review, stale future sequence, old valid signed history, rotated root, forged current head, inconsistent inclusion path and absent root must fail closed.
5. **Recovery liveness:** Historical PENDING must remain provable after unrelated new requests advance the global head. No production design may equate PENDING with COMMITTED/REFUSED or require retaking C5 consent retroactively for an already uncertain original operation.
6. **Operations:** Explicit root/key custody authority, backup/rebuild/rollback runbook, no unsigned fallback, old-writer cutover, SELinux/UID/socket provenance, recovery UI with UNKNOWN/HOLD, and operator approval are separate release gates.

## CHECKLIST

- [x] Original-request rollback/reissue negative test and same-transaction CI hook
- [x] Write-ahead PENDING ordering and signed CI packet validation
- [x] Source-linked signed-PENDING check against the actual Session writer (CI only)
- [ ] PX protected-writer owner **D1/D2 ACCEPT / REVISE / HOLD**
- [ ] Connections/Identity custodian **D4 selected independent history authority and release enrollment**
- [ ] Connections/Hospital joint **D3 authenticated RECOVER and D5 results**
- [ ] Independent security review of new source-linked signed check and this decision contract
- [ ] Separately authorized native implementation, protection, migration, rollback and operator acceptance

## NEXT // DECISIONS

**Proposed direction:** Evaluate C, possibly with B as a narrowly admitted front end. **Do not select C automatically**: approved operator/owner choice must specify custody, hardware/remote prerequisites, enrollment/rotation, rooted history head and failure modes before anyone implements a production service. A failed or unavailable custodian means safe HOLD, not fallback to A.

No installed Host/Connections/SwayPX source, live Hospital DB, production signing key, service, schema v14 migration, PR merge or workstation is changed by this document.
