const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { ensureHomeLayout, resolveHomeLayout } = require('../dist/home-layout');

function runTest(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

runTest('resolveHomeLayout returns persistent desktop directories including tools', () => {
  const homeDir = path.join('D:\\Users\\Alice', 'RpaClaw');
  const layout = resolveHomeLayout(homeDir);

  assert.equal(layout.homeDir, homeDir);
  assert.equal(layout.workspaceDir, path.join(homeDir, 'workspace'));
  assert.equal(layout.toolsDir, path.join(homeDir, 'tools'));
  assert.equal(layout.externalSkillsDir, path.join(homeDir, 'external_skills'));
  assert.equal(layout.dataDir, path.join(homeDir, 'data'));
  assert.equal(layout.logsDir, path.join(homeDir, 'logs'));
  assert.equal(layout.sessionsDir, path.join(homeDir, 'data', 'sessions'));
  assert.equal(layout.usersDir, path.join(homeDir, 'data', 'users'));
  assert.equal(layout.tasksDir, path.join(homeDir, 'data', 'tasks'));
  assert.equal(layout.configFilePath, path.join(homeDir, 'config.json'));
});

runTest('ensureHomeLayout creates the expected directories and default config', () => {
  const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rpaclaw-home-layout-'));

  ensureHomeLayout(homeDir);

  const expectedDirs = [
    homeDir,
    path.join(homeDir, 'workspace'),
    path.join(homeDir, 'tools'),
    path.join(homeDir, 'external_skills'),
    path.join(homeDir, 'data'),
    path.join(homeDir, 'data', 'sessions'),
    path.join(homeDir, 'data', 'users'),
    path.join(homeDir, 'data', 'tasks'),
    path.join(homeDir, 'logs'),
  ];

  for (const dir of expectedDirs) {
    assert.equal(fs.existsSync(dir), true, `${dir} should exist`);
  }

  const configPath = path.join(homeDir, 'config.json');
  assert.equal(fs.existsSync(configPath), true, 'config.json should exist');
  assert.deepEqual(JSON.parse(fs.readFileSync(configPath, 'utf-8')), {
    backend_port: 12001,
    task_service_port: 12002,
    log_level: 'INFO',
  });

  fs.rmSync(homeDir, { recursive: true, force: true });
});

console.log('All home layout tests passed');
