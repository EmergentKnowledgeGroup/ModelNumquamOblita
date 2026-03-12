const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { app, BrowserWindow, ipcMain, shell } = require('electron');
const {
  buildRuntimeLaunchPlan,
  formatTimeoutLabel,
  parseRuntimeStdoutLine,
  parseShellCliArgs,
  resolveShellPaths,
  waitForChildExit,
  waitForRuntimeReady,
} = require('./runtime-controller.cjs');

const cli = parseShellCliArgs(process.argv.slice(1));
const shellPaths = resolveShellPaths(cli.repoRoot || process.env.MNO_REPO_ROOT || '');
const state = {
  status: 'idle',
  runtimeUrl: '',
  storePath: '',
  episodeCardsPath: '',
  repoRoot: shellPaths.repoRoot,
  runtimeRoot: shellPaths.runtimeRoot,
  wizardRunsPath: shellPaths.wizardRunsRoot,
  publishedSetsPath: shellPaths.publishedSetsRoot,
  logPath: '',
  lastError: '',
  bootStage: 'idle',
};

let mainWindow = null;
let runtimeChild = null;
let shuttingDown = false;
let launchPlan = null;
let expectedRuntimeExit = false;
let restartPromise = null;
let quitAfterCleanup = false;

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

function emitState(patch = {}) {
  Object.assign(state, patch);
  writeShellLog(`state status=${state.status} stage=${state.bootStage} runtime_url=${state.runtimeUrl || ''}`);
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
  loadBootPage().catch((error) => {
    emitState({
      status: 'error',
      bootStage: 'boot shell failed',
      lastError: `Failed to load desktop shell: ${error?.message || error}`,
    });
  });
}

function registerIpc() {
  ipcMain.handle('desktop-shell:get-state', async () => ({ ...state }));
  ipcMain.handle('desktop-shell:restart-runtime', async () => {
    await restartRuntime();
    return { ...state };
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

function attachRuntimeLogging(child) {
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
      emitState({ runtimeUrl: parsed.value, bootStage: 'probing runtime health' });
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
    expectedRuntimeExit = false;
    const message = `Failed to start the local runtime: ${error?.message || error}`;
    writeShellLog(`[error] ${message}`);
    emitState({
      status: 'error',
      bootStage: 'runtime launch failed',
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
    emitState({
      status: 'error',
      bootStage: 'runtime exited',
      lastError: `Runtime exited before the desktop shell was done. code=${code ?? 'null'} signal=${signal ?? 'null'}`,
    });
    runtimeChild = null;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.loadFile(path.join(__dirname, 'boot.html')).catch(() => {});
    }
  });
  return { spawnErrorPromise, earlyExitPromise };
}

async function stopRuntime() {
  if (!runtimeChild) {
    return;
  }
  const child = runtimeChild;
  runtimeChild = null;
  shuttingDown = true;
  expectedRuntimeExit = true;
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
  expectedRuntimeExit = false;
  shuttingDown = false;
}

async function loadRuntimeWindow(url) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  try {
    await mainWindow.loadURL(url);
    mainWindow.show();
  } catch (error) {
    await loadBootPage().catch(() => {});
    emitState({
      status: 'error',
      bootStage: 'runtime ui load failed',
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
    bootStage: stage,
    lastError: message,
  });
}

async function startRuntime() {
  launchPlan = buildRuntimeLaunchPlan({
    repoRoot: state.repoRoot,
    pythonCommand: cli.python || process.env.MNO_PYTHON || '',
    memories: cli.memories || process.env.MNO_MEMORIES || '',
    episodes: cli.episodes || process.env.MNO_EPISODES || '',
    host: cli.host || process.env.MNO_RUNTIME_HOST || '127.0.0.1',
    port: Number(cli.port || process.env.MNO_RUNTIME_PORT || 7340),
  });
  emitState({
    status: 'booting',
    runtimeUrl: launchPlan.runtimeUrl,
    storePath: cli.memories || process.env.MNO_MEMORIES || '',
    episodeCardsPath: cli.episodes || process.env.MNO_EPISODES || '',
    lastError: '',
    bootStage: 'starting local runtime',
  });
  writeShellLog(`launch command=${launchPlan.command} args=${JSON.stringify(launchPlan.args)}`);
  runtimeChild = spawn(launchPlan.command, launchPlan.args, {
    cwd: launchPlan.cwd,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const { spawnErrorPromise, earlyExitPromise } = attachRuntimeLogging(runtimeChild);
  const bootResult = await Promise.race([
    waitForRuntimeReady({
      runtimeHealthUrl: launchPlan.runtimeHealthUrl,
      timeoutMs: Number(cli.bootTimeoutMs || 30000),
    }).then((ready) => ({ type: 'health', ready })),
    spawnErrorPromise.then((error) => ({ type: 'spawn_error', error })),
    earlyExitPromise.then((payload) => ({ type: 'early_exit', payload })),
  ]);
  if (bootResult.type === 'spawn_error') {
    return;
  }
  if (bootResult.type === 'early_exit') {
    return;
  }
  if (!bootResult.ready) {
    await stopRuntime();
    const timeoutLabel = formatTimeoutLabel(Number(cli.bootTimeoutMs || 30000));
    emitState({
      status: 'error',
      bootStage: 'runtime boot timeout',
      lastError: `The local runtime did not become healthy within ${timeoutLabel}.`,
    });
    if (cli.smokeExitWhenReady) {
      quitForSmoke(1);
    }
    return;
  }
  emitState({ status: 'ready', bootStage: 'runtime ready' });
  if (mainWindow && !mainWindow.isDestroyed()) {
    await loadRuntimeWindow(launchPlan.runtimeUrl);
  }
  if (cli.smokeExitWhenReady) {
    quitForSmoke(0);
  }
}

async function restartRuntime() {
  if (restartPromise) {
    return restartPromise;
  }
  restartPromise = (async () => {
    await loadBootPage().catch(() => {});
    await stopRuntime();
    await startRuntime();
  })();
  try {
    await restartPromise;
  } finally {
    restartPromise = null;
  }
}

app.whenReady()
  .then(async () => {
    registerIpc();
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
        if (process.platform === 'darwin' && !runtimeChild) {
          restartRuntime().catch((error) => reportShellError('runtime restart failed', error));
        }
      }
    });
    createWindow();
    await startRuntime();
  })
  .catch((error) => {
    reportShellError('desktop shell startup failed', error);
  });

app.on('window-all-closed', async () => {
  await stopRuntime();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', (event) => {
  if (quitAfterCleanup || !runtimeChild) {
    return;
  }
  event.preventDefault();
  quitAfterCleanup = true;
  stopRuntime()
    .catch((error) => {
      writeShellLog(`[before-quit] stopRuntime failed: ${error?.message || error}`);
    })
    .finally(() => {
      app.quit();
    });
});
