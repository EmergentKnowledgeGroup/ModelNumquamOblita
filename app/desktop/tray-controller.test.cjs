const test = require('node:test');
const assert = require('node:assert/strict');
const { buildTrayMenuTemplate } = require('./tray-controller.cjs');

function menuState(template, id) {
  return template.find((item) => item.id === id);
}

test('tray template enables runtime start only for stopped ready configurations', () => {
  const template = buildTrayMenuTemplate({ status: 'stopped', label: 'Stopped', canStartRuntime: true });
  assert.equal(menuState(template, 'start-runtime').enabled, true);
  assert.equal(menuState(template, 'stop-runtime').enabled, false);
});

test('tray template keeps setup entry available when setup is required', () => {
  const template = buildTrayMenuTemplate({ status: 'setup_required', label: 'Setup required', canStartSetup: true });
  assert.equal(menuState(template, 'open-setup').enabled, true);
  assert.equal(menuState(template, 'start-runtime').enabled, false);
});

test('tray template exposes repair when degraded runtime ownership needs cleanup', () => {
  const template = buildTrayMenuTemplate({ status: 'degraded', label: 'Needs attention', canRepairRuntime: true });
  assert.equal(menuState(template, 'repair-runtime').enabled, true);
  assert.equal(menuState(template, 'stop-runtime').enabled, false);
});
