# PX EXEC-S1 // Offline execution isolation fixture

**State:** development-only, awaiting independent review. **Production HOLD.**

EXEC-S1 distinguishes this *new execution-isolation stage* from previous Hospital S1 and Doctor succession stages.

## Scope and boundary

This test harness uses rootless Linux Bubblewrap with an explicit environment and mount allowlist. The sandboxed Python probe sees read-only system /usr, a read-only synthetic /patient, writable disposable /scratch, a private /tmp, isolated /proc and /dev, and empty /home and /var. Host login files, SSH keys, Codex auth, GitHub credentials, Hospital databases and runtime sockets are not mounted. The network, PID and user namespaces are unshared.

The parent passes only FAKE credential values and synthetic canary paths. The child must not inherit them or read their host files. Neither PX, Codex, Hermes nor a production Hospital DB is launched or accessed. The existing PX command guards remain unchanged. This is not an authenticated provider runtime or a sandbox certification.

## Use

On a Linux system with unprivileged user namespaces and Bubblewrap installed, use these commands from the dedicated EXEC-S1 branch:

    python3 -B tests/test-pxd-exec-s1-isolation.py --unit
    python3 -B tests/test-pxd-exec-s1-isolation.py --smoke

The unit suite tests policy construction, symlink and invalid mount refusal, credential environment omissions and failure when Bubblewrap is unavailable.

The smoke suite creates a private temporary fake Patient, writable scratch and fake secrets. Its probe checks Patient read permitted, Patient writes denied, scratch write permitted, fake private token and auth file hidden, poisoned parent environment scrubbed, host-only paths hidden, network namespace different and direct IPv4 network connection unavailable. The harness deletes its disposable fixture when done. It never runs real providers or asks for secrets.

If Bubblewrap is missing, user namespaces are blocked, or any check fails, the test returns a nonzero exit status and **does not fall back** to unrestricted execution. The separate GitHub workflow runs tests on a disposable CI host; that does not substitute for Fedora operator-machine verification.

## Remaining security gates

- EXEC-S1 (authorized): offline fixture, fail-closed negative tests and Nurse 2 independent review.
- S2 (HOLD): protected authentication and model client versus tool process separation.
- S3 (HOLD): integrate enforcement with PX provider launch and resume plus audit.
- Production (HOLD): requires separate operator acceptance; no merge, installation, live DB writes or provider settings changes are implied.

**Review proof:** check mount map, environment allowlist, synthetic canary non-disclosure, network denial, read-only Patient and writable scratch. Interpret PASS only within the exact tested environment.
