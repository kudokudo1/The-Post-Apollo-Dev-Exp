# PX EXEC-S3 // B36-H6 Fedora Read-Only Host Suitability Inventory

> PATIENT // The-Post-Apollo-Dev-Exp
> ROOM // PX Doctor Execution Security (external Hospital compatibility, not live registered)
> ASSIGNMENT // B36-H6: scope and verify opt-in read-only OS inventory
> BASE // H5 merged main 2c39e8467e5ec9007ecef567981b96fbd5e179fa
> STATE // DRAFT · GITHUB SOURCE/FAKE-CI ONLY · NO LOCAL FEDORA EXECUTION
> PRODUCTION // HOLD

## IMPLEMENTATION

H5 demonstrated on GitHub Linux runners that start_new_session/process-group killing can stop a same-group fake worker but cannot guarantee a setsid-escaped descendant has stopped. H5 established **neither** Fedora suitability **nor** real Hermes execution isolation.

H6 adds bin/px_s3_b36_h6_readonly_host_inventory.py as a **no-secrets, fixed-source, opt-in** read-only diagnostic. Its CLI is inactive by default and only starts an inspection with the exact --host-readonly flag. CI **never** enables the real-host inspection. No subprocesses, OS signals, service calls, sockets, network connections, writes, package changes, provider calls or Hospital access.

At an operator-authorized later use on Fedora, H6 would read ONLY this fixed OS list:
- /proc/self/mountinfo, /proc/self/cgroup and /proc/self/status to identify cgroup v2 mount/membership and process-local NoNewPrivs/Seccomp state.
- /sys/fs/cgroup/cgroup.controllers to list **allowlisted controller names**. This does not attest cgroup delegation or the ability to create/kill a dedicated unit.
- /proc/sys/kernel/unprivileged_userns_clone and /proc/sys/user/max_user_namespaces. Missing flags are UNKNOWN, not DENY or ALLOW.
- /sys/fs/selinux/enforce and /etc/os-release to report current SELinux enforcing flag and whether the OS identifies as Fedora Silverblue. Neither proves isolation.
- /proc/self/ns/{user,mnt,pid,net,cgroup} via readlink, reporting presence only, NOT namespace IDs nor whether a future worker is actually isolated.
- Fixed executable metadata for /usr/bin/bwrap, /usr/bin/unshare, /usr/bin/systemd-run and socket-type metadata for /run/user/<current-uid>/bus. Presence is not verified tool behavior or a working user service manager.

**No user home, ~/.hermes, config.yaml, state.db, token, provider session, SSH agent, environment dump, process list, other PID procfs entry, or user-supplied arbitrary path is inspected.** No raw contents, actual paths, PID, UID, hostname, environment, mount source, namespace identifier or exception strings are emitted. Output has only allowlisted flags, known controller labels and fixed refusal codes. Each input source is read with a bounded size and errors become UNKNOWN.

The parser accepts untrusted synthetic snapshots during CI, and even a synthetically perfect snapshot always reports DENY. Notably, existing process Seccomp mode, cgroup v2 mount, SELinux enforcing and tools being installed do **not** certify model-only Hermes, native tool denial, an isolated credential plane, direct gateway STOP_ACK or complete descendant teardown.

## HOW TO USE

**Current approved scope: review PR / CI only. No user action on Fedora.**

After the operator separately reviews and explicitly approves the exact read-only local inspection, the command to consider is:

    PYTHONDONTWRITEBYTECODE=1 python3 -B bin/px_s3_b36_h6_readonly_host_inventory.py --host-readonly

The command requires the new source to be present in an approved checkout first. That would be a **separate local filesystem change approval** if it modifies the host. Nothing in H6 runs this command for the operator, copies scripts to Fedora, or edits the local checkout. Without the flag, the CLI refuses and performs zero host reads.

CI only runs a synthetic snapshot and fixed-path access contract test:

    PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b36-h6-readonly-host-inventory.py

## VERIFY

29 H6 fake-only tests cover positive and missing/UNKNOWN observations, literal fixed host source allowlists, cgroup and namespace parsing, userns sysctls, Fedora variant, SELinux flag, tool metadata, bounded untrusted content, cyclic/hostile payloads, malformed input, no raw data echo, exact opt-in refusal and mocked read-only collector. All tests mock collection or use injected fixtures. **No real process or Hermes is launched in H6.**

Current main CI total after H5 is 441. Expected PR integration: **470/470** (H6 29 + H5 13 + H4 41 + H3 28 + H2 26 + H1 23 + B35 22 + B34 14 + B24–B33 274). Historic baseline remains **274/274** by the existing workflow contract. Actual CI counts, the exact tested merge checkout, and all grammar checks must be independently verified.

## WATCH OUT FOR

- **Read-only does not mean attested.** /proc and /sys data describe the inspection process and ambient machine only. They do not prove a future Hermes process is under a dedicated cgroup/namespace.
- **Missing vs absent vs present must remain distinct.** UNKNOWN observations are not proof a capability is disabled. True flags merely suggest possible host support.
- **No tool dispatch ownership.** H6 does not prove that Hermes can run with every native tool path removed; the installed user's original Hermes gateway remains outside PX control.
- **No process tree or gateway API probe.** H6 cannot prove that Hermes has a turn-specific authenticated stop channel or that startup/reconnect recovery can be safely fenced.
- Fedora Silverblue rpm-ostree/Toolbox/Flatpak and a user-level systemd service may impose different namespace, cgroup delegation and SELinux constraints. Those must be assessed from later actual host evidence, not assumed.
- H6 does not change bin/px-agent, config/agent-providers.json, credentials, personal gateway, Fedora, or any live Hospital Room/Assignment.
- A successful GitHub CI test proves fixture parsing and collector restrictions, **not real Fedora suitability**.

## CHECKLIST

- [x] Reverify H5 merge and canonical source seams
- [x] Add inert-by-default fixed-source Linux inventory with safe diagnostic output
- [x] Add 29 offline malicious/UNKNOWN/access-confinement tests
- [ ] Independently verify CI, PR merge checkout and main baseline
- [ ] Independent security acceptance and operator-authorized PR merge
- [ ] Obtain separate explicit approval for any Fedora local script deployment
- [ ] Run approved Fedora read-only inventory and record only sanitized capability flags
- [ ] Determine a genuinely disposable cgroup/namespace owner and verify fake teardown
- [ ] Source-inspect Hermes STOP, auto-resume and native tool paths
- [ ] Only later consider explicit real-model/credential and production authorization

## NEXT

B36-H7 (proposed, separate authorization) should compare the **actual sanitized** read-only Fedora observation to available isolation mechanisms, then prepare a bounded disposable **non-Hermes** owner experiment. Only after separate local-write approval and verified cleanup should any fake local subprocess be launched. Inspect Hermes source API and all native tool channels independently, but do not restart the personal gateway, inspect credentials, or consider an authenticated model call until actual tool denial and STOP/cgroup teardown evidence exist.

## DECISIONS

DRAFT, unmerged, no local changes, no real provider/credential calls, and **production HOLD**. No automatic privilege, cgroup delegation, namespace, network or credential inference from inventory flags. Close PR to roll back this unmerged patch; a post-merge revert requires separately authorized change.

## RECOVERY / HANDOFF

H6 files: bin/px_s3_b36_h6_readonly_host_inventory.py, tests/test-pxd-exec-s3-b36-h6-readonly-host-inventory.py, this document. One offline test step is added to the existing B34-integrated workflow. Reacquire main and H6 PR HEAD before working further; other Doctor/Room PRs remain untouched.
