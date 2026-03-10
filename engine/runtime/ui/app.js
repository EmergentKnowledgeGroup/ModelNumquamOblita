const state = {
  turns: [],
  selectedTurnId: null,
  routePreview: null,
  contextPackage: null,
  contextError: null,
  memoryCards: [],
  selectedCardId: null,
  selectedCardDetail: null,
  cardDetailRequestSeq: 0,
  memoryRequestSeq: 0,
  memoryGraph: { nodes: [], links: [], total: 0, truncated: false, snapshotAvailable: true },
  memoryGraphRequestSeq: 0,
  selectedGraphAtomId: null,
  proposals: [],
  proposalsStatus: "ok",
  proposalBusyId: null,
  memoryError: null,
  sessions: [],
  activeSessionId: null,
  sessionTelemetry: null,
  runtimeTelemetryTurns: [],
  wizardState: null,
  wizardRunId: null,
  wizardReviewCards: [],
  episodes: [],
  selectedEpisodeId: null,
  selectedEpisodeDetail: null,
  memoryScope: "atoms",
  whyPayload: null,
  archivePayload: null,
  writebackPolicy: null,
  healthPayload: null,
  packagingPayload: null,
  methodologyReadout: null,
  methodologyRecords: [],
  methodologyClusters: [],
  methodologyMaintenance: [],
  methodologyActionResult: null,
};

const settings = {
  highRiskDefault: false,
  retrievalQuery: "",
  memoryPreference: "auto",
  autoRefreshMs: 0,
  uiMode: "simple",
};

let searchTimer = null;
let autoRefreshTimer = null;
const els = {
  modelName: document.getElementById("modelName"),
  metricTurns: document.getElementById("metricTurns"),
  metricTokens: document.getElementById("metricTokens"),
  metricCost: document.getElementById("metricCost"),
  metricP95: document.getElementById("metricP95"),
  metricRecognition: document.getElementById("metricRecognition"),
  btnSimpleMode: document.getElementById("btnSimpleMode"),
  btnAdvancedMode: document.getElementById("btnAdvancedMode"),
  modeHint: document.getElementById("modeHint"),
  chatLog: document.getElementById("chatLog"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  highRisk: document.getElementById("highRisk"),
  btnRoutePreview: document.getElementById("btnRoutePreview"),
  btnContextPreview: document.getElementById("btnContextPreview"),
  btnContextPreviewSide: document.getElementById("btnContextPreviewSide"),
  routePreview: document.getElementById("routePreview"),
  contextPanel: document.getElementById("contextPanel"),
  contextRaw: document.getElementById("contextRaw"),
  tracePanel: document.getElementById("tracePanel"),
  traceHint: document.getElementById("traceHint"),
  btnRefresh: document.getElementById("btnRefresh"),
  btnLedgerRefresh: document.getElementById("btnLedgerRefresh"),
  ledgerMeta: document.getElementById("ledgerMeta"),
  ledgerList: document.getElementById("ledgerList"),
  turnTemplate: document.getElementById("turnTemplate"),
  memorySearch: document.getElementById("memorySearch"),
  memoryKind: document.getElementById("memoryKind"),
  memoryStatus: document.getElementById("memoryStatus"),
  memoryContradiction: document.getElementById("memoryContradiction"),
  memoryList: document.getElementById("memoryList"),
  memoryDetail: document.getElementById("memoryDetail"),
  memoryGraphMeta: document.getElementById("memoryGraphMeta"),
  memoryGraphSvg: document.getElementById("memoryGraphSvg"),
  memoryGraphDetail: document.getElementById("memoryGraphDetail"),
  btnMemoryGraphRefresh: document.getElementById("btnMemoryGraphRefresh"),
  btnMemoryGraphFocus: document.getElementById("btnMemoryGraphFocus"),
  proposalList: document.getElementById("proposalList"),
  btnMemoryRefresh: document.getElementById("btnMemoryRefresh"),
  btnProposalRefresh: document.getElementById("btnProposalRefresh"),
  sessionSelect: document.getElementById("sessionSelect"),
  sessionLabel: document.getElementById("sessionLabel"),
  btnSessionStart: document.getElementById("btnSessionStart"),
  btnSessionRefresh: document.getElementById("btnSessionRefresh"),
  sessionMeta: document.getElementById("sessionMeta"),
  settingHighRiskDefault: document.getElementById("settingHighRiskDefault"),
  settingRetrievalQuery: document.getElementById("settingRetrievalQuery"),
  settingMemoryPreference: document.getElementById("settingMemoryPreference"),
  settingAutoRefresh: document.getElementById("settingAutoRefresh"),
  wizardRunMeta: document.getElementById("wizardRunMeta"),
  wizardStageRail: document.getElementById("wizardStageRail"),
  btnWizardResume: document.getElementById("btnWizardResume"),
  btnWizardStartNew: document.getElementById("btnWizardStartNew"),
  btnWizardRestore: document.getElementById("btnWizardRestore"),
  btnWizardArtifacts: document.getElementById("btnWizardArtifacts"),
  wizardArchivePath: document.getElementById("wizardArchivePath"),
  btnWizardValidate: document.getElementById("btnWizardValidate"),
  btnWizardImport: document.getElementById("btnWizardImport"),
  wizardImportResult: document.getElementById("wizardImportResult"),
  wizardBuildPolicy: document.getElementById("wizardBuildPolicy"),
  btnWizardBuild: document.getElementById("btnWizardBuild"),
  wizardBuildResult: document.getElementById("wizardBuildResult"),
  builderProfileName: document.getElementById("builderProfileName"),
  builderEntityInclude: document.getElementById("builderEntityInclude"),
  builderEntityExclude: document.getElementById("builderEntityExclude"),
  builderEntityAliases: document.getElementById("builderEntityAliases"),
  builderCueInclude: document.getElementById("builderCueInclude"),
  builderCueExclude: document.getElementById("builderCueExclude"),
  builderDomainInclude: document.getElementById("builderDomainInclude"),
  builderDomainExclude: document.getElementById("builderDomainExclude"),
  btnBuilderSave: document.getElementById("btnBuilderSave"),
  btnBuilderRebuild: document.getElementById("btnBuilderRebuild"),
  wizardBuilderResult: document.getElementById("wizardBuilderResult"),
  wizardReviewSearch: document.getElementById("wizardReviewSearch"),
  wizardReviewStatus: document.getElementById("wizardReviewStatus"),
  btnWizardReviewRefresh: document.getElementById("btnWizardReviewRefresh"),
  wizardReviewList: document.getElementById("wizardReviewList"),
  btnWizardCompileReview: document.getElementById("btnWizardCompileReview"),
  wizardReviewResult: document.getElementById("wizardReviewResult"),
  btnWizardVerify: document.getElementById("btnWizardVerify"),
  wizardVerifyResult: document.getElementById("wizardVerifyResult"),
  wizardVerifyLinks: document.getElementById("wizardVerifyLinks"),
  btnWizardGoLive: document.getElementById("btnWizardGoLive"),
  wizardGoLiveResult: document.getElementById("wizardGoLiveResult"),
  wizardGoLiveConfig: document.getElementById("wizardGoLiveConfig"),
  btnMemoryScopeAtoms: document.getElementById("btnMemoryScopeAtoms"),
  btnMemoryScopeEpisodes: document.getElementById("btnMemoryScopeEpisodes"),
  atomsScopePane: document.getElementById("atomsScopePane"),
  episodesScopePane: document.getElementById("episodesScopePane"),
  episodeSearch: document.getElementById("episodeSearch"),
  episodeStatus: document.getElementById("episodeStatus"),
  btnEpisodeRefresh: document.getElementById("btnEpisodeRefresh"),
  btnEpisodeUndo: document.getElementById("btnEpisodeUndo"),
  episodeList: document.getElementById("episodeList"),
  episodeDetail: document.getElementById("episodeDetail"),
  btnWhyRefresh: document.getElementById("btnWhyRefresh"),
  whyShowCitations: document.getElementById("whyShowCitations"),
  whyPanel: document.getElementById("whyPanel"),
  archiveViewer: document.getElementById("archiveViewer"),
  btnArchiveClear: document.getElementById("btnArchiveClear"),
  proposalAtomId: document.getElementById("proposalAtomId"),
  proposalEditText: document.getElementById("proposalEditText"),
  btnProposalCreateDelete: document.getElementById("btnProposalCreateDelete"),
  btnProposalCreateEdit: document.getElementById("btnProposalCreateEdit"),
  btnOpsRefresh: document.getElementById("btnOpsRefresh"),
  writebackEnabled: document.getElementById("writebackEnabled"),
  btnWritebackSave: document.getElementById("btnWritebackSave"),
  writebackPolicyMeta: document.getElementById("writebackPolicyMeta"),
  btnHealthRun: document.getElementById("btnHealthRun"),
  btnHealthExport: document.getElementById("btnHealthExport"),
  healthPanel: document.getElementById("healthPanel"),
  btnPackagingLoad: document.getElementById("btnPackagingLoad"),
  packagingPanel: document.getElementById("packagingPanel"),
  methodologyId: document.getElementById("methodologyId"),
  methodologyActor: document.getElementById("methodologyActor"),
  methodologyTriggerCondition: document.getElementById("methodologyTriggerCondition"),
  methodologyAction: document.getElementById("methodologyAction"),
  methodologyRationale: document.getElementById("methodologyRationale"),
  methodologyCorrection: document.getElementById("methodologyCorrection"),
  methodologyNote: document.getElementById("methodologyNote"),
  btnMethodologyCreate: document.getElementById("btnMethodologyCreate"),
  btnMethodologyApprove: document.getElementById("btnMethodologyApprove"),
  btnMethodologyReject: document.getElementById("btnMethodologyReject"),
  btnMethodologyCanaryStart: document.getElementById("btnMethodologyCanaryStart"),
  btnMethodologyCanaryEval: document.getElementById("btnMethodologyCanaryEval"),
  btnMethodologyActivate: document.getElementById("btnMethodologyActivate"),
  btnMethodologyRollback: document.getElementById("btnMethodologyRollback"),
  btnMethodologyRecordCorrection: document.getElementById("btnMethodologyRecordCorrection"),
  btnMethodologyMaintenanceEval: document.getElementById("btnMethodologyMaintenanceEval"),
  btnMethodologyRefresh: document.getElementById("btnMethodologyRefresh"),
  methodologyReadoutMeta: document.getElementById("methodologyReadoutMeta"),
  methodologyActionMeta: document.getElementById("methodologyActionMeta"),
};

const ROUTE_LABELS = {
  none: "no memory",
  stm_only: "stm only",
  ltm_light: "ltm light",
  ltm_deep: "ltm deep",
};

const MEMORY_PREFERENCE_LABELS = {
  auto: "balanced",
  chat_first: "chat first",
  memory_assist: "memory assist",
};

const ROUTE_REASON_LABELS = {
  smalltalk_routine: "Routine chat. Memory skipped.",
  casual_prompt_no_recall: "Casual turn. Memory skipped.",
  ambiguous_low_signal_skip: "Low-signal turn. Memory skipped.",
  thread_local_reference: "Recent thread context was enough.",
  explicit_memory_request: "You asked for memory recall.",
  memory_signal_probe: "Memory signal detected. Light retrieval used.",
  default_memory_probe: "Default memory probe route.",
  retrieval_query_override: "Retrieval override provided. Light retrieval used.",
  high_risk_escalation: "High-risk turn forced deep memory route.",
  memory_preference_chat_first: "Chat-first mode reduced memory retrieval.",
  memory_preference_memory_assist: "Memory-assist mode expanded retrieval.",
};

async function refreshDecisionCatalog() {
  try {
    const payload = await jsonFetch("/api/runtime/decision-reasons");
    const reasons = payload.reasons || {};
    for (const [key, value] of Object.entries(reasons)) {
      ROUTE_REASON_LABELS[String(key)] = String(value);
    }
    const routes = payload.routes || {};
    for (const [key, value] of Object.entries(routes)) {
      ROUTE_LABELS[String(key)] = String(value);
    }
    const memoryPreferences = payload.memory_preferences || {};
    for (const [key, value] of Object.entries(memoryPreferences)) {
      MEMORY_PREFERENCE_LABELS[String(key)] = String(value);
    }
  } catch (_error) {
    // If this endpoint is unavailable, keep built-in labels.
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatMoney(value) {
  return `$${Number(value || 0).toFixed(5)}`;
}

function formatLatency(value) {
  return `${Math.round(Number(value || 0))} ms`;
}

function formatDate(value) {
  if (!value) {
    return "-";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "-";
  }
  return parsed.toLocaleString();
}

function normalizeUiMode(raw) {
  return String(raw || "").trim().toLowerCase() === "advanced" ? "advanced" : "simple";
}

function isSimpleMode() {
  return normalizeUiMode(settings.uiMode) === "simple";
}

function applyUIMode() {
  const mode = normalizeUiMode(settings.uiMode);
  settings.uiMode = mode;
  document.body.classList.toggle("simple-mode", mode === "simple");
  els.btnSimpleMode?.classList.toggle("active", mode === "simple");
  els.btnAdvancedMode?.classList.toggle("active", mode === "advanced");
  if (els.modeHint) {
    els.modeHint.textContent =
      mode === "simple"
        ? "Simple mode keeps essentials visible and hides advanced controls."
        : "Advanced mode shows full telemetry, context package, and proposal controls.";
  }
}

function setUiMode(mode) {
  settings.uiMode = normalizeUiMode(mode);
  applyUIMode();
  saveSettings();
}

function loadSettings() {
  try {
    settings.highRiskDefault = window.localStorage.getItem("nq.settings.highRiskDefault") === "1";
    settings.retrievalQuery = window.localStorage.getItem("nq.settings.retrievalQuery") || "";
    settings.memoryPreference = window.localStorage.getItem("nq.settings.memoryPreference") || "auto";
    const autoRaw = Number(window.localStorage.getItem("nq.settings.autoRefreshMs") || "0");
    settings.autoRefreshMs = Number.isFinite(autoRaw) && autoRaw >= 0 ? autoRaw : 0;
    settings.uiMode = normalizeUiMode(window.localStorage.getItem("nq.settings.uiMode") || "simple");
  } catch (_error) {
    settings.highRiskDefault = false;
    settings.retrievalQuery = "";
    settings.memoryPreference = "auto";
    settings.autoRefreshMs = 0;
    settings.uiMode = "simple";
  }
  if (!["auto", "chat_first", "memory_assist"].includes(settings.memoryPreference)) {
    settings.memoryPreference = "auto";
  }
  settings.uiMode = normalizeUiMode(settings.uiMode);
}

function saveSettings() {
  try {
    window.localStorage.setItem("nq.settings.highRiskDefault", settings.highRiskDefault ? "1" : "0");
    window.localStorage.setItem("nq.settings.retrievalQuery", settings.retrievalQuery);
    window.localStorage.setItem("nq.settings.memoryPreference", settings.memoryPreference);
    window.localStorage.setItem("nq.settings.autoRefreshMs", String(settings.autoRefreshMs));
    window.localStorage.setItem("nq.settings.uiMode", normalizeUiMode(settings.uiMode));
  } catch (_error) {
    // local storage can fail in private contexts; ignore silently.
  }
}

function applySettingsToInputs() {
  if (els.highRisk) {
    els.highRisk.checked = settings.highRiskDefault;
  }
  if (els.settingHighRiskDefault) {
    els.settingHighRiskDefault.checked = settings.highRiskDefault;
  }
  if (els.settingRetrievalQuery) {
    els.settingRetrievalQuery.value = settings.retrievalQuery;
  }
  if (els.settingMemoryPreference) {
    const preference = String(settings.memoryPreference || "auto");
    if ([...els.settingMemoryPreference.options].some((opt) => opt.value === preference)) {
      els.settingMemoryPreference.value = preference;
    } else {
      els.settingMemoryPreference.value = "auto";
    }
  }
  if (els.settingAutoRefresh) {
    const value = String(settings.autoRefreshMs);
    if ([...els.settingAutoRefresh.options].some((opt) => opt.value === value)) {
      els.settingAutoRefresh.value = value;
    } else {
      els.settingAutoRefresh.value = "0";
    }
  }
  applyUIMode();
}

function updateAutoRefresh() {
  if (autoRefreshTimer !== null) {
    window.clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
  if (settings.autoRefreshMs > 0) {
    autoRefreshTimer = window.setInterval(() => {
      refreshSessionAndState().catch((error) => showTraceError(error.message));
    }, settings.autoRefreshMs);
  }
}

function showTraceError(message) {
  els.tracePanel.classList.remove("empty");
  els.tracePanel.innerHTML = `<div class="warn">${escapeHtml(message)}</div>`;
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  let payload;
  if (contentType.includes("application/json")) {
    payload = await response.json();
  } else {
    const text = await response.text();
    payload = { error: text || `Request failed: ${response.status}` };
  }
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function renderMetrics(payload) {
  els.modelName.textContent = payload.model_name || "runtime";
  els.metricTurns.textContent = String(payload.stats.turns || 0);
  const tokenTotal = Number(payload.stats.total_input_tokens || 0) + Number(payload.stats.total_output_tokens || 0);
  els.metricTokens.textContent = String(tokenTotal);
  els.metricCost.textContent = formatMoney(payload.stats.total_cost_usd);
  els.metricP95.textContent = formatLatency(payload.stats.p95_latency_ms);
  const recognitionRate = Number(payload.stats.recognition_rate || 0);
  const recognitionEvents = Number(payload.stats.recognition_events || 0);
  els.metricRecognition.textContent = `${Math.round(recognitionRate * 100)}% / ${recognitionEvents}`;
}

function routeLabel(route) {
  return ROUTE_LABELS[String(route || "none")] || String(route || "unknown");
}

function reasonLabel(reason) {
  return ROUTE_REASON_LABELS[String(reason || "")] || String(reason || "-");
}

function memoryPreferenceLabel(preference) {
  const key = String(preference || "auto");
  return MEMORY_PREFERENCE_LABELS[key] || key;
}

function reasonDetail(turn) {
  const explicit = String(turn?.route_reason_text || "").trim();
  if (explicit) {
    return explicit;
  }
  return reasonLabel(turn?.route_reason);
}

function decisionPlainLanguage(decision) {
  const normalized = String(decision || "").trim().toUpperCase();
  if (normalized === "ABSTAIN") {
    return "I could not verify enough evidence, so I avoided a confident memory claim.";
  }
  if (normalized === "UNSUPPORTED") {
    return "I responded without memory support because this looked like normal conversation.";
  }
  if (normalized === "PASS") {
    return "Memory evidence was available and passed verification checks.";
  }
  return "Runtime decision recorded.";
}

function clearRoutePreview(message = "Route preview is available before sending a turn.") {
  state.routePreview = null;
  if (!els.routePreview) {
    return;
  }
  els.routePreview.classList.add("empty");
  els.routePreview.textContent = message;
}

function clearContextPreview(message = "Type a draft message and preview to see the exact package sent to the model.") {
  state.contextPackage = null;
  state.contextError = null;
  if (els.contextPanel) {
    els.contextPanel.classList.add("empty");
    els.contextPanel.textContent = message;
  }
  if (els.contextRaw) {
    els.contextRaw.textContent = "";
  }
}

function renderRoutePreview() {
  if (!els.routePreview) {
    return;
  }
  const preview = state.routePreview;
  if (!preview) {
    clearRoutePreview();
    return;
  }
  const route = String(preview.route || "none");
  const reason = reasonLabel(preview.reason);
  const preference = memoryPreferenceLabel(preview.memory_preference || "auto");
  const riskTag = preview.high_risk ? "high-risk" : "normal";
  const signalTag = preview.memory_signal ? "memory-signal" : "no-signal";
  const modeTag = `predicted=${String(preview.predicted_memory_mode || "none")}`;
  const stmHits = Number(preview.stm_hit_count || 0);
  const stmScore = Number(preview.stm_best_score || 0);
  const stmTag = `stm=${stmHits} @ ${stmScore.toFixed(2)}`;
  const ltmTag = preview.will_query_ltm ? "ltm=query" : "ltm=skip";
  const reasonText = String(preview.reason_text || reason || "").trim();
  const plainOutcome = preview.will_query_ltm
    ? "Memory lookup will run for this turn."
    : "No long-memory lookup for this turn.";
  const plainMode = preview.predicted_memory_mode === "none"
    ? "Chat-focused response path."
    : `Response path: ${String(preview.predicted_memory_mode || "none").replaceAll("_", " ")}`;
  const technicalTags = isSimpleMode()
    ? ""
    : `<span>${escapeHtml(riskTag)}</span>` +
      `<span>${escapeHtml(signalTag)}</span>` +
      `<span>${escapeHtml(modeTag)}</span>` +
      `<span>${escapeHtml(stmTag)}</span>` +
      `<span>${escapeHtml(ltmTag)}</span>`;
  els.routePreview.classList.remove("empty");
  els.routePreview.innerHTML =
    `<div class="route-preview-top">` +
    `<span class="route-chip route-${escapeHtml(route)}">${escapeHtml(routeLabel(route))}</span>` +
    `<strong>${escapeHtml(reasonText)}</strong>` +
    `</div>` +
    `<div class="route-preview-meta">` +
    `<span>mode=${escapeHtml(preference)}</span>` +
    `<span>${escapeHtml(plainOutcome)}</span>` +
    `<span>${escapeHtml(plainMode)}</span>` +
    technicalTags +
    `</div>`;
}

function trimDisplay(value, limit = 220) {
  const text = String(value || "").trim();
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, limit - 1)}…`;
}

function renderContextPreview() {
  if (!els.contextPanel) {
    return;
  }
  if (state.contextError) {
    els.contextPanel.classList.remove("empty");
    els.contextPanel.innerHTML = `<div class="warn">${escapeHtml(state.contextError)}</div>`;
    if (els.contextRaw) {
      els.contextRaw.textContent = "";
    }
    return;
  }
  const pack = state.contextPackage;
  if (!pack) {
    clearContextPreview();
    return;
  }
  const preview = pack.preview || {};
  const workingSet = pack.working_set || {};
  const plan = pack.ltm_query_plan || {};
  const guidance = pack.responder_guidance || {};
  const cards = Array.isArray(workingSet.memory_cards) ? workingSet.memory_cards : [];
  const notes = Array.isArray(workingSet.top_notes) ? workingSet.top_notes : [];
  const cardList = cards.length
    ? `<ul class="context-list">` +
      cards
        .slice(0, 4)
        .map((card) => {
          const summary = trimDisplay(card.summary || card.text || "");
          const citations = Array.isArray(card.citations) ? card.citations.length : 0;
          const confidence = Number(card.confidence || 0).toFixed(2);
          return `<li>${escapeHtml(summary)} <span class="context-label">(conf=${confidence} cites=${citations})</span></li>`;
        })
        .join("") +
      `</ul>`
    : `<div class="context-label">No memory cards included in this package.</div>`;
  const noteList = notes.length
    ? `<ul class="context-list">` +
      notes
        .slice(0, 4)
        .map((item) => `<li>${escapeHtml(trimDisplay(item, 180))}</li>`)
        .join("") +
      `</ul>`
    : `<div class="context-label">No short-term notes selected.</div>`;

  els.contextPanel.classList.remove("empty");
  els.contextPanel.innerHTML =
    `<div class="context-grid">` +
    `<div class="context-row">` +
    `<div class="context-label">Route + Decision</div>` +
    `<div><strong>${escapeHtml(routeLabel(preview.route || "none"))}</strong> | ${escapeHtml(reasonLabel(preview.reason || ""))}</div>` +
    `<div class="context-meta">` +
    `<span class="context-pill">mode ${escapeHtml(String(plan.predicted_memory_mode || "none"))}</span>` +
    `<span class="context-pill">ltm ${plan.will_query_ltm ? "query" : "skip"}</span>` +
    `<span class="context-pill">passes ${escapeHtml(String(plan.max_passes ?? "-"))}</span>` +
    `<span class="context-pill">session ${escapeHtml(String(workingSet.session_id || "none"))}</span>` +
    `</div>` +
    `</div>` +
    `<div class="context-row">` +
    `<div class="context-label">Working Set</div>` +
    `<div>notes=${escapeHtml(String(workingSet.short_term_notes || 0))} hits=${escapeHtml(String(workingSet.short_term_hits || 0))}</div>` +
    `${noteList}` +
    `</div>` +
    `<div class="context-row">` +
    `<div class="context-label">Memory Cards</div>` +
    `${cardList}` +
    `</div>` +
    `<div class="context-row">` +
    `<div class="context-label">Responder Guidance</div>` +
    `<div class="context-meta">` +
    `<span class="context-pill">citations ${guidance.require_citations ? "required" : "optional"}</span>` +
    `<span class="context-pill">visible ${guidance.render_citations ? "on" : "off"}</span>` +
    `<span class="context-pill">abstain ${guidance.abstain_without_evidence ? "required" : "optional"}</span>` +
    `<span class="context-pill">preference ${escapeHtml(memoryPreferenceLabel(guidance.memory_preference || "auto"))}</span>` +
    `</div>` +
    `</div>` +
    `</div>`;
  if (els.contextRaw) {
    els.contextRaw.textContent = JSON.stringify(pack, null, 2);
  }
}

function renderSessions() {
  if (!els.sessionSelect) {
    return;
  }
  const options = state.sessions
    .map((session) => {
      const selected = session.session_id === state.activeSessionId ? " selected" : "";
      const label = `${session.label} (${session.turn_count})`;
      return `<option value="${escapeHtml(session.session_id)}"${selected}>${escapeHtml(label)}</option>`;
    })
    .join("");
  els.sessionSelect.innerHTML = options;
  if (!state.sessions.length) {
    els.sessionMeta.textContent = "No active thread.";
    return;
  }
  const active = state.sessions.find((item) => item.session_id === state.activeSessionId) || state.sessions[0];
  if (active && state.activeSessionId !== active.session_id) {
    state.activeSessionId = active.session_id;
  }
  const telemetry = state.sessionTelemetry;
  if (!active) {
    els.sessionMeta.textContent = "No active thread.";
    return;
  }
  const tele = telemetry && telemetry.session_id === active.session_id ? telemetry : null;
  if (tele) {
    const routeCounts = tele.route_counts || {};
    const preferenceCounts = tele.memory_preference_counts || {};
    els.sessionMeta.textContent =
      `${active.label} | turns=${tele.turn_count} | p95=${formatLatency(tele.p95_latency_ms)} | ` +
      `routes none:${routeCounts.none || 0} stm:${routeCounts.stm_only || 0} light:${routeCounts.ltm_light || 0} deep:${routeCounts.ltm_deep || 0} | ` +
      `prefs auto:${preferenceCounts.auto || 0} chat:${preferenceCounts.chat_first || 0} assist:${preferenceCounts.memory_assist || 0}`;
    return;
  }
  els.sessionMeta.textContent = `${active.label} | turns=${active.turn_count} | updated=${formatDate(active.updated_at)}`;
}

function renderRuntimeLedger() {
  if (!els.ledgerList || !els.ledgerMeta) {
    return;
  }
  const rows = Array.isArray(state.runtimeTelemetryTurns) ? state.runtimeTelemetryTurns : [];
  if (!rows.length) {
    els.ledgerMeta.textContent = "No turn telemetry yet.";
    els.ledgerList.classList.add("empty");
    els.ledgerList.textContent = "Ledger entries appear after turns run.";
    return;
  }
  const warnTurns = rows.filter((item) => String(item.warning_state || "ok") === "warn").length;
  els.ledgerMeta.textContent = `${rows.length} recent turns | warnings on ${warnTurns} turns`;
  els.ledgerList.classList.remove("empty");
  els.ledgerList.innerHTML = rows
    .map((item) => {
      const warningCodes = Array.isArray(item.warning_codes) ? item.warning_codes : [];
      const warningText = warningCodes.length ? warningCodes.join(", ") : "none";
      const warningClass = String(item.warning_state || "ok") === "warn" ? " warn" : "";
      return (
        `<article class="ledger-item${warningClass}">` +
        `<div class="ledger-topline">` +
        `<strong>${escapeHtml(String(item.turn_id || "-"))}</strong>` +
        `<span>${escapeHtml(formatDate(item.timestamp))}</span>` +
        `</div>` +
        `<div class="ledger-signals">` +
        `<span class="ledger-pill">${escapeHtml(routeLabel(item.memory_route || "none"))}</span>` +
        `<span class="ledger-pill">${escapeHtml(String(item.decision || "-"))}</span>` +
        `<span class="ledger-pill">${escapeHtml(memoryPreferenceLabel(item.memory_preference || "auto"))}</span>` +
        `<span class="ledger-pill">${escapeHtml(`${Math.round(Number(item.latency_ms || 0))}ms`)}</span>` +
        `<span class="ledger-pill">${escapeHtml(formatMoney(item.turn_cost_usd || 0))}</span>` +
        `</div>` +
        `<div class="ledger-meta">why=${escapeHtml(reasonLabel(item.route_reason || ""))}</div>` +
        `<div class="ledger-meta">warnings=${escapeHtml(warningText)}</div>` +
        `</article>`
      );
    })
    .join("");
}

function renderTurns() {
  els.chatLog.innerHTML = "";
  if (!state.turns.length) {
    els.chatLog.innerHTML = '<div class="memory-empty">No turns in this thread yet.</div>';
    return;
  }
  for (const turn of state.turns) {
    const fragment = els.turnTemplate.content.cloneNode(true);
    const button = fragment.querySelector(".turn-button");
    const meta = fragment.querySelector(".turn-meta");
    const routeBadge = fragment.querySelector(".route-badge");
    const decisionBadge = fragment.querySelector(".decision-badge");
    const text = fragment.querySelector(".turn-text");
    meta.textContent = `${formatDate(turn.timestamp)} | ${turn.turn_id}`;
    routeBadge.textContent = routeLabel(turn.memory_route);
    routeBadge.classList.add(`route-${String(turn.memory_route || "none")}`);
    decisionBadge.textContent = String(turn.decision || "-").toLowerCase();
    decisionBadge.classList.add(`decision-${String(turn.decision || "unknown").toLowerCase()}`);
    text.textContent = `Q: ${turn.user_text}\nA: ${turn.response_text}`;
    button.dataset.turnId = turn.turn_id;
    button.addEventListener("click", () => {
      state.selectedTurnId = turn.turn_id;
      renderTrace();
      refreshWhyPanel().catch((error) => showTraceError(error.message));
    });
    els.chatLog.appendChild(fragment);
  }
}

function renderTrace() {
  if (!state.selectedTurnId) {
    els.tracePanel.classList.add("empty");
    els.tracePanel.textContent = "Select a turn to inspect evidence details.";
    return;
  }
  const turn = state.turns.find((item) => item.turn_id === state.selectedTurnId);
  if (!turn) {
    els.tracePanel.classList.add("empty");
    els.tracePanel.textContent = "Selected turn not available.";
    return;
  }
  els.traceHint.textContent = turn.turn_id;
  els.tracePanel.classList.remove("empty");
  const checks = (turn.claim_checks || [])
    .map(
      (item) =>
        `<div class="trace-row"><div class="trace-label">claim check</div>${escapeHtml(item.claim)}\n` +
        `supported=${escapeHtml(item.supported)} confidence=${Number(item.confidence || 0).toFixed(2)} reason=${escapeHtml(item.reason)}\n` +
        `citations=${escapeHtml((item.citations || []).join(", ") || "none")}</div>`
    )
    .join("");
  const cards = (turn.memory_cards || [])
    .map(
      (card) =>
        `<div class="trace-row"><div class="trace-label">memory card (${escapeHtml(card.kind || "unknown")})</div>` +
        `${escapeHtml(card.summary || "")}` +
        `\nconfidence=${Number(card.confidence || 0).toFixed(2)} contradiction=${escapeHtml(card.contradiction || false)}` +
        `\ncitations=${escapeHtml((card.citations || []).join(", ") || "none")}</div>`
    )
    .join("");
  const citations = escapeHtml((turn.citations || []).join(", ") || "none");
  const budget = turn.budget || {};
  const budgetUsage = budget.usage || {};
  const budgetLimits = budget.limits || {};
  const warnings = Array.isArray(budget.warnings) ? budget.warnings : [];
  const warningState = String(budget.warning_state || "ok");
  const warningLines = warnings
    .map((item) => `${String(item.code || "WARN")}: ${String(item.message || "")}`.trim())
    .filter(Boolean)
    .join("\n");
  const warningSummary = warnings.length
    ? "Runtime guardrails flagged this turn. Reply was still returned with safety limits."
    : "";

  const html =
    `<div class="trace-row"><div class="trace-label">decision</div>${escapeHtml(turn.decision)}</div>` +
    `<div class="trace-row"><div class="trace-label">plain summary</div>${escapeHtml(decisionPlainLanguage(turn.decision))}</div>` +
    `<div class="trace-row"><div class="trace-label">memory route</div>${escapeHtml(routeLabel(turn.memory_route))}</div>` +
    `<div class="trace-row"><div class="trace-label">why memory</div>${escapeHtml(reasonDetail(turn))}</div>` +
    `<div class="trace-row"><div class="trace-label">memory preference</div>${escapeHtml(memoryPreferenceLabel(turn.memory_preference || "auto"))}</div>` +
    `<div class="trace-row"><div class="trace-label">retrieval</div>passes=${Number(turn.retrieval_passes || 0)} query_tokens=${Number(turn.retrieval_query_tokens || 0)} stop=${escapeHtml(turn.retrieval_stop_reason || "-")}</div>` +
    `<div class="trace-row"><div class="trace-label">budget</div>` +
    `state=${escapeHtml(warningState)} ` +
    `retrieval=${Math.round(Number(budgetUsage.retrieval_followup_time_ms || 0))}/${Math.round(Number(budgetLimits.retrieval_followup_time_ms || 0))}ms ` +
    `turn_tokens=${Number(budgetUsage.turn_tokens || 0)}/${Number(budgetLimits.turn_tokens || 0)} ` +
    `latency=${Math.round(Number(budgetUsage.turn_latency_ms || 0))}/${Math.round(Number(budgetLimits.turn_latency_ms || 0))}ms ` +
    `cost=${formatMoney(budgetUsage.turn_cost_usd || 0)}/${formatMoney(budgetLimits.turn_cost_usd || 0)}` +
    `</div>` +
    (warningLines
      ? `<div class="trace-row"><div class="trace-label">guardrail warnings</div><span class="warn">${escapeHtml(warningSummary)}\n${escapeHtml(warningLines)}</span></div>`
      : "") +
    `<div class="trace-row"><div class="trace-label">pack confidence</div>${Number(turn.pack_confidence || 0).toFixed(2)}</div>` +
    `<div class="trace-row"><div class="trace-label">citations</div>${citations}</div>` +
    `<div class="trace-row"><div class="trace-label">latency</div>${formatLatency(turn.telemetry.total_ms)}</div>` +
    `<div class="trace-row"><div class="trace-label">cost</div>${formatMoney(turn.telemetry.turn_cost_usd)}</div>` +
    cards +
    checks;
  els.tracePanel.innerHTML = html;
}

function renderMemoryList() {
  if (!els.memoryList) {
    return;
  }
  const selected = state.selectedCardId;
  if (!state.memoryCards.length) {
    els.memoryList.innerHTML = '<div class="memory-empty">No memory cards matched this filter.</div>';
    return;
  }
  const rows = state.memoryCards
    .map((card) => {
      const selectedClass = selected === card.card_id ? " selected" : "";
      const contradictionBadge = card.contradiction ? " contradiction" : "";
      return (
        `<button type="button" class="memory-item${selectedClass}" data-card-id="${escapeHtml(card.card_id)}">` +
        `<div class="memory-item-head"><strong>${escapeHtml(card.card_id)}</strong><span class="memory-kind">${escapeHtml(card.kind || "-")}</span></div>` +
        `<div class="memory-item-text">${escapeHtml(card.summary || "")}</div>` +
        `<div class="memory-item-meta">status=${escapeHtml(card.atom_status || "-")} confidence=${Number(card.confidence || 0).toFixed(2)} citations=${Number(card.citation_count || 0)}</div>` +
        `<div class="memory-item-flags"><span class="memory-flag${contradictionBadge}">${card.contradiction ? "contradiction" : "stable"}</span></div>` +
        "</button>"
      );
    })
    .join("");
  els.memoryList.innerHTML = rows;
  for (const node of els.memoryList.querySelectorAll(".memory-item")) {
    node.addEventListener("click", () => {
      const cardId = node.getAttribute("data-card-id") || "";
      if (cardId) {
        loadCardDetail(cardId).catch((error) => renderMemoryError(error.message));
      }
    });
  }
}

function renderMemoryError(message) {
  if (!els.memoryDetail) {
    return;
  }
  state.memoryError = message;
  els.memoryDetail.classList.remove("empty");
  els.memoryDetail.innerHTML = `<div class="warn">${escapeHtml(message)}</div>`;
}

function renderMemoryDetail() {
  if (!els.memoryDetail) {
    return;
  }
  const detail = state.selectedCardDetail;
  if (!detail) {
    els.memoryDetail.classList.add("empty");
    els.memoryDetail.textContent = "Select a memory card to inspect evidence, provenance, and graph links.";
    return;
  }
  const card = detail.card || {};
  const atom = detail.atom || {};
  const events = Array.isArray(detail.provenance_events) ? detail.provenance_events : [];
  const graph = detail.graph || {};
  const eventHtml = events.length
    ? events
        .map(
          (evt) =>
            `<div class="memory-event"><span>${escapeHtml(evt.event_type || "")}</span>` +
            `<span>${escapeHtml(formatDate(evt.timestamp))}</span>` +
            `<span>${escapeHtml(evt.reason || "")}</span></div>`
        )
        .join("")
    : '<div class="memory-empty">No provenance events recorded.</div>';

  const graphList = [
    ...(graph.conflicts || []).map((id) => `conflict -> ${id}`),
    ...(graph.constellation_neighbors || []).map((id) => `constellation -> ${id}`),
    ...(graph.arc_neighbors || []).map((id) => `narrative_arc -> ${id}`),
  ];
  const graphHtml = graphList.length
    ? `<ul class="memory-links">${graphList.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
    : '<div class="memory-empty">No linked neighbors for this atom yet.</div>';
  const citations = Array.isArray(card.citations) && card.citations.length
    ? `<ul class="memory-links">${card.citations.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : '<div class="memory-empty">No citations for this card.</div>';

  els.memoryDetail.classList.remove("empty");
  els.memoryDetail.innerHTML =
    `<div class="memory-detail-head"><strong>${escapeHtml(card.card_id || "")}</strong>` +
    `<span>${escapeHtml(card.kind || atom.atom_type || "")}</span></div>` +
    `<div class="memory-detail-text">${escapeHtml(card.summary || atom.canonical_text || "")}</div>` +
    `<div class="memory-detail-meta">status=${escapeHtml(atom.status || card.atom_status || "")} confidence=${Number(card.confidence || atom.confidence || 0).toFixed(2)} contradiction=${Boolean(card.contradiction)}</div>` +
    `<div class="memory-section"><h4>Citations</h4>${citations}</div>` +
    `<div class="memory-section"><h4>Graph</h4>${graphHtml}</div>` +
    `<div class="memory-section"><h4>Conflict Marking</h4>` +
    `<div class="memory-conflict-form">` +
    `<input id="memoryConflictAtomId" class="input" type="text" placeholder="Other atom id" />` +
    `<input id="memoryConflictReason" class="input" type="text" value="manual_conflict_from_ui" placeholder="Reason" />` +
    `<button id="btnMemoryMarkConflict" class="btn ghost" type="button">Mark Conflict</button>` +
    `</div></div>` +
    `<div class="memory-section"><h4>Provenance</h4>${eventHtml}</div>`;
  document.getElementById("btnMemoryMarkConflict")?.addEventListener("click", () => {
    markAtomConflict().catch((error) => renderMemoryError(error.message));
  });
}

function atomIdFromCardId(cardId) {
  const raw = String(cardId || "").trim();
  if (raw.startsWith("card_")) {
    return raw.slice(5);
  }
  return raw;
}

function summarizeGraphNode(node) {
  const text = String(node?.summary || "").trim();
  if (!text) {
    return String(node?.atom_id || "");
  }
  return text.length > 20 ? `${text.slice(0, 20).trim()}…` : text;
}

function splitGraphComponents(nodes, links) {
  const adjacency = new Map();
  for (const node of nodes) {
    adjacency.set(String(node.atom_id), new Set());
  }
  for (const link of links) {
    const source = String(link.source || "");
    const target = String(link.target || "");
    if (!adjacency.has(source) || !adjacency.has(target)) {
      continue;
    }
    adjacency.get(source).add(target);
    adjacency.get(target).add(source);
  }
  const visited = new Set();
  const components = [];
  for (const node of nodes) {
    const atomId = String(node.atom_id);
    if (visited.has(atomId)) {
      continue;
    }
    const queue = [atomId];
    visited.add(atomId);
    const component = [];
    while (queue.length) {
      const current = queue.shift();
      component.push(current);
      for (const neighbor of adjacency.get(current) || []) {
        if (visited.has(neighbor)) {
          continue;
        }
        visited.add(neighbor);
        queue.push(neighbor);
      }
    }
    components.push(component);
  }
  return components;
}

function computeGraphLayout(nodes, links, width, height) {
  const safeWidth = Math.max(320, Number(width || 1000));
  const safeHeight = Math.max(220, Number(height || 540));
  const layout = new Map();
  if (!nodes.length) {
    return layout;
  }
  if (nodes.length === 1) {
    layout.set(String(nodes[0].atom_id), { x: safeWidth * 0.5, y: safeHeight * 0.5 });
    return layout;
  }
  const components = splitGraphComponents(nodes, links);
  const centerX = safeWidth * 0.5;
  const centerY = safeHeight * 0.5;
  const orbit = Math.max(40, Math.min(safeWidth, safeHeight) * 0.3);
  components.forEach((component, idx) => {
    const angle = (Math.PI * 2 * idx) / Math.max(1, components.length);
    const componentX = centerX + orbit * Math.cos(angle);
    const componentY = centerY + orbit * Math.sin(angle);
    const localRadius = Math.max(26, 18 + component.length * 5);
    component.forEach((atomId, localIdx) => {
      const localAngle = (Math.PI * 2 * localIdx) / Math.max(1, component.length);
      const x = componentX + localRadius * Math.cos(localAngle);
      const y = componentY + localRadius * Math.sin(localAngle);
      layout.set(String(atomId), {
        x: Math.max(16, Math.min(safeWidth - 16, x)),
        y: Math.max(16, Math.min(safeHeight - 16, y)),
      });
    });
  });
  return layout;
}

function renderMemoryGraphDetail() {
  if (!els.memoryGraphDetail) {
    return;
  }
  const selectedId = String(state.selectedGraphAtomId || "").trim();
  const nodes = Array.isArray(state.memoryGraph.nodes) ? state.memoryGraph.nodes : [];
  if (!selectedId) {
    els.memoryGraphDetail.classList.add("empty");
    els.memoryGraphDetail.textContent = "Select a map node to inspect quick graph details.";
    return;
  }
  const node = nodes.find((item) => String(item.atom_id) === selectedId);
  if (!node) {
    els.memoryGraphDetail.classList.add("empty");
    els.memoryGraphDetail.textContent = "Selected node is no longer in this filtered map.";
    return;
  }
  const links = Array.isArray(state.memoryGraph.links) ? state.memoryGraph.links : [];
  const linked = links.filter((link) => String(link.source) === selectedId || String(link.target) === selectedId);
  const kinds = [...new Set(linked.map((link) => String(link.kind || "link")))];
  els.memoryGraphDetail.classList.remove("empty");
  els.memoryGraphDetail.innerHTML =
    `<strong>${escapeHtml(String(node.card_id || selectedId))}</strong>` +
    `<div>${escapeHtml(String(node.summary || ""))}</div>` +
    `<div class="meta">kind=${escapeHtml(String(node.kind || "-"))} status=${escapeHtml(String(node.status || "-"))} confidence=${Number(node.confidence || 0).toFixed(2)}</div>` +
    `<div class="meta">degree=${Number(node.degree || linked.length)} links=${linked.length} link_types=${escapeHtml(kinds.join(", ") || "none")}</div>`;
}

function renderMemoryGraph() {
  if (!els.memoryGraphSvg || !els.memoryGraphMeta) {
    return;
  }
  const nodes = Array.isArray(state.memoryGraph.nodes) ? state.memoryGraph.nodes : [];
  const links = Array.isArray(state.memoryGraph.links) ? state.memoryGraph.links : [];
  const truncated = !!state.memoryGraph.truncated;
  const total = Number(state.memoryGraph.total || nodes.length);
  const snapshotAvailable = state.memoryGraph.snapshotAvailable !== false;
  els.memoryGraphMeta.textContent =
    `${nodes.length} nodes • ${links.length} links${truncated ? ` • truncated from ${total}` : ""}` +
    `${snapshotAvailable ? "" : " • snapshot unavailable (showing conflict links only)"}`;

  if (!nodes.length) {
    els.memoryGraphSvg.innerHTML =
      '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" fill="#5a6972" font-family="Courier New, Courier, monospace" font-size="13">No map nodes for current memory filters.</text>';
    renderMemoryGraphDetail();
    return;
  }

  const viewBox = els.memoryGraphSvg.viewBox.baseVal;
  const width = Number(viewBox?.width || 1000);
  const height = Number(viewBox?.height || 540);
  const layout = computeGraphLayout(nodes, links, width, height);
  const selectedId = String(state.selectedGraphAtomId || "");
  const nodeById = new Map(nodes.map((item) => [String(item.atom_id), item]));

  const linkSvg = links
    .map((link) => {
      const source = layout.get(String(link.source || ""));
      const target = layout.get(String(link.target || ""));
      if (!source || !target) {
        return "";
      }
      const kind = String(link.kind || "link");
      const kindClass = kind.toLowerCase().replaceAll("_", "-").replace(/[^a-z0-9-]/g, "-");
      return `<line class="graph-link kind-${escapeHtml(kindClass)}" x1="${source.x.toFixed(2)}" y1="${source.y.toFixed(2)}" x2="${target.x.toFixed(2)}" y2="${target.y.toFixed(2)}"></line>`;
    })
    .join("");

  const nodeSvg = nodes
    .map((node) => {
      const atomId = String(node.atom_id || "");
      const point = layout.get(atomId);
      if (!point) {
        return "";
      }
      const selectedClass = selectedId === atomId ? " selected" : "";
      const kindClass = ` kind-${String(node.kind || "").toLowerCase().replaceAll("_", "-").replace(/[^a-z0-9-]/g, "-")}`;
      const statusClass = ` status-${String(node.status || "").toLowerCase().replaceAll("_", "-").replace(/[^a-z0-9-]/g, "-")}`;
      const radius = 6 + Math.min(8, Number(node.degree || 0));
      const label = summarizeGraphNode(node);
      return (
        `<g class="graph-node${selectedClass}${kindClass}${statusClass}" data-atom-id="${escapeHtml(atomId)}">` +
        `<circle cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="${radius.toFixed(2)}"></circle>` +
        `<text x="${(point.x + radius + 4).toFixed(2)}" y="${(point.y + 3).toFixed(2)}">${escapeHtml(label)}</text>` +
        `</g>`
      );
    })
    .join("");

  els.memoryGraphSvg.innerHTML = `${linkSvg}${nodeSvg}`;
  for (const item of els.memoryGraphSvg.querySelectorAll(".graph-node")) {
    item.addEventListener("click", () => {
      const atomId = String(item.getAttribute("data-atom-id") || "").trim();
      if (!atomId) {
        return;
      }
      state.selectedGraphAtomId = atomId;
      renderMemoryGraph();
      renderMemoryGraphDetail();
      const cardId = nodeById.get(atomId)?.card_id;
      if (cardId) {
        loadCardDetail(cardId).catch((error) => renderMemoryError(error.message));
      }
    });
  }
  renderMemoryGraphDetail();
}

function renderProposals() {
  if (!els.proposalList) {
    return;
  }
  if (state.proposalsStatus === "queue_unavailable") {
    els.proposalList.innerHTML = '<div class="memory-empty">Proposal queue is not configured for this runtime.</div>';
    return;
  }
  if (!state.proposals.length) {
    els.proposalList.innerHTML = '<div class="memory-empty">No proposals queued.</div>';
    return;
  }
  els.proposalList.innerHTML = state.proposals
    .map(
      (proposal) =>
        `<div class="proposal-item" data-proposal-id="${escapeHtml(proposal.proposal_id)}">` +
        `<div class="proposal-headline"><strong>${escapeHtml(proposal.proposal_id)}</strong><span>${escapeHtml(proposal.status)}</span></div>` +
        `<div class="proposal-meta">${escapeHtml(proposal.action)} -> ${escapeHtml(proposal.target_atom_id)}</div>` +
        `<div class="proposal-meta">reason=${escapeHtml(proposal.reason_code)}</div>` +
        `<div class="proposal-actions">` +
        `<button type="button" class="btn ghost proposal-approve" ${proposal.status !== "pending" || state.proposalBusyId === proposal.proposal_id ? "disabled" : ""}>Approve</button>` +
        `<button type="button" class="btn ghost proposal-reject" ${proposal.status !== "pending" || state.proposalBusyId === proposal.proposal_id ? "disabled" : ""}>Reject</button>` +
        `</div>` +
        `</div>`
    )
    .join("");

  for (const node of els.proposalList.querySelectorAll(".proposal-item")) {
    const proposalId = node.getAttribute("data-proposal-id") || "";
    const approveBtn = node.querySelector(".proposal-approve");
    const rejectBtn = node.querySelector(".proposal-reject");
    if (approveBtn) {
      approveBtn.addEventListener("click", () => approveProposal(proposalId));
    }
    if (rejectBtn) {
      rejectBtn.addEventListener("click", () => rejectProposal(proposalId));
    }
  }
}

async function refreshMemory() {
  const requestSeq = state.memoryRequestSeq + 1;
  state.memoryRequestSeq = requestSeq;
  const query = (els.memorySearch?.value || "").trim();
  const kind = (els.memoryKind?.value || "all").trim();
  const status = (els.memoryStatus?.value || "all").trim();
  const contradiction = (els.memoryContradiction?.value || "all").trim();
  const params = new URLSearchParams();
  if (query) {
    params.set("q", query);
  }
  if (kind && kind !== "all") {
    params.set("kind", kind);
  }
  if (status && status !== "all") {
    params.set("status", status);
  }
  if (contradiction && contradiction !== "all") {
    params.set("contradiction", contradiction);
  }
  params.set("limit", "120");
  const payload = await jsonFetch(`/api/memory/cards?${params.toString()}`);
  if (requestSeq !== state.memoryRequestSeq) {
    return;
  }
  state.memoryCards = payload.cards || [];
  renderMemoryList();
  if (state.selectedCardId && !state.memoryCards.some((card) => card.card_id === state.selectedCardId)) {
    state.selectedCardId = null;
    state.selectedCardDetail = null;
  }
  renderMemoryDetail();
  await refreshMemoryGraph();
}

async function loadCardDetail(cardId) {
  const requestSeq = state.cardDetailRequestSeq + 1;
  state.cardDetailRequestSeq = requestSeq;
  state.selectedCardId = cardId;
  state.selectedCardDetail = null;
  renderMemoryList();
  renderMemoryDetail();
  const payload = await jsonFetch(`/api/memory/cards/${encodeURIComponent(cardId)}`);
  if (requestSeq !== state.cardDetailRequestSeq || state.selectedCardId !== cardId || !state.selectedCardId) {
    return;
  }
  state.selectedCardDetail = payload;
  state.selectedGraphAtomId = atomIdFromCardId(cardId);
  renderMemoryGraph();
  renderMemoryGraphDetail();
  renderMemoryDetail();
}

async function markAtomConflict() {
  const detail = state.selectedCardDetail;
  const atom = detail?.atom || {};
  const atomId = String(atom.atom_id || "").trim();
  if (!atomId) {
    throw new Error("Select an atom card before marking conflict.");
  }
  const otherAtomId = (document.getElementById("memoryConflictAtomId")?.value || "").trim();
  if (!otherAtomId) {
    throw new Error("Provide the other atom id to mark conflict.");
  }
  const reason = (document.getElementById("memoryConflictReason")?.value || "").trim() || "manual_conflict_from_ui";
  await jsonFetch(`/api/memory/atoms/${encodeURIComponent(atomId)}/conflict`, {
    method: "POST",
    body: JSON.stringify({
      other_atom_id: otherAtomId,
      reason,
    }),
  });
  renderMemoryError(`Conflict marked: ${atomId} ↔ ${otherAtomId}`);
  await refreshMemory();
  await refreshMemoryGraph();
  if (state.selectedCardId) {
    await loadCardDetail(state.selectedCardId);
  }
}

async function refreshMemoryGraph() {
  const requestSeq = state.memoryGraphRequestSeq + 1;
  state.memoryGraphRequestSeq = requestSeq;
  const query = (els.memorySearch?.value || "").trim();
  const kind = (els.memoryKind?.value || "all").trim();
  const status = (els.memoryStatus?.value || "all").trim();
  const contradiction = (els.memoryContradiction?.value || "all").trim();
  const params = new URLSearchParams();
  if (query) {
    params.set("q", query);
  }
  if (kind && kind !== "all") {
    params.set("kind", kind);
  }
  if (status && status !== "all") {
    params.set("status", status);
  }
  if (contradiction && contradiction !== "all") {
    params.set("contradiction", contradiction);
  }
  params.set("limit", "220");
  const payload = await jsonFetch(`/api/memory/graph-map?${params.toString()}`);
  if (requestSeq !== state.memoryGraphRequestSeq) {
    return;
  }
  state.memoryGraph = {
    nodes: payload.nodes || [],
    links: payload.links || [],
    total: Number(payload.total || 0),
    truncated: !!payload.truncated,
    snapshotAvailable: payload.snapshot_available !== false,
  };
  if (state.selectedCardId) {
    state.selectedGraphAtomId = atomIdFromCardId(state.selectedCardId);
  }
  if (
    state.selectedGraphAtomId &&
    !state.memoryGraph.nodes.some((node) => String(node.atom_id) === String(state.selectedGraphAtomId))
  ) {
    state.selectedGraphAtomId = null;
  }
  if (!state.selectedGraphAtomId && state.memoryGraph.nodes.length) {
    state.selectedGraphAtomId = String(state.memoryGraph.nodes[0].atom_id);
  }
  renderMemoryGraph();
}

async function refreshProposals() {
  const payload = await jsonFetch("/api/memory/proposals");
  state.proposals = payload.proposals || [];
  state.proposalsStatus = payload.status || "ok";
  renderProposals();
}

async function approveProposal(proposalId) {
  if (!window.confirm(`Approve proposal ${proposalId}? This may apply a destructive memory mutation.`)) {
    return;
  }
  state.proposalBusyId = proposalId;
  renderProposals();
  try {
    await jsonFetch(`/api/memory/proposals/${encodeURIComponent(proposalId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ reviewer: "runtime_ui", apply: true }),
    });
    await Promise.all([refreshMemory(), refreshProposals()]);
  } catch (error) {
    renderMemoryError(error.message);
  } finally {
    state.proposalBusyId = null;
    renderProposals();
  }
}

async function rejectProposal(proposalId) {
  if (!window.confirm(`Reject proposal ${proposalId}?`)) {
    return;
  }
  state.proposalBusyId = proposalId;
  renderProposals();
  try {
    await jsonFetch(`/api/memory/proposals/${encodeURIComponent(proposalId)}/reject`, {
      method: "POST",
      body: JSON.stringify({ reviewer: "runtime_ui", reason: "rejected_from_ui" }),
    });
    await refreshProposals();
  } catch (error) {
    renderMemoryError(error.message);
  } finally {
    state.proposalBusyId = null;
    renderProposals();
  }
}

async function refreshSessions() {
  const payload = await jsonFetch("/api/chat/sessions");
  state.sessions = payload.sessions || [];
  if (state.sessions.length && !state.activeSessionId) {
    state.activeSessionId = state.sessions[0].session_id;
  }
  if (state.activeSessionId && !state.sessions.some((item) => item.session_id === state.activeSessionId)) {
    state.activeSessionId = state.sessions.length ? state.sessions[0].session_id : null;
  }
  renderSessions();
}

async function refreshActiveSessionData() {
  if (!state.activeSessionId) {
    state.turns = [];
    state.sessionTelemetry = null;
    renderTurns();
    renderTrace();
    return;
  }
  const sessionId = state.activeSessionId;
  const [historyPayload, telemetryPayload] = await Promise.all([
    jsonFetch(`/api/chat/session/${encodeURIComponent(sessionId)}/history`),
    jsonFetch(`/api/chat/session/${encodeURIComponent(sessionId)}/telemetry`),
  ]);
  if (sessionId !== state.activeSessionId) {
    return;
  }
  state.turns = historyPayload.history || [];
  state.sessionTelemetry = telemetryPayload.telemetry || null;
  if (state.selectedTurnId && !state.turns.some((turn) => turn.turn_id === state.selectedTurnId)) {
    state.selectedTurnId = null;
  }
  if (!state.selectedTurnId && state.turns.length) {
    state.selectedTurnId = state.turns[state.turns.length - 1].turn_id;
  }
  renderTurns();
  renderTrace();
  renderSessions();
  await refreshWhyPanel();
}

async function refreshState() {
  const payload = await jsonFetch("/api/state");
  renderMetrics(payload);
}

async function refreshRuntimeLedger() {
  const payload = await jsonFetch("/api/runtime/telemetry/turns?limit=40");
  state.runtimeTelemetryTurns = payload.turns || [];
  renderRuntimeLedger();
}

async function refreshSessionAndState() {
  await Promise.all([refreshState(), refreshSessions()]);
  await Promise.all([refreshActiveSessionData(), refreshRuntimeLedger()]);
}

async function ensureActiveSession() {
  if (state.activeSessionId) {
    return state.activeSessionId;
  }
  const payload = await jsonFetch("/api/chat/session/start", {
    method: "POST",
    body: JSON.stringify({ label: "Primary" }),
  });
  state.activeSessionId = payload.session.session_id;
  await refreshSessions();
  return state.activeSessionId;
}

async function startSession() {
  const label = (els.sessionLabel?.value || "").trim() || undefined;
  const payload = await jsonFetch("/api/chat/session/start", {
    method: "POST",
    body: JSON.stringify({ label }),
  });
  state.activeSessionId = payload.session.session_id;
  if (els.sessionLabel) {
    els.sessionLabel.value = "";
  }
  clearRoutePreview();
  await refreshSessionAndState();
}

async function sendTurn(event) {
  event.preventDefault();
  const message = (els.chatInput.value || "").trim();
  if (!message) {
    return;
  }
  els.chatInput.disabled = true;
  try {
    const sessionId = await ensureActiveSession();
    const highRisk = !!(els.highRisk?.checked);
    const retrievalQuery = (settings.retrievalQuery || "").trim();
    const retrievalOverride = retrievalQuery
      ? {
          query: retrievalQuery,
          invoker: "engine.runtime.ui",
          reason: "manual_debug_override",
          scope: "runtime_ui",
        }
      : undefined;
    await jsonFetch(`/api/chat/session/${encodeURIComponent(sessionId)}/turn`, {
      method: "POST",
      body: JSON.stringify({
        message,
        high_risk: highRisk,
        retrieval_override: retrievalOverride,
        memory_preference: settings.memoryPreference || "auto",
      }),
    });
    els.chatInput.value = "";
    clearRoutePreview();
    clearContextPreview();
    await Promise.all([refreshSessionAndState(), refreshMemory()]);
    await refreshWhyPanel();
  } catch (error) {
    showTraceError(error.message);
  } finally {
    els.chatInput.disabled = false;
    els.chatInput.focus();
  }
}

async function previewTurnRoute() {
  const message = (els.chatInput?.value || "").trim();
  if (!message) {
    clearRoutePreview("Type a message to preview routing.");
    return;
  }
  const highRisk = !!(els.highRisk?.checked);
  const payload = await jsonFetch("/api/chat/route-preview", {
    method: "POST",
    body: JSON.stringify({
      message,
      high_risk: highRisk,
      memory_preference: settings.memoryPreference || "auto",
      session_id: state.activeSessionId || undefined,
    }),
  });
  state.routePreview = payload.preview || null;
  renderRoutePreview();
}

async function previewContextPackage() {
  const message = (els.chatInput?.value || "").trim();
  if (!message) {
    clearContextPreview("Type a message to preview context.");
    return;
  }
  const highRisk = !!(els.highRisk?.checked);
  const retrievalQuery = (settings.retrievalQuery || "").trim();
  const retrievalOverride = retrievalQuery
    ? {
        query: retrievalQuery,
        invoker: "engine.runtime.ui",
        reason: "manual_debug_override",
        scope: "runtime_ui",
        auth_context: "runtime_ui",
      }
    : undefined;
  const payload = await jsonFetch("/api/chat/context-package", {
    method: "POST",
    body: JSON.stringify({
      message,
      high_risk: highRisk,
      memory_preference: settings.memoryPreference || "auto",
      session_id: state.activeSessionId || undefined,
      retrieval_override: retrievalOverride,
    }),
  });
  state.contextPackage = payload.package || null;
  state.contextError = null;
  if (state.contextPackage && state.contextPackage.preview) {
    state.routePreview = state.contextPackage.preview;
    renderRoutePreview();
  }
  renderContextPreview();
}

function setMemoryScope(scope) {
  const normalized = scope === "episodes" ? "episodes" : "atoms";
  state.memoryScope = normalized;
  els.btnMemoryScopeAtoms?.classList.toggle("active", normalized === "atoms");
  els.btnMemoryScopeEpisodes?.classList.toggle("active", normalized === "episodes");
  if (els.btnMemoryScopeAtoms) {
    els.btnMemoryScopeAtoms.setAttribute("aria-selected", normalized === "atoms" ? "true" : "false");
  }
  if (els.btnMemoryScopeEpisodes) {
    els.btnMemoryScopeEpisodes.setAttribute("aria-selected", normalized === "episodes" ? "true" : "false");
  }
  els.atomsScopePane?.classList.toggle("active", normalized === "atoms");
  els.episodesScopePane?.classList.toggle("active", normalized === "episodes");
  if (els.atomsScopePane) {
    els.atomsScopePane.setAttribute("aria-hidden", normalized === "atoms" ? "false" : "true");
  }
  if (els.episodesScopePane) {
    els.episodesScopePane.setAttribute("aria-hidden", normalized === "episodes" ? "false" : "true");
  }
}

function handleMemoryScopeTabKeydown(event) {
  const tabs = [els.btnMemoryScopeAtoms, els.btnMemoryScopeEpisodes].filter(Boolean);
  if (!tabs.length) {
    return;
  }
  const key = String(event?.key || "");
  let nextIndex = -1;
  const activeIndex = Math.max(0, tabs.findIndex((item) => item === event.currentTarget));
  if (key === "ArrowRight") {
    nextIndex = (activeIndex + 1) % tabs.length;
  } else if (key === "ArrowLeft") {
    nextIndex = (activeIndex - 1 + tabs.length) % tabs.length;
  } else if (key === "Home") {
    nextIndex = 0;
  } else if (key === "End") {
    nextIndex = tabs.length - 1;
  } else {
    return;
  }
  event.preventDefault();
  const nextTab = tabs[nextIndex];
  if (!nextTab) {
    return;
  }
  nextTab.focus();
  const nextScope = nextTab === els.btnMemoryScopeEpisodes ? "episodes" : "atoms";
  setMemoryScope(nextScope);
  if (nextScope === "episodes") {
    refreshEpisodes().catch((error) => renderMemoryError(error.message));
  }
}

function stageLabel(stage) {
  return String(stage || "").replaceAll("_", " ");
}

function wizardResult(el, message, isWarn = false) {
  if (!el) {
    return;
  }
  el.innerHTML = isWarn ? `<span class="warn">${escapeHtml(message)}</span>` : escapeHtml(message);
}

function wizardLinks(el, links = []) {
  if (!el) {
    return;
  }
  if (!Array.isArray(links) || !links.length) {
    el.textContent = "No actionable links available for this step yet.";
    return;
  }
  const items = links
    .map((link) => {
      const label = String(link.label || link.id || "Open link");
      const apiPath = String(link.api_path || "").trim();
      if (!apiPath) {
        return "";
      }
      return `<a class="wizard-action-link" href="${escapeHtml(apiPath)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
    })
    .filter(Boolean)
    .join("");
  el.innerHTML = items || "No actionable links available for this step yet.";
}

function parseAliasPairs(rawText) {
  const raw = String(rawText || "").trim();
  if (!raw) {
    return [];
  }
  const rows = raw
    .split(/[\n,]+/g)
    .map((item) => item.trim())
    .filter(Boolean);
  const out = [];
  for (const row of rows) {
    const pair = row.includes(">") ? row.split(">") : row.split(":");
    if (!pair || pair.length < 2) {
      continue;
    }
    const alias = String(pair[0] || "").trim();
    const canonical = String(pair.slice(1).join(":") || "").trim();
    if (!alias || !canonical) {
      continue;
    }
    out.push({ alias, canonical });
  }
  return out;
}

function renderWizardState() {
  const payload = state.wizardState || {};
  const runId = String(payload.run_id || state.wizardRunId || "");
  if (els.wizardRunMeta) {
    if (!runId) {
      els.wizardRunMeta.textContent = "No wizard run loaded.";
    } else {
      const stage = stageLabel(payload.current_stage || "welcome_resume");
      const updated = formatDate(payload.updated_at || "");
      els.wizardRunMeta.textContent = `run=${runId} | stage=${stage} | updated=${updated}`;
    }
  }
  if (els.wizardArchivePath && !els.wizardArchivePath.value && payload.selected_input_archive_path) {
    els.wizardArchivePath.value = String(payload.selected_input_archive_path || "");
  }
  if (els.wizardStageRail) {
    const completed = new Set(Array.isArray(payload.completed_stages) ? payload.completed_stages : []);
    const current = String(payload.current_stage || "welcome_resume");
    const stageNodes = ["welcome_resume", "import", "build_episodes", "builder_curation", "review", "verify", "go_live"];
    els.wizardStageRail.innerHTML = stageNodes
      .map((item) => {
        const status = item === current ? "current" : completed.has(item) ? "done" : "pending";
        return `<span class="wizard-stage ${status}">${escapeHtml(stageLabel(item))}</span>`;
      })
      .join("");
  }
  const verifyPayload = payload.verify || {};
  if (els.wizardVerifyLinks && verifyPayload && Array.isArray(verifyPayload.actionable_links)) {
    wizardLinks(els.wizardVerifyLinks, verifyPayload.actionable_links);
  }
}

function renderWizardReviewList() {
  if (!els.wizardReviewList) {
    return;
  }
  if (!state.wizardReviewCards.length) {
    els.wizardReviewList.innerHTML = '<div class="memory-empty">No draft episode cards found for review.</div>';
    return;
  }
  els.wizardReviewList.innerHTML = state.wizardReviewCards
    .map((card) => {
      const episodeId = String(card.episode_id || "");
      const decision = String(card.review_decision || "pending");
      return (
        `<article class="wizard-review-item" data-episode-id="${escapeHtml(episodeId)}">` +
        `<div class="wizard-review-top"><strong>${escapeHtml(episodeId)}</strong><span>${escapeHtml(decision)}</span></div>` +
        `<div class="wizard-review-title">${escapeHtml(card.title || "(untitled episode)")}</div>` +
        `<div class="wizard-review-summary">${escapeHtml(trimDisplay(card.summary || "", 180))}</div>` +
        `<div class="wizard-review-actions">` +
        `<button type="button" class="btn ghost review-approve">Approve</button>` +
        `<button type="button" class="btn ghost review-edit">Edit</button>` +
        `<button type="button" class="btn ghost review-reject">Reject</button>` +
        `</div>` +
        `</article>`
      );
    })
    .join("");
  for (const node of els.wizardReviewList.querySelectorAll(".wizard-review-item")) {
    const episodeId = node.getAttribute("data-episode-id") || "";
    node.querySelector(".review-approve")?.addEventListener("click", () => {
      updateWizardReviewDecision(episodeId, "approved").catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
    });
    node.querySelector(".review-reject")?.addEventListener("click", () => {
      updateWizardReviewDecision(episodeId, "rejected").catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
    });
    node.querySelector(".review-edit")?.addEventListener("click", () => {
      const promptResult = window.prompt("Edited summary (leave blank to keep current):", "");
      if (promptResult === null) {
        return;
      }
      const editedSummary = String(promptResult || "").trim();
      if (!editedSummary) {
        return;
      }
      updateWizardReviewDecision(episodeId, "edited", { summary: editedSummary }).catch((error) =>
        wizardResult(els.wizardReviewResult, error.message, true)
      );
    });
  }
}

async function refreshWizardState(runId) {
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  const payload = await jsonFetch(`/api/wizard/state${query}`);
  state.wizardState = payload.state || null;
  state.wizardRunId = payload.current_run_id || payload.latest_run_id || null;
  renderWizardState();
  await loadWizardReviewCards();
}

async function startWizard(mode) {
  const payload = await jsonFetch("/api/wizard/start", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
  state.wizardState = payload.state || null;
  state.wizardRunId = payload.run_id || null;
  renderWizardState();
  wizardResult(els.wizardImportResult, `Wizard ${mode === "new" ? "started" : "resumed"}: ${state.wizardRunId || "-"}`);
  await loadWizardReviewCards();
}

async function validateWizardImport() {
  const archivePath = (els.wizardArchivePath?.value || "").trim();
  const payload = await jsonFetch("/api/wizard/import/validate", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      archive_path: archivePath || undefined,
    }),
  });
  const issueSummary = (payload.issues || []).length ? `issues=${(payload.issues || []).join("; ")}` : "no obvious issues";
  wizardResult(
    els.wizardImportResult,
    `Validation: ${payload.status} | conversations=${payload.conversation_count} messages=${payload.message_count} | ${issueSummary}`,
    payload.status !== "safe"
  );
  await refreshWizardState(state.wizardRunId || undefined);
}

async function runWizardImport() {
  const archivePath = (els.wizardArchivePath?.value || "").trim();
  const payload = await jsonFetch("/api/wizard/import/run", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      archive_path: archivePath || undefined,
    }),
  });
  wizardResult(
    els.wizardImportResult,
    `Import complete. store=${payload.store_path} report=${payload.reports?.json || "-"}`,
    false
  );
  await refreshWizardState(state.wizardRunId || undefined);
  await refreshMemory();
}

async function runWizardBuild() {
  const policyPreset = String(els.wizardBuildPolicy?.value || "strict");
  const payload = await jsonFetch("/api/wizard/build/run", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      policy_preset: policyPreset,
    }),
  });
  const counts = payload.counts || {};
  wizardResult(
    els.wizardBuildResult,
    `Build complete (${policyPreset}). promoted=${counts.promoted_count || 0} candidate=${counts.candidate_count || 0} rejected=${counts.rejected_count || 0}`
  );
  await refreshWizardState(state.wizardRunId || undefined);
  await refreshEpisodes();
}

async function saveBuilderProfile() {
  const payload = await jsonFetch("/api/wizard/builder/profile/save", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      name: (els.builderProfileName?.value || "").trim() || undefined,
      entities: {
        include: (els.builderEntityInclude?.value || "").trim(),
        exclude: (els.builderEntityExclude?.value || "").trim(),
        aliases: parseAliasPairs((els.builderEntityAliases?.value || "").trim()),
      },
      cues: {
        include: (els.builderCueInclude?.value || "").trim(),
        exclude: (els.builderCueExclude?.value || "").trim(),
      },
      domain_rules: {
        include: (els.builderDomainInclude?.value || "").trim(),
        exclude: (els.builderDomainExclude?.value || "").trim(),
      },
    }),
  });
  wizardResult(els.wizardBuilderResult, `Builder profile saved: ${payload.profile_id}`);
  await refreshWizardState(state.wizardRunId || undefined);
}

async function rebuildWithBuilderProfile() {
  await saveBuilderProfile();
  await runWizardBuild();
}

async function loadWizardReviewCards() {
  const runId = state.wizardRunId || "";
  const search = (els.wizardReviewSearch?.value || "").trim();
  const status = (els.wizardReviewStatus?.value || "all").trim();
  if (!runId) {
    state.wizardReviewCards = [];
    renderWizardReviewList();
    return;
  }
  const params = new URLSearchParams();
  params.set("run_id", runId);
  if (search) {
    params.set("q", search);
  }
  if (status && status !== "all") {
    params.set("status", status);
  }
  const payload = await jsonFetch(`/api/wizard/review/cards?${params.toString()}`);
  state.wizardReviewCards = payload.cards || [];
  renderWizardReviewList();
}

async function updateWizardReviewDecision(episodeId, decision, edits = {}) {
  await jsonFetch("/api/wizard/review/update", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      episode_id: episodeId,
      decision,
      ...edits,
    }),
  });
  wizardResult(els.wizardReviewResult, `Updated ${episodeId} -> ${decision}`);
  await loadWizardReviewCards();
}

async function compileWizardReview() {
  const payload = await jsonFetch("/api/wizard/review/compile", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      reviewer: "runtime_ui",
    }),
  });
  wizardResult(
    els.wizardReviewResult,
    `Reviewed set compiled. episodes=${payload.episode_count || 0} path=${payload.reviewed_path || "-"}`
  );
  await refreshWizardState(state.wizardRunId || undefined);
  await refreshEpisodes();
}

async function restoreWizardLastPublished() {
  const payload = await jsonFetch("/api/wizard/restore-last-published", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
    }),
  });
  const pointers = payload.published_pointers || {};
  wizardResult(
    els.wizardGoLiveResult,
    `Restored last published pointers. store=${pointers.store_path || "-"} episodes=${pointers.episodes_path || "-"}`
  );
  await refreshWizardState(state.wizardRunId || undefined);
  await Promise.all([refreshEpisodes(), refreshMemory()]);
}

function renderWizardVerifyResult(payload) {
  const checks = Array.isArray(payload?.checks) ? payload.checks : [];
  const status = String(payload?.status || "unknown");
  const checkSummary = checks
    .slice(0, 4)
    .map((item) => `${String(item.id || "-")}:${String(item.status || "-")}`)
    .join(" | ");
  wizardResult(
    els.wizardVerifyResult,
    `Verify status: ${status} (${checks.length} checks)${checkSummary ? ` | ${checkSummary}` : ""}`,
    status !== "Safe"
  );
  wizardLinks(els.wizardVerifyLinks, payload?.actionable_links || []);
}

async function runWizardVerify() {
  const payload = await jsonFetch("/api/wizard/verify/run", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
    }),
  });
  renderWizardVerifyResult(payload);
  await refreshWizardState(state.wizardRunId || undefined);
}

function renderWizardGoLiveResult(payload) {
  const adapters = Array.isArray(payload?.adapters) ? payload.adapters : [];
  wizardResult(els.wizardGoLiveResult, `Go live ready at ${payload.runtime_url} | adapters=${adapters.length}`);
  const providerConfig = payload?.provider_config || {};
  const modelName = String(providerConfig.model_name || payload.model_name || "-");
  const adapterNames = Array.isArray(providerConfig.adapters) ? providerConfig.adapters.join(", ") : adapters.join(", ");
  const configPath = String(payload.config_entrypoint || providerConfig.config_entrypoint || "/api/runtime/provider/config");
  if (els.wizardGoLiveConfig) {
    els.wizardGoLiveConfig.innerHTML =
      `<div>model=<strong>${escapeHtml(modelName)}</strong></div>` +
      `<div>adapters=${escapeHtml(adapterNames || "-")}</div>` +
      `<div><a class="wizard-action-link" href="${escapeHtml(configPath)}" target="_blank" rel="noopener noreferrer">Open provider/model config</a></div>`;
  }
}

async function runWizardGoLive() {
  const payload = await jsonFetch("/api/wizard/go-live", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
    }),
  });
  renderWizardGoLiveResult(payload);
  await refreshWizardState(state.wizardRunId || undefined);
}

async function openWizardArtifacts() {
  const runId = state.wizardRunId || "";
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  const payload = await jsonFetch(`/api/wizard/artifacts${query}`);
  const folder = payload.open_output_folder_hint || payload.artifacts?.run_folder || "-";
  wizardResult(els.wizardGoLiveResult, `Output folder: ${folder}`);
}

function renderEpisodeList() {
  if (!els.episodeList) {
    return;
  }
  if (!state.episodes.length) {
    els.episodeList.innerHTML = '<div class="memory-empty">No episodes matched this filter.</div>';
    return;
  }
  els.episodeList.innerHTML = state.episodes
    .map((episode) => {
      const selected = state.selectedEpisodeId === episode.episode_id ? " selected" : "";
      return (
        `<button type="button" class="memory-item${selected}" data-episode-id="${escapeHtml(episode.episode_id)}">` +
        `<div class="memory-item-head"><strong>${escapeHtml(episode.episode_id)}</strong><span class="memory-kind">${escapeHtml(episode.promotion_status || "-")}</span></div>` +
        `<div class="memory-item-text">${escapeHtml(episode.title || "(untitled episode)")}</div>` +
        `<div class="memory-item-meta">${escapeHtml(trimDisplay(episode.summary || "", 140))}</div>` +
        `</button>`
      );
    })
    .join("");
  for (const node of els.episodeList.querySelectorAll(".memory-item")) {
    node.addEventListener("click", () => {
      const episodeId = node.getAttribute("data-episode-id") || "";
      selectEpisode(episodeId);
    });
  }
}

function renderEpisodeDetail() {
  if (!els.episodeDetail) {
    return;
  }
  const episode = state.selectedEpisodeDetail;
  if (!episode) {
    els.episodeDetail.classList.add("empty");
    els.episodeDetail.textContent = "Select an episode card to edit title/summary, actors, topic tags, and status.";
    return;
  }
  els.episodeDetail.classList.remove("empty");
  const actors = Array.isArray(episode.actors) ? episode.actors.join(", ") : "";
  const topicTags = Array.isArray(episode.topic_tags) ? episode.topic_tags.join(", ") : "";
  els.episodeDetail.innerHTML =
    `<div class="memory-detail-head"><strong>${escapeHtml(episode.episode_id || "")}</strong><span>${escapeHtml(episode.promotion_status || "")}</span></div>` +
    `<label class="episode-edit-label">Title</label><input id="episodeEditTitle" class="input" type="text" value="${escapeHtml(episode.title || "")}" />` +
    `<label class="episode-edit-label">Summary</label><textarea id="episodeEditSummary" class="input" rows="3">${escapeHtml(episode.summary || "")}</textarea>` +
    `<label class="episode-edit-label">Actors</label><input id="episodeEditActors" class="input" type="text" value="${escapeHtml(actors)}" />` +
    `<label class="episode-edit-label">Topic Tags</label><input id="episodeEditTopics" class="input" type="text" value="${escapeHtml(topicTags)}" />` +
    `<div class="wizard-inline-actions">` +
    `<button id="btnEpisodeSaveEdit" class="btn ghost" type="button">Save Edits</button>` +
    `<button id="btnEpisodeDisable" class="btn ghost" type="button">Disable</button>` +
    `<button id="btnEpisodeEnable" class="btn ghost" type="button">Enable</button>` +
    `</div>`;
  document.getElementById("btnEpisodeSaveEdit")?.addEventListener("click", () => {
    saveEpisodeEdits().catch((error) => renderMemoryError(error.message));
  });
  document.getElementById("btnEpisodeDisable")?.addEventListener("click", () => {
    updateEpisodeStatus("disable").catch((error) => renderMemoryError(error.message));
  });
  document.getElementById("btnEpisodeEnable")?.addEventListener("click", () => {
    updateEpisodeStatus("enable").catch((error) => renderMemoryError(error.message));
  });
}

function selectEpisode(episodeId) {
  state.selectedEpisodeId = episodeId;
  state.selectedEpisodeDetail = state.episodes.find((item) => item.episode_id === episodeId) || null;
  renderEpisodeList();
  renderEpisodeDetail();
}

async function refreshEpisodes() {
  const params = new URLSearchParams();
  const search = (els.episodeSearch?.value || "").trim();
  const status = (els.episodeStatus?.value || "all").trim();
  if (search) {
    params.set("q", search);
  }
  if (status && status !== "all") {
    params.set("status", status);
  }
  if (state.wizardRunId) {
    params.set("run_id", state.wizardRunId);
  }
  const payload = await jsonFetch(`/api/memory/episodes?${params.toString()}`);
  state.episodes = payload.episodes || [];
  if (state.selectedEpisodeId && !state.episodes.some((item) => item.episode_id === state.selectedEpisodeId)) {
    state.selectedEpisodeId = null;
    state.selectedEpisodeDetail = null;
  }
  if (!state.selectedEpisodeId && state.episodes.length) {
    state.selectedEpisodeId = state.episodes[0].episode_id;
    state.selectedEpisodeDetail = state.episodes[0];
  } else if (state.selectedEpisodeId) {
    state.selectedEpisodeDetail = state.episodes.find((item) => item.episode_id === state.selectedEpisodeId) || null;
  }
  renderEpisodeList();
  renderEpisodeDetail();
}

async function updateEpisodeStatus(action) {
  const episode = state.selectedEpisodeDetail;
  if (!episode) {
    throw new Error("No episode selected.");
  }
  const payload = await jsonFetch(`/api/memory/episodes/${encodeURIComponent(episode.episode_id)}/${action}`, {
    method: "POST",
    body: JSON.stringify({ run_id: state.wizardRunId || undefined }),
  });
  renderMemoryError(`Episode ${payload.action} complete for ${episode.episode_id}`);
  await Promise.all([refreshEpisodes(), refreshWizardState(state.wizardRunId || undefined)]);
}

async function saveEpisodeEdits() {
  const episode = state.selectedEpisodeDetail;
  if (!episode) {
    throw new Error("No episode selected.");
  }
  const title = (document.getElementById("episodeEditTitle")?.value || "").trim();
  const summary = (document.getElementById("episodeEditSummary")?.value || "").trim();
  const actors = (document.getElementById("episodeEditActors")?.value || "").trim();
  const topics = (document.getElementById("episodeEditTopics")?.value || "").trim();
  await jsonFetch(`/api/memory/episodes/${encodeURIComponent(episode.episode_id)}/edit`, {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      title,
      summary,
      actors,
      topic_tags: topics,
    }),
  });
  renderMemoryError(`Episode edits saved for ${episode.episode_id}`);
  await refreshEpisodes();
}

async function undoEpisodeChange() {
  const payload = await jsonFetch("/api/memory/episodes/undo-last", {
    method: "POST",
    body: JSON.stringify({}),
  });
  renderMemoryError(`Undo restored ${payload.undo?.restored_path || "-"}`);
  await refreshEpisodes();
}

function renderWhyPanel() {
  if (!els.whyPanel) {
    return;
  }
  if (!state.selectedTurnId) {
    els.whyPanel.classList.add("empty");
    els.whyPanel.textContent = "Select a turn to inspect a plain-language explanation.";
    return;
  }
  const why = state.whyPayload;
  if (!why) {
    els.whyPanel.classList.add("empty");
    els.whyPanel.textContent = "Load Why details for the selected turn.";
    return;
  }
  const windowLabel = why.evidence_time_window || {};
  const topEvidence = Array.isArray(why.top_evidence) ? why.top_evidence : [];
  const citations = Array.isArray(why.citations) ? why.citations : [];
  const evidenceRows = topEvidence.length
    ? topEvidence
        .map(
          (row) =>
            `<div class="why-evidence-row">` +
            `<div><strong>${escapeHtml(row.section || "-")}</strong> · conf=${Number(row.confidence || 0).toFixed(2)}</div>` +
            `<div>${escapeHtml(trimDisplay(row.summary || "", 220))}</div>` +
            `</div>`
        )
        .join("")
    : '<div class="memory-empty">No evidence rows available for this turn.</div>';
  const citationRows =
    citations.length && !why.citations_hidden
      ? `<div class="why-citations">` +
        citations
          .map((token) => `<button type="button" class="btn ghost why-citation-btn" data-citation="${escapeHtml(token)}">${escapeHtml(token)}</button>`)
          .join("") +
        `</div>`
      : '<div class="memory-empty">Citations hidden. Toggle "Show citations" to reveal.</div>';
  els.whyPanel.classList.remove("empty");
  els.whyPanel.innerHTML =
    `<div class="why-summary">decision=${escapeHtml(why.decision || "-")} reason=${escapeHtml(why.decision_reason || "-")}</div>` +
    `<div class="why-summary">window=${escapeHtml(windowLabel.label || "unknown")} (${escapeHtml(windowLabel.start || "-")} → ${escapeHtml(windowLabel.end || "-")})</div>` +
    `<div class="why-evidence">${evidenceRows}</div>` +
    `<div class="why-citations-block">${citationRows}</div>`;
  for (const node of els.whyPanel.querySelectorAll(".why-citation-btn")) {
    node.addEventListener("click", () => {
      const token = node.getAttribute("data-citation") || "";
      if (token) {
        openCitationToken(token).catch((error) => showTraceError(error.message));
      }
    });
  }
}

function renderArchiveViewer() {
  if (!els.archiveViewer) {
    return;
  }
  const payload = state.archivePayload;
  if (!payload) {
    els.archiveViewer.classList.add("empty");
    els.archiveViewer.textContent = "Click a citation token in the Why panel to inspect matched source messages.";
    return;
  }
  const rows = Array.isArray(payload.matches) ? payload.matches : [];
  const items = rows.length
    ? rows
        .map(
          (row) =>
            `<div class="archive-row">` +
            `<div><strong>${escapeHtml(row.atom_id || "-")}</strong> | ${escapeHtml(row.source_id || "-")}#${escapeHtml(row.message_id || "")}</div>` +
            `<div>${escapeHtml(row.timestamp || "-")}</div>` +
            `<div>${escapeHtml(trimDisplay(row.excerpt || "", 240))}</div>` +
            `</div>`
        )
        .join("")
    : '<div class="memory-empty">No matching source refs found for this citation token.</div>';
  els.archiveViewer.classList.remove("empty");
  els.archiveViewer.innerHTML = `<div class="archive-summary">citation=${escapeHtml(payload.citation || "")}</div>${items}`;
}

async function refreshWhyPanel() {
  if (!state.selectedTurnId) {
    state.whyPayload = null;
    renderWhyPanel();
    return;
  }
  const citations = !!(els.whyShowCitations?.checked);
  const payload = await jsonFetch(`/api/turns/${encodeURIComponent(state.selectedTurnId)}/why?citations=${citations ? "true" : "false"}`);
  state.whyPayload = payload.why || null;
  renderWhyPanel();
}

async function openCitationToken(token) {
  const payload = await jsonFetch(`/api/archive/citation/${encodeURIComponent(token)}`);
  state.archivePayload = payload;
  renderArchiveViewer();
}

function clearArchiveViewer() {
  state.archivePayload = null;
  renderArchiveViewer();
}

function renderWritebackPolicy() {
  const policy = state.writebackPolicy || {};
  if (els.writebackEnabled) {
    els.writebackEnabled.checked = !!policy.enabled;
  }
  if (els.writebackPolicyMeta) {
    els.writebackPolicyMeta.textContent = `enabled=${policy.enabled ? "true" : "false"} mode=${policy.mode || "proposal_only"} updated=${formatDate(policy.updated_at || "")}`;
  }
}

async function refreshWritebackPolicy() {
  const payload = await jsonFetch("/api/runtime/writeback/policy");
  state.writebackPolicy = payload.policy || null;
  renderWritebackPolicy();
}

async function saveWritebackPolicy() {
  const enabled = !!(els.writebackEnabled?.checked);
  const payload = await jsonFetch("/api/runtime/writeback/policy", {
    method: "POST",
    body: JSON.stringify({
      enabled,
      mode: "proposal_only",
      auto_apply: false,
    }),
  });
  state.writebackPolicy = payload.policy || null;
  renderWritebackPolicy();
}

function renderHealthPanel() {
  if (!els.healthPanel) {
    return;
  }
  const payload = state.healthPayload;
  if (!payload) {
    els.healthPanel.textContent = "Health check summary appears here.";
    return;
  }
  const checks = Array.isArray(payload.checks) ? payload.checks : [];
  els.healthPanel.innerHTML =
    `<div><strong>${escapeHtml(payload.status || "unknown")}</strong> checked=${escapeHtml(formatDate(payload.checked_at || ""))}</div>` +
    checks.map((item) => `<div>${escapeHtml(item.id || "-")}: ${escapeHtml(item.status || "-")} — ${escapeHtml(item.detail || "")}</div>`).join("");
}

async function runHealthCheck() {
  const payload = await jsonFetch("/api/runtime/health");
  state.healthPayload = payload;
  renderHealthPanel();
}

async function exportDiagnostics() {
  const payload = await jsonFetch("/api/runtime/health/export", {
    method: "POST",
    body: JSON.stringify({}),
  });
  state.healthPayload = payload;
  renderHealthPanel();
  if (els.healthPanel) {
    els.healthPanel.innerHTML += `<div>export=${escapeHtml(payload.export_path || "-")}</div>`;
  }
}

function renderPackagingPanel() {
  if (!els.packagingPanel) {
    return;
  }
  const payload = state.packagingPayload;
  if (!payload) {
    els.packagingPanel.textContent = "One-click setup and runtime launch commands appear here.";
    return;
  }
  const windows = Array.isArray(payload.windows_entrypoints) ? payload.windows_entrypoints.join(", ") : "";
  els.packagingPanel.innerHTML =
    `<div>command: <code>${escapeHtml(payload.one_click_command || "-")}</code></div>` +
    `<div>windows: ${escapeHtml(windows)}</div>` +
    `<div>guide: ${escapeHtml(payload.guide_path || "-")}</div>`;
}

async function loadPackagingHints() {
  const payload = await jsonFetch("/api/runtime/packaging/instructions");
  state.packagingPayload = payload;
  renderPackagingPanel();
}

function methodologyActorValue() {
  return String(els.methodologyActor?.value || "").trim() || "operator";
}

function methodologyTargetId() {
  return String(els.methodologyId?.value || "").trim();
}

function setMethodologyActionMeta(text, isError = false) {
  state.methodologyActionResult = {
    text: String(text || ""),
    isError: !!isError,
    at: new Date().toISOString(),
  };
  renderMethodologyPanel();
}

function renderMethodologyPanel() {
  if (!els.methodologyReadoutMeta || !els.methodologyActionMeta) {
    return;
  }
  const readout = state.methodologyReadout || null;
  const records = Array.isArray(state.methodologyRecords) ? state.methodologyRecords : [];
  const clusters = Array.isArray(state.methodologyClusters) ? state.methodologyClusters : [];
  const maintenance = Array.isArray(state.methodologyMaintenance) ? state.methodologyMaintenance : [];
  if (!readout) {
    els.methodologyReadoutMeta.textContent = "Methodology readout appears here.";
  } else {
    const counts = readout.counts || {};
    const status = counts.status || {};
    const latestCanary = readout.latest_canary || {};
    const latestCompare = (latestCanary.canary || {}).latest_compare || {};
    const topRecords = records
      .slice(0, 5)
      .map((row) => {
        const methodologyId = String(row.methodology_id || "-");
        const rowStatus = String(row.status || "-");
        const approval = String(row.approval_state || "-");
        const risk = String(row.risk_label || "-");
        return `<div>${escapeHtml(methodologyId)} | ${escapeHtml(rowStatus)}/${escapeHtml(approval)} | risk=${escapeHtml(risk)}</div>`;
      })
      .join("");
    const topClusters = clusters
      .slice(0, 3)
      .map((row) => `<div>${escapeHtml(String(row.cluster_id || "-"))}: count=${escapeHtml(String(row.count || 0))}</div>`)
      .join("");
    const latestMaintenance = maintenance[0] || {};
    const triggerCount = Array.isArray(latestMaintenance.triggers) ? latestMaintenance.triggers.length : 0;
    els.methodologyReadoutMeta.innerHTML =
      `<div>active=${escapeHtml(String(readout.active_methodology_id || "-"))} pending=${escapeHtml(String(counts.pending_review || 0))}</div>` +
      `<div>draft=${escapeHtml(String(status.draft || 0))} canary=${escapeHtml(String(status.canary || 0))} active=${escapeHtml(String(status.active || 0))} retired=${escapeHtml(String(status.retired || 0))}</div>` +
      `<div>latest canary risk=${escapeHtml(String(latestCompare.risk_label || "none"))} rollback=${escapeHtml(String(latestCompare.should_rollback || false))}</div>` +
      `<div>latest maintenance risk=${escapeHtml(String(latestMaintenance.risk_label || "none"))} triggers=${escapeHtml(String(triggerCount))}</div>` +
      `<div>top records:${topRecords || "<span> none</span>"}</div>` +
      `<div>top correction clusters:${topClusters || "<span> none</span>"}</div>`;
  }

  const action = state.methodologyActionResult;
  if (!action || !String(action.text || "").trim()) {
    els.methodologyActionMeta.textContent = "Methodology action results appear here.";
    return;
  }
  const prefix = action.isError ? "ERROR" : "OK";
  els.methodologyActionMeta.innerHTML =
    `<div><strong>${escapeHtml(prefix)}</strong> ${escapeHtml(action.text || "")}</div>` +
    `<div>updated=${escapeHtml(formatDate(action.at || ""))}</div>`;
}

async function refreshMethodologyStatus() {
  const [readoutPayload, recordsPayload, clustersPayload, maintenancePayload] = await Promise.all([
    jsonFetch("/api/methodology/readout"),
    jsonFetch("/api/methodology/records?status=all&limit=20&offset=0"),
    jsonFetch("/api/methodology/corrections/clusters?limit=10"),
    jsonFetch("/api/methodology/maintenance/history?limit=5"),
  ]);
  state.methodologyReadout = readoutPayload.readout || null;
  state.methodologyRecords = Array.isArray(recordsPayload.records) ? recordsPayload.records : [];
  state.methodologyClusters = Array.isArray(clustersPayload.clusters) ? clustersPayload.clusters : [];
  state.methodologyMaintenance = Array.isArray(maintenancePayload.maintenance_history) ? maintenancePayload.maintenance_history : [];
  renderMethodologyPanel();
}

async function createMethodologyDraft() {
  const triggerCondition = String(els.methodologyTriggerCondition?.value || "").trim();
  const action = String(els.methodologyAction?.value || "").trim();
  const rationale = String(els.methodologyRationale?.value || "").trim();
  if (!triggerCondition || !action || !rationale) {
    throw new Error("Trigger condition, action, and rationale are required.");
  }
  const payload = await jsonFetch("/api/methodology/create", {
    method: "POST",
    body: JSON.stringify({
      trigger_condition: triggerCondition,
      action,
      rationale,
      actor: methodologyActorValue(),
    }),
  });
  const record = payload.record || {};
  const methodologyId = String(record.methodology_id || "").trim();
  if (methodologyId && els.methodologyId) {
    els.methodologyId.value = methodologyId;
  }
  await refreshMethodologyStatus();
  setMethodologyActionMeta(`Created draft ${methodologyId || "(unknown id)"}.`);
}

async function reviewMethodology(decision) {
  const methodologyId = methodologyTargetId();
  if (!methodologyId) {
    throw new Error("Methodology ID is required.");
  }
  const note = String(els.methodologyNote?.value || "").trim();
  await jsonFetch("/api/methodology/review", {
    method: "POST",
    body: JSON.stringify({
      methodology_id: methodologyId,
      decision: String(decision || "").trim().toLowerCase(),
      reviewer: methodologyActorValue(),
      note,
    }),
  });
  await refreshMethodologyStatus();
  setMethodologyActionMeta(`Review ${String(decision)} applied for ${methodologyId}.`);
}

async function startMethodologyCanary() {
  const methodologyId = methodologyTargetId();
  if (!methodologyId) {
    throw new Error("Methodology ID is required.");
  }
  await jsonFetch("/api/methodology/canary/start", {
    method: "POST",
    body: JSON.stringify({
      methodology_id: methodologyId,
      actor: methodologyActorValue(),
      auto_rollback: true,
    }),
  });
  await refreshMethodologyStatus();
  setMethodologyActionMeta(`Canary started for ${methodologyId}.`);
}

async function evaluateMethodologyCanary() {
  const methodologyId = methodologyTargetId();
  if (!methodologyId) {
    throw new Error("Methodology ID is required.");
  }
  const payload = await jsonFetch("/api/methodology/canary/evaluate", {
    method: "POST",
    body: JSON.stringify({
      methodology_id: methodologyId,
      actor: methodologyActorValue(),
    }),
  });
  const compare = payload.comparison || {};
  await refreshMethodologyStatus();
  setMethodologyActionMeta(
    `Canary evaluated for ${methodologyId}. risk=${String(compare.risk_label || "low")} rollback=${String(compare.should_rollback || false)}.`
  );
}

async function activateMethodology() {
  const methodologyId = methodologyTargetId();
  if (!methodologyId) {
    throw new Error("Methodology ID is required.");
  }
  await jsonFetch("/api/methodology/activate", {
    method: "POST",
    body: JSON.stringify({
      methodology_id: methodologyId,
      actor: methodologyActorValue(),
    }),
  });
  await refreshMethodologyStatus();
  setMethodologyActionMeta(`Activated ${methodologyId}.`);
}

async function rollbackMethodology() {
  const methodologyId = methodologyTargetId();
  if (!methodologyId) {
    throw new Error("Methodology ID is required.");
  }
  const confirmed = window.confirm(`Rollback methodology ${methodologyId}? This retires it and restores previous active if available.`);
  if (!confirmed) {
    return;
  }
  const reason = String(els.methodologyNote?.value || "").trim() || "manual_rollback_from_ui";
  await jsonFetch("/api/methodology/rollback", {
    method: "POST",
    body: JSON.stringify({
      methodology_id: methodologyId,
      actor: methodologyActorValue(),
      reason,
    }),
  });
  await refreshMethodologyStatus();
  setMethodologyActionMeta(`Rollback applied for ${methodologyId}.`);
}

async function recordMethodologyCorrection() {
  const text = String(els.methodologyCorrection?.value || "").trim();
  if (!text) {
    throw new Error("Correction text is required.");
  }
  const payload = await jsonFetch("/api/methodology/corrections/record", {
    method: "POST",
    body: JSON.stringify({
      text,
      actor: methodologyActorValue(),
      assistant_id: "runtime_ui",
      session_id: String(state.activeSessionId || "runtime_ui"),
    }),
  });
  const cluster = payload.cluster || {};
  const generated = payload.generated_methodology || {};
  await refreshMethodologyStatus();
  const generatedId = String(generated.methodology_id || "").trim();
  const generatedPart = generatedId ? ` generated=${generatedId}` : "";
  setMethodologyActionMeta(`Correction cluster=${String(cluster.cluster_id || "-")} count=${String(cluster.count || 0)}.${generatedPart}`);
}

async function evaluateMethodologyMaintenance() {
  const payload = await jsonFetch("/api/methodology/maintenance/evaluate", {
    method: "POST",
    body: JSON.stringify({
      actor: methodologyActorValue(),
      force: true,
    }),
  });
  const evaluation = payload.evaluation || {};
  const triggers = Array.isArray(evaluation.triggers) ? evaluation.triggers.length : 0;
  await refreshMethodologyStatus();
  setMethodologyActionMeta(`Maintenance evaluation risk=${String(evaluation.risk_label || "low")} triggers=${String(triggers)}.`);
}

async function refreshOpsDeck() {
  await Promise.all([refreshWritebackPolicy(), runHealthCheck(), loadPackagingHints(), refreshMethodologyStatus()]);
}

async function createDeleteProposal() {
  const atomId = (els.proposalAtomId?.value || "").trim();
  if (!atomId) {
    throw new Error("Enter an atom id to propose disable.");
  }
  await jsonFetch("/api/memory/proposals/create-delete", {
    method: "POST",
    body: JSON.stringify({
      target_atom_id: atomId,
      reason_code: "manual_disable",
    }),
  });
  await refreshProposals();
}

async function createEditProposal() {
  const atomId = (els.proposalAtomId?.value || "").trim();
  const canonicalText = (els.proposalEditText?.value || "").trim();
  if (!atomId || !canonicalText) {
    throw new Error("Enter atom id and edited text to create edit proposal.");
  }
  await jsonFetch("/api/memory/proposals/create-edit", {
    method: "POST",
    body: JSON.stringify({
      target_atom_id: atomId,
      canonical_text: canonicalText,
      reason_code: "manual_edit",
    }),
  });
  await refreshProposals();
}

function scheduleMemorySearch() {
  if (searchTimer !== null) {
    window.clearTimeout(searchTimer);
  }
  searchTimer = window.setTimeout(() => {
    const task = state.memoryScope === "episodes" ? refreshEpisodes() : refreshMemory();
    task.catch((error) => renderMemoryError(error.message));
  }, 240);
}

function bindEvents() {
  els.btnSimpleMode?.addEventListener("click", () => {
    setUiMode("simple");
  });
  els.btnAdvancedMode?.addEventListener("click", () => {
    setUiMode("advanced");
  });
  els.chatForm?.addEventListener("submit", (event) => {
    sendTurn(event).catch((error) => showTraceError(error.message));
  });
  els.btnRoutePreview?.addEventListener("click", () => {
    previewTurnRoute().catch((error) => {
      clearRoutePreview(`Route preview failed: ${error.message}`);
    });
  });
  els.btnContextPreview?.addEventListener("click", () => {
    previewContextPackage().catch((error) => {
      state.contextError = `Context preview failed: ${error.message}`;
      renderContextPreview();
    });
  });
  els.btnContextPreviewSide?.addEventListener("click", () => {
    previewContextPackage().catch((error) => {
      state.contextError = `Context preview failed: ${error.message}`;
      renderContextPreview();
    });
  });
  els.btnRefresh?.addEventListener("click", () => {
    refreshSessionAndState().catch((error) => showTraceError(error.message));
  });
  els.btnLedgerRefresh?.addEventListener("click", () => {
    refreshRuntimeLedger().catch((error) => showTraceError(error.message));
  });
  els.btnMemoryRefresh?.addEventListener("click", () => {
    Promise.all([refreshMemory(), refreshEpisodes()]).catch((error) => renderMemoryError(error.message));
  });
  els.btnMemoryGraphRefresh?.addEventListener("click", () => {
    refreshMemoryGraph().catch((error) => renderMemoryError(error.message));
  });
  els.btnMemoryGraphFocus?.addEventListener("click", () => {
    if (state.selectedCardId) {
      state.selectedGraphAtomId = atomIdFromCardId(state.selectedCardId);
    } else if (state.memoryGraph.nodes.length) {
      state.selectedGraphAtomId = String(state.memoryGraph.nodes[0].atom_id);
    }
    renderMemoryGraph();
  });
  els.btnProposalRefresh?.addEventListener("click", () => {
    refreshProposals().catch((error) => renderMemoryError(error.message));
  });
  els.memorySearch?.addEventListener("input", scheduleMemorySearch);
  els.memoryStatus?.addEventListener("change", () => {
    refreshMemory().catch((error) => renderMemoryError(error.message));
  });
  els.memoryKind?.addEventListener("change", () => {
    refreshMemory().catch((error) => renderMemoryError(error.message));
  });
  els.memoryContradiction?.addEventListener("change", () => {
    refreshMemory().catch((error) => renderMemoryError(error.message));
  });
  els.btnMemoryScopeAtoms?.addEventListener("click", () => {
    setMemoryScope("atoms");
  });
  els.btnMemoryScopeEpisodes?.addEventListener("click", () => {
    setMemoryScope("episodes");
    refreshEpisodes().catch((error) => renderMemoryError(error.message));
  });
  els.btnMemoryScopeAtoms?.addEventListener("keydown", handleMemoryScopeTabKeydown);
  els.btnMemoryScopeEpisodes?.addEventListener("keydown", handleMemoryScopeTabKeydown);
  els.episodeSearch?.addEventListener("input", scheduleMemorySearch);
  els.episodeStatus?.addEventListener("change", () => {
    refreshEpisodes().catch((error) => renderMemoryError(error.message));
  });
  els.btnEpisodeRefresh?.addEventListener("click", () => {
    refreshEpisodes().catch((error) => renderMemoryError(error.message));
  });
  els.btnEpisodeUndo?.addEventListener("click", () => {
    undoEpisodeChange().catch((error) => renderMemoryError(error.message));
  });
  els.btnProposalCreateDelete?.addEventListener("click", () => {
    createDeleteProposal().catch((error) => renderMemoryError(error.message));
  });
  els.btnProposalCreateEdit?.addEventListener("click", () => {
    createEditProposal().catch((error) => renderMemoryError(error.message));
  });
  els.btnSessionRefresh?.addEventListener("click", () => {
    refreshSessionAndState().catch((error) => showTraceError(error.message));
  });
  els.btnSessionStart?.addEventListener("click", () => {
    startSession().catch((error) => showTraceError(error.message));
  });
  els.sessionSelect?.addEventListener("change", () => {
    state.activeSessionId = els.sessionSelect.value || null;
    clearRoutePreview();
    clearContextPreview();
    refreshActiveSessionData().catch((error) => showTraceError(error.message));
  });

  els.settingHighRiskDefault?.addEventListener("change", () => {
    settings.highRiskDefault = !!els.settingHighRiskDefault.checked;
    if (els.highRisk) {
      els.highRisk.checked = settings.highRiskDefault;
    }
    saveSettings();
  });
  els.settingRetrievalQuery?.addEventListener("change", () => {
    settings.retrievalQuery = (els.settingRetrievalQuery.value || "").trim();
    saveSettings();
  });
  els.settingMemoryPreference?.addEventListener("change", () => {
    settings.memoryPreference = String(els.settingMemoryPreference.value || "auto");
    saveSettings();
    if (state.routePreview) {
      previewTurnRoute().catch((error) => clearRoutePreview(`Route preview failed: ${error.message}`));
    }
    if (state.contextPackage) {
      previewContextPackage().catch((error) => {
        state.contextError = `Context preview failed: ${error.message}`;
        renderContextPreview();
      });
    }
  });
  els.settingAutoRefresh?.addEventListener("change", () => {
    const parsed = Number(els.settingAutoRefresh.value || "0");
    settings.autoRefreshMs = Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
    saveSettings();
    updateAutoRefresh();
  });

  els.btnWizardResume?.addEventListener("click", () => {
    startWizard("resume").catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.btnWizardStartNew?.addEventListener("click", () => {
    startWizard("new").catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.btnWizardRestore?.addEventListener("click", () => {
    restoreWizardLastPublished().catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.btnWizardArtifacts?.addEventListener("click", () => {
    openWizardArtifacts().catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.btnWizardValidate?.addEventListener("click", () => {
    validateWizardImport().catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.btnWizardImport?.addEventListener("click", () => {
    runWizardImport().catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.btnWizardBuild?.addEventListener("click", () => {
    runWizardBuild().catch((error) => wizardResult(els.wizardBuildResult, error.message, true));
  });
  els.btnBuilderSave?.addEventListener("click", () => {
    saveBuilderProfile().catch((error) => wizardResult(els.wizardBuilderResult, error.message, true));
  });
  els.btnBuilderRebuild?.addEventListener("click", () => {
    rebuildWithBuilderProfile().catch((error) => wizardResult(els.wizardBuilderResult, error.message, true));
  });
  els.btnWizardReviewRefresh?.addEventListener("click", () => {
    loadWizardReviewCards().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  });
  els.wizardReviewSearch?.addEventListener("input", () => {
    loadWizardReviewCards().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  });
  els.wizardReviewStatus?.addEventListener("change", () => {
    loadWizardReviewCards().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  });
  els.btnWizardCompileReview?.addEventListener("click", () => {
    compileWizardReview().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  });
  els.btnWizardVerify?.addEventListener("click", () => {
    runWizardVerify().catch((error) => wizardResult(els.wizardVerifyResult, error.message, true));
  });
  els.btnWizardGoLive?.addEventListener("click", () => {
    runWizardGoLive().catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.btnWhyRefresh?.addEventListener("click", () => {
    refreshWhyPanel().catch((error) => showTraceError(error.message));
  });
  els.whyShowCitations?.addEventListener("change", () => {
    refreshWhyPanel().catch((error) => showTraceError(error.message));
  });
  els.btnArchiveClear?.addEventListener("click", () => {
    clearArchiveViewer();
  });
  els.btnWritebackSave?.addEventListener("click", () => {
    saveWritebackPolicy().catch((error) => showTraceError(error.message));
  });
  els.btnHealthRun?.addEventListener("click", () => {
    runHealthCheck().catch((error) => showTraceError(error.message));
  });
  els.btnHealthExport?.addEventListener("click", () => {
    exportDiagnostics().catch((error) => showTraceError(error.message));
  });
  els.btnPackagingLoad?.addEventListener("click", () => {
    loadPackagingHints().catch((error) => showTraceError(error.message));
  });
  els.btnMethodologyCreate?.addEventListener("click", () => {
    createMethodologyDraft().catch((error) => setMethodologyActionMeta(error.message, true));
  });
  els.btnMethodologyApprove?.addEventListener("click", () => {
    reviewMethodology("approve").catch((error) => setMethodologyActionMeta(error.message, true));
  });
  els.btnMethodologyReject?.addEventListener("click", () => {
    reviewMethodology("reject").catch((error) => setMethodologyActionMeta(error.message, true));
  });
  els.btnMethodologyCanaryStart?.addEventListener("click", () => {
    startMethodologyCanary().catch((error) => setMethodologyActionMeta(error.message, true));
  });
  els.btnMethodologyCanaryEval?.addEventListener("click", () => {
    evaluateMethodologyCanary().catch((error) => setMethodologyActionMeta(error.message, true));
  });
  els.btnMethodologyActivate?.addEventListener("click", () => {
    activateMethodology().catch((error) => setMethodologyActionMeta(error.message, true));
  });
  els.btnMethodologyRollback?.addEventListener("click", () => {
    rollbackMethodology().catch((error) => setMethodologyActionMeta(error.message, true));
  });
  els.btnMethodologyRecordCorrection?.addEventListener("click", () => {
    recordMethodologyCorrection().catch((error) => setMethodologyActionMeta(error.message, true));
  });
  els.btnMethodologyMaintenanceEval?.addEventListener("click", () => {
    evaluateMethodologyMaintenance().catch((error) => setMethodologyActionMeta(error.message, true));
  });
  els.btnMethodologyRefresh?.addEventListener("click", () => {
    refreshMethodologyStatus().catch((error) => setMethodologyActionMeta(error.message, true));
  });
  els.btnOpsRefresh?.addEventListener("click", () => {
    refreshOpsDeck().catch((error) => showTraceError(error.message));
  });
}

async function bootstrap() {
  loadSettings();
  applySettingsToInputs();
  updateAutoRefresh();
  setMemoryScope("atoms");
  renderArchiveViewer();
  renderWhyPanel();
  renderPackagingPanel();
  renderHealthPanel();
  bindEvents();
  clearContextPreview();
  await refreshDecisionCatalog();
  await refreshSessionAndState();
  if (!state.activeSessionId) {
    await ensureActiveSession();
    await refreshSessionAndState();
  }
  await Promise.all([refreshMemory(), refreshProposals(), refreshEpisodes()]);
  await refreshWizardState();
  await refreshWhyPanel();
  await refreshOpsDeck();
}

bootstrap().catch((error) => {
  showTraceError(error.message);
});
