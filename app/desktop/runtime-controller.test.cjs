const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  assessExistingRuntime,
  buildExpectedBinding,
  buildRuntimeLaunchPlan,
  buildRuntimeSpawnOptions,
  collectMissingArtifacts,
  defaultShellPreferences,
  deriveShellStartupState,
  formatTimeoutLabel,
  hydratedRuntimeUrl,
  loadDesktopAppVersion,
  loadLatestWizardState,
  loadLastKnownGoodRuntime,
  loadRuntimeBundleManifest,
  loadShellPreferences,
  parseRuntimeStdoutLine,
  parseShellCliArgs,
  readRuntimeLock,
  resolveShellPaths,
  runtimeHealthMatchesExpected,
  sanitizeRuntimeBundleManifest,
  sanitizeShellPreferences,
  saveLastKnownGoodRuntime,
  saveShellPreferences,
  stateLabel,
  summarizeRuntimeLock,
  waitForChildExit,
  waitForRuntimeReady,
} = require('./runtime-controller.cjs');
const { EventEmitter } = require('node:events');

function makeWizardState(overrides = {}) {
  return {
    selected_input: { kind: 'ia_archive', is_valid: true, path: '/tmp/archive.json' },
    store_validation: {
      kind: 'sqlite_store',
      is_valid: true,
      path: '/tmp/store.sqlite3',
      store_fingerprint: 'store_fingerprint_v1',
    },
    published_set: {
      episodes_path: '/tmp/episode_cards.reviewed.json',
      build_id: 'build_123',
    },
    verify: {
      status: 'Safe',
      remap_required: false,
    },
    activation: {
      direct: {},
      draft_override: { active: false },
    },
    ...overrides,
  };
}

test('parseShellCliArgs reads explicit shell overrides', () => {
  const parsed = parseShellCliArgs(['--memories', '/tmp/store.sqlite3', '--episodes', '/tmp/cards.json', '--port', '8450', '--python', 'py', '--repo-root', '/repo', '--smoke-exit-when-ready', '--boot-timeout-ms', '45000']);
  assert.equal(parsed.memories, '/tmp/store.sqlite3');
  assert.equal(parsed.episodes, '/tmp/cards.json');
  assert.equal(parsed.port, 8450);
  assert.equal(parsed.python, 'py');
  assert.equal(parsed.repoRoot, '/repo');
  assert.equal(parsed.smokeExitWhenReady, true);
  assert.equal(parsed.bootTimeoutMs, 45000);
});

test('buildRuntimeLaunchPlan keeps runtime launcher bounded and explicit', () => {
  const manifest = sanitizeRuntimeBundleManifest({
    schema: 'modelnumquamoblita.desktop.runtime_bundle.v1',
    bundle_mode: 'python_entrypoint',
    runtime_version: '0.1.0',
    allowed_app_versions: ['0.1.0'],
    entrypoint: 'tools/run_live_runtime.py',
    python_commands: { default: 'python3' },
  }, { appVersion: '0.1.0' });
  const plan = buildRuntimeLaunchPlan({ repoRoot: '/repo', runtimeManifest: manifest, host: '127.0.0.1', port: 8123, memories: '/tmp/store.sqlite3', episodes: '/tmp/cards.json' });
  const expectedCwd = path.resolve('/repo');
  const expectedLauncher = path.join(expectedCwd, 'tools', 'run_live_runtime.py');
  const expectedStore = path.resolve('/tmp/store.sqlite3');
  const expectedEpisodes = path.resolve('/tmp/cards.json');
  assert.equal(plan.command, 'python3');
  assert.equal(plan.cwd, expectedCwd);
  assert.deepEqual(plan.args.slice(0, 5), [expectedLauncher, '--host', '127.0.0.1', '--port', '8123']);
  assert.ok(plan.args.includes(expectedStore));
  assert.ok(plan.args.includes(expectedEpisodes));
  assert.equal(plan.runtimeHealthUrl, 'http://127.0.0.1:8123/api/runtime/health');
});

test('buildRuntimeLaunchPlan supports setup mode with explicit setup store', () => {
  const manifest = sanitizeRuntimeBundleManifest({
    schema: 'modelnumquamoblita.desktop.runtime_bundle.v1',
    bundle_mode: 'python_entrypoint',
    runtime_version: '0.1.0',
    allowed_app_versions: ['0.1.0'],
    entrypoint: 'tools/run_live_runtime.py',
    python_commands: { default: 'python3' },
  }, { appVersion: '0.1.0' });
  const plan = buildRuntimeLaunchPlan({
    repoRoot: '/repo',
    runtimeManifest: manifest,
    host: '127.0.0.1',
    port: 8123,
    setupMode: true,
    setupModeStorePath: '/repo/runtime/desktop_shell/setup.sqlite3',
  });
  assert.equal(plan.setupMode, true);
  assert.equal(plan.launchMode, 'setup_mode');
  assert.ok(plan.args.includes('--setup-mode'));
  assert.ok(plan.args.includes(path.resolve('/repo/runtime/desktop_shell/setup.sqlite3')));
});

test('buildRuntimeLaunchPlan resolves bundled Python relative to repo root when present', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-bundled-python-'));
  const repoRoot = path.join(tmpDir, 'repo');
  const bundledPython = path.join(repoRoot, 'runtime', 'python', 'bin', 'python3');
  fs.mkdirSync(path.dirname(bundledPython), { recursive: true });
  fs.writeFileSync(bundledPython, '#!/bin/sh\n', 'utf8');
  const manifest = sanitizeRuntimeBundleManifest({
    schema: 'modelnumquamoblita.desktop.runtime_bundle.v1',
    bundle_mode: 'python_entrypoint',
    runtime_version: '0.1.0',
    allowed_app_versions: ['0.1.0'],
    entrypoint: 'tools/run_live_runtime.py',
    python_commands: { default: 'runtime/python/bin/python3' },
  }, { appVersion: '0.1.0' });
  const plan = buildRuntimeLaunchPlan({ repoRoot, runtimeManifest: manifest });
  assert.equal(plan.command, bundledPython);
});

test('buildRuntimeLaunchPlan refuses packaged startup when bundled Python is required but missing', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-missing-bundled-python-'));
  const repoRoot = path.join(tmpDir, 'repo');
  const entrypoint = path.join(repoRoot, 'tools', 'run_live_runtime.py');
  fs.mkdirSync(path.dirname(entrypoint), { recursive: true });
  fs.writeFileSync(entrypoint, '#!/usr/bin/env python3\n', 'utf8');
  const manifest = sanitizeRuntimeBundleManifest({
    schema: 'modelnumquamoblita.desktop.runtime_bundle.v1',
    bundle_mode: 'python_entrypoint',
    runtime_version: '0.1.0',
    allowed_app_versions: ['0.1.0'],
    entrypoint: 'tools/run_live_runtime.py',
    python_commands: { default: 'runtime/python/bin/python3' },
  }, { appVersion: '0.1.0' });
  assert.throws(
    () => buildRuntimeLaunchPlan({ repoRoot, runtimeManifest: manifest, requireBundledRuntime: true }),
    /bundled Python runtime not found/,
  );
});

test('buildRuntimeLaunchPlan refuses packaged startup when pythonCommand override is provided', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-python-override-'));
  const repoRoot = path.join(tmpDir, 'repo');
  const entrypoint = path.join(repoRoot, 'tools', 'run_live_runtime.py');
  fs.mkdirSync(path.dirname(entrypoint), { recursive: true });
  fs.writeFileSync(entrypoint, '#!/usr/bin/env python3\n', 'utf8');
  const manifest = sanitizeRuntimeBundleManifest({
    schema: 'modelnumquamoblita.desktop.runtime_bundle.v1',
    bundle_mode: 'python_entrypoint',
    runtime_version: '0.1.0',
    allowed_app_versions: ['0.1.0'],
    entrypoint: 'tools/run_live_runtime.py',
    python_commands: { default: 'runtime/python/bin/python3' },
  }, { appVersion: '0.1.0' });
  assert.throws(
    () => buildRuntimeLaunchPlan({ repoRoot, runtimeManifest: manifest, requireBundledRuntime: true, pythonCommand: 'python3' }),
    /does not allow overriding pythonCommand/,
  );
});

test('buildRuntimeLaunchPlan refuses packaged startup when entrypoint escapes repo root', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-bundled-entrypoint-'));
  const repoRoot = path.join(tmpDir, 'repo');
  const bundledPython = path.join(repoRoot, 'runtime', 'python', 'bin', 'python3');
  fs.mkdirSync(path.dirname(bundledPython), { recursive: true });
  fs.writeFileSync(bundledPython, '#!/bin/sh\n', 'utf8');
  const manifest = sanitizeRuntimeBundleManifest({
    schema: 'modelnumquamoblita.desktop.runtime_bundle.v1',
    bundle_mode: 'python_entrypoint',
    runtime_version: '0.1.0',
    allowed_app_versions: ['0.1.0'],
    entrypoint: '../tools/run_live_runtime.py',
    python_commands: { default: 'runtime/python/bin/python3' },
  }, { appVersion: '0.1.0' });
  assert.throws(
    () => buildRuntimeLaunchPlan({ repoRoot, runtimeManifest: manifest, requireBundledRuntime: true }),
    /entrypoint escapes repo root/,
  );
});

test('sanitizeRuntimeBundleManifest enforces executable bundle metadata', () => {
  assert.throws(
    () => sanitizeRuntimeBundleManifest({
      schema: 'modelnumquamoblita.desktop.runtime_bundle.v1',
      bundle_mode: 'executable',
      runtime_version: '0.1.0',
      allowed_app_versions: ['0.1.0'],
      executable_path: '',
    }, { appVersion: '0.1.0' }),
    /missing executable_path/,
  );
});

test('buildRuntimeSpawnOptions enforces no-shell launch and windows hide on win32', () => {
  const options = buildRuntimeSpawnOptions({ cwd: '/repo', env: { BASE: '1' }, platform: 'win32' });
  assert.equal(options.cwd, '/repo');
  assert.equal(options.shell, false);
  assert.equal(options.windowsHide, true);
  assert.equal(options.env.BASE, '1');
  assert.equal(options.env.PYTHONUNBUFFERED, '1');
});

test('parseRuntimeStdoutLine accepts key-value output only', () => {
  assert.deepEqual(parseRuntimeStdoutLine('runtime_url=http://127.0.0.1:7340'), { key: 'runtime_url', value: 'http://127.0.0.1:7340' });
  assert.equal(parseRuntimeStdoutLine('Press Ctrl+C to stop.'), null);
});

test('hydratedRuntimeUrl only returns a runtime URL for live health payloads', () => {
  assert.equal(hydratedRuntimeUrl(null), '');
  assert.equal(hydratedRuntimeUrl({}), '');
  assert.equal(hydratedRuntimeUrl({ runtime_url: 'http://127.0.0.1:7340' }), 'http://127.0.0.1:7340');
});

test('resolveShellPaths keeps runtime folders anchored to repo root', () => {
  const paths = resolveShellPaths('/repo');
  assert.equal(paths.repoRoot, '/repo');
  assert.equal(paths.runtimeRoot, '/repo/runtime');
  assert.equal(paths.wizardRunsRoot, '/repo/runtime/wizard_runs');
  assert.equal(paths.publishedSetsRoot, '/repo/runtime/episodes');
  assert.equal(paths.desktopShellRoot, '/repo/runtime/desktop_shell');
  assert.equal(paths.desktopPreferencesPath, '/repo/runtime/desktop_shell/preferences.json');
});

test('resolveShellPaths can split immutable repo assets from per-user runtime state', () => {
  const paths = resolveShellPaths('/repo', { dataRoot: '/user/state/runtime' });
  assert.equal(paths.repoRoot, '/repo');
  assert.equal(paths.runtimeRoot, '/user/state/runtime');
  assert.equal(paths.wizardRunsRoot, '/user/state/runtime/wizard_runs');
  assert.equal(paths.publishedSetsRoot, '/user/state/runtime/episodes');
  assert.equal(paths.desktopShellRoot, '/user/state/runtime/desktop_shell');
});

test('sanitizeShellPreferences clamps invalid values back to safe defaults', () => {
  const payload = sanitizeShellPreferences({ close_behavior: 'explode', auto_start: 'later', runtime_desired_state: 'whatever', background_explainer_seen: 1 });
  assert.equal(payload.close_behavior, 'hide_to_tray');
  assert.equal(payload.auto_start, 'auto_start_if_ready');
  assert.equal(payload.runtime_desired_state, 'running');
  assert.equal(payload.background_explainer_seen, true);
});

test('load/save shell preferences round-trips persisted desktop behavior', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-desktop-pref-'));
  const prefPath = path.join(tmpDir, 'preferences.json');
  const saved = saveShellPreferences(prefPath, {
    close_behavior: 'quit_on_close',
    auto_start: 'manual_start_only',
    runtime_desired_state: 'stopped',
    background_explainer_seen: true,
  });
  assert.equal(saved.close_behavior, 'quit_on_close');
  const loaded = loadShellPreferences(prefPath);
  assert.equal(loaded.close_behavior, 'quit_on_close');
  assert.equal(loaded.auto_start, 'manual_start_only');
  assert.equal(loaded.runtime_desired_state, 'stopped');
  assert.equal(loaded.background_explainer_seen, true);
});

test('load/save last-known-good runtime metadata round-trips bundle identity', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-last-good-'));
  const filePath = path.join(tmpDir, 'runtime_bundle.last_known_good.json');
  const saved = saveLastKnownGoodRuntime(filePath, {
    runtimeVersion: 'cpython-3.12.13+20260303',
    bundleMode: 'python_entrypoint',
    manifestPath: '/repo/app/desktop/runtime-bundle.manifest.json',
  }, {
    appVersion: '0.1.0',
    runtimeUrl: 'http://127.0.0.1:7340',
  });
  assert.equal(saved.runtime_version, 'cpython-3.12.13+20260303');
  const loaded = loadLastKnownGoodRuntime(filePath);
  assert.equal(loaded.app_version, '0.1.0');
  assert.equal(loaded.bundle_mode, 'python_entrypoint');
  assert.equal(loaded.runtime_url, 'http://127.0.0.1:7340');
});

test('loadRuntimeBundleManifest enforces app/runtime compatibility metadata', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-runtime-manifest-'));
  const manifestPath = path.join(tmpDir, 'runtime-bundle.manifest.json');
  fs.writeFileSync(manifestPath, `${JSON.stringify({
    schema: 'modelnumquamoblita.desktop.runtime_bundle.v1',
    bundle_mode: 'python_entrypoint',
    runtime_version: '0.1.0',
    allowed_app_versions: ['0.1.0'],
    entrypoint: 'tools/run_live_runtime.py',
    python_commands: { default: 'python3' },
  }, null, 2)}\n`, 'utf8');
  const manifest = loadRuntimeBundleManifest({ repoRoot: '/repo', appVersion: '0.1.0', manifestPath });
  assert.equal(manifest.runtimeVersion, '0.1.0');
  assert.throws(() => loadRuntimeBundleManifest({ repoRoot: '/repo', appVersion: '9.9.9', manifestPath }), /not compatible/);
});

test('loadRuntimeBundleManifest can resolve the shell-local manifest path for packaged apps', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-shell-manifest-'));
  const manifestPath = path.join(tmpDir, 'runtime-bundle.manifest.json');
  fs.writeFileSync(manifestPath, `${JSON.stringify({
    schema: 'modelnumquamoblita.desktop.runtime_bundle.v1',
    bundle_mode: 'python_entrypoint',
    runtime_version: '0.1.0',
    allowed_app_versions: ['0.1.0'],
    entrypoint: 'tools/run_live_runtime.py',
    python_commands: { default: 'python3' },
  }, null, 2)}\n`, 'utf8');
  const manifest = loadRuntimeBundleManifest({ repoRoot: '/repo', appVersion: '0.1.0', desktopAppRoot: tmpDir });
  assert.equal(manifest.manifestPath, manifestPath);
});

test('buildExpectedBinding extracts the published runtime identity from wizard state', () => {
  const binding = buildExpectedBinding(makeWizardState());
  assert.equal(binding.store_path, '/tmp/store.sqlite3');
  assert.equal(binding.store_fingerprint, 'store_fingerprint_v1');
  assert.equal(binding.episodes_path, '/tmp/episode_cards.reviewed.json');
  assert.equal(binding.build_id, 'build_123');
  assert.equal(binding.artifact_mode, 'published');
});

test('summarizeRuntimeLock distinguishes matching live, foreign live, and stale locks', () => {
  const matching = summarizeRuntimeLock({
    pid: 120,
    host: '127.0.0.1',
    port: 7340,
    store_path: '/tmp/store.sqlite3',
    store_fingerprint: 'store_fingerprint_v1',
    episodes_path: '/tmp/episode_cards.reviewed.json',
  }, {
    expectedBinding: buildExpectedBinding(makeWizardState()),
    expectedHost: '127.0.0.1',
    expectedPort: 7340,
    pidProbeImpl: () => true,
  });
  assert.equal(matching.status, 'matching_live');
  const foreign = summarizeRuntimeLock({ pid: 121, host: '127.0.0.1', port: 7340 }, { pidProbeImpl: () => true });
  assert.equal(foreign.status, 'foreign_live');
  const stale = summarizeRuntimeLock({ pid: 122, host: '127.0.0.1', port: 7340 }, { pidProbeImpl: () => false });
  assert.equal(stale.status, 'stale');
});

test('deriveShellStartupState returns setup_required when no wizard state exists', () => {
  const state = deriveShellStartupState();
  assert.equal(state.status, 'setup_required');
  assert.equal(state.label, 'Setup required');
  assert.equal(state.canStartSetup, true);
  assert.equal(state.canStartRuntime, false);
});

test('deriveShellStartupState returns degraded when artifacts are missing or remap is required', () => {
  const state = deriveShellStartupState({
    wizardRunId: 'wizard_1',
    wizardState: makeWizardState({
      verify: { status: 'Blocked', remap_required: true },
      selected_input: { kind: 'ia_archive', is_valid: true, path: '/tmp/missing_archive.json' },
    }),
    preferences: defaultShellPreferences(),
  });
  assert.equal(state.status, 'degraded');
  assert.equal(state.label, 'Needs attention');
});

test('deriveShellStartupState returns stopped for ready config with manual-start preference', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-shell-state-'));
  const archive = path.join(tmpDir, 'archive.json');
  const store = path.join(tmpDir, 'store.sqlite3');
  const cards = path.join(tmpDir, 'cards.reviewed.json');
  for (const filePath of [archive, store, cards]) {
    fs.writeFileSync(filePath, '{}\n', 'utf8');
  }
  const state = deriveShellStartupState({
    wizardRunId: 'wizard_2',
    wizardState: makeWizardState({
      selected_input: { kind: 'ia_archive', is_valid: true, path: archive },
      store_validation: { kind: 'sqlite_store', is_valid: true, path: store, store_fingerprint: 'store_fingerprint_v1' },
      published_set: { episodes_path: cards, build_id: 'build_123' },
      verify: { status: 'Safe', remap_required: false },
    }),
    preferences: { auto_start: 'manual_start_only' },
  });
  assert.equal(state.status, 'stopped');
  assert.equal(state.readyConfiguration, true);
  assert.equal(state.autoStartAllowed, false);
});


test('deriveShellStartupState does not manufacture a runtime URL for stopped shells', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-shell-stopped-url-'));
  const archive = path.join(tmpDir, 'archive.json');
  const store = path.join(tmpDir, 'store.sqlite3');
  const cards = path.join(tmpDir, 'cards.reviewed.json');
  for (const filePath of [archive, store, cards]) {
    fs.writeFileSync(filePath, '{}\n', 'utf8');
  }
  const state = deriveShellStartupState({
    wizardRunId: 'wizard_stopped',
    wizardState: makeWizardState({
      selected_input: { kind: 'ia_archive', is_valid: true, path: archive },
      store_validation: { kind: 'sqlite_store', is_valid: true, path: store, store_fingerprint: 'store_fingerprint_v1' },
      published_set: { episodes_path: cards, build_id: 'build_123' },
      verify: { status: 'Safe', remap_required: false },
    }),
  });
  assert.equal(state.status, 'stopped');
  assert.equal(state.runtimeUrl, '');
});

test('deriveShellStartupState preserves the live runtime URL when health is present', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-shell-live-url-'));
  const archive = path.join(tmpDir, 'archive.json');
  const store = path.join(tmpDir, 'store.sqlite3');
  const cards = path.join(tmpDir, 'cards.reviewed.json');
  for (const filePath of [archive, store, cards]) {
    fs.writeFileSync(filePath, '{}\n', 'utf8');
  }
  const expected = makeWizardState({
    selected_input: { kind: 'ia_archive', is_valid: true, path: archive },
    store_validation: { kind: 'sqlite_store', is_valid: true, path: store, store_fingerprint: 'store_fingerprint_v1' },
    published_set: { episodes_path: cards, build_id: 'build_123' },
    verify: { status: 'Safe', remap_required: false },
  });
  const state = deriveShellStartupState({
    wizardRunId: 'wizard_live',
    wizardState: expected,
    runtimeUrl: 'http://127.0.0.1:7340',
    runtimeHealth: {
      service: 'modelnumquamoblita-runtime',
      runtime_url: 'http://127.0.0.1:7340',
      binding: buildExpectedBinding(expected),
    },
  });
  assert.equal(state.runtimeUrl, 'http://127.0.0.1:7340');
});

test('deriveShellStartupState returns degraded for stale locks even when config is otherwise ready', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-shell-ready-'));
  const archive = path.join(tmpDir, 'archive.json');
  const store = path.join(tmpDir, 'store.sqlite3');
  const cards = path.join(tmpDir, 'cards.reviewed.json');
  for (const filePath of [archive, store, cards]) {
    fs.writeFileSync(filePath, '{}\n', 'utf8');
  }
  const state = deriveShellStartupState({
    wizardRunId: 'wizard_3',
    wizardState: makeWizardState({
      selected_input: { kind: 'ia_archive', is_valid: true, path: archive },
      store_validation: { kind: 'sqlite_store', is_valid: true, path: store, store_fingerprint: 'store_fingerprint_v1' },
      published_set: { episodes_path: cards, build_id: 'build_123' },
      verify: { status: 'Safe', remap_required: false },
    }),
    lockSummary: { status: 'stale' },
  });
  assert.equal(state.status, 'degraded');
  assert.equal(state.canRepairRuntime, true);
});

test('runtimeHealthMatchesExpected requires runtime identity, version, and binding parity', () => {
  const expected = buildExpectedBinding(makeWizardState());
  const ok = runtimeHealthMatchesExpected({
    service: 'modelnumquamoblita-runtime',
    runtime_version: '0.1.0',
    runtime_url: 'http://127.0.0.1:7340',
    binding: expected,
  }, {
    expectedBinding: expected,
    expectedRuntimeVersion: '0.1.0',
    expectedRuntimeUrl: 'http://127.0.0.1:7340',
  });
  assert.equal(ok, true);
  const bad = runtimeHealthMatchesExpected({ service: 'other', binding: expected }, { expectedBinding: expected });
  assert.equal(bad, false);
  const missingRuntimeUrl = runtimeHealthMatchesExpected({
    service: 'modelnumquamoblita-runtime',
    runtime_version: '0.1.0',
    binding: expected,
  }, {
    expectedBinding: expected,
    expectedRuntimeVersion: '0.1.0',
    expectedRuntimeUrl: 'http://127.0.0.1:7340',
  });
  assert.equal(missingRuntimeUrl, false);
  const setupMatch = runtimeHealthMatchesExpected({
    service: 'modelnumquamoblita-runtime',
    runtime_version: '0.1.0',
    runtime_url: 'http://127.0.0.1:7340',
    binding: {
      store_path: '/repo/runtime/desktop_shell/setup.sqlite3',
      store_fingerprint: 'setup_fp',
      episodes_path: '',
    },
  }, {
    expectedBinding: {
      store_path: '/repo/runtime/desktop_shell/setup.sqlite3',
      store_fingerprint: '',
      episodes_path: '',
    },
    expectedRuntimeVersion: '0.1.0',
    expectedRuntimeUrl: 'http://127.0.0.1:7340',
  });
  assert.equal(setupMatch, true);
});

test('assessExistingRuntime reattaches only to a fully matching runtime', () => {
  const expected = buildExpectedBinding(makeWizardState());
  const attach = assessExistingRuntime({
    healthPayload: {
      service: 'modelnumquamoblita-runtime',
      runtime_version: '0.1.0',
      runtime_url: 'http://127.0.0.1:7340',
      binding: expected,
    },
    lockSummary: { status: 'matching_live' },
    expectedBinding: expected,
    expectedRuntimeVersion: '0.1.0',
    expectedRuntimeUrl: 'http://127.0.0.1:7340',
  });
  assert.equal(attach.action, 'reattach');
  const terminate = assessExistingRuntime({
    healthPayload: { service: 'modelnumquamoblita-runtime', runtime_version: '0.2.0', binding: expected },
    lockSummary: { status: 'matching_live' },
    expectedBinding: expected,
    expectedRuntimeVersion: '0.1.0',
  });
  assert.equal(terminate.action, 'terminate');
  const missingHealthMatching = assessExistingRuntime({
    healthPayload: null,
    lockSummary: { status: 'matching_live' },
    expectedBinding: expected,
    expectedRuntimeVersion: '0.1.0',
  });
  assert.equal(missingHealthMatching.action, 'terminate');
  const missingHealthForeign = assessExistingRuntime({
    healthPayload: null,
    lockSummary: { status: 'foreign_live' },
    expectedBinding: expected,
  });
  assert.equal(missingHealthForeign.action, 'terminate');
});

test('loadLatestWizardState resolves latest wizard run from disk', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mno-wizard-state-'));
  const wizardRoot = path.join(tmpDir, 'wizard_runs');
  fs.mkdirSync(path.join(wizardRoot, 'wizard_1'), { recursive: true });
  fs.writeFileSync(path.join(wizardRoot, 'LATEST.json'), `${JSON.stringify({ run_id: 'wizard_1' })}\n`, 'utf8');
  fs.writeFileSync(path.join(wizardRoot, 'wizard_1', 'wizard_state.json'), `${JSON.stringify(makeWizardState())}\n`, 'utf8');
  const payload = loadLatestWizardState(wizardRoot);
  assert.equal(payload.runId, 'wizard_1');
  assert.equal(payload.state.verify.status, 'Safe');
});

test('collectMissingArtifacts lists missing published artifacts without lying about existing ones', () => {
  const rows = collectMissingArtifacts(makeWizardState({
    selected_input: { kind: 'ia_archive', is_valid: true, path: '/tmp/missing_archive.json' },
    store_validation: { kind: 'sqlite_store', is_valid: true, path: '/tmp/missing_store.sqlite3', store_fingerprint: 'store_fingerprint_v1' },
    published_set: { episodes_path: '/tmp/missing.reviewed.json', build_id: 'build_123' },
  }));
  assert.deepEqual(rows.map((row) => row.target).sort(), ['published_set', 'selected_input', 'store_validation']);
});

test('waitForRuntimeReady retries until health responds ok', async () => {
  let calls = 0;
  let now = 0;
  const ok = await waitForRuntimeReady({
    runtimeHealthUrl: 'http://127.0.0.1:7340/api/runtime/health',
    timeoutMs: 1000,
    intervalMs: 10,
    fetchImpl: async () => {
      calls += 1;
      if (calls < 3) {
        throw new Error('booting');
      }
      return {
        ok: true,
        json: async () => ({ ok: true }),
      };
    },
    sleepImpl: async (ms) => {
      now += ms;
    },
    nowImpl: () => now,
  });
  assert.equal(ok, true);
  assert.equal(calls, 3);
});

test('waitForRuntimeReady fails cleanly on timeout', async () => {
  let now = 0;
  const ok = await waitForRuntimeReady({
    runtimeHealthUrl: 'http://127.0.0.1:7340/api/runtime/health',
    timeoutMs: 25,
    intervalMs: 10,
    fetchImpl: async () => ({ ok: false, json: async () => ({ ok: false }) }),
    sleepImpl: async (ms) => {
      now += ms;
    },
    nowImpl: () => now,
  });
  assert.equal(ok, false);
});

test('waitForChildExit resolves true after exit', async () => {
  const child = new EventEmitter();
  child.exitCode = null;
  setTimeout(() => child.emit('exit', 0, null), 5);
  const exited = await waitForChildExit(child, { timeoutMs: 100 });
  assert.equal(exited, true);
});

test('waitForChildExit resolves false on timeout', async () => {
  const child = new EventEmitter();
  child.exitCode = null;
  const exited = await waitForChildExit(child, { timeoutMs: 10 });
  assert.equal(exited, false);
});

test('formatTimeoutLabel renders configured timeout text', () => {
  assert.equal(formatTimeoutLabel(30000), '30 seconds');
  assert.equal(formatTimeoutLabel(1000), '1 second');
  assert.equal(formatTimeoutLabel(1250), '1.3 seconds');
});

test('loadDesktopAppVersion reads the desktop package version', () => {
  const version = loadDesktopAppVersion(path.resolve(__dirname, '..', '..'));
  assert.match(version, /^\d+\.\d+\.\d+$/);
});

test('stateLabel uses the locked user-facing status names only', () => {
  assert.equal(stateLabel('setup_required'), 'Setup required');
  assert.equal(stateLabel('stopping'), 'Stopped');
  assert.equal(stateLabel('error'), 'Error');
});

test('readRuntimeLock returns empty object for missing files', () => {
  assert.deepEqual(readRuntimeLock(path.join(os.tmpdir(), 'definitely-missing-lock.json')), {});
});
