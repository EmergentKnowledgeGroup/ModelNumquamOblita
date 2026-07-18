const test = require('node:test');
const assert = require('node:assert/strict');

const { canRun, commandArgv, parseVersion, preferredCommands, selectPythonCommand } = require('./run-python.cjs');

test('parseVersion accepts major.minor output', () => {
  assert.deepEqual(parseVersion('3.14\n'), { major: 3, minor: 14 });
  assert.equal(parseVersion('Python 3.14.3'), null);
});

test('preferredCommands includes env override first', () => {
  assert.deepEqual(
    preferredCommands({ MNO_PYTHON: '/custom/python3.12' }, 'linux').slice(0, 3),
    [['/custom/python3.12'], ['python3.15'], ['python3.14']],
  );
});

test('selectPythonCommand skips broken higher-version shims', () => {
  const fakeSpawn = (command) => {
    if (command === 'python3.13') {
      return { status: 1, stdout: '', stderr: 'ImportError: broken pyexpat' };
    }
    if (command === 'python3') {
      return { status: 0, stdout: '3.14\n', stderr: '' };
    }
    if (command === 'python3.12') {
      return { status: 0, stdout: '3.12\n', stderr: '' };
    }
    return { status: 1, stdout: '', stderr: 'not found' };
  };
  assert.deepEqual(selectPythonCommand(['python3.13', 'python3.12', 'python3'], fakeSpawn), ['python3']);
});

test('canRun rejects versions below the floor', () => {
  const fakeSpawn = () => ({ status: 0, stdout: '3.11\n', stderr: '' });
  assert.equal(canRun('python3', fakeSpawn), null);
});

test('commandArgv preserves py launcher version arguments', () => {
  assert.deepEqual(commandArgv('py -3.12'), ['py', '-3.12']);
});

test('commandArgv preserves single- and double-quoted executable paths', () => {
  assert.deepEqual(commandArgv("'/opt/My Python/python3' -X utf8"), ['/opt/My Python/python3', '-X', 'utf8']);
  assert.deepEqual(commandArgv('"C:\\Program Files\\Python\\python.exe" -X utf8'), [
    'C:\\Program Files\\Python\\python.exe', '-X', 'utf8',
  ]);
});

test('probe does not require ensurepip and preserves launcher arguments', () => {
  let observed;
  const fakeSpawn = (command, args) => {
    observed = [command, ...args];
    return { status: 0, stdout: '3.12\n', stderr: '' };
  };
  assert.deepEqual(selectPythonCommand([['py', '-3.12']], fakeSpawn), ['py', '-3.12']);
  assert.deepEqual(observed.slice(0, 2), ['py', '-3.12']);
  assert.equal(observed.at(-1).includes('ensurepip'), false);
});
