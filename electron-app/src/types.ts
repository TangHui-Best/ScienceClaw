export interface AppConfig {
  homeDir: string;
  version: string;
}

export interface ProcessStatus {
  running: boolean;
  port: number;
  pid?: number;
}

export interface BackendEnv {
  STORAGE_BACKEND: string;
  RPA_CLAW_HOME: string;
  WORKSPACE_DIR: string;
  TOOLS_DIR: string;
  EXTERNAL_SKILLS_DIR: string;
  LOCAL_DATA_DIR: string;
  BUILTIN_SKILLS_DIR: string;
  BACKEND_PORT: string;
  TASK_SERVICE_PORT: string;
  PYTHONHOME: string;
  PYTHONPATH: string;
  PLAYWRIGHT_BROWSERS_PATH: string;
  ENVIRONMENT: string;
  LOG_LEVEL: string;
  FRONTEND_DIST_DIR: string;
}
