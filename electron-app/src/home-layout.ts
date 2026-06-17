import * as fs from 'fs';
import * as path from 'path';

export interface HomeLayoutPaths {
  homeDir: string;
  workspaceDir: string;
  toolsDir: string;
  externalSkillsDir: string;
  dataDir: string;
  sessionsDir: string;
  usersDir: string;
  tasksDir: string;
  logsDir: string;
  configFilePath: string;
}

interface HomeLayoutConfig {
  backend_port: number;
  task_service_port: number;
  log_level: string;
}

const DEFAULT_HOME_CONFIG: HomeLayoutConfig = {
  backend_port: 12001,
  task_service_port: 12002,
  log_level: 'INFO',
};

export function resolveHomeLayout(homeDir: string): HomeLayoutPaths {
  const dataDir = path.join(homeDir, 'data');

  return {
    homeDir,
    workspaceDir: path.join(homeDir, 'workspace'),
    toolsDir: path.join(homeDir, 'tools'),
    externalSkillsDir: path.join(homeDir, 'external_skills'),
    dataDir,
    sessionsDir: path.join(dataDir, 'sessions'),
    usersDir: path.join(dataDir, 'users'),
    tasksDir: path.join(dataDir, 'tasks'),
    logsDir: path.join(homeDir, 'logs'),
    configFilePath: path.join(homeDir, 'config.json'),
  };
}

export function ensureHomeLayout(homeDir: string): HomeLayoutPaths {
  const layout = resolveHomeLayout(homeDir);
  const dirs = [
    layout.homeDir,
    layout.workspaceDir,
    layout.toolsDir,
    layout.externalSkillsDir,
    layout.dataDir,
    layout.sessionsDir,
    layout.usersDir,
    layout.tasksDir,
    layout.logsDir,
  ];

  for (const dir of dirs) {
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
  }

  if (!fs.existsSync(layout.configFilePath)) {
    fs.writeFileSync(layout.configFilePath, JSON.stringify(DEFAULT_HOME_CONFIG, null, 2), 'utf-8');
  }

  return layout;
}
