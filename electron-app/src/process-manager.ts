import { spawn, ChildProcess } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import { app } from 'electron';
import { BackendEnv, ProcessStatus } from './types';
import treeKill from 'tree-kill';

export class ProcessManager {
  private backendProcess: ChildProcess | null = null;
  private taskServiceProcess: ChildProcess | null = null;
  private installDir: string;
  private homeDir: string;

  constructor(homeDir: string) {
    this.homeDir = homeDir;
    // In packaged app, resources are in app.getAppPath()/resources
    // In dev mode, they're relative to project root
    this.installDir = app.isPackaged
      ? path.join(process.resourcesPath)
      : path.join(__dirname, '..', '..');
  }

  /**
   * Build environment variables for backend processes
   */
  private buildEnv(): BackendEnv {
    const pythonDir = path.join(this.installDir, 'python');
    const pythonExe = path.join(pythonDir, 'python.exe');
    const sitePackages = path.join(pythonDir, 'Lib', 'site-packages');
    const playwrightBrowsers = path.join(
      sitePackages,
      'playwright',
      'driver',
      'package',
      '.local-browsers'
    );
    const frontendDist = path.join(this.installDir, 'frontend-dist');

    return {
      STORAGE_BACKEND: 'local',
      RPA_CLAW_HOME: this.homeDir,
      WORKSPACE_DIR: path.join(this.homeDir, 'workspace'),
      EXTERNAL_SKILLS_DIR: path.join(this.homeDir, 'external_skills'),
      LOCAL_DATA_DIR: path.join(this.homeDir, 'data'),
      BUILTIN_SKILLS_DIR: path.join(this.installDir, 'builtin_skills'),
      BACKEND_PORT: '12001',
      TASK_SERVICE_PORT: '12002',
      PYTHONHOME: pythonDir,
      PYTHONPATH: sitePackages,
      PLAYWRIGHT_BROWSERS_PATH: playwrightBrowsers,
      ENVIRONMENT: 'production',
      LOG_LEVEL: 'INFO',
      FRONTEND_DIST_DIR: frontendDist,
    };
  }

  /**
   * Start backend process
   */
  async startBackend(): Promise<void> {
    if (this.backendProcess) {
      console.log('Backend already running');
      return;
    }

    const env = this.buildEnv();
    const logFile = path.join(this.homeDir, 'logs', 'backend.log');

    // Ensure log directory exists
    const logDir = path.dirname(logFile);
    if (!fs.existsSync(logDir)) {
      fs.mkdirSync(logDir, { recursive: true });
    }

    const logStream = fs.createWriteStream(logFile, { flags: 'a' });

    // In development mode, check if Python exists, if not, skip backend start
    const pythonExe = path.join(env.PYTHONHOME, 'python.exe');
    const backendDir = path.join(this.installDir, 'backend');

    if (!app.isPackaged && !fs.existsSync(pythonExe)) {
      console.log('Development mode: Python not found at', pythonExe);
      console.log('Please start backend manually:');
      console.log('  cd RpaClaw/backend');
      console.log('  uv run uvicorn backend.main:app --host 127.0.0.1 --port 12001');
      return;
    }

    console.log('Starting backend:', pythonExe, backendDir);
    console.log('Working directory:', path.dirname(backendDir));
    console.log('Environment:', JSON.stringify(env, null, 2));

    this.backendProcess = spawn(
      pythonExe,
      [
        '-m',
        'uvicorn',
        'backend.main:app',
        '--host',
        '127.0.0.1',
        '--port',
        env.BACKEND_PORT,
      ],
      {
        cwd: path.dirname(backendDir),
        env: { ...process.env, ...env },
        stdio: ['ignore', 'pipe', 'pipe'],
      }
    );

    this.backendProcess.stdout?.pipe(logStream);
    this.backendProcess.stderr?.pipe(logStream);

    // Also log to console for debugging
    this.backendProcess.stdout?.on('data', (data) => {
      console.log('Backend stdout:', data.toString());
    });
    this.backendProcess.stderr?.on('data', (data) => {
      console.error('Backend stderr:', data.toString());
    });

    this.backendProcess.on('error', (error) => {
      console.error('Backend process error:', error);
    });

    this.backendProcess.on('exit', (code) => {
      console.log(`Backend process exited with code ${code}`);
      this.backendProcess = null;
    });

    // Wait for backend to be ready
    await this.waitForPort(parseInt(env.BACKEND_PORT), 30000);
  }

  /**
   * Start task-service process
   */
  async startTaskService(): Promise<void> {
    if (this.taskServiceProcess) {
      console.log('Task-service already running');
      return;
    }

    const env = this.buildEnv();
    const logFile = path.join(this.homeDir, 'logs', 'task-service.log');

    const logStream = fs.createWriteStream(logFile, { flags: 'a' });

    // In development mode, check if Python exists, if not, skip task-service start
    const pythonExe = path.join(env.PYTHONHOME, 'python.exe');
    const taskServiceDir = path.join(this.installDir, 'task-service');

    if (!app.isPackaged && !fs.existsSync(pythonExe)) {
      console.log('Development mode: Python not found at', pythonExe);
      console.log('Please start task-service manually:');
      console.log('  cd RpaClaw/task-service');
      console.log('  uv run uvicorn app.main:app --host 127.0.0.1 --port 12002');
      return;
    }

    console.log('Starting task-service:', pythonExe, taskServiceDir);

    this.taskServiceProcess = spawn(
      pythonExe,
      [
        '-m',
        'uvicorn',
        'app.main:app',
        '--host',
        '127.0.0.1',
        '--port',
        env.TASK_SERVICE_PORT,
      ],
      {
        cwd: taskServiceDir,
        env: { ...process.env, ...env },
        stdio: ['ignore', 'pipe', 'pipe'],
      }
    );

    this.taskServiceProcess.stdout?.pipe(logStream);
    this.taskServiceProcess.stderr?.pipe(logStream);

    this.taskServiceProcess.on('error', (error) => {
      console.error('Task-service process error:', error);
    });

    this.taskServiceProcess.on('exit', (code) => {
      console.log(`Task-service process exited with code ${code}`);
      this.taskServiceProcess = null;
    });

    // Wait for task-service to be ready
    await this.waitForPort(parseInt(env.TASK_SERVICE_PORT), 30000);
  }

  /**
   * Stop all processes
   */
  async stopAll(): Promise<void> {
    const promises: Promise<void>[] = [];

    if (this.backendProcess) {
      promises.push(this.killProcess(this.backendProcess));
      this.backendProcess = null;
    }

    if (this.taskServiceProcess) {
      promises.push(this.killProcess(this.taskServiceProcess));
      this.taskServiceProcess = null;
    }

    await Promise.all(promises);
  }

  /**
   * Kill a process and its children
   */
  private killProcess(proc: ChildProcess): Promise<void> {
    return new Promise((resolve) => {
      if (!proc.pid) {
        resolve();
        return;
      }

      treeKill(proc.pid, 'SIGTERM', (err: Error | undefined) => {
        if (err) {
          console.error('Failed to kill process:', err);
        }
        resolve();
      });
    });
  }

  /**
   * Wait for a port to be available
   */
  private async waitForPort(port: number, timeout: number): Promise<void> {
    const startTime = Date.now();
    const http = require('http');

    // Use different health check endpoints for different ports
    const healthPath = port === 12001 ? '/api/v1/auth/status' : '/health';

    while (Date.now() - startTime < timeout) {
      try {
        await new Promise<void>((resolve, reject) => {
          const req = http.get(`http://127.0.0.1:${port}${healthPath}`, (res: any) => {
            if (res.statusCode === 200 || res.statusCode === 401) {
              // 401 is OK for auth/status (means endpoint exists)
              resolve();
            } else {
              reject(new Error(`Status ${res.statusCode}`));
            }
          });
          req.on('error', reject);
          req.setTimeout(1000);
        });
        console.log(`Port ${port} is ready`);
        return;
      } catch (error) {
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    }

    throw new Error(`Timeout waiting for port ${port}`);
  }

  /**
   * Get backend status
   */
  getBackendStatus(): ProcessStatus {
    return {
      running: this.backendProcess !== null,
      port: 12001,
      pid: this.backendProcess?.pid,
    };
  }

  /**
   * Get task-service status
   */
  getTaskServiceStatus(): ProcessStatus {
    return {
      running: this.taskServiceProcess !== null,
      port: 12002,
      pid: this.taskServiceProcess?.pid,
    };
  }
}
