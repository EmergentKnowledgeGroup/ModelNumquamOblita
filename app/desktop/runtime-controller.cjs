const fs = require('node:fs');
const path = require('node:path');
const { once } = require('node:events');

const DESKTOP_STATUS_LABELS = Object.freeze({
  setup_required: 'Setup required',
  stopped: 'Stopped',
  booting: 'Starting',
  ready: 'Ready',
  degraded: 'Needs attention',
  stopping: 'Stopped',
  error: 'Error',
});

const VALID_STORE_KINDS = new Set(['sqlite_store', 'json_store']);
const VALID_INPUT_KINDS = new Set(['ia_archive', 'sqlite_store', 'json_store']);
const DEFAULT_CLOSE_BEHAVIOR = 'hide_to_tray';
const DEFAULT_AUTO_START = 'auto_start_if_ready';
const DEFAULT_RUNTIME_DESIRED_STATE = 'running';
const DEFAULT_BUNDLE_SCHEMA = 'modelnumquamoblita.desktop.runtime_bundle.v1';

function resolveRepoRoot(explicitRoot) {
  return explicitRoot ? path.resolve(String(explicitRoot)) : path.resolve(__dirname, '..', '..');
}

function resolveShellPaths(repoRoot, { dataRoot = '' } = {}) {
  const resolvedRoot = resolveRepoRoot(repoRoot);
  const runtimeRoot = String(dataRoot || '').trim() ? path.resolve(String(dataRoot)) : path.join(resolvedRoot, 'runtime');
  const desktopShellRoot = path.join(runtimeRoot, 'desktop_shell');
  return {
    repoRoot: resolvedRoot,
    runtimeRoot,
    wizardRunsRoot: path.join(runtimeRoot, 'wizard_runs'),
    publishedSetsRoot: path.join(runtimeRoot, 'episodes'),
    desktopShellRoot,
    desktopPreferencesPath: path.join(desktopShellRoot, 'preferences.json'),
    lastKnownGoodRuntimePath: path.join(desktopShellRoot, 'runtime_bundle.last_known_good.json'),
    desktopManifestPath: path.join(resolvedRoot, 'app', 'desktop', 'runtime-bundle.manifest.json'),
    runtimeLockPath: path.join(runtimeRoot, 'live_runtime.lock.json'),
    setupModeStorePath: path.join(desktopShellRoot, 'setup_mode.sqlite3'),
  };
}

function defaultPythonCommand(platform = process.platform) {
  return platform === 'win32' ? 'python' : 'python3';
}

function parseShellCliArgs(argv) {
  const result = {
    memories: '',
    episodes: '',
    host: '127.0.0.1',
    port: 7340,
    python: '',
    repoRoot: '',
    smokeExitWhenReady: false,
    bootTimeoutMs: 30000,
  };
  const args = Array.isArray(argv) ? argv.slice(0) : [];
  for (let index = 0; index < args.length; index += 1) {
    const token = String(args[index] || '').trim();
    const next = String(args[index + 1] || '').trim();
    if (!token.startsWith('--')) {
      continue;
    }
    if (token === '--memories' && next) {
      result.memories = next;
      index += 1;
      continue;
    }
    if (token === '--episodes' && next) {
      result.episodes = next;
      index += 1;
      continue;
    }
    if (token === '--host' && next) {
      result.host = next;
      index += 1;
      continue;
    }
    if (token === '--port' && next) {
      const port = Number(next);
      if (Number.isFinite(port) && port > 0) {
        result.port = port;
      }
      index += 1;
      continue;
    }
    if (token === '--python' && next) {
      result.python = next;
      index += 1;
      continue;
    }
    if (token === '--repo-root' && next) {
      result.repoRoot = next;
      index += 1;
      continue;
    }
    if (token === '--smoke-exit-when-ready') {
      result.smokeExitWhenReady = true;
      continue;
    }
    if (token === '--boot-timeout-ms' && next) {
      const timeoutMs = Number(next);
      if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
        result.bootTimeoutMs = timeoutMs;
      }
      index += 1;
    }
  }
  return result;
}

function loadJsonObject(filePath, fsImpl = fs) {
  const text = fsImpl.readFileSync(filePath, 'utf8');
  const payload = JSON.parse(text);
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error(`expected JSON object: ${filePath}`);
  }
  return payload;
}

function safePathExists(targetPath, fsImpl = fs) {
  if (!String(targetPath || '').trim()) {
    return false;
  }
  try {
    return fsImpl.existsSync(path.resolve(String(targetPath)));
  } catch (_error) {
    return false;
  }
}

function pathWithinRoot(targetPath, rootPath) {
  const resolvedTarget = path.resolve(String(targetPath || ''));
  const resolvedRoot = path.resolve(String(rootPath || ''));
  const relative = path.relative(resolvedRoot, resolvedTarget);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function defaultShellPreferences() {
  return {
    schema: 'modelnumquamoblita.desktop.preferences.v1',
    close_behavior: DEFAULT_CLOSE_BEHAVIOR,
    auto_start: DEFAULT_AUTO_START,
    runtime_desired_state: DEFAULT_RUNTIME_DESIRED_STATE,
    background_explainer_seen: false,
    updated_at: '',
  };
}

function sanitizeShellPreferences(raw) {
  const defaults = defaultShellPreferences();
  const payload = raw && typeof raw === 'object' ? raw : {};
  const closeBehavior = String(payload.close_behavior || defaults.close_behavior).trim().toLowerCase();
  const autoStart = String(payload.auto_start || defaults.auto_start).trim().toLowerCase();
  const runtimeDesiredState = String(payload.runtime_desired_state || defaults.runtime_desired_state).trim().toLowerCase();
  return {
    ...defaults,
    close_behavior: closeBehavior === 'quit_on_close' ? 'quit_on_close' : DEFAULT_CLOSE_BEHAVIOR,
    auto_start: autoStart === 'manual_start_only' ? 'manual_start_only' : DEFAULT_AUTO_START,
    runtime_desired_state: runtimeDesiredState === 'stopped' ? 'stopped' : DEFAULT_RUNTIME_DESIRED_STATE,
    background_explainer_seen: Boolean(payload.background_explainer_seen),
    updated_at: String(payload.updated_at || '').trim(),
  };
}

function loadShellPreferences(paths, fsImpl = fs) {
  const filePath = typeof paths === 'string' ? paths : paths.desktopPreferencesPath;
  if (!safePathExists(filePath, fsImpl)) {
    return defaultShellPreferences();
  }
  try {
    return sanitizeShellPreferences(loadJsonObject(filePath, fsImpl));
  } catch (_error) {
    return defaultShellPreferences();
  }
}

function loadLastKnownGoodRuntime(paths, fsImpl = fs) {
  const filePath = typeof paths === 'string' ? paths : paths.lastKnownGoodRuntimePath;
  if (!safePathExists(filePath, fsImpl)) {
    return {};
  }
  try {
    const payload = loadJsonObject(filePath, fsImpl);
    return payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {};
  } catch (_error) {
    return {};
  }
}

function saveLastKnownGoodRuntime(paths, runtimeBundle, { appVersion = '', runtimeUrl = '' } = {}, fsImpl = fs) {
  const filePath = typeof paths === 'string' ? paths : paths.lastKnownGoodRuntimePath;
  const bundle = runtimeBundle && typeof runtimeBundle === 'object' ? runtimeBundle : {};
  const payload = {
    schema: 'modelnumquamoblita.desktop.last_known_good_runtime.v1',
    recorded_at: new Date().toISOString(),
    app_version: String(appVersion || '').trim(),
    runtime_version: String(bundle.runtimeVersion || '').trim(),
    bundle_mode: String(bundle.bundleMode || '').trim(),
    manifest_path: String(bundle.manifestPath || '').trim(),
    runtime_url: String(runtimeUrl || '').trim(),
  };
  fsImpl.mkdirSync(path.dirname(filePath), { recursive: true });
  fsImpl.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  return payload;
}

function saveShellPreferences(paths, preferences, fsImpl = fs) {
  const filePath = typeof paths === 'string' ? paths : paths.desktopPreferencesPath;
  const sanitized = sanitizeShellPreferences(preferences);
  const payload = {
    ...sanitized,
    updated_at: new Date().toISOString(),
  };
  fsImpl.mkdirSync(path.dirname(filePath), { recursive: true });
  fsImpl.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  return payload;
}

function loadDesktopAppVersion(repoRoot, fsImpl = fs, packagePath = '') {
  const targetPath = packagePath || path.join(resolveRepoRoot(repoRoot), 'app', 'desktop', 'package.json');
  const payload = loadJsonObject(targetPath, fsImpl);
  const version = String(payload.version || '').trim();
  if (!version) {
    throw new Error(`desktop package version missing: ${targetPath}`);
  }
  return version;
}

function sanitizeRuntimeBundleManifest(raw, { manifestPath = '', appVersion = '' } = {}) {
  const payload = raw && typeof raw === 'object' ? raw : {};
  const schema = String(payload.schema || '').trim();
  if (schema !== DEFAULT_BUNDLE_SCHEMA) {
    throw new Error(`runtime bundle manifest schema must be ${DEFAULT_BUNDLE_SCHEMA}`);
  }
  const bundleMode = String(payload.bundle_mode || '').trim().toLowerCase();
  if (!['python_entrypoint', 'executable'].includes(bundleMode)) {
    throw new Error('runtime bundle manifest bundle_mode must be python_entrypoint or executable');
  }
  const runtimeVersion = String(payload.runtime_version || '').trim();
  if (!runtimeVersion) {
    throw new Error('runtime bundle manifest missing runtime_version');
  }
  const allowedAppVersions = Array.isArray(payload.allowed_app_versions)
    ? payload.allowed_app_versions.map((item) => String(item || '').trim()).filter(Boolean)
    : [];
  if (!allowedAppVersions.length) {
    throw new Error('runtime bundle manifest missing allowed_app_versions');
  }
  if (appVersion && !allowedAppVersions.includes(appVersion)) {
    throw new Error(`desktop app version ${appVersion} is not compatible with runtime bundle ${runtimeVersion}`);
  }
  const entrypoint = String(payload.entrypoint || '').trim();
  const executablePath = String(payload.executable_path || '').trim();
  const pythonCommands = payload.python_commands && typeof payload.python_commands === 'object' ? payload.python_commands : {};
  if (bundleMode === 'python_entrypoint' && !entrypoint) {
    throw new Error('runtime bundle manifest missing entrypoint for python_entrypoint bundle_mode');
  }
  if (bundleMode === 'executable' && !executablePath) {
    throw new Error('runtime bundle manifest missing executable_path for executable bundle_mode');
  }
  return {
    schema,
    bundleMode,
    runtimeVersion,
    allowedAppVersions,
    entrypoint: bundleMode === 'python_entrypoint' ? entrypoint : '',
    executablePath,
    pythonCommands,
    manifestPath,
  };
}

function loadRuntimeBundleManifest({ repoRoot, appVersion = '', fsImpl = fs, manifestPath = '', desktopAppRoot = '' } = {}) {
  const resolvedRoot = resolveRepoRoot(repoRoot);
  const shellManifestPath = desktopAppRoot ? path.join(path.resolve(String(desktopAppRoot)), 'runtime-bundle.manifest.json') : '';
  const targetPath = manifestPath || shellManifestPath || path.join(resolvedRoot, 'app', 'desktop', 'runtime-bundle.manifest.json');
  if (!safePathExists(targetPath, fsImpl)) {
    throw new Error(`runtime bundle manifest not found: ${targetPath}`);
  }
  return sanitizeRuntimeBundleManifest(loadJsonObject(targetPath, fsImpl), { manifestPath: targetPath, appVersion });
}

function readRuntimeLock(paths, fsImpl = fs) {
  const filePath = typeof paths === 'string' ? paths : paths.runtimeLockPath;
  if (!safePathExists(filePath, fsImpl)) {
    return {};
  }
  try {
    return loadJsonObject(filePath, fsImpl);
  } catch (_error) {
    return {};
  }
}

function pidIsAlive(pid, pidProbeImpl = (targetPid) => {
  process.kill(targetPid, 0);
  return true;
}) {
  const numericPid = Number(pid);
  if (!Number.isInteger(numericPid) || numericPid <= 0) {
    return false;
  }
  try {
    return Boolean(pidProbeImpl(numericPid));
  } catch (_error) {
    return false;
  }
}

function buildExpectedBinding(wizardState) {
  const state = wizardState && typeof wizardState === 'object' ? wizardState : {};
  const storeValidation = state.store_validation && typeof state.store_validation === 'object' ? state.store_validation : {};
  const publishedSet = state.published_set && typeof state.published_set === 'object' ? state.published_set : {};
  return {
    store_path: String(storeValidation.path || state.store_path || '').trim(),
    store_fingerprint: String(storeValidation.store_fingerprint || '').trim(),
    episodes_path: String(publishedSet.episodes_path || state.last_compiled_reviewed_path || '').trim(),
    build_id: String(publishedSet.build_id || '').trim(),
    artifact_mode: String(publishedSet.episodes_path ? 'published' : '').trim(),
  };
}

function summarizeRuntimeLock(lockPayload, { expectedBinding = {}, expectedHost = '', expectedPort = 0, pidProbeImpl } = {}) {
  const payload = lockPayload && typeof lockPayload === 'object' ? lockPayload : {};
  if (!Object.keys(payload).length) {
    return {
      status: 'missing',
      checked_at: new Date().toISOString(),
      owner_pid: 0,
      owner_host: '',
      owner_port: 0,
      matches_expected: false,
    };
  }
  const ownerPid = Number(payload.pid || 0);
  const ownerHost = String(payload.host || '').trim();
  const ownerPort = Number(payload.port || 0);
  const alive = pidIsAlive(ownerPid, pidProbeImpl);
  const expectedStoreFingerprint = String(expectedBinding.store_fingerprint || '').trim();
  const expectedEpisodesPath = String(expectedBinding.episodes_path || '').trim();
  const expectedStorePath = String(expectedBinding.store_path || '').trim();
  const bindingMatches = Boolean(expectedStoreFingerprint && expectedEpisodesPath && expectedStorePath)
    && String(payload.store_fingerprint || '').trim() === expectedStoreFingerprint
    && String(payload.episodes_path || '').trim() === expectedEpisodesPath
    && String(payload.store_path || '').trim() === expectedStorePath;
  const addressMatches = (!String(expectedHost || '').trim() || ownerHost === String(expectedHost || '').trim())
    && (!Number(expectedPort) || ownerPort === Number(expectedPort));
  let status = 'stale';
  if (alive && bindingMatches && addressMatches) {
    status = 'matching_live';
  } else if (alive) {
    status = 'foreign_live';
  }
  return {
    status,
    checked_at: String(payload.checked_at || '').trim() || new Date().toISOString(),
    owner_pid: ownerPid,
    owner_host: ownerHost,
    owner_port: ownerPort,
    matches_expected: bindingMatches && addressMatches,
    token: String(payload.token || '').trim(),
    store_path: String(payload.store_path || '').trim(),
    store_fingerprint: String(payload.store_fingerprint || '').trim(),
    episodes_path: String(payload.episodes_path || '').trim(),
  };
}

function loadLatestWizardState(paths, fsImpl = fs) {
  const wizardRunsRoot = typeof paths === 'string' ? paths : paths.wizardRunsRoot;
  const latestPath = path.join(wizardRunsRoot, 'LATEST.json');
  let runId = '';
  if (safePathExists(latestPath, fsImpl)) {
    try {
      runId = String(loadJsonObject(latestPath, fsImpl).run_id || '').trim();
    } catch (_error) {
      runId = '';
    }
  }
  if (!runId && safePathExists(wizardRunsRoot, fsImpl)) {
    const entries = fsImpl.readdirSync(wizardRunsRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && entry.name.startsWith('wizard_'))
      .map((entry) => ({ name: entry.name, statePath: path.join(wizardRunsRoot, entry.name, 'wizard_state.json') }))
      .filter((entry) => safePathExists(entry.statePath, fsImpl))
      .sort((left, right) => {
        const leftTime = fsImpl.statSync(left.statePath).mtimeMs;
        const rightTime = fsImpl.statSync(right.statePath).mtimeMs;
        return rightTime - leftTime;
      });
    if (entries.length) {
      runId = entries[0].name;
    }
  }
  if (!runId) {
    return { runId: '', state: null };
  }
  const statePath = path.join(wizardRunsRoot, runId, 'wizard_state.json');
  if (!safePathExists(statePath, fsImpl)) {
    return { runId: '', state: null };
  }
  try {
    return { runId, state: loadJsonObject(statePath, fsImpl), statePath };
  } catch (_error) {
    return { runId, state: null, statePath };
  }
}

function collectMissingArtifacts(wizardState, fsImpl = fs) {
  const state = wizardState && typeof wizardState === 'object' ? wizardState : {};
  const selectedInput = state.selected_input && typeof state.selected_input === 'object' ? state.selected_input : {};
  const storeValidation = state.store_validation && typeof state.store_validation === 'object' ? state.store_validation : {};
  const buildInfo = state.build_info && typeof state.build_info === 'object' ? state.build_info : {};
  const publishedSet = state.published_set && typeof state.published_set === 'object' ? state.published_set : {};
  const rows = [];
  function addRow(target, label, rawPath) {
    const cleanPath = String(rawPath || '').trim();
    if (!cleanPath) {
      return;
    }
    const exists = safePathExists(cleanPath, fsImpl);
    if (exists) {
      return;
    }
    rows.push({ target, label, path: cleanPath });
  }
  const selectedKind = String(selectedInput.kind || '').trim();
  if (VALID_INPUT_KINDS.has(selectedKind)) {
    addRow('selected_input', 'Selected input', selectedInput.path);
  }
  if (VALID_STORE_KINDS.has(String(storeValidation.kind || '').trim())) {
    addRow('store_validation', 'Runtime store', storeValidation.path || state.store_path);
  }
  addRow('draft_cards', 'Draft episode cards', buildInfo.draft_path || state.last_built_episode_draft_path);
  addRow('published_set', 'Published reviewed set', publishedSet.episodes_path || state.last_compiled_reviewed_path);
  return rows;
}

function stateLabel(status) {
  return DESKTOP_STATUS_LABELS[String(status || '').trim()] || DESKTOP_STATUS_LABELS.error;
}

function deriveShellStartupState({ wizardRunId = '', wizardState = null, preferences = defaultShellPreferences(), lockSummary = {}, runtimeUrl = '', runtimeManifest = null, runtimeHealth = null, fsImpl = fs } = {}) {
  const prefs = sanitizeShellPreferences(preferences);
  const resolvedState = wizardState && typeof wizardState === 'object' ? wizardState : null;
  const runtimeHealthPayload = runtimeHealth && typeof runtimeHealth === 'object' ? runtimeHealth : null;
  const base = {
    status: 'setup_required',
    label: stateLabel('setup_required'),
    bootStage: 'Open setup to import an archive or choose an existing MNO store.',
    runtimeUrl: String(runtimeUrl || '').trim(),
    storePath: '',
    episodeCardsPath: '',
    wizardRunId: String(wizardRunId || '').trim(),
    lastError: '',
    preferences: prefs,
    readyConfiguration: false,
    autoStartAllowed: false,
    canStartSetup: true,
    canStartRuntime: false,
    canRepairRuntime: false,
    missingArtifacts: [],
    lock: lockSummary || {},
    runtimeBundle: runtimeManifest || null,
    runtimeHealth: runtimeHealthPayload,
    statusReason: '',
  };

  if (!resolvedState) {
    base.statusReason = 'No prior wizard state exists.';
    return { ...base, label: stateLabel(base.status) };
  }

  const selectedInput = resolvedState.selected_input && typeof resolvedState.selected_input === 'object' ? resolvedState.selected_input : {};
  const storeValidation = resolvedState.store_validation && typeof resolvedState.store_validation === 'object' ? resolvedState.store_validation : {};
  const publishedSet = resolvedState.published_set && typeof resolvedState.published_set === 'object' ? resolvedState.published_set : {};
  const verify = resolvedState.verify && typeof resolvedState.verify === 'object' ? resolvedState.verify : {};
  const activation = resolvedState.activation && typeof resolvedState.activation === 'object' ? resolvedState.activation : {};
  const draftOverride = activation.draft_override && typeof activation.draft_override === 'object' ? activation.draft_override : {};
  const missingArtifacts = collectMissingArtifacts(resolvedState, fsImpl);
  const verifyStatus = String(verify.status || 'Unknown').trim();
  const hasValidInput = VALID_INPUT_KINDS.has(String(selectedInput.kind || '').trim()) && Boolean(selectedInput.is_valid);
  const hasValidStore = VALID_STORE_KINDS.has(String(storeValidation.kind || '').trim())
    && Boolean(storeValidation.is_valid)
    && safePathExists(storeValidation.path || resolvedState.store_path, fsImpl);
  const hasPublishedSet = safePathExists(publishedSet.episodes_path || resolvedState.last_compiled_reviewed_path, fsImpl);
  const readyConfiguration = hasValidInput && hasValidStore && hasPublishedSet && verifyStatus === 'Safe' && !Boolean(draftOverride.active) && !Boolean(verify.remap_required) && !missingArtifacts.length;
  const explicitStop = prefs.runtime_desired_state === 'stopped';

  base.storePath = String(storeValidation.path || resolvedState.store_path || '').trim();
  base.episodeCardsPath = String(publishedSet.episodes_path || resolvedState.last_compiled_reviewed_path || '').trim();
  base.readyConfiguration = readyConfiguration;
  base.autoStartAllowed = readyConfiguration && prefs.auto_start === 'auto_start_if_ready' && !explicitStop;
  base.canStartRuntime = readyConfiguration;
  base.missingArtifacts = missingArtifacts;

  if (runtimeManifest && !runtimeManifest.runtimeVersion) {
    return {
      ...base,
      status: 'error',
      label: stateLabel('error'),
      bootStage: 'Desktop runtime bundle metadata is missing or invalid.',
      statusReason: 'Runtime manifest is invalid.',
      lastError: 'The desktop app cannot prove which managed runtime it should launch.',
    };
  }

  if (missingArtifacts.length || Boolean(verify.remap_required)) {
    return {
      ...base,
      status: 'degraded',
      label: stateLabel('degraded'),
      bootStage: 'A required store or artifact moved or went missing. Repair it before startup.',
      statusReason: 'Artifact repair is required.',
      canRepairRuntime: String(lockSummary.status || '') === 'stale',
    };
  }

  if (Boolean(draftOverride.active)) {
    return {
      ...base,
      status: 'degraded',
      label: stateLabel('degraded'),
      bootStage: 'Developer-only draft activation is recorded. Reset or publish a reviewed set before normal startup.',
      statusReason: 'Draft activation is not normal ready state.',
      canRepairRuntime: String(lockSummary.status || '') === 'stale',
    };
  }

  if (!hasValidInput || !hasValidStore || !hasPublishedSet || verifyStatus !== 'Safe') {
    const reasons = [];
    if (!hasValidInput) {
      reasons.push('select a valid archive or MNO store');
    }
    if (!hasValidStore) {
      reasons.push('import or choose a valid MNO store');
    }
    if (!hasPublishedSet) {
      reasons.push('publish a reviewed set');
    }
    if (verifyStatus !== 'Safe') {
      reasons.push('run verification until the status is Safe');
    }
    return {
      ...base,
      status: 'setup_required',
      label: stateLabel('setup_required'),
      bootStage: 'Finish setup before the desktop app can serve memory in the background.',
      statusReason: reasons.join('; '),
    };
  }

  if (String(lockSummary.status || '') === 'stale') {
    return {
      ...base,
      status: 'degraded',
      label: stateLabel('degraded'),
      bootStage: 'A stale runtime claim must be repaired before normal startup.',
      statusReason: 'The last runtime owner is gone, but its lock is still present.',
      canRepairRuntime: true,
    };
  }

  if (String(lockSummary.status || '') === 'foreign_live') {
    return {
      ...base,
      status: 'degraded',
      label: stateLabel('degraded'),
      bootStage: 'An existing runtime is already live. The desktop app must verify or recover it before startup.',
      statusReason: 'A live runtime already owns the configured address or binding.',
      canRepairRuntime: true,
    };
  }

  if (explicitStop || prefs.auto_start === 'manual_start_only') {
    return {
      ...base,
      status: 'stopped',
      label: stateLabel('stopped'),
      bootStage: 'Runtime is configured and ready, but it will stay stopped until you start it.',
      statusReason: explicitStop ? 'Runtime was explicitly stopped.' : 'Manual-start-only is enabled.',
    };
  }

  return {
    ...base,
    status: 'stopped',
    label: stateLabel('stopped'),
    bootStage: 'Runtime is configured and ready to start.',
    statusReason: 'Ready configuration detected.',
  };
}

function buildRuntimeLaunchPlan({
  repoRoot,
  runtimeManifest,
  pythonCommand = '',
  memories = '',
  episodes = '',
  host = '127.0.0.1',
  port = 7340,
  setupMode = false,
  platform = process.platform,
  setupModeStorePath = '',
  requireBundledRuntime = false,
} = {}) {
  const resolvedRoot = resolveRepoRoot(repoRoot);
  const runtimePort = Number.isFinite(Number(port)) && Number(port) > 0 ? Number(port) : 7340;
  const runtimeHost = String(host || '127.0.0.1').trim() || '127.0.0.1';
  const manifest = runtimeManifest && runtimeManifest.bundleMode
    ? runtimeManifest
    : sanitizeRuntimeBundleManifest(runtimeManifest, { manifestPath: runtimeManifest?.manifestPath || '', appVersion: '' });
  let command = '';
  let args = [];
  const entrypointPath = manifest.bundleMode === 'python_entrypoint' ? path.resolve(resolvedRoot, manifest.entrypoint) : '';
  if (manifest.bundleMode !== 'executable' && requireBundledRuntime) {
    if (!pathWithinRoot(entrypointPath, resolvedRoot)) {
      throw new Error(`bundled runtime entrypoint escapes repo root: ${entrypointPath}`);
    }
    if (!safePathExists(entrypointPath)) {
      throw new Error(`bundled runtime entrypoint not found: ${entrypointPath}`);
    }
  }
  if (manifest.bundleMode === 'executable') {
    command = path.resolve(resolvedRoot, manifest.executablePath);
    if (requireBundledRuntime && !pathWithinRoot(command, resolvedRoot)) {
      throw new Error(`bundled runtime executable escapes repo root: ${command}`);
    }
    if (requireBundledRuntime && !safePathExists(command)) {
      throw new Error(`bundled runtime executable not found: ${command}`);
    }
  } else {
    const platformCommand = String(manifest.pythonCommands[platform] || manifest.pythonCommands.default || '').trim();
    const explicitPython = String(pythonCommand || '').trim();
    if (requireBundledRuntime && explicitPython) {
      throw new Error('bundled runtime launch does not allow overriding pythonCommand');
    }
    if (explicitPython) {
      command = explicitPython;
    } else if (platformCommand && !path.isAbsolute(platformCommand) && /[\\/]/.test(platformCommand)) {
      const bundledPython = path.resolve(resolvedRoot, platformCommand);
      if (requireBundledRuntime && !pathWithinRoot(bundledPython, resolvedRoot)) {
        throw new Error(`bundled Python runtime escapes repo root: ${bundledPython}`);
      }
      if (safePathExists(bundledPython)) {
        command = bundledPython;
      } else if (requireBundledRuntime) {
        throw new Error(`bundled Python runtime not found: ${bundledPython}`);
      } else {
        command = defaultPythonCommand(platform);
      }
    } else if (requireBundledRuntime) {
      throw new Error('bundled runtime launch requires a repo-local python command path');
    } else {
      command = platformCommand || defaultPythonCommand(platform);
    }
    args = [entrypointPath];
  }
  args.push('--host', runtimeHost, '--port', String(runtimePort));
  if (setupMode) {
    args.push('--setup-mode');
    if (String(setupModeStorePath || '').trim()) {
      args.push('--setup-store', path.resolve(String(setupModeStorePath)));
    }
  } else {
    if (String(memories || '').trim()) {
      args.push('--memories', path.resolve(String(memories)));
    }
    if (String(episodes || '').trim()) {
      args.push('--episodes', path.resolve(String(episodes)));
    }
  }
  return {
    repoRoot: resolvedRoot,
    cwd: resolvedRoot,
    command,
    args,
    runtimeUrl: `http://${runtimeHost}:${runtimePort}`,
    runtimeHealthUrl: `http://${runtimeHost}:${runtimePort}/api/runtime/health`,
    runtimeShutdownUrl: `http://${runtimeHost}:${runtimePort}/api/runtime/desktop/shutdown`,
    runtimeVersion: manifest.runtimeVersion,
    setupMode: Boolean(setupMode),
    launchMode: setupMode ? 'setup_mode' : 'normal',
  };
}

function buildRuntimeSpawnOptions({ cwd, env = process.env, platform = process.platform } = {}) {
  return {
    cwd,
    env: { ...env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: false,
    windowsHide: platform === 'win32',
  };
}

function parseRuntimeStdoutLine(line) {
  const match = /^([a-z_]+)=(.*)$/.exec(String(line || '').trim());
  if (!match) {
    return null;
  }
  return { key: match[1], value: match[2] };
}

function formatTimeoutLabel(timeoutMs) {
  const safeTimeoutMs = Math.max(0, Number(timeoutMs) || 0);
  const wholeSeconds = safeTimeoutMs / 1000;
  const seconds = Number.isInteger(wholeSeconds) ? String(wholeSeconds) : wholeSeconds.toFixed(1);
  return `${seconds} ${Number(wholeSeconds) === 1 ? 'second' : 'seconds'}`;
}

async function fetchRuntimeHealthOnce({ runtimeHealthUrl, fetchImpl = globalThis.fetch } = {}) {
  if (typeof fetchImpl !== 'function') {
    throw new Error('fetch implementation is required');
  }
  try {
    const response = await fetchImpl(runtimeHealthUrl, { method: 'GET' });
    if (!response || !response.ok) {
      return null;
    }
    const payload = await response.json();
    return payload && payload.ok === true ? payload : null;
  } catch (_error) {
    return null;
  }
}

function runtimeHealthMatchesExpected(healthPayload, { expectedBinding = {}, expectedRuntimeVersion = '', expectedRuntimeUrl = '' } = {}) {
  const payload = healthPayload && typeof healthPayload === 'object' ? healthPayload : {};
  const binding = payload.binding && typeof payload.binding === 'object' ? payload.binding : {};
  const runtimeVersion = String(payload.runtime_version || '').trim();
  const runtimeIdentity = String(payload.service || '').trim();
  const runtimeUrl = String(payload.runtime_url || '').trim();
  const expectedStoreFingerprint = String(expectedBinding.store_fingerprint || '').trim();
  const expectedEpisodesPath = String(expectedBinding.episodes_path || '').trim();
  const expectedStorePath = String(expectedBinding.store_path || '').trim();
  const hasExpectedBinding = Boolean(expectedStoreFingerprint || expectedEpisodesPath || expectedStorePath);
  if (runtimeIdentity !== 'modelnumquamoblita-runtime') {
    return false;
  }
  if (expectedRuntimeVersion && runtimeVersion !== expectedRuntimeVersion) {
    return false;
  }
  if (expectedRuntimeUrl && runtimeUrl !== expectedRuntimeUrl) {
    return false;
  }
  if (!hasExpectedBinding) {
    return false;
  }
  const actualStoreFingerprint = String(binding.store_fingerprint || '').trim();
  const actualEpisodesPath = String(binding.episodes_path || '').trim();
  const actualStorePath = String(binding.store_path || '').trim();
  return (!expectedStoreFingerprint || actualStoreFingerprint === expectedStoreFingerprint)
    && (!expectedEpisodesPath || actualEpisodesPath === expectedEpisodesPath)
    && (!expectedStorePath || actualStorePath === expectedStorePath);
}

function assessExistingRuntime({ healthPayload = null, lockSummary = {}, expectedBinding = {}, expectedRuntimeVersion = '', expectedRuntimeUrl = '' } = {}) {
  if (!healthPayload) {
    if (String(lockSummary.status || '') === 'matching_live') {
      return { action: 'terminate', reason: 'health_missing_matching_live_lock' };
    }
    if (String(lockSummary.status || '') === 'foreign_live') {
      return { action: 'terminate', reason: 'health_missing_foreign_live_lock' };
    }
    return { action: 'none', reason: 'not_running' };
  }
  if (runtimeHealthMatchesExpected(healthPayload, { expectedBinding, expectedRuntimeVersion, expectedRuntimeUrl })) {
    return { action: 'reattach', reason: 'matching_runtime' };
  }
  if (String(lockSummary.status || '') === 'matching_live') {
    return { action: 'terminate', reason: 'runtime_metadata_mismatch' };
  }
  if (String(lockSummary.status || '') === 'foreign_live') {
    return { action: 'terminate', reason: 'foreign_live_runtime' };
  }
  return { action: 'terminate', reason: 'untrusted_runtime' };
}

async function requestRuntimeShutdown({ runtimeShutdownUrl, fetchImpl = globalThis.fetch } = {}) {
  if (typeof fetchImpl !== 'function') {
    throw new Error('fetch implementation is required');
  }
  const response = await fetchImpl(runtimeShutdownUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  if (!response || !response.ok) {
    throw new Error(`runtime shutdown failed with status ${response?.status || 'unknown'}`);
  }
  return response.json();
}

async function waitForRuntimeReady({
  runtimeHealthUrl,
  timeoutMs = 30000,
  intervalMs = 250,
  fetchImpl = globalThis.fetch,
  sleepImpl = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  nowImpl = () => Date.now(),
} = {}) {
  if (typeof fetchImpl !== 'function') {
    throw new Error('fetch implementation is required');
  }
  const startedAt = Number(nowImpl());
  while ((Number(nowImpl()) - startedAt) <= timeoutMs) {
    try {
      const response = await fetchImpl(runtimeHealthUrl, { method: 'GET' });
      if (response && response.ok) {
        const payload = await response.json();
        if (payload && payload.ok === true) {
          return true;
        }
      }
    } catch (_error) {
      // Runtime may still be booting; keep polling until timeout.
    }
    await sleepImpl(intervalMs);
  }
  return false;
}

async function waitForChildExit(child, { timeoutMs = 2500 } = {}) {
  if (!child || typeof child.once !== 'function') {
    return true;
  }
  if (child.exitCode !== null && child.exitCode !== undefined) {
    return true;
  }
  const exitPromise = once(child, 'exit').then(() => true);
  const timeoutPromise = new Promise((resolve) => {
    setTimeout(() => resolve(false), timeoutMs);
  });
  return Promise.race([exitPromise, timeoutPromise]);
}

module.exports = {
  DESKTOP_STATUS_LABELS,
  assessExistingRuntime,
  buildExpectedBinding,
  buildRuntimeLaunchPlan,
  buildRuntimeSpawnOptions,
  collectMissingArtifacts,
  defaultPythonCommand,
  defaultShellPreferences,
  deriveShellStartupState,
  fetchRuntimeHealthOnce,
  formatTimeoutLabel,
  loadDesktopAppVersion,
  loadJsonObject,
  loadLatestWizardState,
  loadLastKnownGoodRuntime,
  loadRuntimeBundleManifest,
  loadShellPreferences,
  parseRuntimeStdoutLine,
  parseShellCliArgs,
  pidIsAlive,
  pathWithinRoot,
  readRuntimeLock,
  requestRuntimeShutdown,
  resolveRepoRoot,
  resolveShellPaths,
  runtimeHealthMatchesExpected,
  sanitizeRuntimeBundleManifest,
  sanitizeShellPreferences,
  saveLastKnownGoodRuntime,
  saveShellPreferences,
  safePathExists,
  stateLabel,
  summarizeRuntimeLock,
  waitForChildExit,
  waitForRuntimeReady,
};
