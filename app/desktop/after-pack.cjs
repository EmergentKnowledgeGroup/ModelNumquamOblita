const { execFileSync } = require('node:child_process');

exports.default = async function afterPack(context) {
  if (!context || context.electronPlatformName !== 'darwin' || process.platform !== 'darwin') {
    return;
  }
  const appOutDir = String(context.appOutDir || '').trim();
  if (!appOutDir) {
    return;
  }
  try {
    execFileSync('xattr', ['-cr', appOutDir], { stdio: 'ignore' });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || 'unknown error');
    throw new Error(`failed to clear macOS extended attributes before signing: ${message}`);
  }
};
