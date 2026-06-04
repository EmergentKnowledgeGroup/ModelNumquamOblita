(function () {
  const els = {
    status: document.getElementById('bootStatus'),
    statusReason: document.getElementById('bootStatusReason'),
    inlineRepair: document.getElementById('btnBootInlineRepair'),
    stage: document.getElementById('bootStage'),
    paths: document.getElementById('bootPaths'),
    mcpStatus: document.getElementById('bootMcpStatus'),
    mcpSummary: document.getElementById('bootMcpSummary'),
    mcpMode: document.getElementById('bootMcpMode'),
    mcpUrl: document.getElementById('bootMcpUrl'),
    error: document.getElementById('bootError'),
    primary: document.getElementById('btnBootPrimaryAction'),
    openSetup: document.getElementById('btnBootOpenSetup'),
    restart: document.getElementById('btnBootRestart'),
    stop: document.getElementById('btnBootStop'),
    openUi: document.getElementById('btnBootOpenUi'),
    openState: document.getElementById('btnBootOpenState'),
    openPublished: document.getElementById('btnBootOpenPublished'),
    openRuntime: document.getElementById('btnBootOpenRuntime'),
    openLogs: document.getElementById('btnBootOpenLogs'),
    openMcpLogs: document.getElementById('btnBootOpenMcpLogs'),
    closeBehavior: document.getElementById('prefCloseBehavior'),
    autoStart: document.getElementById('prefAutoStart'),
    trayFallback: document.getElementById('bootTrayFallback'),
    backgroundNote: document.getElementById('bootBackgroundNote'),
    acknowledgeBackground: document.getElementById('btnBootAcknowledgeBackground'),
  };

  let currentState = null;
  let savingPreferences = false;
  let pendingPreferences = null;

  function preferencePayload() {
    return {
      close_behavior: els.closeBehavior.value,
      auto_start: els.autoStart.value,
    };
  }

  function primaryActionForState(state) {
    const status = String(state.status || 'setup_required');
    if (status === 'setup_required') {
      return { label: 'Open setup workspace', action: 'startSetup' };
    }
    if (status === 'stopped') {
      return { label: 'Start runtime in background', action: 'startRuntime' };
    }
    if (status === 'degraded') {
      return state.canRepairRuntime ? { label: 'Repair and continue', action: 'repairRuntime' } : { label: 'Open repair flow', action: 'startSetup' };
    }
    if (status === 'error') {
      return { label: 'Retry runtime', action: 'restartRuntime' };
    }
    if (status === 'booting') {
      return { label: 'Starting…', action: null };
    }
    return { label: 'Open chat + memory', action: 'openRuntimeWorkspace' };
  }

  function render(state) {
    currentState = state;
    const status = String(state.status || 'setup_required');
    els.status.textContent = String(state.label || 'Setup required');
    els.status.className = `boot-status ${status}`;
    els.statusReason.textContent = String(state.statusReason || '');
    els.stage.textContent = state.bootStage || 'Preparing desktop shell.';
    const rows = [
      ['runtime', state.runtimeUrl || 'not started'],
      ['store', state.storePath || 'not selected yet'],
      ['published', state.episodeCardsPath || 'not published yet'],
      ['wizard', state.wizardRunId || 'none yet'],
      ['logs', state.logPath || 'pending'],
    ];
    if (Array.isArray(state.missingArtifacts) && state.missingArtifacts.length) {
      rows.push(...state.missingArtifacts.map((row) => [`missing ${row.label}`, row.path]));
    }
    els.paths.replaceChildren(
      ...rows.map(([label, value]) => {
        const item = document.createElement('div');
        item.className = 'boot-path-row';
        const key = document.createElement('span');
        key.className = 'boot-path-key';
        key.textContent = `${label}=`;
        const text = document.createElement('span');
        text.className = 'boot-path-value';
        text.textContent = String(value || '-');
        item.append(key, text);
        return item;
      }),
    );
    const mcpStatus = String(state.mcpStatus || 'not_installed');
    els.mcpStatus.textContent = String(state.mcpLabel || 'Not installed');
    els.mcpStatus.className = `boot-status ${mcpStatus === 'ready' ? 'ready' : (mcpStatus === 'starting' ? 'booting' : (mcpStatus === 'needs_attention' ? 'degraded' : 'stopped'))}`;
    const mcpSummary = mcpStatus === 'ready'
      ? 'An assistant or agent can connect to the managed local memory server.'
      : (String(state.mcpLastError || '').trim() || 'Not connected yet. Open setup, then Activate to install an assistant/agent / MCP client.');
    els.mcpSummary.textContent = mcpSummary;
    els.mcpMode.replaceChildren();
    const modeRows = [
      ['current lane', state.mcpArtifactMode ? String(state.mcpArtifactMode) : 'reviewed'],
      ['current role', String(state.mcpRole || 'viewer')],
      ['writes', state.mcpMutationsEnabled ? 'on' : 'off'],
      ['compat', String(state.mcpCompatMode || 'strict')],
      ['saved profiles', String(state.mcpProfilesSummary || '-')],
    ];
    els.mcpMode.replaceChildren(
      ...modeRows.map(([label, value]) => {
        const item = document.createElement('div');
        item.className = 'boot-path-row';
        const key = document.createElement('span');
        key.className = 'boot-path-key';
        key.textContent = `${label}=`;
        const text = document.createElement('span');
        text.className = 'boot-path-value';
        text.textContent = String(value || '-');
        item.append(key, text);
        return item;
      }),
    );
    els.mcpUrl.replaceChildren();
    if (state.mcpUrl) {
      const item = document.createElement('div');
      item.className = 'boot-path-row';
      const key = document.createElement('span');
      key.className = 'boot-path-key';
      key.textContent = 'url=';
      const text = document.createElement('span');
      text.className = 'boot-path-value';
      text.textContent = String(state.mcpUrl || '-');
      item.append(key, text);
      els.mcpUrl.append(item);
    }
    const errorText = String(state.lastError || '').trim();
    els.error.textContent = errorText;
    els.error.classList.toggle('visually-hidden', !errorText);
    const primary = primaryActionForState(state);
    els.primary.textContent = primary.label;
    els.primary.disabled = !primary.action;
    els.primary.dataset.action = primary.action || '';
    const setupEnabled = Boolean(state.canStartSetup);
    els.openSetup.disabled = !setupEnabled;
    els.openUi.textContent = 'Open browser fallback';
    els.openUi.disabled = !state.runtimeUrl;
    els.restart.disabled = status === 'booting';
    const canStop = Boolean(state.runtimeUrl) || ['booting', 'ready', 'degraded'].includes(status);
    els.stop.disabled = !canStop;
    els.closeBehavior.value = (state.preferences || {}).close_behavior || 'hide_to_tray';
    els.autoStart.value = (state.preferences || {}).auto_start || 'auto_start_if_ready';
    const trayMessage = String(state.trayFallbackMessage || '').trim();
    els.trayFallback.textContent = trayMessage;
    els.trayFallback.classList.toggle('visually-hidden', !state.trayFallbackActive || !trayMessage);
    const inlineRepairVisible = Boolean(state.canRepairRuntime);
    els.inlineRepair.classList.toggle('visually-hidden', !inlineRepairVisible);
    els.inlineRepair.disabled = !inlineRepairVisible;
    const showBackgroundNote = Boolean(state.trayAvailable) && (state.preferences || {}).close_behavior === 'hide_to_tray' && !(state.preferences || {}).background_explainer_seen;
    els.backgroundNote.classList.toggle('visually-hidden', !showBackgroundNote);
  }

  async function savePreferences() {
    if (!window.desktopShell) {
      return;
    }
    pendingPreferences = preferencePayload();
    if (savingPreferences) {
      return;
    }
    savingPreferences = true;
    try {
      while (pendingPreferences) {
        const nextPreferences = pendingPreferences;
        pendingPreferences = null;
        render(await window.desktopShell.setPreferences(nextPreferences));
      }
    } finally {
      savingPreferences = false;
    }
  }

  async function runPrimaryAction() {
    if (!window.desktopShell || !currentState) {
      return;
    }
    const action = els.primary.dataset.action;
    if (!action || typeof window.desktopShell[action] !== 'function') {
      return;
    }
    render(await window.desktopShell[action]());
  }

  async function refresh() {
    if (!window.desktopShell) {
      return;
    }
    render(await window.desktopShell.getState());
  }

  els.primary.addEventListener('click', () => {
    runPrimaryAction().catch(() => {});
  });
  els.openSetup.addEventListener('click', async () => {
    render(await window.desktopShell.startSetup());
  });
  els.restart.addEventListener('click', async () => {
    render(await window.desktopShell.restartRuntime());
  });
  els.inlineRepair.addEventListener('click', async () => {
    render(await window.desktopShell.repairRuntime());
  });
  els.stop.addEventListener('click', async () => {
    render(await window.desktopShell.stopRuntime());
  });
  els.openUi.addEventListener('click', async () => {
    await window.desktopShell.openExternalUi();
  });
  els.openState.addEventListener('click', async () => {
    await window.desktopShell.openStateFolder();
  });
  els.openPublished.addEventListener('click', async () => {
    await window.desktopShell.openPublishedSets();
  });
  els.openRuntime.addEventListener('click', async () => {
    await window.desktopShell.openRuntimeFolder();
  });
  els.openLogs.addEventListener('click', async () => {
    await window.desktopShell.openRuntimeLogs();
  });
  els.openMcpLogs.addEventListener('click', async () => {
    await window.desktopShell.openMcpLogs();
  });
  els.closeBehavior.addEventListener('change', () => {
    savePreferences().catch(() => {});
  });
  els.autoStart.addEventListener('change', () => {
    savePreferences().catch(() => {});
  });
  els.acknowledgeBackground.addEventListener('click', async () => {
    if (!window.desktopShell) {
      return;
    }
    await window.desktopShell.acknowledgeBackgroundExplainer();
    render(await window.desktopShell.getState());
  });

  const unsubscribe = window.desktopShell?.onStateChange((state) => render(state));
  window.addEventListener('beforeunload', () => {
    if (typeof unsubscribe === 'function') {
      unsubscribe();
    }
  });
  refresh().catch(() => {});
})();
