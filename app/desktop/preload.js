const { contextBridge, ipcRenderer } = require('electron');

const isTrustedBootPage = window.location.protocol === 'file:' && window.location.pathname.endsWith('/boot.html');

if (isTrustedBootPage) {
  contextBridge.exposeInMainWorld('desktopShell', {
    getState: () => ipcRenderer.invoke('desktop-shell:get-state'),
    getPreferences: () => ipcRenderer.invoke('desktop-shell:get-preferences'),
    setPreferences: (patch) => ipcRenderer.invoke('desktop-shell:set-preferences', patch),
    startRuntime: () => ipcRenderer.invoke('desktop-shell:start-runtime'),
    startSetup: () => ipcRenderer.invoke('desktop-shell:start-setup'),
    repairRuntime: () => ipcRenderer.invoke('desktop-shell:repair-runtime'),
    restartRuntime: () => ipcRenderer.invoke('desktop-shell:restart-runtime'),
    stopRuntime: () => ipcRenderer.invoke('desktop-shell:stop-runtime'),
    acknowledgeBackgroundExplainer: () => ipcRenderer.invoke('desktop-shell:acknowledge-background-explainer'),
    openRuntimeFolder: () => ipcRenderer.invoke('desktop-shell:open-runtime-folder'),
    openStateFolder: () => ipcRenderer.invoke('desktop-shell:open-state-folder'),
    openPublishedSets: () => ipcRenderer.invoke('desktop-shell:open-published-sets'),
    openRuntimeLogs: () => ipcRenderer.invoke('desktop-shell:open-runtime-logs'),
    openExternalUi: () => ipcRenderer.invoke('desktop-shell:open-external-ui'),
    onStateChange: (callback) => {
      if (typeof callback !== 'function') {
        return () => {};
      }
      const handler = (_event, payload) => callback(payload);
      ipcRenderer.on('desktop-shell:state', handler);
      return () => ipcRenderer.removeListener('desktop-shell:state', handler);
    },
  });
}
