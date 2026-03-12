(function () {
  const els = {
    status: document.getElementById('bootStatus'),
    statusReason: document.getElementById('bootStatusReason'),
    stage: document.getElementById('bootStage'),
    paths: document.getElementById('bootPaths'),
    error: document.getElementById('bootError'),
    primary: document.getElementById('btnBootPrimaryAction'),
    restart: document.getElementById('btnBootRestart'),
    stop: document.getElementById('btnBootStop'),
    openUi: document.getElementById('btnBootOpenUi'),
    openState: document.getElementById('btnBootOpenState'),
    openPublished: document.getElementById('btnBootOpenPublished'),
    openRuntime: document.getElementById('btnBootOpenRuntime'),
    openLogs: document.getElementById('btnBootOpenLogs'),
    closeBehavior: document.getElementById('prefCloseBehavior'),
    autoStart: document.getElementById('prefAutoStart'),
    trayFallback: document.getElementById('bootTrayFallback'),
    backgroundNote: document.getElementById('bootBackgroundNote'),
    acknowledgeBackground: document.getElementById('btnBootAcknowledgeBackground'),
  };

  let currentState = null;
  let savingPreferences = false;

  function primaryActionForState(state) {
    const status = String(state.status || 'setup_required');
    if (status === 'setup_required') {
      return { label: 'Open setup', action: 'startSetup' };
    }
    if (status === 'stopped') {
      return { label: 'Start runtime', action: 'startRuntime' };
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
    return { label: 'Open browser fallback', action: 'openExternalUi' };
  }

  function render(state) {
    currentState = state;
    const status = String(state.status || 'setup_required');
    els.status.textContent = String(state.label || 'Setup required');
    els.status.className = `boot-status ${status}`;
    els.statusReason.textContent = String(state.statusReason || '');
    els.stage.textContent = state.bootStage || 'Preparing desktop shell.';
    const rows = [
      `runtime=${state.runtimeUrl || 'not started'}`,
      `store=${state.storePath || 'not selected yet'}`,
      `published=${state.episodeCardsPath || 'not published yet'}`,
      `wizard=${state.wizardRunId || 'none yet'}`,
      `logs=${state.logPath || 'pending'}`,
    ];
    if (Array.isArray(state.missingArtifacts) && state.missingArtifacts.length) {
      rows.push(...state.missingArtifacts.map((row) => `missing=${row.label}: ${row.path}`));
    }
    els.paths.replaceChildren(
      ...rows.map((row) => {
        const item = document.createElement('div');
        item.textContent = row;
        return item;
      }),
    );
    const errorText = String(state.lastError || '').trim();
    els.error.textContent = errorText;
    els.error.classList.toggle('visually-hidden', !errorText);
    const primary = primaryActionForState(state);
    els.primary.textContent = primary.label;
    els.primary.disabled = !primary.action;
    els.primary.dataset.action = primary.action || '';
    els.openUi.disabled = !state.runtimeUrl;
    els.restart.disabled = status === 'booting';
    const canStop = Boolean(state.runtimeUrl) || ['booting', 'ready', 'degraded'].includes(status);
    els.stop.disabled = !canStop;
    els.closeBehavior.value = (state.preferences || {}).close_behavior || 'hide_to_tray';
    els.autoStart.value = (state.preferences || {}).auto_start || 'auto_start_if_ready';
    const trayMessage = String(state.trayFallbackMessage || '').trim();
    els.trayFallback.textContent = trayMessage;
    els.trayFallback.classList.toggle('visually-hidden', !state.trayFallbackActive || !trayMessage);
    const showBackgroundNote = Boolean(state.trayAvailable) && (state.preferences || {}).close_behavior === 'hide_to_tray' && !(state.preferences || {}).background_explainer_seen;
    els.backgroundNote.classList.toggle('visually-hidden', !showBackgroundNote);
  }

  async function savePreferences() {
    if (!window.desktopShell || savingPreferences) {
      return;
    }
    savingPreferences = true;
    try {
      render(await window.desktopShell.setPreferences({
        close_behavior: els.closeBehavior.value,
        auto_start: els.autoStart.value,
      }));
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
  els.restart.addEventListener('click', async () => {
    render(await window.desktopShell.restartRuntime());
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
