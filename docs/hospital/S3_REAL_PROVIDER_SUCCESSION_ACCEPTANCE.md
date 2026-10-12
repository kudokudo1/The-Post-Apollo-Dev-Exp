# Hospital S3 // Real Provider Doctor A → B Acceptance

**State:** operator-executed evidence harness; NOT yet a real-provider result or a final succession acceptance. P1 PR #62 and S2 PR #63 security/source acceptance stay independent.

## Purpose

Nurse 2 accepted PR #63 S2-01 source/CI work at commit f0346f92b2f2e20b841efff2d049d63caed4584e, but needs an actual new AI Doctor B answer. This runner creates an isolated test Hospital database and Git Bed, records a real Doctor A answer as a durable mixed-case HANDOFF, adds 40 newer ordinary reports and 11 higher-priority operator fixture Chart entries, and launches a fresh Doctor B provider session. It captures exact stdin sent to each provider process and actual returned answers. Another Room serves as a confidentiality negative control.

## Safety and explicit consent

The tool cannot be interpreted as an OS sandbox. Real providers might access other files or online tools available to the launching account. Use a constrained account/container and do not expose secrets to the fixture. Native provider account costs may apply. The runner uses a new disposable Hospital database; it does not edit installed Hospital data or merge a PR. Git identity is fictional and never fetched or pushed.

The script only supports configured real Hermes or Codex providers. It **never** runs a real provider in CI or in its default dry-run mode.

### No-write dry run

Run from an independent checkout containing this S3 branch:

    python3 tests/manual/doctor_succession_real_provider.py \
      --workspace "$HOME/s3-succession-demo-$(date +%Y%m%d)" \
      --provider hermes

Codex is also selectable with --provider codex. This prints the plan without creating the workspace.

### Explicit live-provider run (two actual AI turns)

The operator manually opts in only after inspecting the source, accepting provider access and making sure the destination directory does not already exist:

    python3 tests/manual/doctor_succession_real_provider.py \
      --workspace "$HOME/s3-succession-demo-$(date +%Y%m%d)" \
      --provider hermes \
      --timeout 600 \
      --execute --ack-provider-access

Choose a new nonexistent absolute workspace path. No cron, GitHub workflow, or connector automatically starts this.

## Evidence for Nurse 2

Generated workspace has private permissions (directory 0700; evidence files 0600):

- identity.json: checkout commit, Doctor A/B PX Session IDs, Room, Patient, Assignment ID, Bed path, branch, selected native provider
- turn-A.json / turn-B.json: the actual AI provider answers and native provider session IDs
- provider-input-A.txt / provider-input-B.txt: the exact stdin handed to each native provider, captured by an explicit local wrapper
- doctor-B-context-before-turn.json: B's separate context snapshot (the exact turn prompt is provider-input-B.txt, NOT this snapshot)
- result-summary.json: source handoff/Chart IDs, A/B provider-session distinction, prompt SHA-256 and initial automated assessment
- hospital-state/: isolated PX SQLite, including the original Room Report and Chart provenance
- bed/: a fresh fictional Git repository on the fixture branch

The script fails if a native provider ID or input capture is absent; if mandatory handoff/Chart source IDs are missing; if foreign Room evidence appears in B's prompt; or if Doctor B cannot recover marker, decision and next unfinished action. Such failures preserve partial evidence but are **not** successes.

Preliminary automated pass does not prove semantic understanding. Nurse 2 must independently read B's actual response, compare against source Report/Chart records and exact prompt, and confirm correct Room/Bed/branch, authority READ/TEST, denied EDIT/COMMIT/PUSH/INTEGRATE, unfinished checklist and provenance. A distinct B provider-native session ID is mandatory; it must not resume Doctor A's session. Historical content must be correctly interpreted, not merely quoted.

## Acceptance boundaries

The work still needs the operator's explicit choice to launch two real provider turns, independent Nurse 2 review of local evidence, and later installed-runtime/merge approval. The author has not launched a real provider from GitHub, nor edited the user's installed Hospital.

Do not post local evidence to GitHub before reviewing and redacting any sensitive provider output.

## HEAD NURSE .C / OPERATOR DECISION: CODEX SELECTED (2026-10-11)

Provider choice is **codex**. This does not authorize a real AI call, installation, merge, or any production Bed access. The project registry includes Codex as an option, but a project registry is not proof that it is installed or logged in on the operator's Fedora host.

Run the following *read-only checks in the same shell/environment that will execute the eventual provider*, whether that is Fedora host or Toolbox:

    command -v codex
    codex --version
    codex login status
    codex exec --help

Do not paste credentials, tokens or complete account output into a PR. The operator can share only whether each check passed and its installed Codex version. If Codex is not installed/authenticated, **stop**, without silently switching to Hermes.

A separate checkout/worktree of this **draft S3 branch**, rather than live installed PX, is required for the local exercise. Source-ref and runner instructions are in PR #64. Prefer an isolated user account/container because Codex read-only sandboxing constrains its tool actions but is **not** equivalent to process isolation; it may read accessible files and external provider usage may be metered.

The S3 runner explicitly overrides its private Codex provider registry with `codex exec --sandbox read-only -c approval_policy=never --json -`. This differs from the normal installed PX provider configuration and prevents accidental edits/elevation inside the synthetic exercise. The runner makes no network fetch or Git push on its own.

In the S3 checkout, no-write preflight (the workspace does not yet exist):

    test ! -e "$HOME/s3-codex-acceptance-evidence"
    python3 tests/manual/doctor_succession_real_provider.py \\
      --workspace "$HOME/s3-codex-acceptance-evidence" \\
      --provider codex
    test ! -e "$HOME/s3-codex-acceptance-evidence"

The expected JSON reports `mode: DRY_RUN_NO_PROVIDER`, `provider: codex`, `writesOnDryRun: 0` and `realCallsOnExecute: 2`. The dry run never validates actual local Codex login: perform the four local checks separately.

**Do not run the following command yet.** Once the operator *separately authorizes* actual provider execution after reviewing the prep results, the final real-provider command will be:

    python3 tests/manual/doctor_succession_real_provider.py \\
      --workspace "$HOME/s3-codex-acceptance-evidence" \\
      --provider codex --timeout 600 \\
      --execute --ack-provider-access

Use a fresh nonexistent workspace path, and preserve its entire private evidence folder for Nurse 2. A successful dry run or green CI does not establish that a fresh AI Doctor B understands Doctor A. Nurse 2 must examine the actual B answer with source report/chart IDs, provider identities and exact delivered stdin before acceptance.

S3 real-provider execution, merge and installed runtime remain **NOT AUTHORIZED**.
