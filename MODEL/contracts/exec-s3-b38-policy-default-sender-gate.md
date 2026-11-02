# PX EXEC-S3 // B38-C Policy Shape Gate on B38-B Default Mock Sender

> STATE // DRAFT · OFFLINE ONLY · SOURCE/CI/REVIEW PENDING  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // B38-B / B38-C model-only mock sender integration  
> CONNECTION // External Hospital-compatible worker, no live registration  
> ASSIGNMENT // Mandatory, request-bound offline policy prepare and recheck  
> MAIN BASE // 381dd60b187e920a743a3d68597cb56e49da2d7f (merged #113)  
> PRODUCTION // HOLD · B24 real-provider deny preserved

## IMPLEMENTATION

The merged B38-A/B/C default atomic sender (#113) uses B37-C's local
transactional request fence, but B38-B previously did **not** enforce
B38-C's existing inert policy fixture. This additive milestone edits
**only B38-B mock sender** and adds an isolated test suite, contract and CI.

On `MockTrustedSender.prepare_mock(atomic, sealed)`:

1. Existing synthetic paused/ready and B37-C reservation checks run.
2. B38-C `prepare_fake_plan(manifest, sealed, current_binding)` now
   must pass. The default manifest is exactly
   `default_fake_manifest()`: no process, credentials, broker, native
   tool, HTTP, DNS, socket, or arbitrary environment values.
3. The immutable `OfflinePlan` (canonical policy bytes, policy SHA-256,
   request ID, payload SHA-256 and synthetic Assignment binding) is held
   in B38-B's already one-use private `_MockPermit` beside the epoch.

On `MockTrustedSender.send_mock(atomic, sealed, permit)`:

1. Permit identity/epoch, readiness and sealed request are rechecked.
2. B38-C `recheck_fake_plan` revalidates the **current** manifest and
   exact original bytes/request/binding snapshot. Failures deny *before*
   invoking B38-A's fake `exchange_mock` / B37-C transition.
3. The policy receipt must explicitly remain
   `OFFLINE_SHAPE_ONLY` with **false** for every authorization, network
   enforcement, credential protection, OS isolation, readiness and
   production indicator, and zero simulated provider/network/tool/Hospital
   writes.
4. Only after that diagnostic shape check may the original fixed mock
   frames reach B38-A, which retains B37-C's atomic fake transition.

A caller can supply `mock_manifest=` to `MockTrustedSender` solely
for negative tests. Omitting it still generates an internal immutable-plan
snapshot and requires both B38-C checks. The fixture keeps an untrusted
manifest *reference* so a test mutating it between preparation and send
can be detected by the final comparison. This is not a trusted OS
observation or a general runtime manifest update API.

## HOW TO USE

In CI on a disposable GitHub PR checkout, run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38-policy-default-gate.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38b-trusted-sender-mock.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38c-transport-policy.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38-default-atomic-integration.py
```

No real provider, network, secret, OS sandbox, local Fedora or live
Hospital access is requested.

## VERIFY

Expected new tests:
- Default sender always prepares and rechecks a policy plan.
- Explicit safe manifest binds an immutable policy digest to request/turn.
- Missing/extra/unsafe secret, process, broker, tool and egress fields
  fail before preparing a send.
- Mutations to a previously valid policy (including a separately valid
  environment allowlist) fail before synthetic handoff.
- Forged in-process permit plan hashes and permission-looking diagnostics
  fail closed without making the B37-C state transition.
- Replay, crash/reopen, `REMOTE_OUTCOME_UNKNOWN` budget hold, non-text
  direct-client boundary and no real network/credentials remain intact.

Dedicated CI runs the new suite and existing B38-A/B/C, B37-A/B/C and
B33 regression tests on the same PR merge checkout. Inspect exact head,
base and merge SHA; do not treat a green badge as a trusted environment.

## WATCH OUT FOR

**Important scope boundary:** `B38-A.exchange_mock` remains a
directly callable *fake* parser and atomic B37-C entry point; it does
not itself enforce B38-C's policy. This milestone covers B38-B's
**default mock sender path**, not every internal fixture helper, and
does not gate a real runtime transport.

B38-C validates a caller-provided description of **no** process and
**no** network, not observed OS process or secret isolation. The sender
and mock policy are Python objects in one interpreter. An adversary
with Python execution authority can patch functions or instantiate
other fake clients; this fixture is not a security sandbox.

The test-only fake response is returned after `SUBMISSION_UNCONFIRMED`
local transition, not as B33 durable independent provider observation.
The full transaction/remote-delivery gap remains unverified for real
systems. No real credential or endpoint mechanism is introduced.

The historical B38-C contract predates consolidation and describes
older stacked draft branch provenance; this integration addendum
states the actual new `main` baseline. Do not rewrite the original
B37-C or old B38 branches during this work.

## CHECKLIST

- [x] Check live `main`, concurrent PRs and Syntagma authority
- [x] Add bounded B38-B source change on isolated branch
- [x] Add new negative/positive sender-policy tests
- [ ] Verify dedicated and inherited PR-head CI
- [ ] Independent cross-lane Hospital review
- [ ] Operator decision to merge, not assumed by continuation
- [ ] B38-D real OS/credential isolation verification (separate approval)
- [ ] Real provider production admission: HOLD

## NEXT

Review that no path through the B38-B fake sender reaches
`exchange_mock` without a B38-C `OfflinePlan` bound at
preparation and rechecked at the final synthetic send boundary.
A later real model-only sender must use independently observed
authority and OS/credential/network enforcement, not these
caller-owned fake policy claims.

## DECISIONS

Operator's `continue` applies only to the next identified *offline*
B38-C/B38-B compatibility step. No merge, rebase of concurrent worker
branches, production activation, actual credentials or Fedora writes.
The canonical B37-C SQLite fence is unchanged; the B24 deny holds.
