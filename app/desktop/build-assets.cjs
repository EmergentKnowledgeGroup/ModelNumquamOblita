const path = require('node:path');
const { spawnSync } = require('node:child_process');

function assetCommandForPlatform(platform = process.platform, root = __dirname) {
  if (platform !== 'darwin') {
    return null;
  }
  return {
    command: '/bin/bash',
    args: [path.join(root, 'build', 'generate_macos_icon.sh')],
  };
}

function main() {
  const plan = assetCommandForPlatform();
  if (!plan) {
    process.stdout.write(`desktop assets: no platform-specific build required for ${process.platform}\n`);
    return 0;
  }
  const result = spawnSync(plan.command, plan.args, {
    cwd: __dirname,
    stdio: 'inherit',
    windowsHide: true,
  });
  if (result.error) {
    throw result.error;
  }
  return Number.isInteger(result.status) ? result.status : 1;
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = { assetCommandForPlatform, main };
