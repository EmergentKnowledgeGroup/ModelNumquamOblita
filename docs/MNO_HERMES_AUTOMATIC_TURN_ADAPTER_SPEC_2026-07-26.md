# MNO Hermes Automatic Turn Adapter Specification

**Status:** LOCKED
**Draft date:** 2026-07-26
**Lock date:** 2026-07-26
**Lock version:** 1.0
**Target:** next merged MNO main release
**Hermes reference:** `NousResearch/hermes-agent` v0.19.0 at `588b7059a8b57b0e3dea98b480048eb7199ce0b6`

## 1. Decision

MNO will ship an optional Hermes general plugin named `mno-memory` and one MNO-owned lifecycle command, `mno-hermes`.

```text
ordinary Hermes turn
  pre_llm_call
    -> bounded context.build
    -> neutral MNO context appended to this model request

  Hermes/model work continues

  post_llm_call
    -> enqueue the completed turn without blocking delivery
    -> one background memory.observe attempt
    -> provisional observation/reinforcement only
```

The adapter is the automatic per-turn client. The model does not need to remember to call MNO. MCP remains optional for explicit inspection and actions. Human-reviewed canonical truth, HCR, review decisions, publish, verify, and activate remain unchanged.

This is a general Hermes integration, not a Lux-specific patch and not a Hermes memory-provider replacement.

## 2. Complexity and SpecSwarm route

Complexity is **5/5 — Hard**: this crosses an external runtime lifecycle, authentication, concurrency, packaging, installation, compatibility, and release-proof boundaries.

Required SpecSwarm reviewers are GPT-5.6 Sol: gap/edge `xhigh`, implementation mapper `high`, over-engineering/reward-hacking `xhigh`, and fresh final QA `xhigh`.

## 3. Product goal

After one explicit install/configure/restart:

- MNO context is retrieved automatically before eligible Hermes turns;
- a successful completed user/assistant turn is offered automatically to MNO afterward;
- routine observation needs neither a tool call nor human approval;
- observation is provisional, not canonical;
- unavailable or slow MNO never prevents Hermes from replying;
- install, health, degradation, and removal are explicit and machine-readable;
- the adapter adds information and context, never instructions for how the agent should behave.

## 4. Scope and no-touch boundary

### In scope

1. A standard-library-only Hermes Python plugin using `plugin.yaml` and `register(ctx)`.
2. `pre_llm_call`, `post_llm_call`, `on_session_end`, `on_session_finalize`, and `on_session_reset` handling.
3. Per-turn signed-handle correlation.
4. One bounded background observation worker.
5. Loopback-only MNO HTTP integration-v1 transport.
6. A dedicated operation-scoped adapter credential.
7. One Python implementation for `install`, `doctor`, `status`, and `uninstall`.
8. Ordinary `hermes_agent` integration bundles containing the real plugin and thin installer launchers.
9. Focused tests, real installed-Hermes proof, packaging proof, affected canonical docs, and affected architecture visuals.

### Out of scope

- automatic canonicalization, automatic approval, or agent-held review authority;
- a new provisional episode-card lane;
- replacing Hermes's memory provider or changing Hermes core;
- changing MNO retrieval/ranking, provisional-store semantics, HCR, import, MCP tools, or desktop review;
- remote MNO transport, redirects, proxies, TLS policy, or a service supervisor;
- a persistent conversation spool or post-turn retry subsystem;
- natural-language temporal parsing or autonomous reminders;
- platform/personality/provider behavior;
- broad documentation or visual redesign unrelated to this adapter.

### Authority invariant

The adapter principal may call only:

- `health.get`
- `capabilities.get`
- `context.build`
- `memory.observe`

It must be rejected from `review_apply` and every review, writeback-apply, publish, verify, activate, and canonical mutation operation regardless of the environment-variable name containing the credential.

## 5. Distribution

Packaged source:

```text
engine/integrations/hermes_plugin/
  plugin.yaml
  __init__.py
  adapter.py
```

Installed source:

```text
$HERMES_HOME/
  plugins/mno-memory/
    plugin.yaml
    __init__.py
    adapter.py
  mno/
    mno-memory.json
    install-state.json
```

The plugin:

- supports Hermes's Python range `>=3.11,<3.14`;
- uses only the Python standard library;
- does not import MNO inside the Hermes interpreter;
- contains all internal exceptions before Hermes can log secret-bearing exception text.

MNO retains its own Python requirement because it runs separately.

## 6. Hermes home and installer ownership

Hermes home precedence is:

1. `--hermes-home`;
2. `HERMES_HOME`;
3. platform default, including `%LOCALAPPDATA%\hermes` on native Windows and the upstream default on POSIX.

Every Hermes subprocess receives the resolved `HERMES_HOME`.

There is exactly one installer engine: the Python `mno-hermes` command. Exported `.ps1`/`.sh` helpers may only locate Python and invoke that engine.

`install-state.json` uses schema `mno.hermes-install-state.v1` and records:

- adapter/package version;
- resolved home;
- UTC install timestamp;
- SHA-256 for each owned plugin/config file;
- prior plugin state: `enabled`, `disabled`, or `neither`;
- at most one owned backup path and its hashes.

Writes use same-directory temporary files followed by atomic replacement. Owner-only mode is applied where supported. Installation refuses:

- symlinks, junctions, reparse points, or paths escaping the resolved home;
- an unowned existing plugin/config;
- an owned file whose hash changed, unless `--force` is explicit.

`--force` never widens credential authority or removes unrelated files.

Any install, enablement, or doctor failure rolls back both bytes and exact prior `enabled`/`disabled`/`neither` state. Uninstall restores that prior state instead of leaving an accidental Hermes config tombstone.

## 7. Configuration

`mno-memory.json`:

```json
{
  "schema_version": "mno.hermes-adapter.v1",
  "runtime_base_url": "http://127.0.0.1:7340",
  "token_env": "NO_INTEGRATION_HERMES_ADAPTER_TOKEN",
  "context_timeout_ms": 2500,
  "context_response_max_characters": 8192,
  "observe_timeout_ms": 5500,
  "observe_queue_max_items": 16,
  "observe_queue_max_age_seconds": 60,
  "pending_max_items": 256,
  "pending_ttl_seconds": 600,
  "capability_cache_ttl_seconds": 30,
  "enabled": true
}
```

Fixed v1 rules:

- URL scheme is `http`;
- host must resolve syntactically to loopback (`127.0.0.0/8`, `::1`, or `localhost`);
- userinfo, query, fragment, redirects, non-loopback hosts, and proxy routing are rejected;
- only the four operation paths in Section 4 may be requested;
- the token is read from the named environment variable and is never accepted as an argv/config value;
- the default token is dedicated to this adapter and server-side `allowed_operations` enforces its scope;
- bounds may be configured only within packaged safe minima/maxima; invalid config disables the plugin;
- capability cache keys include normalized runtime URL and a one-way token identity digest, never the token;
- cache is invalidated on auth, contract, or availability failure.

The adapter does not use `NO_INTEGRATION_REVIEW_APPLY_TOKEN` or a broad review-capable principal.

## 8. Turn eligibility and content normalization

Automatic processing applies only to successful, root, human-facing Hermes turns on the pinned Hermes revision.

It excludes by default:

- subagent/child turns;
- cron, heartbeat, curator, background-review, and internal gateway-dispatch turns;
- empty user text;
- non-text or multimodal-only user input;
- interrupted, failed, or empty assistant responses.

Eligibility uses and caches pinned Hermes pre-hook origin telemetry because post-hook telemetry is narrower. Internal origins named `subagent`, `cron`, `curator`, or `gateway`, and thread name `bg-review`, are excluded. An ordinary gateway-delivered human message is eligible only when explicit sender/origin telemetry identifies it as human rather than internal gateway dispatch. Unknown or ambiguous origin is a full adapter no-op for that turn; the adapter never guesses.

Content rules:

- accept strings only; never stringify arbitrary Python objects;
- replace unpaired surrogates with `U+FFFD`;
- normalize line endings to `\n`, apply Unicode NFC, and trim leading/trailing whitespace;
- retain the first 4,096 Unicode code points for each user and assistant string, matching integration-v1's effective generic string limit;
- store the exact bounded user string once at pre-turn and reuse it byte-for-byte at post-turn;
- report truncation only as a boolean/count, never content;
- test 4,095/4,096/4,097 characters and multibyte Unicode.

## 9. Identity and correlation

Raw Hermes/platform/session/turn identifiers are never copied directly into MNO identifiers. Normalized pinned-hook identity is hashed with SHA-256:

```text
session_id = "hermes_session_" + hex(sha256(platform || "\0" || raw_session_id))
run_id     = "hermes_turn_" + hex(sha256(platform || "\0" || raw_session_id || "\0" || raw_turn_id))
```

Both stay below MNO's 128-character ID limit.

Rules:

- `session_id` is stable for one Hermes session;
- `run_id` is unique for each Hermes turn;
- the exact pre-turn `run_id`, bounded user string, registration, and receipt are retained through post;
- current supported Hermes must supply `turn_id`;
- if `turn_id` is blank or absent, the adapter is a complete no-op for that turn;
- there is no FIFO or chronological fallback;
- locks protect metadata maps only and are never held across HTTP or filesystem I/O.

Pending entries contain the bounded current user text and signed handles only. Maximum is 256, TTL is the lesser of 600 seconds or the signed-handle expiry. Lifecycle hooks delete matching/expired pending items; they never delete MNO memory.

A consumed-turn tombstone stores only opaque IDs, disposition, and expiry. Maximum is 256; TTL is 600 seconds. It suppresses a duplicate `post_llm_call` without retaining conversation content.

## 10. Pre-turn recall

On an eligible `pre_llm_call`:

1. Validate config, eligibility, and identities.
2. Use one shared hard 2,500 ms wall-clock budget covering cold capability lookup and one `context.build`; no filesystem, subprocess, sleep, or queue work occurs inside that budget.
3. Gate recall only on effective `context.build` availability.
4. Require valid `mno.agent_context.v2`; compactly reserialize the JSON and escape `<`, `>`, and `&`.
5. Reject the entire context if invalid, longer than 8,192 characters, or its envelope claims more than 4,096 tokens. Never truncate JSON.
6. Retain correlation state only when `memory.observe` is effectively available and valid `source_registration` plus `retrieval_receipt` handles were returned. Recall still succeeds without observation state.
7. Return one fixed JSON-safe context block:

```text
<MNO_MEMORY_CONTEXT_V1>
{"format":"mno.agent_context.v2","context":{...validated compact JSON...}}
</MNO_MEMORY_CONTEXT_V1>
```

The JSON is serialized safely; recalled text cannot terminate the outer block. The wrapper states format/provenance only and adds no behavioral instruction.

Hermes v0.19.0 keeps the clean message `content`, but persists the composed augmented user content in `messages.api_content` and can replay it in later prompt history. Uninstall does not scrub that Hermes-owned history. The adapter itself does not write recalled content to its own files or logs.

Failure, timeout, or invalid context returns no context and never blocks or rewrites the user turn. Missing observation handles disable only observation. The adapter never calls `memory.source.register`.

## 11. Post-turn observation

`post_llm_call` must return quickly:

1. Match exact `(session_id, turn_id)` state.
2. Reject missing/mismatched/consumed state.
3. Create an immutable snapshot, enqueue it with `put_nowait`, remove pending turn state on successful enqueue, and retain only a consumed tombstone.
4. Return within a 25 ms local enqueue budget.

The single daemon worker:

- owns a bounded FIFO queue of 16 items;
- discards items older than 60 seconds or whose handles expire first;
- makes exactly one `memory.observe` attempt with a 5,500 ms end-to-end deadline;
- never retries after any send attempt, timeout, connection ambiguity, `429`, or `5xx`;
- never performs work ahead of the next turn's recall;
- never holds a map/queue lock during HTTP;
- classifies timeout, disconnect, `429`, or `5xx` after transmission as `observe_outcome_unknown`, then drops without retry;
- drops newest on overflow and records metadata-only degradation;
- loses queued items on process exit by design.

`memory.observe` receives only:

- exact bounded current user text with its source registration;
- exact bounded final assistant text;
- exact retrieval receipt;
- `remember_intent: "model_observed"`;
- stable per-turn request/run identity.

The endpoint is non-idempotent. A stable request ID aids tracing but is not a retry guarantee. At-most-once client behavior prefers losing an ambiguous observation over adding false reinforcement.

Pinned Hermes fires `on_session_end` after every `run_conversation` turn. That hook therefore purges only unmatched pending state for its exact `(session_id, turn_id)` and must not remove a successfully queued observation. `on_session_reset` and `on_session_finalize` purge remaining session pending state and queued-but-not-started work without synchronous flushing. One already in-flight attempt may finish within its deadline. No automatic path creates a review decision, evidence atom, episode card, publish action, activation, or canonical truth.

## 12. Explicit “remember this”

Automatic observation always uses `model_observed`.

Explicit user intent remains a separate MNO action:

```text
memory.observe remember_intent=user_explicit
  -> writeback.propose
  -> separate human review/apply authority
```

The adapter does not infer explicit intent from words, invoke writeback, or hold review credentials.

## 13. Fail-open and diagnostics

Hermes response delivery is primary. The adapter:

- catches all its exceptions;
- never changes the assistant response;
- never waits for post-turn observation;
- logs no token, message text, recalled context, signed handle, or exception body;
- records only timestamp, operation, bounded reason code, status class, duration, opaque request ID, and counters.

Default status is static install/config only. `status --live` may add a read-only health/capability probe:

- `healthy`
- `context_only`
- `disabled`
- `auth_missing`
- `auth_denied`
- `runtime_unavailable`
- `operation_unavailable`
- `contract_incompatible`
- `curation_required` only when an explicit local MNO/HCR readiness artifact proves it

There is no persistent “last hook” history or daemon status channel.

## 14. Lifecycle commands

### `mno-hermes install`

Options: `--hermes-home`, `--runtime-url`, `--token-env`, `--dry-run`, `--force`, `--json`.

It resolves/validates the home, verifies supported Hermes plugin commands, checks the token environment without printing it, installs atomically, enables via official Hermes CLI, and runs doctor. It reports that a running Hermes process must restart.

### `mno-hermes doctor`

Doctor is read-only. It:

- validates owned hashes/config/schema/plugin enablement;
- performs only `health.get` and `capabilities.get`;
- proves `context.build` and `memory.observe` are authorized/effectively available;
- proves the presented principal is denied from `review_apply` or a packaged negative authorization probe that creates no data;
- never calls `context.build` merely as a probe;
- reports ordinary runtime unavailability unless a concrete HCR readiness artifact proves `CURATION_REQUIRED`.

### `mno-hermes status`

Reports install ownership and enabled/configured state. Only `status --live` performs the optional live read-only health/capability probe. It never claims observation history.

### `mno-hermes uninstall`

Options: `--hermes-home`, `--dry-run`, `--force`, `--json`.

It removes only hash-matching owned files, restores the prior Hermes plugin state, preserves modified/unowned files unless forced, and never touches MNO stores, provisional memory, reviewed cards, Hermes sessions, or unrelated configuration.

## 15. Bundle migration

Only `tools/integration_bundle_common.py` is extended. The ordinary `hermes_agent` target adds:

- the plugin tree;
- an example non-secret config;
- thin install helpers;
- human/LLM quickstart;
- manifest metadata and `context.build`/`memory.observe` endpoint hints using `mno.agent_context.v2`.

Existing hint artifacts remain additive-compatible.

Existing endpoint keys and artifact names remain compatible. Generic, OpenClaw, Nanobot, MCP, and HCR/wizard exports receive regression coverage. The HCR draft-curation export must not install or emit the automatic observation adapter.

## 16. MCP and Hermes memory-provider coexistence

- MCP configuration alone causes no second automatic observation.
- Explicit MCP calls remain separate model/operator actions and may intentionally duplicate content.
- The adapter does not disable or replace Hermes's configured memory provider.
- If both are enabled, each may contribute context/observation according to its own contract; docs must disclose that overlapping memory systems can duplicate or compete.

No impossible global deduplication claim is allowed.

## 17. Compatibility claims

The pinned Hermes proof target is v0.19.0 at commit `588b7059a8b57b0e3dea98b480048eb7199ce0b6`.

| Surface | Release status rule |
| --- | --- |
| Python 3.11, 3.12, 3.13 plugin import/tests | must pass |
| One installed real Hermes root-turn lifecycle | must pass |
| Exact platform used for that proof | PASS |
| Native Windows | PASS only after real installed proof; upstream supports it |
| Linux/WSL/macOS | CONDITIONAL/UNVERIFIED unless each is actually run |
| Gateway | PASS only after a real gateway turn; CLI proof cannot substitute |
| Unsupported/missing `turn_id` | full adapter no-op for that turn |
| MNO unavailable/slow | Hermes still answers |
| MCP absent | adapter works against standalone MNO runtime |
| MCP/provider coexistence | behavior documented and tested without exclusivity claims |

“Closest upstream harness” is not release proof.

## 18. Required tests and evidence

### Unit/contract

- config schema and exact numeric bounds;
- URL grammar, redirect/proxy rejection, and operation allow-list;
- dedicated credential positive four-operation scope and negative review/canonical scope;
- 4,095/4,096/4,097 text, Unicode, empty, and multimodal skips;
- length-framed JSON wrapper with adversarial closing text;
- stable session/unique turn IDs below 128 characters;
- exact pre/post bounded user bytes and signed-handle pairing;
- overlapping sessions, duplicate post, absent turn ID full no-op, cached origin eligibility, expiry, lifecycle cleanup;
- 25 ms enqueue path, queue max/age/overflow, one attempt, no retry;
- black-hole/slow runtime without response delay or cross-session serialization;
- exception/log/status/bundle privacy scan;
- installer home precedence, atomicity, hashes, reparse containment, backup, prior enabled state, force boundary, rollback, and uninstall;
- ordinary versus HCR bundle separation;
- wheel/sdist plugin files and Python 3.11/3.12/3.13 import.

### Real installed-Hermes release proof

Using the pinned upstream revision and a disposable Hermes home:

1. install through `mno-hermes` and verify actual Hermes discovery/enablement;
2. run ordinary CLI and gateway-human-message root turns through `run_conversation`;
3. capture the actual provider request and prove the MNO wrapper occurs once;
4. disclose/prove the augmented API-bound content sidecar behavior;
5. prove post fires automatically and creates provisional evidence;
6. run a second same-session turn with a distinct `run_id` and prove expected reinforcement;
7. prove duplicate post adds no support;
8. prove interrupt/empty/failure does not observe;
9. stop/black-hole MNO and prove bounded pre plus non-blocking post while Hermes still responds;
10. prove no review, evidence-atom, episode-card, publish, verify, activate, or canonical state changes;
11. install/update/uninstall and prove MNO/Hermes data stores remain;
12. label only the actually run platform/surface PASS.

Direct callback invocation, status output, mocks, or import tests do not satisfy this gate.

### Repository gates

- focused adapter/contract/installer/bundle tests;
- full Python suite;
- existing desktop Node suite;
- build wheel/sdist and isolated install smoke;
- distribution verifier;
- `git diff --check`;
- secret/privacy scan;
- affected-doc link/stale-reference scan;
- affected visual source/export parity;
- focused diff-scope audit.

## 19. PASS / CONDITIONAL / FAIL

**PASS** requires every blocker closed, real installed-Hermes proof on every claimed PASS surface, operation-scoped auth, fail-open latency evidence, no canonical mutation, package proof, and accurate affected docs.

**CONDITIONAL** means the core proven platform is green while another named platform/surface remains explicitly unverified.

**FAIL** includes:

- the model must remember to call MNO for routine turns;
- a session-wide `run_id`, FIFO guessing, cross-turn/cross-session handle pairing, or observation retry;
- post-turn HTTP blocks reply delivery;
- remote transport or a review-capable token;
- automatic canonical/review/publish mutation;
- content/secrets/handles in adapter logs or files;
- automatic adapter artifacts leaking into HCR draft-only export;
- mocks/direct callbacks substituted for installed lifecycle proof;
- broader platform claims than evidence.

## 20. Rollout, backout, and claims

Rollout is explicit install, configure both processes with the dedicated scoped token, enable, restart Hermes, and run doctor. Existing MCP-only and manual integration-v1 paths continue.

Backout is `mno-hermes uninstall` plus Hermes restart. MNO stores and existing integrations remain.

Allowed claim:

> MNO can automatically provide context before eligible Hermes turns and observe successful completed turns afterward through an optional installed plugin. Routine observations remain provisional; canonical truth remains human-reviewed.

Forbidden claims include “remembers everything,” “every turn is stored,” “zero configuration,” “automatic canonical memory,” and untested platform support.

## 21. Change control

SpecSwarm final QA approved locking after the exact corrections above were applied consistently. This artifact is locked at version `1.0` on `2026-07-26`.

Changes to authority, identity, transport, persistence, retry behavior, lifecycle ownership, or truth boundaries require a written amendment and renewed blocker review. Implementation details may change only if they preserve every locked invariant and proof gate.

### Amendment 1 — per-turn end versus true session teardown

**Date:** 2026-07-26
**Reason:** direct inspection of pinned `turn_finalizer.py` proved `on_session_end` fires after every ordinary turn, later in the same finalizer after `post_llm_call` and before `run_conversation` returns.

The earlier lock sentence that grouped end/reset/finalize cleanup would have allowed the just-enqueued observation to be discarded before the worker sent it. Section 11 now makes `on_session_end` exact-turn pending cleanup only. During an actual Hermes session transition, finalize cleans the old session and reset defensively cleans the new session. This is a source-truth correction that preserves non-blocking delivery, at-most-once observation, bounded retention, and all authority boundaries.

### Amendment 2 — atomic session queue filtering

**Date:** 2026-07-26
**Reason:** final lifecycle QA proved that drain-and-reinsert cleanup can interleave with a producer or worker unless every queue mutation shares one synchronization boundary.

Enqueue, dequeue, and reset/finalize session filtering must share one queue transaction lock. Session filtering must complete atomically, must not lose another session's observation, and must release that lock before HTTP. A concurrent cross-session cleanup test is required. This corrects an implementation-level race without changing the product, authority, persistence, or at-most-once contract.
