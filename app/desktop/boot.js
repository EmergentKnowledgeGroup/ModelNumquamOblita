(function () {
  const els = {
    status: document.getElementById('bootStatus'),
    stage: document.getElementById('bootStage'),
    paths: document.getElementById('bootPaths'),
    error: document.getElementById('bootError'),
    retry: document.getElementById('btnBootRetry'),
    openUi: document.getElementById('btnBootOpenUi'),
    openState: document.getElementById('btnBootOpenState'),
    openPublished: document.getElementById('btnBootOpenPublished'),
    openRuntime: document.getElementById('btnBootOpenRuntime'),
    openLogs: document.getElementById('btnBootOpenLogs'),
  };

  function render(state) {
    const status = String(state.status || 'idle');
    els.status.textContent = status === 'ready' ? 'Runtime ready' : status === 'error' ? 'Needs attention' : 'Booting';
    els.status.className = `boot-status ${status === 'ready' ? 'ready' : status === 'error' ? 'error' : 'booting'}`;
    els.stage.textContent = state.bootStage || 'Preparing runtime startup.';
    els.paths.innerHTML = [
      `runtime=${state.runtimeUrl || 'pending'}`,
      `store=${state.storePath || 'auto-detecting'}`,
      `episodes=${state.episodeCardsPath || 'latest published or none'}`,
      `state=${state.wizardRunsPath || 'pending'}`,
      `published=${state.publishedSetsPath || 'pending'}`,
      `logs=${state.logPath || 'pending'}`,
    ].map((row) => `<div>${row}</div>`).join('');
    const errorText = String(state.lastError || '').trim();
    els.error.textContent = errorText;
    els.error.classList.toggle('hidden', !errorText);
    els.openUi.disabled = !state.runtimeUrl;
  }

  async function refresh() {
    if (!window.desktopShell) {
      return;
    }
    render(await window.desktopShell.getState());
  }

  els.retry.addEventListener('click', async () => {
    render(await window.desktopShell.restartRuntime());
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

  const unsubscribe = window.desktopShell?.onStateChange((state) => render(state));
  window.addEventListener('beforeunload', () => {
    if (typeof unsubscribe === 'function') {
      unsubscribe();
    }
  });
  refresh().catch(() => {});
})();
