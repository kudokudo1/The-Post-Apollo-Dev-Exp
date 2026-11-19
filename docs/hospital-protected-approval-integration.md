# 🏥 Hospital Trash and Restore // Protected approval integration

## IMPLEMENTATION

**This is the database-side portion of the existing Hospital Trash and Restore assignment**, not a new Hospital job or a transfer of the Trash++ file/Camera/Archive owner.

- **PX parent:** draft #130, existing Room lifecycle v12 and the protected 21-write/19-read database service. **Prerequisite:** PX #121 (schema v11 Room names). This new branch is stacked on exact PX #130 HEAD \`aea04d01242c9d13f2dd4f34d699cab7bd11abf3\`, without overwriting that branch.
- **Hospital application:** draft #2069, native approval request and source-owned Trash++ bin.
- **Connections:** merged application #2056, independent operator identity/seat/Polkit/signature authority.
- \`bin/px_hospital_native_approval.py\` adds the **exact C5-H2 protected \`PREPARE\`/\`COMMIT\` protocol**, retaining original Room and evidence. Its PREPARE reads the protected database, checks current Room state, blockers, patient and repository, requires a separate root-owned retention/legal-hold approval, and returns a short-lived, explicitly bound prepared receipt.
- COMMIT takes a separately signed Ed25519 one-use grant; verifies the pinned issuer key and installed host binding; checks exact Room/action/revision/graph/Patient/Repository and a matching outstanding writer-side request ID; rechecks retention policy before source transition and again **inside the same SQLite write transaction** as the nonce/approval receipt and Room state. Replay and expired approvals refuse. No Burn.
- \`bin/px-hospital-native-writerd\` is a **source-only** native socket-activated listener for the specific C5-H2 \`SOCK_SEQPACKET\` protocol at fixed \`/run/post-apollo/hospital/px-writer.sock\`. It rejects non-root issuers; each packet requires kernel \`SCM_CREDENTIALS\`, not merely user-submitted JSON IDs. It reuses PX's separately protected database writer identity and source validators, without modifying the existing read-only \`SOCK_STREAM\` Room/Bin service.
- C5-H2 requestNonce and Ed25519 grant nonce are intentionally distinct. The former binds the approved PREPARE/COMMIT exchange; the latter is irrevocably consumed in the DB ledger. Operator consent cannot be inferred from either nonce alone.
- The independently controlled retention source is fixed at \`/etc/post-apollo/hospital/room-retention-policy.json\` with schema \`postapollo.hospital.room-retention-decision.v1\`. It must be root-owned and explicitly authorize the exact Room, Patient, repository and operation with \`legalHold:false\`, a positive policy generation and future expiry. **This PR does not create that file or decide legal/retention eligibility.** Without the policy, PREPARE refuses.

## VERIFY

The new cross-repository CI checkout imports the **actual merged Connections signer code** and the real PX v12 SQLite source, with ephemeral Ed25519 keys and a disposable, independently supplied test policy. Test assertions exercise PREPARE format, C5-H2 validation, sign, one-use COMMIT, exact writer receipt, Room Trash→Restore, replay denial, retention revocation and unsigned/nonroot denial.

All files are source-only and no user machine, real Hospital Room, service or root key is modified by CI.

## WATCH OUT FOR

1. **This is not an installed service.** Administrator-approved systemd socket activation, real root-owned file provenance, executable identity hash enrollment, independent trusted retention source, private key/public verification pinning, SELinux and 3-UID socket ACLs remain to be implemented and accepted. No automatic local install, merge or deployment.
2. **The existing PX #130 socket remains available for read-only bin/review and protected runtime legacy commands.** This new C5 protocol adds a distinct, root-activated listener; the owner must verify two-service lifecycle, credentials, resource contention, and approved installed paths.
3. The parent PX protected source still has the deployment/rollback prerequisite: backup and v10→v11→v12 migration, no desktop-owned DB fallback, old-writer fencing, and Bed/Session/Assignment command reconciliation with their existing PR owners. Those branches are not silently merged.
4. The root-owned retention document is only a technical admission mechanism. The operator, Hospital policy and independent security reviewer must define actual legal/retention authority before any grant is issued.
5. **Never activate Hospital Burn**, which is explicitly outside this work.

## NEXT

After CI and independent review, finish the exact protected installed-host contract and align owner-approved PX #130 / #121 merging. Then validate the real *Hospital → Connections approval → protected database → Trash++ bin → Restore* sequence on disposable host data before requesting operator acceptance.

## DECISIONS

User has explicitly directed this worker to take responsibility for the overall Hospital Trash and Restore integration and stop making them coordinate unidentified technical work across chats. Development proceeds on this separate PX draft branch, while active #130 remains untouched. The user's approval to develop does **not** constitute permission to merge, change the user workstation or destroy Room evidence.
