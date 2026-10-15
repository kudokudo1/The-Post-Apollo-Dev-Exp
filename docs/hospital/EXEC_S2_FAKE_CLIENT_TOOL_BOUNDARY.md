# PX EXEC-S2 // Fake client vs isolated tool credential boundary

**STATE:** offline proof-of-separation candidate; no real Codex/Hermes execution or production acceptance. This EXEC-S2 is distinct from the historical Hospital S2 Doctor-continuity work.

## Objective and trust model

Demonstrate that a **trusted fake model-client parent** may read a synthetic authentication file while the **separate tool process** cannot. This is a synthetic boundary test, not an implementation of real Codex credential transport.

| Component | Access |
|---|---|
| Trusted parent and in-process fake model service | Random synthetic token in 0600 disposable credential file under private staging root; simulated authorization only |
| Trusted task gate | Allows only fixed READ_SYNTHETIC_PATIENT_AND_WRITE_SCRATCH; rejects shell text and arbitrary model-generated commands |
| OS-isolated tool child | Accepted EXEC-S1 Bubblewrap policy, read-only fake Patient, writable disposable scratch, no host private credential mount, private tmpfs, cleared environment, separate network namespace |
| Evidence validator | Requires exact expected result checks; denies false, incomplete, malformed or failed tool results |

The fake client, fake authentication service and task policy live on the trusted parent side. No provider token is passed into the tool's program, environment, arguments or filesystem mounts. An intentionally open fake credential descriptor exists in the parent during tool launch and close_fds=True prevents its inheritance; the child also checks its /proc/self/fd. The parent deliberately supplies *fake* hostile API variables to the Bubblewrap process, whose existing S1 --clearenv removes them in the child. **No real environment variables are copied from the machine.**

The fake model service is an in-memory stub, **not an authenticated network call or an actual Codex CLI process**. Passing this test does not establish a secure transport mechanism for ChatGPT-authenticated Codex, and it is not sufficient to certify real-provider isolation.

## Verify

Run from the separate EXEC-S2 development branch, with the accepted S1 file alongside S2:

    python3 -B tests/test-pxd-exec-s2-credential-boundary.py --unit
    python3 -B tests/test-pxd-exec-s2-credential-boundary.py --smoke

The ten unit tests check fake authentication and refusal, no missing/weak/symlinked credential acceptance, exact allowlisted tool action, no real inherited environment, absent token in fixed tool program, and rejection of forged/incomplete evidence. They do not require Bubblewrap.

The smoke test requires validated /usr/bin/bwrap and executes a real synthetic tool inside the accepted S1 sandbox, with random fake authentication in a disposable parent-only file. It verifies hidden fake secrets and inherited descriptors, cleared sensitive environment, read-only Patient, writable scratch, separate network namespace and unsuccessful direct IPv4 egress. It refuses if the sandbox cannot launch or any check fails. **There is no unisolated fallback.**

The CI job installs Bubblewrap only on a disposable GitHub runner, and uses no external model provider or actual credentials. GitHub PASS will apply to that CI environment only. Fedora-specific verification is a separate check.

## Boundary and acceptance

- **EXEC-S1:** existing merged and accepted offline launcher, reused *without modification*.
- **EXEC-S2:** this limited offline fake-client/tool separation test, pending independent Nurse 2 review. It proves only behavior observable in the exact fixture.
- **EXEC-S3:** PX dispatch + resume enforcement and real-provider integration, **HOLD**.
- **Live credential handling, real Codex/Hermes calls, PX executable modifications, live Hospital, merge, and production activation:** **HOLD**, requiring separate operator authority.

Nurse 2 review must examine both sides of the trust boundary, environment construction, close_fds, fixed task policy, S1 reuse, child negative assertions, CI evidence and explicit limitations. Document any limitation rather than treating a fake service as a certified authentication broker.
