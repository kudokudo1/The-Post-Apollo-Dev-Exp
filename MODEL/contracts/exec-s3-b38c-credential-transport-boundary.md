# PX EXEC-S3 // B38-C Credential Ownership and Transport Boundary

> STATE // DRAFT · OFFLINE SECURITY DESIGN + SHAPE TESTS · REVIEW REQUIRED
> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // Hermes Integration Security (external Hospital-compatible; not live attached)
> STAFF // Hospital-compatible browser Doctor, no verified formal staffing assignment
> ASSIGNMENT // Option A: separate PX model-only client, credential/process/transport boundary
> BASE // Stacked on B38-B draft PR #110, head 40844e2fb5dd9c4800450060a7d3e3b8a318cdc8
> NEIGHBOR // B37-C PR #109 owns atomic recovery; B38-A PR #108 remains separate
> OPERATOR // Approved continuation after B38-B, 2026-11-02
> PRODUCTION // HOLD · B24 REAL_PROVIDER_PRODUCTION_HOLD · NO REAL CREDENTIALS

## IMPLEMENTATION

Option A is selected: PX owns a dedicated **model-only sender**, without
loading native Hermes tool dispatch, delegation, browser, memory manager,
plugin/MCP hooks or the native CLI runtime. This B38-C increment is a
**pure offline policy-shape fixture plus architectural contract**. It cannot
authenticate, send network traffic, load keys, spawn a provider, or enable
production, and it does not modify any existing B37/B38 execution file.

New `bin/px_s3_b38c_transport_policy_fixture.py` defines one intentionally
inert, tightly bounded, exact-shape manifest, representing a pretend sender
topology, and two pure operations:

1. `prepare_fake_plan` checks the declared no-credential/no-process/
   no-network/no-broker configuration **and** the existing B37-B immutable
   request seal against a caller-supplied synthetic B29 authority binding.
   It copies the manifest to canonical immutable bytes and records only
   its SHA-256 and the safe sealed-request identifiers.
2. `recheck_fake_plan` requires the same policy bytes and request identity,
   rechecks the B37-B seal and synthetic binding, then returns an explicitly
   **non-authorizing** diagnostic. It never hands the plan to a transport.
3. `require_real_transport` permanently refuses. There is no real provider
   selection, endpoint resolution, TLS handshake, network connection,
   credential retrieval, FD inspection, OS sandbox, or IPC.

The fixed mock destination is `mock-model.invalid`, with transport
`IN_MEMORY_FIXTURE` and `tcpEnabled: false`. It is only a string inside
a manifest and must **never** be resolved or connected. Actual provider
endpoints, URLs, credentials and HTTP headers are forbidden by this fixture.
The allowable `environment.names` contain **names only** from LANG,
LC_ALL and TZ, never actual environment values.

**Critical interpretation:** the manifest is supplied by the test caller,
including every apparent security property. Matching it proves only that
the fixture input is well-formed. It is **not** OS evidence that any such
process exists or is isolated, that a secret is protected, or that an
external provider has been called. SHA-256 is not an authenticating signature.

### Proposed production trust ownership (NOT IMPLEMENTED)

```text
LIVE AUTHORITY SOURCE  ->  PX Supervisor / audit authority
                              |
                   exact request identity + grant
                              |
                              v
     TRUSTED MODEL-ONLY SENDER (separate process)
     - no native tool or delegate code
     - dedicated restricted runtime identity
     - receives only approved sealed bytes
     - credential source owned by sender, not tools
     - outbound network only via verified provider policy
     - no arbitrary local tool execution or broker socket
                              |
                              v
        PINNED PROVIDER ORIGIN / TLS (future only)
                              |
                 response bytes (untrusted)
                              |
                              v
             PX validation / persistence
                              |
                separately authorized tools
                              v
          PX broker -> disposable isolated worker
          NO model credential / NO tool egress
```

A process that holds model credentials is **trusted only for the narrowly
reviewed model-communication role**, not a general Doctor tool executor.

### Credential boundary requirements for a later real sender

- Sender runs under a dedicated identity/process/namespace with an exact
  versioned executable/dependency profile; no native Hermes CLI tool code,
  plugins, imports with side effects, general Python `eval` or shell path.
- Credentials belong only to the trusted sender. Do not include them in
  prompts, JSON tool requests, process argv, inherited host env, logs,
  exception strings, stdout/stderr forwarded to the model, tool mounts,
  or untrusted worker FDs/sockets.
- Define a separately reviewed credential-injection mechanism after the
  OS boundary is prepared (e.g. restricted inherited descriptor or trusted
  credential service). The exact mechanism is **undecided**; this fixture
  does not assume systemd credentials, keyring integrations or a real token.
- Restrict the sender's file system: no broad HOME, no foreign Room Beds, no
  tool writable directory, no ambient agent/SSH/desktop sockets. Close or
  explicitly map every inherited FD and verify through trusted OS
  observations, not model output.
- Neither a fake sentinel nor a `noToolSecret: true` assertion demonstrates
  confidentiality against malicious code in the same process.

### Network and transport boundary requirements (future only)

- Model provider origin must be a **separately approved, fixed allowlist**,
  binding hostname, scheme, port, request path, TLS name/certificate checks,
  allowed methods, request size and credential use. The exact provider/model
  selection is not chosen by B38-C.
- A real sender must reject redirects, environment proxy inheritance,
  unapproved DNS/address changes, userinfo-in-URL, dynamic endpoints,
  alternate ports, ambient socket use, and fallback transports.
  Enforce the actual egress policy outside the untrusted model process;
  checking a Python dict is insufficient.
- HTTPS alone does not constrain *which* hosts the process can contact or
  prevent local subprocesses. The sender must have no independent arbitrary
  egress or ability to launch unrestricted code.
- Keep response streaming parsers bounded with exact schema and size
  limits, reject non-text tool/provider-control events until a separate
  PX-owned proposal protocol is designed. B38-A uses **invented mock frames**
  and must not be treated as a real Responses API parser.
- Broker IPC is exclusively supervisor-owned. The model sender cannot
  access a broker socket or mint a grant. The eventual supervisor-sender
  IPC needs authenticated peer identity, versioning, limited messages,
  stale/replayed request rejection and fail-closed shutdown.
- Rate limits, spend reservation, idempotency and restart uncertainty
  must be coordinated with B29/B37-C's owning worker rather than creating
  a conflicting sender ledger.

### Stage A/B/C and recovery order (future only)

1. **A // Before persistence:** acquire trusted Hospital authority, exact
   Room/Patient/Assignment/Bed/turn/generation, provider profile, secret and
   network plans. Missing evidence or authority denies without sending,
   accepting a turn or writing the outgoing operator message.
2. **B // Still before persistence:** start and verify the restricted
   **tool broker** (when applicable) and the eligible model-only sender
   envelope using supervisor/OS observations, then atomically recheck
   live Assignment and pause/revocation generation. No model prompt leaves.
   Stop/reap failed startup with no unconfined fallback.
3. **C // Accepted turn:** commit accepted outgoing work and identity, then
   pass exactly the bound sealed bytes to the sender. A failure after
   acceptance records FAILED/UNKNOWN rather than silently deleting the
   message or replaying an unknown remote request.
4. At cancellation/revocation, prevent further requests, interrupt/reap
   workers, quarantine in-flight results, and reconcile ambiguous remote
   delivery with B37-C/B33. **Local SQLite cannot make network send atomic**.
5. Resume repeats A/B/C, never imports an arbitrary native Hermes session
   and never silently rebuilds a credential-bearing tool-enabled process.

### Negative acceptance matrix

| Future test | Evidence required | Current B38-C coverage |
| --- | --- | --- |
| Credential inaccessible to tool | Independent OS FD/env/mount/IPC inspection + sentinel negative | **Not verified**; mock manifest only |
| Model-only client cannot execute tools | Exact pinned client process with adverse import/tool/process tests | **Not verified**; no real client |
| No ambient network | OS firewall/namespace/proxy/DNS observations and adversarial egress attempt | **Not verified**; simulated flag only |
| Provider origin TLS/redirect | Real transport configured and OS-observed | **Not verified** |
| Bound request/authority | Trusted Hospital read + atomic check at last launch | B37-B synthetic validation only |
| Replay/duplicate after crash | Durable state + observed remote uncertainty, coordinated with B37-C | B38-B synthetic token, B37-C separate draft |
| Invalid policy field/secret leakage | No extra fields, real endpoint, credential source, network or native-tool claims | **B38-C tests only** |
| Live provider admissions | Independent review, pinned real sender, trusted auth and explicit operator approval | **DENY** |

## HOW TO USE

From a disposable checkout **of the B38-C stacked branch**, no environment
variables or API keys are required:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38c-transport-policy.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38b-trusted-sender-mock.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38a-model-only-mock-client.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37b-sealed-handoff.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37a-tool-free-contract.py
```

These test fixtures use no real provider, credentials, process launch, socket,
HTTP or live Hospital storage. Never enter an API key into their configuration.

## VERIFY

- Explicit exact typed fields, extra-field refusal, hard-coded offline
  destination, no network, proxy, redirect, native tool or broker access.
- Environment **variable names only**, no secret values, duplicate or
  non-allowlisted variables. Fixed safe diagnostics.
- Fresh immutable manifest bytes, recheck after caller mutation,
  request/seal hash/binding mismatches, and unconditional real transport denial.
- B37-A/B and B38-A/B regression checks on the same GitHub branch head.
- Static no-native/network imports for this module. Static inspection is a
  regression convenience, **not** a security guarantee.

## WATCH OUT FOR

- All claims about a "trusted" process in this milestone are hypothetical.
  A malicious same-process caller can forge plan data and tamper with Python
  objects. There is no trust boundary implemented by these tests.
- B38-B's fake credential sentinel resides in the same interpreter as the
  fixture; there is no real secret confinement.
- B37-C PR #109 is active in an adjacent lane. Do not modify its atomic
  recovery files, invent a competing ledger or skip remote-unknown state.
- B38-A PR #108 and B38-B PR #110 remain draft/unmerged at this branch's
  initial checkpoint. **This PR is stacked on B38-B**, not directly on main.
- No actual provider endpoint, credential storage mode, runtime OS
  isolation or authentication scheme has been selected or authorized.
- None of these tests certifies real Hermes, Codex or production security.

## CHECKLIST

- [x] Operator approved continued Option A work
- [x] Rechecked exact GitHub source and B37-C ownership collision
- [x] New B38-C offline manifest, negative tests, CI and review document
- [ ] Verify exact branch-head CI and independent audit
- [ ] Operator acceptance of this bounded fixture
- [ ] Owner-coordinated transport/recovery integration design
- [ ] Separately authorize real process/credential test and live sender
- [ ] Production admission (still HOLD)

## NEXT

Review the manifest's intentionally non-authorizing behavior and approve
the **separate OS/network threat-model proof plan**. Coordinate B37-C's
atomic recovery design before any actual sender. The real provider
authentication mechanism and first real endpoint remain decisions requiring
explicit authorization.

## DECISIONS

Option A remains selected. **B38-C implements only the no-network,
credential-free policy fixture and detailed future transport requirements.**
It does not modify any other worker's source, invoke Hermes, read
credentials, touch Fedora or Hospital, approve real transport, or merge PRs.
