const { spawnSync } = require('node:child_process');
const path = require('node:path');

function buildElectronBuilderInvocation(rawArgs, { platform = process.platform, env = process.env } = {}) {
  const unsignedMacLocal = rawArgs.includes('--unsigned-mac-local');
  const args = rawArgs.filter((entry) => entry !== '--unsigned-mac-local');
  const nextEnv = { ...env };
  if (platform === 'darwin' && unsignedMacLocal) {
    args.push('-c.mac.identity=null');
    nextEnv.CSC_IDENTITY_AUTO_DISCOVERY = 'false';
  }
  return {
    args,
    env: nextEnv,
  };
}

function main() {
  const { args, env } = buildElectronBuilderInvocation(process.argv.slice(2));
  const cliPath = path.resolve(__dirname, 'node_modules', 'electron-builder', 'cli.js');
  const result = spawnSync(process.execPath, [cliPath, ...args], {
    cwd: __dirname,
    stdio: 'inherit',
    env,
    shell: false,
  });
  if (typeof result.status === 'number') {
    process.exit(result.status);
  }
  process.exit(1);
}

module.exports = {
  buildElectronBuilderInvocation,
};

if (require.main === module) {
  main();
}
