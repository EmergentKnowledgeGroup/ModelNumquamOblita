const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {
  buildRuntimeLaunchPlan,
  parseRuntimeStdoutLine,
  parseShellCliArgs,
  resolveShellPaths,
  waitForChildExit,
  waitForRuntimeReady,
} = require('./runtime-controller.cjs');
const { EventEmitter } = require('node:events');

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
  const plan = buildRuntimeLaunchPlan({ repoRoot: '/repo', pythonCommand: 'python3', host: '127.0.0.1', port: 8123, memories: '/tmp/store.sqlite3', episodes: '/tmp/cards.json' });
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

test('parseRuntimeStdoutLine accepts key-value output only', () => {
  assert.deepEqual(parseRuntimeStdoutLine('runtime_url=http://127.0.0.1:7340'), { key: 'runtime_url', value: 'http://127.0.0.1:7340' });
  assert.equal(parseRuntimeStdoutLine('Press Ctrl+C to stop.'), null);
});

test('resolveShellPaths keeps runtime folders anchored to repo root', () => {
  const paths = resolveShellPaths('/repo');
  assert.equal(paths.repoRoot, '/repo');
  assert.equal(paths.runtimeRoot, '/repo/runtime');
  assert.equal(paths.wizardRunsRoot, '/repo/runtime/wizard_runs');
  assert.equal(paths.publishedSetsRoot, '/repo/runtime/episodes');
  assert.equal(paths.desktopShellRoot, '/repo/runtime/desktop_shell');
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
