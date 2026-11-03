# PX EXEC-S3 // B38-F Actual B38-E Fake Sender in Disposable Linux Sandbox

> STATE // DRAFT · OFFLINE · STACKED ON B38-E PR #117 · REVIEW PENDING  
> PATIENT // The-Post-Apollo-Dev-Exp  
> ROOM // Hermes Integration Security (external Hospital-compatible; NOT live registered)  
> STAFF ROLE // PXD continuation, bounded implementation  
> ASSIGNMENT // B38-F: run the exact B38-E fake sender subprocess inside accepted S1 sandbox and observe real child boundaries  
> PARENT // PR #117 head 831a36792f1bd3dc55c48274b703b7d295f5f068  
> SECURITY // B24 REAL PROVIDER DENY · EXEC-S3 PRODUCTION HOLD

## IMPLEMENTATION

This is a **stacked, test-only** continuation, not a change to the default
B38-B sender or the B37-C durable admission owner. Three added files only:
a disposable Linux B38-F probe, dedicated GitHub Actions workflow, and this
contract. The existing B38-E source, B38-D S1/Bubblewrap fixture, B37-C,
and production launcher remain untouched.

The host test creates only synthetic Patient / scratch / private directories,
copies byte-identical source modules from the B38-E checkout to a disposable
Patient mount, and keeps a **fake** credential file in a host-private directory.
It invokes the previously accepted EXEC-S1 root-owned /usr/bin/bwrap command
with --unshare-all, --clearenv, no host root mount, read-only /patient and
writable scratch. There is no unrestricted fallback when Bubblewrap fails.

**The actual unchanged B38-E fake model-only sender** is launched by a
test-only supervisor *inside that sandbox*, not merely a different disposable
tool process. B38-E itself continues to construct a synthetic sealed B37-B
tool-free request, generate a disposable 32-byte fake HMAC key, send it through
an inherited pipe FD, and verify the fixed signed response with child PID,
nonce, identity and exact response schema. The test-only supervisor inspects
the live child before supplying its fake key. The child is blocked on that key
pipe during observation.

The kernel probe checks:
- Outer net and PID namespaces differ from the host; child inherits those
  namespaces and has a distinct live PID and expected parent.
- Child's launch path and environment are exact; close_fds and pass_fds
  permit the inherited fake-key pipe, not arbitrary host descriptors.
- The child's /proc FD targets exclude the host fake credential; environment
  excludes host API, runtime, database and GitHub canary values.
- Host private directories, /run/user and Hospital fixture path are hidden;
  Patient source mount is read-only; scratch is writable.
- A direct IPv4 connection fails inside the network namespace.
- Signed B38-E mock receipt is well formed, fixed synthetic text only, zero
  model/tool/network calls and **all production flags remain false**.

The parent strictly validates all expected observation keys and literal
true booleans and checks post-run disposable fixture invariants.

## HOW TO USE

Review the B38-F draft PR and its GitHub Actions "b38f-sandboxed-fake-child"
job. It installs Bubblewrap on a disposable Ubuntu 22.04 runner only.

The test commands (for CI, not requested on operator Fedora):

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38f-sandboxed-fake-child.py --unit
    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b38f-sandboxed-fake-child.py --smoke

The workflow additionally runs B38-E, B38-D and B37/B38 security regressions
on the exact generated PR merge checkout. This PR is stacked on the specific
B38-E branch because #117 was **open, draft and unmerged** at preflight.

## VERIFY

Required for this bounded B38-F checkpoint:
- GitHub generated PR merge checkout SHA and exact base/head in CI logs.
- Unit evidence that missing trusted bwrap fails closed, exact expected
  boolean-key schema is enforced, accepted launcher flags remain present.
- Actual child PID, inherited namespace and inherited fake-key FD
  observed live, then B38-E HMAC/nonce/PID verification succeeds.
- Host private fake secret, env, writable path and direct IPv4 isolation
  observed without real secrets or provider endpoints.
- Existing B38-E and merged B37/B38 parent test suites pass.
- Independent Nurse/security review and operator final acceptance pending.

## WATCH OUT FOR

**Scope limit:** The host launches a Bubblewrap sandbox that contains BOTH
the test supervisor and the actual B38-E fake sender. This proves the fake
model subprocess can operate in the accepted sandbox. It does **not** yet
prove an outside trusted supervisor can securely communicate with a separately
confined model-only child, nor an authenticated Unix peer, a private UID/cgroup,
production-level egress control, an independently guarded real credential,
or reliable process attestation against a malicious same-UID sandbox owner.
The child is still mock-only, and its B38-E receipt intentionally reports
sender_os_isolated=false rather than claiming certification.

The network test is direct IPv4 denial inside a network namespace, not a
formal exhaustive egress proof (IPv6/Unix sockets/FD injection must later be
addressed). The parent inspect hook observes the child after spawn and before
fake-key delivery, which is a test seam, not a production supervisor.

**B38-E remains independent of B37-C's durable SQLite submission.** A fake
IPC reply is not a Hospital Doctor turn or an authorization to transmit.
The production B24 deny and EXEC-S3 hold remain unconditional. No real
provider calls, SDK, credentials, native tools, Fedora changes, live Hospital
registration, production activation, or merge are part of this assignment.

## CHECKLIST

- [x] Recheck GitHub main, Syntagma, current PR #117 and B38-D #116.
- [x] Preserve unmerged #117; open separate stacked B38-F branch.
- [x] Add test harness for unchanged B38-E inside actual S1 Bubblewrap.
- [x] Add live PID/FD/mount/net observations, fail-closed static checks.
- [x] Add PR CI and preserve parent security regressions.
- [ ] Inspect actual GitHub CI outcomes and fix any errors.
- [ ] Independent security review.
- [ ] Operator acceptance / approved merges.
- [ ] Separate trusted outside supervisor vs sandbox child IPC boundary.
- [ ] B37-C durable authority integration with owner coordination.
- [ ] Real provider and production admission (not authorized).

## NEXT

Once the stacked B38-F disposable CI passes, review its exact source and
kernel observations. Follow with an explicitly scoped host-supervisor-to-
sandboxed-child IPC milestone, including a trusted peer identity and durable
submission coordination with the B37-C owner. No real provider enablement.

## DECISIONS

Option A remains selected; B38-E and B38-D are preserved unchanged.
B38-F is a narrow offline security proof, not a new policy or live Hospital
authority. The external ChatGPT Proxy Doctor is only Hospital-compatible.
Final operator DONE and any merge decision remain separate.
