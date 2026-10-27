# EXEC-S3 // B36-H3a Post-Merge Diagnostic Redaction

> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (external Hospital-compatible, not connected)
> ASSIGNMENT // Narrow post-merge security hardening of H3 diagnostics
> BASE // H3 merged `main` at `3736afb37650abd9ba46c3faa5aa8b8cdb1e0646`
> STATE // DRAFT · SOURCE AND OFFLINE TESTS ONLY · NO LIVE GATEWAY OR PROVIDER

## IMPLEMENTATION

B36-H3's offline `assess()` returns a fixed diagnostic decision while refusing native provider execution. Its original response included `candidateSnapshot: deepcopy(candidate)`. Because the candidate is an **untrusted arbitrary dictionary**, this copies user data (possibly credentials or unbounded nested content) into a diagnostic object that might later be logged, serialized or reported. It can also trigger special deep-copy behavior or recursion.

H3a removes the snapshot field and its `deepcopy` import. Results retain only constant schema/decision fields, fixed zero/false admission flags, and sorted refusal-reason codes. Input validation, H3 semantics, B24 hard DENY, ACK/kernel separation and all source security checks remain unchanged. It adds four dedicated regression tests.

This is a **diagnostic output contract change**: any downstream consumer expecting `candidateSnapshot` must stop relying on raw untrusted input in diagnostics. No such consumer is introduced in H3/H3a.

## HOW TO USE

No Fedora action is required. Review the GitHub PR. Tests run entirely in GitHub or an isolated checkout:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b36-h3-hermes-supervisor.py

## VERIFY

Expected H3 tests increase from 24 to **28**. Combined integration expected **387** (H3 28 + H2 26 + H1 23 + B35 22 + B34 14 + B24–B33 274). Existing main baseline job remains **274**. CI and exact merge checkout evidence are required before review completion.

New tests verify: injected secret values never appear in diagnostic output; a large arbitrary extra payload does not increase returned evidence size; a hostile non-copyable object is not recursively traversed; and a self-referential candidate never propagates into result serialization.

## WATCH OUT FOR

- H3a does **not** implement a trusted supervisor, gateway stop, kernel teardown, credential namespace, real Hermes isolation, process launch or Hospital registration.
- No new real-provider capability; every H3 result remains DENY.
- This fix prevents the diagnostic return value from copying raw payloads. It does not prove other callers will never log raw inputs before passing them to this function.
- The personal Hermes service, local Fedora system, provider registry, `bin/px-agent` and production configurations are untouched.

## CHECKLIST

- [x] Reinspect current merged H3 source and owner state
- [x] Remove untrusted candidate snapshot from diagnostic response
- [x] Add four redaction/recursion/size regression tests
- [ ] Verify exact GitHub integration checkout and test counts
- [ ] Independent review and separate merge authorization
- [ ] Future trusted supervisor runtime/OS evidence acceptance

## NEXT

Review this H3a patch and its CI. Resume B36-H4 offline architecture only after preserving H2/H3 acceptance requirements. Do not promote H3 fake evidence into real gateway authority.

## DECISIONS

Standalone GitHub PR, no merge or production activation. Revert H3a as a discrete change if a downstream diagnostic contract legitimately requires safe metadata; do **not** restore raw candidate copies. Production HOLD.
