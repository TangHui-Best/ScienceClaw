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
  wizardComplete: () => ipcRenderer.send('wizard-complete'),
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
      wizardComplete: () => void;
      onWizardComplete: (callback: () => void) => void;
    };
  }
}
