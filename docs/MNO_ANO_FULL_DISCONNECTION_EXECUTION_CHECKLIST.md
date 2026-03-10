# MNO / ANO Full Disconnection Execution Checklist

Derived from: `docs/MNO_ANO_FULL_DISCONNECTION_SPEC.md`  
Top-level goal: **full disconnection**  
Status: Ready for implementation

## Global Execution Rules

- Keep one extraction slice per PR.
- Do not use this work as cover for unrelated refactors.
- Do not redesign MNO retrieval quality as part of separation.
- Do not redesign ANO research semantics as part of separation.
- Every changed surface must end with one clear owner:
  - MNO
  - ANO
  - shared
  - compatibility shim
- Every shim must declare:
  - owner
  - reason
  - removal trigger
  - latest allowed phase/version
- MNO standalone CI must fail on direct or transitive ANO imports.
- MNO packaging must exclude ANO modules, not merely ignore them.

## Global Done Rules

The separation is not done unless all of these are true:

- `MNO startup imports ANO-only modules = 0`
- `MNO UI surfaces exposing ANO-only controls = 0`
- `Top-level MNO exports of ANO symbols = 0`
- `Hidden plugin/dynamic ANO autoloads on MNO startup = 0`
- `Mixed mandatory runtime files remaining = 0`
- `MNO standalone install/test/runtime = PASS`
- `ANO standalone install/test/runtime = PASS`
- `Undeclared shared surfaces = 0`
- `Expired shims = 0`

## P0: Boundary Lock and Inventory

### P0.1 Inventory ownership

- [ ] classify current files as:
  - MNO-owned
  - ANO-owned
  - shared
  - mixed
- [ ] identify every mandatory MNO startup/import path that still touches ANO
- [ ] identify every mixed UI/server/export/test/doc/package surface
- [ ] record canonical owner for each mixed surface before implementation starts

Done when:

- there is no ownership ambiguity on startup, runtime, UI, package, docs, or tests

### P0.2 Lock the separation definitions

- [ ] lock the meaning of `ANO absent`
- [ ] lock the meaning of `public MNO contract`
- [ ] lock shared-lane hard rules
- [ ] lock compatibility shim policy
- [ ] lock duplicate-first reconciliation rule

Done when:

- future PRs cannot redefine “separated” on the fly

### P0.3 Compatibility matrix anchor

- [ ] establish `docs/MNO_ANO_COMPATIBILITY_MATRIX.md` as canonical matrix source
- [ ] define owner, update policy, support window, and deprecation policy
- [ ] define stop-ship rules for unsupported pairs

Done when:

- both future lanes can gate against one canonical matrix

### P0.4 P0 regression gate

- [ ] architecture review signoff
- [ ] no unresolved ownership ambiguity
- [ ] no unresolved definition ambiguity for `ANO absent`, shim ownership, or matrix scope

P0 closes only when all checks above are green.

## P1: MNO Startup / Runtime Detox In Current Tree

### P1.1 Top-level export detox

- [ ] remove ANO research exports from top-level MNO package surface
- [ ] stop `engine/__init__.py` from exporting ANO research symbols
- [ ] prove dependency tracing shows no transitive ANO import through MNO public imports

Done when:

- importing MNO public package surfaces does not pull ANO

### P1.2 Runtime server detox

- [ ] remove `AnoIncrementalManager` from mandatory MNO startup path
- [ ] move ANO endpoints behind ANO-owned lane or explicit optional boundary
- [ ] keep any plugin/add-on path default-off and explicit-enable only
- [ ] forbid auto-load-if-present behavior

Done when:

- MNO runtime startup succeeds with ANO imports failing

### P1.3 Runtime UI detox

- [ ] remove ANO incremental/operator panels from MNO runtime UI
- [ ] move ANO controls into ANO-owned UI surfaces
- [ ] remove combined MNO+ANO operator screen assumptions

Done when:

- MNO UI shows only MNO product behavior

### P1.4 Test-lane detox

- [ ] split or move mixed runtime tests
- [ ] move cross-product tests into explicit compatibility lane
- [ ] ensure shared fixtures do not leak ANO into MNO standalone CI
- [ ] make MNO standalone CI fail on ANO import, direct or transitive

Done when:

- MNO CI proves ANO absence instead of tolerating it

### P1.5 Packaging/docs detox

- [ ] stop MNO packaging/build scripts from targeting mixed paths
- [ ] strip ANO from baseline MNO package/install lane
- [ ] strip ANO setup language from normal MNO operator docs

Done when:

- MNO can be packaged and documented without ANO baggage

### P1.6 P1 regression gate

- [ ] MNO runtime launches with ANO modules unavailable
- [ ] MNO standalone CI is green
- [ ] dependency trace shows no ANO through MNO public imports
- [ ] MNO package excludes ANO modules

P1 closes only when all checks above are green.

## P2: Folder / Package Extraction

### P2.1 Explicit product roots

- [ ] create explicit MNO-owned package/folder roots
- [ ] create explicit ANO-owned package/folder roots
- [ ] move or duplicate mixed surfaces into owned roots

### P2.2 Mixed-surface surgery

- [ ] split:
  - `engine/runtime/server.py`
  - `engine/runtime/ui/index.html`
  - `engine/runtime/ui/app.js`
  - other declared mixed surfaces
- [ ] reduce mixed files to zero or thin shims only
- [ ] declare canonical owner for every duplicated surface

### P2.3 Duplicate/shim discipline

- [ ] add parity tests for duplicated surfaces
- [ ] or document intentional divergence rationale
- [ ] assign owner + removal trigger to every shim
- [ ] block indefinite “temporary” bridges

### P2.4 Packaging/doc path re-home

- [ ] re-home docs, fixtures, and packaging scripts to owned paths
- [ ] remove references to deleted mixed paths

### P2.5 P2 regression gate

- [ ] no mixed implementation files remain on mandatory paths
- [ ] ownership map matches code locations
- [ ] duplicated surfaces have parity or declared divergence
- [ ] packaging/docs no longer point to removed mixed paths

P2 closes only when all checks above are green.

## P3: Repo / Package Split

### P3.1 Standalone repo creation

- [ ] create standalone MNO repo/package lane
- [ ] create standalone ANO repo/package lane
- [ ] move tests/docs/release config accordingly

### P3.2 Contracted integration

- [ ] ensure ANO consumes only public MNO/shared contracts
- [ ] verify ANO does not import private MNO internals
- [ ] mirror compatibility matrix from canonical source as needed

### P3.3 Operator continuity

- [ ] provide migration path for existing MNO operators
- [ ] provide migration path for existing ANO operators
- [ ] preserve existing data paths without forced re-import due solely to repo split

### P3.4 Repo authority and fallback

- [ ] define which lane/repo remains authoritative if cutover partially fails
- [ ] keep monorepo lane authoritative until standalone gates are green

### P3.5 P3 regression gate

- [ ] independent install/build/test succeeds for MNO
- [ ] independent install/build/test succeeds for ANO
- [ ] MNO works standalone
- [ ] ANO works against stable MNO/shared contracts
- [ ] claimed supported version pairs are matrix-covered
- [ ] existing operator data paths stay valid

P3 closes only when all checks above are green.

## P4: Post-Split Hardening

### P4.1 Boundary enforcement

- [ ] add hidden-import and transitive-dependency audits
- [ ] add periodic boundary audit
- [ ] add release gate enforcement for compatibility matrix

### P4.2 Shim retirement

- [ ] remove expired shims
- [ ] fail releases on expired shim carryover
- [ ] keep no shim past the first release after both standalone lanes are green unless explicitly renewed

### P4.3 Shared-lane discipline

- [ ] reject shared-lane bloat
- [ ] revert oversized shared logic back to product-owned copies if needed

### P4.4 P4 regression gate

- [ ] boundary audit green
- [ ] compatibility lane green
- [ ] no hidden ANO import on MNO startup/export path
- [ ] no expired shim remains

P4 closes only when all checks above are green.

## Final Release Checklist

- [ ] all required P0 items closed
- [ ] all required P1 items closed
- [ ] all required P2 items closed
- [ ] all required P3 items closed
- [ ] all required P4 items closed
- [ ] canonical compatibility matrix is current
- [ ] no product claims separation while shipping hidden coupling
