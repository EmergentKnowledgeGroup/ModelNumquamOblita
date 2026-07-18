const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const { assetCommandForPlatform } = require('./build-assets.cjs');

test('non-mac desktop packaging has no bash dependency', () => {
  assert.equal(assetCommandForPlatform('win32'), null);
  assert.equal(assetCommandForPlatform('linux'), null);
});

test('mac desktop packaging runs the mac-only icon builder', () => {
  const root = path.join('Z:', 'mno', 'app', 'desktop');
  const plan = assetCommandForPlatform('darwin', root);
  assert.equal(plan.command, '/bin/bash');
  assert.equal(plan.args[0], path.join(root, 'build', 'generate_macos_icon.sh'));
});
