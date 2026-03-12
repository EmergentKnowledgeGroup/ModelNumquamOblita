function buildTrayMenuTemplate(state = {}) {
  const statusLabel = String(state.label || 'Setup required').trim() || 'Setup required';
  const canStartRuntime = Boolean(state.canStartRuntime) && ['stopped'].includes(String(state.status || '').trim());
  const canOpenSetup = Boolean(state.canStartSetup) && ['setup_required', 'degraded', 'error'].includes(String(state.status || '').trim());
  const canRepairRuntime = Boolean(state.canRepairRuntime);
  const runtimeReachable = Boolean(String(state.runtimeUrl || '').trim());
  const runtimeLive = ['booting', 'ready'].includes(String(state.status || '').trim()) || runtimeReachable;
  return [
    { id: 'status', label: `Status: ${statusLabel}`, enabled: false },
    { type: 'separator' },
    { id: 'open-app', label: 'Open ModelNumquamOblita', enabled: true },
    { id: 'start-runtime', label: 'Start Runtime', enabled: canStartRuntime },
    { id: 'open-setup', label: 'Open Setup', enabled: canOpenSetup },
    { id: 'repair-runtime', label: 'Repair Runtime Claim', enabled: canRepairRuntime },
    { id: 'restart-runtime', label: 'Restart Runtime', enabled: runtimeLive },
    { id: 'stop-runtime', label: 'Stop Runtime', enabled: runtimeLive },
    { type: 'separator' },
    { id: 'open-logs', label: 'Open Logs', enabled: true },
    { id: 'open-state-folder', label: 'Open State Folder', enabled: true },
    { type: 'separator' },
    { id: 'quit', label: 'Quit', enabled: true },
  ];
}

module.exports = {
  buildTrayMenuTemplate,
};
