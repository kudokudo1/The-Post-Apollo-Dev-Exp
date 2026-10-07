# PX // TERM EXP shell v0

This is the rebuilt terminal frontend for the current PX control plane.

It is intentionally **not** the old `feature/px-foundation` backend. The old
Ratatui work is donor material only. The living frontend reads the current
machine contracts:

```text
px actions --json
px tools --json
```

That keeps Hospital, GitHub, AI, workflows, and ordinary executable discovery
behind one source of truth.

## Open

```bash
px term
# alias:
px tui
```

Until the later installer/runtime lane installs a compiled `px-term-exp`
binary, `bin/px-term` launches the crate through Cargo from the runtime tree.

## v0 surface

The first shell proves:

- current PX action registry loads successfully;
- current host + Toolbox tool registry loads successfully;
- the live action/tool counts are visible;
- backend environments and readiness are visible;
- action categories are derived from the registry rather than hard-coded;
- representative semantic actions are rendered from the live registry;
- terminal raw/alternate-screen cleanup is guarded on exit.

The first interaction model is now live:

- `SPACE` opens a command/category menu;
- `/` opens Find Anything;
- leader and search selectors are independent;
- fuzzy search spans semantic PX actions and preferred host/Toolbox commands;
- narrow terminals stack the dashboard vertically instead of crushing the
  two-column layout;
- `q`, `Esc`, and `Ctrl-C` preserve clean terminal exit behavior.

Tool selection can now delegate a guarded specialist set:

- Lazygit;
- Neovim;
- btop;
- Zellij;
- fzf.

TERM EXP re-resolves the selected specialist through `px which --json` at
launch time, suspends raw/alternate-screen mode, runs the exact resolved
invocation, and restores TERM EXP when the specialist exits.

Find Anything now labels results by role:

- `ACTION` — a semantic PX capability;
- `SPECIAL` — an approved interactive specialist that TERM EXP can delegate
  to directly;
- `COMMAND` — an executable discovered on the host or in Toolbox. These are
  real programs, but TERM EXP does not pretend every low-level CLI is an
  interactive app.

Read-only PX actions are executable in TERM EXP. Actions with no arguments run
immediately and render their output in-app. Actions with arguments pass through
the same argument resolver used by mutation previews.

Mutation handling is deliberately staged:

- `read` actions execute immediately after argument resolution;
- `local` mutations resolve all arguments, freeze the exact PX command, show a
  preview, then require a second confirmation screen and the word `LOCAL`;
- generic `remote` and `external` mutations can resolve and preview their exact
  frozen targets but remain execution-locked unless the action declares a
  certified execution policy;
- Hospital fast-forward integration is a narrow remote exception:
  TERM EXP re-runs `px room <repo> <room> prepare`, requires its branch, Room
  HEAD, base, and base HEAD to match the frozen selection exactly, then asks
  for the explicit word `REMOTE` before calling the already-guarded
  `px integrate` contract;
- GitHub workflow-run cancellation is `px-guarded`: PX preflights the exact
  active run, TERM EXP freezes PX's target token, revalidates it immediately
  before execution, requires `REMOTE`, journals the cancellation request,
  and then asks PX to verify that the run reached `completed/cancelled`;
- GitHub workflow rerun is also `px-guarded`, but only for a completed run:
  PX freezes the run identity plus its current attempt number, TERM EXP
  revalidates that exact attempt before execution, and post-op verification
  requires the same run to advance to a higher attempt;
- GitHub workflow dispatch is `px-guarded`: PX resolves an omitted ref to an
  explicit ref, freezes its commit SHA plus the workflow file blob and the
  pre-dispatch run set, and supplies the canonical command TERM EXP will
  execute. Verification only passes when exactly one new matching
  `workflow_dispatch` run appears; zero or multiple candidates are reported
  as failed/ambiguous rather than guessed;
- workflow creation and workflow deletion remain preview-only until their own
  PX guard and verification contracts are certified;
- after guarded remote execution, TERM EXP reports execution success separately
  from post-operation verification.

Changing UI selection after a preview cannot silently retarget a pending
mutation because execution uses the frozen command shown in the preview.

Every action also declares a recovery class. `NONE` means the action does not
need recovery semantics; `EVIDENCE_ONLY` means PX/TERM EXP can preserve and
verify evidence but must not promise an automatic undo. Stronger classes such
as `REF_RECOVERABLE` and `CONTENT_RECOVERABLE` are reserved for domain
operations that actually prove those recovery guarantees. Confirmation and
recovery are intentionally separate concepts.

## Known-value arguments

TERM EXP should not make the operator memorize identifiers that PX already
knows. The action registry declares argument kinds; the resolver asks PX for
the corresponding authoritative values only when that argument is reached.

Current known-value selectors include:

- repositories from `px repos --json`;
- workflows and workflow runs scoped by repository;
- repository branches/refs and recent commits;
- Hospital Rooms, Doctors, sessions, checkpoints, Doctor Notes, and Room Chart
  entries;
- AI providers;
- workflow templates;
- executable command names from the PX tool registry;
- finite `enum` values declared directly in the action registry.

Selectors are searchable. Optional known values include a deliberate
`(default / none)` entry so converting a field into a selector never makes an
optional argument mandatory.

Dependencies remain contextual, but TERM EXP no longer infers them from argument kinds.
Each argument can declare a `dependsOn` role map in the PX action registry. The
map points semantic resolver roles such as `repository`, `room`, and
`reference` at earlier argument names. This keeps dependency order and identity
in PX metadata instead of Rust UI code, and lets two commit arguments depend on
different branch arguments without ambiguity.

Examples include:

```text
repository -> workflow
repository -> run
repository -> branch/ref -> commit
repository -> Room
Room       -> session
Room       -> report
Room       -> checkpoint
Room       -> Chart entry
```

Free typing remains the correct UI for genuinely open-ended values such as
prompts and paths. Typed integer and slug values are validated before PX is
invoked. If known-value discovery fails, TERM EXP falls back to typing rather
than making the whole action unusable.

For example, Inspect Workflow Run is:

```text
Inspect Workflow Run
  -> choose repository
  -> choose/search recent run
  -> inspect
```

No repository alias or run ID has to be remembered.

## Durable operation journal

Mutation history belongs to PX, not to TERM EXP. Before an executable mutation
runs, TERM EXP asks PX to create a durable RUNNING operation record. If that
record cannot be created, execution is refused.

The record preserves:

- semantic action ID and mutation/recovery classes;
- the exact frozen PX command shown during confirmation;
- named argument values;
- available preflight/arming evidence;
- execution exit status and bounded stdout/stderr evidence;
- post-operation verification status/evidence where a domain provides it;
- COMPLETE or FAILED lifecycle state.

Read-side journal actions are normal semantic PX actions, so TERM EXP can list,
inspect, and show recovery facts without requiring operation IDs to be
memorized.

Recovery classes describe guarantees, not wishes:

- `NONE` — no recovery operation is declared;
- `EVIDENCE_ONLY` — durable evidence exists, but automatic undo is not promised;
- `REF_RECOVERABLE` — reserved for operations that can prove reference-level
  recovery;
- `CONTENT_RECOVERABLE` — reserved for operations that can prove content-level
  recovery.

Even a recoverable class does not make an executor magically available. PX
recovery facts explicitly report `automaticRecoveryAvailable: false` until an
operation-specific recovery implementation is registered and certified.

```text
confirm frozen target
        |
        v
PX operation START (RUNNING)
        |
        v
execute mutation
        |
        +--> optional domain verification
        |
        v
PX operation FINISH (COMPLETE / FAILED)
```

## Architecture

```text
PX // TERM EXP
      |
      +-- px actions --json
      |      semantic control plane
      |
      +-- px tools --json
      |      ordinary executable universe
      |
      +-- contextual PX contracts
             repos / workflows / runs / branches / commits
             Hospital Rooms / Doctors / sessions / reports / Chart
             AI providers / workflow templates
```

TERM EXP is therefore a frontend to current PX. It does not recreate the old
Rust-side discovery, backend, or semantic action registries.
