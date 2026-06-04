const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { app, BrowserWindow, dialog, ipcMain, Menu, Tray, nativeImage, shell } = require('electron');
const {
  assessExistingRuntime,
  buildExpectedBinding,
  buildRuntimeLaunchPlan,
  buildRuntimeSpawnOptions,
  defaultPythonCommand,
  deriveShellStartupState,
  fetchRuntimeHealthOnce,
  formatTimeoutLabel,
  hydratedRuntimeUrl,
  loadDesktopAppVersion,
  loadLastKnownGoodRuntime,
  loadLatestWizardState,
  loadRuntimeBundleManifest,
  loadShellPreferences,
  normalizePlatformPath,
  buildWindowsDetachedRuntimeLauncher,
  resolveWindowsGuiPythonCommand,
  parseRuntimeStdoutLine,
  parseShellCliArgs,
  normalizeRuntimePort,
  readRuntimeLock,
  requestRuntimeShutdown,
  resolveShellPaths,
  runtimeHealthMatchesExpected,
  saveLastKnownGoodRuntime,
  saveShellPreferences,
  summarizeRuntimeLock,
  waitForChildExit,
  waitForRuntimeReady,
} = require('./runtime-controller.cjs');
const { buildTrayMenuTemplate } = require('./tray-controller.cjs');

const cli = parseShellCliArgs(process.argv.slice(1));
const desktopAppRoot = __dirname;
const packagedRepoRoot = app.isPackaged ? path.join(process.resourcesPath, 'mno_bundle') : '';
const explicitStateRoot = String(process.env.MNO_DESKTOP_STATE_ROOT || '').trim();
const shellPaths = resolveShellPaths(cli.repoRoot || process.env.MNO_REPO_ROOT || packagedRepoRoot || '', {
  dataRoot: explicitStateRoot || (app.isPackaged ? path.join(app.getPath('userData'), 'runtime') : ''),
});
const appVersion = String(app.getVersion() || '').trim() || loadDesktopAppVersion(shellPaths.repoRoot, fs, path.join(desktopAppRoot, 'package.json'));
const singleInstanceLock = app.requestSingleInstanceLock();

if (!singleInstanceLock) {
  app.exit(0);
}

const state = {
  status: 'setup_required',
  label: 'Setup required',
  runtimeUrl: '',
  storePath: '',
  episodeCardsPath: '',
  repoRoot: shellPaths.repoRoot,
  runtimeRoot: shellPaths.runtimeRoot,
  wizardRunsPath: shellPaths.wizardRunsRoot,
  publishedSetsPath: shellPaths.publishedSetsRoot,
  logPath: '',
  lastError: '',
  bootStage: 'Open setup to import an archive or choose an existing MNO store.',
  wizardRunId: '',
  preferences: loadShellPreferences(shellPaths),
  readyConfiguration: false,
  autoStartAllowed: false,
  canStartSetup: true,
  canStartRuntime: false,
  canRepairRuntime: false,
  missingArtifacts: [],
  lock: {},
  runtimeBundle: null,
  lastKnownGoodRuntime: loadLastKnownGoodRuntime(shellPaths),
  runtimeHealth: null,
  trayAvailable: false,
  trayFallbackActive: false,
  trayFallbackMessage: '',
  appVersion,
  mcpStatus: 'not_installed',
  mcpLabel: 'Not installed',
  mcpUrl: 'http://127.0.0.1:8765/mcp',
  mcpLastError: '',
  mcpArtifactMode: 'reviewed',
  mcpRole: 'viewer',
  mcpCompatMode: 'strict',
  mcpMutationsEnabled: false,
  mcpProfilesSummary: '',
};

writeShellLog(`[startup] argv=${JSON.stringify(process.argv.slice(1))} smoke_exit=${Boolean(cli.smokeExitWhenReady)} repo_root=${shellPaths.repoRoot}`);

let mainWindow = null;
let runtimeWindow = null;
let runtimeChild = null;
let mcpSidecarChild = null;
let tray = null;
let shuttingDown = false;
let expectedRuntimeExit = false;
let quitAfterCleanup = false;
let restartPromise = null;
let runtimeLaunchPlan = null;
let mcpSidecarPlan = null;
let runtimeAttachmentMode = '';
let latestWizardState = null;
let latestExpectedBinding = {};
let latestExpectedMcpBinding = {};
let runtimeBundleManifest = null;
let restartHistory = [];

const MCP_SIDECAR_HOST = '127.0.0.1';
const MCP_SIDECAR_PORT = 8765;
const MANAGED_MCP_PROFILE_DEFAULTS = Object.freeze({
  draft: Object.freeze({ defaultRole: 'viewer', compatMode: 'strict', mutationsEnabled: true }),
  reviewed: Object.freeze({ defaultRole: 'viewer', compatMode: 'strict', mutationsEnabled: false }),
});
const MANAGED_MCP_ALLOWED_ROLES = new Set(['viewer', 'operator', 'admin']);

function normalizeManagedMcpArtifactMode(value) {
  return String(value || '').trim().toLowerCase() === 'draft' ? 'draft' : 'reviewed';
}

function normalizeManagedMcpProfile(profile = {}, artifactMode = 'reviewed') {
  const mode = normalizeManagedMcpArtifactMode(artifactMode);
  const defaults = MANAGED_MCP_PROFILE_DEFAULTS[mode];
  const requestedRole = String(profile.defaultRole || profile.default_role || defaults.defaultRole).trim().toLowerCase();
  const compatMode = String(profile.compatMode || profile.compat_mode || defaults.compatMode).trim().toLowerCase() || defaults.compatMode;
  return {
    defaultRole: MANAGED_MCP_ALLOWED_ROLES.has(requestedRole) ? requestedRole : defaults.defaultRole,
    compatMode: compatMode || defaults.compatMode,
    mutationsEnabled: Object.prototype.hasOwnProperty.call(profile, 'mutationsEnabled')
      ? Boolean(profile.mutationsEnabled)
      : Object.prototype.hasOwnProperty.call(profile, 'mutations_enabled')
        ? Boolean(profile.mutations_enabled)
        : defaults.mutationsEnabled,
  };
}

function mcpSidecarSettingsPath() {
  return path.join(shellPaths.desktopShellRoot, 'mcp_sidecar_settings.json');
}

function localLogStamp(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const seconds = String(date.getSeconds()).padStart(2, '0');
  const millis = String(date.getMilliseconds()).padStart(3, '0');
  return `${year}-${month}-${day} | ${hours}:${minutes}:${seconds}.${millis}`;
}

function expectedRuntimeHealthVersion() {
  return String(appVersion || '').trim();
}

function writeShellDiagnostic(line) {
  try {
    const repoRoot = shellPaths?.repoRoot || path.resolve(__dirname, '..', '..');
    const runtimeRoot = shellPaths?.runtimeRoot || path.join(repoRoot, 'runtime');
    const desktopShellRoot = path.join(runtimeRoot, 'desktop_shell');
    fs.mkdirSync(desktopShellRoot, { recursive: true });
    const target = path.join(desktopShellRoot, 'desktop_shell_diagnostic.log');
    fs.appendFileSync(target, `${localLogStamp()} ${line}${os.EOL}`, 'utf8');
  } catch (_error) {
    // Best effort only.
  }
}

function createRuntimeChildLogBundle() {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const stdoutPath = path.join(logDir(), `runtime_child_${timestamp}.stdout.log`);
  const stderrPath = path.join(logDir(), `runtime_child_${timestamp}.stderr.log`);
  const stdoutFd = fs.openSync(stdoutPath, 'a');
  const stderrFd = fs.openSync(stderrPath, 'a');
  return { stdoutPath, stderrPath, stdoutFd, stderrFd };
}

function createRuntimeChildLogPaths() {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const stdoutPath = path.join(logDir(), `runtime_child_${timestamp}.stdout.log`);
  const stderrPath = path.join(logDir(), `runtime_child_${timestamp}.stderr.log`);
  return { stdoutPath, stderrPath, stdoutFd: null, stderrFd: null };
}

function closeRuntimeChildLogBundle(bundle) {
  if (!bundle) {
    return;
  }
  for (const fd of [bundle.stdoutFd, bundle.stderrFd]) {
    if (typeof fd !== 'number') {
      continue;
    }
    try {
      fs.closeSync(fd);
    } catch (_error) {
      // Best effort.
    }
  }
}

function cliExpectedBinding() {
  const storePath = normalizePlatformPath(cli.memories || '');
  const episodesPath = normalizePlatformPath(cli.episodes || '');
  if (!storePath && !episodesPath) {
    return {};
  }
  return {
    store_path: storePath,
    store_fingerprint: '',
    episodes_path: episodesPath,
    build_id: '',
    artifact_mode: episodesPath ? 'published' : '',
  };
}

const FIVE_MINUTES_MS = 5 * 60 * 1000;
const MAX_AUTOMATIC_RESTARTS = 2;

function desiredRuntimeHost() {
  return String(cli.host || process.env.MNO_RUNTIME_HOST || '127.0.0.1').trim() || '127.0.0.1';
}

function desiredRuntimePort() {
  return normalizeRuntimePort(cli.port || process.env.MNO_RUNTIME_PORT || 7340);
}

function desiredRuntimeUrl() {
  return `http://${desiredRuntimeHost()}:${desiredRuntimePort()}`;
}

function desiredMcpBaseUrl() {
  return `http://${MCP_SIDECAR_HOST}:${MCP_SIDECAR_PORT}`;
}

function desiredMcpUrl() {
  return `${desiredMcpBaseUrl()}/mcp`;
}

function desiredMcpHealthUrl() {
  return `${desiredMcpBaseUrl()}/`;
}

function mcpSidecarStatePath() {
  return path.join(shellPaths.desktopShellRoot, 'mcp_sidecar_state.json');
}

function readMcpSidecarState() {
  const target = mcpSidecarStatePath();
  if (!fs.existsSync(target)) {
    return {};
  }
  try {
    const payload = JSON.parse(fs.readFileSync(target, 'utf8'));
    return payload && typeof payload === 'object' ? payload : {};
  } catch (_error) {
    return {};
  }
}

function readMcpSidecarSettings() {
  const target = mcpSidecarSettingsPath();
  if (!fs.existsSync(target)) {
    return {};
  }
  try {
    const payload = JSON.parse(fs.readFileSync(target, 'utf8'));
    return payload && typeof payload === 'object' ? payload : {};
  } catch (_error) {
    return {};
  }
}

function normalizedManagedMcpProfiles(source = {}) {
  const payload = source && typeof source === 'object' ? source : {};
  const profiles = payload.profiles && typeof payload.profiles === 'object' ? payload.profiles : {};
  return {
    draft: normalizeManagedMcpProfile(profiles.draft || {}, 'draft'),
    reviewed: normalizeManagedMcpProfile(profiles.reviewed || {}, 'reviewed'),
  };
}

function readManagedMcpProfiles() {
  return normalizedManagedMcpProfiles(readMcpSidecarSettings());
}

function managedMcpProfileForArtifactMode(artifactMode = 'reviewed') {
  const mode = normalizeManagedMcpArtifactMode(artifactMode);
  return readManagedMcpProfiles()[mode];
}

function writeMcpSidecarSettings(payload = {}) {
  const target = mcpSidecarSettingsPath();
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

function managedMcpConfigPayload() {
  return {
    ok: true,
    activeArtifactMode: normalizeManagedMcpArtifactMode(latestExpectedMcpBinding.artifact_mode || 'reviewed'),
    profiles: readManagedMcpProfiles(),
  };
}

function friendlyManagedMcpArtifactMode(value) {
  return normalizeManagedMcpArtifactMode(value) === 'draft' ? 'Draft' : 'Reviewed';
}

function friendlyManagedMcpRole(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'operator') {
    return 'Operator';
  }
  if (normalized === 'admin') {
    return 'Admin';
  }
  return 'Viewer';
}

function summarizeManagedMcpProfiles(profiles = readManagedMcpProfiles()) {
  const draft = normalizeManagedMcpProfile(profiles.draft || {}, 'draft');
  const reviewed = normalizeManagedMcpProfile(profiles.reviewed || {}, 'reviewed');
  return `draft ${draft.defaultRole} / writes ${draft.mutationsEnabled ? 'on' : 'off'} • reviewed ${reviewed.defaultRole} / writes ${reviewed.mutationsEnabled ? 'on' : 'off'}`;
}

function managedMcpDisplayState({ sidecarState = readMcpSidecarState(), artifactMode = latestExpectedMcpBinding.artifact_mode || 'reviewed' } = {}) {
  const profiles = readManagedMcpProfiles();
  const activeMode = normalizeManagedMcpArtifactMode(
    (sidecarState && sidecarState.binding && sidecarState.binding.artifact_mode)
      || artifactMode
      || 'reviewed',
  );
  const activeBinding = sidecarState && typeof sidecarState === 'object' ? sidecarState.binding || {} : {};
  const activeProfile = normalizeManagedMcpProfile(
    {
      defaultRole: activeBinding.default_role,
      compatMode: activeBinding.compat_mode,
      mutationsEnabled: activeBinding.mutations_enabled,
    },
    activeMode,
  );
  return {
    mcpArtifactMode: activeMode,
    mcpRole: activeProfile.defaultRole,
    mcpCompatMode: activeProfile.compatMode,
    mcpMutationsEnabled: activeProfile.mutationsEnabled,
    mcpProfilesSummary: summarizeManagedMcpProfiles(profiles),
  };
}

function saveManagedMcpProfile(config = {}) {
  const artifactMode = normalizeManagedMcpArtifactMode(config.artifactMode || config.artifact_mode || 'reviewed');
  const profiles = readManagedMcpProfiles();
  profiles[artifactMode] = normalizeManagedMcpProfile(config, artifactMode);
  writeMcpSidecarSettings({
    schema: 'modelnumquamoblita.desktop.mcp_sidecar_settings.v1',
    managed_by: 'modelnumquamoblita-desktop',
    profiles,
    updated_at: new Date().toISOString(),
  });
  return {
    activeArtifactMode: artifactMode,
    profiles,
  };
}

function logDir() {
  const dir = shellPaths.desktopShellRoot;
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function writeShellLog(line) {
  writeShellDiagnostic(line);
  const logPath = state.logPath || path.join(logDir(), `desktop_shell_${new Date().toISOString().replace(/[:.]/g, '-')}.log`);
  state.logPath = logPath;
  fs.appendFileSync(logPath, `${localLogStamp()} ${line}${os.EOL}`, 'utf8');
}

async function fetchMcpHealthOnce({ healthUrl = desiredMcpHealthUrl() } = {}) {
  try {
    const response = await fetch(healthUrl, { method: 'GET' });
    if (!response || !response.ok) {
      return null;
    }
    const payload = await response.json();
    if (!payload || payload.ok !== true || String(payload.service || '').trim() !== 'numquamoblita-mcp-http') {
      return null;
    }
    return payload;
  } catch (_error) {
    return null;
  }
}

function writeMcpSidecarState(payload = {}) {
  const target = mcpSidecarStatePath();
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

function clearMcpSidecarState() {
  try {
    fs.unlinkSync(mcpSidecarStatePath());
  } catch (_error) {
    // Best effort.
  }
}

function emitMcpState(patch = {}) {
  emitState({
    mcpStatus: patch.mcpStatus ?? state.mcpStatus,
    mcpLabel: patch.mcpLabel ?? state.mcpLabel,
    mcpUrl: patch.mcpUrl ?? state.mcpUrl,
    mcpLastError: patch.mcpLastError ?? state.mcpLastError,
    mcpArtifactMode: patch.mcpArtifactMode ?? state.mcpArtifactMode,
    mcpRole: patch.mcpRole ?? state.mcpRole,
    mcpCompatMode: patch.mcpCompatMode ?? state.mcpCompatMode,
    mcpMutationsEnabled: patch.mcpMutationsEnabled ?? state.mcpMutationsEnabled,
    mcpProfilesSummary: patch.mcpProfilesSummary ?? state.mcpProfilesSummary,
  });
}

function resolveSidecarPythonCommand() {
  const explicitPython = String(cli.python || process.env.MNO_PYTHON || '').trim();
  if (explicitPython) {
    return explicitPython;
  }
  if (runtimeBundleManifest && runtimeBundleManifest.bundleMode === 'python_entrypoint') {
    const platformCommand = String(
      runtimeBundleManifest.pythonCommands?.[process.platform]
      || runtimeBundleManifest.pythonCommands?.default
      || ''
    ).trim();
    if (platformCommand && !path.isAbsolute(platformCommand) && /[\\/]/.test(platformCommand)) {
      const bundledPython = path.resolve(shellPaths.repoRoot, platformCommand);
      if (fs.existsSync(bundledPython)) {
        return bundledPython;
      }
    } else if (platformCommand) {
      return platformCommand;
    }
  }
  return defaultPythonCommand(process.platform);
}

function buildMcpSidecarLaunchPlan(binding = {}) {
  const fallbackBinding = mcpBindingReady(binding) ? binding : latestExpectedMcpBinding;
  const storePath = String(fallbackBinding.store_path || '').trim();
  const episodesPath = String(fallbackBinding.episodes_path || '').trim();
  const artifactMode = String(fallbackBinding.artifact_mode || '').trim().toLowerCase();
  const managedProfile = managedMcpProfileForArtifactMode(artifactMode || 'reviewed');
  if (!storePath || !episodesPath) {
    return null;
  }
  const command = resolveSidecarPythonCommand();
  const args = [
    path.join(shellPaths.repoRoot, 'tools', 'run_claude_live_mcp.py'),
    '--memories', storePath,
    '--default-role', managedProfile.defaultRole,
    '--compat-mode', managedProfile.compatMode,
    '--transport', 'http',
    '--http-host', MCP_SIDECAR_HOST,
    '--http-port', String(MCP_SIDECAR_PORT),
  ];
  if (managedProfile.mutationsEnabled) {
    args.push('--mutations-enabled');
  }
  if (episodesPath) {
    args.push('--episodes', episodesPath);
  }
  return {
    command,
    args,
    cwd: shellPaths.repoRoot,
    url: desiredMcpUrl(),
    healthUrl: desiredMcpHealthUrl(),
    binding: {
      store_path: storePath,
      store_fingerprint: String(fallbackBinding.store_fingerprint || '').trim(),
      episodes_path: episodesPath,
      artifact_mode: artifactMode,
      default_role: managedProfile.defaultRole,
      compat_mode: managedProfile.compatMode,
      mutations_enabled: managedProfile.mutationsEnabled,
    },
  };
}

function buildExpectedMcpBinding(wizardState) {
  const source = wizardState && typeof wizardState === 'object' ? wizardState : {};
  const storeValidation = source.store_validation && typeof source.store_validation === 'object'
    ? source.store_validation
    : {};
  const publishedSet = source.published_set && typeof source.published_set === 'object'
    ? source.published_set
    : {};
  const reviewedEpisodesPath = String(publishedSet.episodes_path || source.last_compiled_reviewed_path || '').trim();
  const draftEpisodesPath = String(source.last_built_episode_draft_path || '').trim();
  const selectedEpisodesPath = reviewedEpisodesPath || draftEpisodesPath;
  return {
    store_path: normalizePlatformPath(storeValidation.path || source.store_path || ''),
    store_fingerprint: String(storeValidation.store_fingerprint || '').trim(),
    episodes_path: normalizePlatformPath(selectedEpisodesPath),
    build_id: String(publishedSet.build_id || '').trim(),
    artifact_mode: reviewedEpisodesPath ? 'reviewed' : (draftEpisodesPath ? 'draft' : ''),
  };
}

function mcpBindingReady(binding = {}) {
  return Boolean(
    String(binding.store_path || '').trim()
    && String(binding.episodes_path || '').trim(),
  );
}

function attachMcpSidecarLogging(child, launchPlan, { childLogBundle = null } = {}) {
  let stdoutBuffer = '';
  if (child.stdout && typeof child.stdout.on === 'function') {
    child.stdout.on('data', (chunk) => {
      const text = String(chunk || '');
      writeShellLog(`[mcp-stdout] ${text.trimEnd()}`);
      stdoutBuffer += text;
    });
  } else if (childLogBundle) {
    writeShellLog(`[mcp-child-logs] stdout=${childLogBundle.stdoutPath} stderr=${childLogBundle.stderrPath}`);
  }
  if (child.stderr && typeof child.stderr.on === 'function') {
    child.stderr.on('data', (chunk) => {
      const text = String(chunk || '').trimEnd();
      if (!text) {
        return;
      }
      writeShellLog(`[mcp-stderr] ${text}`);
      emitMcpState({ mcpStatus: 'needs_attention', mcpLabel: 'Needs attention', mcpLastError: text, mcpUrl: launchPlan.url });
    });
  }
  child.on('error', (error) => {
    mcpSidecarChild = null;
    const message = `Claude / MCP sidecar failed to start: ${error?.message || error}`;
    writeShellLog(`[mcp-error] ${message}`);
    clearMcpSidecarState();
    emitMcpState({ mcpStatus: 'needs_attention', mcpLabel: 'Needs attention', mcpLastError: message, mcpUrl: launchPlan.url });
  });
  child.on('exit', (code, signal) => {
    if (stdoutBuffer.trim()) {
      writeShellLog(`[mcp-stdout-tail] ${stdoutBuffer.trim()}`);
    }
    writeShellLog(`[mcp-exit] pid=${child.pid || 0} code=${code ?? 'null'} signal=${signal ?? 'null'}`);
    if (mcpSidecarChild === child) {
      mcpSidecarChild = null;
    }
    if (!shuttingDown && !expectedRuntimeExit) {
      clearMcpSidecarState();
      emitMcpState({
        mcpStatus: 'needs_attention',
        mcpLabel: 'Needs attention',
        mcpLastError: `Claude / MCP sidecar exited unexpectedly. code=${code ?? 'null'} signal=${signal ?? 'null'}`,
        mcpUrl: launchPlan.url,
      });
    }
  });
}

async function waitForMcpSidecarReady({ healthUrl = desiredMcpHealthUrl(), timeoutMs = 10000 } = {}) {
  const startedAt = Date.now();
  while ((Date.now() - startedAt) <= timeoutMs) {
    const payload = await fetchMcpHealthOnce({ healthUrl });
    if (payload) {
      return payload;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return null;
}

async function stopMcpSidecar() {
  const child = mcpSidecarChild;
  mcpSidecarChild = null;
  mcpSidecarPlan = null;
  clearMcpSidecarState();
  const display = managedMcpDisplayState();
  if (!child) {
    emitMcpState({ mcpStatus: 'not_installed', mcpLabel: 'Not installed', mcpLastError: '', mcpUrl: desiredMcpUrl(), ...display });
    return;
  }
  try {
    child.kill('SIGTERM');
  } catch (_error) {
    // Best effort.
  }
  await waitForChildExit(child, { timeoutMs: 1500 });
  emitMcpState({ mcpStatus: 'not_installed', mcpLabel: 'Not installed', mcpLastError: '', mcpUrl: desiredMcpUrl(), ...display });
}

async function ensureMcpSidecar(binding = {}) {
  const launchPlan = buildMcpSidecarLaunchPlan(binding);
  if (!launchPlan) {
    await stopMcpSidecar();
    return null;
  }
  const existingHealth = await fetchMcpHealthOnce({ healthUrl: launchPlan.healthUrl });
  const statePath = mcpSidecarStatePath();
  let existingState = {};
  if (fs.existsSync(statePath)) {
    existingState = readMcpSidecarState();
  }
  const existingBinding = existingState && typeof existingState === 'object' ? existingState.binding || {} : {};
  const bindingMatches = existingHealth
    && String(existingBinding.store_path || '').trim() === launchPlan.binding.store_path
    && String(existingBinding.episodes_path || '').trim() === launchPlan.binding.episodes_path
    && String(existingBinding.store_fingerprint || '').trim() === launchPlan.binding.store_fingerprint
    && String(existingBinding.default_role || '').trim() === launchPlan.binding.default_role
    && String(existingBinding.compat_mode || '').trim() === launchPlan.binding.compat_mode
    && Boolean(existingBinding.mutations_enabled) === Boolean(launchPlan.binding.mutations_enabled);
  if (bindingMatches) {
    mcpSidecarPlan = launchPlan;
    emitMcpState({ mcpStatus: 'ready', mcpLabel: 'Ready', mcpLastError: '', mcpUrl: launchPlan.url, ...managedMcpDisplayState({ sidecarState: existingState, artifactMode: launchPlan.binding.artifact_mode }) });
    return existingHealth;
  }
  if (mcpSidecarChild) {
    await stopMcpSidecar();
  }
  const childLogBundle = process.platform === 'win32' ? createRuntimeChildLogBundle() : null;
  let launchCommand = launchPlan.command;
  if (process.platform === 'win32') {
    launchCommand = resolveWindowsGuiPythonCommand(launchPlan.command);
    writeShellLog(`[mcp-child-logs] stdout=${childLogBundle.stdoutPath} stderr=${childLogBundle.stderrPath}`);
  }
  writeShellLog(`mcp launch command=${launchCommand} args=${JSON.stringify(launchPlan.args)}`);
  try {
    mcpSidecarChild = spawn(
      launchCommand,
      launchPlan.args,
      buildRuntimeSpawnOptions({
        cwd: launchPlan.cwd,
        env: { ...process.env, MNO_RUNTIME_STATE_ROOT: shellPaths.runtimeRoot },
        platform: process.platform,
        stdio: process.platform === 'win32'
          ? ['ignore', childLogBundle.stdoutFd, childLogBundle.stderrFd]
          : ['ignore', 'pipe', 'pipe'],
      }),
    );
  } finally {
    closeRuntimeChildLogBundle(childLogBundle);
  }
  mcpSidecarPlan = launchPlan;
  attachMcpSidecarLogging(mcpSidecarChild, launchPlan, { childLogBundle });
  emitMcpState({ mcpStatus: 'starting', mcpLabel: 'Starting', mcpLastError: '', mcpUrl: launchPlan.url, ...managedMcpDisplayState({ artifactMode: launchPlan.binding.artifact_mode }) });
  const ready = await waitForMcpSidecarReady({ healthUrl: launchPlan.healthUrl, timeoutMs: 10000 });
  if (!ready) {
    emitMcpState({
      mcpStatus: 'needs_attention',
      mcpLabel: 'Needs attention',
      mcpLastError: 'Claude / MCP sidecar did not become healthy within 10 seconds.',
      mcpUrl: launchPlan.url,
      ...managedMcpDisplayState({ artifactMode: launchPlan.binding.artifact_mode }),
    });
    return null;
  }
  writeMcpSidecarState({
    schema: 'modelnumquamoblita.desktop.mcp_sidecar_state.v1',
    managed_by: 'modelnumquamoblita-desktop',
    status: 'ready',
    url: launchPlan.url,
    health_url: launchPlan.healthUrl,
    transport: 'http',
    host: MCP_SIDECAR_HOST,
    port: MCP_SIDECAR_PORT,
    binding: launchPlan.binding,
    profiles: readManagedMcpProfiles(),
    updated_at: new Date().toISOString(),
    pid: mcpSidecarChild?.pid || 0,
  });
  emitMcpState({ mcpStatus: 'ready', mcpLabel: 'Ready', mcpLastError: '', mcpUrl: launchPlan.url, ...managedMcpDisplayState({ sidecarState: readMcpSidecarState(), artifactMode: launchPlan.binding.artifact_mode }) });
  return ready;
}

function shouldIgnoreDevSignal() {
  return process.platform === 'win32' && !app.isPackaged && !quitAfterCleanup;
}

function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
}

async function refreshDesktopHomeState() {
  const candidateRuntimeUrl = String(state.runtimeUrl || desiredRuntimeUrl() || '').trim();
  const runtimeHealth = candidateRuntimeUrl
    ? await fetchRuntimeHealthOnce({ runtimeHealthUrl: `${candidateRuntimeUrl.replace(/\/+$/, '')}/api/runtime/health` })
    : null;
  hydrateStateFromDisk({ runtimeHealth, lastError: runtimeHealth ? '' : state.lastError });
  const mcpHealth = await fetchMcpHealthOnce({ healthUrl: desiredMcpHealthUrl() });
  const display = managedMcpDisplayState();
  if (mcpHealth) {
    emitMcpState({ mcpStatus: 'ready', mcpLabel: 'Ready', mcpLastError: '', mcpUrl: desiredMcpUrl(), ...display });
  } else if ((runtimeHealth && state.readyConfiguration) || mcpBindingReady(latestExpectedMcpBinding)) {
    emitMcpState({
      mcpStatus: 'needs_attention',
      mcpLabel: 'Needs attention',
      mcpLastError: 'Claude / MCP is installed but the local sidecar is not responding.',
      mcpUrl: desiredMcpUrl(),
      ...display,
    });
  } else {
    emitMcpState({ mcpStatus: 'not_installed', mcpLabel: 'Not installed', mcpLastError: '', mcpUrl: desiredMcpUrl(), ...display });
  }
}

function showRuntimeWindow() {
  if (!runtimeWindow || runtimeWindow.isDestroyed()) {
    return;
  }
  if (runtimeWindow.isMinimized()) {
    runtimeWindow.restore();
  }
  runtimeWindow.show();
  runtimeWindow.focus();
}

function runtimeWorkspaceOpen() {
  return Boolean(runtimeWindow && !runtimeWindow.isDestroyed());
}

function buildRuntimeWorkspaceUrl(runtimeUrl, { tabId = '' } = {}) {
  const base = String(runtimeUrl || '').trim() || desiredRuntimeUrl();
  const url = new URL(base);
  if (String(tabId || '').trim()) {
    url.searchParams.set('desktopTab', String(tabId).trim());
  } else {
    url.searchParams.delete('desktopTab');
  }
  return url.toString();
}

function setTrayFallback(message) {
  emitState({
    trayAvailable: false,
    trayFallbackActive: true,
    trayFallbackMessage: String(message || 'Tray or menu-bar controls are unavailable on this system.'),
  });
}

function emitState(patch = {}) {
  Object.assign(state, patch);
  writeShellLog(`state status=${state.status} label=${state.label} stage=${state.bootStage} runtime_url=${state.runtimeUrl || ''}`);
  updateTrayMenu();
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('desktop-shell:state', { ...state });
  }
}

function loadBootPage() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return Promise.resolve();
  }
  return mainWindow.loadFile(path.join(__dirname, 'boot.html'));
}

function isBenignNavigationAbortError(error) {
  const code = Number(error?.code);
  const message = String(error?.message || error || '');
  return code === -3 || /ERR_ABORTED/i.test(message);
}

function trayIcon() {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
      <rect width="64" height="64" rx="18" fill="#08111f"/>
      <circle cx="32" cy="32" r="21" fill="#10233d" stroke="#f2a14c" stroke-width="3"/>
      <path d="M20 42V22h6l12 13V22h6v20h-6L26 29v13z" fill="#f5efe6"/>
    </svg>
  `;
  const image = nativeImage.createFromDataURL(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`);
  return image.resize({ width: 18, height: 18 });
}

function updateTrayMenu() {
  if (!tray) {
    return;
  }
  const template = buildTrayMenuTemplate(state).map((item) => {
    if (item.type === 'separator') {
      return { type: 'separator' };
    }
    const handlerMap = {
      'open-app': () => refreshDesktopHomeState().catch(() => {}).finally(() => showMainWindow()),
      'start-runtime': () => startRuntime({ setupMode: false, openWorkspace: false }).catch((error) => reportShellError('start runtime failed', error)),
      'open-setup': () => startRuntime({ setupMode: true, openWorkspace: true }).catch((error) => reportShellError('open setup failed', error)),
      'repair-runtime': () => repairRuntimeClaim().catch((error) => reportShellError('repair runtime failed', error)),
      'restart-runtime': () => restartRuntime().catch((error) => reportShellError('restart runtime failed', error)),
      'stop-runtime': () => stopRuntime({ explicitUserStop: true, reloadBootUi: true }).catch((error) => reportShellError('stop runtime failed', error)),
      'open-logs': () => shell.openPath(state.logPath ? path.dirname(state.logPath) : logDir()),
      'open-state-folder': () => shell.openPath(state.wizardRunsPath),
      quit: () => app.quit(),
    };
    return {
      id: item.id,
      label: item.label,
      enabled: item.enabled !== false,
      click: handlerMap[item.id],
    };
  });
  tray.setContextMenu(Menu.buildFromTemplate(template));
  tray.setToolTip(`ModelNumquamOblita • ${state.label}`);
  if (process.platform === 'darwin') {
    tray.setTitle(state.label);
  }
}

function createTrayIfSupported() {
  try {
    tray = new Tray(trayIcon());
    tray.on('click', () => {
      refreshDesktopHomeState().catch(() => {}).finally(() => showMainWindow());
    });
    emitState({ trayAvailable: true, trayFallbackActive: false, trayFallbackMessage: '' });
  } catch (error) {
    tray = null;
    setTrayFallback(`Tray/menu-bar controls are unavailable: ${error?.message || error}`);
    return;
  }
  updateTrayMenu();
}

function persistPreferences(patch = {}) {
  const updated = saveShellPreferences(shellPaths, { ...state.preferences, ...patch });
  emitState({ preferences: updated });
  return updated;
}

function hydrateStateFromDisk({ runtimeHealth = null, lastError = '' } = {}) {
  const preferences = loadShellPreferences(shellPaths);
  const lastKnownGoodRuntime = loadLastKnownGoodRuntime(shellPaths);
  let manifest = null;
  let manifestError = '';
  try {
    manifest = loadRuntimeBundleManifest({ repoRoot: shellPaths.repoRoot, appVersion, desktopAppRoot });
  } catch (error) {
    manifestError = error?.message || String(error);
  }
  const latest = loadLatestWizardState(shellPaths);
  latestWizardState = latest.state;
  const explicitCliBinding = cliExpectedBinding();
  latestExpectedBinding = Object.keys(explicitCliBinding).length
    ? explicitCliBinding
    : (latest.state ? buildExpectedBinding(latest.state) : {});
  latestExpectedMcpBinding = Object.keys(explicitCliBinding).length
    ? explicitCliBinding
    : (latest.state ? buildExpectedMcpBinding(latest.state) : {});
  const lockPayload = readRuntimeLock(shellPaths);
  const lockSummary = summarizeRuntimeLock(lockPayload, {
    expectedBinding: latestExpectedBinding,
    expectedHost: desiredRuntimeHost(),
    expectedPort: desiredRuntimePort(),
  });
  const currentRuntimeUrl = hydratedRuntimeUrl(runtimeHealth);
  const healthBinding = runtimeHealth && typeof runtimeHealth === 'object' && runtimeHealth.binding && typeof runtimeHealth.binding === 'object'
    ? runtimeHealth.binding
    : {};
  writeShellLog(
    `[hydrate] run=${latest.runId || ''} expected_store=${latestExpectedBinding.store_path || ''} expected_fp=${latestExpectedBinding.store_fingerprint || ''} `
    + `expected_episodes=${latestExpectedBinding.episodes_path || ''} lock_status=${String(lockSummary.status || '')} `
    + `lock_store=${String(lockSummary.store_path || '')} lock_fp=${String(lockSummary.store_fingerprint || '')} `
    + `health_store=${String(healthBinding.store_path || '')} health_fp=${String(healthBinding.store_fingerprint || '')} `
    + `health_launch_mode=${String(runtimeHealth?.launch_mode || '')}`,
  );
  let derived = deriveShellStartupState({
    wizardRunId: latest.runId,
    wizardState: latest.state,
    preferences,
    lockSummary,
    runtimeUrl: currentRuntimeUrl,
    runtimeManifest: manifest,
    runtimeHealth,
    fsImpl: fs,
  });
  if (runtimeHealth && typeof runtimeHealth === 'object' && runtimeHealth.service === 'modelnumquamoblita-runtime') {
    const healthBinding = runtimeHealth.binding && typeof runtimeHealth.binding === 'object' ? runtimeHealth.binding : {};
    const bindingMatches = String(healthBinding.store_fingerprint || '').trim() === String(latestExpectedBinding.store_fingerprint || '').trim()
      && String(healthBinding.episodes_path || '').trim() === String(latestExpectedBinding.episodes_path || '').trim()
      && String(healthBinding.store_path || '').trim() === String(latestExpectedBinding.store_path || '').trim();
    if (bindingMatches && String(runtimeHealth.launch_mode || '').trim() === 'normal') {
      derived = {
        ...derived,
        status: 'ready',
        label: 'Ready',
        bootStage: 'Runtime ready.',
      };
    } else if (String(runtimeHealth.launch_mode || '').trim() === 'setup_mode') {
      derived = {
        ...derived,
        status: 'setup_required',
        label: 'Setup required',
        bootStage: 'Setup workspace ready. Finish the guided workflow before normal background serving.',
      };
    }
  }
  if (Object.keys(explicitCliBinding).length) {
    const cliStoreReady = Boolean(explicitCliBinding.store_path) && fs.existsSync(explicitCliBinding.store_path);
    const cliEpisodesReady = !explicitCliBinding.episodes_path || fs.existsSync(explicitCliBinding.episodes_path);
    const cliReady = cliStoreReady && cliEpisodesReady;
    if (cliReady) {
      const runtimeStopped = preferences.runtime_desired_state === 'stopped'
        || preferences.auto_start === 'manual_start_only';
      derived = {
        ...derived,
        status: runtimeStopped ? 'stopped' : derived.status,
        label: stateLabel(runtimeStopped ? 'stopped' : derived.status),
        bootStage: cliEpisodesReady
          ? 'Runtime is configured from explicit CLI overrides.'
          : 'Runtime is configured from an explicit store override.',
        statusReason: 'Explicit CLI runtime binding is active.',
        readyConfiguration: true,
        autoStartAllowed: preferences.auto_start === 'auto_start_if_ready'
          && preferences.runtime_desired_state !== 'stopped',
        canStartRuntime: true,
        storePath: explicitCliBinding.store_path,
        episodeCardsPath: explicitCliBinding.episodes_path,
        missingArtifacts: [],
      };
    }
  }
  if (manifestError) {
    const rollbackHint = String(lastKnownGoodRuntime.runtime_version || '').trim()
      ? ` Last known good runtime: ${String(lastKnownGoodRuntime.runtime_version || '').trim()} for app ${String(lastKnownGoodRuntime.app_version || '').trim() || 'unknown'}.`
      : '';
    derived = {
      ...derived,
      status: 'error',
      label: 'Error',
      bootStage: 'Desktop runtime metadata is invalid or missing.',
      lastError: `${manifestError}${rollbackHint}`.trim(),
      statusReason: `${manifestError}${rollbackHint}`.trim(),
    };
  }
  runtimeBundleManifest = manifest;
  emitState({
    ...derived,
    runtimeUrl: currentRuntimeUrl || derived.runtimeUrl || '',
    lastError: String(lastError || derived.lastError || manifestError || '').trim(),
    repoRoot: shellPaths.repoRoot,
    runtimeRoot: shellPaths.runtimeRoot,
    wizardRunsPath: shellPaths.wizardRunsRoot,
    publishedSetsPath: shellPaths.publishedSetsRoot,
    preferences,
    lock: lockSummary,
    runtimeBundle: manifest ? { runtimeVersion: manifest.runtimeVersion, bundleMode: manifest.bundleMode } : null,
    lastKnownGoodRuntime,
    appVersion,
    ...managedMcpDisplayState(),
  });
  return state;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1420,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#08111f',
      title: 'ModelNumquamOblita Desktop',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  mainWindow.once('ready-to-show', () => {
    writeShellLog('[window] ready-to-show');
    mainWindow.show();
  });
  mainWindow.webContents.on('did-fail-load', (_event, code, description, validatedURL, isMainFrame) => {
    const isBenignAbort = Number(code) === -3 || /ERR_ABORTED/i.test(String(description || ''));
    if (isBenignAbort) {
      writeShellLog(`[window] did-fail-load ignored code=${code} description=${description} url=${validatedURL} main_frame=${Boolean(isMainFrame)}`);
      return;
    }
    writeShellLog(`[window] did-fail-load code=${code} description=${description} url=${validatedURL} main_frame=${Boolean(isMainFrame)}`);
    emitState({
      status: 'error',
      label: 'Error',
      bootStage: 'Desktop shell failed to load.',
      lastError: `Failed to load ${validatedURL || 'desktop UI'}: ${description || code}`,
    });
  });
  mainWindow.webContents.on('did-start-navigation', (_event, url, isInPlace, isMainFrame) => {
    writeShellLog(`[window] did-start-navigation url=${url} in_place=${Boolean(isInPlace)} main_frame=${Boolean(isMainFrame)}`);
  });
  mainWindow.webContents.on('did-finish-load', () => {
    writeShellLog(`[window] did-finish-load url=${mainWindow?.webContents?.getURL?.() || ''}`);
  });
  mainWindow.webContents.on('console-message', (details = {}) => {
    const { level = '', message = '', lineNumber = null, sourceId = '' } = details || {};
    writeShellLog(`[window-console] level=${level} source=${sourceId || ''}:${lineNumber ?? 'null'} message=${message}`);
  });
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    writeShellLog(`[window] render-process-gone reason=${details?.reason || 'unknown'} exit_code=${details?.exitCode ?? 'null'}`);
  });
  mainWindow.on('close', async (event) => {
    writeShellLog(`[window] close requested quitAfterCleanup=${Boolean(quitAfterCleanup)} close_behavior=${state.preferences.close_behavior}`);
    if (quitAfterCleanup) {
      return;
    }
    if (state.preferences.close_behavior === 'quit_on_close') {
      return;
    }
    if (state.trayAvailable && tray) {
      event.preventDefault();
      if (!state.preferences.background_explainer_seen) {
        persistPreferences({ background_explainer_seen: true });
        await dialog.showMessageBox(mainWindow, {
          type: 'info',
          buttons: ['Keep running'],
          defaultId: 0,
          title: 'Still running in the background',
          message: 'ModelNumquamOblita will keep running in the background.',
          detail: 'Use the tray or menu-bar icon to reopen the app, restart the runtime, or quit cleanly.',
        }).catch(() => {});
      }
      mainWindow.hide();
      return;
    }
    event.preventDefault();
    const result = await dialog.showMessageBox(mainWindow, {
      type: 'warning',
      buttons: ['Keep open', 'Quit app'],
      defaultId: 0,
      cancelId: 0,
      title: 'Tray unavailable',
      message: 'Tray or menu-bar controls are unavailable on this system.',
      detail: 'Closing now would fully quit ModelNumquamOblita instead of hiding it to the background.',
    }).catch(() => ({ response: 0 }));
    if (result.response === 1) {
      quitAfterCleanup = false;
      app.quit();
    }
  });
  loadBootPage().catch((error) => {
    if (isBenignNavigationAbortError(error)) {
      writeShellLog(`[window] loadBootPage ignored code=${error?.code ?? ''} message=${error?.message || error}`);
      return;
    }
    emitState({
      status: 'error',
      label: 'Error',
      bootStage: 'Desktop shell failed to load.',
      lastError: `Failed to load desktop shell: ${error?.message || error}`,
    });
  });
}

function createRuntimeWindow() {
  runtimeWindow = new BrowserWindow({
    width: 1420,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#08111f',
    title: 'ModelNumquamOblita Runtime',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  runtimeWindow.once('ready-to-show', () => {
    writeShellLog('[runtime-window] ready-to-show');
    runtimeWindow.show();
  });
  runtimeWindow.webContents.on('did-fail-load', (_event, code, description, validatedURL, isMainFrame) => {
    const isBenignAbort = Number(code) === -3 || /ERR_ABORTED/i.test(String(description || ''));
    if (isBenignAbort) {
      writeShellLog(`[runtime-window] did-fail-load ignored code=${code} description=${description} url=${validatedURL} main_frame=${Boolean(isMainFrame)}`);
      return;
    }
    writeShellLog(`[runtime-window] did-fail-load code=${code} description=${description} url=${validatedURL} main_frame=${Boolean(isMainFrame)}`);
  });
  runtimeWindow.webContents.on('did-start-navigation', (_event, url, isInPlace, isMainFrame) => {
    writeShellLog(`[runtime-window] did-start-navigation url=${url} in_place=${Boolean(isInPlace)} main_frame=${Boolean(isMainFrame)}`);
  });
  runtimeWindow.webContents.on('did-finish-load', () => {
    writeShellLog(`[runtime-window] did-finish-load url=${runtimeWindow?.webContents?.getURL?.() || ''}`);
  });
  runtimeWindow.on('closed', () => {
    writeShellLog('[runtime-window] closed');
    runtimeWindow = null;
  });
}

function registerIpc() {
  ipcMain.handle('desktop-shell:get-state', async () => ({ ...state }));
  ipcMain.handle('desktop-shell:get-preferences', async () => ({ ...state.preferences }));
  ipcMain.handle('desktop-shell:set-preferences', async (_event, patch = {}) => {
    persistPreferences(patch);
    hydrateStateFromDisk({ lastError: state.lastError, runtimeHealth: state.runtimeHealth });
    return { ...state };
  });
  ipcMain.handle('desktop-shell:start-runtime', async () => {
    writeShellLog('[ipc] start-runtime');
    await startRuntime({ setupMode: false, openWorkspace: false });
    return { ...state };
  });
  ipcMain.handle('desktop-shell:start-setup', async () => {
    writeShellLog('[ipc] start-setup');
    if (state.readyConfiguration) {
      if (!state.runtimeUrl) {
        await startRuntime({ setupMode: false, openWorkspace: true, workspaceTab: 'setup' });
      } else {
        await loadRuntimeWindow(buildRuntimeWorkspaceUrl(state.runtimeUrl, { tabId: 'setup' }));
      }
      return { ...state };
    }
    await startRuntime({ setupMode: true, openWorkspace: true, workspaceTab: 'setup' });
    return { ...state };
  });
  ipcMain.handle('desktop-shell:repair-runtime', async () => {
    writeShellLog('[ipc] repair-runtime');
    await repairRuntimeClaim();
    return { ...state };
  });
  ipcMain.handle('desktop-shell:restart-runtime', async () => {
    writeShellLog('[ipc] restart-runtime');
    await restartRuntime();
    return { ...state };
  });
  ipcMain.handle('desktop-shell:stop-runtime', async () => {
    writeShellLog('[ipc] stop-runtime');
    await stopRuntime({ explicitUserStop: true, reloadBootUi: true });
    return { ...state };
  });
  ipcMain.handle('desktop-shell:open-runtime-workspace', async () => {
    writeShellLog('[ipc] open-runtime-workspace');
    if (!state.runtimeUrl) {
      await startRuntime({
        setupMode: !state.readyConfiguration,
        openWorkspace: true,
        workspaceTab: state.readyConfiguration ? 'chat' : 'setup',
      });
      return true;
    }
    await loadRuntimeWindow(buildRuntimeWorkspaceUrl(state.runtimeUrl, { tabId: 'chat' }));
    return true;
  });
  ipcMain.handle('desktop-shell:show-home', async () => {
    writeShellLog('[ipc] show-home');
    await refreshDesktopHomeState();
    showMainWindow();
    return { ...state };
  });
  ipcMain.handle('desktop-shell:pick-source-files', async () => {
    const owner = (runtimeWindow && !runtimeWindow.isDestroyed() ? runtimeWindow : null) || (mainWindow && !mainWindow.isDestroyed() ? mainWindow : null);
    const result = await dialog.showOpenDialog(owner || undefined, {
      title: 'Pick source files for MNO import',
      properties: ['openFile', 'multiSelections'],
      filters: [
        { name: 'Supported source files', extensions: ['json', 'jsonl', 'txt', 'md'] },
        { name: 'All files', extensions: ['*'] },
      ],
    });
    return {
      canceled: Boolean(result.canceled),
      paths: Array.isArray(result.filePaths) ? result.filePaths : [],
    };
  });
  ipcMain.handle('desktop-shell:pick-source-folders', async () => {
    const owner = (runtimeWindow && !runtimeWindow.isDestroyed() ? runtimeWindow : null) || (mainWindow && !mainWindow.isDestroyed() ? mainWindow : null);
    const result = await dialog.showOpenDialog(owner || undefined, {
      title: 'Pick source folders for MNO import',
      properties: ['openDirectory', 'multiSelections'],
    });
    return {
      canceled: Boolean(result.canceled),
      paths: Array.isArray(result.filePaths) ? result.filePaths : [],
    };
  });
  ipcMain.handle('desktop-shell:get-managed-mcp-config', async () => {
    writeShellLog('[ipc] get-managed-mcp-config');
    hydrateStateFromDisk({ lastError: state.lastError, runtimeHealth: state.runtimeHealth });
    return managedMcpConfigPayload();
  });
  ipcMain.handle('desktop-shell:save-managed-mcp-config', async (_event, payload = {}) => {
    writeShellLog(`[ipc] save-managed-mcp-config payload=${JSON.stringify(payload || {})}`);
    hydrateStateFromDisk({ lastError: state.lastError, runtimeHealth: state.runtimeHealth });
    const config = saveManagedMcpProfile(payload || {});
    if (Boolean(payload && payload.restart)) {
      if (mcpBindingReady(latestExpectedMcpBinding)) {
        await ensureMcpSidecar(latestExpectedMcpBinding);
      } else {
        await stopMcpSidecar();
      }
    }
    return {
      ok: true,
      active: Boolean(mcpBindingReady(latestExpectedMcpBinding)),
      binding: { ...latestExpectedMcpBinding },
      config,
      mcpStatus: state.mcpStatus,
      mcpLabel: state.mcpLabel,
      mcpUrl: state.mcpUrl,
      mcpLastError: state.mcpLastError,
    };
  });
  ipcMain.handle('desktop-shell:ensure-draft-curation-mcp', async () => {
    writeShellLog('[ipc] ensure-draft-curation-mcp');
    hydrateStateFromDisk({ lastError: state.lastError, runtimeHealth: state.runtimeHealth });
    if (mcpBindingReady(latestExpectedMcpBinding)) {
      await ensureMcpSidecar(latestExpectedMcpBinding);
      return { ok: true, active: true, binding: { ...latestExpectedMcpBinding } };
    }
    return { ok: true, active: false, binding: { ...latestExpectedMcpBinding } };
  });
  ipcMain.handle('desktop-shell:acknowledge-background-explainer', async () => {
    persistPreferences({ background_explainer_seen: true });
    return { ...state.preferences };
  });
  ipcMain.handle('desktop-shell:open-runtime-folder', async () => shell.openPath(path.join(state.repoRoot, 'runtime')));
  ipcMain.handle('desktop-shell:open-state-folder', async () => shell.openPath(state.wizardRunsPath));
  ipcMain.handle('desktop-shell:open-published-sets', async () => shell.openPath(state.publishedSetsPath));
  ipcMain.handle('desktop-shell:open-runtime-logs', async () => {
    const target = state.logPath ? path.dirname(state.logPath) : logDir();
    return shell.openPath(target);
  });
  ipcMain.handle('desktop-shell:open-mcp-logs', async () => shell.openPath(logDir()));
  ipcMain.handle('desktop-shell:open-external-ui', async () => {
    if (!state.runtimeUrl) {
      return false;
    }
    await shell.openExternal(state.runtimeUrl);
    return true;
  });
}

function attachRuntimeLogging(child, launchPlan, { childLogBundle = null, attachmentMode = runtimeAttachmentMode } = {}) {
  let stdoutBuffer = '';
  let resolveSpawnError = () => {};
  let resolveEarlyExit = () => {};
  const spawnErrorPromise = new Promise((resolve) => {
    resolveSpawnError = resolve;
  });
  const earlyExitPromise = new Promise((resolve) => {
    resolveEarlyExit = resolve;
  });

  function handleStdoutLine(line) {
    const parsed = parseRuntimeStdoutLine(line);
    if (!parsed) {
      return;
    }
    if (parsed.key === 'runtime_url') {
      emitState({ runtimeUrl: parsed.value, bootStage: 'Probing runtime health.' });
    } else if (parsed.key === 'memories_path') {
      emitState({ storePath: parsed.value });
    } else if (parsed.key === 'episode_cards_path') {
      emitState({ episodeCardsPath: parsed.value });
    }
  }

  if (child.stdout && typeof child.stdout.on === 'function') {
    child.stdout.on('data', (chunk) => {
      const text = String(chunk || '');
      writeShellLog(`[stdout] ${text.trimEnd()}`);
      stdoutBuffer += text;
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() || '';
      for (const line of lines) {
        handleStdoutLine(line);
      }
    });
  }
  if (child.stderr && typeof child.stderr.on === 'function') {
    child.stderr.on('data', (chunk) => {
      const text = String(chunk || '').trimEnd();
      if (!text) {
        return;
      }
      writeShellLog(`[stderr] ${text}`);
      emitState({ lastError: text });
    });
  } else if (childLogBundle) {
    writeShellLog(
      `[child-logs] stdout=${childLogBundle.stdoutPath} stderr=${childLogBundle.stderrPath} attachment=${attachmentMode || ''}`,
    );
  }
  child.on('error', (error) => {
    runtimeChild = null;
    runtimeAttachmentMode = '';
    expectedRuntimeExit = false;
    const message = `Failed to start the local runtime: ${error?.message || error}`;
    writeShellLog(`[error] ${message}`);
    emitState({
      status: 'error',
      label: 'Error',
      bootStage: 'Runtime launch failed.',
      lastError: message,
    });
    resolveSpawnError(error);
    if (cli.smokeExitWhenReady) {
      quitForSmoke(1);
    }
  });
  child.on('exit', (code, signal) => {
    if (stdoutBuffer.trim()) {
      handleStdoutLine(stdoutBuffer.trim());
      stdoutBuffer = '';
    }
    writeShellLog(`[child-exit] pid=${child.pid || 0} code=${code ?? 'null'} signal=${signal ?? 'null'} attachment=${attachmentMode || ''}`);
    resolveEarlyExit({ code, signal });
    if (shuttingDown || expectedRuntimeExit) {
      return;
    }
    if (attachmentMode === 'launcher') {
      writeShellLog(`[launcher-exit] pid=${child.pid || 0} code=${code ?? 'null'} signal=${signal ?? 'null'} waiting_for_health=true`);
      return;
    }
    runtimeChild = null;
    runtimeAttachmentMode = '';
    (async () => {
      const reattached = await maybeReattachAfterUnexpectedChildExit({ launchPlan, code, signal });
      if (reattached) {
        return;
      }
      await handleUnexpectedRuntimeExit({ code, signal, launchPlan });
    })().catch((error) => {
      reportShellError('runtime exit recovery failed', error);
    });
  });
  return { spawnErrorPromise, earlyExitPromise };
}

function registerAutomaticRestart() {
  const now = Date.now();
  restartHistory = restartHistory.filter((stamp) => (now - stamp) <= FIVE_MINUTES_MS);
  restartHistory.push(now);
  return restartHistory.length;
}

async function maybeReattachAfterUnexpectedChildExit({ launchPlan, code, signal }) {
  if (!launchPlan || !launchPlan.runtimeHealthUrl) {
    return false;
  }
  const expectedBinding = expectedBindingForLaunchPlan(launchPlan);
  const expectedLaunchMode = launchPlan.setupMode ? 'setup_mode' : 'normal';
  const deadline = Date.now() + 2500;
  while (Date.now() <= deadline) {
    const health = await fetchRuntimeHealthOnce({ runtimeHealthUrl: launchPlan.runtimeHealthUrl });
    const lockPayload = readRuntimeLock(shellPaths);
    const lockSummary = summarizeRuntimeLock(lockPayload, {
      expectedBinding,
      expectedHost: desiredRuntimeHost(),
      expectedPort: desiredRuntimePort(),
    });
    const assessment = assessExistingRuntime({
      healthPayload: health,
      lockSummary,
      expectedBinding,
      expectedRuntimeVersion: expectedRuntimeHealthVersion(),
      expectedRuntimeUrl: launchPlan.runtimeUrl,
    });
    const healthMatchesLaunchTarget = Boolean(health)
      && runtimeHealthMatchesExpected(health, {
        expectedBinding,
        expectedRuntimeVersion: expectedRuntimeHealthVersion(),
        expectedRuntimeUrl: launchPlan.runtimeUrl,
      })
      && String(health?.launch_mode || '').trim() === expectedLaunchMode;
    writeShellLog(
      `[child-exit-check] code=${code ?? 'null'} signal=${signal ?? 'null'} `
      + `health=${health ? 'up' : 'down'} launch_match=${healthMatchesLaunchTarget} action=${assessment.action} reason=${assessment.reason} `
      + `lock_status=${String(lockSummary.status || '')}`,
    );
    if (healthMatchesLaunchTarget && health) {
      runtimeAttachmentMode = 'reattached';
      hydrateStateFromDisk({ runtimeHealth: health, lastError: '' });
      emitState({
        status: 'ready',
        label: 'Ready',
        bootStage: 'Runtime stayed healthy after launcher exit. Reattached to the live service.',
        runtimeUrl: health.runtime_url || launchPlan.runtimeUrl,
        runtimeHealth: health,
      });
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  return false;
}

async function handleUnexpectedRuntimeExit({ code, signal }) {
  const attempts = registerAutomaticRestart();
  await stopMcpSidecar();
  closeRuntimeWindow();
  await loadBootPage().catch(() => {});
  hydrateStateFromDisk({
    lastError: `Runtime exited unexpectedly. code=${code ?? 'null'} signal=${signal ?? 'null'}`,
  });
  if (!state.readyConfiguration || state.preferences.auto_start !== 'auto_start_if_ready' || state.preferences.runtime_desired_state === 'stopped') {
    emitState({
      status: 'degraded',
      label: 'Needs attention',
      bootStage: 'Runtime stopped unexpectedly. Start it again when you are ready.',
    });
    return;
  }
  if (attempts > MAX_AUTOMATIC_RESTARTS) {
    emitState({
      status: 'degraded',
      label: 'Needs attention',
      bootStage: 'Automatic restart paused after repeated failures. Use manual restart to continue.',
    });
    return;
  }
  emitState({
    status: 'booting',
    label: 'Starting',
    bootStage: `Runtime exited unexpectedly. Restarting automatically (${attempts}/${MAX_AUTOMATIC_RESTARTS}).`,
  });
  await startRuntime({ setupMode: false });
}

async function waitForRuntimeDown(runtimeHealthUrl, timeoutMs = 8000) {
  const startedAt = Date.now();
  while ((Date.now() - startedAt) <= timeoutMs) {
    const payload = await fetchRuntimeHealthOnce({ runtimeHealthUrl });
    if (!payload) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

async function terminateExistingRuntime(launchPlan) {
  writeShellLog(`[terminate-existing-runtime] shutdown_url=${launchPlan.runtimeShutdownUrl} health_url=${launchPlan.runtimeHealthUrl}`);
  try {
    await requestRuntimeShutdown({ runtimeShutdownUrl: launchPlan.runtimeShutdownUrl });
  } catch (error) {
    throw new Error(`Existing runtime refused desktop shutdown: ${error?.message || error}`);
  }
  const stopped = await waitForRuntimeDown(launchPlan.runtimeHealthUrl);
  if (!stopped) {
    throw new Error('Existing runtime did not stop in time.');
  }
}

async function loadRuntimeWindow(url) {
  if (!runtimeWindow || runtimeWindow.isDestroyed()) {
    createRuntimeWindow();
  }
  if (!runtimeWindow || runtimeWindow.isDestroyed()) {
    return;
  }
  try {
    await runtimeWindow.loadURL(url);
    showRuntimeWindow();
  } catch (error) {
    if (isBenignNavigationAbortError(error)) {
      writeShellLog(`[runtime-window] loadURL ignored code=${error?.code ?? ''} message=${error?.message || error} url=${url}`);
      showRuntimeWindow();
      return;
    }
    emitState({
      status: 'error',
      label: 'Error',
      bootStage: 'Runtime UI load failed.',
      lastError: `The runtime became healthy, but the desktop shell could not load it: ${error?.message || error}`,
    });
    throw error;
  }
}

function closeRuntimeWindow() {
  if (!runtimeWindow || runtimeWindow.isDestroyed()) {
    runtimeWindow = null;
    return;
  }
  runtimeWindow.close();
  runtimeWindow = null;
}

function quitForSmoke(code) {
  process.exitCode = code;
  quitAfterCleanup = true;
  setTimeout(() => {
    app.quit();
  }, 250);
}

function reportShellError(stage, error) {
  const message = error?.message || String(error || 'unknown error');
  emitState({
    status: 'error',
    label: 'Error',
    bootStage: stage,
    lastError: message,
  });
}

function buildLaunchPlan({ setupMode = false }) {
  if (!runtimeBundleManifest) {
    throw new Error('desktop runtime bundle manifest is unavailable');
  }
  return buildRuntimeLaunchPlan({
    repoRoot: state.repoRoot,
    runtimeManifest: runtimeBundleManifest,
    pythonCommand: cli.python || process.env.MNO_PYTHON || '',
    memories: setupMode ? '' : latestExpectedBinding.store_path,
    episodes: setupMode ? '' : latestExpectedBinding.episodes_path,
    host: desiredRuntimeHost(),
    port: desiredRuntimePort(),
    setupMode,
    setupModeStorePath: shellPaths.setupModeStorePath,
    requireBundledRuntime: app.isPackaged,
  });
}

function expectedBindingForLaunchPlan(launchPlan) {
  if (launchPlan && launchPlan.setupMode) {
    return {
      store_path: String(shellPaths.setupModeStorePath || '').trim(),
      store_fingerprint: '',
      episodes_path: '',
      build_id: '',
      artifact_mode: 'setup',
    };
  }
  return latestExpectedBinding;
}

async function reattachOrRecoverExistingRuntime(launchPlan, { openWorkspace = false, workspaceTab = '' } = {}) {
  const health = await fetchRuntimeHealthOnce({ runtimeHealthUrl: launchPlan.runtimeHealthUrl });
  const expectedBinding = expectedBindingForLaunchPlan(launchPlan);
  const lockPayload = readRuntimeLock(shellPaths);
  const lockSummary = summarizeRuntimeLock(lockPayload, {
    expectedBinding,
    expectedHost: desiredRuntimeHost(),
    expectedPort: desiredRuntimePort(),
  });
  const assessment = assessExistingRuntime({
    healthPayload: health,
    lockSummary,
    expectedBinding,
    expectedRuntimeVersion: expectedRuntimeHealthVersion(),
    expectedRuntimeUrl: launchPlan.runtimeUrl,
  });
  if (assessment.action === 'none') {
    return false;
  }
  if (assessment.action === 'reattach') {
    runtimeChild = null;
    runtimeAttachmentMode = 'reattached';
    expectedRuntimeExit = false;
    if (!launchPlan.setupMode) {
      await ensureMcpSidecar(health?.binding || expectedBinding);
    } else if (mcpBindingReady(latestExpectedMcpBinding)) {
      await ensureMcpSidecar(latestExpectedMcpBinding);
    } else {
      await stopMcpSidecar();
    }
    hydrateStateFromDisk({ runtimeHealth: health, lastError: '' });
    emitState({
      status: 'ready',
      label: 'Ready',
      bootStage: 'Reattached to the existing runtime.',
      runtimeUrl: health.runtime_url || launchPlan.runtimeUrl,
      runtimeHealth: health,
    });
    if (openWorkspace || runtimeWorkspaceOpen()) {
      await loadRuntimeWindow(buildRuntimeWorkspaceUrl(health.runtime_url || launchPlan.runtimeUrl, { tabId: workspaceTab || (launchPlan.setupMode ? 'setup' : 'chat') }));
    }
    return true;
  }
  emitState({
    status: 'booting',
    label: 'Starting',
    bootStage: 'Recovering an existing runtime before startup.',
  });
  await terminateExistingRuntime(launchPlan);
  return false;
}

async function startRuntime({ setupMode = false, openWorkspace = null, workspaceTab = '' } = {}) {
  if (restartPromise) {
    return restartPromise;
  }
  restartPromise = (async () => {
    const shouldOpenWorkspace = typeof openWorkspace === 'boolean' ? openWorkspace : runtimeWorkspaceOpen();
    hydrateStateFromDisk({ lastError: '' });
    if (!setupMode && !state.readyConfiguration) {
      await loadBootPage().catch(() => {});
      emitState({
        status: 'setup_required',
        label: 'Setup required',
        bootStage: 'Complete setup before starting the live runtime.',
      });
      return;
    }
    if (!setupMode) {
      persistPreferences({ runtime_desired_state: 'running' });
    }
    const launchPlan = buildLaunchPlan({ setupMode });
    runtimeLaunchPlan = launchPlan;
    writeShellLog(
      `[start] mode=${launchPlan.launchMode} expected_store=${String(expectedBindingForLaunchPlan(launchPlan).store_path || '')} `
      + `expected_fp=${String(expectedBindingForLaunchPlan(launchPlan).store_fingerprint || '')} `
      + `expected_episodes=${String(expectedBindingForLaunchPlan(launchPlan).episodes_path || '')}`,
    );
    await loadBootPage().catch(() => {});
    emitState({
      status: 'booting',
      label: 'Starting',
      runtimeUrl: launchPlan.runtimeUrl,
      lastError: '',
      bootStage: setupMode ? 'Starting the local setup workspace.' : 'Starting the local runtime.',
    });
    const reattached = await reattachOrRecoverExistingRuntime(launchPlan, { openWorkspace: shouldOpenWorkspace, workspaceTab });
    if (reattached) {
      if (cli.smokeExitWhenReady) {
        quitForSmoke(0);
      }
      return;
    }
    let launchCommand = launchPlan.command;
    let launchArgs = launchPlan.args;
    let attachmentMode = 'child';
    let childLogBundle = null;
    if (process.platform === 'win32') {
      childLogBundle = createRuntimeChildLogBundle();
      launchCommand = resolveWindowsGuiPythonCommand(launchPlan.command);
      launchArgs = launchPlan.args;
      writeShellLog(`[child-logs] stdout=${childLogBundle.stdoutPath} stderr=${childLogBundle.stderrPath} attachment=${attachmentMode}`);
    }
    writeShellLog(`launch command=${launchCommand} args=${JSON.stringify(launchArgs)} attachment=${attachmentMode}`);
    try {
      runtimeChild = spawn(
        launchCommand,
        launchArgs,
        buildRuntimeSpawnOptions({
          cwd: launchPlan.cwd,
          env: { ...process.env, MNO_RUNTIME_STATE_ROOT: shellPaths.runtimeRoot },
          platform: process.platform,
          stdio: process.platform === 'win32'
            ? ['ignore', childLogBundle.stdoutFd, childLogBundle.stderrFd]
            : ['ignore', 'pipe', 'pipe'],
        }),
      );
    } finally {
      closeRuntimeChildLogBundle(childLogBundle);
    }
    runtimeAttachmentMode = attachmentMode;
    expectedRuntimeExit = false;
    const { spawnErrorPromise, earlyExitPromise } = attachRuntimeLogging(runtimeChild, launchPlan, { childLogBundle, attachmentMode });
    const bootWaiters = [
      waitForRuntimeReady({ runtimeHealthUrl: launchPlan.runtimeHealthUrl, timeoutMs: Number(cli.bootTimeoutMs || 30000) }).then((ready) => ({ type: 'health', ready })),
      spawnErrorPromise.then((error) => ({ type: 'spawn_error', error })),
    ];
    if (attachmentMode !== 'launcher') {
      bootWaiters.push(earlyExitPromise.then((payload) => ({ type: 'early_exit', payload })));
    }
    const bootResult = await Promise.race([
      ...bootWaiters,
    ]);
    if (bootResult.type === 'spawn_error' || bootResult.type === 'early_exit') {
      return;
    }
    if (!bootResult.ready) {
      await stopRuntime({ explicitUserStop: false, reloadBootUi: false });
      const timeoutLabel = formatTimeoutLabel(Number(cli.bootTimeoutMs || 30000));
      emitState({
        status: 'error',
        label: 'Error',
        bootStage: 'Runtime boot timed out.',
        lastError: `The local runtime did not become healthy within ${timeoutLabel}.`,
      });
      if (cli.smokeExitWhenReady) {
        quitForSmoke(1);
      }
      return;
    }
    const health = await fetchRuntimeHealthOnce({ runtimeHealthUrl: launchPlan.runtimeHealthUrl });
    writeShellLog(
      `[health] mode=${launchPlan.launchMode} runtime_url=${launchPlan.runtimeUrl} `
      + `binding_store=${String((health?.binding || {}).store_path || '')} `
      + `binding_fp=${String((health?.binding || {}).store_fingerprint || '')} `
      + `binding_episodes=${String((health?.binding || {}).episodes_path || '')}`,
    );
    const lastKnownGoodRuntime = saveLastKnownGoodRuntime(shellPaths, runtimeBundleManifest, { appVersion, runtimeUrl: launchPlan.runtimeUrl });
    if (attachmentMode === 'launcher') {
      runtimeChild = null;
      runtimeAttachmentMode = 'reattached';
    }
    if (setupMode) {
      if (mcpBindingReady(latestExpectedMcpBinding)) {
        await ensureMcpSidecar(latestExpectedMcpBinding);
      } else {
        await stopMcpSidecar();
      }
      hydrateStateFromDisk({ runtimeHealth: health, lastError: '' });
      emitState({
        status: 'setup_required',
        label: 'Setup required',
        bootStage: 'Setup workspace ready. Open setup when you want to continue the guided flow.',
        runtimeUrl: launchPlan.runtimeUrl,
        runtimeHealth: health,
        lastKnownGoodRuntime,
      });
      if (shouldOpenWorkspace || runtimeWorkspaceOpen()) {
        await loadRuntimeWindow(buildRuntimeWorkspaceUrl(launchPlan.runtimeUrl, { tabId: workspaceTab || 'setup' }));
      }
    } else {
      await ensureMcpSidecar(health?.binding || latestExpectedBinding);
      hydrateStateFromDisk({ runtimeHealth: health, lastError: '' });
      emitState({
        status: 'ready',
        label: 'Ready',
        bootStage: 'Runtime ready in the background. Open chat + memory when you want to use it.',
        runtimeUrl: launchPlan.runtimeUrl,
        runtimeHealth: health,
        lastKnownGoodRuntime,
      });
      if (shouldOpenWorkspace || runtimeWorkspaceOpen()) {
        await loadRuntimeWindow(buildRuntimeWorkspaceUrl(launchPlan.runtimeUrl, { tabId: workspaceTab || 'chat' }));
      }
    }
    if (cli.smokeExitWhenReady) {
      quitForSmoke(0);
    }
  })();
  try {
    await restartPromise;
  } finally {
    restartPromise = null;
  }
}

async function stopRuntime({ explicitUserStop = false, reloadBootUi = true } = {}) {
  writeShellLog(
    `[stop-runtime] explicit=${Boolean(explicitUserStop)} reload_boot=${Boolean(reloadBootUi)} `
      + `attachment=${runtimeAttachmentMode || ''} child_pid=${runtimeChild?.pid || 0} runtime_url=${state.runtimeUrl || ''}`,
  );
  if (explicitUserStop) {
    persistPreferences({ runtime_desired_state: 'stopped' });
  }
  shuttingDown = true;
  expectedRuntimeExit = true;
  let shutdownFailure = null;
  const remoteRuntimeUrl = String(state.runtimeUrl || '').replace(/\/$/, '');
  const remoteRuntimeHealthUrl = remoteRuntimeUrl ? `${remoteRuntimeUrl}/api/runtime/health` : '';
  try {
    const shouldPreferRemoteShutdown = process.platform === 'win32'
      && remoteRuntimeUrl
      && (runtimeAttachmentMode === 'child' || runtimeAttachmentMode === 'reattached' || runtimeAttachmentMode === 'launcher');
    if (shouldPreferRemoteShutdown) {
      writeShellLog(`[stop-runtime] preferring remote desktop shutdown for windows child runtime url=${remoteRuntimeUrl}`);
      await requestRuntimeShutdown({ runtimeShutdownUrl: `${remoteRuntimeUrl}/api/runtime/desktop/shutdown` });
      const stopped = await waitForRuntimeDown(remoteRuntimeHealthUrl);
      if (!stopped) {
        throw new Error(`remote runtime did not stop in time: ${remoteRuntimeUrl}`);
      }
      runtimeChild = null;
    } else if (runtimeChild) {
      const child = runtimeChild;
      runtimeChild = null;
      writeShellLog(`[stop-runtime] sending SIGINT to child pid=${child.pid || 0}`);
      try {
        child.kill('SIGINT');
      } catch (_error) {
        // Best effort.
      }
      const exitedOnSigint = await waitForChildExit(child, { timeoutMs: 1500 });
      if (!exitedOnSigint) {
        writeShellLog(`[stop-runtime] child pid=${child.pid || 0} ignored SIGINT; sending SIGTERM`);
        try {
          child.kill('SIGTERM');
        } catch (_error) {
          // Best effort.
        }
        const exitedOnSigterm = await waitForChildExit(child, { timeoutMs: 1500 });
        if (!exitedOnSigterm) {
          writeShellLog(`[stop-runtime] child pid=${child.pid || 0} ignored SIGTERM; sending SIGKILL`);
          try {
            child.kill('SIGKILL');
          } catch (_error) {
            // Best effort.
          }
          await waitForChildExit(child, { timeoutMs: 1000 });
        }
      }
    } else if (
      runtimeAttachmentMode === 'reattached'
      || (state.runtimeUrl && state.runtimeHealth && state.runtimeHealth.service === 'modelnumquamoblita-runtime')
    ) {
      try {
        await requestRuntimeShutdown({ runtimeShutdownUrl: `${remoteRuntimeUrl}/api/runtime/desktop/shutdown` });
        const stopped = await waitForRuntimeDown(remoteRuntimeHealthUrl);
        if (!stopped) {
          throw new Error(`remote runtime did not stop in time: ${remoteRuntimeUrl}`);
        }
      } catch (error) {
        shutdownFailure = error instanceof Error ? error : new Error(String(error || 'remote shutdown failed'));
        writeShellLog(`[stop-runtime] remote shutdown failed for ${remoteRuntimeUrl}: ${shutdownFailure.message}`);
        throw shutdownFailure;
      }
    }
  } finally {
    await stopMcpSidecar();
    runtimeAttachmentMode = '';
    runtimeLaunchPlan = null;
    expectedRuntimeExit = false;
    shuttingDown = false;
    const refreshedRemoteHealth = shutdownFailure && remoteRuntimeHealthUrl
      ? await fetchRuntimeHealthOnce({ runtimeHealthUrl: remoteRuntimeHealthUrl })
      : null;
    hydrateStateFromDisk({
      runtimeHealth: refreshedRemoteHealth,
      lastError: shutdownFailure ? shutdownFailure.message : '',
    });
    if (reloadBootUi) {
      await loadBootPage().catch(() => {});
    }
    closeRuntimeWindow();
  }
}

async function restartRuntime() {
  await loadBootPage().catch(() => {});
  persistPreferences({ runtime_desired_state: 'running' });
  await stopRuntime({ explicitUserStop: false, reloadBootUi: false });
  return startRuntime({ setupMode: !state.readyConfiguration, openWorkspace: runtimeWorkspaceOpen() });
}

async function repairRuntimeClaim() {
  hydrateStateFromDisk({ lastError: '' });
  const lockSummary = state.lock || {};
  writeShellLog(`[repair-runtime] lock_status=${String(lockSummary.status || '')} ready_configuration=${Boolean(state.readyConfiguration)}`);
  if (String(lockSummary.status || '') === 'stale' && shellPaths.runtimeLockPath) {
    try {
      fs.unlinkSync(shellPaths.runtimeLockPath);
      writeShellLog(`[repair-runtime] removed stale lock path=${shellPaths.runtimeLockPath}`);
    } catch (_error) {
      // Best effort.
    }
    hydrateStateFromDisk({ lastError: '' });
  }
  await loadBootPage().catch(() => {});
  emitState({
    status: state.readyConfiguration ? 'booting' : 'degraded',
    label: state.readyConfiguration ? 'Starting' : 'Needs attention',
    bootStage: state.readyConfiguration
      ? 'Repair finished. Re-checking the runtime claim against the selected store.'
      : 'Repair finished. Finish setup only if the selected store or reviewed set is still missing.',
    lastError: '',
  });
  if (state.readyConfiguration) {
    await startRuntime({ setupMode: false, openWorkspace: false });
    return;
  }
  await startRuntime({ setupMode: true, openWorkspace: true });
}

async function performInitialLaunch() {
  hydrateStateFromDisk({ lastError: '' });
  if (state.status === 'error') {
    return;
  }
  if (state.status === 'setup_required') {
    await loadBootPage().catch(() => {});
    return;
  }
  if (state.autoStartAllowed) {
    await startRuntime({ setupMode: false, openWorkspace: false });
    return;
  }
  if (state.status === 'stopped' || state.status === 'degraded') {
    await loadBootPage().catch(() => {});
  }
}

app.on('second-instance', () => {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow();
  }
  refreshDesktopHomeState().catch(() => {}).finally(() => showMainWindow());
});

app.whenReady()
  .then(async () => {
    registerIpc();
    createWindow();
    createTrayIfSupported();
    app.on('activate', () => {
      if (!mainWindow || mainWindow.isDestroyed()) {
        createWindow();
      }
      showMainWindow();
    });
    await performInitialLaunch();
  })
  .catch((error) => {
    reportShellError('desktop shell startup failed', error);
    if (cli.smokeExitWhenReady) {
      quitForSmoke(1);
    }
  });

process.on('uncaughtException', (error) => {
  writeShellDiagnostic(`[uncaughtException] ${error?.stack || error?.message || error}`);
});

process.on('unhandledRejection', (reason) => {
  writeShellDiagnostic(`[unhandledRejection] ${reason?.stack || reason?.message || reason}`);
});

process.on('SIGINT', () => {
  writeShellDiagnostic(`[signal] main process received SIGINT ignore_dev=${Boolean(shouldIgnoreDevSignal())}`);
  if (shouldIgnoreDevSignal()) {
    return;
  }
  app.quit();
});

process.on('SIGTERM', () => {
  writeShellDiagnostic(`[signal] main process received SIGTERM ignore_dev=${Boolean(shouldIgnoreDevSignal())}`);
  if (shouldIgnoreDevSignal()) {
    return;
  }
  app.quit();
});

app.on('window-all-closed', () => {
  writeShellLog('window-all-closed received; desktop shell remains alive for tray/menu behavior');
});

app.on('before-quit', (event) => {
  if (quitAfterCleanup) {
    return;
  }
  if (!runtimeChild && runtimeAttachmentMode !== 'reattached' && !state.runtimeUrl) {
    return;
  }
  event.preventDefault();
  quitAfterCleanup = true;
  stopRuntime({ explicitUserStop: false, reloadBootUi: false })
    .catch((error) => {
      writeShellLog(`[before-quit] stopRuntime failed: ${error?.message || error}`);
    })
    .finally(() => {
      app.quit();
    });
});
