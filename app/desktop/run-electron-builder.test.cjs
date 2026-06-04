const test = require('node:test');
const assert = require('node:assert/strict');

const { buildElectronBuilderInvocation } = require('./run-electron-builder.cjs');

test('unsigned mac local build disables signing discovery and sets mac identity to null', () => {
  const invocation = buildElectronBuilderInvocation(['--dir', '--publish', 'never', '--unsigned-mac-local'], {
    platform: 'darwin',
    env: {},
  });
  assert.deepEqual(invocation.args, ['--dir', '--publish', 'never', '-c.mac.identity=null']);
  assert.equal(invocation.env.CSC_IDENTITY_AUTO_DISCOVERY, 'false');
});

test('non-mac builds leave args unchanged', () => {
  const invocation = buildElectronBuilderInvocation(['--linux', 'AppImage', '--publish', 'never'], {
    platform: 'linux',
    env: {},
  });
  assert.deepEqual(invocation.args, ['--linux', 'AppImage', '--publish', 'never']);
  assert.equal(invocation.env.CSC_IDENTITY_AUTO_DISCOVERY, undefined);
});
