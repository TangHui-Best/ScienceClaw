# Windows Desktop Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package RpaClaw as a standalone Windows desktop application with embedded Python runtime, Electron UI, and standard installer.

**Architecture:** Electron main process manages Backend/Task-service Python processes, serves Vue frontend via Backend static files, handles first-run wizard and configuration. Python embeddable package with all dependencies bundled. Electron Builder generates NSIS installer.

**Tech Stack:** Electron 28+, TypeScript, Node.js 20+, Python 3.13 embeddable, Electron Builder, NSIS

---

## Scope Check

This plan covers the complete Windows desktop packaging implementation. It's a single cohesive system with these components:
1. Electron application structure
2. Backend configuration for packaged environment
3. Build scripts and tooling
4. First-run wizard

All components work together to produce a working installer. No decomposition needed.

---

## File Structure

### New Files (electron-app/)

**Core Electron Application:**
- `electron-app/package.json` - Electron Builder config, dependencies, build scripts
- `electron-app/tsconfig.json` - TypeScript compiler config
- `electron-app/src/main.ts` - Main process: process management, window creation, IPC
- `electron-app/src/preload.ts` - Preload script for secure IPC bridge
- `electron-app/src/types.ts` - TypeScript type definitions
- `electron-app/src/config.ts` - Configuration management (read/write app-config.json)
- `electron-app/src/process-manager.ts` - Backend/Task-service process lifecycle
- `electron-app/src/wizard/wizard.html` - First-run wizard UI
- `electron-app/src/wizard/wizard.ts` - Wizard logic (directory selection, initialization)
- `electron-app/src/wizard/wizard.css` - Wizard styling
- `electron-app/resources/icon.ico` - Application icon (placeholder)
- `electron-app/.gitignore` - Ignore dist/, release/, node_modules/

**Build Scripts:**
- `build-windows.ps1` - PowerShell build script for Windows
- `.github/workflows/build-windows.yml` - GitHub Actions workflow (optional)

### Modified Files

**Backend:**
- `RpaClaw/backend/config.py` - Add packaged environment path resolution
- `RpaClaw/backend/main.py` - Add static file serving for frontend dist

**Frontend:**
- `RpaClaw/frontend/vite.config.ts` - Ensure build output works with Electron

**Root:**
- `.gitignore` - Add build/, electron-app/dist/, electron-app/release/

---

## Task 1: Electron Project Setup

**Files:**
- Create: `electron-app/package.json`
- Create: `electron-app/tsconfig.json`
- Create: `electron-app/.gitignore`
- Create: `electron-app/src/types.ts`

- [ ] **Step 1: Create electron-app directory structure**

```bash
mkdir -p electron-app/src/wizard
mkdir -p electron-app/resources
```

- [ ] **Step 2: Create package.json**

Create `electron-app/package.json`:

```json
{
  "name": "rpaclaw-desktop",
  "version": "1.0.0",
  "description": "RpaClaw Desktop Application",
  "main": "dist/main.js",
  "scripts": {
    "dev": "tsc && electron .",
    "build": "tsc",
    "pack": "electron-builder --dir",
    "dist": "electron-builder"
  },
  "author": "RpaClaw Team",
  "license": "MIT",
  "devDependencies": {
    "@types/node": "^20.11.0",
    "electron": "^28.2.0",
    "electron-builder": "^24.9.1",
    "typescript": "^5.3.3"
  },
  "dependencies": {
    "tree-kill": "^1.2.2"
  },
  "build": {
    "appId": "com.rpaclaw.app",
    "productName": "RpaClaw",
    "directories": {
      "output": "release"
    },
    "files": [
      "dist/**/*",
      "resources/**/*"
    ],
    "extraResources": [
      {
        "from": "../build/python",
        "to": "python",
        "filter": ["**/*"]
      },
      {
        "from": "../RpaClaw/backend",
        "to": "backend",
        "filter": ["**/*", "!**/__pycache__", "!**/*.pyc"]
      },
      {
        "from": "../RpaClaw/task-service",
        "to": "task-service",
        "filter": ["**/*", "!**/__pycache__", "!**/*.pyc"]
      },
      {
        "from": "../RpaClaw/backend/builtin_skills",
        "to": "builtin_skills",
        "filter": ["**/*"]
      },
      {
        "from": "../RpaClaw/frontend/dist",
        "to": "frontend-dist",
        "filter": ["**/*"]
      }
    ],
    "win": {
      "target": "nsis",
      "icon": "resources/icon.ico"
    },
    "nsis": {
      "oneClick": false,
      "allowToChangeInstallationDirectory": true,
      "createDesktopShortcut": true,
      "createStartMenuShortcut": true,
      "installerIcon": "resources/icon.ico",
      "uninstallerIcon": "resources/icon.ico"
    }
  }
}
```

- [ ] **Step 3: Create tsconfig.json**

Create `electron-app/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "commonjs",
    "lib": ["ES2020"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "moduleResolution": "node"
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist"]
}
```

- [ ] **Step 4: Create .gitignore**

Create `electron-app/.gitignore`:

```
node_modules/
dist/
release/
*.log
.DS_Store
```

- [ ] **Step 5: Create types.ts**

Create `electron-app/src/types.ts`:

```typescript
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
}
```

- [ ] **Step 6: Install dependencies**

```bash
cd electron-app
npm install
```

Expected: Dependencies installed successfully

- [ ] **Step 7: Commit**

```bash
git add electron-app/
git commit -m "feat: initialize Electron project structure"
```

---

## Task 2: Configuration Management Module

**Files:**
- Create: `electron-app/src/config.ts`

- [ ] **Step 1: Create config.ts**

Create `electron-app/src/config.ts`:

```typescript
import { app } from 'electron';
import * as fs from 'fs';
import * as path from 'path';
import { AppConfig } from './types';

const APP_NAME = 'RpaClaw';
const CONFIG_FILE = 'app-config.json';

export class ConfigManager {
  private configPath: string;
  private config: AppConfig | null = null;

  constructor() {
    const appDataDir = path.join(app.getPath('appData'), APP_NAME);
    if (!fs.existsSync(appDataDir)) {
      fs.mkdirSync(appDataDir, { recursive: true });
    }
    this.configPath = path.join(appDataDir, CONFIG_FILE);
  }

  /**
   * Check if this is the first run (config file doesn't exist)
   */
  isFirstRun(): boolean {
    return !fs.existsSync(this.configPath);
  }

  /**
   * Load configuration from disk
   */
  load(): AppConfig | null {
    if (!fs.existsSync(this.configPath)) {
      return null;
    }
    try {
      const data = fs.readFileSync(this.configPath, 'utf-8');
      this.config = JSON.parse(data);
      return this.config;
    } catch (error) {
      console.error('Failed to load config:', error);
      return null;
    }
  }

  /**
   * Save configuration to disk
   */
  save(config: AppConfig): void {
    try {
      fs.writeFileSync(this.configPath, JSON.stringify(config, null, 2), 'utf-8');
      this.config = config;
    } catch (error) {
      console.error('Failed to save config:', error);
      throw error;
    }
  }

  /**
   * Get current configuration
   */
  get(): AppConfig | null {
    return this.config;
  }

  /**
   * Get default home directory
   */
  getDefaultHomeDir(): string {
    return path.join(app.getPath('home'), APP_NAME);
  }

  /**
   * Initialize home directory structure
   */
  initializeHomeDir(homeDir: string): void {
    const dirs = [
      homeDir,
      path.join(homeDir, 'workspace'),
      path.join(homeDir, 'external_skills'),
      path.join(homeDir, 'data'),
      path.join(homeDir, 'data', 'sessions'),
      path.join(homeDir, 'data', 'users'),
      path.join(homeDir, 'data', 'tasks'),
      path.join(homeDir, 'logs'),
    ];

    for (const dir of dirs) {
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
    }

    // Create default config.json in home directory
    const configPath = path.join(homeDir, 'config.json');
    if (!fs.existsSync(configPath)) {
      const defaultConfig = {
        backend_port: 12001,
        task_service_port: 12002,
        log_level: 'INFO',
      };
      fs.writeFileSync(configPath, JSON.stringify(defaultConfig, null, 2), 'utf-8');
    }
  }

  /**
   * Validate home directory (writable and has space)
   */
  validateHomeDir(homeDir: string): { valid: boolean; error?: string } {
    try {
      // Check if parent directory exists
      const parentDir = path.dirname(homeDir);
      if (!fs.existsSync(parentDir)) {
        return { valid: false, error: 'Parent directory does not exist' };
      }

      // Check if writable
      const testFile = path.join(parentDir, '.rpaclaw-test');
      fs.writeFileSync(testFile, 'test');
      fs.unlinkSync(testFile);

      return { valid: true };
    } catch (error) {
      return { valid: false, error: `Not writable: ${error}` };
    }
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add electron-app/src/config.ts
git commit -m "feat: add configuration management module"
```

---

## Task 3: Process Manager Module

**Files:**
- Create: `electron-app/src/process-manager.ts`

- [ ] **Step 1: Create process-manager.ts**

Create `electron-app/src/process-manager.ts`:

```typescript
import { spawn, ChildProcess } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import { app } from 'electron';
import { BackendEnv, ProcessStatus } from './types';
import * as treeKill from 'tree-kill';

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
    const pythonExe = path.join(env.PYTHONHOME, 'python.exe');
    const backendDir = path.join(this.installDir, 'backend');
    const logFile = path.join(this.homeDir, 'logs', 'backend.log');

    // Ensure log directory exists
    const logDir = path.dirname(logFile);
    if (!fs.existsSync(logDir)) {
      fs.mkdirSync(logDir, { recursive: true });
    }

    const logStream = fs.createWriteStream(logFile, { flags: 'a' });

    console.log('Starting backend:', pythonExe, backendDir);

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
    const pythonExe = path.join(env.PYTHONHOME, 'python.exe');
    const taskServiceDir = path.join(this.installDir, 'task-service');
    const logFile = path.join(this.homeDir, 'logs', 'task-service.log');

    const logStream = fs.createWriteStream(logFile, { flags: 'a' });

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

      treeKill(proc.pid, 'SIGTERM', (err) => {
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

    while (Date.now() - startTime < timeout) {
      try {
        await new Promise<void>((resolve, reject) => {
          const req = http.get(`http://127.0.0.1:${port}/health`, (res: any) => {
            if (res.statusCode === 200) {
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
```

- [ ] **Step 2: Commit**

```bash
git add electron-app/src/process-manager.ts
git commit -m "feat: add process manager for backend services"
```

---

## Task 4: First-Run Wizard UI

**Files:**
- Create: `electron-app/src/wizard/wizard.html`
- Create: `electron-app/src/wizard/wizard.css`
- Create: `electron-app/src/wizard/wizard.ts`

- [ ] **Step 1: Create wizard.html**

Create `electron-app/src/wizard/wizard.html`:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>RpaClaw Setup</title>
  <link rel="stylesheet" href="wizard.css">
</head>
<body>
  <div id="app">
    <!-- Page 1: Welcome -->
    <div id="page-welcome" class="page active">
      <h1>Welcome to RpaClaw</h1>
      <p>Your privacy-first personal research assistant powered by AI.</p>
      <ul>
        <li>1,900+ built-in scientific tools</li>
        <li>Multi-format document generation</li>
        <li>RPA skill recording system</li>
        <li>All data stays local</li>
      </ul>
      <button id="btn-start" class="primary">Get Started</button>
    </div>

    <!-- Page 2: Home Directory Selection -->
    <div id="page-home-dir" class="page">
      <h1>Choose Home Directory</h1>
      <p>Select where RpaClaw will store your data and workspace.</p>
      <div class="form-group">
        <label>Home Directory:</label>
        <div class="input-group">
          <input type="text" id="input-home-dir" readonly>
          <button id="btn-browse">Browse...</button>
        </div>
        <small>Estimated space required: ~500MB</small>
      </div>
      <div id="validation-error" class="error hidden"></div>
      <div class="button-group">
        <button id="btn-back-1" class="secondary">Back</button>
        <button id="btn-next" class="primary">Next</button>
      </div>
    </div>

    <!-- Page 3: Initialization Progress -->
    <div id="page-progress" class="page">
      <h1>Setting Up RpaClaw</h1>
      <p id="progress-status">Initializing...</p>
      <div class="progress-bar">
        <div id="progress-fill" class="progress-fill"></div>
      </div>
      <div id="progress-log" class="log"></div>
    </div>

    <!-- Page 4: Completion -->
    <div id="page-complete" class="page">
      <h1>Setup Complete!</h1>
      <p>RpaClaw is ready to use.</p>
      <button id="btn-launch" class="primary">Launch RpaClaw</button>
    </div>
  </div>

  <script src="wizard.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create wizard.css**

Create `electron-app/src/wizard/wizard.css`:

```css
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  padding: 20px;
}

#app {
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  width: 100%;
  max-width: 600px;
  min-height: 400px;
  padding: 40px;
}

.page {
  display: none;
}

.page.active {
  display: block;
  animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

h1 {
  font-size: 28px;
  color: #333;
  margin-bottom: 16px;
}

p {
  font-size: 16px;
  color: #666;
  margin-bottom: 24px;
  line-height: 1.6;
}

ul {
  list-style: none;
  margin-bottom: 32px;
}

ul li {
  padding: 8px 0;
  padding-left: 24px;
  position: relative;
  color: #555;
}

ul li:before {
  content: '✓';
  position: absolute;
  left: 0;
  color: #667eea;
  font-weight: bold;
}

.form-group {
  margin-bottom: 24px;
}

label {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin-bottom: 8px;
}

.input-group {
  display: flex;
  gap: 8px;
}

input[type="text"] {
  flex: 1;
  padding: 10px 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
  background: #f9f9f9;
}

small {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: #999;
}

.error {
  padding: 12px;
  background: #fee;
  border: 1px solid #fcc;
  border-radius: 6px;
  color: #c33;
  font-size: 14px;
  margin-bottom: 16px;
}

.error.hidden {
  display: none;
}

.button-group {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

button {
  padding: 12px 24px;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

button.primary {
  background: #667eea;
  color: white;
}

button.primary:hover {
  background: #5568d3;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

button.primary:disabled {
  background: #ccc;
  cursor: not-allowed;
  transform: none;
}

button.secondary {
  background: #f0f0f0;
  color: #666;
}

button.secondary:hover {
  background: #e0e0e0;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: #f0f0f0;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 24px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
  width: 0%;
  transition: width 0.3s ease;
}

.log {
  max-height: 200px;
  overflow-y: auto;
  background: #f9f9f9;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 12px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  color: #666;
}

.log div {
  padding: 2px 0;
}
```

- [ ] **Step 3: Create wizard.ts**

Create `electron-app/src/wizard/wizard.ts`:

```typescript
import { ipcRenderer } from 'electron';

let currentPage = 0;
let selectedHomeDir = '';

const pages = [
  'page-welcome',
  'page-home-dir',
  'page-progress',
  'page-complete',
];

function showPage(index: number) {
  pages.forEach((pageId, i) => {
    const page = document.getElementById(pageId);
    if (page) {
      page.classList.toggle('active', i === index);
    }
  });
  currentPage = index;
}

function showError(message: string) {
  const errorDiv = document.getElementById('validation-error');
  if (errorDiv) {
    errorDiv.textContent = message;
    errorDiv.classList.remove('hidden');
  }
}

function hideError() {
  const errorDiv = document.getElementById('validation-error');
  if (errorDiv) {
    errorDiv.classList.add('hidden');
  }
}

function updateProgress(percent: number, status: string, log?: string) {
  const fill = document.getElementById('progress-fill');
  const statusEl = document.getElementById('progress-status');
  const logEl = document.getElementById('progress-log');

  if (fill) fill.style.width = `${percent}%`;
  if (statusEl) statusEl.textContent = status;
  if (log && logEl) {
    const logLine = document.createElement('div');
    logLine.textContent = log;
    logEl.appendChild(logLine);
    logEl.scrollTop = logEl.scrollHeight;
  }
}

async function initializeHomeDir() {
  showPage(2);
  updateProgress(0, 'Creating directory structure...', 'Starting initialization');

  try {
    await ipcRenderer.invoke('initialize-home-dir', selectedHomeDir);
    updateProgress(100, 'Complete!', 'Initialization complete');
    
    setTimeout(() => {
      showPage(3);
    }, 500);
  } catch (error) {
    updateProgress(0, 'Error', `Failed: ${error}`);
    setTimeout(() => {
      showPage(1);
      showError(`Initialization failed: ${error}`);
    }, 2000);
  }
}

// Page 1: Welcome
document.getElementById('btn-start')?.addEventListener('click', () => {
  showPage(1);
  
  // Load default home directory
  ipcRenderer.invoke('get-default-home-dir').then((dir: string) => {
    selectedHomeDir = dir;
    const input = document.getElementById('input-home-dir') as HTMLInputElement;
    if (input) input.value = dir;
  });
});

// Page 2: Home Directory Selection
document.getElementById('btn-browse')?.addEventListener('click', async () => {
  const result = await ipcRenderer.invoke('select-directory');
  if (result) {
    selectedHomeDir = result;
    const input = document.getElementById('input-home-dir') as HTMLInputElement;
    if (input) input.value = result;
    hideError();
  }
});

document.getElementById('btn-back-1')?.addEventListener('click', () => {
  showPage(0);
});

document.getElementById('btn-next')?.addEventListener('click', async () => {
  if (!selectedHomeDir) {
    showError('Please select a home directory');
    return;
  }

  // Validate directory
  const validation = await ipcRenderer.invoke('validate-home-dir', selectedHomeDir);
  if (!validation.valid) {
    showError(validation.error || 'Invalid directory');
    return;
  }

  hideError();
  await initializeHomeDir();
});

// Page 4: Complete
document.getElementById('btn-launch')?.addEventListener('click', () => {
  ipcRenderer.send('wizard-complete');
});

// Initialize
showPage(0);
```

- [ ] **Step 4: Compile wizard TypeScript**

Update `electron-app/tsconfig.json` to include wizard:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "commonjs",
    "lib": ["ES2020", "DOM"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "moduleResolution": "node"
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist"]
}
```

- [ ] **Step 5: Build wizard**

```bash
cd electron-app
npm run build
```

Expected: TypeScript compiled successfully, wizard.js created in dist/wizard/

- [ ] **Step 6: Commit**

```bash
git add electron-app/src/wizard/
git add electron-app/tsconfig.json
git commit -m "feat: add first-run wizard UI"
```

---

## Task 5: Preload Script

**Files:**
- Create: `electron-app/src/preload.ts`

- [ ] **Step 1: Create preload.ts**

Create `electron-app/src/preload.ts`:

```typescript
import { contextBridge, ipcRenderer } from 'electron';

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // Config
  getHomeDir: () => ipcRenderer.invoke('get-home-dir'),
  setHomeDir: (path: string) => ipcRenderer.invoke('set-home-dir', path),
  
  // Process status
  getBackendStatus: () => ipcRenderer.invoke('get-backend-status'),
  getTaskServiceStatus: () => ipcRenderer.invoke('get-task-service-status'),
  
  // App control
  restartApp: () => ipcRenderer.send('restart-app'),
  openExternal: (url: string) => ipcRenderer.send('open-external', url),
  
  // Wizard
  getDefaultHomeDir: () => ipcRenderer.invoke('get-default-home-dir'),
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  validateHomeDir: (path: string) => ipcRenderer.invoke('validate-home-dir', path),
  initializeHomeDir: (path: string) => ipcRenderer.invoke('initialize-home-dir', path),
  onWizardComplete: (callback: () => void) => {
    ipcRenderer.on('wizard-complete', callback);
  },
});

// Type definitions for window.electronAPI
declare global {
  interface Window {
    electronAPI: {
      getHomeDir: () => Promise<string>;
      setHomeDir: (path: string) => Promise<void>;
      getBackendStatus: () => Promise<{ running: boolean; port: number }>;
      getTaskServiceStatus: () => Promise<{ running: boolean; port: number }>;
      restartApp: () => void;
      openExternal: (url: string) => void;
      getDefaultHomeDir: () => Promise<string>;
      selectDirectory: () => Promise<string | null>;
      validateHomeDir: (path: string) => Promise<{ valid: boolean; error?: string }>;
      initializeHomeDir: (path: string) => Promise<void>;
      onWizardComplete: (callback: () => void) => void;
    };
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add electron-app/src/preload.ts
git commit -m "feat: add preload script for secure IPC"
```

---

## Task 6: Electron Main Process

**Files:**
- Create: `electron-app/src/main.ts`

- [ ] **Step 1: Create main.ts (part 1: imports and initialization)**

Create `electron-app/src/main.ts`:

```typescript
import { app, BrowserWindow, ipcMain, dialog, Tray, Menu, shell } from 'electron';
import * as path from 'path';
import { ConfigManager } from './config';
import { ProcessManager } from './process-manager';

let mainWindow: BrowserWindow | null = null;
let wizardWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let configManager: ConfigManager;
let processManager: ProcessManager | null = null;

const BACKEND_URL = 'http://127.0.0.1:12001';

/**
 * Create the wizard window
 */
function createWizardWindow() {
  wizardWindow = new BrowserWindow({
    width: 600,
    height: 500,
    resizable: false,
    frame: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  wizardWindow.loadFile(path.join(__dirname, 'wizard', 'wizard.html'));

  wizardWindow.on('closed', () => {
    wizardWindow = null;
  });
}

/**
 * Create the main application window
 */
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Load backend URL
  mainWindow.loadURL(BACKEND_URL);

  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      mainWindow?.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

/**
 * Create system tray icon
 */
function createTray() {
  // Use a default icon (you'll need to provide icon.ico)
  const iconPath = path.join(__dirname, '..', 'resources', 'icon.ico');
  tray = new Tray(iconPath);

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show RpaClaw',
      click: () => {
        mainWindow?.show();
      },
    },
    {
      label: 'Quit',
      click: () => {
        app.isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setToolTip('RpaClaw');
  tray.setContextMenu(contextMenu);

  tray.on('click', () => {
    mainWindow?.show();
  });
}

/**
 * Initialize application
 */
async function initialize() {
  configManager = new ConfigManager();

  if (configManager.isFirstRun()) {
    // Show wizard
    createWizardWindow();
  } else {
    // Load config and start services
    const config = configManager.load();
    if (!config) {
      console.error('Failed to load config');
      app.quit();
      return;
    }

    // Start backend services
    processManager = new ProcessManager(config.homeDir);
    try {
      await processManager.startBackend();
      await processManager.startTaskService();
    } catch (error) {
      console.error('Failed to start services:', error);
      dialog.showErrorBox('Startup Error', `Failed to start services: ${error}`);
      app.quit();
      return;
    }

    // Create main window and tray
    createMainWindow();
    createTray();
  }
}

// App lifecycle
app.on('ready', initialize);

app.on('window-all-closed', () => {
  // On macOS, keep app running when all windows closed
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === null) {
    createMainWindow();
  } else {
    mainWindow.show();
  }
});

app.on('before-quit', async () => {
  app.isQuitting = true;
  if (processManager) {
    await processManager.stopAll();
  }
});
```

- [ ] **Step 2: Add IPC handlers to main.ts**

Add to `electron-app/src/main.ts`:

```typescript
// IPC Handlers

// Config
ipcMain.handle('get-home-dir', () => {
  const config = configManager.get();
  return config?.homeDir || '';
});

ipcMain.handle('set-home-dir', async (event, newPath: string) => {
  const config = configManager.get();
  if (config) {
    config.homeDir = newPath;
    configManager.save(config);
    
    // Restart required
    dialog.showMessageBox({
      type: 'info',
      title: 'Restart Required',
      message: 'Please restart RpaClaw for changes to take effect.',
      buttons: ['OK'],
    });
  }
});

// Process status
ipcMain.handle('get-backend-status', () => {
  return processManager?.getBackendStatus() || { running: false, port: 12001 };
});

ipcMain.handle('get-task-service-status', () => {
  return processManager?.getTaskServiceStatus() || { running: false, port: 12002 };
});

// App control
ipcMain.on('restart-app', () => {
  app.relaunch();
  app.quit();
});

ipcMain.on('open-external', (event, url: string) => {
  shell.openExternal(url);
});

// Wizard
ipcMain.handle('get-default-home-dir', () => {
  return configManager.getDefaultHomeDir();
});

ipcMain.handle('select-directory', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openDirectory', 'createDirectory'],
    title: 'Select Home Directory',
  });

  if (result.canceled) {
    return null;
  }

  return result.filePaths[0];
});

ipcMain.handle('validate-home-dir', (event, dirPath: string) => {
  return configManager.validateHomeDir(dirPath);
});

ipcMain.handle('initialize-home-dir', async (event, dirPath: string) => {
  try {
    configManager.initializeHomeDir(dirPath);
    
    // Save config
    const config = {
      homeDir: dirPath,
      version: app.getVersion(),
    };
    configManager.save(config);
    
    return { success: true };
  } catch (error) {
    throw new Error(`Initialization failed: ${error}`);
  }
});

ipcMain.on('wizard-complete', async () => {
  // Close wizard
  wizardWindow?.close();
  
  // Load config
  const config = configManager.load();
  if (!config) {
    console.error('Failed to load config after wizard');
    app.quit();
    return;
  }

  // Start backend services
  processManager = new ProcessManager(config.homeDir);
  try {
    await processManager.startBackend();
    await processManager.startTaskService();
  } catch (error) {
    console.error('Failed to start services:', error);
    dialog.showErrorBox('Startup Error', `Failed to start services: ${error}`);
    app.quit();
    return;
  }

  // Create main window and tray
  createMainWindow();
  createTray();
});

// Add isQuitting flag to app
declare module 'electron' {
  interface App {
    isQuitting?: boolean;
  }
}
```

- [ ] **Step 3: Build main process**

```bash
cd electron-app
npm run build
```

Expected: TypeScript compiled successfully

- [ ] **Step 4: Commit**

```bash
git add electron-app/src/main.ts
git commit -m "feat: add Electron main process with IPC handlers"
```

---