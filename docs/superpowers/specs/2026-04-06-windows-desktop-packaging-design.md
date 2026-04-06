# Windows Desktop Packaging Design

**Date:** 2026-04-06  
**Status:** Draft  
**Target:** Package RpaClaw as a Windows desktop application for non-technical business users

## Overview

Package RpaClaw as a standalone Windows desktop application that runs in local mode without requiring Docker, MongoDB, or any development environment. The application will use Electron as the UI shell, embed Python runtime and all dependencies, and provide a standard Windows installation experience.

## Scope

**Included Services:**
- Backend (FastAPI)
- Task-service (scheduled tasks)
- Frontend (Vue 3 SPA, packaged as Electron app)

**Excluded Services:**
- MongoDB (replaced by local JSON file storage)
- Sandbox Docker container (only local mode RPA supported)
- Redis/Celery (Task-service simplified to scheduled tasks)

**Key Features:**
- Embedded Python 3.13 runtime with all dependencies
- Playwright + Chromium browser for local RPA
- Standard Windows installer with first-run setup wizard
- Automatic directory initialization
- No development environment required

## Architecture

### Packaging Strategy

- **Python Runtime:** Python 3.13 embeddable package (~30MB)
- **Dependencies:** All pip packages installed to embedded Python's Lib/site-packages
- **Playwright Browser:** Chromium downloaded and bundled during build (~300MB)
- **Frontend:** Electron application wrapping Vue 3 built static files
- **Installer:** Electron Builder generating Windows NSIS installer
- **Total Size:** ~1.5GB (including Chromium browser)

### Directory Structure

**Installation Directory (C:\Program Files\RpaClaw\):**
```
RpaClaw\
├── python\                         # Python 3.13 embeddable (30MB)
│   ├── python.exe
│   ├── python313.dll
│   └── Lib\
│       └── site-packages\          # All dependencies
│           ├── fastapi\
│           ├── playwright\
│           ├── langchain\
│           └── playwright\driver\package\.local-browsers\  # Chromium
├── backend\                        # Backend source code
│   ├── main.py
│   ├── config.py
│   ├── route\
│   ├── deepagent\
│   ├── rpa\
│   └── ...
├── task-service\                   # Task-service source code
│   └── app\
├── builtin_skills\                 # 9 built-in skills (read-only)
│   ├── pdf\
│   ├── docx\
│   ├── pptx\
│   └── ...
├── resources\                      # Electron resources
│   ├── app\dist\                   # Frontend build output
│   └── icon.ico
└── RpaClaw.exe                     # Electron main executable
```

**Home Directory (C:\Users\{username}\RpaClaw\):**
```
RpaClaw\
├── config.json                     # User configuration
├── workspace\                      # User workspace
├── external_skills\                # User custom skills
├── data\                           # Local data storage
│   ├── sessions\                   # Session data (JSON files)
│   ├── users\                      # User data (JSON files)
│   └── tasks\                      # Scheduled task data
└── logs\                           # Application logs
    ├── backend.log
    └── task-service.log
```

**App Config Location:**
- `%APPDATA%\RpaClaw\app-config.json` - Stores Home directory path

### Installation Mode

**Standard Windows Installation:**
- Requires administrator privileges
- Program files installed to `C:\Program Files\RpaClaw\` (read-only)
- User data stored in `C:\Users\{username}\RpaClaw\` (read-write)
- Start menu shortcuts and desktop icon created
- Standard uninstaller provided
- Multi-user friendly (each user has independent Home directory)

## First-Run Experience

### Setup Wizard Flow

**1. Detection Phase**
- Check if `%APPDATA%\RpaClaw\app-config.json` exists
- If not found, trigger first-run wizard

**2. Welcome Page**
- Introduction to RpaClaw
- Brief feature overview
- "Get Started" button

**3. Home Directory Selection**
- Default: `C:\Users\{username}\RpaClaw`
- "Browse" button to select custom location
- Display estimated space requirement (~500MB)
- Validate selected path (writable, sufficient space)

**4. Initialization Progress**
- Show progress bar with status messages:
  - Creating directory structure
  - Initializing workspace
  - Generating configuration
  - Setting up logging
- Create directories: workspace, external_skills, data, logs
- Generate `config.json` with default settings
- Save Home path to `%APPDATA%\RpaClaw\app-config.json`

**5. Completion**
- "Setup Complete" message
- Launch main application

### Subsequent Launches

- Read Home path from `%APPDATA%\RpaClaw\app-config.json`
- Start Backend and Task-service processes
- Open Electron window with frontend
- User can change Home directory in Settings (requires restart)

## Backend Configuration

### Environment Variables

Electron main process sets these environment variables when spawning Backend:

```javascript
{
  // Storage mode
  STORAGE_BACKEND: 'local',
  
  // Home directory paths
  RPA_CLAW_HOME: homeDir,
  WORKSPACE_DIR: path.join(homeDir, 'workspace'),
  EXTERNAL_SKILLS_DIR: path.join(homeDir, 'external_skills'),
  LOCAL_DATA_DIR: path.join(homeDir, 'data'),
  
  // Installation directory paths (read-only)
  BUILTIN_SKILLS_DIR: path.join(installDir, 'builtin_skills'),
  
  // Service ports
  BACKEND_PORT: '12001',
  TASK_SERVICE_PORT: '12002',
  
  // Python environment
  PYTHONHOME: path.join(installDir, 'python'),
  PYTHONPATH: path.join(installDir, 'python', 'Lib', 'site-packages'),
  
  // Playwright browser path
  PLAYWRIGHT_BROWSERS_PATH: path.join(installDir, 'python', 'Lib', 'site-packages', 'playwright', 'driver', 'package', '.local-browsers'),
  
  // Runtime settings
  ENVIRONMENT: 'production',
  LOG_LEVEL: 'INFO',
}
```

### Backend Modifications Required

**config.py:**
- Ensure `STORAGE_BACKEND=local` activates JSON file storage mode
- `BUILTIN_SKILLS_DIR` points to installation directory (read-only)
- `EXTERNAL_SKILLS_DIR` points to Home directory (read-write)
- Log files written to `{HOME}/logs/backend.log`

**Data Storage:**
- Current local mode JSON storage implementation is used as-is
- No MongoDB dependency

**RPA Mode:**
- Only local mode supported (no Docker sandbox)
- Playwright runs on host machine using embedded Chromium
- CDP screencast for display streaming

## Electron Application

### Main Process Responsibilities

**1. Backend Process Management**
- Spawn Backend process: `python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 12001`
- Spawn Task-service process: `python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 12002`
- Monitor process health (restart on crash)
- Terminate processes on app quit
- Handle port conflicts (try alternative ports if occupied)

**2. Window Management**
- Create main window (1280x800, resizable)
- Load `http://127.0.0.1:12001` (Backend serves frontend static files)
- Handle window close (minimize to system tray option)
- System tray icon with context menu (Show/Hide, Quit)

**3. Configuration Management**
- Read/write `%APPDATA%\RpaClaw\app-config.json`
- Expose IPC channels for renderer to access config
- Handle Home directory changes (require restart)

**4. First-Run Wizard**
- Detect first run
- Show wizard window (modal, 600x400)
- Initialize Home directory
- Save configuration

### Renderer Process

- Load Vue 3 frontend from Backend static file server
- Communicate with Backend via REST API (http://127.0.0.1:12001/api/v1)
- No changes to existing frontend code required

### IPC Channels

```javascript
// Main -> Renderer
'backend-status': { running: boolean, port: number }
'task-service-status': { running: boolean, port: number }

// Renderer -> Main
'get-home-dir': () => string
'set-home-dir': (path: string) => void
'restart-app': () => void
'open-external': (url: string) => void
```

## Build Process

### Build Pipeline

**1. Frontend Build**
```bash
cd RpaClaw/frontend
npm install
npm run build
# Output: dist/ folder
```

**2. Python Environment Preparation**
```bash
# Download Python 3.13 embeddable package
curl -O https://www.python.org/ftp/python/3.13.0/python-3.13.0-embed-amd64.zip
unzip python-3.13.0-embed-amd64.zip -d build/python

# Install pip
curl -O https://bootstrap.pypa.io/get-pip.py
build/python/python.exe get-pip.py

# Install dependencies
build/python/python.exe -m pip install -r RpaClaw/backend/requirements.txt
build/python/python.exe -m pip install -r RpaClaw/task-service/requirements.txt

# Install Playwright browsers
build/python/python.exe -m playwright install chromium
```

**3. Electron Build**
```bash
cd electron-app
npm install
npm run build
# Electron Builder packages everything into installer
```

### Electron Builder Configuration

**package.json:**
```json
{
  "name": "rpaclaw",
  "version": "1.0.0",
  "main": "dist/main.js",
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
        "to": "python"
      },
      {
        "from": "../RpaClaw/backend",
        "to": "backend"
      },
      {
        "from": "../RpaClaw/task-service",
        "to": "task-service"
      },
      {
        "from": "../RpaClaw/backend/builtin_skills",
        "to": "builtin_skills"
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
      "createStartMenuShortcut": true
    }
  }
}
```

### Build Script

**build.sh (or build.ps1 for Windows):**
```bash
#!/bin/bash
set -e

echo "Building RpaClaw Windows Desktop Application..."

# 1. Build frontend
echo "Step 1: Building frontend..."
cd RpaClaw/frontend
npm install
npm run build
cd ../..

# 2. Prepare Python environment
echo "Step 2: Preparing Python environment..."
mkdir -p build/python
curl -O https://www.python.org/ftp/python/3.13.0/python-3.13.0-embed-amd64.zip
unzip -q python-3.13.0-embed-amd64.zip -d build/python
curl -O https://bootstrap.pypa.io/get-pip.py
build/python/python.exe get-pip.py
build/python/python.exe -m pip install -r RpaClaw/backend/requirements.txt
build/python/python.exe -m pip install -r RpaClaw/task-service/requirements.txt
build/python/python.exe -m playwright install chromium

# 3. Build Electron app
echo "Step 3: Building Electron application..."
cd electron-app
npm install
npm run build

echo "Build complete! Installer: electron-app/release/RpaClaw-Setup-1.0.0.exe"
```

## Project Structure

### New Directory: electron-app/

```
electron-app/
├── package.json                    # Electron Builder config
├── tsconfig.json                   # TypeScript config
├── src/
│   ├── main.ts                     # Electron main process
│   ├── preload.ts                  # Preload script
│   └── wizard/                     # First-run wizard
│       ├── wizard.html
│       ├── wizard.ts
│       └── wizard.css
├── resources/
│   └── icon.ico                    # Application icon
└── dist/                           # Compiled output (gitignored)
```

### Modified Files

**RpaClaw/backend/config.py:**
- Add logic to handle `STORAGE_BACKEND=local`
- Ensure paths resolve correctly in packaged environment

**RpaClaw/backend/main.py:**
- Add static file serving for frontend dist folder
- Ensure CORS allows Electron origin

**RpaClaw/frontend/src/api/client.ts:**
- Base URL should work with `http://127.0.0.1:12001`

## Testing Strategy

### Development Testing

**1. Local Development Mode**
- Run Backend and Task-service manually
- Run Electron app in dev mode: `npm run dev`
- Test IPC communication
- Test process management

**2. Build Testing**
- Build installer on Windows machine
- Install to test machine (clean Windows VM)
- Verify first-run wizard
- Test all features in packaged environment
- Test uninstall process

### User Acceptance Testing

**Target Users:** Non-technical business users

**Test Scenarios:**
1. Install application on clean Windows 10/11 machine
2. Complete first-run wizard
3. Create a new session and chat with agent
4. Record an RPA skill (local mode)
5. Schedule a task
6. Restart application (verify data persistence)
7. Change Home directory in settings
8. Uninstall application

## Deployment

### Release Process

**1. Version Bump**
- Update version in `electron-app/package.json`
- Update version in `RpaClaw/backend/main.py`

**2. Build Installer**
- Run build script on Windows build machine
- Output: `RpaClaw-Setup-{version}.exe`

**3. Distribution**
- Upload installer to release server
- Provide download link to users
- Optional: Code signing certificate for Windows SmartScreen

### Auto-Update (Future Enhancement)

- Electron Builder supports auto-update via electron-updater
- Requires update server hosting release metadata
- Can be added in future versions

## Security Considerations

**1. Local-Only Access**
- Backend binds to 127.0.0.1 (not 0.0.0.0)
- No external network exposure

**2. File System Permissions**
- Installation directory is read-only (Program Files)
- Home directory is user-writable only
- No elevated privileges required after installation

**3. API Key Storage**
- User API keys stored in `config.json` (plain text)
- Future: Consider Windows Credential Manager integration

**4. Code Signing**
- Recommended: Sign installer with code signing certificate
- Prevents Windows SmartScreen warnings

## Known Limitations

**1. RPA Functionality**
- Only local mode supported (no Docker sandbox)
- Cannot execute arbitrary code in isolated environment
- Playwright runs on host machine

**2. Database**
- JSON file storage (not suitable for large datasets)
- No concurrent access control
- Performance degrades with many sessions

**3. Task Service**
- Simplified scheduling (no Celery/Redis)
- Tasks run in same process as API server
- No distributed task execution

**4. Platform**
- Windows only (macOS/Linux require separate builds)
- Requires Windows 10 or later

## Future Enhancements

**1. Auto-Update**
- Implement electron-updater for seamless updates

**2. Better Data Storage**
- Migrate to SQLite for better performance
- Add data export/import functionality

**3. Multi-Language Support**
- Package with multiple LLM provider support
- Offline mode with local models

**4. Enhanced Security**
- Windows Credential Manager for API keys
- Encrypted data storage

**5. Cross-Platform**
- macOS and Linux builds
- Unified build pipeline

## Success Criteria

**Installation:**
- ✓ User can install without any development tools
- ✓ Installation completes in under 5 minutes
- ✓ First-run wizard is intuitive

**Functionality:**
- ✓ All core features work (chat, RPA, tasks, skills)
- ✓ Application starts in under 10 seconds
- ✓ No crashes during normal usage

**User Experience:**
- ✓ Feels like a native Windows application
- ✓ No command-line interaction required
- ✓ Clear error messages for common issues

**Performance:**
- ✓ Memory usage under 500MB idle
- ✓ CPU usage under 5% idle
- ✓ Responsive UI (no freezing)
