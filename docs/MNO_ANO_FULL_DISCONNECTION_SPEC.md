# MNO / ANO Full Disconnection Spec

Status: Locked after 4-pass QA  
Owner: MNO product/runtime  
Planning base: `Z:\\openAIdata\\numquamoblita_mno_desktop_gui\\`  
Last updated: 2026-03-10

Derived docs:

- `docs/MNO_ANO_FULL_DISCONNECTION_EXECUTION_CHECKLIST.md`
- `docs/MNO_ANO_FULL_DISCONNECTION_BLOCKERBOARD.md`

## Goal

Top-level goal: **full disconnection**.

That means:

1. MNO can be built, packaged, tested, shipped, and embedded without ANO code, ANO startup imports, ANO UI panels, or ANO runtime contracts.
2. ANO can continue as its own product lane without forcing MNO to carry research/enterprise/connector baggage.
3. The split preserves current MNO behavior and trust guarantees.
4. The split preserves a clean path for ANO to consume stable MNO contracts where needed.

This is not a cosmetic repo cleanup. This is an architectural extraction plan with a final target of **separate MNO and ANO codebases / package lanes**.

## Why This Spec Exists

The current repo already states the intended contract:

- MNO is the personal memory runtime.
- ANO is additive and enterprise/document-research focused.
- MNO must remain functional without ANO attached.

But the current codebase does not fully honor that cleanly:

- `engine/__init__.py` exports `DocumentResearchLibrary` from ANO research.
- `engine/runtime/server.py` imports and initializes `AnoIncrementalManager`.
- `engine/runtime/ui/*` exposes ANO incremental update controls inside the same operator app.
- the repo package name and test surface still ship MNO and ANO together as one monolith.

So the product contract says “separate,” but the implementation still says “shared blob.”

## Product Decision

The end-state is:

- one **standalone MNO repo / package lane**
- one **standalone ANO repo / package lane**
- one optional **shared-contracts lane** only if required by implementation pressure

The migration path is staged:

1. first, lock boundaries and make MNO runnable without ANO in the current tree
2. then separate folders/packages inside the codebase
3. then cut real repo/package boundaries
4. then harden release/test/version policy so drift does not re-couple them

Do **not** start with a blind hard repo split.

Do **not** let “temporary shared convenience” become permanent hidden coupling.

## Root Cause

MNO and ANO share a historical codebase because ANO grew inside the same runtime/package surfaces that MNO already owned.

The most visible coupling points today are:

- top-level package export mixing:
  - `engine/__init__.py`
- runtime server startup mixing:
  - `engine/runtime/server.py`
- runtime operator UI mixing:
  - `engine/runtime/ui/index.html`
  - `engine/runtime/ui/app.js`
- runtime support module mixing:
  - `engine/runtime/ano_incremental.py`
- shared docs/tests/package identity:
  - `docs/*`
  - `tests/*`
  - `pyproject.toml`

The result is:

- user confusion
- packaging confusion
- import/startup ambiguity
- dirty-tree coordination pain
- inability to hand MNO cleanly to another system without dragging ANO along

## Non-Negotiable Separation Contract

The finished separation must satisfy all of these:

1. MNO startup paths cannot import ANO-only modules.
2. MNO runtime UI cannot expose ANO-only controls.
3. MNO package exports cannot re-export ANO research symbols.
4. ANO must consume only stable/public MNO contracts, not hidden internal shortcuts.
5. Shared code is allowed only if:
   - ownership is explicit
   - versioning is explicit
   - both sides can evolve without silent breakage
6. Repo/package split must not regress MNO trust or runtime behavior.
7. Repo/package split must not block ANO from continuing independently.
8. No fake separation:
   - copy/paste is allowed as a transitional extraction tool
   - but final ownership must be singular per surface
9. Release/test lanes must prove:
   - MNO works with ANO absent
   - ANO works against stable MNO contracts
10. No ANO-only dependency may remain on mandatory MNO install/startup/embed paths.

## SpecSwarm Fold-In Status

This spec is being hardened in four passes:

1. gap / edge-case review
2. implementation touchpoint mapping
3. final QA review
4. author final QA lock

Every blocking issue found in those passes must be folded into the main body of this spec before checklist/blockerboard derivation.

## Scope

### In scope

- full architectural separation plan for MNO vs ANO
- current-tree disentanglement work
- folder/package split plan
- repo split plan
- test/release/versioning contract after split
- migration of runtime UI/server/package exports off ANO mixing
- temporary clone/copy strategy where needed to break coupling safely

### Out of scope

- new retrieval ranking redesign unrelated to separation
- new ANO feature design
- new MNO feature design unrelated to separation
- immediate licensing/commercial text drafting
- actual code implementation in this spec pass

## Current Repo Truth (Planning Baseline)

These are the important real couplings in the visible MNO planning tree:

### MNO-intended core surfaces

- `engine/config.py`
- `engine/contracts.py`
- `engine/memory/*`
- `engine/retrieval/*`
- `engine/continuity/*`
- `engine/runtime/session.py`
- most of `engine/runtime/live_eval.py`
- MNO tools/docs around import, episodes, runtime, eval, MCP

### ANO-intended surfaces

- `engine/research/*`
- `engine/runtime/ano_incremental.py`
- document research tools / scale / connector / governance paths
- ANO-specific docs/boards/specs

### Mixed / contaminated surfaces

- `engine/__init__.py`
- `engine/runtime/server.py`
- `engine/runtime/ui/index.html`
- `engine/runtime/ui/app.js`
- `tests/integration/test_runtime_server.py`
- package/release identity in `pyproject.toml`
- some shared docs and runtime operator guides

These mixed surfaces are the real extraction problem.

## Required Definitions

### Definition: `ANO absent`

For this spec, `ANO absent` means all of the following:

- ANO-owned modules are not importable from the MNO runtime/package lane
- `engine/research/*` and ANO runtime modules are either physically absent from the MNO lane or excluded from its build/install path
- any optional plugin discovery path must not auto-load ANO code unless the user/operator explicitly enables an ANO lane
- MNO startup/runtime tests must pass in an environment where ANO imports would fail

`ANO absent` does **not** mean “the files happen to exist somewhere else on disk.”

### Definition: `public MNO contract`

ANO may depend only on:

- documented contract types
- documented schema/version constants
- explicit adapter/plugin interfaces
- compatibility-tested public runtime/service interfaces

ANO may not depend on:

- private MNO runtime internals
- transitive imports through top-level MNO package exports
- hidden helper modules not declared in the compatibility matrix

### Definition: `mixed file`

A mixed file is any implementation file that:

- imports both MNO-only and ANO-only logic in its mandatory path
- exposes both MNO and ANO UI/runtime operations in one product surface
- cannot be assigned a single final owner without extraction

### Definition: `compatibility shim`

A compatibility shim is a temporary bridge file that exists only to preserve imports or operator workflows during migration.

It must have:

- a single owner
- an expiration condition
- a removal gate
- no product logic growth after creation

## Target End-State

### End-state A: MNO repo

Contains only:

- personal memory ingest/import path
- atom store / continuity / retrieval / verifier / runtime
- reviewed-episode workflow
- direct/internal runtime activation
- MCP/runtime/operator surfaces relevant to MNO only
- MNO docs/tests/release pipeline

Must not contain:

- `engine/research/*`
- ANO incremental runtime
- document research connectors
- enterprise governance/compliance logic
- ANO scale qualification tooling

### End-state B: ANO repo

Contains:

- document research library
- connectors
- segmented ingest/index/query lifecycle
- ANO runtime/operator UI
- governance/compliance/entitlement surfaces
- ANO docs/tests/release pipeline

May depend on:

- stable MNO/shared contracts only

Must not assume:

- access to private MNO runtime internals
- ability to patch MNO behavior through hidden imports

### End-state C: Optional shared lane

Only create this if a real shared-core pressure remains after extraction.

Allowed contents:

- schema/version constants
- stable contracts/types
- minimal utility surfaces that are truly product-agnostic

Forbidden contents:

- runtime startup logic
- ANO research implementation
- MNO retrieval implementation
- product-specific UI

If in doubt, duplicate first, then reduce into shared only after ownership is proven.

### Shared-lane hard rules

- dependency direction may only be:
  - MNO -> shared
  - ANO -> shared
- forbidden dependency directions:
  - shared -> MNO
  - shared -> ANO
  - MNO -> ANO
  - ANO -> private MNO internals
- shared lane must stay limited to:
  - contracts/types
  - schema/version constants
  - narrow product-agnostic interfaces
- if a candidate shared surface carries runtime startup, UI, retrieval, research, or product workflow logic, it is not shared and must live in one product lane

## Separation Strategy

### Chosen strategy

Use a **staged surgical extraction**:

1. lock the boundary contract
2. stop MNO from importing/exporting ANO by default
3. peel ANO UI/runtime paths out of mixed surfaces
4. create clean folder/package roots
5. cut separate repo/package lanes
6. enforce versioned contract compatibility after the split

### Why not a blind repo split first

Because today the coupling still lives in startup paths, UI, exports, tests, and packaging.

A blind repo split would create:

- broken imports
- duplicated ownership
- flaky tests
- “works only if both repos are checked out together” failure modes

## No-Touch / Boundary Rules During Extraction

### Allowed extraction surfaces

- `engine/__init__.py`
- `engine/runtime/server.py`
- `engine/runtime/ui/*`
- `engine/runtime/__init__.py`
- `engine/runtime/ano_incremental.py`
- `pyproject.toml`
- MNO/ANO docs and packaging docs
- tests that currently validate mixed startup/runtime/export behavior

### Extraction no-touch rules

- do not redesign MNO retrieval quality as part of this work
- do not redesign ANO research semantics as part of this work
- do not use this split as cover for opportunistic refactors unrelated to separation
- do not blur ownership after a surface is assigned

## Required Separation Principles

### Principle 1: MNO-first independence

MNO must be able to:

- import
- build episodes
- review/publish
- run runtime
- run evals
- expose MCP/direct connectors

with ANO code absent.

### Principle 2: ANO as additive consumer

ANO may reuse only explicit contracts from MNO/shared layers.

ANO must not require:

- importing top-level MNO runtime server internals
- patching MNO UI
- hidden shared globals

### Principle 3: one owner per file

During/after split, every file must clearly be:

- MNO-owned
- ANO-owned
- shared-owned

No “kinda both” files after phase completion.

### Principle 4: copy first if needed, then dedupe surgically

If a shared file is too entangled:

- duplicate it into MNO and ANO lanes first
- make behavior stable
- then remove accidental duplication later

This is preferred over keeping one unhealthy god-file alive.

### Principle 5: no hidden dynamic recoupling

Dynamic import/plugin paths must obey the same boundary as static imports.

That means:

- MNO may not auto-discover/load ANO code on startup
- plugin registries must require explicit enablement
- default state for ANO plugin/add-on paths in MNO must be `off`
- “optional if present” auto-loading is not an acceptable excuse for hidden coupling

## Required User / Operator Outcomes

After separation:

### For MNO operators

- they can install/run MNO without ANO baggage
- docs do not mention ANO for normal MNO setup
- runtime UI does not show ANO controls
- package/install surface is smaller and simpler

### For ANO operators

- they can install/run ANO on its own lane
- ANO docs do not depend on MNO monorepo tribal knowledge
- ANO upgrade path is independent

### For integrators

- MNO can be embedded directly without hauling in document research code
- contracts are documented and versioned
- package boundaries are obvious

## Detailed Requirements

### Package export cleanup

- remove ANO research exports from top-level MNO package surface
- `engine/__init__.py` must stop exporting `DocumentResearchLibrary`
- if ANO needs a public root, it must live under its own package root
- dependency tracing must prove no transitive ANO imports survive through MNO top-level imports

### Runtime server separation

- MNO runtime server must not import `AnoIncrementalManager` on required startup path
- ANO runtime endpoints must move behind:
  - a separate ANO server
  - or a clearly optional plugin/add-on boundary
- MNO startup must succeed when ANO code is physically absent
- explicit “ANO absent” test mode must exercise import failure on ANO modules and still pass MNO startup/runtime gates
- optional plugin/add-on boundary means:
  - explicit operator enablement only
  - default-off
  - no auto-load-if-present behavior

### Runtime UI separation

- MNO runtime UI must remove ANO incremental update sections
- ANO operator UI must move into ANO-owned surfaces
- no combined “one page with MNO + ANO panels” final state

### Tooling separation

- MNO tools and ANO tools must live in different lanes/namespaces/docs
- MNO operator docs must not point users into ANO tooling
- ANO heavy-path/enterprise tools must not ship in baseline MNO package lane

### Test separation

- MNO CI/test lane must pass with ANO absent
- ANO CI/test lane must pass against released/stable MNO contracts
- mixed integration tests must be either:
  - removed
  - duplicated into explicit cross-product compatibility tests
  - or moved into a dedicated compatibility lane
- shared fixtures must not leak ANO into MNO CI
- compatibility tests must have an explicit owner and run outside the MNO standalone gate
- MNO standalone CI must fail if ANO modules are imported directly or transitively

### Packaging separation

- MNO package identity must describe MNO only
- ANO package identity must describe ANO only
- if a shared package exists, it must not become a dumping ground
- packaging/build scripts must not reference old mixed paths after extraction
- standalone build/install must prove MNO and ANO can be packaged independently
- MNO build/install artifacts must exclude ANO-owned modules, not merely leave them unused
- ANO build/install artifacts must exclude private MNO runtime internals

### Docs separation

- MNO docs index must point to MNO-only setup/runtime paths
- ANO docs index must point to ANO-only setup/runtime paths
- cross-product docs must become explicit integration docs, not ambient assumptions

## Candidate File Ownership Map

### MNO-owned after extraction

- `engine/config.py`
- `engine/contracts.py`
- `engine/memory/*`
- `engine/retrieval/*`
- `engine/continuity/*`
- `engine/runtime/session.py`
- `engine/runtime/live_eval.py`
- MNO runtime UI/server surfaces
- MNO MCP/direct connector surfaces
- MNO import/episode/review/runtime tools

### ANO-owned after extraction

- `engine/research/*`
- `engine/runtime/ano_incremental.py`
- ANO document-research tools
- ANO scale/gate/qualification tooling
- ANO operator UI/server surfaces

### Shared-only if justified

- selected stable contracts/types
- schema/version constants
- maybe selected adapter interfaces

### Explicitly mixed today and must be split

- `engine/__init__.py`
- `engine/runtime/server.py`
- `engine/runtime/ui/index.html`
- `engine/runtime/ui/app.js`
- `tests/integration/test_runtime_server.py`
- shared docs indexes and packaging docs

## Temporary Extraction Pattern

When a file is too mixed to separate in place cleanly, use this sequence:

1. duplicate the mixed surface into:
   - MNO-owned variant
   - ANO-owned variant
2. redirect callers/imports to the owned variants
3. prove both variants independently
4. delete the mixed original or leave only a thin compatibility shim

This is especially acceptable for:

- runtime UI/server split
- launcher/bootstrap surfaces
- docs/setup/runbook surfaces

### Duplicate-first reconciliation rule

If a surface is duplicated to break coupling:

- the spec/checklist must declare which variant is the canonical future owner
- divergence is allowed only when it reflects product-specific behavior
- accidental divergence must be resolved before the phase closes
- no duplicated mixed surface may survive without a declared deletion or shim plan
- every duplicated surface must have either:
  - parity tests
  - or a documented intentional divergence rationale

### Compatibility shim policy

Every shim must declare:

- owner: MNO or ANO
- reason for existence
- import paths preserved
- removal trigger
- latest allowed phase/version

Default rule:

- no shim may survive past the first release after both standalone lanes are green

## Versioning / Contract Rules After Split

### Required contracts

- IA output version -> MNO version matrix
- ANO supported-against-MNO version matrix
- optional shared-contract package version

### Compatibility matrix scope

The matrix must define:

- supported version window
  - current major/minor
  - previous supported minor if applicable
- deprecation policy
- required test coverage per supported version pair
- stop-ship conditions for unsupported or broken pairs

Minimum declared matrix:

- IA current -> supported MNO versions
- MNO current -> supported ANO versions
- shared-contract package version -> compatible MNO/ANO versions if shared lane exists

### Compatibility matrix ownership

- canonical location during extraction is `docs/MNO_ANO_COMPATIBILITY_MATRIX.md`
- canonical owner during extraction is the separation program workstream
- both MNO and ANO release lanes must gate against that same canonical matrix
- matrix duplication across repos is allowed only as generated mirrors of the canonical source

### Required guarantees

- MNO minor release cannot silently break ANO compatibility without declared contract change
- ANO cannot consume unpublished/private MNO APIs
- shared contract changes must be versioned and test-gated

### Stop-ship rules

- if MNO standalone gate fails, separation work does not ship
- if ANO consumes undeclared/private MNO internals, separation work does not ship
- if compatibility matrix coverage is missing for a claimed supported pair, separation work does not ship
- if a shim exceeds its allowed phase/version without explicit renewal, separation work does not ship
- if MNO build passes but ANO still imports private MNO internals in a claimed separated phase, separation work does not ship

## Migration / Rollout Plan

### P0: Boundary lock and inventory

Goal:

- freeze the separation contract and inventory every mixed surface

Required scope:

- classify all files into MNO / ANO / shared / mixed
- lock no-touch and no-fake-separation rules
- identify which startup paths still import ANO from MNO
- define `ANO absent`, public MNO contract namespace, shared-lane hard rules, and shim policy

Done when:

- there is no ambiguity about the target owner of every mixed surface

Regression gate:

- architecture review signoff
- no unresolved ownership ambiguity on startup/runtime/export surfaces
- no unresolved definition ambiguity for `ANO absent`, shim ownership, or compatibility matrix scope

### P1: MNO startup/runtime detox in current tree

Goal:

- make MNO run cleanly without ANO attached while still inside the current codebase

Required scope:

- remove ANO exports from top-level MNO package path
- remove ANO imports from mandatory MNO startup paths
- split ANO panels/endpoints from MNO UI/runtime server
- isolate or shim mixed runtime tests
- prove no hidden dynamic/plugin ANO auto-load remains in MNO startup path

Done when:

- MNO package/runtime/UI works with ANO physically absent

Regression gate:

- MNO test lane passes with ANO disabled/removed from startup path
- MNO runtime launches without ANO modules available
- dependency trace proves no ANO import survives through public MNO imports

### P2: Folder/package extraction

Goal:

- move from mixed layout to explicit product roots

Required scope:

- create explicit MNO-owned and ANO-owned package/folder roots
- move/duplicate mixed surfaces into owned lanes
- reduce mixed files to zero or compatibility shims only
- re-home docs, fixtures, and packaging scripts so they no longer assume mixed paths

Done when:

- a developer can tell ownership by path, not tribal knowledge

Regression gate:

- no mixed implementation files remain on mandatory paths
- ownership map matches actual code locations
- packaging scripts and docs paths no longer target removed mixed surfaces
- no duplicated mixed surface closes without parity coverage or documented divergence

### P3: Repo/package split

Goal:

- cut separate release lanes

Required scope:

- create standalone MNO repo/package lane
- create standalone ANO repo/package lane
- move docs/tests/release config accordingly
- keep compatibility docs and version matrix current
- define user/operator continuity path for existing monorepo users
- define which repo remains authoritative if repo cutover partially fails

Done when:

- MNO and ANO can be checked out, built, and released independently

Regression gate:

- independent install/build/test succeeds for both lanes
- MNO works standalone
- ANO works against stable MNO/shared contracts
- version skew policy is documented and enforced for claimed supported pairs
- existing operator data paths remain valid without forced re-import solely due to repo split

### P4: Post-split hardening

Goal:

- stop drift from re-coupling the products

Required scope:

- contract tests
- compatibility matrix enforcement
- docs/release gate enforcement
- periodic boundary audit
- shim retirement audit
- hidden import / transitive dependency audit

Done when:

- future work cannot casually reintroduce hidden coupling

Regression gate:

- boundary audit green
- compatibility lane green
- no hidden import of ANO into MNO startup/export paths
- no expired shim remains

## Success Metrics

The separation is not done unless all of these are true:

- `MNO startup imports ANO-only modules = 0`
- `MNO UI surfaces exposing ANO-only controls = 0`
- `Top-level MNO package exports ANO symbols = 0`
- `Mixed mandatory runtime files after split = 0`
- `MNO standalone install/test/runtime success = PASS`
- `ANO standalone install/test/runtime success = PASS`
- `Undeclared shared surfaces = 0`
- `Compatibility matrix coverage gaps on supported versions = 0`
- `Hidden dynamic/plugin ANO loads on MNO startup = 0`
- `Expired compatibility shims remaining = 0`

## Rollback / Backout Rules

Must support all of these during the separation program:

1. restore the last known good monorepo runtime state if extraction regresses startup
2. keep compatibility shims only where required and time-box them
3. preserve both MNO and ANO docs during migration
4. prevent release cutover until standalone validation is green

### Required backout coverage

- partial P1 failure:
  - restore prior mixed startup/runtime behavior while preserving the ownership inventory
- partial P2 failure:
  - restore prior folder/package layout or maintain import-compatible shims until the next clean attempt
- partial P3 failure:
  - stop repo/package cutover and keep monorepo release lane authoritative
- failed repo authority split:
  - one repo/lane must be explicitly declared authoritative before release resumes
- version skew failure:
  - pin to last supported MNO/ANO pair and block unsupported claims
- shared-lane mistake:
  - revert the shared surface back into product-owned copies until the contract is corrected
- shared-lane bloat:
  - revert oversized shared logic back into product-owned lanes before release

### Operator continuity guarantees

- existing MNO operators must retain a documented migration path from monorepo lane to standalone MNO lane
- existing ANO operators must retain a documented migration path from monorepo lane to standalone ANO lane
- existing user data/workflows must not require re-import solely because the repos split

## SpecSwarm Fold-In Log

### Pass 1: Gap / edge-case review folded in

- defined `ANO absent` explicitly
- added public-contract/shared-lane/shim definitions
- added compatibility matrix scope and stop-ship rules
- added hidden dynamic-load guardrails
- added partial-failure backout coverage and operator continuity requirements

### Pass 2: Implementation mapping folded in

- reinforced `engine/__init__.py`, `engine/runtime/server.py`, `engine/runtime/ui/*`, tests, docs, and packaging as the real mixed surfaces
- added package/export/runtime/test/docs extraction requirements based on current repo reality
- added explicit dependency tracing and packaging-path cleanup requirements
- clarified that mixed integration tests must become owned compatibility lanes or be split

### Pass 3: Final QA review folded in

- made ANO plugin/add-on paths explicitly default-off and never auto-load-if-present
- added artifact-bundling requirements so MNO packages exclude ANO modules
- added a hard rule that MNO standalone CI cannot import ANO directly or transitively
- defined canonical compatibility-matrix ownership and gate usage
- added parity-test-or-divergence requirements for duplicated surfaces
- added stop-ship/backout coverage for partial split states and shared-lane bloat

### Pass 4: Author final QA lock

- anchored the canonical compatibility matrix to `docs/MNO_ANO_COMPATIBILITY_MATRIX.md`
- locked the spec status after the 4-pass review cycle
- confirmed that plugin/add-on language stays explicit-enable and default-off
- confirmed that standalone MNO packaging must exclude ANO code, not merely avoid using it

## Remaining Non-Blocking Decisions

1. Should the final shared lane be a small package, or should MNO and ANO duplicate stable contracts until the split is fully proven?
2. Should ANO runtime/operator UI live as a separate app immediately, or as an optional plugin shell first?
3. Which exact integration tests should remain as cross-product compatibility tests instead of being fully separated?
