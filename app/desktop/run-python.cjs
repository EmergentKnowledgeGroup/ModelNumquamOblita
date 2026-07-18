const { spawnSync } = require('node:child_process');
const path = require('node:path');

const MIN_MAJOR = 3;
const MIN_MINOR = 12;
const PYTHON_PROBE = [
  '-c',
  "import sys, venv, xml.parsers.expat; print(f'{sys.version_info[0]}.{sys.version_info[1]}')",
];

function commandArgv(value) {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  const text = String(value || '').trim();
  if (!text) return [];
  const matches = text.match(/(?:[^\s"]+|"[^"]*")+/g) || [];
  return matches.map((part) => part.replace(/^(["'])(.*)\1$/, '$2'));
}

function preferredCommands(env = process.env, platform = process.platform) {
  const envOverride = String(env.MNO_PYTHON || '').trim();
  const candidates = [];
  if (envOverride) {
    candidates.push(commandArgv(envOverride));
  }
  if (platform === 'win32') {
    candidates.push(['py', '-3.15'], ['py', '-3.14'], ['py', '-3.13'], ['py', '-3.12']);
  }
  candidates.push(['python3.15'], ['python3.14'], ['python3.13'], ['python3.12'], ['/usr/bin/python3'], ['python3'], ['python']);
  return candidates;
}

function parseVersion(raw) {
  const trimmed = String(raw || '').trim();
  const match = /^(\d+)\.(\d+)$/.exec(trimmed);
  if (!match) {
    return null;
  }
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
  };
}

function canRun(command, spawn = spawnSync) {
  const argv = commandArgv(command);
  if (!argv.length) return null;
  const probe = spawn(argv[0], [...argv.slice(1), ...PYTHON_PROBE], {
    encoding: 'utf8',
    shell: false,
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 10000,
  });
  if (probe.status !== 0) {
    return null;
  }
  const version = parseVersion(probe.stdout);
  if (!version) {
    return null;
  }
  if (version.major < MIN_MAJOR || (version.major === MIN_MAJOR && version.minor < MIN_MINOR)) {
    return null;
  }
  return version;
}

function selectPythonCommand(candidates, spawn = spawnSync) {
  let bestCommand = [];
  let bestScore = -1;
  for (const candidate of candidates) {
    if (!candidate) {
      continue;
    }
    const version = canRun(candidate, spawn);
    if (!version) {
      continue;
    }
    const score = version.major * 100 + version.minor;
    if (score > bestScore) {
      bestScore = score;
      bestCommand = commandArgv(candidate);
    }
  }
  return bestCommand;
}

function main() {
  const scriptArgs = process.argv.slice(2);
  if (!scriptArgs.length) {
    console.error('usage: node run-python.cjs <script> [args...]');
    process.exit(2);
  }
  const scriptPath = path.resolve(__dirname, scriptArgs[0]);
  const command = selectPythonCommand(preferredCommands());
  if (!command.length) {
    console.error('No compatible Python interpreter found. Install python3.12+ or set MNO_PYTHON.');
    process.exit(2);
  }
  const result = spawnSync(command[0], [...command.slice(1), scriptPath, ...scriptArgs.slice(1)], {
    stdio: 'inherit',
    shell: false,
  });
  if (typeof result.status === 'number') {
    process.exit(result.status);
  }
  process.exit(1);
}

module.exports = {
  canRun,
  commandArgv,
  parseVersion,
  preferredCommands,
  selectPythonCommand,
};

if (require.main === module) {
  main();
}
