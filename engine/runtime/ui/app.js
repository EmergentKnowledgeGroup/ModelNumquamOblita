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
  memoryGraphView: {
    scale: 1,
    offsetX: 0,
    offsetY: 0,
    baseScale: 1,
    baseOffsetX: 0,
    baseOffsetY: 0,
    signature: "",
  },
  memoryGraphLayoutCache: {
    signature: "",
    width: 0,
    height: 0,
    layout: null,
  },
  memoryGraphPan: {
    active: false,
    pointerId: null,
    startClientX: 0,
    startClientY: 0,
    startOffsetX: 0,
    startOffsetY: 0,
  },
  selectedGraphAtomId: null,
  memoryNeighborhood: {
    root: null,
    neighbors: [],
    links: [],
    depth: 1,
    includeSharedLanguage: false,
    nodeLimit: 18,
    linkLimit: 36,
    requestsUsed: 0,
    truncated: false,
    truncation: null,
    loading: false,
    error: null,
  },
  memoryNeighborhoodRequestSeq: 0,
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
  wizardLatestRunId: "",
  hcrMode: false,
  hcrRunId: "",
  hcrStatus: null,
  wizardResumeAvailable: false,
  wizardImportPending: false,
  wizardVisibleStage: "import",
  wizardReviewCards: [],
  wizardReviewMeta: {
    total: 0,
    filteredTotal: 0,
    page: 1,
    pageSize: 6,
    totalPages: 1,
  },
  wizardReviewRequestSeq: 0,
  wizardReviewSummaryRequestSeq: 0,
  wizardReviewPendingWrites: {},
  wizardReviewFacets: { actors: [], topics: [] },
  wizardReviewFilters: { actors: [], topics: [] },
  wizardReviewFacetMenuOpen: false,
  wizardReviewFocusEpisodeId: "",
  wizardReviewShouldFocus: false,
  wizardReviewEditorEpisodeId: "",
  wizardReviewEditorReturnFocus: null,
  wizardReviewEditorSelections: { actors: [], topics: [] },
  wizardReviewEditorPickerOpen: null,
  wizardDraftCurationStatus: null,
  wizardDraftCurationAllCards: [],
  wizardDraftCurationCards: [],
  wizardDraftCurationMeta: {
    total: 0,
    filteredTotal: 0,
    page: 1,
    pageSize: 6,
    totalPages: 1,
    statusFilter: "pending",
    search: "",
  },
  wizardDraftCurationRequestSeq: 0,
  wizardDraftCurationDetailRequestSeq: 0,
  wizardDraftCurationSelectedEpisodeId: "",
  wizardDraftCurationDetail: null,
  wizardDraftCurationReturnFocus: null,
  wizardDraftCurationSidebarCollapsed: false,
  wizardDraftCurationMcp: null,
  wizardDraftCurationMcpTarget: "claude_code",
  wizardDraftCurationMcpScope: "user",
  wizardDraftCurationMcpRole: "viewer",
  wizardDraftCurationMcpMutations: true,
  wizardManagedMcpLoaded: false,
  wizardInputOptions: null,
  wizardInputMode: "archive",
  wizardArchiveTargetMode: "new",
  wizardLocalSourcePaths: [],
  wizardUploadedSourceFiles: [],
  wizardActivation: null,
  wizardMcpTarget: "claude_code",
  wizardMcpScope: "user",
  wizardMcpRole: "viewer",
  wizardMcpMutations: false,
  wizardActivationProviderConfig: null,
  wizardRemap: null,
  wizardPendingRemapTarget: "",
  wizardInlineDialogReturnFocus: null,
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
  tabDataLoaded: {
    setup: false,
    chat: false,
    memory: false,
    "memory-cards": false,
    "memory-graph": false,
    "memory-proposals": false,
    trace: false,
    ops: false,
  },
  tabDataLoading: {},
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
let wizardReviewSearchTimer = null;
const els = {
  modelName: document.getElementById("modelName"),
  metricTurns: document.getElementById("metricTurns"),
  metricTokens: document.getElementById("metricTokens"),
  metricCost: document.getElementById("metricCost"),
  metricP95: document.getElementById("metricP95"),
  metricRecognition: document.getElementById("metricRecognition"),
  btnDesktopHome: document.getElementById("btnDesktopHome"),
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
  memoryGraphViewportMeta: document.getElementById("memoryGraphViewportMeta"),
  memoryGraphViewport: document.getElementById("memoryGraphViewport"),
  memoryGraphSvg: document.getElementById("memoryGraphSvg"),
  memoryGraphDetail: document.getElementById("memoryGraphDetail"),
  btnMemoryGraphFit: document.getElementById("btnMemoryGraphFit"),
  btnMemoryGraphZoomOut: document.getElementById("btnMemoryGraphZoomOut"),
  btnMemoryGraphZoomIn: document.getElementById("btnMemoryGraphZoomIn"),
  btnMemoryGraphReset: document.getElementById("btnMemoryGraphReset"),
  memoryNeighborhoodMeta: document.getElementById("memoryNeighborhoodMeta"),
  memoryNeighborhoodSvg: document.getElementById("memoryNeighborhoodSvg"),
  memoryNeighborhoodList: document.getElementById("memoryNeighborhoodList"),
  memoryNeighborhoodDepth: document.getElementById("memoryNeighborhoodDepth"),
  memoryNeighborhoodShared: document.getElementById("memoryNeighborhoodShared"),
  btnMemoryGraphRefresh: document.getElementById("btnMemoryGraphRefresh"),
  btnMemoryGraphExpand: document.getElementById("btnMemoryGraphExpand"),
  btnMemoryGraphToggleIsolated: document.getElementById("btnMemoryGraphToggleIsolated"),
  btnMemoryGraphFocus: document.getElementById("btnMemoryGraphFocus"),
  memoryNeighborhoodPanel: document.getElementById("memoryNeighborhoodPanel"),
  memoryNeighborhoodBackdrop: document.getElementById("memoryNeighborhoodBackdrop"),
  memoryNeighborhoodViewport: document.getElementById("memoryNeighborhoodViewport"),
  btnMemoryNeighborhoodClose: document.getElementById("btnMemoryNeighborhoodClose"),
  btnMemoryNeighborhoodRefresh: document.getElementById("btnMemoryNeighborhoodRefresh"),
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
  hcrRoomStatus: document.getElementById("hcrRoomStatus"),
  wizardStageRail: document.getElementById("wizardStageRail"),
  btnWizardResume: document.getElementById("btnWizardResume"),
  btnWizardStartNew: document.getElementById("btnWizardStartNew"),
  btnWizardRestore: document.getElementById("btnWizardRestore"),
  btnWizardArtifacts: document.getElementById("btnWizardArtifacts"),
  wizardArchivePath: document.getElementById("wizardArchivePath"),
  wizardArchivePathInline: document.getElementById("wizardArchivePathInline"),
  btnWizardArchivePathInline: document.getElementById("btnWizardArchivePathInline"),
  btnWizardLaneArchive: document.getElementById("btnWizardLaneArchive"),
  btnWizardLaneStore: document.getElementById("btnWizardLaneStore"),
  wizardArchivePanel: document.getElementById("wizardArchivePanel"),
  wizardStorePanel: document.getElementById("wizardStorePanel"),
  btnWizardPickFiles: document.getElementById("btnWizardPickFiles"),
  btnWizardPickFolder: document.getElementById("btnWizardPickFolder"),
  btnWizardClearSources: document.getElementById("btnWizardClearSources"),
  wizardArchiveFile: document.getElementById("wizardArchiveFile"),
  wizardArchiveFolder: document.getElementById("wizardArchiveFolder"),
  wizardSourceList: document.getElementById("wizardSourceList"),
  btnWizardArchiveTargetNew: document.getElementById("btnWizardArchiveTargetNew"),
  btnWizardArchiveTargetExisting: document.getElementById("btnWizardArchiveTargetExisting"),
  wizardArchiveStorePanel: document.getElementById("wizardArchiveStorePanel"),
  wizardArchiveStoreSelect: document.getElementById("wizardArchiveStoreSelect"),
  btnWizardRefreshSourcesArchive: document.getElementById("btnWizardRefreshSourcesArchive"),
  wizardArchiveStoreSummary: document.getElementById("wizardArchiveStoreSummary"),
  wizardArchiveSummary: document.getElementById("wizardArchiveSummary"),
  wizardStoreSelect: document.getElementById("wizardStoreSelect"),
  btnWizardRefreshSources: document.getElementById("btnWizardRefreshSources"),
  wizardStoreSummary: document.getElementById("wizardStoreSummary"),
  btnWizardValidate: document.getElementById("btnWizardValidate"),
  btnWizardImport: document.getElementById("btnWizardImport"),
  wizardImportResult: document.getElementById("wizardImportResult"),
  btnWizardBuildPolicyInfo: document.getElementById("btnWizardBuildPolicyInfo"),
  wizardBuildPolicyDialog: document.getElementById("wizardBuildPolicyDialog"),
  btnWizardBuildPolicyClose: document.getElementById("btnWizardBuildPolicyClose"),
  btnMemoryPreferenceInfo: document.getElementById("btnMemoryPreferenceInfo"),
  memoryPreferenceDialog: document.getElementById("memoryPreferenceDialog"),
  btnMemoryPreferenceClose: document.getElementById("btnMemoryPreferenceClose"),
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
  wizardReviewPageSize: document.getElementById("wizardReviewPageSize"),
  btnWizardReviewFacetToggle: document.getElementById("btnWizardReviewFacetToggle"),
  btnWizardReviewFacetClear: document.getElementById("btnWizardReviewFacetClear"),
  wizardReviewFacetMenu: document.getElementById("wizardReviewFacetMenu"),
  wizardReviewActiveFilters: document.getElementById("wizardReviewActiveFilters"),
  wizardReviewActorFilters: document.getElementById("wizardReviewActorFilters"),
  wizardReviewTopicFilters: document.getElementById("wizardReviewTopicFilters"),
  btnWizardReviewRefresh: document.getElementById("btnWizardReviewRefresh"),
  wizardReviewMeta: document.getElementById("wizardReviewMeta"),
  wizardReviewList: document.getElementById("wizardReviewList"),
  btnWizardReviewPrev: document.getElementById("btnWizardReviewPrev"),
  wizardReviewPager: document.getElementById("wizardReviewPager"),
  btnWizardReviewNext: document.getElementById("btnWizardReviewNext"),
  wizardReviewEditorDialog: document.getElementById("wizardReviewEditorDialog"),
  btnWizardReviewEditorClose: document.getElementById("btnWizardReviewEditorClose"),
  btnWizardReviewEditorPrev: document.getElementById("btnWizardReviewEditorPrev"),
  btnWizardReviewEditorNext: document.getElementById("btnWizardReviewEditorNext"),
  wizardReviewEditorMeta: document.getElementById("wizardReviewEditorMeta"),
  wizardReviewEditorEpisodeId: document.getElementById("wizardReviewEditorEpisodeId"),
  wizardReviewEditorDecision: document.getElementById("wizardReviewEditorDecision"),
  wizardReviewEditorTitle: document.getElementById("wizardReviewEditorTitle"),
  wizardReviewEditorSummary: document.getElementById("wizardReviewEditorSummary"),
  wizardReviewEditorTruthFamilyId: document.getElementById("wizardReviewEditorTruthFamilyId"),
  wizardReviewEditorSupersedesEpisodeId: document.getElementById("wizardReviewEditorSupersedesEpisodeId"),
  btnWizardReviewEditorApprove: document.getElementById("btnWizardReviewEditorApprove"),
  btnWizardReviewEditorReject: document.getElementById("btnWizardReviewEditorReject"),
  wizardReviewEditorResult: document.getElementById("wizardReviewEditorResult"),
  btnWizardReviewEditorActorsToggle: document.getElementById("btnWizardReviewEditorActorsToggle"),
  btnWizardReviewEditorTopicsToggle: document.getElementById("btnWizardReviewEditorTopicsToggle"),
  wizardReviewEditorActorsMenu: document.getElementById("wizardReviewEditorActorsMenu"),
  wizardReviewEditorTopicsMenu: document.getElementById("wizardReviewEditorTopicsMenu"),
  wizardReviewEditorActorsOptions: document.getElementById("wizardReviewEditorActorsOptions"),
  wizardReviewEditorTopicsOptions: document.getElementById("wizardReviewEditorTopicsOptions"),
  btnWizardReviewEditorActorsCustomToggle: document.getElementById("btnWizardReviewEditorActorsCustomToggle"),
  btnWizardReviewEditorTopicsCustomToggle: document.getElementById("btnWizardReviewEditorTopicsCustomToggle"),
  wizardReviewEditorActorsCustomBox: document.getElementById("wizardReviewEditorActorsCustomBox"),
  wizardReviewEditorTopicsCustomBox: document.getElementById("wizardReviewEditorTopicsCustomBox"),
  wizardReviewEditorActorsCustomInput: document.getElementById("wizardReviewEditorActorsCustomInput"),
  wizardReviewEditorTopicsCustomInput: document.getElementById("wizardReviewEditorTopicsCustomInput"),
  btnWizardReviewEditorActorsCustomAdd: document.getElementById("btnWizardReviewEditorActorsCustomAdd"),
  btnWizardReviewEditorTopicsCustomAdd: document.getElementById("btnWizardReviewEditorTopicsCustomAdd"),
  wizardReviewActorSummary: document.getElementById("wizardReviewActorSummary"),
  wizardReviewTopicSummary: document.getElementById("wizardReviewTopicSummary"),
  btnWizardDraftCurationRefresh: document.getElementById("btnWizardDraftCurationRefresh"),
  btnWizardDraftCurationForceRelease: document.getElementById("btnWizardDraftCurationForceRelease"),
  btnWizardDraftCurationOpenWorkspace: document.getElementById("btnWizardDraftCurationOpenWorkspace"),
  btnWizardDraftCurationSidebarToggle: document.getElementById("btnWizardDraftCurationSidebarToggle"),
  btnWizardDraftCurationSidebarRestore: document.getElementById("btnWizardDraftCurationSidebarRestore"),
  wizardDraftCurationSidebarToggleIcon: document.getElementById("wizardDraftCurationSidebarToggleIcon"),
  wizardDraftCurationSidebarToggleLabel: document.getElementById("wizardDraftCurationSidebarToggleLabel"),
  wizardDraftCurationRunId: document.getElementById("wizardDraftCurationRunId"),
  btnWizardDraftCurationCopyRunId: document.getElementById("btnWizardDraftCurationCopyRunId"),
  wizardDraftCurationStatus: document.getElementById("wizardDraftCurationStatus"),
  wizardDraftCurationWorkspaceStatus: document.getElementById("wizardDraftCurationWorkspaceStatus"),
  wizardDraftCurationWorkspaceMcpSummary: document.getElementById("wizardDraftCurationWorkspaceMcpSummary"),
  wizardDraftCurationQueue: document.getElementById("wizardDraftCurationQueue"),
  wizardDraftCurationWorkspaceGrid: document.getElementById("wizardDraftCurationWorkspaceGrid"),
  wizardDraftCurationWorkspaceRail: document.getElementById("wizardDraftCurationWorkspaceRail"),
  wizardDraftCurationSearch: document.getElementById("wizardDraftCurationSearch"),
  wizardDraftCurationStatusFilter: document.getElementById("wizardDraftCurationStatusFilter"),
  wizardDraftCurationPageSize: document.getElementById("wizardDraftCurationPageSize"),
  wizardDraftCurationList: document.getElementById("wizardDraftCurationList"),
  wizardDraftCurationResult: document.getElementById("wizardDraftCurationResult"),
  btnWizardDraftCurationPrev: document.getElementById("btnWizardDraftCurationPrev"),
  wizardDraftCurationPager: document.getElementById("wizardDraftCurationPager"),
  btnWizardDraftCurationNext: document.getElementById("btnWizardDraftCurationNext"),
  wizardDraftCurationProposalDialog: document.getElementById("wizardDraftCurationProposalDialog"),
  btnWizardDraftCurationProposalClose: document.getElementById("btnWizardDraftCurationProposalClose"),
  btnWizardDraftCurationProposalPrev: document.getElementById("btnWizardDraftCurationProposalPrev"),
  btnWizardDraftCurationProposalNext: document.getElementById("btnWizardDraftCurationProposalNext"),
  wizardDraftCurationProposalMeta: document.getElementById("wizardDraftCurationProposalMeta"),
  wizardDraftCurationCurrentCard: document.getElementById("wizardDraftCurationCurrentCard"),
  wizardDraftCurationSuggestedCard: document.getElementById("wizardDraftCurationSuggestedCard"),
  wizardDraftCurationContext: document.getElementById("wizardDraftCurationContext"),
  btnWizardDraftCurationToggleView: document.getElementById("btnWizardDraftCurationToggleView"),
  wizardDraftCurationDiffView: document.getElementById("wizardDraftCurationDiffView"),
  btnWizardDraftCurationReject: document.getElementById("btnWizardDraftCurationReject"),
  btnWizardDraftCurationPromote: document.getElementById("btnWizardDraftCurationPromote"),
  btnWizardDraftCurationPromoteAll: document.getElementById("btnWizardDraftCurationPromoteAll"),
  wizardDraftCurationProposalResult: document.getElementById("wizardDraftCurationProposalResult"),
  btnWizardDraftCurationMcpRefresh: document.getElementById("btnWizardDraftCurationMcpRefresh"),
  btnWizardDraftCurationMcpApply: document.getElementById("btnWizardDraftCurationMcpApply"),
  btnWizardDraftCurationMcpExport: document.getElementById("btnWizardDraftCurationMcpExport"),
  wizardDraftCurationMcpTarget: document.getElementById("wizardDraftCurationMcpTarget"),
  wizardDraftCurationMcpScope: document.getElementById("wizardDraftCurationMcpScope"),
  wizardDraftCurationMcpRole: document.getElementById("wizardDraftCurationMcpRole"),
  wizardDraftCurationMcpMutations: document.getElementById("wizardDraftCurationMcpMutations"),
  wizardDraftCurationMcpStatus: document.getElementById("wizardDraftCurationMcpStatus"),
  wizardDraftCurationTargets: document.getElementById("wizardDraftCurationTargets"),
  wizardDraftCurationMcpTargets: document.getElementById("wizardDraftCurationMcpTargets"),
  btnWizardPublish: document.getElementById("btnWizardPublish"),
  wizardPublishSummary: document.getElementById("wizardPublishSummary"),
  wizardReviewResult: document.getElementById("wizardReviewResult"),
  wizardPublishResult: document.getElementById("wizardPublishResult"),
  wizardPublishedHistory: document.getElementById("wizardPublishedHistory"),
  btnWizardVerify: document.getElementById("btnWizardVerify"),
  wizardVerifyResult: document.getElementById("wizardVerifyResult"),
  wizardVerifyLinks: document.getElementById("wizardVerifyLinks"),
  wizardRemapFile: document.getElementById("wizardRemapFile"),
  wizardRemapStatus: document.getElementById("wizardRemapStatus"),
  btnWizardActivateRefresh: document.getElementById("btnWizardActivateRefresh"),
  btnWizardGoLive: document.getElementById("btnWizardGoLive"),
  btnWizardExportMcp: document.getElementById("btnWizardExportMcp"),
  btnWizardManagedMcpApply: document.getElementById("btnWizardManagedMcpApply"),
  wizardMcpTarget: document.getElementById("wizardMcpTarget"),
  wizardMcpScope: document.getElementById("wizardMcpScope"),
  wizardMcpRole: document.getElementById("wizardMcpRole"),
  wizardMcpMutations: document.getElementById("wizardMcpMutations"),
  wizardActivationStatus: document.getElementById("wizardActivationStatus"),
  wizardMcpTargets: document.getElementById("wizardMcpTargets"),
  wizardDeveloperTools: document.getElementById("wizardDeveloperTools"),
  wizardDeveloperMode: document.getElementById("wizardDeveloperMode"),
  wizardDraftReason: document.getElementById("wizardDraftReason"),
  btnWizardDraftGoLive: document.getElementById("btnWizardDraftGoLive"),
  wizardDirectCleanup: document.getElementById("btnWizardDirectCleanup"),
  wizardGoLiveResult: document.getElementById("wizardGoLiveResult"),
  wizardOperateState: document.getElementById("wizardOperateState"),
  wizardGoLiveConfig: document.getElementById("wizardGoLiveConfig"),
  btnWizardOperateChat: document.getElementById("btnWizardOperateChat"),
  btnWizardOperateMemory: document.getElementById("btnWizardOperateMemory"),
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
  btnWizardReviewApprovePage: document.getElementById("btnWizardReviewApprovePage"),
  btnWizardReviewApproveAll: document.getElementById("btnWizardReviewApproveAll"),
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

const WIZARD_ACTION_LABELS = [
  "Create MNO Store",
  "Publish Reviewed Memory Set",
  "Export Selected Setup Bundle",
  "Approve and Close",
  "Restore Last Good Copy",
  "Build Review Draft",
  "Start Memory Runtime",
  "Check Readiness",
  "Open Memory Check",
  "Open Chat Test",
  "Use This Store",
  "File Checked",
  "Quick Edit",
  "Approve",
  "Reject",
  "Filter",
  "Next",
  "Previous",
  "Start Fresh",
  "Resume Last Run",
  "Check File",
];

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function formatWizardGuidanceHtml(text) {
  let html = escapeHtml(text);
  const labels = [...WIZARD_ACTION_LABELS].sort((left, right) => right.length - left.length);
  for (const label of labels) {
    const pattern = new RegExp(`\\b${escapeRegExp(label)}\\b`, "g");
    html = html.replace(pattern, `<span class="wizard-guidance-action">${escapeHtml(label)}</span>`);
  }
  return html;
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
        ? "Simple mode keeps setup and everyday memory use visible while hiding operator-heavy controls."
        : "Advanced mode shows operator diagnostics, developer tools, and full runtime detail.";
  }
}

function setUiMode(mode) {
  settings.uiMode = normalizeUiMode(mode);
  applyUIMode();
  saveSettings();
  // If the active tab is hidden in simple mode, fall back to setup
  if (settings.uiMode === "simple") {
    const activeTab = document.querySelector(".tab-btn.active");
    if (activeTab && (activeTab.classList.contains("trace-only") || activeTab.classList.contains("ops-only"))) {
      switchTab("setup");
    }
  }
}

function syncDesktopHomeAvailability() {
  if (!els.btnDesktopHome) {
    return;
  }
  const available = Boolean(window.desktopWorkspace && typeof window.desktopWorkspace.openDesktopHome === "function");
  els.btnDesktopHome.hidden = !available;
  els.btnDesktopHome.disabled = !available;
}

function requestedDesktopTab() {
  try {
    const params = new URLSearchParams(window.location.search || "");
    const tabId = String(params.get("desktopTab") || "").trim().toLowerCase();
    if (tabId && document.querySelector(`.tab-pane[data-pane="${tabId}"]`)) {
      return tabId;
    }
  } catch (_error) {
    // ignore
  }
  return "";
}

function requestedHcrRunId() {
  const match = /^\/curate\/([^/]+)\/?$/.exec(String(window.location.pathname || ""));
  if (!match) {
    return "";
  }
  try {
    return decodeURIComponent(match[1]).trim();
  } catch (_error) {
    return "";
  }
}

function initializeHcrMode() {
  const runId = requestedHcrRunId();
  state.hcrMode = Boolean(runId);
  state.hcrRunId = runId;
  document.body.classList.toggle("hcr-mode", state.hcrMode);
  if (state.hcrMode) {
    state.wizardVisibleStage = "review";
    document.title = "NumquamOblita Curation Room";
    const draftPanel = document.getElementById("wizardDraftCurationPanel");
    if (draftPanel) {
      draftPanel.open = false;
    }
  }
}

function hcrPreferredWizardStage(status = state.hcrStatus || {}) {
  const roomState = String(status.state || "").trim().toLowerCase();
  if (roomState === "ready_to_publish") return "publish";
  if (["published_unverified", "verification_blocked"].includes(roomState)) return "verify";
  if (["ready_to_activate", "ready"].includes(roomState)) return "activate";
  return "review";
}

/* ─── Tab Navigation ─── */

function switchTab(tabId, { loadData = true } = {}) {
  if (state.hcrMode) {
    tabId = "setup";
  }
  const btns = document.querySelectorAll(".tab-btn");
  const panes = document.querySelectorAll(".tab-pane");
  btns.forEach((btn) => {
    const isTarget = btn.getAttribute("data-tab") === tabId;
    btn.classList.toggle("active", isTarget);
    btn.setAttribute("aria-selected", isTarget ? "true" : "false");
  });
  panes.forEach((pane) => {
    pane.classList.toggle("active", pane.getAttribute("data-pane") === tabId);
  });
  try {
    window.localStorage.setItem("nq.ui.activeTab", tabId);
  } catch (_e) {
    // ignore
  }
  if (loadData) {
    ensureTabData(tabId).catch((error) => handleTabDataError(tabId, error));
  }
}

function activeTabId() {
  return document.querySelector(".tab-btn.active")?.getAttribute("data-tab") || "setup";
}

function handleTabDataError(tabId, error) {
  const message = error?.message || String(error || "unknown error");
  if (tabId === "memory") {
    renderMemoryError(message);
    return;
  }
  if (tabId === "ops" || tabId === "trace" || tabId === "chat") {
    showTraceError(message);
    return;
  }
  if (els.wizardImportStatus) {
    els.wizardImportStatus.textContent = `Setup refresh failed: ${message}`;
  }
}

function activeMemoryTabKey() {
  const activeSubtab = String(document.querySelector('.tab-pane[data-pane="memory"] .sub-tab-btn.active')?.getAttribute("data-subtab") || "mem-cards").trim();
  if (activeSubtab === "mem-graph") {
    return "memory-graph";
  }
  if (activeSubtab === "mem-proposals") {
    return "memory-proposals";
  }
  return "memory-cards";
}

async function refreshVisibleWizardStageData() {
  const runId = currentWizardRunId() || undefined;
  if (!runId) {
    return;
  }
  const visibleStage = String(state.wizardVisibleStage || state.wizardState?.stage_flow?.current_stage || "import").trim() || "import";
  if (visibleStage === "import") {
    await refreshWizardInputOptions(runId);
    return;
  }
  if (visibleStage === "review") {
    await loadWizardReviewCards();
    return;
  }
  if (visibleStage === "verify") {
    await refreshWizardRemapStatus(runId);
    return;
  }
  if (visibleStage === "activate") {
    await refreshWizardActivationStatus(runId);
  }
}

async function refreshSetupTabData() {
  if (!state.hcrMode) {
    await refreshState();
  }
  await refreshWizardState(state.hcrMode ? state.hcrRunId : undefined, {
    includeReview: false,
    includeInputOptions: false,
    includeActivation: false,
    includeRemap: false,
  });
  if (state.hcrMode) {
    await refreshHcrStatus();
    state.wizardVisibleStage = hcrPreferredWizardStage();
    renderWizardState();
  }
  await refreshVisibleWizardStageData();
}

async function refreshChatTabData() {
  await refreshDecisionCatalog();
  await refreshSessionAndState();
  if (!state.activeSessionId) {
    await ensureActiveSession();
    await refreshSessionAndState();
  }
}

async function refreshMemoryTabData() {
  const activeMemoryTab = activeMemoryTabKey();
  if (activeMemoryTab === "memory-graph") {
    await refreshMemoryGraph();
    return;
  }
  if (activeMemoryTab === "memory-proposals") {
    await refreshProposals();
    return;
  }
  if (state.memoryScope === "episodes") {
    await refreshEpisodes();
    return;
  }
  await refreshMemory();
}

async function refreshTraceTabData() {
  if (!state.tabDataLoaded.chat) {
    await refreshChatTabData();
    state.tabDataLoaded.chat = true;
    return;
  }
  await Promise.all([refreshRuntimeLedger(), refreshWhyPanel()]);
}

async function refreshOpsTabData() {
  await refreshOpsDeck();
}

async function ensureTabData(tabId, { force = false } = {}) {
  const normalized = String(tabId || "setup").trim() || "setup";
  const cacheKey = normalized === "memory" ? activeMemoryTabKey() : normalized;
  if (!force && state.tabDataLoaded[cacheKey]) {
    return;
  }
  if (!force && state.tabDataLoading[cacheKey]) {
    await state.tabDataLoading[cacheKey];
    return;
  }
  const task = (async () => {
    if (normalized === "setup") {
      await refreshSetupTabData();
    } else if (normalized === "chat") {
      await refreshChatTabData();
    } else if (normalized === "memory") {
      await refreshMemoryTabData();
    } else if (normalized === "trace") {
      await refreshTraceTabData();
    } else if (normalized === "ops") {
      await refreshOpsTabData();
    }
    state.tabDataLoaded[normalized] = true;
    state.tabDataLoaded[cacheKey] = true;
  })();
  state.tabDataLoading[cacheKey] = task;
  try {
    await task;
  } finally {
    delete state.tabDataLoading[cacheKey];
  }
}

function bindTabNavigation() {
  if (state.hcrMode) {
    switchTab("setup", { loadData: false });
    return;
  }
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tabId = btn.getAttribute("data-tab");
      if (tabId) switchTab(tabId);
    });
  });
  const requestedTab = requestedDesktopTab();
  if (requestedTab) {
    switchTab(requestedTab, { loadData: false });
    return;
  }
  // Restore last active tab from localStorage
  try {
    const saved = window.localStorage.getItem("nq.ui.activeTab");
    if (saved && document.querySelector(`.tab-pane[data-pane="${saved}"]`)) {
      // Don't restore trace/ops tabs if in simple mode
      if (settings.uiMode === "simple" && (saved === "trace" || saved === "ops")) {
        switchTab("setup");
      } else {
        switchTab(saved, { loadData: false });
      }
    }
  } catch (_e) {
    // ignore
  }
}

/* ─── Sub-Tab Navigation ─── */

function switchSubTab(groupEl, subtabId) {
  const parent = groupEl.closest(".tab-pane");
  if (!parent) return;
  parent.querySelectorAll(".sub-tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-subtab") === subtabId);
    btn.setAttribute("aria-selected", btn.getAttribute("data-subtab") === subtabId ? "true" : "false");
  });
  parent.querySelectorAll(".sub-pane").forEach((pane) => {
    pane.classList.toggle("active", pane.getAttribute("data-subpane") === subtabId);
  });
  const parentTabId = String(parent.getAttribute("data-pane") || "").trim();
  if (parentTabId) {
    ensureTabData(parentTabId).catch((error) => handleTabDataError(parentTabId, error));
  }
}

/* ─── Discrete Card Stepping ─── */

function bindDiscreteCardStepping() {
  const reviewList = document.getElementById("wizardReviewList");
  if (!reviewList) return;
  let stepCooldown = false;
  reviewList.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (stepCooldown) return;
    stepCooldown = true;
    setTimeout(() => { stepCooldown = false; }, 200);
    const cards = [...reviewList.querySelectorAll(".wizard-review-item")];
    if (!cards.length) return;
    const currentIndex = cards.findIndex((c) => c.classList.contains("review-focus"));
    const direction = e.deltaY > 0 ? 1 : -1;
    let nextIndex;
    if (currentIndex < 0) {
      nextIndex = direction > 0 ? 0 : cards.length - 1;
    } else {
      nextIndex = Math.max(0, Math.min(cards.length - 1, currentIndex + direction));
    }
    cards.forEach((c) => c.classList.remove("review-focus"));
    cards[nextIndex].classList.add("review-focus");
    // Snap the card into view using scrollTop (programmatic, not user scroll)
    const listRect = reviewList.getBoundingClientRect();
    const cardRect = cards[nextIndex].getBoundingClientRect();
    const offset = cardRect.top - listRect.top;
    reviewList.scrollTop += offset;
  }, { passive: false });
}

function bindSubTabNavigation() {
  document.querySelectorAll(".sub-tab-bar").forEach((bar) => {
    bar.addEventListener("click", (e) => {
      const btn = e.target.closest(".sub-tab-btn");
      if (!btn) return;
      const subtabId = btn.getAttribute("data-subtab");
      if (subtabId) switchSubTab(bar, subtabId);
    });
  });
}

/* ─── Wizard Step Navigation ─── */

function switchWizardStep(index) {
  const cards = document.querySelectorAll(".wizard-grid .wizard-card");
  cards.forEach((card, i) => {
    card.classList.toggle("wizard-active", i === index);
  });
  // Highlight clicked stage in rail
  const stages = document.querySelectorAll("#wizardStageRail .wizard-stage");
  stages.forEach((stage, i) => {
    stage.classList.toggle("wizard-nav-active", i === index);
  });
  const selectedStage = stages[index];
  state.wizardVisibleStage = String(selectedStage?.getAttribute("data-stage") || state.wizardVisibleStage || "import").trim() || "import";
  if (!state.tabDataLoading.setup) {
    refreshVisibleWizardStageData().catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  }
}

function bindWizardStepNavigation() {
  const rail = document.getElementById("wizardStageRail");
  if (!rail) return;
  rail.addEventListener("click", (e) => {
    const stage = e.target.closest(".wizard-stage");
    if (!stage) return;
    const stageId = String(stage.getAttribute("data-stage") || "").trim();
    if (!wizardStageIsReachable(stageId)) return;
    const index = [...rail.children].indexOf(stage);
    if (index >= 0) {
      state.wizardVisibleStage = stageId || state.wizardVisibleStage;
      switchWizardStep(index);
    }
  });
}

function autoSelectWizardStep() {
  const stages = document.querySelectorAll("#wizardStageRail .wizard-stage");
  let currentIndex = 0;
  let preferredIndex = -1;
  stages.forEach((stage, i) => {
    const stageId = String(stage.getAttribute("data-stage") || "").trim();
    if (stage.classList.contains("current")) currentIndex = i;
    if (stageId && stageId === state.wizardVisibleStage && wizardStageIsReachable(stageId)) preferredIndex = i;
  });
  let selectedIndex = preferredIndex >= 0 ? preferredIndex : currentIndex;
  if (state.hcrMode) {
    const requestedStage = hcrPreferredWizardStage();
    const hcrIndex = [...stages].findIndex((stage) => String(stage.getAttribute("data-stage") || "").trim() === requestedStage);
    if (hcrIndex >= 0) selectedIndex = hcrIndex;
  }
  const selectedStage = stages[selectedIndex];
  state.wizardVisibleStage = String(selectedStage?.getAttribute("data-stage") || "import").trim() || "import";
  switchWizardStep(selectedIndex);
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

function compactPathDisplay(value, limit = 52) {
  const text = String(value || "").trim();
  if (!text) {
    return "-";
  }
  if (text.length <= limit) {
    return text;
  }
  const separator = text.includes("\\") ? "\\" : "/";
  const segments = text.split(/[/\\]+/).filter(Boolean);
  const tail = segments.slice(-2).join(separator);
  if (tail && tail.length + 2 < limit) {
    return `…${separator}${tail}`;
  }
  return `…${text.slice(-(limit - 1))}`;
}

async function copyTextToClipboard(value) {
  const text = String(value || "").trim();
  if (!text) {
    throw new Error("Nothing to copy.");
  }
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const probe = document.createElement("textarea");
  probe.value = text;
  probe.setAttribute("readonly", "readonly");
  probe.style.position = "fixed";
  probe.style.opacity = "0";
  probe.style.pointerEvents = "none";
  document.body.appendChild(probe);
  probe.select();
  try {
    const ok = document.execCommand("copy");
    if (!ok) {
      throw new Error("Clipboard copy was blocked.");
    }
  } finally {
    probe.remove();
  }
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

function graphCssToken(value) {
  return String(value || "")
    .toLowerCase()
    .replaceAll("_", "-")
    .replace(/[^a-z0-9-]/g, "-");
}

function graphEdgeLabel(value) {
  const raw = String(value || "link").trim();
  if (!raw) {
    return "link";
  }
  return raw.replaceAll("_", " ");
}

function graphHashUnit(value) {
  let hash = 2166136261;
  const input = String(value || "");
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 100000) / 100000;
}

function graphHashSigned(value) {
  return (graphHashUnit(value) * 2) - 1;
}

function graphDegreeMap(nodes, links) {
  const degree = new Map();
  for (const node of nodes) {
    degree.set(String(node.atom_id || ""), Math.max(0, Number(node.degree || 0)));
  }
  for (const link of links) {
    const source = String(link.source || "");
    const target = String(link.target || "");
    if (degree.has(source)) {
      degree.set(source, Number(degree.get(source) || 0) + 1);
    }
    if (degree.has(target)) {
      degree.set(target, Number(degree.get(target) || 0) + 1);
    }
  }
  return degree;
}

function graphCurvedPath(source, target, curveSeed = "") {
  const dx = Number(target.x || 0) - Number(source.x || 0);
  const dy = Number(target.y || 0) - Number(source.y || 0);
  const distance = Math.max(1, Math.hypot(dx, dy));
  const normalX = -dy / distance;
  const normalY = dx / distance;
  const bend = Math.min(46, Math.max(0, distance * 0.16)) * graphHashSigned(curveSeed || `${source.x}:${source.y}:${target.x}:${target.y}`);
  const controlX = ((Number(source.x || 0) + Number(target.x || 0)) / 2) + (normalX * bend);
  const controlY = ((Number(source.y || 0) + Number(target.y || 0)) / 2) + (normalY * bend);
  return `M ${Number(source.x || 0).toFixed(2)} ${Number(source.y || 0).toFixed(2)} Q ${controlX.toFixed(2)} ${controlY.toFixed(2)} ${Number(target.x || 0).toFixed(2)} ${Number(target.y || 0).toFixed(2)}`;
}

function computeGraphLayout(nodes, links, width, height) {
  const safeWidth = Math.max(320, Number(width || 2400));
  const safeHeight = Math.max(220, Number(height || 1600));
  const layout = new Map();
  if (!nodes.length) {
    return layout;
  }
  if (nodes.length === 1) {
    layout.set(String(nodes[0].atom_id), { x: safeWidth * 0.5, y: safeHeight * 0.5 });
    return layout;
  }
  const centerX = safeWidth * 0.5;
  const centerY = safeHeight * 0.5;
  const degrees = graphDegreeMap(nodes, links);
  const nodeById = new Map(nodes.map((node) => [String(node.atom_id || ""), node]));
  const ordered = [...nodes].sort((left, right) => {
    const leftId = String(left.atom_id || "");
    const rightId = String(right.atom_id || "");
    const leftDegree = Number(degrees.get(leftId) || 0);
    const rightDegree = Number(degrees.get(rightId) || 0);
    if (rightDegree !== leftDegree) {
      return rightDegree - leftDegree;
    }
    const confidenceDelta = Number(right.confidence || 0) - Number(left.confidence || 0);
    if (Math.abs(confidenceDelta) > 0.001) {
      return confidenceDelta;
    }
    return leftId.localeCompare(rightId);
  });
  const positions = new Map();
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  ordered.forEach((node, index) => {
    const atomId = String(node.atom_id || "");
    const degree = Number(degrees.get(atomId) || 0);
    const linkedBias = degree > 0 ? 0.65 : 1.6;
    const spiralRadius = 36 * Math.sqrt(index + 1.2) * linkedBias;
    const spiralAngle = (index * goldenAngle) + (graphHashUnit(`${atomId}:angle`) * 0.8);
    const jitterX = graphHashSigned(`${atomId}:x`) * 18;
    const jitterY = graphHashSigned(`${atomId}:y`) * 14;
    positions.set(atomId, {
      x: centerX + (Math.cos(spiralAngle) * spiralRadius * 1.45) + jitterX,
      y: centerY + (Math.sin(spiralAngle) * spiralRadius * 0.92) + jitterY,
      vx: 0,
      vy: 0,
      degree,
    });
  });

  const edges = links
    .map((link) => ({
      source: String(link.source || ""),
      target: String(link.target || ""),
      kind: String(link.kind || "link"),
    }))
    .filter((edge) => positions.has(edge.source) && positions.has(edge.target));
  const maxDegree = Math.max(1, ...ordered.map((node) => Number(degrees.get(String(node.atom_id || "")) || 0)));
  const pairCount = ordered.length;
  const iterations = pairCount > 300 ? 38 : pairCount > 180 ? 48 : pairCount > 96 ? 56 : 72;
  const repulsion = pairCount > 300 ? 9600 : pairCount > 180 ? 8400 : pairCount > 96 ? 7200 : 6400;
  const damping = pairCount > 300 ? 0.86 : pairCount > 180 ? 0.84 : 0.81;
  const centerPull = pairCount > 300 ? 0.003 : pairCount > 180 ? 0.004 : 0.006;

  for (let step = 0; step < iterations; step += 1) {
    const alpha = 1 - (step / iterations);
    for (let index = 0; index < ordered.length; index += 1) {
      const leftId = String(ordered[index]?.atom_id || "");
      const left = positions.get(leftId);
      if (!left) {
        continue;
      }
      for (let inner = index + 1; inner < ordered.length; inner += 1) {
        const rightId = String(ordered[inner]?.atom_id || "");
        const right = positions.get(rightId);
        if (!right) {
          continue;
        }
        const dx = right.x - left.x;
        const dy = right.y - left.y;
        const distanceSquared = (dx * dx) + (dy * dy) + 24;
        const distance = Math.sqrt(distanceSquared);
        const directionX = dx / distance;
        const directionY = dy / distance;
        let force = (repulsion * alpha) / distanceSquared;
        if (left.degree === 0 && right.degree === 0) {
          force *= 0.56;
        }
        left.vx -= directionX * force;
        left.vy -= directionY * force;
        right.vx += directionX * force;
        right.vy += directionY * force;
      }
    }

    for (const edge of edges) {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      if (!source || !target) {
        continue;
      }
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const directionX = dx / distance;
      const directionY = dy / distance;
      const sourceDegree = Number(degrees.get(edge.source) || 0);
      const targetDegree = Number(degrees.get(edge.target) || 0);
      const desiredLength = edge.kind === "conflict"
        ? 140
        : 90 + Math.min(60, Math.abs(sourceDegree - targetDegree) * 8);
      const pull = (distance - desiredLength) * 0.012 * (0.7 + (alpha * 0.9));
      source.vx += directionX * pull;
      source.vy += directionY * pull;
      target.vx -= directionX * pull;
      target.vy -= directionY * pull;
    }

    for (const node of ordered) {
      const atomId = String(node.atom_id || "");
      const point = positions.get(atomId);
      if (!point) {
        continue;
      }
      const degree = Number(degrees.get(atomId) || 0);
      const gravity = degree > 0 ? 0.42 : 0.15;
      point.vx += (centerX - point.x) * centerPull * gravity * alpha;
      point.vy += (centerY - point.y) * centerPull * gravity * alpha;
      point.vx *= damping;
      point.vy *= damping;
      point.x += point.vx;
      point.y += point.vy;
    }
  }

  // Collision resolution — guarantee minimum separation
  const collisionPasses = 12;
  const minSep = 28;
  for (let pass = 0; pass < collisionPasses; pass += 1) {
    for (let i = 0; i < ordered.length; i += 1) {
      const aId = String(ordered[i]?.atom_id || "");
      const a = positions.get(aId);
      if (!a) continue;
      const aDeg = Number(degrees.get(aId) || 0);
      const aR = aDeg <= 0 ? 3.2 : 7.2 + Math.min(9, aDeg * 1.2);
      for (let j = i + 1; j < ordered.length; j += 1) {
        const bId = String(ordered[j]?.atom_id || "");
        const b = positions.get(bId);
        if (!b) continue;
        const bDeg = Number(degrees.get(bId) || 0);
        const bR = bDeg <= 0 ? 3.2 : 7.2 + Math.min(9, bDeg * 1.2);
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.max(0.5, Math.hypot(dx, dy));
        const needed = aR + bR + minSep;
        if (dist < needed) {
          const overlap = (needed - dist) * 0.5;
          const nx = dx / dist;
          const ny = dy / dist;
          a.x -= nx * overlap;
          a.y -= ny * overlap;
          b.x += nx * overlap;
          b.y += ny * overlap;
        }
      }
    }
  }

  const bounds = graphLayoutBounds(
    ordered.map((node) => ({
      atom_id: String(node.atom_id || ""),
      degree: Number(degrees.get(String(node.atom_id || "")) || 0),
    })),
    positions,
  );
  const centerBoundsX = (bounds.minX + bounds.maxX) / 2;
  const centerBoundsY = (bounds.minY + bounds.maxY) / 2;
  const spanX = Math.max(180, bounds.maxX - bounds.minX);
  const spanY = Math.max(140, bounds.maxY - bounds.minY);
  const scale = Math.max(
    0.38,
    Math.min(1.4, Math.min((safeWidth - 92) / spanX, (safeHeight - 78) / spanY)),
  );

  for (const node of ordered) {
    const atomId = String(node.atom_id || "");
    const point = positions.get(atomId);
    if (!point) {
      continue;
    }
    const x = centerX + ((point.x - centerBoundsX) * scale);
    const y = centerY + ((point.y - centerBoundsY) * scale);
    layout.set(atomId, {
      x: Math.max(22, Math.min(safeWidth - 22, x)),
      y: Math.max(22, Math.min(safeHeight - 22, y)),
    });
  }
  return layout;
}

function computeNeighborhoodLayout(rootId, nodes, width, height) {
  const safeWidth = Math.max(320, Number(width || 1000));
  const safeHeight = Math.max(260, Number(height || 540));
  const layout = new Map();
  if (!nodes.length) {
    return layout;
  }
  const centerX = safeWidth * 0.5;
  const centerY = safeHeight * 0.48;
  layout.set(String(rootId), { x: centerX, y: centerY });
  const others = nodes.filter((node) => String(node.atom_id || "") !== String(rootId));
  if (!others.length) {
    return layout;
  }

  const depthOne = others.filter((node) => Number(node.distance || 1) <= 1);
  const depthTwo = others.filter((node) => Number(node.distance || 1) > 1);
  const maxRadius = Math.min(safeWidth, safeHeight) * 0.38;

  const placeRing = (ring, radius) => {
    if (!ring.length) return;
    const edgeRank = { conflict: 0, constellation: 1, narrative_arc: 2, link: 3 };
    const sorted = [...ring].sort((a, b) => {
      const aEdge = String(a.via_edge_kind || "link");
      const bEdge = String(b.via_edge_kind || "link");
      return (edgeRank[aEdge] ?? 99) - (edgeRank[bEdge] ?? 99);
    });
    sorted.forEach((node, index) => {
      const atomId = String(node.atom_id || "");
      const angle = ((index / sorted.length) * Math.PI * 2) - (Math.PI / 2);
      const jitter = graphHashSigned(`${atomId}:radial`) * radius * 0.08;
      layout.set(atomId, {
        x: Math.max(24, Math.min(safeWidth - 24, centerX + Math.cos(angle) * (radius + jitter))),
        y: Math.max(24, Math.min(safeHeight - 24, centerY + Math.sin(angle) * (radius + jitter))),
      });
    });
  };

  const innerRadius = depthTwo.length > 0 ? maxRadius * 0.55 : maxRadius * 0.7;
  placeRing(depthOne, innerRadius);
  placeRing(depthTwo, maxRadius * 0.92);
  return layout;
}

function graphViewportSize(svgEl) {
  const viewBox = svgEl?.viewBox?.baseVal;
  return {
    width: Math.max(320, Number(viewBox?.width || 2400)),
    height: Math.max(220, Number(viewBox?.height || 1600)),
  };
}

function graphLayoutSignature(nodes, links) {
  const nodeSig = nodes.map((node) => String(node?.atom_id || "")).join("|");
  const linkSig = links
    .map((link) => `${String(link?.source || "")}:${String(link?.target || "")}:${String(link?.kind || "link")}`)
    .join("|");
  return `${nodeSig}::${linkSig}`;
}

function getMemoryGraphLayout(nodes, links, width, height) {
  const signature = graphLayoutSignature(nodes, links);
  const cached = state.memoryGraphLayoutCache || {};
  if (
    String(cached.signature || "") === signature
    && Number(cached.width || 0) === Number(width || 0)
    && Number(cached.height || 0) === Number(height || 0)
    && cached.layout instanceof Map
  ) {
    return cached.layout;
  }
  const layout = computeGraphLayout(nodes, links, width, height);
  state.memoryGraphLayoutCache = {
    signature,
    width: Number(width || 0),
    height: Number(height || 0),
    layout,
  };
  return layout;
}

function graphLayoutBounds(nodes, layout) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of nodes) {
    const atomId = String(node?.atom_id || "");
    const point = layout.get(atomId);
    if (!point) {
      continue;
    }
    const radius = 12 + Math.min(16, Number(node?.degree || 0) * 1.6);
    minX = Math.min(minX, point.x - radius);
    minY = Math.min(minY, point.y - radius);
    maxX = Math.max(maxX, point.x + radius);
    maxY = Math.max(maxY, point.y + radius);
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(maxX) || !Number.isFinite(maxY)) {
    return { minX: 0, minY: 0, maxX: 1000, maxY: 540 };
  }
  return { minX, minY, maxX, maxY };
}

function fitMemoryGraphView(nodes, layout, width, height) {
  const bounds = graphLayoutBounds(nodes, layout);
  const spanX = Math.max(160, bounds.maxX - bounds.minX);
  const spanY = Math.max(140, bounds.maxY - bounds.minY);
  const paddingX = Math.max(76, width * 0.12);
  const paddingY = Math.max(64, height * 0.14);
  const scale = Math.max(0.18, Math.min(1.6, Math.min((width - paddingX * 2) / spanX, (height - paddingY * 2) / spanY)));
  const centerX = (bounds.minX + bounds.maxX) / 2;
  const centerY = (bounds.minY + bounds.maxY) / 2;
  return {
    scale,
    offsetX: width * 0.5 - centerX * scale,
    offsetY: height * 0.5 - centerY * scale,
  };
}

function ensureMemoryGraphView(nodes, links, layout, width, height) {
  const signature = `${graphLayoutSignature(nodes, links)}::${Math.round(width)}x${Math.round(height)}`;
  const current = state.memoryGraphView || {};
  if (String(current.signature || "") === signature) {
    return;
  }
  const fitted = fitMemoryGraphView(nodes, layout, width, height);
  state.memoryGraphView = {
    scale: fitted.scale,
    offsetX: fitted.offsetX,
    offsetY: fitted.offsetY,
    baseScale: fitted.scale,
    baseOffsetX: fitted.offsetX,
    baseOffsetY: fitted.offsetY,
    signature,
  };
}

function resetMemoryGraphView() {
  const current = state.memoryGraphView || {};
  state.memoryGraphView = {
    ...current,
    scale: Number(current.baseScale || 1),
    offsetX: Number(current.baseOffsetX || 0),
    offsetY: Number(current.baseOffsetY || 0),
  };
}

function fitMemoryGraphToCurrentData() {
  if (!els.memoryGraphSvg) {
    return;
  }
  const nodes = Array.isArray(state.memoryGraph.nodes) ? state.memoryGraph.nodes : [];
  const links = Array.isArray(state.memoryGraph.links) ? state.memoryGraph.links : [];
  const { width, height } = graphViewportSize(els.memoryGraphSvg);
  const layout = getMemoryGraphLayout(nodes, links, width, height);
  const fitted = fitMemoryGraphView(nodes, layout, width, height);
  state.memoryGraphView = {
    ...(state.memoryGraphView || {}),
    scale: fitted.scale,
    offsetX: fitted.offsetX,
    offsetY: fitted.offsetY,
    baseScale: fitted.scale,
    baseOffsetX: fitted.offsetX,
    baseOffsetY: fitted.offsetY,
  };
}

function centerMemoryGraphOnNode(atomId) {
  if (!els.memoryGraphSvg) {
    return;
  }
  const normalized = String(atomId || "").trim();
  if (!normalized) {
    return;
  }
  const nodes = Array.isArray(state.memoryGraph.nodes) ? state.memoryGraph.nodes : [];
  const links = Array.isArray(state.memoryGraph.links) ? state.memoryGraph.links : [];
  const { width, height } = graphViewportSize(els.memoryGraphSvg);
  const layout = getMemoryGraphLayout(nodes, links, width, height);
  const point = layout.get(normalized);
  if (!point) {
    return;
  }
  const current = state.memoryGraphView || { scale: 1, offsetX: 0, offsetY: 0 };
  state.memoryGraphView = {
    ...current,
    offsetX: width * 0.5 - point.x * Number(current.scale || 1),
    offsetY: height * 0.46 - point.y * Number(current.scale || 1),
  };
}

function setMemoryGraphZoom(deltaScale, anchorClientX = null, anchorClientY = null) {
  if (!els.memoryGraphSvg) {
    return;
  }
  const current = state.memoryGraphView || { scale: 1, offsetX: 0, offsetY: 0 };
  const oldScale = Math.max(0.12, Number(current.scale || 1));
  const nextScale = Math.max(0.12, Math.min(5.0, oldScale * deltaScale));
  if (Math.abs(nextScale - oldScale) < 0.001) {
    return;
  }
  const rect = els.memoryGraphSvg.getBoundingClientRect();
  const { width, height } = graphViewportSize(els.memoryGraphSvg);
  const anchorX = rect.width > 0 && anchorClientX !== null
    ? ((anchorClientX - rect.left) / rect.width) * width
    : width * 0.5;
  const anchorY = rect.height > 0 && anchorClientY !== null
    ? ((anchorClientY - rect.top) / rect.height) * height
    : height * 0.5;
  state.memoryGraphView = {
    ...current,
    scale: nextScale,
    offsetX: anchorX - (nextScale / oldScale) * (anchorX - Number(current.offsetX || 0)),
    offsetY: anchorY - (nextScale / oldScale) * (anchorY - Number(current.offsetY || 0)),
  };
}

function renderMemoryGraphViewportMeta(selectedLinkCount = 0, visibleLabelCount = 0) {
  if (!els.memoryGraphViewportMeta) {
    return;
  }
  const current = state.memoryGraphView || {};
  const scale = Math.round(Number(current.scale || 1) * 100);
  const fragments = [`zoom ${scale}%`];
  if (selectedLinkCount > 0) {
    fragments.push(`${selectedLinkCount} linked`);
  }
  if (visibleLabelCount > 0) {
    fragments.push(`${visibleLabelCount} labels`);
  }
  fragments.push("drag to pan");
  els.memoryGraphViewportMeta.textContent = fragments.join(" • ");
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
    `<div class="memory-graph-detail-kicker">${escapeHtml(String(node.kind || "node").replace(/_/g, " "))}</div>` +
    `<strong class="memory-graph-detail-title">${escapeHtml(String(node.summary || selectedId))}</strong>` +
    `<div class="memory-graph-detail-chip-row">` +
    `<span class="memory-graph-detail-chip">confidence ${Number(node.confidence || 0).toFixed(2)}</span>` +
    (linked.length > 0 ? `<span class="memory-graph-detail-chip">${linked.length} connections</span>` : `<span class="memory-graph-detail-chip">isolated</span>`) +
    `</div>` +
    `<div class="memory-graph-detail-actions">` +
    `<button class="btn ghost" id="btnGraphDetailNeighbors" type="button">Show neighbors</button>` +
    `<button class="btn ghost" id="btnGraphDetailDismiss" type="button">Dismiss</button>` +
    `</div>`;
  els.memoryGraphDetail.classList.add("visible");
  const dismissBtn = document.getElementById("btnGraphDetailDismiss");
  dismissBtn?.addEventListener("click", () => {
    els.memoryGraphDetail.classList.remove("visible");
  });
  const neighborsBtn = document.getElementById("btnGraphDetailNeighbors");
  neighborsBtn?.addEventListener("click", () => {
    openNeighborhoodDrawer();
  });
}

function positionFloatingCard(event) {
  if (!els.memoryGraphDetail) {
    return;
  }
  const card = els.memoryGraphDetail;
  const margin = 16;
  const viewportW = window.innerWidth;
  const viewportH = window.innerHeight;
  card.style.removeProperty("left");
  card.style.removeProperty("right");
  card.style.removeProperty("top");
  card.style.removeProperty("bottom");
  requestAnimationFrame(() => {
    const rect = card.getBoundingClientRect();
    const cardW = rect.width || 320;
    const cardH = rect.height || 200;
    let x = event.clientX + margin;
    let y = event.clientY + margin;
    if (x + cardW > viewportW - margin) {
      x = event.clientX - cardW - margin;
    }
    if (y + cardH > viewportH - margin) {
      y = event.clientY - cardH - margin;
    }
    x = Math.max(margin, x);
    y = Math.max(margin, y);
    card.style.left = `${x}px`;
    card.style.top = `${y}px`;
  });
}

function dismissFloatingCard() {
  if (els.memoryGraphDetail) {
    els.memoryGraphDetail.classList.remove("visible");
  }
}

function openNeighborhoodDrawer() {
  els.memoryNeighborhoodPanel?.classList.add("open");
  els.memoryNeighborhoodBackdrop?.classList.add("visible");
  refreshMemoryNeighborhood().catch((error) => renderMemoryError(error.message));
}

function closeNeighborhoodDrawer() {
  els.memoryNeighborhoodPanel?.classList.remove("open");
  els.memoryNeighborhoodBackdrop?.classList.remove("visible");
}

function beginNeighborhoodPan(event) {
  if (!(event instanceof PointerEvent) || event.button !== 0) return;
  if (event.target instanceof Element && event.target.closest(".graph-node")) return;
  const viewport = els.memoryNeighborhoodViewport;
  if (!viewport || !els.memoryNeighborhoodSvg) return;
  event.preventDefault();
  state.neighborhoodPan = {
    active: true, dragging: false,
    pointerId: event.pointerId,
    startClientX: event.clientX, startClientY: event.clientY,
    startOffsetX: Number((state.neighborhoodView || {}).offsetX || 0),
    startOffsetY: Number((state.neighborhoodView || {}).offsetY || 0),
  };
}

function continueNeighborhoodPan(event) {
  const pan = state.neighborhoodPan || {};
  if (!pan.active || !(event instanceof PointerEvent) || pan.pointerId !== event.pointerId) return;
  const clientDx = event.clientX - Number(pan.startClientX || 0);
  const clientDy = event.clientY - Number(pan.startClientY || 0);
  if (!pan.dragging) {
    if (Math.hypot(clientDx, clientDy) < 5) return;
    pan.dragging = true;
    els.memoryNeighborhoodViewport?.classList.add("is-panning");
  }
  const svg = els.memoryNeighborhoodSvg;
  const rect = svg.getBoundingClientRect();
  const vb = svg.viewBox.baseVal;
  const w = Math.max(320, Number(vb?.width || 1000));
  const h = Math.max(220, Number(vb?.height || 700));
  const dx = rect.width > 0 ? clientDx * (w / rect.width) : 0;
  const dy = rect.height > 0 ? clientDy * (h / rect.height) : 0;
  state.neighborhoodView = {
    ...(state.neighborhoodView || { scale: 1 }),
    offsetX: Number(pan.startOffsetX || 0) + dx,
    offsetY: Number(pan.startOffsetY || 0) + dy,
  };
  renderMemoryNeighborhood();
}

function endNeighborhoodPan(event) {
  const pan = state.neighborhoodPan || {};
  if (!pan.active) return;
  state.neighborhoodPan = { active: false, dragging: false, pointerId: null, startClientX: 0, startClientY: 0, startOffsetX: 0, startOffsetY: 0 };
  els.memoryNeighborhoodViewport?.classList.remove("is-panning");
}

function neighborhoodGraphNodes() {
  const payload = state.memoryNeighborhood || {};
  const root = payload.root && typeof payload.root === "object" ? payload.root : null;
  const neighbors = Array.isArray(payload.neighbors) ? payload.neighbors : [];
  if (!root) {
    return [];
  }
  return [{ ...root, distance: 0 }, ...neighbors];
}

function renderMemoryNeighborhood() {
  if (!els.memoryNeighborhoodMeta || !els.memoryNeighborhoodSvg || !els.memoryNeighborhoodList) {
    return;
  }
  const selectedId = String(state.selectedGraphAtomId || "").trim();
  const payload = state.memoryNeighborhood || {};
  const root = payload.root && typeof payload.root === "object" ? payload.root : null;
  const neighbors = Array.isArray(payload.neighbors) ? payload.neighbors : [];
  const links = Array.isArray(payload.links) ? payload.links : [];
  const truncation = payload.truncation && typeof payload.truncation === "object" ? payload.truncation : {};
  const truncationFlags = [
    truncation.node_limit_hit ? "node limit" : "",
    truncation.link_limit_hit ? "link limit" : "",
    truncation.request_budget_hit ? "request budget" : "",
    truncation.dropped_shared_language ? "shared language dropped" : "",
  ].filter(Boolean);

  if (!selectedId) {
    els.memoryNeighborhoodMeta.textContent = "Pick a node or card to load a bounded local graph.";
    els.memoryNeighborhoodSvg.innerHTML =
      '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" fill="#5a6972" font-family="Courier New, Courier, monospace" font-size="13">No local graph root selected yet.</text>';
    els.memoryNeighborhoodList.classList.add("empty");
    els.memoryNeighborhoodList.textContent = "Select a card or map node to inspect local neighbors.";
    return;
  }
  if (payload.loading) {
    els.memoryNeighborhoodMeta.textContent = "Loading local graph around the selected node.";
    els.memoryNeighborhoodSvg.innerHTML =
      '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" fill="#5a6972" font-family="Courier New, Courier, monospace" font-size="13">Loading bounded neighborhood…</text>';
    els.memoryNeighborhoodList.classList.add("empty");
    els.memoryNeighborhoodList.textContent = "Pulling local graph details from the native endpoint.";
    return;
  }
  if (payload.error) {
    els.memoryNeighborhoodMeta.textContent = "Local graph could not be loaded.";
    els.memoryNeighborhoodSvg.innerHTML =
      '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" fill="#9b3a2f" font-family="Courier New, Courier, monospace" font-size="13">Local graph unavailable for the current selection.</text>';
    els.memoryNeighborhoodList.classList.add("empty");
    els.memoryNeighborhoodList.textContent = String(payload.error);
    return;
  }
  if (!root) {
    els.memoryNeighborhoodMeta.textContent = "Select a graph node to inspect local links.";
    els.memoryNeighborhoodSvg.innerHTML =
      '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" fill="#5a6972" font-family="Courier New, Courier, monospace" font-size="13">No local graph payload available.</text>';
    els.memoryNeighborhoodList.classList.add("empty");
    els.memoryNeighborhoodList.textContent = "Select a graph node to load bounded neighborhood results.";
    return;
  }

  const nodes = neighborhoodGraphNodes();
  const viewBox = els.memoryNeighborhoodSvg.viewBox.baseVal;
  const width = Number(viewBox?.width || 1000);
  const height = Number(viewBox?.height || 540);
  const rootId = String(root.atom_id || selectedId);
  const layout = computeNeighborhoodLayout(rootId, nodes, width, height);
  const nodeById = new Map(nodes.map((item) => [String(item.atom_id), item]));

  els.memoryNeighborhoodMeta.textContent =
    `${neighbors.length} local nodes • ${links.length} links • depth ${Number(payload.depth || 1)} • requests ${Number(payload.requestsUsed || 0)}` +
    `${payload.truncated ? ` • truncated: ${truncationFlags.join(", ") || "yes"}` : ""}`;

  const linkSvg = links
    .map((link) => {
      const source = layout.get(String(link.source || ""));
      const target = layout.get(String(link.target || ""));
      if (!source || !target) {
        return "";
      }
      return `<path class="graph-link kind-${escapeHtml(graphCssToken(link.kind || "link"))}" d="${graphCurvedPath(source, target, `${String(link.source || "")}:${String(link.target || "")}:${String(link.kind || "link")}:neighborhood`)}"></path>`;
    })
    .join("");

  const nodeSvg = nodes
    .map((node) => {
      const atomId = String(node.atom_id || "");
      const point = layout.get(atomId);
      if (!point) {
        return "";
      }
      const radius = atomId === rootId ? 16 : 9 + Math.min(5, Number(node.distance || 1));
      const hitRadius = Math.max(16, radius + 8);
      const classes = [
        "graph-node",
        atomId === rootId ? "is-root" : "",
        atomId === selectedId ? "selected" : "",
        `kind-${graphCssToken(node.kind || "")}`,
        `status-${graphCssToken(node.status || "")}`,
        atomId === rootId ? "" : `distance-${Math.min(2, Math.max(1, Number(node.distance || 1)))}`,
      ]
        .filter(Boolean)
        .join(" ");
      const label = atomId === rootId ? "root" : summarizeGraphNode(node);
      return (
        `<g class="${classes}" data-neighbor-atom-id="${escapeHtml(atomId)}">` +
        `<circle class="graph-node-hit" cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="${hitRadius.toFixed(2)}" fill="transparent" stroke="none"></circle>` +
        `<circle cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="${radius.toFixed(2)}"></circle>` +
        `<text x="${(point.x + radius + 5).toFixed(2)}" y="${(point.y + 3).toFixed(2)}">${escapeHtml(label)}</text>` +
        `</g>`
      );
    })
    .join("");
  const nView = state.neighborhoodView || { scale: 1, offsetX: 0, offsetY: 0 };
  els.memoryNeighborhoodSvg.innerHTML =
    `<g transform="translate(${Number(nView.offsetX || 0).toFixed(2)} ${Number(nView.offsetY || 0).toFixed(2)})">` +
    `<g transform="scale(${Number(nView.scale || 1).toFixed(3)})">` +
    `${linkSvg}${nodeSvg}` +
    `</g></g>`;
  for (const item of els.memoryNeighborhoodSvg.querySelectorAll("[data-neighbor-atom-id]")) {
    item.addEventListener("click", (clickEvent) => {
      const pan = state.neighborhoodPan || {};
      if (pan.dragging) return;
      const atomId = String(item.getAttribute("data-neighbor-atom-id") || "").trim();
      const node = nodeById.get(atomId);
      if (!atomId || !node) {
        return;
      }
      state.selectedGraphAtomId = atomId;
      renderMemoryGraphDetail();
      positionFloatingCard(clickEvent);
    });
  }

  const rootSummary = trimDisplay(root.summary || "", 180);
  const neighborRows = neighbors.length
    ? neighbors
        .map((node) => {
          const atomId = String(node.atom_id || "");
          return (
            `<button type="button" class="memory-neighborhood-row" data-neighbor-row-id="${escapeHtml(atomId)}">` +
            `<div class="memory-neighborhood-row-head">` +
            `<strong>${escapeHtml(String(node.card_id || atomId))}</strong>` +
            `<span>depth ${Number(node.distance || 1)} • ${escapeHtml(graphEdgeLabel(node.via_edge_kind || "link"))}</span>` +
            `</div>` +
            `<div class="memory-neighborhood-row-body">${escapeHtml(trimDisplay(node.summary || "", 160))}</div>` +
            `<div class="memory-neighborhood-row-meta">kind=${escapeHtml(String(node.kind || "-"))} status=${escapeHtml(String(node.status || "-"))}</div>` +
            `</button>`
          );
        })
        .join("")
    : '<div class="memory-empty">No additional neighbors inside the current bounds.</div>';
  els.memoryNeighborhoodList.classList.remove("empty");
  els.memoryNeighborhoodList.innerHTML =
    `<div class="memory-neighborhood-root">` +
    `<div class="memory-neighborhood-root-label">Root</div>` +
    `<strong>${escapeHtml(String(root.card_id || rootId))}</strong>` +
    `<div>${escapeHtml(rootSummary || "No root summary available.")}</div>` +
    `</div>` +
    `<div class="memory-neighborhood-list-head">` +
    `<strong>Neighbor paths</strong>` +
    `<span>${neighbors.length} visible</span>` +
    `</div>` +
    neighborRows;
  for (const item of els.memoryNeighborhoodList.querySelectorAll("[data-neighbor-row-id]")) {
    item.addEventListener("click", () => {
      const atomId = String(item.getAttribute("data-neighbor-row-id") || "").trim();
      const node = nodeById.get(atomId);
      if (!atomId || !node) {
        return;
      }
      selectGraphNode(atomId, node.card_id || "");
    });
  }
}

function renderMemoryGraph() {
  if (!els.memoryGraphSvg || !els.memoryGraphMeta) {
    return;
  }
  const allNodes = Array.isArray(state.memoryGraph.nodes) ? state.memoryGraph.nodes : [];
  const links = Array.isArray(state.memoryGraph.links) ? state.memoryGraph.links : [];
  const truncated = !!state.memoryGraph.truncated;
  const total = Number(state.memoryGraph.total || allNodes.length);
  const snapshotAvailable = state.memoryGraph.snapshotAvailable !== false;

  // Filter isolated nodes if toggle is active
  const hideIsolated = !!state.memoryGraphHideIsolated;
  const linkedIds = new Set();
  for (const link of links) {
    linkedIds.add(String(link.source || ""));
    linkedIds.add(String(link.target || ""));
  }
  const nodes = hideIsolated
    ? allNodes.filter((node) => {
        const id = String(node.atom_id || "");
        if (linkedIds.has(id)) return true;
        // Keep top 30 isolated by confidence as dim background stars
        return false;
      })
    : allNodes;

  const hiddenCount = allNodes.length - nodes.length;
  els.memoryGraphMeta.textContent =
    `${nodes.length} nodes • ${links.length} links${hiddenCount > 0 ? ` • ${hiddenCount} isolated hidden` : ""}${truncated ? ` • truncated from ${total}` : ""}` +
    `${snapshotAvailable ? "" : " • snapshot unavailable (showing conflict links only)"}`;

  if (!nodes.length) {
    els.memoryGraphSvg.innerHTML =
      '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" fill="#5a6972" font-family="Courier New, Courier, monospace" font-size="13">No map nodes for current memory filters.</text>';
    renderMemoryGraphViewportMeta(0, 0);
    renderMemoryGraphDetail();
    return;
  }

  const { width, height } = graphViewportSize(els.memoryGraphSvg);
  const layout = getMemoryGraphLayout(nodes, links, width, height);
  ensureMemoryGraphView(nodes, links, layout, width, height);
  const selectedId = String(state.selectedGraphAtomId || "");
  const nodeById = new Map(nodes.map((item) => [String(item.atom_id), item]));
  const degrees = graphDegreeMap(nodes, links);
  const connectedIds = new Set(selectedId ? [selectedId] : []);
  const connectedLinkKeys = new Set();
  if (selectedId) {
    links.forEach((link, index) => {
      const sourceId = String(link.source || "");
      const targetId = String(link.target || "");
      if (sourceId === selectedId || targetId === selectedId) {
        connectedIds.add(sourceId);
        connectedIds.add(targetId);
        connectedLinkKeys.add(String(index));
      }
    });
  }
  const topLabelIds = new Set(
    [...nodes]
      .sort((left, right) => {
        const leftId = String(left.atom_id || "");
        const rightId = String(right.atom_id || "");
        const degreeDelta = Number(degrees.get(rightId) || 0) - Number(degrees.get(leftId) || 0);
        if (degreeDelta !== 0) {
          return degreeDelta;
        }
        return Number(right.confidence || 0) - Number(left.confidence || 0);
      })
      .slice(0, selectedId ? 6 : 10)
      .map((node) => String(node.atom_id || ""))
  );

  const linkSvg = links
    .map((link, index) => {
      const source = layout.get(String(link.source || ""));
      const target = layout.get(String(link.target || ""));
      if (!source || !target) {
        return "";
      }
      const kindClass = graphCssToken(String(link.kind || "link"));
      const activeClass = connectedLinkKeys.has(String(index)) ? " active" : "";
      const dimClass = selectedId && !connectedLinkKeys.has(String(index)) ? " dim" : "";
      const pathD = graphCurvedPath(source, target, `${String(link.source || "")}:${String(link.target || "")}:${String(link.kind || "link")}`);
      return `<path class="graph-link kind-${escapeHtml(kindClass)}${activeClass}${dimClass}" d="${pathD}"></path>`;
    })
    .join("");

  const nodeSvg = nodes
    .map((node) => {
      const atomId = String(node.atom_id || "");
      const point = layout.get(atomId);
      if (!point) {
        return "";
      }
      const degree = Number(degrees.get(atomId) || 0);
      const selectedClass = selectedId === atomId ? " selected" : "";
      const connectedClass = connectedIds.has(atomId) && atomId !== selectedId ? " connected" : "";
      const dimClass = selectedId && !connectedIds.has(atomId) ? " dim" : "";
      const isolatedClass = degree <= 0 ? " is-isolated" : "";
      const kindClass = ` kind-${graphCssToken(String(node.kind || ""))}`;
      const statusClass = ` status-${graphCssToken(String(node.status || ""))}`;
      const radius = degree <= 0 ? 3.2 : 7.2 + Math.min(9, degree * 1.2);
      const hitRadius = Math.max(14, radius + 8);
      const label = summarizeGraphNode(node);
      const showLabel = nodes.length <= 14 || selectedId === atomId || connectedIds.has(atomId) || topLabelIds.has(atomId);
      return (
        `<g class="graph-node${selectedClass}${connectedClass}${dimClass}${isolatedClass}${kindClass}${statusClass}" data-atom-id="${escapeHtml(atomId)}">` +
        `<circle class="graph-node-hit" cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="${hitRadius.toFixed(2)}" fill="transparent" stroke="none"></circle>` +
        `<circle cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="${radius.toFixed(2)}"></circle>` +
        (showLabel
          ? `<text class="graph-label${selectedId && !connectedIds.has(atomId) && selectedId !== atomId ? " is-muted" : ""}" x="${(point.x + radius + 5).toFixed(2)}" y="${(point.y + 3).toFixed(2)}">${escapeHtml(label)}</text>`
          : "") +
        `</g>`
      );
    })
    .join("");

  const view = state.memoryGraphView || { scale: 1, offsetX: 0, offsetY: 0 };
  els.memoryGraphSvg.innerHTML =
    `<g transform="translate(${Number(view.offsetX || 0).toFixed(2)} ${Number(view.offsetY || 0).toFixed(2)})">` +
    `<g transform="scale(${Number(view.scale || 1).toFixed(3)})">` +
    `${linkSvg}${nodeSvg}` +
    `</g>` +
    `</g>`;
  renderMemoryGraphViewportMeta(connectedLinkKeys.size, els.memoryGraphSvg.querySelectorAll(".graph-label").length);
  for (const item of els.memoryGraphSvg.querySelectorAll(".graph-node")) {
    item.addEventListener("click", (clickEvent) => {
      const atomId = String(item.getAttribute("data-atom-id") || "").trim();
      if (!atomId) {
        return;
      }
      state.selectedGraphAtomId = atomId;
      renderMemoryGraph();
      renderMemoryGraphDetail();
      positionFloatingCard(clickEvent);
      const cardId = nodeById.get(atomId)?.card_id;
      if (cardId) {
        loadCardDetail(cardId).catch((error) => renderMemoryError(error.message));
        return;
      }
      refreshMemoryNeighborhood().catch((error) => renderMemoryError(error.message));
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

function beginMemoryGraphPan(event) {
  if (!(event instanceof PointerEvent) || event.button !== 0) {
    return;
  }
  if (event.target instanceof Element && event.target.closest(".graph-node")) {
    return;
  }
  const viewport = els.memoryGraphViewport;
  if (!viewport || !els.memoryGraphSvg) {
    return;
  }
  event.preventDefault();
  const current = state.memoryGraphView || { offsetX: 0, offsetY: 0 };
  state.memoryGraphPan = {
    active: true,
    dragging: false,
    pointerId: event.pointerId,
    startClientX: event.clientX,
    startClientY: event.clientY,
    startOffsetX: Number(current.offsetX || 0),
    startOffsetY: Number(current.offsetY || 0),
  };
}

function continueMemoryGraphPan(event) {
  const pan = state.memoryGraphPan || {};
  if (!pan.active || !(event instanceof PointerEvent) || pan.pointerId !== event.pointerId || !els.memoryGraphSvg) {
    return;
  }
  const clientDx = event.clientX - Number(pan.startClientX || 0);
  const clientDy = event.clientY - Number(pan.startClientY || 0);
  if (!pan.dragging) {
    if (Math.hypot(clientDx, clientDy) < 5) {
      return;
    }
    pan.dragging = true;
    els.memoryGraphViewport?.classList.add("is-panning");
  }
  const rect = els.memoryGraphSvg.getBoundingClientRect();
  const { width, height } = graphViewportSize(els.memoryGraphSvg);
  const dx = rect.width > 0 ? clientDx * (width / rect.width) : 0;
  const dy = rect.height > 0 ? clientDy * (height / rect.height) : 0;
  state.memoryGraphView = {
    ...(state.memoryGraphView || {}),
    offsetX: Number(pan.startOffsetX || 0) + dx,
    offsetY: Number(pan.startOffsetY || 0) + dy,
  };
  renderMemoryGraph();
}

function endMemoryGraphPan(event) {
  const pan = state.memoryGraphPan || {};
  if (!pan.active || (event instanceof PointerEvent && pan.pointerId !== event.pointerId)) {
    return;
  }
  state.memoryGraphPan = {
    active: false,
    pointerId: null,
    startClientX: 0,
    startClientY: 0,
    startOffsetX: 0,
    startOffsetY: 0,
  };
  els.memoryGraphViewport?.classList.remove("is-panning");
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

function syncMemoryNeighborhoodInputs() {
  if (els.memoryNeighborhoodDepth) {
    els.memoryNeighborhoodDepth.value = String(Number(state.memoryNeighborhood.depth || 1));
  }
  if (els.memoryNeighborhoodShared) {
    els.memoryNeighborhoodShared.checked = !!state.memoryNeighborhood.includeSharedLanguage;
  }
}

function selectGraphNode(atomId, cardId = "") {
  const normalized = String(atomId || "").trim();
  if (!normalized) {
    return;
  }
  if (cardId) {
    loadCardDetail(String(cardId)).catch((error) => renderMemoryError(error.message));
    return;
  }
  state.selectedGraphAtomId = normalized;
  renderMemoryGraph();
  renderMemoryGraphDetail();
  refreshMemoryNeighborhood().catch((error) => renderMemoryError(error.message));
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
  await refreshMemoryNeighborhood();
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
  params.set("limit", "500");
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
  state.memoryGraphLayoutCache = {
    signature: "",
    width: 0,
    height: 0,
    layout: null,
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
  await refreshMemoryNeighborhood();
}

async function refreshMemoryNeighborhood() {
  const selectedId = String(state.selectedGraphAtomId || "").trim();
  if (!selectedId) {
    state.memoryNeighborhood = {
      ...state.memoryNeighborhood,
      root: null,
      neighbors: [],
      links: [],
      requestsUsed: 0,
      truncated: false,
      truncation: null,
      loading: false,
      error: null,
    };
    renderMemoryNeighborhood();
    return;
  }
  const requestSeq = state.memoryNeighborhoodRequestSeq + 1;
  state.memoryNeighborhoodRequestSeq = requestSeq;
  state.memoryNeighborhood = {
    ...state.memoryNeighborhood,
    loading: true,
    error: null,
  };
  syncMemoryNeighborhoodInputs();
  renderMemoryNeighborhood();
  const params = new URLSearchParams();
  params.set("atom_id", selectedId);
  params.set("depth", String(Math.max(1, Math.min(2, Number(state.memoryNeighborhood.depth || 1)))));
  params.set("node_limit", String(Math.max(6, Number(state.memoryNeighborhood.nodeLimit || 18))));
  params.set("link_limit", String(Math.max(8, Number(state.memoryNeighborhood.linkLimit || 36))));
  params.set("include_shared_language", state.memoryNeighborhood.includeSharedLanguage ? "true" : "false");
  params.set("include_root_detail", "true");
  try {
    const payload = await jsonFetch(`/api/memory/graph/neighbors?${params.toString()}`);
    if (requestSeq !== state.memoryNeighborhoodRequestSeq || String(state.selectedGraphAtomId || "").trim() !== selectedId) {
      return;
    }
    state.memoryNeighborhood = {
      ...state.memoryNeighborhood,
      root: payload.node || null,
      neighbors: payload.neighbors || [],
      links: payload.links || [],
      depth: Number(payload.depth || state.memoryNeighborhood.depth || 1),
      nodeLimit: Number(payload.node_limit || state.memoryNeighborhood.nodeLimit || 18),
      linkLimit: Number(payload.link_limit || state.memoryNeighborhood.linkLimit || 36),
      requestsUsed: Number(payload.requests_used || 0),
      truncated: !!payload.truncated,
      truncation: payload.truncation || null,
      loading: false,
      error: null,
    };
  } catch (error) {
    if (requestSeq !== state.memoryNeighborhoodRequestSeq) {
      return;
    }
    state.memoryNeighborhood = {
      ...state.memoryNeighborhood,
      root: null,
      neighbors: [],
      links: [],
      requestsUsed: 0,
      truncated: false,
      truncation: null,
      loading: false,
      error: error.message || "Local graph request failed.",
    };
  }
  renderMemoryNeighborhood();
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

function wizardStageItems(payload = state.wizardState || {}) {
  return Array.isArray(payload.stage_flow?.items)
    ? payload.stage_flow.items
    : ["import", "build_episodes", "review", "publish", "verify", "activate", "operate"].map((stage) => ({
        stage,
        status: stage === String(payload.current_stage || "import") ? "current" : "pending",
        tone: "normal",
      }));
}

function wizardStageRow(stage, payload = state.wizardState || {}) {
  const wanted = String(stage || "").trim();
  return wizardStageItems(payload).find((item) => String(item?.stage || "").trim() === wanted) || null;
}

function wizardStageIsReachable(stage, payload = state.wizardState || {}) {
  const row = wizardStageRow(stage, payload);
  if (!row) {
    return false;
  }
  const status = String(row.status || "pending").trim().toLowerCase();
  return status === "current" || status === "done";
}

function wizardStageComplete(stage, payload = state.wizardState || {}) {
  const completedStages = new Set(Array.isArray(payload.completed_stages) ? payload.completed_stages.map((item) => String(item || "").trim()) : []);
  return completedStages.has(String(stage || "").trim());
}

function setWizardActionState(el, { primary = false, complete = false, hidden = false, disabled = false } = {}) {
  if (!el) {
    return;
  }
  el.classList.toggle("wizard-primary-action", Boolean(primary));
  el.classList.toggle("wizard-action-complete", Boolean(complete));
  el.classList.toggle("wizard-action-disabled", Boolean(disabled));
  el.disabled = Boolean(disabled);
  if (hidden) {
    el.setAttribute("hidden", "hidden");
  } else {
    el.removeAttribute("hidden");
  }
}

function normalizeWizardResultPayload(message, isWarn = false) {
  if (message && typeof message === "object" && !Array.isArray(message)) {
    return {
      tone: String(message.tone || (isWarn ? "warn" : "info")).trim().toLowerCase(),
      title: String(message.title || message.verdict || "").trim(),
      detail: String(message.detail || "").trim(),
      next: String(message.next || "").trim(),
      meta: String(message.meta || "").trim(),
      bullets: Array.isArray(message.bullets) ? message.bullets.map((item) => String(item || "").trim()).filter(Boolean) : [],
      html: typeof message.html === "string" ? message.html : "",
    };
  }
  return {
    tone: isWarn ? "warn" : "info",
    title: String(message || "").trim(),
    detail: "",
    next: "",
    meta: "",
    bullets: [],
    html: "",
  };
}

function wizardResult(el, message, isWarn = false) {
  if (!el) {
    return;
  }
  const payload = normalizeWizardResultPayload(message, isWarn);
  const tone = ["ok", "warn", "error", "info"].includes(payload.tone) ? payload.tone : "info";
  el.classList.remove("wizard-result-info", "wizard-result-ok", "wizard-result-warn", "wizard-result-error");
  el.classList.add(`wizard-result-${tone}`);
  if (payload.html) {
    el.innerHTML = payload.html;
    return;
  }
  const rows = [];
  if (payload.title) {
    rows.push(`<div class="wizard-result-title">${escapeHtml(payload.title)}</div>`);
  }
  if (payload.detail) {
    rows.push(`<div class="wizard-result-detail">${escapeHtml(payload.detail)}</div>`);
  }
  if (payload.bullets.length) {
    rows.push(`<ul class="wizard-result-list">${payload.bullets.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`);
  }
  if (payload.next) {
    rows.push(`<div class="wizard-result-next"><strong>Next:</strong> ${formatWizardGuidanceHtml(payload.next)}</div>`);
  }
  if (payload.meta) {
    rows.push(`<div class="wizard-result-meta"><strong>Details:</strong> ${escapeHtml(payload.meta)}</div>`);
  }
  el.innerHTML = `<div class="wizard-result-shell">${rows.join("")}</div>`;
}

function wizardLinks(el, links = []) {
  if (!el) {
    return;
  }
  const items = wizardLinksHtml(links);
  el.innerHTML = items || "No actionable links available for this step yet.";
}

function wizardLinksHtml(links = []) {
  if (!Array.isArray(links) || !links.length) {
    return "";
  }
  return links
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

function setWizardInputMode(mode) {
  state.wizardInputMode = mode === "store" ? "store" : "archive";
  els.btnWizardLaneArchive?.classList.toggle("active", state.wizardInputMode === "archive");
  els.btnWizardLaneStore?.classList.toggle("active", state.wizardInputMode === "store");
  els.wizardArchivePanel?.classList.toggle("active", state.wizardInputMode === "archive");
  els.wizardStorePanel?.classList.toggle("active", state.wizardInputMode === "store");
  if (els.btnWizardImport) {
    els.btnWizardImport.textContent = wizardPrimaryImportLabel();
  }
}

function setWizardArchiveTargetMode(mode) {
  state.wizardArchiveTargetMode = mode === "existing" ? "existing" : "new";
  els.btnWizardArchiveTargetNew?.classList.toggle("active", state.wizardArchiveTargetMode === "new");
  els.btnWizardArchiveTargetExisting?.classList.toggle("active", state.wizardArchiveTargetMode === "existing");
  els.wizardArchiveStorePanel?.classList.toggle("active", state.wizardArchiveTargetMode === "existing");
  if (els.btnWizardImport && state.wizardInputMode === "archive") {
    els.btnWizardImport.textContent = wizardPrimaryImportLabel();
  }
}

function wizardIssueSummary(issues = []) {
  if (!Array.isArray(issues) || !issues.length) {
    return "No obvious issues.";
  }
  return issues.map((item) => String(item || "").trim()).filter(Boolean).join(" | ");
}

function resetWizardSourceSelectionState() {
  state.wizardLocalSourcePaths = [];
  state.wizardUploadedSourceFiles = [];
  if (els.wizardArchiveFile) {
    els.wizardArchiveFile.value = "";
  }
  if (els.wizardArchiveFolder) {
    els.wizardArchiveFolder.value = "";
  }
  if (els.wizardArchiveFolder) {
    els.wizardArchiveFolder.value = "";
  }
  if (els.wizardArchivePathInline) {
    els.wizardArchivePathInline.value = "";
  }
}

function wizardSourceRowsFromState(payload = state.wizardState || {}) {
  return Array.isArray(payload.selected_input_sources) ? payload.selected_input_sources.filter((row) => row && typeof row === "object") : [];
}

function seedWizardSourceSelectionState(payload = state.wizardState || {}) {
  const rows = wizardSourceRowsFromState(payload);
  if (!rows.length) {
    state.wizardLocalSourcePaths = [];
    return;
  }
  if (state.wizardUploadedSourceFiles.length) {
    return;
  }
  state.wizardLocalSourcePaths = rows
    .map((row) => String(row.original_path || "").trim())
    .filter(Boolean);
}

function renderWizardSourceList(payload = state.wizardState || {}) {
  if (!els.wizardSourceList) {
    return;
  }
  const rows = wizardSourceRowsFromState(payload);
  if (!rows.length) {
    els.wizardSourceList.innerHTML = '<div class="wizard-source-list-empty">No files or folders selected yet.</div>';
    return;
  }
  els.wizardSourceList.innerHTML = rows
    .map((row, index) => {
      const sourceId = String(row.id || `source_${index + 1}`);
      const label = escapeHtml(String(row.label || row.original_path || row.staged_path || sourceId));
      const meta = escapeHtml(String(row.original_path || row.staged_path || ""));
      const kind = escapeHtml(String(row.kind || "file"));
      return (
        `<div class="wizard-source-row" role="listitem">` +
        `<div class="wizard-source-row-copy">` +
        `<div class="wizard-source-row-title">${label}</div>` +
        `<div class="wizard-source-row-meta">${kind}${meta ? ` | ${meta}` : ""}</div>` +
        `</div>` +
        `<button class="btn ghost wizard-source-row-remove" type="button" data-wizard-source-remove="${escapeHtml(sourceId)}">Remove</button>` +
        `</div>`
      );
    })
    .join("");
}

function currentWizardArchiveImportStorePath() {
  if (state.wizardArchiveTargetMode !== "existing") {
    return "";
  }
  return String(els.wizardArchiveStoreSelect?.value || "").trim();
}

function currentWizardInputPayload() {
  if (state.wizardInputMode === "store") {
    const storePath = String(els.wizardStoreSelect?.value || "").trim();
    return {
      store_path: storePath || undefined,
      input_path: storePath || undefined,
    };
  }
  const selectedPath = String(state.wizardState?.selected_input?.path || els.wizardArchivePath?.value || els.wizardArchivePathInline?.value || "").trim();
  const storePath = currentWizardArchiveImportStorePath();
  return {
    archive_path: selectedPath || undefined,
    input_path: selectedPath || undefined,
    store_path: storePath || undefined,
  };
}

function currentWizardUiInputPath() {
  if (state.wizardInputMode === "store") {
    return String(els.wizardStoreSelect?.value || "").trim();
  }
  return String(state.wizardState?.selected_input?.path || els.wizardArchivePath?.value || els.wizardArchivePathInline?.value || "").trim();
}

function currentWizardImportValidation(payload = state.wizardState || {}) {
  const activePath = currentWizardUiInputPath();
  const validation = payload.artifacts?.import_validation || {};
  const validationPath = String(validation.path || "").trim();
  const validationStatus = String(validation.status || "").trim().toLowerCase();
  return {
    activePath,
    ok: Boolean(activePath) && activePath === validationPath && validationStatus === "safe",
    status: validationStatus || "unknown",
  };
}

function wizardCountLabel(count, singular, plural = `${singular}s`) {
  const safeCount = Math.max(0, Number(count || 0));
  return `${safeCount} ${safeCount === 1 ? singular : plural}`;
}

function wizardEntryPrimaryAction(payload = state.wizardState || {}) {
  const hasRun = Boolean(state.wizardRunId);
  const hasResume = Boolean(state.wizardResumeAvailable || state.wizardLatestRunId);
  const publishedHistory = Array.isArray(payload.published_history) ? payload.published_history : [];
  const hasRestore = Boolean(publishedHistory.length);
  if (hasRun || hasResume) {
    return "resume";
  }
  if (!hasResume && hasRestore) {
    return "restore";
  }
  return "new";
}

function wizardPrimaryImportLabel() {
  if (state.wizardInputMode === "store") {
    return "Use This Store";
  }
  return state.wizardArchiveTargetMode === "existing" ? "Add To Existing Store" : "Create MNO Store";
}

async function stageWizardLocalPaths(paths) {
  const deduped = Array.from(new Set((Array.isArray(paths) ? paths : []).map((item) => String(item || "").trim()).filter(Boolean)));
  if (!deduped.length) {
    await clearWizardSelectedSources();
    return;
  }
  const payload = await jsonFetch('/api/wizard/input/stage-local', {
    method: 'POST',
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      paths: deduped,
    }),
  });
  state.wizardLocalSourcePaths = deduped;
  state.wizardUploadedSourceFiles = [];
  state.wizardState = {
    ...(state.wizardState || {}),
    selected_input: payload.classification || {},
    selected_input_sources: Array.isArray(payload.source_paths) ? payload.source_paths : [],
  };
  renderWizardState();
  await refreshWizardInputOptions(state.wizardRunId || undefined);
  await validateWizardImport();
}

async function clearWizardSelectedSources() {
  resetWizardSourceSelectionState();
  const payload = await jsonFetch('/api/wizard/input/clear', {
    method: 'POST',
    body: JSON.stringify({ run_id: state.wizardRunId || undefined }),
  });
  state.wizardState = payload.state || state.wizardState;
  renderWizardState();
  await refreshWizardInputOptions(state.wizardRunId || undefined);
}

function wizardUploadFileKey(file) {
  return [
    String(file?.name || ''),
    String(file?.size || 0),
    String(file?.lastModified || 0),
    String(file?.webkitRelativePath || ''),
  ].join('::');
}

async function addWizardUploadFiles(files) {
  const incoming = Array.isArray(files) ? files.filter(Boolean) : [];
  if (!incoming.length) {
    return;
  }
  const merged = new Map(state.wizardUploadedSourceFiles.map((row) => [row.key, row]));
  for (const file of incoming) {
    const key = wizardUploadFileKey(file);
    merged.set(key, { key, label: String(file.webkitRelativePath || file.name || "").trim() || file.name, file });
  }
  state.wizardUploadedSourceFiles = Array.from(merged.values());
  state.wizardLocalSourcePaths = [];
  await uploadWizardArchive(state.wizardUploadedSourceFiles.map((row) => row.file));
}

async function removeWizardSelectedSource(sourceId) {
  const targetId = String(sourceId || '').trim();
  if (!targetId) {
    return;
  }
  const rows = wizardSourceRowsFromState();
  const target = rows.find((row) => String(row.id || '') === targetId);
  if (!target) {
    return;
  }
  const uploadMatch = state.wizardUploadedSourceFiles.find((row) => row.key === targetId || String(row.label || "") === String(target.label || ""));
  if (uploadMatch) {
    state.wizardUploadedSourceFiles = state.wizardUploadedSourceFiles.filter((row) => row.key !== uploadMatch.key);
    if (!state.wizardUploadedSourceFiles.length) {
      await clearWizardSelectedSources();
      return;
    }
    await uploadWizardArchive(state.wizardUploadedSourceFiles.map((row) => row.file));
    return;
  }
  const originalPath = String(target.original_path || '').trim();
  state.wizardLocalSourcePaths = state.wizardLocalSourcePaths.filter((item) => item !== originalPath);
  if (!state.wizardLocalSourcePaths.length) {
    await clearWizardSelectedSources();
    return;
  }
  await stageWizardLocalPaths(state.wizardLocalSourcePaths);
}
function renderWizardPublishSummary(payload = state.wizardState || {}) {
  if (!els.wizardPublishSummary) {
    return;
  }
  const reviewState = payload.review_state || {};
  const approved = Number(reviewState.approved_count || 0);
  const edited = Number(reviewState.edited_count || 0);
  const rejected = Number(reviewState.rejected_count || 0);
  const pending = Number(reviewState.pending_count || 0);
  const publishable = Number(reviewState.publishable_count || 0);
  const total = Number(reviewState.reviewable_count || 0);
  if (!total) {
    wizardResult(els.wizardPublishSummary, {
      title: "Publish comes after review.",
      detail: "You need a reviewed draft before MNO can create the memory set the runtime will actually use.",
      next: "Build a draft, then review every card.",
      tone: "info",
    });
    return;
  }
  wizardResult(els.wizardPublishSummary, {
    title: "This step freezes the reviewed memory set.",
    detail: pending > 0
      ? `You still have ${wizardCountLabel(pending, "card")} waiting for a decision. Publish stays blocked until every draft card is approved, edited, or rejected.`
      : publishable <= 0
        ? "Every reviewed card is rejected. MNO has nothing safe to publish yet."
        : "Your review decisions are complete. Publishing will create the reviewed memory set the runtime should actually use.",
    next: pending > 0
      ? "Go back to Review and finish the remaining cards."
      : publishable <= 0
        ? "Go back to Review and keep at least one card."
        : "Click Publish Reviewed Memory Set.",
    meta: `approved=${approved} | edited=${edited} | rejected=${rejected} | publishable=${publishable} | total=${total}`,
    tone: pending > 0 || publishable <= 0 ? "warn" : "info",
  });
}

function renderWizardOperateState(payload = state.wizardState || {}) {
  const verify = payload.verify || {};
  const activation = payload.activation || {};
  const direct = activation.direct || {};
  const mcpTargets = (activation.mcp || {}).targets || {};
  const installedTargets = Object.values(mcpTargets).filter((target) => String(target?.status || "").trim() === "installed");
  const verifiedSafe = String(verify.status || "") === "Safe";
  const directStatus = String(direct.status || "not_active");
  const runtimeHealthy = directStatus === "running";
  if (els.wizardOperateState) {
    if (runtimeHealthy && verifiedSafe) {
      wizardResult(els.wizardOperateState, {
        tone: "ok",
        title: "You are live.",
        detail: "The local runtime is healthy, the reviewed memory set passed verification, and the system is ready for a real smoke test.",
        next: "Open Chat Test, then Open Memory Check to confirm the right store is attached.",
        meta: `runtime=${friendlyActivationStatus(directStatus)} | mcp_installs=${installedTargets.length}`,
      });
    } else if (directStatus === "draft_active") {
      wizardResult(els.wizardOperateState, {
        tone: "warn",
        title: "Only the unsafe draft runtime is live.",
        detail: "This is for developer testing only. It does not count as normal success and should not be treated as a ready memory system.",
        next: "Return to Publish and Verify, then start the normal local runtime.",
      });
    } else {
      wizardResult(els.wizardOperateState, {
        tone: verifiedSafe ? "warn" : "info",
        title: verifiedSafe ? "Verification passed, but the live runtime is not up yet." : "Operate unlocks after Verify and Activate are truly ready.",
        detail: verifiedSafe
          ? "The reviewed set looks safe, but the local runtime is not running the normal published memory path yet."
          : "Operate is the final smoke-test step. It only becomes meaningful after the reviewed set is safe and the local runtime is healthy.",
        next: verifiedSafe ? "Go to Activate and start the local runtime." : "Finish Verify, then start the local runtime in Activate.",
      });
    }
  }
  if (els.wizardGoLiveConfig) {
    if (runtimeHealthy && verifiedSafe) {
      const providerConfig = state.wizardActivationProviderConfig || {};
      const modelName = String(providerConfig.model_name || "-");
      const adapters = Array.isArray(providerConfig.adapters)
        ? providerConfig.adapters.join(", ")
        : "-";
      els.wizardGoLiveConfig.innerHTML =
        `<div class="wizard-result-shell">` +
        `<div class="wizard-result-title">Quick live test checklist</div>` +
        `<div class="wizard-result-detail">1. Ask one memory question in Chat. 2. Open Memory Check and confirm the right store and reviewed set are attached. 3. If an assistant, agent, or MCP client is installed, run one external recall test before trusting it.</div>` +
        `<div class="wizard-result-next"><strong>Next:</strong> Use the buttons above to run the local smoke test.</div>` +
        `<div class="wizard-result-meta"><strong>Details:</strong> model=${escapeHtml(modelName)} | adapters=${escapeHtml(adapters || "-")} | runtime=${escapeHtml(String(direct.runtime_url || "-"))}</div>` +
        `</div>`;
    } else {
      wizardResult(els.wizardGoLiveConfig, {
        tone: "info",
        title: "Live smoke-test steps appear here after activation.",
        detail: "Once the runtime is healthy, this panel turns into a short checklist for testing the system like a normal user.",
        next: "Finish Verify and Activate first.",
      });
    }
  }
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let index = 0; index < bytes.byteLength; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return window.btoa(binary);
}

function renderWizardInputOptions() {
  const payload = state.wizardInputOptions || {};
  const candidates = Array.isArray(payload.memory_candidates) ? payload.memory_candidates : [];
  const labels = Array.isArray(payload.memory_candidate_labels) ? payload.memory_candidate_labels : [];
  const storeSelectionPath = String(state.wizardState?.selected_input?.path || els.wizardStoreSelect?.value || "").trim();
  const archiveStorePath = String(state.wizardState?.store_path || els.wizardArchiveStoreSelect?.value || "").trim();
  const options = ['<option value="">Pick an existing store</option>']
    .concat(
      candidates.map((candidate, index) => {
        const candidatePath = String(candidate.path || "");
        const label = labels[index] || candidate.label || candidatePath || "memory store";
        return `<option value="${escapeHtml(candidatePath)}">${escapeHtml(label)}</option>`;
      })
    )
    .join("");
  if (els.wizardStoreSelect) {
    els.wizardStoreSelect.innerHTML = options;
    els.wizardStoreSelect.value = storeSelectionPath;
  }
  if (els.wizardArchiveStoreSelect) {
    els.wizardArchiveStoreSelect.innerHTML = options;
    if (archiveStorePath && candidates.some((candidate) => String(candidate.path || "") === archiveStorePath)) {
      els.wizardArchiveStoreSelect.value = archiveStorePath;
    } else {
      els.wizardArchiveStoreSelect.value = "";
    }
  }
  if (els.wizardStoreSummary) {
    const selected = String(state.wizardState?.selected_input?.kind || "").trim();
    if (selected.startsWith("mno_store")) {
      const selection = state.wizardState?.selected_input || {};
      wizardResult(
        els.wizardStoreSummary,
        {
          tone: (selection.issues || []).length ? "warn" : "info",
          title: "Existing MNO store selected.",
          detail: "This lane skips raw source import and continues from memory data that is already in MNO format.",
          next: "If File Checked is green, click Use This Store.",
          meta: `path=${selection.path || "-"} | atoms=${selection.atom_count || 0} | ${wizardIssueSummary(selection.issues || [])}`,
        }
      );
    } else {
      wizardResult(els.wizardStoreSummary, {
        title: "Use this lane when the memory data is already in MNO format.",
        detail: "It skips raw source import and lets you continue from an existing store.",
        next: "Pick one store so MNO can validate it, then use Use This Store.",
        tone: "info",
      });
    }
  }
  if (els.wizardArchiveStoreSummary) {
    const selectedStore = String(els.wizardArchiveStoreSelect?.value || "").trim();
    wizardResult(
      els.wizardArchiveStoreSummary,
      selectedStore
        ? {
            tone: "info",
            title: "Append destination selected.",
            detail: "MNO will import the new raw source and merge it into the existing store you picked.",
            next: "Validate the source, then click Add To Existing Store.",
            meta: `store=${selectedStore}`,
          }
        : {
            tone: "info",
            title: "Pick an existing MNO store for append.",
            detail: "Use this only when you want the new raw source merged into an existing store instead of creating a fresh one.",
            next: "Choose one store to unlock Add To Existing Store.",
          }
    );
  }
}

function renderWizardState() {
  const payload = state.wizardState || {};
  const runId = String(payload.run_id || state.wizardRunId || "");
  const selectedInput = payload.selected_input || {};
  const storeValidation = payload.store_validation || {};
  const reviewState = payload.review_state || {};
  const verifyState = payload.verify || {};
  const activationState = payload.activation || {};
  const directActivation = activationState.direct || {};
  const importValidation = currentWizardImportValidation(payload);
  const importComplete = wizardStageComplete("import", payload);
  const reviewComplete = Boolean(reviewState.complete) && Number(reviewState.reviewable_count || 0) > 0;
  const publishableCount = Number(reviewState.publishable_count || 0);
  const publishedReady = Boolean(String((payload.published_set || {}).episodes_path || "").trim());
  const verifySafe = String(verifyState.status || "").trim() === "Safe";
  const directStatus = String(directActivation.status || "not_active").trim().toLowerCase();
  const runtimeHealthy = directStatus === "running";
  if (els.wizardRunMeta) {
    if (!runId) {
      els.wizardRunMeta.textContent = "No setup run is open yet. Start fresh for a new import, or resume the last run if you were already working.";
    } else {
      const activeStage = String(payload.stage_flow?.current_stage || payload.current_stage || "import");
      const stage = stageLabel(activeStage);
      const updated = formatDate(payload.updated_at || "");
      els.wizardRunMeta.textContent = `Current run: ${runId} | active step: ${stage} | last updated: ${updated}`;
    }
  }
  renderWizardDraftCurationRunId();
  renderWizardDraftCurationWorkspaceChrome();
  seedWizardSourceSelectionState(payload);
  renderWizardSourceList(payload);
  if (els.wizardArchivePath) {
    els.wizardArchivePath.value = String(payload.selected_input?.path || payload.selected_input_archive_path || "");
  }
  if (els.wizardArchivePathInline && !String(els.wizardArchivePathInline.value || "").trim()) {
    els.wizardArchivePathInline.value = String(payload.selected_input?.path || payload.selected_input_archive_path || "");
  }
  if (String(payload.selected_input?.kind || "").startsWith("mno_store")) {
    setWizardInputMode("store");
  } else if (String(payload.selected_input?.kind || "").trim()) {
    setWizardInputMode("archive");
  }
  const appendStorePath = String(payload.store_path || "").trim();
  const appendStoreAvailable = appendStorePath && Array.isArray(state.wizardInputOptions?.memory_candidates)
    ? state.wizardInputOptions.memory_candidates.some((candidate) => String(candidate.path || "") === appendStorePath)
    : Boolean(String(els.wizardArchiveStoreSelect?.value || "").trim());
  setWizardArchiveTargetMode(appendStoreAvailable ? "existing" : "new");
  if (els.wizardArchiveSummary) {
    if (String(selectedInput.kind || "") === "source_input") {
      const sourceRows = wizardSourceRowsFromState(payload);
      const sourceCount = sourceRows.length || Number(selectedInput.source_file_count || 0);
      wizardResult(
        els.wizardArchiveSummary,
        {
          tone: (selectedInput.issues || []).length ? "warn" : "info",
          title: sourceCount > 1 ? "Source bundle selected." : "Source input selected.",
          detail: state.wizardArchiveTargetMode === "existing"
            ? "MNO can see the files and folders you picked. Validation checks the bundle first, then Import will merge it into the existing store you selected."
            : "MNO can see the files and folders you picked. Validation checks the bundle first, then Import creates a ready-to-build MNO store.",
          next: importValidation.ok
            ? `If File Checked is green, click ${wizardPrimaryImportLabel()}.`
            : "Wait for File Checked to turn green, then run Import.",
          meta: `staged=${selectedInput.path || "-"} | format=${selectedInput.input_format || "-"} | sources=${sourceCount} | conversations=${selectedInput.conversation_count || 0} | messages=${selectedInput.message_count || 0} | ${wizardIssueSummary(selectedInput.issues || [])}`,
        }
      );
    } else if (state.wizardInputMode === "archive") {
      wizardResult(els.wizardArchiveSummary, {
        title: "Pick raw source files or folders.",
        detail: "Use Add Files or Add Folder. You can stack a folder plus extra files, then import the staged bundle as one source.",
        next: "Build a source list first, then wait for File Checked to turn green.",
        tone: "info",
      });
    }
  }
  if (els.btnWizardValidate) {
    setWizardActionState(els.btnWizardValidate, {
      complete: importValidation.ok,
      disabled: !Boolean(importValidation.activePath),
    });
    els.btnWizardValidate.textContent = importValidation.ok ? "File Checked" : "Check File";
  }
  if (els.btnWizardImport) {
    const appendNeedsStore = state.wizardInputMode === "archive" && state.wizardArchiveTargetMode === "existing" && !currentWizardArchiveImportStorePath();
    els.btnWizardImport.textContent = state.wizardImportPending
      ? (state.wizardInputMode === "store" ? "Binding Store..." : state.wizardArchiveTargetMode === "existing" ? "Adding To Store..." : "Creating Store...")
      : wizardPrimaryImportLabel();
    setWizardActionState(els.btnWizardImport, {
      primary: true,
      complete: importComplete,
      disabled: !importValidation.ok || state.wizardImportPending || appendNeedsStore,
    });
  }
  if (els.btnWizardBuild) {
    setWizardActionState(els.btnWizardBuild, {
      primary: true,
      complete: wizardStageComplete("build_episodes", payload),
      disabled: !importComplete,
    });
  }
  if (els.btnWizardPublish) {
    setWizardActionState(els.btnWizardPublish, {
      primary: true,
      complete: wizardStageComplete("publish", payload),
      disabled: !reviewComplete || publishableCount <= 0,
    });
  }
  if (els.btnWizardVerify) {
    setWizardActionState(els.btnWizardVerify, {
      primary: true,
      complete: verifySafe,
      disabled: !publishedReady,
    });
  }
  if (els.btnWizardGoLive) {
    setWizardActionState(els.btnWizardGoLive, {
      primary: true,
      complete: runtimeHealthy,
      disabled: !verifySafe,
    });
  }
  if (els.btnWizardOperateChat) {
    setWizardActionState(els.btnWizardOperateChat, {
      primary: true,
      complete: verifySafe && runtimeHealthy,
      disabled: !(verifySafe && runtimeHealthy),
    });
  }
  if (els.btnWizardResume && els.btnWizardStartNew && els.btnWizardRestore) {
    const primaryEntry = wizardEntryPrimaryAction(payload);
    setWizardActionState(els.btnWizardResume, { primary: primaryEntry === "resume" });
    setWizardActionState(els.btnWizardStartNew, { primary: primaryEntry === "new" });
    setWizardActionState(els.btnWizardRestore, { primary: primaryEntry === "restore" });
  }
  if (els.wizardImportResult) {
    if (wizardStageComplete("import", payload) && String(storeValidation.path || payload.store_path || "").trim()) {
      wizardResult(els.wizardImportResult, {
        tone: "ok",
        title: "Import is complete.",
        detail: state.wizardInputMode === "store"
          ? "A valid existing MNO store is selected and ready for the next step."
          : "The selected source has been turned into a ready-to-build MNO memory store.",
        next: "Move to Build Episodes.",
        meta: `store=${storeValidation.path || payload.store_path || "-"} | kind=${storeValidation.kind || selectedInput.kind || "-"}`,
      });
    } else if (importValidation.ok) {
      wizardResult(els.wizardImportResult, {
        tone: "ok",
        title: "The selected input looks valid.",
        detail: "Validation passed, but Import is not complete yet.",
        next: `If File Checked is green, click ${wizardPrimaryImportLabel()}.`,
        meta: `path=${importValidation.activePath || "-"}`,
      });
    } else if (String(selectedInput.path || "").trim()) {
      wizardResult(els.wizardImportResult, {
        tone: "info",
        title: "A source is selected.",
        detail: "MNO can see the file or store you picked, and validation should run before import continues.",
        next: "Wait for File Checked to turn green.",
        meta: `path=${selectedInput.path || "-"}`,
      });
    } else {
      wizardResult(els.wizardImportResult, {
        tone: "info",
        title: "Import starts here.",
        detail: "Choose either raw source files/folder or an existing MNO store.",
        next: "Pick the source you want to use, then validate it.",
      });
    }
  }
  if (els.wizardStageRail) {
    const stageItems = wizardStageItems(payload);
    els.wizardStageRail.innerHTML = stageItems
      .map((item) => {
        const stage = String(item.stage || "");
        const status = String(item.status || "pending");
        const tone = String(item.tone || "normal").trim().toLowerCase();
        const reachable = wizardStageIsReachable(stage, payload);
        return `<span class="wizard-stage ${status} tone-${escapeHtml(tone)}${reachable ? " reachable" : " blocked"}" data-stage="${escapeHtml(stage)}" aria-disabled="${reachable ? "false" : "true"}">${escapeHtml(stageLabel(stage))}</span>`;
      })
      .join("");
  }
  const buildInfo = payload.build_info || {};
  const buildCounts = buildInfo.counts || {};
  if (els.wizardBuildResult) {
    if (String(buildInfo.draft_path || "").trim()) {
      wizardResult(els.wizardBuildResult, {
        tone: "ok",
        title: `${wizardCountLabel(buildCounts.promoted_count || 0, "draft card")} are ready for review.`,
        detail: Number(buildCounts.promoted_count || 0) > 24
          ? "This is a large draft. Expect more cleanup during review."
          : Number(buildCounts.promoted_count || 0) <= 2
            ? "This is a very small draft. If it feels too thin, rebuild with a less strict style."
            : "The draft looks ready for a normal review pass.",
        next: "Move to Review.",
        meta: `draft=${buildInfo.draft_path || "-"} | rejected=${buildCounts.rejected_count || 0}`,
      });
    } else {
      wizardResult(els.wizardBuildResult, {
        tone: "info",
        title: "Build creates the draft cards you review next.",
        detail: "This is not the final memory set. It is the draft you clean up before publish.",
        next: "Choose a build style, then click Build Review Draft.",
      });
    }
  }
  renderWizardPublishSummary(payload);
  if (els.wizardPublishResult) {
    const publishedSet = payload.published_set || {};
    if (String(publishedSet.version_id || "").trim()) {
      wizardResult(els.wizardPublishResult, {
        tone: "ok",
        title: "Latest publish is ready.",
        detail: "The reviewed set exists and can move into Verify.",
        next: "Run Verify before activation.",
        meta: `version=${publishedSet.version_id || "-"} | episodes=${publishedSet.episode_count || 0}`,
      });
    } else {
      const pending = Number((payload.review_state || {}).pending_count || 0);
      const publishable = Number((payload.review_state || {}).publishable_count || 0);
      wizardResult(els.wizardPublishResult, {
        tone: pending > 0 || (reviewComplete && publishable <= 0) ? "warn" : "info",
        title: pending > 0
          ? "Publish is still blocked by unfinished review."
          : reviewComplete && publishable <= 0
            ? "Publish is blocked because nothing is left to publish."
            : "Nothing has been published yet.",
        detail: pending > 0
          ? `You still have ${wizardCountLabel(pending, "card")} waiting for a decision.`
          : reviewComplete && publishable <= 0
            ? "Every reviewed card is rejected. Approve or edit at least one card before MNO can publish a reviewed memory set."
            : "Publishing freezes the reviewed memory set that the runtime should actually use.",
        next: pending > 0
          ? "Finish Review first."
          : reviewComplete && publishable <= 0
            ? "Go back to Review and keep at least one card."
            : "Click Publish Reviewed Memory Set when you are ready.",
      });
    }
  }
  if (els.wizardPublishedHistory) {
    const publishedSet = payload.published_set || {};
    const history = Array.isArray(payload.published_history) ? payload.published_history : [];
    const versionId = String(publishedSet.version_id || "").trim();
    if (!versionId) {
      wizardResult(
        els.wizardPublishedHistory,
        history.length
          ? {
              tone: "warn",
              title: "No live published set is attached right now.",
              detail: `You still have ${wizardCountLabel(history.length, "older snapshot")} available if you need to recover a last good copy.`,
              next: "Either publish a reviewed set now, or use Restore Last Good Copy if you need to recover.",
            }
          : {
              title: "No published memory set exists yet.",
              detail: "Publishing creates the reviewed version the runtime will actually use and gives you a recovery copy.",
              next: "Finish review, then publish the reviewed memory set.",
              tone: "info",
            }
      );
    } else {
      const historyRows = history
        .slice(-3)
        .reverse()
        .map((row) => {
          const snapshot = row?.published_set || {};
          return `<div class="wizard-history-item"><strong>${escapeHtml(String(snapshot.version_id || "older_snapshot"))}</strong><span>${escapeHtml(formatDate(row.at || snapshot.published_at || ""))}</span></div>`;
        })
        .join("");
      wizardResult(els.wizardPublishedHistory, {
        tone: "ok",
        title: "A published memory set is ready.",
        detail: "This is the reviewed version the runtime should use. Older snapshots stay available for recovery.",
        next: "Run Verify before activation, especially after a restore.",
        meta: `version=${versionId} | episodes=${publishedSet.episode_count || 0} | build=${publishedSet.build_id || "-"} | older_snapshots=${history.length || 0}`,
        html:
          `<div class="wizard-result-shell">` +
          `<div class="wizard-result-title">A published memory set is ready.</div>` +
          `<div class="wizard-result-detail">This is the reviewed version the runtime should use. Older snapshots stay available for recovery.</div>` +
          `<div class="wizard-result-next"><strong>Next:</strong> Run Verify before activation, especially after a restore.</div>` +
          `<div class="wizard-result-meta"><strong>Details:</strong> version=${escapeHtml(versionId)} | episodes=${escapeHtml(String(publishedSet.episode_count || 0))} | build=${escapeHtml(String(publishedSet.build_id || "-"))} | older_snapshots=${escapeHtml(String(history.length || 0))}</div>` +
          (historyRows ? `<div class="wizard-history-list">${historyRows}</div>` : "") +
          `</div>`,
      });
    }
  }
  const verifyPayload = payload.verify || {};
  renderWizardVerifyResult(verifyPayload);
  renderWizardInputOptions();
  renderWizardDraftCurationStatus();
  renderWizardDraftCurationList();
  renderWizardOperateState(payload);
  autoSelectWizardStep();
}

function renderWizardReviewList() {
  renderWizardReviewFilters();
  renderWizardReviewMeta();
  if (!els.wizardReviewList) {
    return;
  }
  const meta = state.wizardReviewMeta || {};
  const reviewState = state.wizardState?.review_state || {};
  if (!state.wizardRunId) {
    els.wizardReviewList.innerHTML = '<div class="memory-empty">Start or resume a run first, then build a draft before you review cards.</div>';
    renderWizardReviewPager();
    return;
  }
  if (!state.wizardReviewCards.length) {
    if (Number(meta.filteredTotal || 0) > 0) {
      els.wizardReviewList.innerHTML = '<div class="memory-empty">This page has no cards. Move to another page or change the filter.</div>';
    } else if (Number(reviewState.reviewable_count || 0) > 0 && Number(reviewState.pending_count || 0) === 0) {
      els.wizardReviewList.innerHTML =
        '<div class="memory-empty">Every draft card already has a decision. Move to Publish when you are ready.</div>';
    } else if (Number(reviewState.reviewable_count || 0) > 0) {
      els.wizardReviewList.innerHTML =
        '<div class="memory-empty">No draft cards match this filter. Clear the search or choose a different review status.</div>';
    } else {
      els.wizardReviewList.innerHTML = '<div class="memory-empty">Build draft episode cards first. Review only appears after a draft exists.</div>';
    }
    renderWizardReviewPager();
    return;
  }
  els.wizardReviewList.innerHTML = state.wizardReviewCards
    .map((card) => {
      const episodeId = String(card.episode_id || "");
      const decision = String(card.review_decision || "pending");
      const busy = !!state.wizardReviewPendingWrites?.[episodeId];
      const reviewPayload = card.review_payload || {};
      const titleValue = reviewTextValue(card, reviewPayload, "title");
      const summaryValue = reviewSummaryDisplayValue(titleValue, reviewTextValue(card, reviewPayload, "summary"));
      return (
        `<article class="wizard-review-item ${escapeHtml(decision)}${decision === "pending" ? " review-focus" : ""}${busy ? " busy" : ""}" data-episode-id="${escapeHtml(episodeId)}" tabindex="-1">` +
        `<div class="wizard-review-top"><strong>${escapeHtml(episodeId)}</strong><span>${escapeHtml(friendlyReviewDecision(decision))}</span></div>` +
        `<div class="wizard-review-title">${escapeHtml(titleValue || "(untitled episode)")}</div>` +
        (summaryValue ? `<div class="wizard-review-summary">${escapeHtml(trimDisplay(summaryValue, 180))}</div>` : "") +
        `<div class="wizard-review-meta">${escapeHtml(reviewCardMeta(card, reviewPayload))}</div>` +
        `<div class="wizard-review-actions">` +
        `<button type="button" class="btn ghost review-approve"${busy ? ' disabled="disabled"' : ""}>Approve</button>` +
        `<button type="button" class="btn ghost review-edit"${busy ? ' disabled="disabled"' : ""}>Quick Edit</button>` +
        `<button type="button" class="btn ghost review-reject"${busy ? ' disabled="disabled"' : ""}>Reject</button>` +
        `${decision !== "pending" ? `<button type="button" class="btn ghost review-pending"${busy ? ' disabled="disabled"' : ""}>Mark Pending</button>` : ""}` +
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
    node.querySelector(".review-pending")?.addEventListener("click", () => {
      updateWizardReviewDecision(episodeId, "pending").catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
    });
    node.querySelector(".review-edit")?.addEventListener("click", (event) => {
      openWizardReviewEditor(episodeId, event.currentTarget);
    });
  }
  renderWizardReviewPager();
  focusWizardReviewTarget();
}

function renderWizardReviewMeta() {
  if (!els.wizardReviewMeta) {
    return;
  }
  const meta = state.wizardReviewMeta || {};
  const reviewState = state.wizardState?.review_state || {};
  const total = Number(meta.total || reviewState.reviewable_count || 0);
  const filteredTotal = Number(meta.filteredTotal || 0);
  const page = Math.max(1, Number(meta.page || 1));
  const pageSize = Math.max(1, Number(meta.pageSize || 6));
  const first = filteredTotal ? ((page - 1) * pageSize) + 1 : 0;
  const last = filteredTotal ? first + Math.max(0, state.wizardReviewCards.length - 1) : 0;
  const pending = Number(reviewState.pending_count || 0);
  const approved = Number(reviewState.approved_count || 0);
  const edited = Number(reviewState.edited_count || 0);
  const rejected = Number(reviewState.rejected_count || 0);
  const publishable = Number(reviewState.publishable_count || 0);
  if (!total) {
    wizardResult(els.wizardReviewMeta, {
      title: "Review starts after a draft exists.",
      detail: "Once MNO builds episode cards, this step will show how many still need a decision and what to do next.",
      next: "Build a draft first.",
      tone: "info",
    });
    return;
  }
  wizardResult(els.wizardReviewMeta, {
    tone: pending > 0 || (total > 0 && publishable <= 0) ? "warn" : "ok",
    title: pending > 0
      ? `${wizardCountLabel(pending, "card")} still need review.`
      : publishable <= 0
        ? "Review is complete, but nothing is left to publish."
        : "Every draft card has a decision.",
    detail: pending > 0
      ? `You are reviewing ${filteredTotal ? `${first}-${last} of ${filteredTotal}` : "the current draft page"} out of ${wizardCountLabel(total, "draft card")}. Publish stays locked until every card is approved, edited, or rejected.`
      : publishable <= 0
        ? `You reviewed ${wizardCountLabel(total, "draft card")}, but every reviewed card is rejected.`
        : `You reviewed ${wizardCountLabel(total, "draft card")}. Review is complete and Publish is the next safe step.`,
    next: pending > 0
      ? "Approve, Quick Edit, or Reject the remaining cards."
      : publishable <= 0
        ? "Quick Edit or Approve at least one card."
        : "Move to Publish.",
    meta: `approved=${approved} | edited=${edited} | rejected=${rejected} | publishable=${publishable} | pending=${pending}`,
  });
}

function friendlyDraftCurationStatus(value) {
  const normalized = String(value || "not_started").trim().toLowerCase() || "not_started";
  if (normalized === "active") {
    return "Active";
  }
  if (normalized === "idle") {
    return "Idle";
  }
  if (normalized === "completed") {
    return "Completed";
  }
  return "Not started";
}

function renderDraftProposalPreviewCard(card = {}) {
  const title = String(card.title || "").trim() || "(untitled draft)";
  const summary = reviewSummaryDisplayValue(title, String(card.summary || "").trim()) || String(card.summary || "").trim();
  const actors = Array.isArray(card.actors) ? card.actors : [];
  const topics = Array.isArray(card.topic_tags) ? card.topic_tags : [];
  const rationale = String(card.rationale || "").trim();
  const cueTerms = Array.isArray(card.retrieval_cues) ? card.retrieval_cues : [];
  const parts = [];
  parts.push(`<div class="draft-field"><span class="draft-field-label">Title</span><div class="draft-field-value draft-field-title">${escapeHtml(title)}</div></div>`);
  if (summary) {
    parts.push(`<div class="draft-field"><span class="draft-field-label">Summary</span><div class="draft-field-value">${escapeHtml(trimDisplay(summary, 400))}</div></div>`);
  }
  if (topics.length) {
    parts.push(`<div class="draft-field"><span class="draft-field-label">Topics</span><div class="draft-field-value draft-field-tags">${topics.map((t) => `<span class="draft-tag">${escapeHtml(t)}</span>`).join("")}</div></div>`);
  }
  if (actors.length) {
    parts.push(`<div class="draft-field"><span class="draft-field-label">Actors</span><div class="draft-field-value draft-field-tags">${actors.map((a) => `<span class="draft-tag">${escapeHtml(a)}</span>`).join("")}</div></div>`);
  }
  if (cueTerms.length) {
    parts.push(`<div class="draft-field"><span class="draft-field-label">Retrieval Cues</span><div class="draft-field-value draft-field-tags">${cueTerms.map((c) => `<span class="draft-tag draft-tag-cue">${escapeHtml(c)}</span>`).join("")}</div></div>`);
  }
  if (rationale) {
    parts.push(`<div class="draft-field"><span class="draft-field-label">Rationale</span><div class="draft-field-value draft-field-rationale">${escapeHtml(trimDisplay(rationale, 500))}</div></div>`);
  }
  return parts.join("");
}

function currentWizardRunId() {
  if (state.hcrMode) {
    return state.hcrRunId;
  }
  return String(state.wizardRunId || state.wizardLatestRunId || state.wizardState?.run_id || "").trim();
}

function renderHcrStatus() {
  if (!els.hcrRoomStatus) {
    return;
  }
  if (!state.hcrMode) {
    els.hcrRoomStatus.hidden = true;
    return;
  }
  const payload = state.hcrStatus || {};
  const counts = payload.counts || {};
  const roomState = String(payload.state || "review_in_progress").replaceAll("_", " ");
  const verification = String(payload.verification_status || "Unknown");
  wizardResult(els.hcrRoomStatus, {
    tone: payload.state === "verification_blocked" ? "warn" : payload.state === "ready" ? "ok" : "info",
    title: `Curation room: ${roomState}.`,
    detail: "This room is bound to the run in this URL. Draft proposals stay separate until a human promotes or reviews them.",
    next: `Current handoff: ${String(payload.next_action || "review").replaceAll("_", " ")}.`,
    meta: `run=${payload.run_id || state.hcrRunId || "-"} | pending=${Number(counts.pending || 0)} | publishable=${Number(counts.publishable || 0)} | proposals=${Number(counts.draft_proposals || 0)} | verification=${verification}`,
  });
  els.hcrRoomStatus.hidden = false;
}

async function refreshHcrStatus() {
  if (!state.hcrMode || !state.hcrRunId) {
    return;
  }
  const payload = await jsonFetch(`/api/wizard/hcr/status?run_id=${encodeURIComponent(state.hcrRunId)}`);
  if (String(payload.run_id || "").trim() !== state.hcrRunId) {
    throw new Error("Curation room did not return the requested run.");
  }
  state.hcrStatus = payload;
  renderHcrStatus();
}

async function refreshHcrProgress() {
  if (!state.hcrMode) {
    return;
  }
  await refreshHcrStatus();
  state.wizardVisibleStage = hcrPreferredWizardStage();
  renderWizardState();
}

const MANAGED_MCP_PROFILE_DEFAULTS = {
  draft: { default_role: "viewer", compat_mode: "strict", mutations_enabled: true },
  reviewed: { default_role: "viewer", compat_mode: "strict", mutations_enabled: false },
};

function normalizeManagedMcpArtifactMode(value) {
  return String(value || "").trim().toLowerCase() === "draft" ? "draft" : "reviewed";
}

function normalizeManagedMcpProfile(profile, artifactMode = "reviewed") {
  const mode = normalizeManagedMcpArtifactMode(artifactMode);
  const defaults = MANAGED_MCP_PROFILE_DEFAULTS[mode];
  const source = profile && typeof profile === "object" ? profile : {};
  const requestedRole = String(source.default_role || source.defaultRole || defaults.default_role).trim().toLowerCase();
  return {
    default_role: ["viewer", "operator", "admin"].includes(requestedRole) ? requestedRole : defaults.default_role,
    compat_mode: String(source.compat_mode || source.compatMode || defaults.compat_mode).trim().toLowerCase() || defaults.compat_mode,
    mutations_enabled: Object.prototype.hasOwnProperty.call(source, "mutations_enabled")
      ? Boolean(source.mutations_enabled)
      : Object.prototype.hasOwnProperty.call(source, "mutationsEnabled")
        ? Boolean(source.mutationsEnabled)
        : defaults.mutations_enabled,
  };
}

function applyManagedMcpProfileToState(artifactMode, profile) {
  const normalized = normalizeManagedMcpProfile(profile, artifactMode);
  if (normalizeManagedMcpArtifactMode(artifactMode) === "draft") {
    state.wizardDraftCurationMcpRole = normalized.default_role;
    state.wizardDraftCurationMcpMutations = normalized.mutations_enabled;
    return normalized;
  }
  state.wizardMcpRole = normalized.default_role;
  state.wizardMcpMutations = normalized.mutations_enabled;
  return normalized;
}

function managedMcpProfileFromState(artifactMode) {
  const mode = normalizeManagedMcpArtifactMode(artifactMode);
  if (mode === "draft") {
    return normalizeManagedMcpProfile(
      {
        default_role: String(els.wizardDraftCurationMcpRole?.value || state.wizardDraftCurationMcpRole || "viewer").trim(),
        compat_mode: "strict",
        mutations_enabled: Boolean(els.wizardDraftCurationMcpMutations?.checked ?? state.wizardDraftCurationMcpMutations),
      },
      mode,
    );
  }
  return normalizeManagedMcpProfile(
    {
      default_role: String(els.wizardMcpRole?.value || state.wizardMcpRole || "viewer").trim(),
      compat_mode: "strict",
      mutations_enabled: Boolean(els.wizardMcpMutations?.checked ?? state.wizardMcpMutations),
    },
    mode,
  );
}

async function ensureManagedMcpConfigLoaded(force = false) {
  if (!window.desktopWorkspace || typeof window.desktopWorkspace.getManagedMcpConfig !== "function") {
    return null;
  }
  if (state.wizardManagedMcpLoaded && !force) {
    return null;
  }
  const payload = await window.desktopWorkspace.getManagedMcpConfig();
  const profiles = payload && typeof payload === "object" && payload.profiles && typeof payload.profiles === "object"
    ? payload.profiles
    : {};
  applyManagedMcpProfileToState("draft", profiles.draft || {});
  applyManagedMcpProfileToState("reviewed", profiles.reviewed || {});
  state.wizardManagedMcpLoaded = true;
  return payload;
}

async function saveManagedMcpProfileFromUi(artifactMode) {
  if (!window.desktopWorkspace || typeof window.desktopWorkspace.saveManagedMcpConfig !== "function") {
    throw new Error("Managed desktop MCP controls are only available inside the desktop shell.");
  }
  const mode = normalizeManagedMcpArtifactMode(artifactMode);
  const profile = managedMcpProfileFromState(mode);
  const payload = await window.desktopWorkspace.saveManagedMcpConfig({
    artifact_mode: mode,
    default_role: profile.default_role,
    compat_mode: profile.compat_mode,
    mutations_enabled: profile.mutations_enabled,
    restart: true,
  });
  const profiles = payload?.config?.profiles;
  if (profiles && typeof profiles === "object") {
    applyManagedMcpProfileToState("draft", profiles.draft || {});
    applyManagedMcpProfileToState("reviewed", profiles.reviewed || {});
    state.wizardManagedMcpLoaded = true;
  } else {
    await ensureManagedMcpConfigLoaded(true);
  }
  return payload;
}

async function ensureDesktopDraftCurationMcp() {
  if (!window.desktopWorkspace || typeof window.desktopWorkspace.ensureDraftCurationMcp !== "function") {
    return null;
  }
  return window.desktopWorkspace.ensureDraftCurationMcp();
}

function renderWizardDraftCurationSignal(el, message, { isWarn = false, fallbackLabel = "Status" } = {}) {
  if (!el) {
    return;
  }
  const payload = normalizeWizardResultPayload(message, isWarn);
  const tone = ["ok", "warn", "error", "info"].includes(payload.tone) ? payload.tone : "info";
  const title = payload.title || payload.detail || "Waiting for draft curation state.";
  const detail = payload.title && payload.detail ? payload.detail : "";
  const meta = [payload.next, payload.meta].filter(Boolean).join(" | ");
  el.className = `wizard-draft-curation-signal wizard-draft-curation-signal-${tone}`;
  el.innerHTML =
    `<div class="wizard-draft-curation-signal-label">${escapeHtml(fallbackLabel)}</div>` +
    `<div class="wizard-draft-curation-signal-title">${escapeHtml(trimDisplay(title, 80))}</div>` +
    (detail ? `<div class="wizard-draft-curation-signal-detail">${escapeHtml(trimDisplay(detail, 140))}</div>` : "") +
    (meta ? `<div class="wizard-draft-curation-signal-meta">${escapeHtml(trimDisplay(meta, 160))}</div>` : "");
}

function renderWizardDraftCurationRunId() {
  const runId = currentWizardRunId();
  if (els.wizardDraftCurationRunId) {
    els.wizardDraftCurationRunId.textContent = runId || "No run open yet";
    els.wizardDraftCurationRunId.title = runId || "No run open yet";
  }
  if (els.btnWizardDraftCurationCopyRunId) {
    els.btnWizardDraftCurationCopyRunId.disabled = !runId;
    els.btnWizardDraftCurationCopyRunId.textContent =
      els.btnWizardDraftCurationCopyRunId.dataset.copied === "true" ? "Copied" : "Copy Run ID";
  }
}

function renderWizardDraftCurationWorkspaceChrome() {
  /* Default: sidebar hidden. wizardDraftCurationSidebarCollapsed=true means hidden (default). */
  const collapsed = state.wizardDraftCurationSidebarCollapsed !== false;
  const open = !collapsed;
  if (els.wizardDraftCurationWorkspaceGrid) {
    els.wizardDraftCurationWorkspaceGrid.classList.toggle("sidebar-open", open);
    els.wizardDraftCurationWorkspaceGrid.classList.toggle("sidebar-collapsed", collapsed);
  }
  if (els.wizardDraftCurationWorkspaceRail) {
    els.wizardDraftCurationWorkspaceRail.setAttribute("aria-hidden", collapsed ? "true" : "false");
  }
  if (els.btnWizardDraftCurationSidebarToggle) {
    els.btnWizardDraftCurationSidebarToggle.setAttribute("aria-expanded", String(open));
  }
  if (els.btnWizardDraftCurationSidebarRestore) {
    els.btnWizardDraftCurationSidebarRestore.textContent = open ? "Hide Setup" : "Show Setup";
    els.btnWizardDraftCurationSidebarRestore.setAttribute("aria-expanded", String(open));
  }
  if (els.wizardDraftCurationSidebarToggleIcon) {
    els.wizardDraftCurationSidebarToggleIcon.textContent = open ? "<<" : ">>";
  }
  if (els.wizardDraftCurationSidebarToggleLabel) {
    els.wizardDraftCurationSidebarToggleLabel.textContent = open ? "Hide Setup" : "Show Setup";
  }
}

function renderWizardDraftCurationStatus() {
  if (!els.wizardDraftCurationStatus && !els.wizardDraftCurationWorkspaceStatus) {
    return;
  }
  const payload = state.wizardDraftCurationStatus || {};
  const draftState = payload.draft_curation || {};
  const lease = draftState.lease || {};
  const status = String(draftState.status || "not_started").trim().toLowerCase() || "not_started";
  const activeLease = Boolean(lease.active);
  const proposalCount = Number(draftState.proposal_count || 0);
  const acceptedCount = Number(draftState.accepted_count || 0);
  const rejectedCount = Number(draftState.rejected_count || 0);
  const promotedCount = Number(draftState.promoted_count || 0);
  const staleCount = Number(draftState.stale_count || 0);
  const resultPayload = !payload.draft_ready
    ? {
        tone: "info",
        title: "Assistant/agent draft curation unlocks after Build.",
        detail: "Once a draft exists, an assistant or agent can propose bounded cleanup and ranking hints here without touching publish or activation.",
        next: "Build a draft first, then open this optional lane if you want model help.",
      }
    : {
        tone: activeLease ? "ok" : proposalCount > 0 || acceptedCount > 0 || rejectedCount > 0 ? "warn" : "info",
        title: activeLease
          ? `${friendlyDraftCurationStatus(status)} lease: ${String(lease.model_identity || lease.owner_id || "unknown curator").trim() || "unknown curator"}`
          : `${friendlyDraftCurationStatus(status)} draft curation lane`,
        detail: activeLease
          ? "An assistant or agent is actively shaping this draft. Suggestions stay separate until you explicitly promote them."
          : proposalCount > 0 || acceptedCount > 0 || rejectedCount > 0
            ? "Assistant/agent suggestions exist for this draft. You can accept, reject, or promote them one at a time."
            : "No assistant/agent suggestions exist yet. The default human-only review path is still ready right now.",
        next: activeLease
          ? "Use Refresh Suggestions to watch the queue, or Release Lease if the curator is stuck."
          : "If you want model-aware draft shaping, let an assistant or agent call the draft curation tools, then review the queue here.",
        meta: `pending=${proposalCount} | accepted=${acceptedCount} | rejected=${rejectedCount} | promoted=${promotedCount} | stale=${staleCount}`,
      };
  if (!payload.draft_ready) {
    if (els.wizardDraftCurationQueue) {
      els.wizardDraftCurationQueue.classList.remove("has-items");
    }
    if (els.wizardDraftCurationStatus) {
      wizardResult(els.wizardDraftCurationStatus, resultPayload);
    }
    if (els.wizardDraftCurationWorkspaceStatus) {
      renderWizardDraftCurationSignal(els.wizardDraftCurationWorkspaceStatus, resultPayload, { fallbackLabel: "Curation Lane" });
    }
    return;
  }
  if (els.wizardDraftCurationStatus) {
    wizardResult(els.wizardDraftCurationStatus, resultPayload);
  }
  if (els.wizardDraftCurationWorkspaceStatus) {
    renderWizardDraftCurationSignal(els.wizardDraftCurationWorkspaceStatus, resultPayload, { fallbackLabel: "Curation Lane" });
  }
  if (els.btnWizardDraftCurationForceRelease) {
    els.btnWizardDraftCurationForceRelease.hidden = !activeLease;
    els.btnWizardDraftCurationForceRelease.disabled = !activeLease;
  }
  if (els.wizardDraftCurationQueue) {
    els.wizardDraftCurationQueue.classList.toggle("has-items", proposalCount > 0 || acceptedCount > 0 || rejectedCount > 0 || promotedCount > 0 || staleCount > 0);
  }
}

function renderWizardDraftCurationList() {
  renderWizardDraftCurationStatus();
  if (!els.wizardDraftCurationList) {
    return;
  }
  const rows = Array.isArray(state.wizardDraftCurationCards) ? state.wizardDraftCurationCards : [];
  const allRows = Array.isArray(state.wizardDraftCurationAllCards) ? state.wizardDraftCurationAllCards : [];
  const statusFilter = String(state.wizardDraftCurationMeta?.statusFilter || "pending").trim().toLowerCase() || "pending";
  const readyCount = allRows.filter((proposal) => {
    const status = String(proposal?.status || "pending").trim().toLowerCase();
    return status === "pending" || status === "accepted";
  }).length;
  if (els.wizardDraftCurationSearch) {
    els.wizardDraftCurationSearch.value = String(state.wizardDraftCurationMeta?.search || "");
  }
  if (els.wizardDraftCurationStatusFilter) {
    els.wizardDraftCurationStatusFilter.value = statusFilter;
  }
  if (els.wizardDraftCurationPageSize) {
    els.wizardDraftCurationPageSize.value = String(state.wizardDraftCurationMeta?.pageSize || 6);
  }
  if (els.wizardDraftCurationQueue) {
    els.wizardDraftCurationQueue.classList.toggle("has-items", Number(state.wizardDraftCurationMeta?.filteredTotal || 0) > 0);
  }
  if (els.btnWizardDraftCurationPromoteAll) {
    els.btnWizardDraftCurationPromoteAll.disabled = readyCount === 0;
  }
  if (!rows.length) {
    const label = statusFilter === "pending" ? "No pending assistant/agent suggestions are waiting." : "No assistant/agent suggestions match this filter yet.";
    els.wizardDraftCurationList.innerHTML = `<div class="memory-empty">${escapeHtml(label)}</div>`;
    renderWizardDraftCurationPager();
    return;
  }
  els.wizardDraftCurationList.innerHTML = rows
    .map((proposal) => {
      const episodeId = String(proposal.episode_id || "").trim();
      const cardPreview = proposal.card_preview || {};
      const status = String(proposal.status || "pending").trim().toLowerCase() || "pending";
      const suggestionTitle = String(proposal.title || "").trim() || String(cardPreview.title || "").trim() || episodeId;
      const detail = String(proposal.rationale || proposal.summary || cardPreview.summary || "").trim();
      return (
        `<article class="wizard-draft-proposal-item ${escapeHtml(status)}" data-draft-episode-id="${escapeHtml(episodeId)}">` +
        `<div class="wizard-draft-proposal-top">` +
        `<strong>${escapeHtml(episodeId)}</strong>` +
        `<span>${escapeHtml(status.replaceAll("_", " "))}</span>` +
        `</div>` +
        `<div class="wizard-draft-proposal-title">${escapeHtml(trimDisplay(suggestionTitle, 140))}</div>` +
        (detail ? `<div class="wizard-draft-proposal-summary">${escapeHtml(trimDisplay(detail, 180))}</div>` : "") +
        `<div class="wizard-draft-proposal-meta">${escapeHtml(`build=${proposal.build_id || "-"} | model=${proposal.model_identity || "unknown"}`)}</div>` +
        `<div class="wizard-review-actions">` +
        `<button type="button" class="btn ghost draft-open">Inspect</button>` +
        `</div>` +
        `</article>`
      );
    })
    .join("");
  for (const node of els.wizardDraftCurationList.querySelectorAll(".wizard-draft-proposal-item")) {
    const episodeId = String(node.getAttribute("data-draft-episode-id") || "").trim();
    node.querySelector(".draft-open")?.addEventListener("click", (event) => {
      openWizardDraftCurationProposal(episodeId, event.currentTarget).catch((error) => {
        renderWizardDraftCurationFeedback(error.message, true);
      });
    });
  }
  renderWizardDraftCurationPager();
}

async function refreshWizardDraftCurationStatus(runId = state.wizardRunId || undefined) {
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  const payload = await jsonFetch(`/api/wizard/draft-curation/status${query}`);
  state.wizardDraftCurationStatus = payload;
  renderWizardDraftCurationStatus();
}

function renderWizardDraftCurationMcp() {
  if (!els.wizardDraftCurationMcpStatus) {
    return;
  }
  const payload = state.wizardDraftCurationMcp || {};
  const mcp = payload.mcp || {};
  const preview = mcp.preview || {};
  const selectedTarget = String(preview.target || state.wizardDraftCurationMcpTarget || "claude_code").trim().toLowerCase() || "claude_code";
  const selectedScope = String(preview.claude_code_scope || state.wizardDraftCurationMcpScope || "user").trim().toLowerCase() || "user";
  const selectedRole = String(preview.default_role || state.wizardDraftCurationMcpRole || "viewer").trim().toLowerCase() || "viewer";
  const selectedMutations = Object.prototype.hasOwnProperty.call(preview, "mutations_enabled")
    ? Boolean(preview.mutations_enabled)
    : Boolean(state.wizardDraftCurationMcpMutations);
  const issues = Array.isArray(mcp.issues) ? mcp.issues : [];
  const status = String(mcp.status || "not_installed").trim().toLowerCase() || "not_installed";
  const draftReady = Boolean(payload.draft_ready);
  state.wizardDraftCurationMcpScope = selectedScope;
  state.wizardDraftCurationMcpRole = selectedRole;
  state.wizardDraftCurationMcpMutations = selectedMutations;
  state.wizardDraftCurationMcpTarget = selectedTarget;
  if (els.wizardDraftCurationMcpTarget) {
    els.wizardDraftCurationMcpTarget.value = selectedTarget;
  }
  if (els.wizardDraftCurationMcpScope) {
    els.wizardDraftCurationMcpScope.value = selectedScope;
    els.wizardDraftCurationMcpScope.disabled = selectedTarget !== "claude_code";
  }
  if (els.wizardDraftCurationMcpRole) {
    els.wizardDraftCurationMcpRole.value = selectedRole;
  }
  if (els.wizardDraftCurationMcpMutations) {
    els.wizardDraftCurationMcpMutations.checked = selectedMutations;
  }
  if (els.wizardDraftCurationTargets) {
    els.wizardDraftCurationTargets.hidden = !draftReady;
    if (!draftReady) {
      els.wizardDraftCurationTargets.open = false;
    }
  }
  wizardResult(els.wizardDraftCurationMcpStatus, {
    tone: status === "installed" || status === "export_ready" ? "ok" : draftReady ? "info" : "warn",
    title: draftReady ? `Connect assistant/agent to this draft: ${friendlyMcpStatus(status)}` : "Connect assistant/agent to this draft: not ready yet",
    detail: issues.length
      ? issues.join(" ")
      : `${integrationTargetDisplay(selectedTarget, mcp)} is ready for draft-curation setup with ${friendlyMcpRole(selectedRole).toLowerCase()} role, strict mode, and mutation tools ${selectedMutations ? "on" : "off"}.`,
    next: draftReady
      ? "Install or export the target you want, then tell the assistant or agent to work on this run_id."
      : "Finish Import and Build first. Then this panel can wire an assistant or agent into the draft-curation lane.",
    meta: `target=${selectedTarget} | role=${selectedRole} | compat=strict | mutations=${selectedMutations ? "on" : "off"}${selectedScope ? ` | scope=${selectedScope}` : ""}`,
  });
  if (els.wizardDraftCurationWorkspaceMcpSummary) {
    renderWizardDraftCurationSignal(
      els.wizardDraftCurationWorkspaceMcpSummary,
      {
        tone: status === "installed" || status === "export_ready" ? "ok" : draftReady ? "info" : "warn",
        title: !draftReady
          ? "Draft connector locked until Build finishes."
          : status === "installed"
            ? `${integrationTargetDisplay(selectedTarget, mcp)} ready${selectedTarget === "claude_code" ? ` in ${friendlyMcpScope(selectedScope)} scope` : ""}.`
            : status === "export_ready"
              ? "Draft setup bundle is ready to export."
              : `${integrationTargetDisplay(selectedTarget, mcp)} ${friendlyMcpStatus(status)}.`,
        detail: issues.length
          ? issues.join(" ")
          : draftReady
            ? `${friendlyMcpRole(selectedRole)} mode, strict compatibility, and mutation tools ${selectedMutations ? "on" : "off"} for this managed draft lane.`
            : "Build the draft first, then install or repair the connector.",
        meta: `scope=${friendlyMcpScope(selectedScope)} | ${friendlyMcpRole(selectedRole)} | strict | mutations ${selectedMutations ? "on" : "off"}`,
      },
      { fallbackLabel: "Assistant/Agent Connector" },
    );
  }
  if (els.btnWizardDraftCurationMcpExport) {
    els.btnWizardDraftCurationMcpExport.disabled = !draftReady;
  }
  if (els.btnWizardDraftCurationMcpApply) {
    els.btnWizardDraftCurationMcpApply.disabled = !draftReady;
  }
  renderWizardMcpTargets(els.wizardDraftCurationMcpTargets, {
    mcp,
    selectedScope,
    resultNode: els.wizardDraftCurationMcpStatus,
    onInstall: runWizardDraftCurationMcpInstall,
    onRemove: runWizardDraftCurationMcpRemove,
    onExport: exportWizardDraftCurationMcp,
    disabled: !draftReady,
    emptyMessage: draftReady ? "No draft-curation assistant/agent targets detected." : "Build a draft first, then connect an assistant or agent here.",
  });
}

function renderWizardDraftCurationFeedback(message, isWarn = false) {
  if (els.wizardDraftCurationResult) {
    wizardResult(els.wizardDraftCurationResult, message, isWarn);
  }
}

function wizardDraftCurationMcpRequestBody(runId = state.wizardRunId || undefined) {
  const profile = managedMcpProfileFromState("draft");
  return {
    run_id: runId,
    target: String(els.wizardDraftCurationMcpTarget?.value || state.wizardDraftCurationMcpTarget || "claude_code").trim() || "claude_code",
    claude_code_scope: String(els.wizardDraftCurationMcpScope?.value || state.wizardDraftCurationMcpScope || "user").trim() || "user",
    default_role: profile.default_role,
    compat_mode: profile.compat_mode,
    mutations_enabled: profile.mutations_enabled,
  };
}

function renderWizardDraftCurationPager() {
  const meta = state.wizardDraftCurationMeta || {};
  const page = Math.max(1, Number(meta.page || 1));
  const totalPages = Math.max(1, Number(meta.totalPages || 1));
  const filteredTotal = Number(meta.filteredTotal || 0);
  if (els.wizardDraftCurationPager) {
    els.wizardDraftCurationPager.textContent = filteredTotal > 0
      ? `Page ${page} of ${totalPages} • ${wizardCountLabel(filteredTotal, "suggestion")}`
      : "Queue idle";
  }
  if (els.btnWizardDraftCurationPrev) {
    els.btnWizardDraftCurationPrev.disabled = page <= 1 || filteredTotal <= 0;
  }
  if (els.btnWizardDraftCurationNext) {
    els.btnWizardDraftCurationNext.disabled = page >= totalPages || filteredTotal <= 0;
  }
}

async function refreshWizardDraftCurationMcpStatus(runId = state.wizardRunId || undefined) {
  await ensureManagedMcpConfigLoaded();
  await ensureDesktopDraftCurationMcp().catch(() => null);
  if (!runId) {
    state.wizardDraftCurationMcp = null;
    renderWizardDraftCurationMcp();
    return;
  }
  const payload = await jsonFetch("/api/wizard/draft-curation/mcp/status", {
    method: "POST",
    body: JSON.stringify(wizardDraftCurationMcpRequestBody(runId)),
  });
  state.wizardDraftCurationMcp = payload;
  renderWizardDraftCurationMcp();
}

async function runWizardDraftCurationMcpInstall(target, ownershipAction = "") {
  const claudeCodeScope = String(els.wizardDraftCurationMcpScope?.value || state.wizardDraftCurationMcpScope || "user").trim() || "user";
  const profile = managedMcpProfileFromState("draft");
  const targetLabel = integrationTargetDisplay(target, (state.wizardDraftCurationMcp || {}).mcp || {});
  const payload = await jsonFetch("/api/wizard/draft-curation/mcp/install", {
    method: "POST",
    body: JSON.stringify({
      ...wizardDraftCurationMcpRequestBody(state.wizardRunId || undefined),
      target,
      ownership_action: ownershipAction || undefined,
    }),
  });
  wizardResult(els.wizardDraftCurationMcpStatus, {
    tone: "ok",
    title: "Draft-curation setup updated.",
    detail: `${targetLabel} now points at the current draft curation lane${target === "claude_code" ? ` in ${friendlyMcpScope(claudeCodeScope)} scope` : ""}.`,
    next: "Restart the external client if it was already open, then tell it to use this run_id for draft curation.",
    meta: `target=${target}${target === "claude_code" ? ` | scope=${claudeCodeScope}` : ""} | role=${profile.default_role} | mutations=${profile.mutations_enabled ? "on" : "off"}`,
  });
  state.wizardDraftCurationMcp = {
    ...(state.wizardDraftCurationMcp || {}),
    mcp: payload.mcp || {},
  };
  await refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined);
}

async function runWizardDraftCurationMcpRemove(target) {
  const claudeCodeScope = String(els.wizardDraftCurationMcpScope?.value || state.wizardDraftCurationMcpScope || "user").trim() || "user";
  const targetLabel = integrationTargetDisplay(target, (state.wizardDraftCurationMcp || {}).mcp || {});
  const payload = await jsonFetch("/api/wizard/draft-curation/mcp/remove", {
    method: "POST",
    body: JSON.stringify({
      ...wizardDraftCurationMcpRequestBody(state.wizardRunId || undefined),
      target,
    }),
  });
  wizardResult(els.wizardDraftCurationMcpStatus, {
    tone: "info",
    title: "Draft-curation setup removed.",
    detail: `${targetLabel} no longer points at this draft curation lane${target === "claude_code" ? ` in ${friendlyMcpScope(claudeCodeScope)} scope` : ""}.`,
    next: "Install it again here if you want that assistant or agent back on this draft.",
    meta: `target=${target}${target === "claude_code" ? ` | scope=${claudeCodeScope}` : ""}`,
  });
  state.wizardDraftCurationMcp = {
    ...(state.wizardDraftCurationMcp || {}),
    mcp: payload.mcp || {},
  };
  await refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined);
}

async function exportWizardDraftCurationMcp(target = String(els.wizardDraftCurationMcpTarget?.value || state.wizardDraftCurationMcpTarget || "claude_code").trim() || "claude_code") {
  const payload = await jsonFetch("/api/wizard/draft-curation/mcp/export", {
    method: "POST",
    body: JSON.stringify({
      ...wizardDraftCurationMcpRequestBody(state.wizardRunId || undefined),
      target,
    }),
  });
  const targetLabel = integrationTargetDisplay(String(payload.target || target), (state.wizardDraftCurationMcp || {}).mcp || {});
  wizardResult(els.wizardDraftCurationMcpStatus, {
    tone: "ok",
    title: "Draft-curation setup bundle is ready.",
    detail: `Use this when you want ${targetLabel.toLowerCase()} to connect to the current draft-cards lane instead of the published runtime.`,
    next: "Use one of the exported launchers or config snippets, then tell the assistant or agent to work on this run_id.",
    meta: `target=${payload.target || target} | server=${payload.export?.server_name || "-"} | files=${Array.isArray(payload.export?.artifact_paths) ? payload.export.artifact_paths.length : 0}`,
  });
  state.wizardDraftCurationMcp = {
    ...(state.wizardDraftCurationMcp || {}),
    mcp: payload.mcp || {},
  };
  await refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined);
}

async function applyWizardDraftCurationManagedMcpProfile() {
  const profile = managedMcpProfileFromState("draft");
  await saveManagedMcpProfileFromUi("draft");
  wizardResult(els.wizardDraftCurationMcpStatus, {
    tone: "ok",
    title: "Managed draft MCP restarted.",
    detail: `The desktop-managed draft connector now runs with ${friendlyMcpRole(profile.default_role).toLowerCase()} role and mutation tools ${profile.mutations_enabled ? "on" : "off"}.`,
    next: "Restart the external client if it was already open, then refresh the queue or install targets again if needed.",
    meta: `role=${profile.default_role} | compat=strict | mutations=${profile.mutations_enabled ? "on" : "off"}`,
  });
  await refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined);
}

async function loadWizardDraftCurationProposals(runId = state.wizardRunId || undefined) {
  const requestSeq = state.wizardDraftCurationRequestSeq + 1;
  state.wizardDraftCurationRequestSeq = requestSeq;
  if (!runId) {
    state.wizardDraftCurationAllCards = [];
    state.wizardDraftCurationCards = [];
    state.wizardDraftCurationMeta = {
      ...(state.wizardDraftCurationMeta || {}),
      total: 0,
      filteredTotal: 0,
      page: 1,
      totalPages: 1,
    };
    renderWizardDraftCurationList();
    return;
  }
  const params = new URLSearchParams();
  params.set("run_id", runId);
  params.set("status", String(state.wizardDraftCurationMeta?.statusFilter || "pending"));
  const payload = await jsonFetch(`/api/wizard/draft-curation/proposals?${params.toString()}`);
  if (requestSeq !== state.wizardDraftCurationRequestSeq) {
    return;
  }
  state.wizardDraftCurationAllCards = Array.isArray(payload.proposals) ? payload.proposals : [];
  applyWizardDraftCurationFilters();
}

function applyWizardDraftCurationFilters() {
  const search = String(state.wizardDraftCurationMeta?.search || "").trim().toLowerCase();
  const rows = Array.isArray(state.wizardDraftCurationAllCards) ? state.wizardDraftCurationAllCards : [];
  const filteredRows = rows.filter((proposal) => {
    if (!search) {
      return true;
    }
    const hay = [
      proposal.episode_id,
      proposal.title,
      proposal.summary,
      proposal.rationale,
      proposal.model_identity,
      proposal.card_preview?.title,
      proposal.card_preview?.summary,
    ]
      .map((item) => String(item || "").toLowerCase())
      .join(" ");
    return hay.includes(search);
  });
  const pageSize = Math.max(1, Number(state.wizardDraftCurationMeta?.pageSize || 6));
  const filteredTotal = filteredRows.length;
  const totalPages = Math.max(1, Math.ceil(filteredTotal / pageSize));
  const page = Math.min(totalPages, Math.max(1, Number(state.wizardDraftCurationMeta?.page || 1)));
  const start = (page - 1) * pageSize;
  state.wizardDraftCurationAllCards = filteredRows;
  state.wizardDraftCurationCards = filteredRows.slice(start, start + pageSize);
  state.wizardDraftCurationMeta = {
    ...(state.wizardDraftCurationMeta || {}),
    total: rows.length,
    filteredTotal,
    page,
    pageSize,
    totalPages,
  };
  renderWizardDraftCurationList();
}

function closeWizardDraftCurationProposal({ restoreFocus = true } = {}) {
  if (!els.wizardDraftCurationProposalDialog) {
    return;
  }
  if (typeof els.wizardDraftCurationProposalDialog.close === "function" && els.wizardDraftCurationProposalDialog.open) {
    els.wizardDraftCurationProposalDialog.close();
  } else {
    els.wizardDraftCurationProposalDialog.removeAttribute("open");
  }
  if (restoreFocus) {
    const target = state.wizardDraftCurationReturnFocus;
    if (target && typeof target.focus === "function") {
      target.focus();
    }
  }
  state.wizardDraftCurationReturnFocus = null;
  state.wizardDraftCurationSelectedEpisodeId = "";
  state.wizardDraftCurationDetail = null;
}

function navigateWizardDraftCurationProposal(direction) {
  const items = Array.isArray(state.wizardDraftCurationCards) ? state.wizardDraftCurationCards : [];
  if (items.length === 0) return;
  const currentId = state.wizardDraftCurationSelectedEpisodeId || "";
  const idx = items.findIndex((item) => (item.episode_id || "") === currentId);
  const nextIdx = direction === "next" ? idx + 1 : idx - 1;
  if (nextIdx < 0 || nextIdx >= items.length) return;
  const nextItem = items[nextIdx];
  if (!nextItem || !nextItem.episode_id) return;
  openWizardDraftCurationProposal(nextItem.episode_id).catch((error) => {
    wizardResult(els.wizardDraftCurationProposalResult, error.message, true);
  });
}

function renderWizardDraftCurationContext(detail = {}) {
  const context = detail.context || {};
  const policy = context.policy || detail.context_policy || {};
  const transcriptRows = Array.isArray(context.transcript_context) ? context.transcript_context : [];
  const neighbors = Array.isArray(context.neighbor_cards) ? context.neighbor_cards : [];
  if (!els.wizardDraftCurationContext) {
    return;
  }
  const transcriptHtml = transcriptRows.length
    ? transcriptRows
        .map((row) => {
          const prefix = row.is_anchor ? "anchor" : `±${row.distance || 0}`;
          return `<li><strong>${escapeHtml(`${prefix} | ${row.role || "unknown"}`)}</strong> ${escapeHtml(trimDisplay(row.text || "", 220))}</li>`;
        })
        .join("")
    : "<li>No local transcript context was available for this card.</li>";
  const neighborHtml = neighbors.length
    ? neighbors
        .map((row) => `<li><strong>${escapeHtml(row.title || row.episode_id || "neighbor")}</strong> ${escapeHtml(trimDisplay(row.summary || "", 120))}</li>`)
        .join("")
    : "<li>No neighboring cards were attached for this view.</li>";
  els.wizardDraftCurationContext.innerHTML =
    `<div class="wizard-result-shell">` +
    `<div class="wizard-result-title">${context.partial ? "Bounded context is partial." : "Bounded context is ready."}</div>` +
    `<div class="wizard-result-detail">${escapeHtml(context.partial ? `Context was capped or unavailable: ${(context.partial_reasons || []).join(", ") || "unknown reason"}.` : "The assistant or agent saw only bounded local context for this card, not an open-ended transcript crawl.")}</div>` +
    `<div class="wizard-result-next"><strong>Context policy:</strong> window=${escapeHtml(String(policy.default_window ?? "-"))} | max_messages=${escapeHtml(String(policy.max_messages ?? "-"))} | max_bytes=${escapeHtml(String(policy.max_bytes ?? "-"))}</div>` +
    `<div class="wizard-draft-context-grid"><section><strong>Transcript context</strong><ul class="wizard-result-list">${transcriptHtml}</ul></section><section><strong>Neighbor cards</strong><ul class="wizard-result-list">${neighborHtml}</ul></section></div>` +
    `</div>`;
}

async function openWizardDraftCurationProposal(episodeId, returnFocusNode = null) {
  const query = new URLSearchParams();
  if (state.wizardRunId) {
    query.set("run_id", state.wizardRunId);
  }
  query.set("include_context", "true");
  query.set("context_window", "2");
  const requestSeq = state.wizardDraftCurationDetailRequestSeq + 1;
  state.wizardDraftCurationDetailRequestSeq = requestSeq;
  const payload = await jsonFetch(`/api/wizard/draft-curation/cards/${encodeURIComponent(episodeId)}?${query.toString()}`);
  if (requestSeq !== state.wizardDraftCurationDetailRequestSeq) {
    return;
  }
  state.wizardDraftCurationDetail = payload;
  state.wizardDraftCurationSelectedEpisodeId = String(episodeId || "").trim();
  state.wizardDraftCurationReturnFocus = returnFocusNode || document.activeElement;
  /* Reset to card comparison view on each new card */
  if (els.wizardDraftCurationContext) els.wizardDraftCurationContext.hidden = true;
  if (els.wizardDraftCurationDiffView) els.wizardDraftCurationDiffView.hidden = false;
  if (els.btnWizardDraftCurationToggleView) els.btnWizardDraftCurationToggleView.textContent = "Show Transcript & Neighbors";
  const proposal = payload.proposal || {};
  const card = payload.card || {};
  if (els.wizardDraftCurationProposalMeta) {
    const statusText = String(proposal.status || "pending").replaceAll("_", " ");
    els.wizardDraftCurationProposalMeta.textContent = `${episodeId}  •  ${statusText}`;
  }
  if (false && els.wizardDraftCurationProposalMeta) {
    wizardResult(els.wizardDraftCurationProposalMeta, {
      tone: String(proposal.status || "pending").trim().toLowerCase() === "promoted" ? "ok" : "info",
      title: `${episodeId} • ${String(proposal.status || "pending").replaceAll("_", " ")}`,
      detail: String(proposal.model_identity || "").trim()
        ? `Assistant/agent suggestion from ${proposal.model_identity}.`
        : "Assistant/agent suggestion for this draft card.",
      next: "Use This In Review copies the suggestion into the real review path. Dismiss keeps the original draft card.",
      meta: `build=${proposal.build_id || payload.build_id || "-"} | suggestion=${proposal.proposal_id || "-"}`,
    });
  }
  if (els.wizardDraftCurationCurrentCard) {
    els.wizardDraftCurationCurrentCard.innerHTML = renderDraftProposalPreviewCard({
      ...card,
      rationale: "",
      retrieval_cues: [],
    });
  }
  if (els.wizardDraftCurationSuggestedCard) {
    els.wizardDraftCurationSuggestedCard.innerHTML = renderDraftProposalPreviewCard({
      title: proposal.title || card.title,
      summary: proposal.summary || card.summary,
      actors: proposal.actors || card.actors || [],
      topic_tags: proposal.topic_tags || card.topic_tags || [],
      rationale: proposal.rationale,
      retrieval_cues: proposal.retrieval_cues || [],
    });
  }
  renderWizardDraftCurationContext(payload);
  if (els.btnWizardDraftCurationReject) {
    const status = String(proposal.status || "pending").trim().toLowerCase();
    els.btnWizardDraftCurationReject.disabled = status === "rejected" || status === "promoted";
  }
  if (els.btnWizardDraftCurationPromote) {
    const status = String(proposal.status || "pending").trim().toLowerCase();
    els.btnWizardDraftCurationPromote.disabled = !["pending", "accepted"].includes(status);
  }
  wizardResult(els.wizardDraftCurationProposalResult, {
    tone: "info",
    title: "Assistant/agent suggestions stay separate until you use one in Review.",
    detail: "Use This In Review copies the suggestion into the real review decision for this card.",
    next: "Dismiss Assistant/Agent Suggestion ignores the suggestion and keeps the original draft card untouched.",
  });
  if (typeof els.wizardDraftCurationProposalDialog?.showModal === "function") {
    if (!els.wizardDraftCurationProposalDialog.open) {
      els.wizardDraftCurationProposalDialog.showModal();
    }
  } else {
    els.wizardDraftCurationProposalDialog?.setAttribute("open", "open");
  }
}

async function updateWizardDraftProposal(action, episodeId) {
  const payload = await jsonFetch(`/api/wizard/draft-curation/proposals/${encodeURIComponent(episodeId)}/${action}`, {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      reviewer: "runtime_ui",
      note: action === "reject" ? "Dismissed from runtime UI." : "Used in review from runtime UI.",
    }),
  });
  await Promise.all([refreshWizardDraftCurationStatus(state.wizardRunId || undefined), loadWizardDraftCurationProposals(state.wizardRunId || undefined), refreshWizardReviewSummary(state.wizardRunId || undefined)]);
  if (action === "promote") {
    await loadWizardReviewCards();
  }
  if (state.wizardDraftCurationSelectedEpisodeId === episodeId && action !== "promote") {
    await openWizardDraftCurationProposal(episodeId, state.wizardDraftCurationReturnFocus);
  } else if (action === "promote") {
    closeWizardDraftCurationProposal();
  }
  renderWizardDraftCurationFeedback({
    tone: action === "reject" ? "warn" : "ok",
    title:
      action === "promote"
        ? `${episodeId} is now in Review.`
        : action === "reject"
          ? `${episodeId} dismissed.`
          : `${episodeId} ${action}ed.`,
    detail: action === "promote"
      ? "The suggestion is now copied into the real human review path for this card."
      : "The optional curation lane updated cleanly.",
    next: action === "promote" ? "Continue normal Review or Publish when you are ready." : "Inspect more suggestions or ignore the rest and continue human review.",
    meta: `proposal_status=${payload.proposal?.status || "-"}`,
  });
}

async function runWizardDraftProposalBulkAction(action) {
  const targetIds = (Array.isArray(state.wizardDraftCurationAllCards) ? state.wizardDraftCurationAllCards : [])
    .filter((proposal) => {
      const status = String(proposal?.status || "pending").trim().toLowerCase();
      return status === "pending" || status === "accepted";
    })
    .map((proposal) => String(proposal?.episode_id || "").trim())
    .filter(Boolean);
  if (!targetIds.length) {
    renderWizardDraftCurationFeedback({
      tone: "info",
      title: "No assistant/agent suggestions are ready to use.",
      detail: "Nothing changed in the queue.",
    });
    return;
  }
  closeWizardDraftCurationProposal({ restoreFocus: false });
  renderWizardDraftCurationFeedback({
    tone: "info",
    title: `Using ${targetIds.length} assistant/agent suggestion${targetIds.length === 1 ? "" : "s"}.`,
    detail: "The workspace will refresh when the batch finishes.",
  });
  let completed = 0;
  const failures = [];
  for (const episodeId of targetIds) {
    try {
      await jsonFetch(`/api/wizard/draft-curation/proposals/${encodeURIComponent(episodeId)}/${action}`, {
        method: "POST",
        body: JSON.stringify({
          run_id: state.wizardRunId || undefined,
          reviewer: "runtime_ui",
          note: "Used in review from runtime UI.",
        }),
      });
      completed += 1;
    } catch (error) {
      failures.push(`${episodeId}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  await Promise.all([
    refreshWizardDraftCurationStatus(state.wizardRunId || undefined),
    loadWizardDraftCurationProposals(state.wizardRunId || undefined),
    refreshWizardReviewSummary(state.wizardRunId || undefined),
  ]);
  if (action === "promote") {
    await loadWizardReviewCards();
  }
  renderWizardDraftCurationFeedback({
    tone: failures.length ? (completed ? "warn" : "error") : "ok",
    title: `Used ${completed} assistant/agent suggestion${completed === 1 ? "" : "s"}.`,
    detail: failures.length
      ? `Some items did not update cleanly.`
      : "The assistant/agent suggestions are now in the real review path.",
    bullets: failures.slice(0, 5),
    next: failures.length
      ? "Refresh the queue and retry the remaining items if needed."
      : "Continue Review, then Publish when every card has a real decision.",
    meta: `targeted=${targetIds.length} | completed=${completed} | failed=${failures.length}`,
  });
}

function setWizardDraftCurationPage(page) {
  const totalPages = Math.max(1, Number(state.wizardDraftCurationMeta?.totalPages || 1));
  state.wizardDraftCurationMeta = {
    ...(state.wizardDraftCurationMeta || {}),
    page: Math.min(totalPages, Math.max(1, Number(page || 1))),
  };
}

function resetWizardDraftCurationPaging() {
  state.wizardDraftCurationMeta = {
    ...(state.wizardDraftCurationMeta || {}),
    page: 1,
  };
}

function renderWizardReviewPager() {
  const meta = state.wizardReviewMeta || {};
  const page = Math.max(1, Number(meta.page || 1));
  const totalPages = Math.max(1, Number(meta.totalPages || 1));
  if (els.wizardReviewPager) {
    els.wizardReviewPager.textContent = `Page ${page} of ${totalPages}`;
  }
  if (els.btnWizardReviewPrev) {
    els.btnWizardReviewPrev.disabled = page <= 1;
  }
  if (els.btnWizardReviewNext) {
    els.btnWizardReviewNext.disabled = page >= totalPages;
  }
}

function renderWizardReviewFilters() {
  const facets = state.wizardReviewFacets || { actors: [], topics: [] };
  const filters = state.wizardReviewFilters || { actors: [], topics: [] };
  if (els.wizardReviewFacetToggle) {
    els.wizardReviewFacetToggle.setAttribute("aria-expanded", state.wizardReviewFacetMenuOpen ? "true" : "false");
    const activeCount = (filters.actors || []).length + (filters.topics || []).length;
    els.wizardReviewFacetToggle.textContent = activeCount > 0 ? `Filter (${activeCount})` : "Filter";
    els.wizardReviewFacetToggle.classList.toggle("wizard-action-ok", activeCount > 0);
  }
  if (els.wizardReviewFacetMenu) {
    els.wizardReviewFacetMenu.hidden = !state.wizardReviewFacetMenuOpen;
  }
  if (els.wizardReviewActiveFilters) {
    const actorLabel = (filters.actors || []).length ? `Actors: ${(filters.actors || []).join(", ")}` : "";
    const topicLabel = (filters.topics || []).length ? `Topics: ${(filters.topics || []).join(", ")}` : "";
    const combined = [actorLabel, topicLabel].filter(Boolean);
    els.wizardReviewActiveFilters.textContent = combined.length
      ? combined.join(" • ")
      : "No actor or topic filters are active.";
  }
  renderWizardReviewFacetGroup(els.wizardReviewActorFilters, facets.actors || [], filters.actors || [], "actors");
  renderWizardReviewFacetGroup(els.wizardReviewTopicFilters, facets.topics || [], filters.topics || [], "topics");
  if (els.wizardReviewActorSummary) {
    els.wizardReviewActorSummary.textContent = `Actors (${(facets.actors || []).length})`;
  }
  if (els.wizardReviewTopicSummary) {
    els.wizardReviewTopicSummary.textContent = `Topics (${(facets.topics || []).length})`;
  }
}

function renderWizardReviewFacetGroup(container, rows, selectedValues, kind) {
  if (!container) {
    return;
  }
  if (!Array.isArray(rows) || !rows.length) {
    container.innerHTML = '<div class="memory-empty">No filters are available yet.</div>';
    return;
  }
  const selected = new Set((selectedValues || []).map((value) => String(value || "").trim().toLowerCase()).filter(Boolean));
  container.innerHTML = rows
    .map((row) => {
      const value = String(row?.value || "").trim();
      const count = Number(row?.count || 0);
      const checked = selected.has(value.toLowerCase());
      return (
        `<label class="wizard-review-filter-option">` +
        `<span class="wizard-review-filter-option-label">` +
        `<input type="checkbox" data-review-filter-kind="${escapeHtml(kind)}" value="${escapeHtml(value)}"${checked ? ' checked="checked"' : ""} />` +
        `<span>${escapeHtml(value)}</span>` +
        `</span>` +
        `<span class="wizard-review-filter-option-count">${escapeHtml(String(count))}</span>` +
        `</label>`
      );
    })
    .join("");
  for (const input of container.querySelectorAll('input[data-review-filter-kind]')) {
    input.addEventListener("change", () => {
      toggleWizardReviewFacetValue(kind, String(input.value || ""), input.checked);
    });
  }
}

function toggleWizardReviewFacetMenu(forceOpen) {
  const nextOpen = typeof forceOpen === "boolean" ? forceOpen : !state.wizardReviewFacetMenuOpen;
  state.wizardReviewFacetMenuOpen = nextOpen;
  renderWizardReviewFilters();
}

function closeWizardReviewFacetMenu({ restoreFocus = false } = {}) {
  if (!state.wizardReviewFacetMenuOpen) {
    return;
  }
  state.wizardReviewFacetMenuOpen = false;
  renderWizardReviewFilters();
  if (restoreFocus) {
    els.btnWizardReviewFacetToggle?.focus();
  }
}

function closeWizardReviewEditorPickers({ restoreFocus = false } = {}) {
  const openKind = state.wizardReviewEditorPickerOpen;
  if (!openKind) {
    return;
  }
  state.wizardReviewEditorPickerOpen = null;
  renderWizardReviewEditorPicker("actors");
  renderWizardReviewEditorPicker("topics");
  if (restoreFocus) {
    if (openKind === "actors") {
      els.btnWizardReviewEditorActorsToggle?.focus();
    } else if (openKind === "topics") {
      els.btnWizardReviewEditorTopicsToggle?.focus();
    }
  }
}

function clearWizardReviewFacetFilters() {
  state.wizardReviewFilters = { actors: [], topics: [] };
  state.wizardReviewShouldFocus = true;
  state.wizardReviewFocusEpisodeId = "";
  resetWizardReviewPaging();
  renderWizardReviewFilters();
  loadWizardReviewCards().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
}

function toggleWizardReviewFacetValue(kind, rawValue, checked) {
  const value = String(rawValue || "").trim();
  if (!value) {
    return;
  }
  const current = new Set((state.wizardReviewFilters?.[kind] || []).map((item) => String(item || "").trim()).filter(Boolean));
  if (checked) {
    current.add(value);
  } else {
    current.delete(value);
  }
  state.wizardReviewFilters = {
    ...(state.wizardReviewFilters || {}),
    [kind]: Array.from(current).sort((left, right) => left.localeCompare(right)),
  };
  state.wizardReviewShouldFocus = true;
  state.wizardReviewFocusEpisodeId = "";
  resetWizardReviewPaging();
  renderWizardReviewFilters();
  loadWizardReviewCards().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
}

function wizardReviewCardById(episodeId) {
  const wanted = String(episodeId || "").trim();
  if (!wanted) {
    return null;
  }
  return state.wizardReviewCards.find((card) => String(card?.episode_id || "").trim() === wanted) || null;
}

function wizardReviewEditorDraftFromCard(card) {
  const reviewPayload = card?.review_payload || {};
  return {
    title: reviewTextValue(card, reviewPayload, "title"),
    summary: reviewTextValue(card, reviewPayload, "summary"),
    actors: reviewListValue(card, reviewPayload, "actors"),
    topic_tags: reviewListValue(card, reviewPayload, "topic_tags"),
    truth_family_id: String(reviewPayload.truth_family_id ?? card?.truth_family_id ?? "").trim(),
    supersedes_episode_id: String(reviewPayload.supersedes_episode_id ?? card?.supersedes_episode_id ?? "").trim(),
  };
}

function wizardReviewEditorDraftFromInputs() {
  return {
    title: String(els.wizardReviewEditorTitle?.value || "").trim(),
    summary: String(els.wizardReviewEditorSummary?.value || "").trim(),
    actors: [...(state.wizardReviewEditorSelections?.actors || [])],
    topic_tags: [...(state.wizardReviewEditorSelections?.topics || [])],
    truth_family_id: String(els.wizardReviewEditorTruthFamilyId?.value || "").trim(),
    supersedes_episode_id: String(els.wizardReviewEditorSupersedesEpisodeId?.value || "").trim(),
  };
}

function splitWizardReviewList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function wizardReviewEditorOptions(kind) {
  const facetRows = kind === "actors" ? (state.wizardReviewFacets?.actors || []) : (state.wizardReviewFacets?.topics || []);
  const fromFacets = facetRows.map((row) => String(row?.value || "").trim()).filter(Boolean);
  const fromSelection = [...(state.wizardReviewEditorSelections?.[kind] || [])];
  return Array.from(new Set([...fromFacets, ...fromSelection])).sort((left, right) => left.localeCompare(right));
}

function renderWizardReviewEditorPicker(kind) {
  const selected = [...(state.wizardReviewEditorSelections?.[kind] || [])];
  const button = kind === "actors" ? els.btnWizardReviewEditorActorsToggle : els.btnWizardReviewEditorTopicsToggle;
  const menu = kind === "actors" ? els.wizardReviewEditorActorsMenu : els.wizardReviewEditorTopicsMenu;
  const optionsEl = kind === "actors" ? els.wizardReviewEditorActorsOptions : els.wizardReviewEditorTopicsOptions;
  const customBox = kind === "actors" ? els.wizardReviewEditorActorsCustomBox : els.wizardReviewEditorTopicsCustomBox;
  if (button) {
    button.textContent = selected.length ? selected.join(", ") : `Choose ${kind}`;
    button.setAttribute("aria-expanded", state.wizardReviewEditorPickerOpen === kind ? "true" : "false");
  }
  if (menu) {
    menu.hidden = state.wizardReviewEditorPickerOpen !== kind;
  }
  if (!optionsEl) {
    return;
  }
  const options = wizardReviewEditorOptions(kind);
  optionsEl.innerHTML = options.length
    ? options
        .map((value) => {
          const checked = selected.includes(value);
          return (
            `<label class="wizard-review-picker-option">` +
            `<span class="wizard-review-picker-label">` +
            `<input type="checkbox" data-review-editor-kind="${escapeHtml(kind)}" value="${escapeHtml(value)}"${checked ? ' checked="checked"' : ""} />` +
            `<span>${escapeHtml(value)}</span>` +
            `</span>` +
            `</label>`
          );
        })
        .join("")
    : '<div class="memory-empty">No saved options yet. Use Custom to add one.</div>';
  for (const input of optionsEl.querySelectorAll("input[data-review-editor-kind]")) {
    input.addEventListener("change", () => {
      const current = new Set(state.wizardReviewEditorSelections?.[kind] || []);
      if (input.checked) {
        current.add(String(input.value || "").trim());
      } else {
        current.delete(String(input.value || "").trim());
      }
      state.wizardReviewEditorSelections = {
        ...(state.wizardReviewEditorSelections || {}),
        [kind]: Array.from(current).filter(Boolean).sort((left, right) => left.localeCompare(right)),
      };
      renderWizardReviewEditorPicker(kind);
    });
  }
  if (customBox) {
    if (state.wizardReviewEditorPickerOpen !== kind) {
      customBox.hidden = true;
    }
  }
}

function toggleWizardReviewEditorPicker(kind) {
  state.wizardReviewEditorPickerOpen = state.wizardReviewEditorPickerOpen === kind ? null : kind;
  renderWizardReviewEditorPicker("actors");
  renderWizardReviewEditorPicker("topics");
}

function toggleWizardReviewEditorCustomBox(kind) {
  const box = kind === "actors" ? els.wizardReviewEditorActorsCustomBox : els.wizardReviewEditorTopicsCustomBox;
  if (!box) {
    return;
  }
  box.hidden = !box.hidden;
}

function addWizardReviewEditorCustomValue(kind) {
  const input = kind === "actors" ? els.wizardReviewEditorActorsCustomInput : els.wizardReviewEditorTopicsCustomInput;
  const box = kind === "actors" ? els.wizardReviewEditorActorsCustomBox : els.wizardReviewEditorTopicsCustomBox;
  const value = String(input?.value || "").trim();
  if (!value) {
    return;
  }
  const current = new Set(state.wizardReviewEditorSelections?.[kind] || []);
  current.add(value);
  state.wizardReviewEditorSelections = {
    ...(state.wizardReviewEditorSelections || {}),
    [kind]: Array.from(current).filter(Boolean).sort((left, right) => left.localeCompare(right)),
  };
  if (input) {
    input.value = "";
  }
  if (box) {
    box.hidden = true;
  }
  renderWizardReviewEditorPicker(kind);
}

function wizardReviewDraftEquals(left, right) {
  return (
    String(left?.title || "").trim() === String(right?.title || "").trim() &&
    String(left?.summary || "").trim() === String(right?.summary || "").trim() &&
    JSON.stringify(left?.actors || []) === JSON.stringify(right?.actors || []) &&
    JSON.stringify(left?.topic_tags || []) === JSON.stringify(right?.topic_tags || []) &&
    String(left?.truth_family_id || "").trim() === String(right?.truth_family_id || "").trim() &&
    String(left?.supersedes_episode_id || "").trim() === String(right?.supersedes_episode_id || "").trim()
  );
}

function openWizardReviewEditor(episodeId, returnFocusNode = null) {
  const card = wizardReviewCardById(episodeId);
  if (!card || !els.wizardReviewEditorDialog) {
    return;
  }
  state.wizardReviewEditorEpisodeId = String(episodeId || "").trim();
  state.wizardReviewEditorReturnFocus = returnFocusNode || document.activeElement;
  loadWizardReviewEditorCard(card);
  if (typeof els.wizardReviewEditorDialog.showModal === "function") {
    if (!els.wizardReviewEditorDialog.open) {
      els.wizardReviewEditorDialog.showModal();
    }
  } else {
    els.wizardReviewEditorDialog.setAttribute("open", "open");
  }
}

function closeWizardReviewEditor({ restoreFocus = true } = {}) {
  if (!els.wizardReviewEditorDialog) {
    return;
  }
  if (typeof els.wizardReviewEditorDialog.close === "function" && els.wizardReviewEditorDialog.open) {
    els.wizardReviewEditorDialog.close();
  } else {
    els.wizardReviewEditorDialog.removeAttribute("open");
  }
  state.wizardReviewEditorEpisodeId = "";
  state.wizardReviewEditorSelections = { actors: [], topics: [] };
  state.wizardReviewEditorPickerOpen = null;
  if (els.wizardReviewEditorActorsCustomBox) {
    els.wizardReviewEditorActorsCustomBox.hidden = true;
  }
  if (els.wizardReviewEditorTopicsCustomBox) {
    els.wizardReviewEditorTopicsCustomBox.hidden = true;
  }
  if (restoreFocus) {
    const target = state.wizardReviewEditorReturnFocus;
    if (target && typeof target.focus === "function") {
      target.focus();
    }
  }
  state.wizardReviewEditorReturnFocus = null;
}

async function requestCloseWizardReviewEditor({ restoreFocus = true } = {}) {
  if (wizardReviewEditorDirty()) {
    await saveWizardReviewEditorEditsIfNeeded();
  }
  closeWizardReviewEditor({ restoreFocus });
}

function loadWizardReviewEditorCard(card) {
  if (!card) {
    return;
  }
  const draft = wizardReviewEditorDraftFromCard(card);
  state.wizardReviewEditorSelections = {
    actors: [...draft.actors],
    topics: [...draft.topic_tags],
  };
  state.wizardReviewEditorPickerOpen = null;
  if (els.wizardReviewEditorActorsCustomBox) {
    els.wizardReviewEditorActorsCustomBox.hidden = true;
  }
  if (els.wizardReviewEditorTopicsCustomBox) {
    els.wizardReviewEditorTopicsCustomBox.hidden = true;
  }
  if (els.wizardReviewEditorEpisodeId) {
    els.wizardReviewEditorEpisodeId.textContent = String(card.episode_id || "episode");
  }
  if (els.wizardReviewEditorDecision) {
    els.wizardReviewEditorDecision.textContent = friendlyReviewDecision(card.review_decision || "pending");
  }
  if (els.wizardReviewEditorTitle) {
    els.wizardReviewEditorTitle.value = draft.title;
  }
  if (els.wizardReviewEditorSummary) {
    els.wizardReviewEditorSummary.value = draft.summary;
  }
  if (els.wizardReviewEditorTruthFamilyId) {
    els.wizardReviewEditorTruthFamilyId.value = draft.truth_family_id;
  }
  if (els.wizardReviewEditorSupersedesEpisodeId) {
    els.wizardReviewEditorSupersedesEpisodeId.value = draft.supersedes_episode_id;
  }
  renderWizardReviewEditorPicker("actors");
  renderWizardReviewEditorPicker("topics");
  updateWizardReviewEditorMeta();
  wizardResult(els.wizardReviewEditorResult, {
    tone: "info",
    title: "Quick Edit is focused on one card at a time.",
    detail: "Edit the fields you want. Moving left, right, or closing the editor saves changes automatically.",
    next: "Approve and Close keeps the card. Reject removes it from the published set.",
  });
}

function updateWizardReviewEditorMeta() {
  const episodeId = String(state.wizardReviewEditorEpisodeId || "").trim();
  const cards = state.wizardReviewCards || [];
  const page = Number(state.wizardReviewMeta?.page || 1);
  const totalPages = Math.max(1, Number(state.wizardReviewMeta?.totalPages || 1));
  const index = cards.findIndex((card) => String(card?.episode_id || "").trim() === episodeId);
  const position = index >= 0 ? index + 1 : 0;
  if (els.wizardReviewEditorMeta) {
    els.wizardReviewEditorMeta.textContent = index >= 0
      ? `Card ${position} of ${cards.length} on page ${page} of ${totalPages}`
      : "This card is no longer visible in the current filter.";
  }
  if (els.btnWizardReviewEditorPrev) {
    els.btnWizardReviewEditorPrev.disabled = page <= 1 && index <= 0;
  }
  if (els.btnWizardReviewEditorNext) {
    els.btnWizardReviewEditorNext.disabled = page >= totalPages && (index < 0 || index >= cards.length - 1);
  }
}

function wizardReviewEditorDirty() {
  const card = wizardReviewCardById(state.wizardReviewEditorEpisodeId);
  if (!card) {
    return false;
  }
  return !wizardReviewDraftEquals(wizardReviewEditorDraftFromCard(card), wizardReviewEditorDraftFromInputs());
}

async function saveWizardReviewEditorEditsIfNeeded() {
  const episodeId = String(state.wizardReviewEditorEpisodeId || "").trim();
  const card = wizardReviewCardById(episodeId);
  if (!episodeId || !card || !wizardReviewEditorDirty()) {
    return false;
  }
  await updateWizardReviewDecision(episodeId, "edited", wizardReviewEditorDraftFromInputs(), {
    setListFocus: false,
    resultElement: els.wizardReviewEditorResult,
  });
  const refreshedCard = wizardReviewCardById(episodeId);
  if (refreshedCard) {
    loadWizardReviewEditorCard(refreshedCard);
  }
  return true;
}

async function navigateWizardReviewEditor(direction) {
  const episodeId = String(state.wizardReviewEditorEpisodeId || "").trim();
  const currentIndex = state.wizardReviewCards.findIndex((card) => String(card?.episode_id || "").trim() === episodeId);
  if (currentIndex < 0) {
    closeWizardReviewEditor();
    return;
  }
  const statusFilter = String(els.wizardReviewStatus?.value || "all").trim().toLowerCase();
  const dirty = wizardReviewEditorDirty();
  const currentDecision = String(state.wizardReviewCards[currentIndex]?.review_decision || "pending").trim().toLowerCase();
  const nextDecision = dirty ? "edited" : currentDecision;
  const staysVisible = statusFilter === "all" || statusFilter === nextDecision;
  let targetIndex = currentIndex + (direction === "next" ? 1 : -1);
  if (dirty && !staysVisible && direction === "next") {
    targetIndex = currentIndex;
  }
  await saveWizardReviewEditorEditsIfNeeded();
  let page = Number(state.wizardReviewMeta?.page || 1);
  let cards = state.wizardReviewCards || [];
  if (direction === "next" && targetIndex >= cards.length && page < Number(state.wizardReviewMeta?.totalPages || 1)) {
    setWizardReviewPage(page + 1);
    await loadWizardReviewCards();
    page = Number(state.wizardReviewMeta?.page || page + 1);
    cards = state.wizardReviewCards || [];
    targetIndex = 0;
  } else if (direction === "prev" && targetIndex < 0 && page > 1) {
    setWizardReviewPage(page - 1);
    await loadWizardReviewCards();
    page = Number(state.wizardReviewMeta?.page || page - 1);
    cards = state.wizardReviewCards || [];
    targetIndex = Math.max(0, cards.length - 1);
  }
  const nextCard = cards[targetIndex] || null;
  if (!nextCard) {
    wizardResult(els.wizardReviewEditorResult, {
      tone: "info",
      title: "No more cards are available in this direction.",
      detail: "You reached the end of the current filtered review queue.",
      next: "Approve and Close this card, Reject it, or change the filter.",
    });
    updateWizardReviewEditorMeta();
    return;
  }
  state.wizardReviewEditorEpisodeId = String(nextCard.episode_id || "").trim();
  loadWizardReviewEditorCard(nextCard);
}

async function approveAndCloseWizardReviewEditor() {
  const episodeId = String(state.wizardReviewEditorEpisodeId || "").trim();
  if (!episodeId) {
    return;
  }
  const decision = wizardReviewEditorDirty() ? "edited" : "approved";
  const edits = decision === "edited" ? wizardReviewEditorDraftFromInputs() : {};
  await updateWizardReviewDecision(episodeId, decision, edits, {
    setListFocus: false,
    resultElement: els.wizardReviewEditorResult,
  });
  closeWizardReviewEditor();
}

async function rejectWizardReviewEditor() {
  const episodeId = String(state.wizardReviewEditorEpisodeId || "").trim();
  if (!episodeId) {
    return;
  }
  await updateWizardReviewDecision(episodeId, "rejected", {}, {
    setListFocus: false,
    resultElement: els.wizardReviewEditorResult,
  });
  closeWizardReviewEditor();
}

function focusWizardReviewTarget() {
  if (!state.wizardReviewShouldFocus || !els.wizardReviewList) {
    return;
  }
  const preferredId = String(state.wizardReviewFocusEpisodeId || "").trim();
  const candidates = [
    preferredId ? els.wizardReviewList.querySelector(`[data-episode-id="${CSS.escape(preferredId)}"]`) : null,
    els.wizardReviewList.querySelector(".wizard-review-item.review-focus"),
    els.wizardReviewList.querySelector(".wizard-review-item"),
  ].filter(Boolean);
  const target = candidates[0];
  if (target && typeof target.focus === "function") {
    target.focus();
  } else if (els.wizardReviewMeta && typeof els.wizardReviewMeta.focus === "function") {
    els.wizardReviewMeta.focus();
  }
  state.wizardReviewShouldFocus = false;
  state.wizardReviewFocusEpisodeId = "";
}

function setWizardReviewPage(page) {
  const totalPages = Math.max(1, Number(state.wizardReviewMeta?.totalPages || 1));
  state.wizardReviewMeta = {
    ...(state.wizardReviewMeta || {}),
    page: Math.min(totalPages, Math.max(1, Number(page || 1))),
  };
}

function resetWizardReviewPaging() {
  state.wizardReviewMeta = {
    ...(state.wizardReviewMeta || {}),
    page: 1,
  };
}

function reviewTextValue(card, reviewPayload, field) {
  if (Object.prototype.hasOwnProperty.call(reviewPayload, field)) {
    const override = String(reviewPayload[field] ?? "").trim();
    if (override) {
      return override;
    }
  }
  return String(card?.[field] ?? "").trim();
}

function reviewSummaryDisplayValue(title, summary) {
  const titleValue = String(title || "").trim();
  const summaryValue = String(summary || "").trim();
  if (!summaryValue) {
    return "";
  }
  if (!titleValue) {
    return summaryValue;
  }
  if (summaryValue.localeCompare(titleValue, undefined, { sensitivity: "accent" }) === 0) {
    return "";
  }
  if (summaryValue.toLocaleLowerCase().startsWith(titleValue.toLocaleLowerCase())) {
    const trimmed = summaryValue.slice(titleValue.length).replace(/^[\s|:;,.!?—–-]+/, "").trim();
    if (trimmed) {
      return trimmed;
    }
    return "";
  }
  return summaryValue;
}

function reviewListValue(card, reviewPayload, field) {
  if (Object.prototype.hasOwnProperty.call(reviewPayload, field) && Array.isArray(reviewPayload[field])) {
    return reviewPayload[field];
  }
  return Array.isArray(card?.[field]) ? card[field] : [];
}

function reviewCardMeta(card, reviewPayload = {}) {
  const actorRows = reviewListValue(card, reviewPayload, "actors");
  const topicRows = reviewListValue(card, reviewPayload, "topic_tags");
  const actors = actorRows.length ? `A: ${actorRows.slice(0, 3).join(", ")}` : "A: none";
  const topics = topicRows.length ? `T: ${topicRows.slice(0, 3).join(", ")}` : "T: none";
  return `${actors} | ${topics}`;
}

function friendlyReviewDecision(value) {
  const normalized = String(value || "pending").trim().toLowerCase();
  if (normalized === "approved") {
    return "Approved";
  }
  if (normalized === "edited") {
    return "Edited + approved";
  }
  if (normalized === "rejected") {
    return "Rejected";
  }
  return "Needs review";
}

function friendlyActivationStatus(value) {
  const normalized = String(value || "not_active").trim().toLowerCase();
  if (normalized === "running") {
    return "Running";
  }
  if (normalized === "draft_active") {
    return "Unsafe local draft";
  }
  if (normalized === "needs_attention") {
    return "Needs attention";
  }
  if (normalized === "stale_config") {
    return "Needs repair";
  }
  return "Not active";
}

function friendlyArtifactMode(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "published") {
    return "Frozen reviewed set";
  }
  if (normalized === "draft") {
    return "Unreviewed draft";
  }
  return normalized || "-";
}

function friendlyLockStatus(value) {
  const normalized = String(value || "missing").trim().toLowerCase();
  if (normalized === "owned") {
    return "owned by this runtime";
  }
  if (normalized === "foreign_live") {
    return "owned by another live runtime";
  }
  if (normalized === "stale") {
    return "stale lock";
  }
  if (normalized === "missing") {
    return "missing";
  }
  return normalized || "-";
}

function friendlyMcpStatus(value) {
  const normalized = String(value || "not_installed").trim().toLowerCase();
  if (normalized === "installed") {
    return "Installed";
  }
  if (normalized === "export_ready") {
    return "Bundle ready";
  }
  if (normalized === "export_only") {
    return "Export only";
  }
  if (normalized === "not_ready") {
    return "Not ready";
  }
  if (normalized === "stale_config") {
    return "Needs repair";
  }
  return "Not installed";
}

function friendlyMcpOwnership(value) {
  const normalized = String(value || "absent").trim().toLowerCase();
  if (normalized === "bundle") {
    return "export bundle only";
  }
  if (normalized === "owned" || normalized === "app_owned") {
    return "owned by this app";
  }
  if (normalized === "adopted") {
    return "adopted by this app";
  }
  if (normalized === "unknown") {
    return "belongs to something else or cannot be verified";
  }
  return "no existing entry";
}

function isManagedMcpTarget(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return normalized === "claude_code" || normalized === "claude_desktop";
}

function integrationTargetDisplay(target, mcpPayload = null) {
  const targets = (mcpPayload && mcpPayload.targets) || {};
  const row = targets ? targets[target] : null;
  return String((row && row.display) || target || "target").trim() || "target";
}

function friendlyMcpScope(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "user") {
    return "User";
  }
  if (normalized === "local") {
    return "Local";
  }
  if (normalized === "project") {
    return "Project";
  }
  return "-";
}

function friendlyMcpRole(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "operator") {
    return "Operator";
  }
  if (normalized === "admin") {
    return "Admin";
  }
  return "Viewer";
}

async function refreshWizardState(runId, options = {}) {
  const {
    includeReview = true,
    includeInputOptions = true,
    includeActivation = false,
    includeRemap = true,
    includeDraftCuration = true,
  } = options;
  const requestedRunId = state.hcrMode ? state.hcrRunId : runId;
  const query = requestedRunId ? `?run_id=${encodeURIComponent(requestedRunId)}` : "";
  const payload = await jsonFetch(`/api/wizard/state${query}`);
  if (state.hcrMode && (!payload.has_state || String(payload.current_run_id || "").trim() !== state.hcrRunId)) {
    throw new Error("Curation room could not load the requested run.");
  }
  state.wizardState = payload.state || null;
  state.wizardRunId = state.hcrMode ? state.hcrRunId : (payload.current_run_id || payload.latest_run_id || null);
  state.wizardLatestRunId = String(payload.latest_run_id || "");
  state.wizardResumeAvailable = Boolean(payload.resume_available);
  state.wizardReviewFacetMenuOpen = false;
  state.wizardReviewShouldFocus = false;
  state.wizardReviewFocusEpisodeId = "";
  renderWizardState();
  const tasks = [];
  if (includeReview) {
    tasks.push(loadWizardReviewCards());
  }
  if (includeInputOptions) {
    tasks.push(refreshWizardInputOptions(state.wizardRunId || undefined));
  }
  if (includeDraftCuration) {
    tasks.push(refreshWizardDraftCurationStatus(state.wizardRunId || undefined));
    tasks.push(loadWizardDraftCurationProposals(state.wizardRunId || undefined));
    tasks.push(refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined));
  }
  if (includeActivation) {
    tasks.push(refreshWizardActivationStatus(state.wizardRunId || undefined));
  }
  if (includeRemap) {
    tasks.push(refreshWizardRemapStatus(state.wizardRunId || undefined));
  }
  if (tasks.length) {
    await Promise.all(tasks);
  }
  await refreshHcrProgress();
}

async function refreshWizardReviewSummary(runId) {
  const requestSeq = state.wizardReviewSummaryRequestSeq + 1;
  state.wizardReviewSummaryRequestSeq = requestSeq;
  const requestedRunId = state.hcrMode ? state.hcrRunId : runId;
  const query = requestedRunId ? `?run_id=${encodeURIComponent(requestedRunId)}` : "";
  const payload = await jsonFetch(`/api/wizard/state${query}`);
  if (requestSeq !== state.wizardReviewSummaryRequestSeq) {
    return;
  }
  state.wizardState = payload.state || null;
  if (state.hcrMode && (!payload.has_state || String(payload.current_run_id || "").trim() !== state.hcrRunId)) {
    throw new Error("Curation room could not refresh the requested run.");
  }
  state.wizardRunId = state.hcrMode ? state.hcrRunId : (payload.current_run_id || payload.latest_run_id || state.wizardRunId || null);
  state.wizardLatestRunId = String(payload.latest_run_id || state.wizardLatestRunId || "");
  state.wizardResumeAvailable = Boolean(payload.resume_available || state.wizardLatestRunId);
  renderWizardState();
  renderWizardReviewMeta();
  await refreshHcrProgress();
}

async function startWizard(mode) {
  const payload = await jsonFetch("/api/wizard/start", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
  state.wizardState = payload.state || null;
  state.wizardRunId = payload.run_id || null;
  state.wizardReviewFacetMenuOpen = false;
  state.wizardReviewEditorEpisodeId = "";
  state.wizardReviewFilters = { actors: [], topics: [] };
  state.wizardReviewEditorSelections = { actors: [], topics: [] };
  state.wizardReviewEditorPickerOpen = null;
  state.wizardDraftCurationStatus = null;
  state.wizardDraftCurationAllCards = [];
  state.wizardDraftCurationCards = [];
  state.wizardDraftCurationMeta = { total: 0, filteredTotal: 0, page: 1, pageSize: 6, totalPages: 1, statusFilter: "pending", search: "" };
  state.wizardDraftCurationSelectedEpisodeId = "";
  state.wizardDraftCurationDetail = null;
  state.wizardDraftCurationMcp = null;
  state.wizardImportPending = false;
  state.wizardArchiveTargetMode = "new";
  resetWizardSourceSelectionState();
  resetWizardReviewPaging();
  renderWizardState();
  wizardResult(els.wizardImportResult, {
    tone: "info",
    title: mode === "new" ? "Fresh setup run started." : "Previous setup run resumed.",
    detail: mode === "new"
      ? "You are starting from the top of the wizard."
      : "The wizard reopened the last saved run so you can keep going without losing progress.",
    next: "Follow the highlighted step.",
    meta: `run=${state.wizardRunId || "-"}`,
  });
  await Promise.all([
    loadWizardReviewCards(),
    refreshWizardDraftCurationStatus(state.wizardRunId || undefined),
    loadWizardDraftCurationProposals(state.wizardRunId || undefined),
    refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined),
    refreshWizardInputOptions(state.wizardRunId || undefined),
    refreshWizardRemapStatus(state.wizardRunId || undefined),
  ]);
}

async function refreshWizardInputOptions(runId) {
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  const payload = await jsonFetch(`/api/wizard/input/options${query}`);
  state.wizardInputOptions = payload;
  renderWizardInputOptions();
}

async function uploadWizardArchive(file) {
  const files = Array.isArray(file) ? file : file ? [file] : [];
  if (!files.length) {
    return;
  }
  const encodedFiles = await Promise.all(
    files.map(async (item) => {
      const arrayBuffer = await item.arrayBuffer();
      return {
        file_name: item.name,
        relative_path: String(item.webkitRelativePath || item.name || "").trim() || item.name,
        content_base64: arrayBufferToBase64(arrayBuffer),
      };
    })
  );
  const payload = await jsonFetch("/api/wizard/input/upload", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      files: encodedFiles,
    }),
  });
  state.wizardState = {
    ...(state.wizardState || {}),
    selected_input: payload.classification || {},
    selected_input_sources: Array.isArray(payload.source_paths) ? payload.source_paths : (state.wizardState?.selected_input_sources || []),
  };
  renderWizardState();
  wizardResult(
    els.wizardImportResult,
    {
      tone: (payload.classification?.issues || []).length ? "warn" : "info",
      title: payload.file_count > 1 ? "Source files staged locally." : "Source file staged locally.",
      detail: payload.file_count > 1
        ? "MNO can see the files you picked as one source bundle, but the step is not complete yet."
        : "MNO can see the file you picked, but the step is not complete yet.",
      next: `Wait for File Checked to turn green, then click ${wizardPrimaryImportLabel()}.`,
      meta: `path=${payload.classification?.path || files[0]?.name || "-"} | files=${payload.file_count || files.length} | ${wizardIssueSummary(payload.classification?.issues || [])}`,
    }
  );
  await refreshWizardInputOptions(state.wizardRunId || undefined);
  await validateWizardImport();
  if (els.wizardArchiveFile) {
    els.wizardArchiveFile.value = "";
  }
  if (els.wizardArchiveFolder) {
    els.wizardArchiveFolder.value = "";
  }
}

async function validateWizardImport() {
  const inputPayload = currentWizardInputPayload();
  const payload = await jsonFetch("/api/wizard/import/validate", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      ...inputPayload,
    }),
  });
  const issueSummary = wizardIssueSummary(payload.issues || []);
  wizardResult(
    els.wizardImportResult,
    {
      tone: payload.status === "safe" ? "ok" : "warn",
      title: payload.status === "safe" ? "The selected input looks valid." : "The selected input needs attention.",
      detail: payload.status === "safe"
        ? "Validation only checks the file or store. It does not finish Import by itself."
        : "MNO found a problem that should be fixed before import continues.",
      next: payload.status === "safe" ? `If File Checked is green, click ${wizardPrimaryImportLabel()}.` : "Pick a safer file or fix the listed issue, then use Check File again.",
      meta: `kind=${payload.kind || "unknown"} | status=${payload.status} | ${issueSummary}`,
    }
  );
  await refreshWizardState(state.wizardRunId || undefined);
}

async function runWizardImport() {
  if (state.wizardImportPending) {
    return;
  }
  const inputPayload = currentWizardInputPayload();
  if (state.wizardInputMode === "archive" && state.wizardArchiveTargetMode === "existing" && !String(inputPayload.store_path || "").trim()) {
    wizardResult(els.wizardImportResult, {
      tone: "warn",
      title: "Pick the existing store first.",
      detail: "Add To Existing Store needs a real destination store.",
      next: "Choose one store under Import destination, then try again.",
    });
    return;
  }
  state.wizardImportPending = true;
  renderWizardState();
  wizardResult(els.wizardImportResult, {
    tone: "info",
    title: state.wizardInputMode === "store"
      ? "Binding the selected store."
      : state.wizardArchiveTargetMode === "existing"
        ? "Adding the source into the existing store."
        : "Creating the MNO store.",
    detail: state.wizardInputMode === "store"
      ? "MNO is binding the existing store into this wizard run."
      : state.wizardArchiveTargetMode === "existing"
        ? "MNO is importing the selected source into the existing store you picked."
        : "MNO is importing the selected source into a draft memory store for this wizard run.",
    next: "Wait for Import to finish.",
  });
  try {
    const payload = await jsonFetch("/api/wizard/import/run", {
      method: "POST",
      body: JSON.stringify({
        run_id: state.wizardRunId || undefined,
        ...inputPayload,
      }),
    });
    wizardResult(
      els.wizardImportResult,
      {
        tone: "ok",
        title: state.wizardInputMode === "store"
          ? "Existing MNO store is ready to use."
          : state.wizardArchiveTargetMode === "existing"
            ? "Raw source added into the existing store."
            : "MNO store created successfully.",
        detail: state.wizardInputMode === "store"
          ? "Import is complete because you selected a valid existing store."
          : state.wizardArchiveTargetMode === "existing"
            ? "The selected source was imported into the existing store you picked, and the next step is ready."
            : "The selected source has been converted into a real MNO store and the next step is ready.",
        next: "Move to Build Episodes.",
        meta: `kind=${payload.input_kind || "-"} | store=${payload.store_path || "-"} | report=${payload.reports?.json || "-"}`,
      }
    );
    await refreshWizardState(state.wizardRunId || undefined);
    await refreshMemory();
  } finally {
    state.wizardImportPending = false;
    renderWizardState();
  }
}

function openWizardBuildPolicyDialog() {
  const dialog = els.wizardBuildPolicyDialog;
  if (!dialog) {
    return;
  }
  if (typeof dialog.showModal === "function") {
    if (!dialog.open) {
      dialog.showModal();
    }
    return;
  }
  dialog.setAttribute("open", "open");
}

function closeWizardBuildPolicyDialog() {
  const dialog = els.wizardBuildPolicyDialog;
  if (!dialog) {
    return;
  }
  if (typeof dialog.close === "function" && dialog.open) {
    dialog.close();
    return;
  }
  dialog.removeAttribute("open");
}

function openMemoryPreferenceDialog() {
  const dialog = els.memoryPreferenceDialog;
  if (!dialog) {
    return;
  }
  if (typeof dialog.showModal === "function") {
    if (!dialog.open) {
      dialog.showModal();
    }
    return;
  }
  dialog.setAttribute("open", "open");
}

function closeMemoryPreferenceDialog() {
  const dialog = els.memoryPreferenceDialog;
  if (!dialog) {
    return;
  }
  if (typeof dialog.close === "function" && dialog.open) {
    dialog.close();
    return;
  }
  dialog.removeAttribute("open");
}

function openInlineDialog(dialogId) {
  const dialog = document.getElementById(dialogId);
  if (!dialog) {
    return;
  }
  if (typeof dialog.showModal === "function") {
    if (!dialog.open) {
      dialog.showModal();
    }
    return;
  }
  dialog.setAttribute("open", "open");
}

function closeInlineDialog(dialog) {
  if (!dialog) {
    return;
  }
  if (typeof dialog.close === "function" && dialog.open) {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
  const returnFocus = state.wizardInlineDialogReturnFocus;
  if (returnFocus && typeof returnFocus.focus === "function") {
    returnFocus.focus();
  }
  state.wizardInlineDialogReturnFocus = null;
}

function bindInlineDialogs() {
  for (const trigger of document.querySelectorAll("[data-dialog-open]")) {
    trigger.addEventListener("click", () => {
      const dialogId = String(trigger.getAttribute("data-dialog-open") || "").trim();
      if (dialogId) {
        state.wizardInlineDialogReturnFocus = trigger;
        openInlineDialog(dialogId);
      }
    });
  }
  for (const button of document.querySelectorAll("[data-dialog-close]")) {
    button.addEventListener("click", () => {
      const dialogId = String(button.getAttribute("data-dialog-close") || "").trim();
      if (!dialogId) {
        return;
      }
      closeInlineDialog(document.getElementById(dialogId));
    });
  }
  for (const dialog of document.querySelectorAll("dialog[data-inline-dialog]")) {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        closeInlineDialog(dialog);
      }
    });
  }
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
    {
      tone: "ok",
      title: `${wizardCountLabel(counts.promoted_count || 0, "draft card")} ready for review.`,
      detail: Number(counts.promoted_count || 0) > 24
        ? "This draft is fairly large. Expect more cleanup in Review."
        : Number(counts.promoted_count || 0) <= 2
          ? "This draft is very small. If it feels too thin, try a less strict build style."
          : "The draft looks like a normal review pass.",
      next: "Move to Review and decide what survives, or optionally let an assistant or agent help curate the draft first.",
      meta: `build_style=${policyPreset} | candidate=${counts.candidate_count || 0} | rejected=${counts.rejected_count || 0}`,
    }
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
  const requestSeq = state.wizardReviewRequestSeq + 1;
  state.wizardReviewRequestSeq = requestSeq;
  const runId = state.wizardRunId || "";
  const search = (els.wizardReviewSearch?.value || "").trim();
  const status = (els.wizardReviewStatus?.value || "all").trim();
  if (!runId) {
    state.wizardReviewCards = [];
    state.wizardReviewFacets = { actors: [], topics: [] };
    state.wizardReviewMeta = { total: 0, filteredTotal: 0, page: 1, pageSize: Number(els.wizardReviewPageSize?.value || 6), totalPages: 1 };
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
  for (const actor of state.wizardReviewFilters?.actors || []) {
    params.append("actors", actor);
  }
  for (const topic of state.wizardReviewFilters?.topics || []) {
    params.append("topics", topic);
  }
  params.set("page", String(Math.max(1, Number(state.wizardReviewMeta?.page || 1))));
  params.set("page_size", String(Math.max(1, Number(els.wizardReviewPageSize?.value || state.wizardReviewMeta?.pageSize || 6))));
  const payload = await jsonFetch(`/api/wizard/review/cards?${params.toString()}`);
  if (requestSeq !== state.wizardReviewRequestSeq) {
    return;
  }
  state.wizardReviewCards = payload.cards || [];
  state.wizardReviewFacets = payload.filter_facets || { actors: [], topics: [] };
  state.wizardReviewFilters = {
    actors: Array.isArray(payload.active_filters?.actors) ? payload.active_filters.actors : (state.wizardReviewFilters?.actors || []),
    topics: Array.isArray(payload.active_filters?.topics) ? payload.active_filters.topics : (state.wizardReviewFilters?.topics || []),
  };
  state.wizardReviewMeta = {
    total: Number(payload.total || 0),
    filteredTotal: Number(payload.filtered_total || payload.total || 0),
    page: Number(payload.page || 1),
    pageSize: Number(payload.page_size || els.wizardReviewPageSize?.value || 6),
    totalPages: Number(payload.total_pages || 1),
  };
  if (els.wizardReviewPageSize) {
    els.wizardReviewPageSize.value = String(state.wizardReviewMeta.pageSize || 6);
  }
  renderWizardReviewList();
  if (state.wizardReviewEditorEpisodeId) {
    const currentCard = wizardReviewCardById(state.wizardReviewEditorEpisodeId);
    if (currentCard) {
      loadWizardReviewEditorCard(currentCard);
    } else {
      updateWizardReviewEditorMeta();
    }
  }
}

async function updateWizardReviewDecision(episodeId, decision, edits = {}, options = {}) {
  const resultElement = options.resultElement || els.wizardReviewResult;
  const setListFocus = options.setListFocus !== false;
  if (state.wizardReviewPendingWrites?.[episodeId]) {
    return;
  }
  state.wizardReviewPendingWrites = {
    ...(state.wizardReviewPendingWrites || {}),
    [episodeId]: true,
  };
  state.wizardReviewShouldFocus = setListFocus;
  state.wizardReviewFocusEpisodeId = setListFocus ? episodeId : "";
  renderWizardReviewList();
  try {
    await jsonFetch("/api/wizard/review/update", {
      method: "POST",
      body: JSON.stringify({
        run_id: state.wizardRunId || undefined,
        episode_id: episodeId,
        decision,
        ...edits,
      }),
    });
    wizardResult(resultElement, {
      tone: decision === "rejected" ? "warn" : "ok",
      title: `${episodeId} updated.`,
      detail: `${friendlyReviewDecision(decision)} is now saved for this card.`,
      next: "Keep reviewing until every card has a decision.",
    });
    await Promise.all([loadWizardReviewCards(), refreshWizardReviewSummary(state.wizardRunId || undefined)]);
  } finally {
    const nextWrites = { ...(state.wizardReviewPendingWrites || {}) };
    delete nextWrites[episodeId];
    state.wizardReviewPendingWrites = nextWrites;
    renderWizardReviewList();
  }
}

async function approveWizardReviewPage() {
  const pendingCards = state.wizardReviewCards.filter(
    (card) => String(card.review_decision || "pending") === "pending"
  );
  state.wizardReviewShouldFocus = true;
  state.wizardReviewFocusEpisodeId = "";
  if (!pendingCards.length) {
    wizardResult(els.wizardReviewResult, {
      title: "No pending cards are left on this page.",
      detail: "Everything visible here already has a decision.",
      next: "Move to another page or go to Publish if review is complete.",
      tone: "info",
    });
    return;
  }
  wizardResult(els.wizardReviewResult, {
    title: `Approving ${wizardCountLabel(pendingCards.length, "pending card")} on this page...`,
    detail: "MNO is applying the same approve decision to the cards that are still pending on this page.",
    next: "Wait for the page to refresh.",
    tone: "info",
  });
  let approved = 0;
  for (const card of pendingCards) {
    const episodeId = String(card.episode_id || card.id || "");
    if (!episodeId) continue;
    try {
      await jsonFetch("/api/wizard/review/update", {
        method: "POST",
        body: JSON.stringify({
          run_id: state.wizardRunId || undefined,
          episode_id: episodeId,
          decision: "approved",
        }),
      });
      approved++;
    } catch (error) {
      wizardResult(els.wizardReviewResult, {
        tone: "error",
        title: `Review update failed for ${episodeId}.`,
        detail: error.message,
        next: "Fix the error, then try the update again.",
      });
      break;
    }
  }
  wizardResult(els.wizardReviewResult, {
    tone: "ok",
    title: `Approved ${approved} of ${pendingCards.length} cards on this page.`,
    detail: approved === pendingCards.length ? "Every pending card on this page now has a decision." : "Some cards were approved before the run stopped.",
    next: "Keep reviewing until every card has a decision.",
  });
  await Promise.all([loadWizardReviewCards(), refreshWizardReviewSummary(state.wizardRunId || undefined)]);
}

async function releaseWizardDraftCurationLease(forceRelease = true) {
  const lease = state.wizardDraftCurationStatus?.draft_curation?.lease || {};
  const ownerId = String(lease.owner_id || "runtime_ui").trim() || "runtime_ui";
  const sessionId = String(lease.session_id || "runtime_ui").trim() || "runtime_ui";
  const payload = await jsonFetch("/api/wizard/draft-curation/session/release", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      owner_id: ownerId,
      session_id: sessionId,
      force_release: forceRelease,
      note: "Released from runtime UI.",
    }),
  });
  state.wizardDraftCurationStatus = {
    ...(state.wizardDraftCurationStatus || {}),
    draft_curation: payload.draft_curation || {},
  };
  renderWizardDraftCurationStatus();
  renderWizardDraftCurationFeedback({
    tone: "ok",
    title: "Draft curation lease released.",
    detail: "The assistant or agent can reconnect cleanly if you want to restart the optional lane later.",
    next: "Refresh Suggestions if you expect the queue to change.",
  });
}

async function approveWizardReviewAll() {
  if (!window.confirm("Approve ALL pending cards across every page? This cannot be undone.")) {
    return;
  }
  wizardResult(els.wizardReviewResult, {
    title: "Approving all pending cards...",
    detail: "This bulk action touches every page in the current draft.",
    next: "Wait for the review summary to refresh.",
    tone: "warn",
  });
  state.wizardReviewShouldFocus = true;
  state.wizardReviewFocusEpisodeId = "";
  let approved = 0;
  const pageSize = 48;
  while (true) {
    try {
      const payload = await jsonFetch(
        `/api/wizard/review/cards?run_id=${encodeURIComponent(state.wizardRunId || "")}&status=pending&page=1&page_size=${pageSize}`
      );
      const cards = Array.isArray(payload.cards) ? payload.cards : [];
      if (!cards.length) {
        break;
      }
      for (const card of cards) {
        const episodeId = String(card.episode_id || card.id || "");
        if (!episodeId) continue;
        try {
          await jsonFetch("/api/wizard/review/update", {
            method: "POST",
            body: JSON.stringify({
              run_id: state.wizardRunId || undefined,
              episode_id: episodeId,
              decision: "approved",
            }),
          });
          approved++;
        } catch (error) {
          wizardResult(els.wizardReviewResult, {
            tone: "error",
            title: `Bulk approve failed on ${episodeId}.`,
            detail: error.message,
            next: "Fix the error, then run the bulk action again if you still want it.",
          });
          throw error;
        }
      }
      wizardResult(els.wizardReviewResult, {
        title: `Approved ${approved} cards so far...`,
        detail: "MNO is still working through the remaining pending cards.",
        next: "Wait for the bulk action to finish.",
        tone: "info",
      });
    } catch (error) {
      wizardResult(els.wizardReviewResult, {
        tone: "error",
        title: "Bulk approve failed.",
        detail: error.message,
        next: "Fix the error, then try again if you still want the bulk action.",
      });
      break;
    }
  }
  wizardResult(els.wizardReviewResult, {
    tone: "ok",
    title: `Bulk approve finished: ${approved} cards approved.`,
    detail: "Every pending card the bulk action touched now has a decision.",
    next: "If Review is green, move to Publish.",
  });
  await Promise.all([loadWizardReviewCards(), refreshWizardReviewSummary(state.wizardRunId || undefined)]);
}

function scheduleWizardReviewSearch() {
  if (wizardReviewSearchTimer) {
    window.clearTimeout(wizardReviewSearchTimer);
  }
  wizardReviewSearchTimer = window.setTimeout(() => {
    wizardReviewSearchTimer = null;
    state.wizardReviewShouldFocus = true;
    state.wizardReviewFocusEpisodeId = "";
    resetWizardReviewPaging();
    loadWizardReviewCards().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  }, 250);
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
    els.wizardPublishResult,
    {
      tone: "ok",
      title: "Reviewed memory set published.",
      detail: "MNO created the frozen reviewed set the runtime should actually use.",
      next: "Run Verify before activation.",
      meta: `version=${payload.version_id || "-"} | episodes=${payload.episode_count || 0} | path=${payload.reviewed_path || "-"}`,
    }
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
    els.wizardPublishResult,
    {
      tone: "warn",
      title: "Last good published copy restored.",
      detail: "The recovery copy is back, but restore does not count as fresh success by itself.",
      next: "Run Verify again before activation.",
      meta: `store=${pointers.store_path || "-"} | episodes=${pointers.episodes_path || "-"} | remaining_snapshots=${payload.remaining_snapshots || 0}`,
    }
  );
  await refreshWizardState(state.wizardRunId || undefined);
  await Promise.all([refreshEpisodes(), refreshMemory()]);
}

function renderWizardVerifyResult(payload) {
  const checks = Array.isArray(payload?.checks) ? payload.checks : [];
  const status = String(payload?.status || "unknown");
  const failed = checks.filter((item) => String(item?.status || "") === "fail");
  const warned = checks.filter((item) => String(item?.status || "") === "warn");
  const publishedReady = Boolean(String((state.wizardState?.published_set || {}).episodes_path || "").trim());
  if (!status || status === "unknown" || status === "Unknown") {
    wizardResult(els.wizardVerifyResult, {
      tone: publishedReady ? "warn" : "info",
      title: publishedReady ? "Verification is stale and must run again." : "Verification has not run yet.",
      detail: publishedReady
        ? "The current published memory set exists, but MNO does not have a current safety verdict for it yet."
        : "This step checks whether the store, published set, and readiness state still line up.",
      next: "Click Check Readiness.",
    });
  } else if (status === "Safe") {
    wizardResult(els.wizardVerifyResult, {
      tone: "ok",
      title: "Safe. Normal activation can continue.",
      detail: checks.length
        ? `MNO checked ${wizardCountLabel(checks.length, "readiness check")} and found no blockers.`
        : "The reviewed set and store look aligned for normal activation.",
      next: "Move to Activate and start the local runtime.",
      meta: `checks=${checks.length} | checked_at=${payload?.checked_at || "-"}`,
    });
  } else if (status === "Needs attention") {
    wizardResult(els.wizardVerifyResult, {
      tone: "warn",
      title: "Needs attention before you trust this build.",
      detail: warned.length
        ? warned.map((item) => String(item.detail || "").trim()).filter(Boolean).join(" | ")
        : "Something should be checked before you trust this memory system.",
      next: "Use the recovery links or remap/reset actions below, then verify again.",
      meta: `checks=${checks.length} | warnings=${warned.length} | checked_at=${payload?.checked_at || "-"}`,
    });
  } else {
    wizardResult(els.wizardVerifyResult, {
      tone: "error",
      title: "Blocked. Activation is stopped.",
      detail: failed.length
        ? failed.map((item) => String(item.detail || "").trim()).filter(Boolean).join(" | ")
        : "A required artifact is missing, stale, or mismatched.",
      next: "Fix the problem below, then run Verify again.",
      meta: `checks=${checks.length} | failures=${failed.length} | checked_at=${payload?.checked_at || "-"}`,
    });
  }
  if (els.wizardVerifyLinks) {
    if (Array.isArray(payload?.actionable_links) && payload.actionable_links.length) {
      els.wizardVerifyLinks.classList.remove("wizard-result-error");
      wizardResult(els.wizardVerifyLinks, {
        tone: "info",
        html:
          `<div class="wizard-result-shell">` +
          `<div class="wizard-result-title">Helpful repair links</div>` +
          `<div class="wizard-result-detail">Use these links if you want to inspect the failing or stale part directly.</div>` +
          `<div>${wizardLinksHtml(payload.actionable_links)}</div>` +
          `</div>`,
      });
    } else {
      wizardResult(els.wizardVerifyLinks, {
        tone: "info",
        title: "No direct repair links are needed right now.",
        detail: "If Verify still looks wrong, use the remap/reset controls below or go back to the earlier step.",
      });
    }
  }
}

function renderWizardRemapStatus(payload) {
  const remap = payload?.remap || payload || {};
  state.wizardRemap = remap;
  if (!els.wizardRemapStatus) {
    return;
  }
  const rows = Array.isArray(remap.missing_artifacts) ? remap.missing_artifacts : [];
  if (!rows.length) {
    wizardResult(els.wizardRemapStatus, {
      tone: "info",
      title: "No missing artifacts need remapping right now.",
      detail: "If Verify still says something is wrong, use the repair links above or go back to the earlier step that created the stale file.",
    });
    return;
  }
  els.wizardRemapStatus.classList.remove("wizard-result-info", "wizard-result-ok", "wizard-result-warn", "wizard-result-error");
  els.wizardRemapStatus.classList.add("wizard-result-warn");
  els.wizardRemapStatus.innerHTML =
    `<div class="wizard-result-shell">` +
    `<div class="wizard-result-title">Repair this before activation.</div>` +
    `<div class="wizard-result-detail">A file the wizard expects is missing or stale. Pick the replacement file, or go back to the right step and rebuild it cleanly.</div>` +
    rows
    .map((row) => {
      const target = String(row.target || "");
      const resetStage = String(row.reset_stage || "import");
      return (
        `<article class="wizard-remap-item">` +
        `<header><strong>${escapeHtml(String(row.label || target || "Missing artifact"))}</strong><span>${escapeHtml(stageLabel(resetStage))}</span></header>` +
        `<div>missing file: ${escapeHtml(String(row.missing_path || "-"))}</div>` +
        `<div>${escapeHtml(String(row.recommendation || "Pick the missing file again or reset the stale state."))}</div>` +
        `<div class="wizard-inline-actions wizard-inline-actions-tight">` +
        `<button type="button" class="btn ghost wizard-remap-action" data-target="${escapeHtml(target)}" data-action="pick">Pick Replacement File</button>` +
        `<button type="button" class="btn ghost wizard-remap-action" data-target="${escapeHtml(target)}" data-action="reset" data-stage="${escapeHtml(resetStage)}">Go Back To ${escapeHtml(stageLabel(resetStage))}</button>` +
        `</div>` +
        `</article>`
      );
    })
    .join("") +
    `</div>`;
  for (const button of els.wizardRemapStatus.querySelectorAll(".wizard-remap-action")) {
    button.addEventListener("click", () => {
      const action = button.getAttribute("data-action") || "pick";
      const target = button.getAttribute("data-target") || "";
      if (action === "pick") {
        state.wizardPendingRemapTarget = target;
        els.wizardRemapFile?.click();
      } else {
        const stage = button.getAttribute("data-stage") || "import";
        resetWizardState(stage).catch((error) => wizardResult(els.wizardVerifyResult, error.message, true));
      }
    });
  }
}

async function runWizardVerify() {
  const payload = await jsonFetch("/api/wizard/verify/run", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
    }),
  });
  renderWizardVerifyResult(payload);
  await refreshWizardRemapStatus(state.wizardRunId || undefined);
  await refreshWizardState(state.wizardRunId || undefined);
}

function renderWizardMcpTargets(container, { mcp = {}, selectedScope = "user", resultNode = null, onInstall, onRemove, onExport, emptyMessage = "No MCP targets detected.", disabled = false }) {
  if (!container) {
    return;
  }
  const compact = container.classList.contains("wizard-draft-curation-mcp-targets");
  const targets = mcp.targets || {};
  const rows = Object.entries(targets)
    .map(([targetKey, target]) => {
      const status = String(target.status || "not_installed");
      const ownership = String(target.ownership || "absent");
      const scope = String(target.scope || (targetKey === "claude_code" ? selectedScope : "")).trim();
      const display = String(target.display || targetKey);
      const supportedActions = Array.isArray(target.supported_actions) ? target.supported_actions.map((item) => String(item || "").trim().toLowerCase()).filter(Boolean) : [];
      const issues = Array.isArray(target.issues) ? target.issues.join(" | ") : "";
      const summary = trimDisplay(issues || String(target.summary || "This target is ready for assistant/agent / MCP setup."), compact ? 120 : 220);
      const configPath = String(target.config_path || "-");
      const configPathDisplay = compact ? compactPathDisplay(configPath, 42) : configPath;
      const actionButtons = [];
      const disabledAttr = disabled ? ' disabled aria-disabled="true"' : "";
      if (supportedActions.includes("export") && supportedActions.length === 1) {
        actionButtons.push(`<button type="button" class="btn ghost wizard-mcp-action" data-target="${escapeHtml(targetKey)}" data-action="export"${disabledAttr}>Export</button>`);
      } else if (ownership === "unknown") {
        actionButtons.push(`<button type="button" class="btn ghost wizard-mcp-action" data-target="${escapeHtml(targetKey)}" data-action="adopt"${disabledAttr}>Adopt</button>`);
        actionButtons.push(`<button type="button" class="btn ghost wizard-mcp-action" data-target="${escapeHtml(targetKey)}" data-action="overwrite"${disabledAttr}>Overwrite</button>`);
      } else if (status === "installed" || status === "stale_config") {
        actionButtons.push(`<button type="button" class="btn ghost wizard-mcp-action" data-target="${escapeHtml(targetKey)}" data-action="remove"${disabledAttr}>Remove</button>`);
        if (status !== "installed") {
          actionButtons.push(`<button type="button" class="btn ghost wizard-mcp-action" data-target="${escapeHtml(targetKey)}" data-action="overwrite"${disabledAttr}>Repair</button>`);
        }
        if (supportedActions.includes("export")) {
          actionButtons.push(`<button type="button" class="btn ghost wizard-mcp-action" data-target="${escapeHtml(targetKey)}" data-action="export"${disabledAttr}>Export</button>`);
        }
      } else {
        actionButtons.push(`<button type="button" class="btn ghost wizard-mcp-action" data-target="${escapeHtml(targetKey)}" data-action="install"${disabledAttr}>Install</button>`);
        if (supportedActions.includes("export")) {
          actionButtons.push(`<button type="button" class="btn ghost wizard-mcp-action" data-target="${escapeHtml(targetKey)}" data-action="export"${disabledAttr}>Export</button>`);
        }
      }
      return (
        `<article class="wizard-activation-card ${compact ? "wizard-activation-card-compact " : ""}${escapeHtml(status)}">` +
        `<header><strong>${escapeHtml(display)}</strong><span>${escapeHtml(friendlyMcpStatus(status))}</span></header>` +
        `<div class="wizard-activation-summary">${escapeHtml(summary)}</div>` +
        `<div class="wizard-activation-meta-row"><span>ownership=${escapeHtml(friendlyMcpOwnership(ownership))}</span><span>scope=${escapeHtml(friendlyMcpScope(scope))}</span></div>` +
        `<div class="wizard-result-meta" title="${escapeHtml(configPath)}"><strong>Config:</strong> ${escapeHtml(configPathDisplay)}</div>` +
        `<div class="wizard-inline-actions wizard-inline-actions-tight">${actionButtons.join("")}</div>` +
        `</article>`
      );
    })
    .join("");
  container.innerHTML = rows || `<div class="wizard-card-result">${escapeHtml(emptyMessage)}</div>`;
  if (disabled) {
    return;
  }
  for (const button of container.querySelectorAll(".wizard-mcp-action")) {
    button.addEventListener("click", () => {
      const target = button.getAttribute("data-target") || "claude_code";
      const action = button.getAttribute("data-action") || "install";
      if (action === "export") {
        onExport(target).catch((error) => wizardResult(resultNode, error.message, true));
      } else if (action === "remove") {
        onRemove(target).catch((error) => wizardResult(resultNode, error.message, true));
      } else if (action === "adopt") {
        onInstall(target, "adopt").catch((error) => wizardResult(resultNode, error.message, true));
      } else {
        onInstall(target, action === "overwrite" ? "overwrite" : "").catch((error) => wizardResult(resultNode, error.message, true));
      }
    });
  }
}

function renderWizardActivation(payload) {
  const activation = payload?.activation || payload || {};
  state.wizardActivation = activation;
  const direct = activation.direct || {};
  const mcp = activation.mcp || {};
  const preview = mcp.preview || {};
  const selectedTarget = String(preview.target || state.wizardMcpTarget || "claude_code").trim().toLowerCase() || "claude_code";
  const selectedScope = String(preview.claude_code_scope || state.wizardMcpScope || "user").trim().toLowerCase() || "user";
  const selectedRole = String(preview.default_role || state.wizardMcpRole || "viewer").trim().toLowerCase() || "viewer";
  const selectedMutations = Object.prototype.hasOwnProperty.call(preview, "mutations_enabled")
    ? Boolean(preview.mutations_enabled)
    : Boolean(state.wizardMcpMutations);
  state.wizardMcpScope = selectedScope;
  state.wizardMcpRole = selectedRole;
  state.wizardMcpMutations = selectedMutations;
  state.wizardMcpTarget = selectedTarget;
  const directLock = direct.lock || {};
  const draftOverride = activation.draft_override || {};
  if (els.wizardMcpTarget) {
    els.wizardMcpTarget.value = selectedTarget;
  }
  if (els.wizardMcpScope) {
    els.wizardMcpScope.value = selectedScope;
    els.wizardMcpScope.disabled = selectedTarget !== "claude_code";
  }
  if (els.wizardMcpRole) {
    els.wizardMcpRole.value = selectedRole;
  }
  if (els.wizardMcpMutations) {
    els.wizardMcpMutations.checked = selectedMutations;
  }
  if (els.wizardActivationStatus) {
    const issues = Array.isArray(direct.issues) ? direct.issues : [];
    const lockStatus = String(directLock.status || "missing");
    const directLabel = friendlyActivationStatus(String(direct.status || "not_active"));
    const repairButton = directLock.cleanup_allowed
      ? `<div class="wizard-inline-actions wizard-inline-actions-tight wizard-activation-inline-actions"><button type="button" class="btn ghost wizard-direct-repair-inline">Repair this now</button></div>`
      : "";
    els.wizardActivationStatus.innerHTML =
      `<article class="wizard-activation-card ${escapeHtml(String(direct.status || "not_active"))}">` +
      `<header><strong>Direct runtime</strong><span>${escapeHtml(directLabel)}</span></header>` +
      `<div>${escapeHtml(issues.length ? issues.join(" | ") : "This runtime is pointed at the selected store and reviewed memory set.")}</div>` +
      `<div>artifact mode=${escapeHtml(friendlyArtifactMode(String(direct.artifact_mode || "-")))}</div>` +
      `<div>lock status=${escapeHtml(friendlyLockStatus(lockStatus))}</div>` +
      `<div>last checked=${escapeHtml(formatDate(direct.checked_at || ""))}</div>` +
      `<div class="wizard-result-meta"><strong>Details:</strong> store_fingerprint=${escapeHtml(String(direct.store_fingerprint || "-"))} | episode_source=${escapeHtml(String(direct.episodes_path || "-"))}</div>` +
      repairButton +
      `</article>`;
    const repairInline = els.wizardActivationStatus.querySelector(".wizard-direct-repair-inline");
    if (repairInline) {
      repairInline.addEventListener("click", () => {
        runWizardDirectCleanup().catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
      });
    }
  }
  if (els.wizardDirectCleanup) {
    els.wizardDirectCleanup.disabled = !Boolean(directLock.cleanup_allowed);
    els.wizardDirectCleanup.hidden = !Boolean(directLock.cleanup_allowed);
    els.wizardDirectCleanup.title = directLock.cleanup_allowed
      ? "Repair or clear a stale direct-runtime lock."
      : "Cleanup is only available when the lock is missing or stale.";
  }
  if (els.wizardDeveloperMode) {
    els.wizardDeveloperMode.checked = Boolean(activation.developer_mode);
  }
  if (els.wizardDraftReason && !String(els.wizardDraftReason.value || "").trim() && draftOverride.reason) {
    els.wizardDraftReason.value = String(draftOverride.reason || "");
  }
  if (els.btnWizardDraftGoLive) {
    const developerMode = Boolean(activation.developer_mode);
    els.btnWizardDraftGoLive.disabled = !developerMode;
    els.btnWizardDraftGoLive.title = developerMode
      ? "Unsafe local testing only. This never counts as normal success."
      : "Enable developer mode before draft activation.";
  }
  if (els.wizardMcpTargets) {
    renderWizardMcpTargets(els.wizardMcpTargets, {
      mcp,
      selectedScope,
      resultNode: els.wizardGoLiveResult,
      onInstall: runWizardMcpInstall,
      onRemove: runWizardMcpRemove,
      onExport: exportWizardMcp,
    });
  }
}

function wizardActivationMcpRequestBody(runId = state.wizardRunId || undefined) {
  const profile = managedMcpProfileFromState("reviewed");
  return {
    run_id: runId,
    target: String(els.wizardMcpTarget?.value || state.wizardMcpTarget || "claude_code").trim() || "claude_code",
    claude_code_scope: String(els.wizardMcpScope?.value || state.wizardMcpScope || "user").trim() || "user",
    default_role: profile.default_role,
    compat_mode: profile.compat_mode,
    mutations_enabled: profile.mutations_enabled,
  };
}

async function refreshWizardActivationStatus(runId = state.wizardRunId || undefined) {
  if (!runId) {
    return;
  }
  await ensureManagedMcpConfigLoaded();
  const payload = await jsonFetch("/api/wizard/activate/status", {
    method: "POST",
    body: JSON.stringify(wizardActivationMcpRequestBody(runId)),
  });
  state.wizardState = {
    ...(state.wizardState || {}),
    activation: payload.activation || payload,
  };
  renderWizardActivation(payload);
  renderWizardOperateState(state.wizardState || {});
}

async function runWizardGoLive() {
  const payload = await jsonFetch("/api/wizard/activate/direct", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
    }),
  });
  const adapters = Array.isArray(payload?.adapters) ? payload.adapters : [];
  wizardResult(els.wizardGoLiveResult, {
    tone: "ok",
    title: "Local runtime started.",
    detail: "MNO is now serving the reviewed memory set in the background.",
    next: "Use Operate to run the live smoke test, or set up an assistant, agent, or MCP client.",
    meta: `runtime_url=${payload.runtime_url} | adapters=${adapters.length}`,
  });
  const providerConfig = payload?.provider_config || {};
  state.wizardActivationProviderConfig = providerConfig;
  const modelName = String(providerConfig.model_name || payload.model_name || "-");
  const adapterNames = Array.isArray(providerConfig.adapters) ? providerConfig.adapters.join(", ") : adapters.join(", ");
  const configPath = String(payload.config_entrypoint || providerConfig.config_entrypoint || "/api/runtime/provider/config");
  if (els.wizardGoLiveConfig) {
    els.wizardGoLiveConfig.innerHTML =
      `<div>model=<strong>${escapeHtml(modelName)}</strong></div>` +
      `<div>adapters=${escapeHtml(adapterNames || "-")}</div>` +
      `<div><a class="wizard-action-link" href="${escapeHtml(configPath)}" target="_blank" rel="noopener noreferrer">View runtime settings (read-only)</a></div>`;
  }
  await refreshWizardState(state.wizardRunId || undefined);
}

async function setWizardDeveloperMode(enabled) {
  const payload = await jsonFetch("/api/wizard/activate/developer-mode", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      enabled: Boolean(enabled),
    }),
  });
  renderWizardActivation(payload);
  await refreshWizardState(state.wizardRunId || undefined);
}

async function runWizardDraftGoLive() {
  const reason = String(els.wizardDraftReason?.value || "").trim();
  const payload = await jsonFetch("/api/wizard/activate/direct/draft", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      acknowledged: true,
      reason,
      operator: "runtime_ui",
    }),
  });
  wizardResult(els.wizardGoLiveResult, {
    tone: "warn",
    title: "Unsafe local draft runtime started.",
    detail: "This is only for local developer testing and does not count as normal success.",
    next: "Use Publish and Verify if you want a real production-like activation path.",
    meta: `runtime_url=${payload.runtime_url}`,
  });
  renderWizardActivation(payload);
  await refreshWizardState(state.wizardRunId || undefined);
}

async function runWizardDirectCleanup() {
  const payload = await jsonFetch("/api/wizard/activate/direct/cleanup", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
    }),
  });
  wizardResult(els.wizardGoLiveResult, {
    tone: "info",
    title: "Local runtime lock cleanup finished.",
    detail: "This only repairs stale or broken lock state. It does not start the runtime by itself.",
    next: "Check activation status again, then start the local runtime if the path is clear.",
    meta: `cleanup_action=${payload.cleanup?.action || "noop"}`,
  });
  renderWizardActivation(payload);
  await refreshWizardState(state.wizardRunId || undefined);
}

async function refreshWizardRemapStatus(runId = state.wizardRunId || undefined) {
  if (!runId) {
    return;
  }
  const payload = await jsonFetch("/api/wizard/remap/status", {
    method: "POST",
    body: JSON.stringify({ run_id: runId }),
  });
  renderWizardRemapStatus(payload);
}

async function applyWizardRemapFile(file) {
  const target = String(state.wizardPendingRemapTarget || "").trim();
  if (!file || !target) {
    return;
  }
  const arrayBuffer = await file.arrayBuffer();
  const payload = await jsonFetch("/api/wizard/remap/apply", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      target,
      file_name: file.name,
      content_base64: arrayBufferToBase64(arrayBuffer),
    }),
  });
  state.wizardPendingRemapTarget = "";
  if (els.wizardRemapFile) {
    els.wizardRemapFile.value = "";
  }
  wizardResult(els.wizardVerifyResult, {
    tone: "ok",
    title: "Missing artifact replaced.",
    detail: `The wizard now points ${target} at the replacement file you picked.`,
    next: "Run Verify again.",
    meta: `replacement=${payload.result?.replacement?.path || file.name}`,
  });
  renderWizardRemapStatus(payload);
  await refreshWizardState(state.wizardRunId || undefined);
}

async function resetWizardState(stage) {
  const payload = await jsonFetch("/api/wizard/reset", {
    method: "POST",
    body: JSON.stringify({
      run_id: state.wizardRunId || undefined,
      stage,
    }),
  });
  wizardResult(els.wizardVerifyResult, {
    tone: "warn",
    title: `Wizard moved back to ${stageLabel(stage)}.`,
    detail: "The stale downstream state was cleared so you can rebuild it cleanly.",
    next: `Finish ${stageLabel(stage)} again, then continue forward.`,
  });
  state.wizardState = payload.state || state.wizardState;
  renderWizardState();
  await refreshWizardState(state.wizardRunId || undefined);
}

async function runWizardMcpInstall(target, ownershipAction = "") {
  const claudeCodeScope = String(els.wizardMcpScope?.value || state.wizardMcpScope || "user").trim() || "user";
  const profile = managedMcpProfileFromState("reviewed");
  const targetLabel = integrationTargetDisplay(target, (state.wizardActivation || {}).mcp || {});
  const payload = await jsonFetch("/api/wizard/activate/mcp/install", {
    method: "POST",
    body: JSON.stringify({
      ...wizardActivationMcpRequestBody(state.wizardRunId || undefined),
      target,
      ownership_action: ownershipAction || undefined,
    }),
  });
  wizardResult(els.wizardGoLiveResult, {
    tone: "ok",
    title: "Assistant/agent / MCP setup updated.",
    detail: `${targetLabel} now has the latest MNO connection entry${target === "claude_code" ? ` in ${friendlyMcpScope(claudeCodeScope)} scope` : ""}.`,
    next: "Restart the external client if it was already open, then run a small recall test.",
    meta: `target=${target}${target === "claude_code" ? ` | scope=${claudeCodeScope}` : ""} | role=${profile.default_role} | mutations=${profile.mutations_enabled ? "on" : "off"}`,
  });
  renderWizardActivation(payload);
  await refreshWizardState(state.wizardRunId || undefined);
}

async function runWizardMcpRemove(target) {
  const claudeCodeScope = String(els.wizardMcpScope?.value || state.wizardMcpScope || "user").trim() || "user";
  const targetLabel = integrationTargetDisplay(target, (state.wizardActivation || {}).mcp || {});
  const payload = await jsonFetch("/api/wizard/activate/mcp/remove", {
    method: "POST",
    body: JSON.stringify({
      ...wizardActivationMcpRequestBody(state.wizardRunId || undefined),
      target,
    }),
  });
  wizardResult(els.wizardGoLiveResult, {
    tone: "info",
    title: "Assistant/agent / MCP entry removed.",
    detail: `${targetLabel} no longer has the MNO connection entry installed${target === "claude_code" ? ` in ${friendlyMcpScope(claudeCodeScope)} scope` : ""}.`,
    next: "Use Export Selected Setup Bundle again if you want to reconnect it later.",
    meta: `target=${target}${target === "claude_code" ? ` | scope=${claudeCodeScope}` : ""}`,
  });
  renderWizardActivation(payload);
  await refreshWizardState(state.wizardRunId || undefined);
}

async function applyWizardManagedMcpProfile() {
  const profile = managedMcpProfileFromState("reviewed");
  await saveManagedMcpProfileFromUi("reviewed");
  wizardResult(els.wizardGoLiveResult, {
    tone: "ok",
    title: "Managed local MCP restarted.",
    detail: `The desktop-managed reviewed connector now runs with ${friendlyMcpRole(profile.default_role).toLowerCase()} role and mutation tools ${profile.mutations_enabled ? "on" : "off"}.`,
    next: "Refresh activation status, then rerun your MCP client if it was already open.",
    meta: `role=${profile.default_role} | compat=strict | mutations=${profile.mutations_enabled ? "on" : "off"}`,
  });
  await refreshWizardActivationStatus(state.wizardRunId || undefined);
}

async function exportWizardMcp(target = String(els.wizardMcpTarget?.value || state.wizardMcpTarget || "claude_code").trim() || "claude_code") {
  const payload = await jsonFetch("/api/wizard/activate/mcp/export", {
    method: "POST",
    body: JSON.stringify({
      ...wizardActivationMcpRequestBody(state.wizardRunId || undefined),
      target,
    }),
  });
  const targetLabel = integrationTargetDisplay(String(payload.target || target), (state.wizardActivation || {}).mcp || {});
  wizardResult(els.wizardGoLiveResult, {
    tone: "ok",
    title: "Assistant/agent setup bundle is ready.",
    detail: `Use this when you want ${targetLabel.toLowerCase()} to connect to the live MNO runtime.`,
    next: "Use one of the exported launchers or config snippets, then run one memory recall smoke test.",
    meta: `target=${payload.target || target} | server=${payload.export?.server_name || "-"} | files=${Array.isArray(payload.export?.artifact_paths) ? payload.export.artifact_paths.length : 0}`,
  });
  await refreshWizardActivationStatus(state.wizardRunId || undefined);
}

async function openWizardArtifacts() {
  const runId = state.wizardRunId || "";
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  const payload = await jsonFetch(`/api/wizard/artifacts${query}`);
  const folder = payload.open_output_folder_hint || payload.artifacts?.run_folder || "-";
  wizardResult(els.wizardGoLiveResult, {
    tone: "info",
    title: "Run folder located.",
    detail: "This is where the wizard keeps the current run artifacts and reports.",
    next: "Open it if you need the raw files. Otherwise keep going in the wizard.",
    meta: `folder=${folder}`,
  });
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

function episodeLineageSummary(episode) {
  const familyId = String(episode?.truth_family_id || "").trim();
  const supersedes = String(episode?.supersedes_episode_id || "").trim();
  const supersededBy = String(episode?.superseded_by_episode_id || "").trim();
  const hasLineage = familyId || supersedes || supersededBy || Object.prototype.hasOwnProperty.call(episode || {}, "lineage_is_current");
  if (!hasLineage) {
    return "";
  }
  const stateLabel = episode?.lineage_is_current ? "Current" : (supersededBy ? "Superseded" : "Reviewed");
  const rows = [
    `<div><strong>Truth Family</strong><span>${escapeHtml(familyId || "—")}</span></div>`,
    `<div><strong>Status</strong><span>${escapeHtml(stateLabel)}</span></div>`,
  ];
  if (supersedes) {
    rows.push(`<div><strong>Supersedes</strong><span>${escapeHtml(supersedes)}</span></div>`);
  }
  if (supersededBy) {
    rows.push(`<div><strong>Superseded By</strong><span>${escapeHtml(supersededBy)}</span></div>`);
  }
  return `<div class="episode-lineage-card"><div class="episode-lineage-title">Truth Lineage</div><div class="episode-lineage-grid">${rows.join("")}</div></div>`;
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
  const lineageSummary = episodeLineageSummary(episode);
  els.episodeDetail.innerHTML =
    `<div class="memory-detail-head"><strong>${escapeHtml(episode.episode_id || "")}</strong><span>${escapeHtml(episode.promotion_status || "")}</span></div>` +
    lineageSummary +
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
  const setupWorkspace = Array.isArray(payload.setup_workspace_entrypoints) ? payload.setup_workspace_entrypoints.join(", ") : "";
  const targetCount = Object.keys(payload.integration_targets || {}).length;
  els.packagingPanel.innerHTML =
    `<div>setup command: <code>${escapeHtml(payload.setup_workspace_command || payload.one_click_command || "-")}</code></div>` +
    `<div>setup files: ${escapeHtml(setupWorkspace || "-")}</div>` +
    `<div>windows: ${escapeHtml(windows)}</div>` +
    `<div>integration targets: ${escapeHtml(String(targetCount || 0))}</div>` +
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
  syncDesktopHomeAvailability();
  els.btnDesktopHome?.addEventListener("click", () => {
    window.desktopWorkspace?.openDesktopHome?.();
  });
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
  els.btnMemoryGraphExpand?.addEventListener("click", () => {
    const panel = document.querySelector(".memory-graph-panel");
    if (panel) {
      panel.classList.toggle("expanded");
      const isExpanded = panel.classList.contains("expanded");
      els.btnMemoryGraphExpand.textContent = isExpanded ? "Collapse" : "Expand";
      requestAnimationFrame(() => fitMemoryGraphToCurrentData());
    }
  });
  els.btnMemoryGraphToggleIsolated?.addEventListener("click", () => {
    state.memoryGraphHideIsolated = !state.memoryGraphHideIsolated;
    els.btnMemoryGraphToggleIsolated.textContent = state.memoryGraphHideIsolated ? "Show isolated" : "Hide isolated";
    state.memoryGraphLayoutCache = {};
    renderMemoryGraph();
    requestAnimationFrame(() => fitMemoryGraphToCurrentData());
  });
  els.btnMemoryNeighborhoodClose?.addEventListener("click", closeNeighborhoodDrawer);
  els.memoryNeighborhoodBackdrop?.addEventListener("click", closeNeighborhoodDrawer);
  els.memoryNeighborhoodViewport?.addEventListener("pointerdown", beginNeighborhoodPan);
  els.memoryNeighborhoodViewport?.addEventListener("pointermove", continueNeighborhoodPan);
  els.memoryNeighborhoodViewport?.addEventListener("pointerup", endNeighborhoodPan);
  els.memoryNeighborhoodViewport?.addEventListener("pointerleave", endNeighborhoodPan);
  els.memoryNeighborhoodViewport?.addEventListener("wheel", (event) => {
    event.preventDefault();
    const current = state.neighborhoodView || { scale: 1, offsetX: 0, offsetY: 0 };
    const oldScale = Math.max(0.3, Number(current.scale || 1));
    const delta = event.deltaY < 0 ? 1.12 : 0.89;
    const nextScale = Math.max(0.3, Math.min(4.0, oldScale * delta));
    state.neighborhoodView = { ...current, scale: nextScale };
    renderMemoryNeighborhood();
  }, { passive: false });
  els.memoryGraphViewport?.addEventListener("click", (event) => {
    const pan = state.memoryGraphPan || {};
    if (pan.dragging) {
      return;
    }
    if (event.target instanceof Element && !event.target.closest(".graph-node")) {
      dismissFloatingCard();
      state.selectedGraphAtomId = "";
      renderMemoryGraph();
      renderMemoryGraphDetail();
    }
  });
  els.btnMemoryGraphFit?.addEventListener("click", () => {
    fitMemoryGraphToCurrentData();
    renderMemoryGraph();
  });
  els.btnMemoryGraphZoomOut?.addEventListener("click", () => {
    setMemoryGraphZoom(1 / 1.18);
    renderMemoryGraph();
  });
  els.btnMemoryGraphZoomIn?.addEventListener("click", () => {
    setMemoryGraphZoom(1.18);
    renderMemoryGraph();
  });
  els.btnMemoryGraphFocus?.addEventListener("click", () => {
    if (state.selectedGraphAtomId) {
      centerMemoryGraphOnNode(state.selectedGraphAtomId);
      renderMemoryGraph();
      return;
    }
    if (state.selectedCardId) {
      state.selectedGraphAtomId = atomIdFromCardId(state.selectedCardId);
      centerMemoryGraphOnNode(state.selectedGraphAtomId);
      renderMemoryGraph();
      refreshMemoryNeighborhood().catch((error) => renderMemoryError(error.message));
      return;
    }
    if (state.memoryGraph.nodes.length) {
      state.selectedGraphAtomId = String(state.memoryGraph.nodes[0].atom_id);
      centerMemoryGraphOnNode(state.selectedGraphAtomId);
    }
    renderMemoryGraph();
    renderMemoryGraphDetail();
    refreshMemoryNeighborhood().catch((error) => renderMemoryError(error.message));
  });
  els.btnMemoryGraphReset?.addEventListener("click", () => {
    resetMemoryGraphView();
    renderMemoryGraph();
  });
  els.memoryGraphViewport?.addEventListener("wheel", (event) => {
    event.preventDefault();
    setMemoryGraphZoom(event.deltaY > 0 ? 1 / 1.12 : 1.12, event.clientX, event.clientY);
    renderMemoryGraph();
  }, { passive: false });
  els.memoryGraphViewport?.addEventListener("pointerdown", beginMemoryGraphPan);
  window.addEventListener("pointermove", continueMemoryGraphPan);
  window.addEventListener("pointerup", endMemoryGraphPan);
  window.addEventListener("pointercancel", endMemoryGraphPan);
  els.btnMemoryNeighborhoodRefresh?.addEventListener("click", () => {
    refreshMemoryNeighborhood().catch((error) => renderMemoryError(error.message));
  });
  els.memoryNeighborhoodDepth?.addEventListener("change", () => {
    state.memoryNeighborhood.depth = Math.max(1, Math.min(2, Number(els.memoryNeighborhoodDepth?.value || 1)));
    refreshMemoryNeighborhood().catch((error) => renderMemoryError(error.message));
  });
  els.memoryNeighborhoodShared?.addEventListener("change", () => {
    state.memoryNeighborhood.includeSharedLanguage = !!els.memoryNeighborhoodShared?.checked;
    refreshMemoryNeighborhood().catch((error) => renderMemoryError(error.message));
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
    const hasExisting = Boolean(state.wizardRunId || state.wizardResumeAvailable || state.wizardLatestRunId);
    if (
      hasExisting &&
      !window.confirm(
        "Start Fresh creates a new setup run. Older runs stay on disk, but this new run becomes the one you are working in now. Continue?"
      )
    ) {
      return;
    }
    startWizard("new").catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.btnWizardLaneArchive?.addEventListener("click", () => {
    setWizardInputMode("archive");
  });
  els.btnWizardLaneStore?.addEventListener("click", () => {
    setWizardInputMode("store");
  });
  els.btnWizardArchiveTargetNew?.addEventListener("click", () => {
    setWizardArchiveTargetMode("new");
    renderWizardState();
  });
  els.btnWizardArchiveTargetExisting?.addEventListener("click", () => {
    setWizardArchiveTargetMode("existing");
    renderWizardState();
  });
  els.btnWizardPickFiles?.addEventListener("click", async () => {
    try {
      if (window.desktopWorkspace && typeof window.desktopWorkspace.pickSourceFiles === "function") {
        const result = await window.desktopWorkspace.pickSourceFiles();
        const paths = Array.isArray(result?.paths) ? result.paths : [];
        if (paths.length) {
          await stageWizardLocalPaths([...state.wizardLocalSourcePaths, ...paths]);
          return;
        }
      }
      els.wizardArchiveFile?.click();
    } catch (error) {
      wizardResult(els.wizardImportResult, error.message, true);
    }
  });
  els.btnWizardPickFolder?.addEventListener("click", async () => {
    try {
      if (window.desktopWorkspace && typeof window.desktopWorkspace.pickSourceFolders === "function") {
        const result = await window.desktopWorkspace.pickSourceFolders();
        const paths = Array.isArray(result?.paths) ? result.paths : [];
        if (paths.length) {
          await stageWizardLocalPaths([...state.wizardLocalSourcePaths, ...paths]);
          return;
        }
      }
      els.wizardArchiveFolder?.click();
    } catch (error) {
      wizardResult(els.wizardImportResult, error.message, true);
    }
  });
  els.btnWizardClearSources?.addEventListener("click", () => {
    clearWizardSelectedSources().catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.wizardArchiveFile?.addEventListener("change", () => {
    const files = Array.from(els.wizardArchiveFile.files || []);
    addWizardUploadFiles(files).catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.wizardArchiveFolder?.addEventListener("change", () => {
    const files = Array.from(els.wizardArchiveFolder.files || []);
    addWizardUploadFiles(files).catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.wizardSourceList?.addEventListener("click", (event) => {
    const button = event.target instanceof HTMLElement ? event.target.closest("[data-wizard-source-remove]") : null;
    if (!button) {
      return;
    }
    const sourceId = String(button.getAttribute("data-wizard-source-remove") || "").trim();
    removeWizardSelectedSource(sourceId).catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.btnWizardArchivePathInline?.addEventListener("click", () => {
    const rawPath = String(els.wizardArchivePathInline?.value || "").trim();
    if (!rawPath) {
      wizardResult(els.wizardImportResult, {
        tone: "warn",
        title: "Paste one path first.",
        detail: "Advanced path mode only accepts one local file or folder path at a time.",
        next: "Paste a real path, then click Use Path.",
      });
      return;
    }
    stageWizardLocalPaths([rawPath]).catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.wizardArchivePathInline?.addEventListener("change", () => {
    const rawPath = String(els.wizardArchivePathInline?.value || "").trim();
    if (!rawPath) {
      return;
    }
    stageWizardLocalPaths([rawPath]).catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.btnWizardRefreshSources?.addEventListener("click", () => {
    refreshWizardInputOptions(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.btnWizardRefreshSourcesArchive?.addEventListener("click", () => {
    refreshWizardInputOptions(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardImportResult, error.message, true));
  });
  els.wizardArchiveStoreSelect?.addEventListener("change", () => {
    setWizardArchiveTargetMode(els.wizardArchiveStoreSelect?.value ? "existing" : "new");
    renderWizardInputOptions();
    renderWizardState();
  });
  els.wizardStoreSelect?.addEventListener("change", () => {
    if (els.wizardStoreSummary) {
      const selected = String(els.wizardStoreSelect.value || "").trim();
      wizardResult(
        els.wizardStoreSummary,
        selected
          ? {
              tone: "info",
              title: "Existing MNO store picked.",
              detail: "This skips archive import and continues from the store you chose.",
              next: "Wait for File Checked to turn green, then click Use This Store.",
              meta: `path=${selected}`,
            }
          : {
              tone: "info",
              title: "Pick an existing MNO store.",
              detail: "Use this lane only when the memory data already exists in MNO format.",
              next: "Choose one store to continue.",
            }
      );
    }
    if (els.wizardStoreSelect?.value) {
      validateWizardImport().catch((error) => wizardResult(els.wizardImportResult, error.message, true));
    }
  });
  els.btnWizardRestore?.addEventListener("click", () => {
    if (
      !window.confirm(
        "Restore Last Good Copy swaps the current published pointer back to the most recent good published set and forces Verify again before normal activation. Continue?"
      )
    ) {
      return;
    }
    restoreWizardLastPublished().catch((error) => wizardResult(els.wizardPublishResult, error.message, true));
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
  els.btnWizardBuildPolicyInfo?.addEventListener("click", () => {
    openWizardBuildPolicyDialog();
  });
  els.btnWizardBuildPolicyClose?.addEventListener("click", () => {
    closeWizardBuildPolicyDialog();
  });
  els.wizardBuildPolicyDialog?.addEventListener("click", (event) => {
    if (event.target === els.wizardBuildPolicyDialog) {
      closeWizardBuildPolicyDialog();
    }
  });
  els.btnMemoryPreferenceInfo?.addEventListener("click", () => {
    openMemoryPreferenceDialog();
  });
  els.btnMemoryPreferenceClose?.addEventListener("click", () => {
    closeMemoryPreferenceDialog();
  });
  els.memoryPreferenceDialog?.addEventListener("click", (event) => {
    if (event.target === els.memoryPreferenceDialog) {
      closeMemoryPreferenceDialog();
    }
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
  els.btnWizardReviewFacetToggle?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleWizardReviewFacetMenu();
  });
  els.btnWizardReviewFacetClear?.addEventListener("click", () => {
    clearWizardReviewFacetFilters();
  });
  els.wizardReviewSearch?.addEventListener("input", () => {
    scheduleWizardReviewSearch();
  });
  els.wizardReviewStatus?.addEventListener("change", () => {
    state.wizardReviewShouldFocus = true;
    state.wizardReviewFocusEpisodeId = "";
    resetWizardReviewPaging();
    loadWizardReviewCards().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  });
  els.wizardReviewPageSize?.addEventListener("change", () => {
    state.wizardReviewShouldFocus = true;
    state.wizardReviewFocusEpisodeId = "";
    resetWizardReviewPaging();
    loadWizardReviewCards().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  });
  els.btnWizardReviewPrev?.addEventListener("click", () => {
    state.wizardReviewShouldFocus = true;
    state.wizardReviewFocusEpisodeId = "";
    setWizardReviewPage(Number(state.wizardReviewMeta?.page || 1) - 1);
    loadWizardReviewCards().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  });
  els.btnWizardReviewNext?.addEventListener("click", () => {
    state.wizardReviewShouldFocus = true;
    state.wizardReviewFocusEpisodeId = "";
    setWizardReviewPage(Number(state.wizardReviewMeta?.page || 1) + 1);
    loadWizardReviewCards().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  });
  els.btnWizardReviewApprovePage?.addEventListener("click", () => {
    approveWizardReviewPage().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  });
  els.btnWizardReviewApproveAll?.addEventListener("click", () => {
    approveWizardReviewAll().catch((error) => wizardResult(els.wizardReviewResult, error.message, true));
  });
  els.btnWizardDraftCurationOpenWorkspace?.addEventListener("click", () => {
    state.wizardInlineDialogReturnFocus = els.btnWizardDraftCurationOpenWorkspace;
    openInlineDialog("wizardDraftCurationWorkspaceDialog");
    renderWizardDraftCurationWorkspaceChrome();
    Promise.all([
      refreshWizardDraftCurationStatus(state.wizardRunId || undefined),
      loadWizardDraftCurationProposals(state.wizardRunId || undefined),
      refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined),
    ]).catch((error) => renderWizardDraftCurationFeedback(error.message, true));
  });
  els.btnWizardDraftCurationSidebarToggle?.addEventListener("click", () => {
    state.wizardDraftCurationSidebarCollapsed = !state.wizardDraftCurationSidebarCollapsed;
    renderWizardDraftCurationWorkspaceChrome();
  });
  els.btnWizardDraftCurationSidebarRestore?.addEventListener("click", () => {
    state.wizardDraftCurationSidebarCollapsed = !state.wizardDraftCurationSidebarCollapsed;
    renderWizardDraftCurationWorkspaceChrome();
  });
  els.btnWizardDraftCurationRefresh?.addEventListener("click", () => {
    Promise.all([
      refreshWizardDraftCurationStatus(state.wizardRunId || undefined),
      loadWizardDraftCurationProposals(state.wizardRunId || undefined),
      refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined),
    ]).catch((error) => renderWizardDraftCurationFeedback(error.message, true));
  });
  els.btnWizardDraftCurationMcpRefresh?.addEventListener("click", () => {
    refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardDraftCurationMcpStatus, error.message, true));
  });
  els.btnWizardDraftCurationMcpApply?.addEventListener("click", () => {
    applyWizardDraftCurationManagedMcpProfile().catch((error) => wizardResult(els.wizardDraftCurationMcpStatus, error.message, true));
  });
  els.btnWizardDraftCurationCopyRunId?.addEventListener("click", async () => {
    const runId = currentWizardRunId();
    if (!runId) {
      renderWizardDraftCurationFeedback("No run_id is available yet. Start or resume a run first.", true);
      return;
    }
    try {
      await copyTextToClipboard(runId);
      els.btnWizardDraftCurationCopyRunId.dataset.copied = "true";
      renderWizardDraftCurationRunId();
      renderWizardDraftCurationFeedback(`Run ID copied: ${runId}`);
      window.setTimeout(() => {
        if (!els.btnWizardDraftCurationCopyRunId) {
          return;
        }
        els.btnWizardDraftCurationCopyRunId.dataset.copied = "false";
        renderWizardDraftCurationRunId();
      }, 1800);
    } catch (error) {
      renderWizardDraftCurationFeedback(error instanceof Error ? error.message : String(error), true);
    }
  });
  els.btnWizardDraftCurationMcpExport?.addEventListener("click", () => {
    exportWizardDraftCurationMcp().catch((error) => wizardResult(els.wizardDraftCurationMcpStatus, error.message, true));
  });
  els.wizardDraftCurationMcpTarget?.addEventListener("change", () => {
    state.wizardDraftCurationMcpTarget = String(els.wizardDraftCurationMcpTarget?.value || "claude_code").trim() || "claude_code";
    refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardDraftCurationMcpStatus, error.message, true));
  });
  els.wizardDraftCurationMcpScope?.addEventListener("change", () => {
    state.wizardDraftCurationMcpScope = String(els.wizardDraftCurationMcpScope?.value || "user").trim() || "user";
    refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardDraftCurationMcpStatus, error.message, true));
  });
  els.wizardDraftCurationMcpRole?.addEventListener("change", () => {
    state.wizardDraftCurationMcpRole = String(els.wizardDraftCurationMcpRole?.value || "viewer").trim() || "viewer";
    refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardDraftCurationMcpStatus, error.message, true));
  });
  els.wizardDraftCurationMcpMutations?.addEventListener("change", () => {
    state.wizardDraftCurationMcpMutations = Boolean(els.wizardDraftCurationMcpMutations?.checked);
    refreshWizardDraftCurationMcpStatus(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardDraftCurationMcpStatus, error.message, true));
  });
  els.btnWizardDraftCurationForceRelease?.addEventListener("click", () => {
    releaseWizardDraftCurationLease(true).catch((error) => renderWizardDraftCurationFeedback(error.message, true));
  });
  els.wizardDraftCurationSearch?.addEventListener("input", () => {
    state.wizardDraftCurationMeta = {
      ...(state.wizardDraftCurationMeta || {}),
      search: String(els.wizardDraftCurationSearch?.value || "").trim(),
    };
    resetWizardDraftCurationPaging();
    applyWizardDraftCurationFilters();
  });
  els.wizardDraftCurationStatusFilter?.addEventListener("change", () => {
    state.wizardDraftCurationMeta = {
      ...(state.wizardDraftCurationMeta || {}),
      statusFilter: String(els.wizardDraftCurationStatusFilter?.value || "pending").trim() || "pending",
    };
    resetWizardDraftCurationPaging();
    loadWizardDraftCurationProposals(state.wizardRunId || undefined).catch((error) => renderWizardDraftCurationFeedback(error.message, true));
  });
  els.wizardDraftCurationPageSize?.addEventListener("change", () => {
    state.wizardDraftCurationMeta = {
      ...(state.wizardDraftCurationMeta || {}),
      pageSize: Math.max(1, Number(els.wizardDraftCurationPageSize?.value || 6)),
    };
    resetWizardDraftCurationPaging();
    applyWizardDraftCurationFilters();
  });
  els.btnWizardDraftCurationPrev?.addEventListener("click", () => {
    setWizardDraftCurationPage(Number(state.wizardDraftCurationMeta?.page || 1) - 1);
    applyWizardDraftCurationFilters();
  });
  els.btnWizardDraftCurationNext?.addEventListener("click", () => {
    setWizardDraftCurationPage(Number(state.wizardDraftCurationMeta?.page || 1) + 1);
    applyWizardDraftCurationFilters();
  });
  els.btnWizardReviewEditorClose?.addEventListener("click", () => {
    requestCloseWizardReviewEditor().catch((error) => wizardResult(els.wizardReviewEditorResult, error.message, true));
  });
  els.btnWizardReviewEditorPrev?.addEventListener("click", () => {
    navigateWizardReviewEditor("prev").catch((error) => wizardResult(els.wizardReviewEditorResult, error.message, true));
  });
  els.btnWizardReviewEditorNext?.addEventListener("click", () => {
    navigateWizardReviewEditor("next").catch((error) => wizardResult(els.wizardReviewEditorResult, error.message, true));
  });
  els.btnWizardReviewEditorApprove?.addEventListener("click", () => {
    approveAndCloseWizardReviewEditor().catch((error) => wizardResult(els.wizardReviewEditorResult, error.message, true));
  });
  els.btnWizardReviewEditorReject?.addEventListener("click", () => {
    rejectWizardReviewEditor().catch((error) => wizardResult(els.wizardReviewEditorResult, error.message, true));
  });
  els.btnWizardReviewEditorActorsToggle?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleWizardReviewEditorPicker("actors");
  });
  els.btnWizardReviewEditorTopicsToggle?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleWizardReviewEditorPicker("topics");
  });
  els.btnWizardReviewEditorActorsCustomToggle?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleWizardReviewEditorCustomBox("actors");
  });
  els.btnWizardReviewEditorTopicsCustomToggle?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleWizardReviewEditorCustomBox("topics");
  });
  els.btnWizardReviewEditorActorsCustomAdd?.addEventListener("click", () => {
    addWizardReviewEditorCustomValue("actors");
  });
  els.btnWizardReviewEditorTopicsCustomAdd?.addEventListener("click", () => {
    addWizardReviewEditorCustomValue("topics");
  });
  els.wizardReviewEditorDialog?.addEventListener("click", (event) => {
    if (event.target === els.wizardReviewEditorDialog) {
      requestCloseWizardReviewEditor().catch((error) => wizardResult(els.wizardReviewEditorResult, error.message, true));
    }
  });
  els.wizardReviewEditorDialog?.addEventListener("cancel", (event) => {
    event.preventDefault();
    requestCloseWizardReviewEditor({ restoreFocus: true }).catch((error) => wizardResult(els.wizardReviewEditorResult, error.message, true));
  });
  els.btnWizardDraftCurationProposalClose?.addEventListener("click", () => {
    closeWizardDraftCurationProposal();
  });
  els.btnWizardDraftCurationToggleView?.addEventListener("click", () => {
    const showingContext = !els.wizardDraftCurationContext?.hidden;
    if (els.wizardDraftCurationContext) {
      els.wizardDraftCurationContext.hidden = showingContext;
    }
    if (els.wizardDraftCurationDiffView) {
      els.wizardDraftCurationDiffView.hidden = !showingContext;
    }
    if (els.btnWizardDraftCurationToggleView) {
      els.btnWizardDraftCurationToggleView.textContent = showingContext
        ? "Show Transcript & Neighbors"
        : "Show Card Comparison";
    }
  });
  els.btnWizardDraftCurationProposalPrev?.addEventListener("click", () => {
    navigateWizardDraftCurationProposal("prev");
  });
  els.btnWizardDraftCurationProposalNext?.addEventListener("click", () => {
    navigateWizardDraftCurationProposal("next");
  });
  els.btnWizardDraftCurationReject?.addEventListener("click", () => {
    updateWizardDraftProposal("reject", state.wizardDraftCurationSelectedEpisodeId).catch((error) => {
      wizardResult(els.wizardDraftCurationProposalResult, error.message, true);
    });
  });
  els.btnWizardDraftCurationPromote?.addEventListener("click", () => {
    updateWizardDraftProposal("promote", state.wizardDraftCurationSelectedEpisodeId).catch((error) => {
      wizardResult(els.wizardDraftCurationProposalResult, error.message, true);
    });
  });
  els.btnWizardDraftCurationPromoteAll?.addEventListener("click", () => {
    runWizardDraftProposalBulkAction("promote").catch((error) => {
      renderWizardDraftCurationFeedback(error.message, true);
    });
  });
  els.wizardDraftCurationProposalDialog?.addEventListener("click", (event) => {
    if (event.target === els.wizardDraftCurationProposalDialog) {
      closeWizardDraftCurationProposal();
    }
  });
  els.wizardDraftCurationProposalDialog?.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeWizardDraftCurationProposal();
  });
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Node)) {
      return;
    }
    if (
      state.wizardReviewFacetMenuOpen &&
      !els.wizardReviewFacetMenu?.contains(target) &&
      !els.btnWizardReviewFacetToggle?.contains(target)
    ) {
      closeWizardReviewFacetMenu();
    }
    if (
      state.wizardReviewEditorPickerOpen &&
      !els.wizardReviewEditorActorsMenu?.contains(target) &&
      !els.btnWizardReviewEditorActorsToggle?.contains(target) &&
      !els.wizardReviewEditorTopicsMenu?.contains(target) &&
      !els.btnWizardReviewEditorTopicsToggle?.contains(target)
    ) {
      closeWizardReviewEditorPickers();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
      return;
    }
    if (state.wizardReviewEditorPickerOpen) {
      event.preventDefault();
      closeWizardReviewEditorPickers({ restoreFocus: true });
      return;
    }
    if (state.wizardReviewFacetMenuOpen) {
      event.preventDefault();
      closeWizardReviewFacetMenu({ restoreFocus: true });
    }
  });
  els.btnWizardPublish?.addEventListener("click", () => {
    compileWizardReview().catch((error) => wizardResult(els.wizardPublishResult, error.message, true));
  });
  els.btnWizardVerify?.addEventListener("click", () => {
    runWizardVerify().catch((error) => wizardResult(els.wizardVerifyResult, error.message, true));
  });
  els.wizardRemapFile?.addEventListener("change", () => {
    const [file] = Array.from(els.wizardRemapFile.files || []);
    applyWizardRemapFile(file).catch((error) => wizardResult(els.wizardVerifyResult, error.message, true));
  });
  els.btnWizardActivateRefresh?.addEventListener("click", () => {
    refreshWizardActivationStatus(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.btnWizardManagedMcpApply?.addEventListener("click", () => {
    applyWizardManagedMcpProfile().catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.wizardMcpTarget?.addEventListener("change", () => {
    state.wizardMcpTarget = String(els.wizardMcpTarget?.value || "claude_code").trim() || "claude_code";
    refreshWizardActivationStatus(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.wizardMcpScope?.addEventListener("change", () => {
    state.wizardMcpScope = String(els.wizardMcpScope?.value || "user").trim() || "user";
    refreshWizardActivationStatus(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.wizardMcpRole?.addEventListener("change", () => {
    state.wizardMcpRole = String(els.wizardMcpRole?.value || "viewer").trim() || "viewer";
    refreshWizardActivationStatus(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.wizardMcpMutations?.addEventListener("change", () => {
    state.wizardMcpMutations = Boolean(els.wizardMcpMutations?.checked);
    refreshWizardActivationStatus(state.wizardRunId || undefined).catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.wizardDeveloperMode?.addEventListener("change", () => {
    setWizardDeveloperMode(els.wizardDeveloperMode.checked).catch((error) => {
      if (els.wizardDeveloperMode) {
        els.wizardDeveloperMode.checked = !els.wizardDeveloperMode.checked;
      }
      wizardResult(els.wizardGoLiveResult, error.message, true);
    });
  });
  els.btnWizardGoLive?.addEventListener("click", () => {
    runWizardGoLive().catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.btnWizardDraftGoLive?.addEventListener("click", () => {
    runWizardDraftGoLive().catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.wizardDirectCleanup?.addEventListener("click", () => {
    runWizardDirectCleanup().catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.btnWizardExportMcp?.addEventListener("click", () => {
    exportWizardMcp().catch((error) => wizardResult(els.wizardGoLiveResult, error.message, true));
  });
  els.btnWizardOperateChat?.addEventListener("click", () => {
    switchTab("chat");
  });
  els.btnWizardOperateMemory?.addEventListener("click", () => {
    switchTab("memory");
    setMemoryScope("episodes");
    refreshEpisodes().catch((error) => renderMemoryError(error.message));
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
  initializeHcrMode();
  applySettingsToInputs();
  syncMemoryNeighborhoodInputs();
  updateAutoRefresh();
  setMemoryScope("atoms");
  renderArchiveViewer();
  renderWhyPanel();
  renderPackagingPanel();
  renderHealthPanel();
  renderMemoryNeighborhood();
  bindEvents();
  bindInlineDialogs();
  bindTabNavigation();
  bindSubTabNavigation();
  bindWizardStepNavigation();
  bindDiscreteCardStepping();
  clearContextPreview();
  await ensureTabData("setup", { force: true });
  const initialTab = activeTabId();
  if (initialTab !== "setup") {
    await ensureTabData(initialTab, { force: true });
  }
}

bootstrap().catch((error) => {
  showTraceError(error.message);
});
