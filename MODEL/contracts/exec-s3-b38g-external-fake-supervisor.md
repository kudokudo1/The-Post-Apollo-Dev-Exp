# PX EXEC-S3 // B38-G External Fake Supervisor and Sandboxed Model-Only Child

> STATE // DRAFT · OFFLINE FAKE-ONLY · INDEPENDENT REVIEW PENDING  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // Hermes Integration Security  
> STAFF ROLE // PXD (external Hospital-compatible, NOT live registered)  
> ASSIGNMENT // B38-G: trusted fake supervisor on host, B38-E synthetic handler inside EXEC-S1 Bubblewrap  
> BASE // main 09538dbd9afe05480da09a38aa018ab5fa97de46 after merged B38-E #117 and B38-F #118  
> SECURITY // B24 REAL-PROVIDER DENY · EXEC-S3 PRODUCTION HOLD

## IMPLEMENTATION

B38-E's one-shot signed fake model-only IPC was previously exercised in a
separate Python subprocess without sandboxing (#117), and inside a Bubblewrap
sandbox *alongside* its test supervisor (#118). B38-G tests the **missing
cross-boundary topology**: a supervisor that stays **outside** Bubblewrap
handles the sealed fake B37-B request, B38-C fake-policy checks, disposable
HMAC key, nonce, signed reply verification and process lifecycle. The
sandboxed process executes the actual unchanged B38-E \`child_main\` handler,
loaded from byte-identical read-only copies of its existing code/dependencies.

New files only:
- \`tests/test-pxd-exec-s3-b38g-external-fake-supervisor.py\` contains an
  explicit test-only host supervisor, a fixed bwrap child entry snippet,
  positive/negative cross-boundary smoke, and fail-closed unit tests.
- Dedicated CI workflow runs B38-G + B38-F + B38-E + B37/B38 regressions.
- This durable checkpoint contract.

The host invokes the **same accepted EXEC-S1** root-owned \`/usr/bin/bwrap\`
launcher from \`tests/test-pxd-exec-s1-isolation.py\`: PID, network, mount,
user and other namespaces; read-only \`/patient\`, writable scratch, private
tmpfs, cleared env, no mounted host home, and \`--die-with-parent\`.
There is no less-restricted fallback and no change to that launcher.

The original B38-E \`child_main(fd)\` needs a key on a separate readable FD.
Bubblewrap deliberately closes unexpected inherited FDs as it enters the
sandbox. Rather than weakening its FD policy, B38-G uses the documented
\`--perms 0400 --file FD /tmp/b38g-fake-key\` setup operation: Bubblewrap
consumes exactly one **32-byte synthetic key** from a pipe passed to bwrap
with \`close_fds=True, pass_fds=(read_fd,)\` and creates a private read-only
file in the sandbox's tmpfs. The isolated Python child opens that file as
its own FD and calls the **unchanged** B38-E \`child_main(fd)\`.

That fake key is not a provider credential. It must not be reused beyond
this disposable exchange, and it is necessarily accessible to the
untrusted child: the HMAC is a **synthetic protocol-integrity exercise**,
not independent production peer identity proof.

The actual signed B38-E request flows through stdin, the signed reply
through stdout. The host requires a single clean child exit, the exact
B38-E schema, 128-bit nonce, client request identity, fixed synthetic
text and verified fake HMAC. It expects sandbox-local PID 2 under
EXEC-S1's standard bwrap PID 1 reaper, **not** the host's bwrap PID.
Timeouts kill and reap the sandbox; all errors use sanitized reason codes.
No shell, HTTP, SDK, provider URL, credentials, native tools, local Fedora
modification, Hospital connection, or B37-C ledger mutation occurs.

The child starts with fixed negative checks for distinct PID/network
namespaces, hidden host fake secret, hidden runtime/DB paths, scrubbed
credentials canaries, private cwd/home, read-only Patient mount, writable
scratch, direct IPv4 refusal, no unexpected inherited FD, and private
fake-key file permissions. Those self-checks fail closed before the
B38-E handler executes. The parent independently checks post-child
fixture invariants.

## HOW TO USE

Review the B38-G draft PR and its dedicated GitHub Actions job, which
installs Bubblewrap only on a disposable Ubuntu runner. No operator Fedora
tests or installation are requested.

Test-only commands:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38g-external-fake-supervisor.py --unit
    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38g-external-fake-supervisor.py --smoke

The smoke performs a real sandboxed positive exchange, wrong-key
negative and altered signed-frame negative, and checks fixture integrity.
The CI workflow also runs the existing B38-F/B38-E/B37 suites.

## VERIFY

Acceptance evidence for bounded B38-G:
- Exact generated PR merge SHA, head and base recorded in CI logs.
- New B38-G units, actual positive OS sandbox exchange, wrong-key and
  tampered-frame denials, byte-identical staged B38-E source.
- A real trusted **outside** supervisor cannot read child-only paths as
  authority and does not inherit a live Hospital or provider credential.
- The child exercises original B38-E \`child_main(fd)\` and authenticates
  only a synthetic signed request; fixed signed reply verified by host.
- No host-canary mutation, no Patient source mutation; scratch-only proof.
- B38-E/F and B37/B38 regression suites remain green.
- Independent Nurse 2 security review, operator acceptance and any merge
  authorization remain separate.

## WATCH OUT FOR

This is a **test topology**, not production-model isolation certification.
The direct child observation checks execute *inside the fixed test process*;
they are not trusted, adversary-resistant OS attestation of a malicious
model. The parent knows only which pinned bwrap command it launched, what
the sandbox process returned and its exit status; in-sandbox PID 2 alone
does not authenticate a host PID/UID/peer. A compromised child possesses
the disposable fake HMAC key, so HMAC does NOT prevent that process
forging its own reply. A future real model needs stronger process identity,
independent host-side kernel evidence, credential broker/least privilege,
and exhaustive egress/proc/socket/FD tests.

This milestone uses a **private temporary key file** inside sandbox tmpfs
rather than B38-E's original inherited private pipe FD across the
boundary. The key transits a setup pipe into bwrap, then the child opens
its isolated ephemeral copy. Real secret storage is not yet authorized.
The environment's fake canary variables are not real credentials.

The accepted EXEC-S1 profile is a disposable harness only. Network
evidence checks one direct IPv4 destination, not complete egress.
The B38-G test-only supervisor does **not** call the B37-C durable
SQLite submission or crash-recovery ledger, and cannot act as a Doctor
or admit a live Hospital turn. No provider, credentials or production.

## CHECKLIST

- [x] Confirm PR #117 and #118 merged into main at 09538dbd...
- [x] Check Syntagma Hospital protocols, B38-E/F and S1 source.
- [x] Preserve B38-E runtime and S1 launcher byte-for-byte.
- [x] Add test-only host/outside ↔ sandbox/inside single-use fake exchange.
- [x] Add wrong-key/tampering/fail-closed and source boundary tests.
- [x] Add disposable-runner CI and continuity contract.
- [ ] Verify GitHub CI and repair any B38-G failures.
- [ ] Independent Nurse 2 audit.
- [ ] Operator final acceptance and merge decision.
- [ ] B37-C durability/admission integration with owning worker.
- [ ] Real provider credential/sender admission (NOT AUTHORIZED).

## NEXT

After CI and independent review, develop an explicitly scoped trusted
host-side launch/identity attestation and credential-broker design before
any real model. Separately coordinate a durable B37-C mock admission
handshake, with replay/uncertain-outcome handling owned by B37-C.

## DECISIONS

Option A remains selected. B38-G is a strictly offline independent
integration seam; no modifications to production launcher, provider
configuration, running Fedora, or live Hospital. B24 provider DENY and
EXEC-S3 production HOLD remain unconditional. A green technical review
never silently becomes the operator's final DONE or merge approval.
