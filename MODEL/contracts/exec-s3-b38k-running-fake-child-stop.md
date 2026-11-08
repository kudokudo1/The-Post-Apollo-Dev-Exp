# PX EXEC-S3 // B38-K Running Disposable Fake Child Stop

> STATUS // DRAFT · TEST-ONLY · NO REAL PROVIDER · INDEPENDENT REVIEW PENDING  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // Hermes Integration Security  
> STAFF ROLE // PXD, bounded fake-only implementation, B37-C owner interface preserved  
> CONNECTION // External Hospital-compatible; no live Hospital registration  
> BASE // B38-J PR #124 merged main 769b154169b43ac9cb376dc3532b8b394272aa37  
> PRODUCTION // HOLD · B24 REAL_PROVIDER_DENY

## IMPLEMENTATION

B38-J proved host-observed separate worker exit and refusal after READY
when a cancellation was committed before LAUNCH. It **did not stop a
genuinely running isolated child**. B38-K adds one standalone disposable
test harness, a CI workflow and this handoff. No B29/B33/B37-C/B38-G/
B38-I/B38-J/runtime provider source modifications.

The experiment:
1. Creates a verified disposable B37-C/B29 SQLite fixture, seals the
   unchanged G fake request, marks B37-C \`SUBMISSION_UNCONFIRMED\` and
   records B38-I one-use fake launch claim.
2. Uses unchanged S1 \`build_command\` and its trusted system Bubblewrap to
   start a **fixed** synthetic heartbeat loop inside the isolated PID/network
   namespace. No model, endpoints, credentials or arbitrary command.
3. Parent observes an actual marker written under S1's permitted scratch
   mount while the bwrap wrapper's OS process remains alive.
4. Parent commits B29 \`CANCEL_PENDING\` while the fake child is running;
   then SIGTERM's the **owned** process group and calls \`wait()\` with a
   strict timeout, with fail-closed clean-up on unexpected outcomes.
5. Parent observes OS wait/reaping of bwrap and unchanged scratch heartbeat
   across an additional interval. This is evidence of the *observed wrapper
   terminating and heartbeat quiescence*, **not kernel certification of all
   possible sandbox descendants**, a trusted OS service receipt or
   independently authenticated provider stop.
6. B29 budget remains held, no B33 observation or mock usage settlement
   is created. Reopening SQLite retains the B38-I fake claim,
   \`CANCEL_PENDING\`, and no retry.

The new helper records \`real_stop_verified=false\`,
\`authenticated_peer=false\`, \`independent_b33_witness=false\`,
\`production_ready=false\` even when its wrapper stop test passes.

## HOW TO USE

Review the GitHub draft B38-K PR and raw CI logs. No local Fedora/PX
installation, real Hospital assignment, actual model or provider secret.

Only in a disposable Linux test checkout:

    python3 -B tests/test-pxd-exec-s3-b38k-running-fake-child-stop.py --unit
    python3 -B tests/test-pxd-exec-s3-b38k-running-fake-child-stop.py --smoke

## VERIFY

- No B38-I claim, pre-cancel and pre-revoke refuse before OS launch.
- Real Bubblewrap fake child starts and generates a visible scratch
  heartbeat while OS wrapper is running.
- B29 cancel commits while the fake child runs; process-group SIGTERM,
  host OS wait and heartbeat quiescence must all be observed.
- Second stop is refused; no automatic restart or claim replay.
- After reopening disposable SQLite, the prior B38-I claim persists,
  held fake budget and \`CANCEL_PENDING\` remain.
- Missing trusted S1 binary refuses before process spawn; zero fallback.
- No B33 observation, real transport, credential or real-stop
  certification from child-controlled text.
- All B38-J/I/H/G/F/E/D and B37/B38 regressions, B34 baseline and
  integration, grammar validation run on GitHub merge checkout.

## WATCH OUT FOR

**This experiment is NOT a production stop protocol.** A trusted
external supervisor can know that it reaped an OS process it created,
but the marker is a child-controlled file and its quiescence is not a
kernel-authenticated proof that every isolated descendant stopped.
The wrapper may reap before actual nested process termination; no
external pidfd/cgroup/S1 descendant attestation exists here.
A post-claim cancel can still race physical child spawn and no
production-safe non-bypassable sender gate has been added.

The test module's S1 script has a bounded heartbeat lifetime and is
synthetic code under the existing accepted isolate; it is not
the B38-E fake model script. B38-G's unchanged actual fake model
exchange is still covered by inherited OS smoke.

The fake claimant, database and synthetic binding are same-UID test
fixtures, not authenticated Hospital actors. No B33 independent remote
observation, real credential boundary or authorized provider dispatch.
B24 REAL_PROVIDER_DENY / EXEC-S3 PRODUCTION HOLD remain enforced.

## CHECKLIST

- [x] Verify B38-J merged into current main and no existing B38-K work.
- [x] New isolated running fake-child stop harness, workflow, contract.
- [ ] Exact-head OS smoke, new unit and inherited regressions PASS.
- [ ] Nurse 2 independent security review of actual stop evidence and
      remaining nested-descendant/launch-race uncertainties.
- [ ] Operator explicit acceptance and merge authorization.
- [ ] Future trusted external launch/stop worker and independently
      authenticated B33 outcome observation; no production approval.

## NEXT

Run CI, correct only B38-K new files if needed, and preserve
exact-head review pointers. The next production-oriented research must
identify real OS process-tree custody (pidfd/cgroup) and authenticated
external observer capabilities before any claim of real stop/settlement.

## DECISIONS

Conservative fake OS proof: attest only to wrapper process reaping and
heartbeat quiescence, not certified child stop or independent B33
delivery. Preserve historical B38-H/I/J accepted checkpoints.
New PR draft and unmerged until separate operator acceptance.
