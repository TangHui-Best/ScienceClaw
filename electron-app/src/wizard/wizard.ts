// Use window.electronAPI provided by preload script
// Type is already defined in preload.ts

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
    await window.electronAPI.initializeHomeDir(selectedHomeDir);
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

function setupEventListeners() {
  // Page 1: Welcome
  document.getElementById('btn-start')?.addEventListener('click', async () => {
    showPage(1);

    // Load default home directory
    const dir = await window.electronAPI.getDefaultHomeDir();
    selectedHomeDir = dir;
    const input = document.getElementById('input-home-dir') as HTMLInputElement;
    if (input) input.value = dir;
  });

  // Page 2: Home Directory Selection
  document.getElementById('btn-browse')?.addEventListener('click', async () => {
    const result = await window.electronAPI.selectDirectory();
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
    const validation = await window.electronAPI.validateHomeDir(selectedHomeDir);
    if (!validation.valid) {
      showError(validation.error || 'Invalid directory');
      return;
    }

    hideError();
    await initializeHomeDir();
  });

  // Page 4: Complete
  document.getElementById('btn-launch')?.addEventListener('click', () => {
    window.electronAPI.wizardComplete();
  });
}

// Wait for DOM to be ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    showPage(0);
  });
} else {
  setupEventListeners();
  showPage(0);
}
