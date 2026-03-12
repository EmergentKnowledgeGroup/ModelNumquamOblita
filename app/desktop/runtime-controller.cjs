const path = require('node:path');
const { once } = require('node:events');

function resolveRepoRoot(explicitRoot) {
  return explicitRoot ? path.resolve(String(explicitRoot)) : path.resolve(__dirname, '..', '..');
}

function resolveShellPaths(repoRoot) {
  const resolvedRoot = resolveRepoRoot(repoRoot);
  const runtimeRoot = path.join(resolvedRoot, 'runtime');
  return {
    repoRoot: resolvedRoot,
    runtimeRoot,
    wizardRunsRoot: path.join(runtimeRoot, 'wizard_runs'),
    publishedSetsRoot: path.join(runtimeRoot, 'episodes'),
    desktopShellRoot: path.join(runtimeRoot, 'desktop_shell'),
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

function buildRuntimeLaunchPlan({
  repoRoot,
  pythonCommand = '',
  memories = '',
  episodes = '',
  host = '127.0.0.1',
  port = 7340,
} = {}) {
  const resolvedRoot = resolveRepoRoot(repoRoot);
  const runtimePort = Number.isFinite(Number(port)) && Number(port) > 0 ? Number(port) : 7340;
  const runtimeHost = String(host || '127.0.0.1').trim() || '127.0.0.1';
  const command = String(pythonCommand || '').trim() || defaultPythonCommand();
  const args = [
    path.join(resolvedRoot, 'tools', 'run_live_runtime.py'),
    '--host',
    runtimeHost,
    '--port',
    String(runtimePort),
  ];
  if (String(memories || '').trim()) {
    args.push('--memories', path.resolve(String(memories)));
  }
  if (String(episodes || '').trim()) {
    args.push('--episodes', path.resolve(String(episodes)));
  }
  return {
    repoRoot: resolvedRoot,
    cwd: resolvedRoot,
    command,
    args,
    runtimeUrl: `http://${runtimeHost}:${runtimePort}`,
    runtimeHealthUrl: `http://${runtimeHost}:${runtimePort}/api/runtime/health`,
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
  buildRuntimeLaunchPlan,
  defaultPythonCommand,
  formatTimeoutLabel,
  parseRuntimeStdoutLine,
  parseShellCliArgs,
  resolveRepoRoot,
  resolveShellPaths,
  waitForChildExit,
  waitForRuntimeReady,
};
