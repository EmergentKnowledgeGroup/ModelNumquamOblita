const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const distRoot = path.join(__dirname, 'dist');
const runtimeBuildRoot = path.join(__dirname, 'build', 'runtime');
const quarantineRoot = path.join(__dirname, 'build', '.clean-pack-quarantine');

function bestEffortRemove(targetPath) {
  try {
    fs.rmSync(targetPath, { recursive: true, force: true });
    return true;
  } catch (error) {
    if (!['ENOTEMPTY', 'EPERM', 'EBUSY'].includes(error?.code || '')) {
      throw error;
    }
  }
  if (process.platform === 'win32') {
    try {
      execFileSync(
        'powershell.exe',
        ['-NoProfile', '-NonInteractive', '-Command', `Remove-Item -LiteralPath '${targetPath.replace(/'/g, "''")}' -Recurse -Force -ErrorAction SilentlyContinue`],
        { stdio: 'ignore' },
      );
    } catch (_) {
      // fall through to final check
    }
  } else {
    try {
      execFileSync('rm', ['-rf', targetPath], { stdio: 'ignore' });
    } catch (_) {
      // fall through to final check
    }
  }
  try {
    fs.rmSync(targetPath, { recursive: true, force: true });
  } catch (_) {
    // final existence check decides whether cleanup really failed
  }
  return !fs.existsSync(targetPath);
}

function quarantineRemove(targetPath) {
  if (!fs.existsSync(targetPath)) {
    return;
  }
  if (bestEffortRemove(targetPath)) {
    return;
  }
  fs.mkdirSync(quarantineRoot, { recursive: true });
  const quarantined = path.join(
    quarantineRoot,
    `${path.basename(targetPath)}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
  );
  fs.renameSync(targetPath, quarantined);
  if (!bestEffortRemove(quarantined) && fs.existsSync(quarantined)) {
    throw new Error(`failed to clean packaging path: ${targetPath}`);
  }
}

quarantineRemove(distRoot);
quarantineRemove(runtimeBuildRoot);
