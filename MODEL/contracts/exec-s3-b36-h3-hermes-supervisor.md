# PX EXEC-S3 // B36-H3 Trusted Supervisor Boundary (OFFLINE)

> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (external Hospital-compatible; not live-registered)
> ASSIGNMENT // B36-H3 trusted-supervisor adapter design and offline refusal gates
> BASE // B36-H1 merged main `3e8ac2563f510c5308b989f13bc37ce72fd9a7bc`
> STATE // DRAFT · OFFLINE ONLY · NO REAL HERMES EXECUTION · PRODUCTION HOLD

## IMPLEMENTATION

B36-H3 defines the **shape of evidence a future trusted PX supervisor would need**, without implementing that supervisor.

The offline adapter in `bin/px_s3_b36_h3_hermes_supervisor.py` evaluates an untrusted candidate envelope containing:

- exact Patient / Room / Assignment / Session / Turn / Generation scope;
- a PX supervisor identity and fresh Hospital-authority generation;
- dedicated Hermes gateway identity;
- restart fencing;
- native tool denial and credential confinement;
- explicit cancellation or revocation intent;
- authenticated gateway STOP acknowledgment;
- a separate kernel-evidence identifier;
- independent descendant-empty observation bound to the same generation.

Gateway acknowledgment and kernel teardown are deliberately distinct. A protocol `STOP_ACK` is not process-tree proof. A claimed empty process tree is not trusted merely because an input dictionary says so.

Every result remains `DENY`, with `launchAuthorized=false`, `terminationVerified=false`, zero model/tool/gateway/Hospital calls, and explicit `TRUSTED_SUPERVISOR_RUNTIME_UNAVAILABLE`, `KERNEL_ATTESTATION_UNAVAILABLE`, and `REAL_PROVIDER_PRODUCTION_HOLD`.

This checkpoint is independent of unmerged B36-H2 PR #95. It does not import H2 fake-owner state and does not create a stacked PR dependency.

## HOW TO USE

No Fedora action is required. Run only in a disposable checkout:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b36-h3-hermes-supervisor.py

Do not start, stop, restart, reconfigure, inspect credentials from, or recruit the operator's personal Hermes gateway.

## VERIFY

24 offline tests cover exact Hospital scope, generation freshness, supervisor identity, dedicated gateway identity, restart fencing, native tool denial, credential confinement, cancellation intent, authenticated STOP ACK, independent kernel evidence, descendant teardown, malformed schemas, spoofed provider identity, immutable inputs, zero subprocess/file/socket effects, and unconditional real-admission refusal.

Current-main integration count is expected to be B36-H3 **24** + B36-H1 **23** + B35 **20** + B34 **14** + B24-B33 **274** = **355** tests. H2 is intentionally excluded until PR #95 is separately reviewed and merged.

## WATCH OUT FOR

1. This is a **contract model**, not a trusted supervisor implementation.
2. No kernel pidfd/cgroup reader exists here. `descendantsEmpty=true` is untrusted fixture data.
3. No authenticated Hermes STOP protocol is implemented here. `gatewayAckAuthenticated=true` is untrusted fixture data.
4. Fresh Hospital authority is not fetched. The candidate's freshness flag is explicitly insufficient for admission.
5. A future real implementation must bind the gateway process tree, credential namespace, stop request, gateway ACK, kernel observation, Assignment generation, and restart fence to one non-replayable authority record.
6. Personal Hermes remains outside this experiment. No production activation.

## CHECKLIST

- [x] Keep H3 independent of unmerged H2
- [x] Specify supervisor/Hospital/gateway/STOP/kernel evidence boundary
- [x] Keep gateway ACK distinct from kernel teardown
- [x] Add 24 offline refusal/zero-side-effect tests
- [ ] Verify GitHub PR integration checkout and exact counts
- [ ] Independent security review
- [ ] Operator-authorized merge
- [ ] Later: implement trusted supervisor runtime
- [ ] Later: independently verify real OS teardown and restart fencing

## NEXT

B36-H4 should remain offline until H2/H3 review resolves. A future checkpoint may design a disposable real-gateway harness, but only after the trusted supervisor interface, model-only tool denial, credential confinement, and kernel teardown observation have independent acceptance criteria.

## DECISIONS

DRAFT ONLY. H3 does not merge H2, does not weaken B24 production DENY, and does not touch `bin/px-agent`, provider registry, personal Hermes, credentials, Fedora services, or live Hospital state.

## RECOVERY / HANDOFF

Expected new files:
- `bin/px_s3_b36_h3_hermes_supervisor.py`
- `tests/test-pxd-exec-s3-b36-h3-hermes-supervisor.py`
- `MODEL/contracts/exec-s3-b36-h3-hermes-supervisor.md`

Existing integration workflow receives one H3 offline test step. Rollback is closing the draft PR; after any separately authorized merge, revert separately.
