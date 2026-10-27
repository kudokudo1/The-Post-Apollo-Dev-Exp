# PXD EXEC-S3 // B37-A Offline Tool-Free Request Contract

> STATE // DRAFT · OFFLINE-ONLY · REVIEW REQUIRED  
> PATIENT // The-Post-Apollo-Dev-Exp  
> SCOPE // Request construction, strict fixture validation, negative tests and CI only  
> AUTHORITY // bounded operator approval for B37-A only; no S3 implementation admission  
> PRODUCTION // HOLD

## IMPLEMENTATION

B37-A adds an **inert** request-shape validator at
`bin/px_s3_b37a_tool_free_contract.py`. It reuses the B25
Responses-shaped fixture builder but accepts **only** its fixed fake model and
one nonblank user-text input (up to 2048 characters). No native Codex,
Responses SDK, HTTP request, authorization header, provider credentials,
Hospital state, filesystem operation, or tool broker is introduced.

The accepted request shape is strictly limited to:

- `model`: the **B25 fake fixture model**, never a selectable production model
- `input`: exactly one `{role: user, content: text}` object
- `tools: []`; `tool_choice: none`; `parallel_tool_calls: false`
- `store: false`; `stream: true`; `background: false`
- `truncation: disabled`; `max_output_tokens: 512`

Every extra field is rejected, including endpoint/base URL, API key,
`previous_response_id`, tool call IDs, instruction overrides,
MCP servers, prompt caching, provider session identity or authentication
headers. JSON decoding rejects duplicate property names, invalid UTF-8,
non-finite numbers, malformed wire data and inputs beyond 8192 bytes.

Successful validation returns only **offline shape evidence**, not a dispatch
capability. `inspect_request` never includes user prompt or credentials.
`require_launch_authority` always refuses. The fixture has no transport,
network calls, native processes, Hospital writes, launch authority, verified
remote stop, certification or automatic retry.

## HOW TO USE

From an isolated checked-out B37-A branch or CI environment:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b37a-tool-free-contract.py
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/test-pxd-exec-s3-b25-responses-fixtures.py
```

These commands import fixture code and exercise in-memory data only.
They do not run native Codex or Hermes and do not read user configuration.

## VERIFY

- Fixed request-schema, model, tools, storage, background, stream and token-budget assertions.
- Reject any additional root keys, tool inventory, tool choice, alternate
  model, multiple roles/turns, extra input keys, or serialized duplicate keys.
- Reject malformed/nonfinite/oversized/invalid UTF-8 payloads, wrong types,
  missing keys and non-text input.
- Verify sanitized diagnostics, unconditional launch refusal, zero modeled
  provider/tool/Hospital calls and zero synthetic authorization.
- B25 fixture regressions continue unchanged, including their separate
  **untrusted** fake function-proposal mode. B37-A cannot admit that mode.
- Dedicated PR CI must pass before independent review; no CI result
  constitutes Fedora, authenticated-provider or production acceptance.

## WATCH OUT FOR

B37-A is intentionally **not** an HTTP client, configured transport,
authenticator, tool broker, Bed authority evaluator, response-event consumer,
retry driver or cancellation controller. Do not pass its output directly to
an SDK or infer that a pinned request body protects an untrusted client
process. The trusted-client and OS/proxy layer still need independent review
under the existing EXEC-S3 Stage A/B/C contract.

The legacy `bin/px-agent` and `config/agent-providers.json` native
`codex exec`/Hermes pathways remain unchanged and are not certified model-only.
The B37-A fake model identifier cannot be used as a real billable API model.

## CHECKLIST

- [x] B37-A contract and negative fixture suite prepared on isolated branch
- [ ] CI verified on exact PR head/merge checkout
- [ ] Nurse 2/Head Nurse ownership and review
- [ ] B37-B integration separately scoped and authorized
- [ ] Real API credentials/billing/provider test separately authorized
- [ ] Production authorization (explicitly withheld)

## NEXT

Independent review of strict request serialization and launch-refusal
boundary. Any B37-B connection to B29-B33 supervisor/ledger or live Hospital
requires a distinct bounded implementation decision.

## DECISIONS

Do not modify Fedora, personal Codex/Hermes, PX dispatch/resume, provider
registry, Hospital schemas, existing S3 authority previews or live services.
Never merge or activate solely because offline CI passes.
