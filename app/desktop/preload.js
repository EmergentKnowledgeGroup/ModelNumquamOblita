const { contextBridge, ipcRenderer } = require('electron');

const isTrustedBootPage = window.location.protocol === 'file:' && window.location.pathname.endsWith('/boot.html');

if (isTrustedBootPage) {
  contextBridge.exposeInMainWorld('desktopShell', {
    getState: () => ipcRenderer.invoke('desktop-shell:get-state'),
    restartRuntime: () => ipcRenderer.invoke('desktop-shell:restart-runtime'),
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
