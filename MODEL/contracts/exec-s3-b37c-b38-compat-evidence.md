# PX EXEC-S3 // B37-C ↔ B38 mock compatibility evidence

> STATE // DRAFT · CROSS-LANE OFFLINE EVIDENCE · NOT AN INTEGRATED SENDER  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // B37-C/B38 compatibility (external Hospital-compatible, not live)  
> ASSIGNMENT // Prove B38 legacy bypass and demonstrate B37-C adapter compatibility *in tests only*  
> PRODUCTION // HOLD  
> B38 OWNER // Separate active workstream. No B38 code modified.

## IMPLEMENTATION

The merged B37-C `AtomicOfflineFixture.begin_mock` checks the client-request
identity, stored payload SHA-256, synthetic Assignment binding, foreground
mode and RESERVED state in one B29 SQLite transaction.

Current B38-A and B38-B have a different path:

```text
B38-B MockTrustedSender.send_mock
  -> B38-A exchange_mock
  -> imported B37-B mock_handoff
  -> B29 mark_submission (does not compare B37-C payload digest)
```

The **source-verified gap** is real: a B38-B fake sender can transition a
B29 reservation that lacks B37-C's stored SHA-256, because B38-A invokes
B37-B, not B37-C. The tests intentionally assert that this old path still
runs, making the missing enforcement observable rather than hiding it behind
green CI.

The compatibility tests additionally use Python `unittest.mock.patch.object`
inside a disposable test to temporarily redirect B38-A's imported
`mock_handoff` reference to `AtomicOfflineFixture.begin_mock`. That
isolated simulation proves that B38-B's static text-frame parser and
one-use permit can *technically* coexist with the B37-C atomic transition.
The adapter maps B37-C refusal into B37-B's existing sanitized refusal
shape, which B38-B already recognizes.

**This is not a secure or production adapter.** Runtime monkeypatching
is not a real security barrier, is not thread-safe as process-wide policy,
and leaves the original unmodified B38-A/B implementation callable. It
must NOT be installed, shipped or used as the accepted B38 sender.

## HOW TO USE

The dedicated GitHub Actions workflow checks out the PR's `main`-derived
branch and the **exact separate B38-B head SHA** as a read-only test
dependency, without adding B38's files to this PR:

- B38-B pinned source: `40844e2fb5dd9c4800450060a7d3e3b8a318cdc8`
  (includes parent B38-A implementation)
- B37-C landed main baseline: `8b288f1b548f4ebc50fb134b77f8df3527efa805`

Run in CI or a separately authorized disposable checkout:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37c-b38-compat-evidence.py
```

The harness requires the pinned checkout in `b38-pinned/bin` and otherwise
refuses. No real user machine setup is requested.

## VERIFY

This test-only PR checks:

- **Expected old-path bypass:** unregistered B37-C digest and corrupted
  B37-C digest do not block the unmodified fake B38 sender. These are
  *evidence of the integration gap*, not security passes.
- **Experimental guarded test seam:** refused unregistered or corrupted
  payload hash; B37-C transition occurs once for a valid request.
- B38-B permit refusal after pause, revocation, generation change or restart;
  replay and forged seal refusal.
- Reopening the disposable database after simulated transition moves
  unobserved submission into `REMOTE_OUTCOME_UNKNOWN`, preserves held budget,
  and refuses a new B38 preparation.
- Non-text frame refusal and permanent no-network/no-real-provider claims.

CI also runs B37-C, B38-B and B38-A test suites against the pinned source.

## WATCH OUT FOR

Do **not** describe this compatibility harness as closing the integration
gap. It proves a currently bypassable path and tests one possible adaptation.
For genuine code integration, the separate B38 owner must explicitly
choose a non-monkeypatched interface; then:

1. B38's normal `send_mock` must require the registered B37-C hash and
   consume a single audited atomic mock transition, not call B37-B directly.
2. Test **all** entry points and concurrency/replay paths, including
   B38-A direct invocation, so a caller cannot fall back to old B37-B.
3. Keep live Hospital authority sourcing, authenticated provider transports,
   credentials, real billing and process isolation on **PRODUCTION HOLD**;
   disposable SHA-256 and mock permits are not authenticated capability tokens.
4. Treat B38-B's dependency on B38-A, and B38-C's dependency on B38-B,
   as separate merge/acceptance decisions.

## CHECKLIST

- [x] Read and compare merged B37-C and pinned draft B38-A/B source
- [x] Prepare isolated compatibility evidence tests and boundary contract
- [ ] Verify exact PR head, pinned B38 commit and CI logs
- [ ] Independent cross-lane review by B38 owner and Hospital reviewers
- [ ] Operator decision on a real offline interface change in B38
- [ ] Combined default code path cannot bypass B37-C (NOT DONE)
- [ ] Production authorization (NOT GRANTED)

## NEXT

B38 owner: review the documented default-path bypass, then coordinate an
offline-only interface design to use B37-C without relying on a global
monkeypatch or changing B37-owned source. Existing B38 PR #108/#110/#111
remain untouched. The operator separately decides merge and production
permissions.

## DECISIONS

This PR only adds tests, documentation and CI. It deliberately does not edit
B37-C, B38-A/B/C, `bin/px-agent`, Hermes, Fedora or Hospital records, and
does not introduce a callable real sender. Independent review and operator
acceptance remain mandatory.
