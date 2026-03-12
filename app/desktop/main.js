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
  deriveShellStartupState,
  fetchRuntimeHealthOnce,
  formatTimeoutLabel,
  hydratedRuntimeUrl,
  loadDesktopAppVersion,
  loadLastKnownGoodRuntime,
  loadLatestWizardState,
  loadRuntimeBundleManifest,
  loadShellPreferences,
  parseRuntimeStdoutLine,
  parseShellCliArgs,
  readRuntimeLock,
  requestRuntimeShutdown,
  resolveShellPaths,
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
};

let mainWindow = null;
let runtimeChild = null;
let tray = null;
let shuttingDown = false;
let expectedRuntimeExit = false;
let quitAfterCleanup = false;
let restartPromise = null;
let runtimeLaunchPlan = null;
let runtimeAttachmentMode = '';
let latestWizardState = null;
let latestExpectedBinding = {};
let runtimeBundleManifest = null;
let restartHistory = [];

const FIVE_MINUTES_MS = 5 * 60 * 1000;
const MAX_AUTOMATIC_RESTARTS = 2;

function desiredRuntimeHost() {
  return String(cli.host || process.env.MNO_RUNTIME_HOST || '127.0.0.1').trim() || '127.0.0.1';
}

function desiredRuntimePort() {
  const numeric = Number(cli.port || process.env.MNO_RUNTIME_PORT || 7340);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 7340;
}

function desiredRuntimeUrl() {
  return `http://${desiredRuntimeHost()}:${desiredRuntimePort()}`;
}

function logDir() {
  const dir = shellPaths.desktopShellRoot;
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function writeShellLog(line) {
  const logPath = state.logPath || path.join(logDir(), `desktop_shell_${new Date().toISOString().replace(/[:.]/g, '-')}.log`);
  state.logPath = logPath;
  fs.appendFileSync(logPath, `${new Date().toISOString()} ${line}${os.EOL}`, 'utf8');
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
      'open-app': () => showMainWindow(),
      'start-runtime': () => startRuntime({ setupMode: false }).catch((error) => reportShellError('start runtime failed', error)),
      'open-setup': () => startRuntime({ setupMode: true }).catch((error) => reportShellError('open setup failed', error)),
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
    tray.on('click', () => showMainWindow());
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
  latestExpectedBinding = latest.state ? buildExpectedBinding(latest.state) : {};
  const lockPayload = readRuntimeLock(shellPaths);
  const lockSummary = summarizeRuntimeLock(lockPayload, {
    expectedBinding: latestExpectedBinding,
    expectedHost: desiredRuntimeHost(),
    expectedPort: desiredRuntimePort(),
  });
  const currentRuntimeUrl = hydratedRuntimeUrl(runtimeHealth);
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
    title: 'ModelNumquamOblita',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });
  mainWindow.on('close', async (event) => {
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
    emitState({
      status: 'error',
      label: 'Error',
      bootStage: 'Desktop shell failed to load.',
      lastError: `Failed to load desktop shell: ${error?.message || error}`,
    });
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
    await startRuntime({ setupMode: false });
    return { ...state };
  });
  ipcMain.handle('desktop-shell:start-setup', async () => {
    await startRuntime({ setupMode: true });
    return { ...state };
  });
  ipcMain.handle('desktop-shell:repair-runtime', async () => {
    await repairRuntimeClaim();
    return { ...state };
  });
  ipcMain.handle('desktop-shell:restart-runtime', async () => {
    await restartRuntime();
    return { ...state };
  });
  ipcMain.handle('desktop-shell:stop-runtime', async () => {
    await stopRuntime({ explicitUserStop: true, reloadBootUi: true });
    return { ...state };
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
  ipcMain.handle('desktop-shell:open-external-ui', async () => {
    if (!state.runtimeUrl) {
      return false;
    }
    await shell.openExternal(state.runtimeUrl);
    return true;
  });
}

function attachRuntimeLogging(child, launchPlan) {
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
  child.stderr.on('data', (chunk) => {
    const text = String(chunk || '').trimEnd();
    if (!text) {
      return;
    }
    writeShellLog(`[stderr] ${text}`);
    emitState({ lastError: text });
  });
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
    resolveEarlyExit({ code, signal });
    if (shuttingDown || expectedRuntimeExit) {
      return;
    }
    runtimeChild = null;
    runtimeAttachmentMode = '';
    handleUnexpectedRuntimeExit({ code, signal, launchPlan }).catch((error) => {
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

async function handleUnexpectedRuntimeExit({ code, signal }) {
  const attempts = registerAutomaticRestart();
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
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  try {
    await mainWindow.loadURL(url);
    showMainWindow();
  } catch (error) {
    await loadBootPage().catch(() => {});
    emitState({
      status: 'error',
      label: 'Error',
      bootStage: 'Runtime UI load failed.',
      lastError: `The runtime became healthy, but the desktop shell could not load it: ${error?.message || error}`,
    });
    throw error;
  }
}

function quitForSmoke(code) {
  process.exitCode = code;
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

async function reattachOrRecoverExistingRuntime(launchPlan) {
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
    expectedRuntimeVersion: launchPlan.runtimeVersion,
    expectedRuntimeUrl: launchPlan.runtimeUrl,
  });
  if (assessment.action === 'none') {
    return false;
  }
  if (assessment.action === 'reattach') {
    runtimeChild = null;
    runtimeAttachmentMode = 'reattached';
    expectedRuntimeExit = false;
    hydrateStateFromDisk({ runtimeHealth: health, lastError: '' });
    emitState({
      status: 'ready',
      label: 'Ready',
      bootStage: 'Reattached to the existing runtime.',
      runtimeUrl: health.runtime_url || launchPlan.runtimeUrl,
      runtimeHealth: health,
    });
    await loadRuntimeWindow(health.runtime_url || launchPlan.runtimeUrl);
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

async function startRuntime({ setupMode = false } = {}) {
  if (restartPromise) {
    return restartPromise;
  }
  restartPromise = (async () => {
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
    await loadBootPage().catch(() => {});
    emitState({
      status: 'booting',
      label: 'Starting',
      runtimeUrl: launchPlan.runtimeUrl,
      lastError: '',
      bootStage: setupMode ? 'Starting the local setup workspace.' : 'Starting the local runtime.',
    });
    const reattached = await reattachOrRecoverExistingRuntime(launchPlan);
    if (reattached) {
      if (cli.smokeExitWhenReady) {
        quitForSmoke(0);
      }
      return;
    }
    writeShellLog(`launch command=${launchPlan.command} args=${JSON.stringify(launchPlan.args)}`);
    runtimeChild = spawn(
      launchPlan.command,
      launchPlan.args,
      buildRuntimeSpawnOptions({
        cwd: launchPlan.cwd,
        env: { ...process.env, MNO_RUNTIME_STATE_ROOT: shellPaths.runtimeRoot },
        platform: process.platform,
      }),
    );
    runtimeAttachmentMode = 'child';
    expectedRuntimeExit = false;
    const { spawnErrorPromise, earlyExitPromise } = attachRuntimeLogging(runtimeChild, launchPlan);
    const bootResult = await Promise.race([
      waitForRuntimeReady({ runtimeHealthUrl: launchPlan.runtimeHealthUrl, timeoutMs: Number(cli.bootTimeoutMs || 30000) }).then((ready) => ({ type: 'health', ready })),
      spawnErrorPromise.then((error) => ({ type: 'spawn_error', error })),
      earlyExitPromise.then((payload) => ({ type: 'early_exit', payload })),
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
    const lastKnownGoodRuntime = saveLastKnownGoodRuntime(shellPaths, runtimeBundleManifest, { appVersion, runtimeUrl: launchPlan.runtimeUrl });
    if (setupMode) {
      hydrateStateFromDisk({ runtimeHealth: health, lastError: '' });
      emitState({
        status: 'setup_required',
        label: 'Setup required',
        bootStage: 'Setup workspace ready. Finish the guided workflow before normal background serving.',
        runtimeUrl: launchPlan.runtimeUrl,
        runtimeHealth: health,
        lastKnownGoodRuntime,
      });
      await loadRuntimeWindow(launchPlan.runtimeUrl);
    } else {
      hydrateStateFromDisk({ runtimeHealth: health, lastError: '' });
      emitState({
        status: 'ready',
        label: 'Ready',
        bootStage: 'Runtime ready.',
        runtimeUrl: launchPlan.runtimeUrl,
        runtimeHealth: health,
        lastKnownGoodRuntime,
      });
      await loadRuntimeWindow(launchPlan.runtimeUrl);
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
  if (explicitUserStop) {
    persistPreferences({ runtime_desired_state: 'stopped' });
  }
  shuttingDown = true;
  expectedRuntimeExit = true;
  try {
    if (runtimeChild) {
      const child = runtimeChild;
      runtimeChild = null;
      try {
        child.kill('SIGINT');
      } catch (_error) {
        // Best effort.
      }
      const exitedOnSigint = await waitForChildExit(child, { timeoutMs: 1500 });
      if (!exitedOnSigint) {
        try {
          child.kill('SIGTERM');
        } catch (_error) {
          // Best effort.
        }
        const exitedOnSigterm = await waitForChildExit(child, { timeoutMs: 1500 });
        if (!exitedOnSigterm) {
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
        await requestRuntimeShutdown({ runtimeShutdownUrl: `${String(state.runtimeUrl || '').replace(/\/$/, '')}/api/runtime/desktop/shutdown` });
        await waitForRuntimeDown(`${String(state.runtimeUrl || '').replace(/\/$/, '')}/api/runtime/health`);
      } catch (error) {
        writeShellLog(`[stop-runtime] remote shutdown failed: ${error?.message || error}`);
      }
    }
  } finally {
    runtimeAttachmentMode = '';
    runtimeLaunchPlan = null;
    expectedRuntimeExit = false;
    shuttingDown = false;
    hydrateStateFromDisk({ lastError: '' });
    if (reloadBootUi) {
      await loadBootPage().catch(() => {});
    }
  }
}

async function restartRuntime() {
  await loadBootPage().catch(() => {});
  persistPreferences({ runtime_desired_state: 'running' });
  await stopRuntime({ explicitUserStop: false, reloadBootUi: false });
  return startRuntime({ setupMode: !state.readyConfiguration });
}

async function repairRuntimeClaim() {
  hydrateStateFromDisk({ lastError: '' });
  const lockSummary = state.lock || {};
  if (String(lockSummary.status || '') === 'stale' && shellPaths.runtimeLockPath) {
    try {
      fs.unlinkSync(shellPaths.runtimeLockPath);
    } catch (_error) {
      // Best effort.
    }
    hydrateStateFromDisk({ lastError: '' });
  }
  if (state.readyConfiguration) {
    await startRuntime({ setupMode: false });
    return;
  }
  await startRuntime({ setupMode: true });
}

async function performInitialLaunch() {
  hydrateStateFromDisk({ lastError: '' });
  if (state.status === 'error') {
    return;
  }
  if (state.status === 'setup_required') {
    await startRuntime({ setupMode: true });
    return;
  }
  if (state.autoStartAllowed) {
    await startRuntime({ setupMode: false });
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
  showMainWindow();
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
