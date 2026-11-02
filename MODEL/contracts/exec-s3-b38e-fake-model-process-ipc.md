# PX EXEC-S3 // B38-E Separate Mock Model Process and Signed IPC

> STATE // DRAFT · OFFLINE FAKE-ONLY · INDEPENDENT REVIEW PENDING  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // Hermes Integration Security (external Hospital-compatible; not registered live)  
> ASSIGNMENT // B38-E: prove separate process + test authenticated one-shot *synthetic* supervisor IPC  
> BASE // main `20a1f0e43f583a18fb40f94d281c6f5da0661af2` after B38-D #116  
> SECURITY // B24 REAL_PROVIDER_PRODUCTION_HOLD · EXEC-S3 PRODUCTION HOLD

## IMPLEMENTATION

**Purpose:** Move from an in-memory mock sender into two actual
processes (test supervisor + fake model-only child) on disposable
GitHub CI, without actual credentials, provider HTTP, tool dispatch,
live Hospital authority, or modifying the operator's Fedora machine.

`bin/px_s3_b38e_fake_process_ipc.py` has two distinct paths:

1. The offline supervisor checks the existing B37-B exact sealed
   tool-free bytes and B38-C immutable **mock policy shape** against
   caller-supplied synthetic Room/Patient/Assignment/Bed/turn/generation.
   It creates a fresh 32-byte random **fixture HMAC key** and
   independent 128-bit nonce for one request.
2. The supervisor spawns an actual separate Python process using
   `subprocess.Popen` with a fixed executable/script, `shell=False`,
   sanitized explicit environment, `close_fds=True`, two bounded
   stdio pipes and a narrowly inherited **private pipe FD** for the
   fake HMAC key. The fake secret is not placed in argv, environment,
   model prompt, stderr or response body. Timeout kills and reaps the
   child. The child receives *no* PX broker address or tool grant.
3. The child verifies an exact versioned canonical JSON frame and
   HMAC over nonce, request ID, scope digest and **the exact sealed
   request bytes** (base64 in the fake IPC body). It independently
   validates the B37-A request shape: fixed fake model,
   `tools: []`, `tool_choice: none`, no extra keys, strict budgets.
   Unknown, tool-capable or unauthenticated frames refuse.
4. The child returns exactly one fixed, prewritten **fake text**
   response, signed under the same disposable key and including its
   observed PID. The supervisor verifies MAC, nonce, request identity,
   expected child PID, schema, text, and complete clean exit.
   No arbitrary tool callback, SDK, network endpoint, or dynamic
   model-generated content is accepted.
5. A frozen `FakeProcessReceipt` explicitly reports zero real
   provider/model/tool/network calls, with `sender_os_isolated: false`,
   `credential_isolation_certified: false`, and production false.
   `require_real_sender` unconditionally refuses.

**This is a separate process and cryptographically signed fixture
protocol, not authenticated production IPC.** The "key" is known
within the trusted test supervisor and child. It does not bind a
trusted Unix peer UID, independently attest child executable,
protect against same-UID/process compromise, or create an
isolated credential-bearing model sender. An adversarial child that
holds the key can sign arbitrary responses, so exact response
content and tool-free schema are also checked by the parent.

### Deliberate separation from the default mock sender

B38-E is a **new standalone fake process exchange**. It validates
B37-B's sealed bytes and B38-C's plan, but does NOT call
B38-B's `send_mock` or B37-C's atomic ledger transition.
This means its subprocess result **cannot be treated as an
authorized Hospital Doctor turn or even a B37-C mock submission**.
Production-style process lifecycle + atomic authority integration
is later work, with B37-C owner coordination.

### Remaining security boundary

The child in this milestone is a separate normal Python process,
**not** under Bubblewrap, cgroup or a dedicated UID. It is not
independently OS-confined. The B38-D disposable S1 Bubblewrap
tool child is a *different* fixture. B38-E does not claim its
isolated OS properties apply to this process. The supervisor's
sanitized environment and FD inheritance are useful hygiene,
not proof of filesystem, network or arbitrary Python execution
confinement. No real credentials or model endpoint are permitted.

## HOW TO USE

Review this PR's dedicated GitHub Actions run. Its offline test command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38e-process-ipc.py
```

CI also runs the existing strict B38-B sender policy, B37-C atomic
regression, B38-A/B/C, B37-A/B and B38-D static tests. Running
the helper in child mode directly is not a user-facing action.
There is nothing to install or run on Fedora.

## VERIFY

Required evidence for this bounded milestone:

- At least one **actual separate process** with non-parent PID,
  signed request/response, and bounded stdout/exit behavior.
- Wrong fake key, forged or changed MAC, request data tampering,
  bad version and schema, duplicate keys, unsafe tool-capable
  payload, extra endpoint, invalid base64, replayed nonce, wrong
  child PID and tool-looking response denied.
- Stale caller-supplied binding or forged seal refuses *before
  child launch*. No real provider send exists.
- Fixed environment allowlist, no real credential in argv/env,
  no network/client/tool-dispatch imports in this source.
- All parent B37-C and B38-B policy cases remain passing.
- CI run provenance includes exact generated checkout and head/base.

## WATCH OUT FOR

- **No OS sandbox for this fake sender yet.** This is intentionally
  more realistic IPC, not ready-to-run actual provider isolation.
- A shared HMAC key transported via FD is not an actual provider
  credential. This code is not suitable for production auth. Separate
  process peer identity and lifetime checks are not yet robust
  enough for an adversarial host.
- Replay resistance is only single-request process lifetime, fresh
  nonce/key, and parent verification. There is no persistent
  replay ledger in B38-E and no B37-C atomic submission integration.
- Tool-free JSON is still *data*; do not treat text suggesting a
  shell command as a tool request.
- No host Fedora, Hermes, provider config or live Hospital modifications.
- B38-B strong policy gate from merged #114 and B38-D's #116
  fake OS evidence must remain intact; this PR adds new files only.

## CHECKLIST

- [x] Rechecked main, Syntagma authority, open PRs and B38 ownership
- [x] Added single-use fake-key separate process sender fixture
- [x] Added signed request/response negative tests and CI
- [ ] Exact GitHub generated merge checkout test pass
- [ ] Independent Nurse/Head Nurse source/security review
- [ ] Operator final acceptance and merge authorization
- [ ] OS-confine **actual** sender process with fake key
- [ ] B37-C atomic submission and supervisor identity integration
- [ ] Real provider authentication (not authorized)
- [ ] Production admission (HOLD)

## NEXT

Review the IPC fixture as a true separate-process stepping stone,
then design a **disposable OS-confined fake sender process** with
independent kernel/FD/network observations, authenticated peer
identity, and a B37-C coordinated identity/commit interface.
Real provider/auth, any local machine installation, live Hospital
registration, and production activation require separate explicit
authorization.

## DECISIONS

Option A remains selected. This PR does not modify `bin/px-agent`,
the real Hermes installation, B37-C, existing B38-A/B/C/D, or
any authentic provider endpoint. H11.5 and compatibility PR #112
remain independent. CI passing is technical evidence, not live
authorization or final operator acceptance.
