/**
 * Stdlib-only automatic MNO turn lifecycle adapter for OpenClaw.
 *
 * The adapter has no host-memory authority.  It performs one bounded context
 * build before an eligible root human turn, injects a compact prompt-only
 * packet, and records one provisional observation only after a matching
 * successful agent_end event.  All hook failures are fail-open.
 */

import { Buffer } from "node:buffer";
import { createHash, randomUUID } from "node:crypto";
import { isIP } from "node:net";

export const PLUGIN_ID = "mno-openclaw-memory";
export const SCHEMA_VERSION = "mno.openclaw-adapter.v1";
export const CONTEXT_FORMAT = "mno.agent_context.v2";
export const TOKEN_ENV = "NO_INTEGRATION_OPENCLAW_ADAPTER_TOKEN";
export const ALLOWED_OPERATIONS = Object.freeze([
  "health.get",
  "capabilities.get",
  "context.build",
  "memory.observe",
]);

const MAX_TEXT = 4096;
const MAX_CONTEXT_TOKENS = 4096;
const MAX_HTTP_RESPONSE_BYTES = 262144;
const CAPABILITIES_TTL_DEFAULT_MS = 30000;
const FIXED_REASONS = new Set([
  "disabled",
  "ineligible",
  "invalid_config",
  "unavailable",
  "unauthorized",
  "contract",
  "expired",
  "queue_full",
  "duplicate",
  "closed",
]);

function asObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}

function nonEmptyString(value) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

export function normalizeText(value) {
  if (typeof value !== "string") return null;
  const repaired = Array.from(value, (char) => {
    const code = char.codePointAt(0);
    return code >= 0xd800 && code <= 0xdfff ? "\ufffd" : char;
  }).join("");
  const normalized = repaired.replace(/\r\n?/g, "\n").normalize("NFC").trim();
  return normalized ? normalized.slice(0, MAX_TEXT) : null;
}

function boundedInteger(data, key, defaultValue, low, high) {
  const raw = Object.prototype.hasOwnProperty.call(data, key) ? data[key] : defaultValue;
  if (typeof raw !== "number" || !Number.isInteger(raw) || raw < low || raw > high) return null;
  return raw;
}

export function normalizeMnoRuntimeUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "");
    const loopback = host === "localhost" ||
      (isIP(host) === 4 && /^127\./.test(host)) ||
      (isIP(host) === 6 && host === "::1");
    if (
      url.protocol !== "http:" || !loopback || url.username || url.password ||
      url.search || url.hash || (url.pathname !== "" && url.pathname !== "/")
    ) return null;
    return url.origin;
  } catch {
    return null;
  }
}

export function parseMnoOpenClawConfig(raw) {
  const data = asObject(raw) || {};
  if (data.enabled !== undefined && typeof data.enabled !== "boolean") return null;
  const enabled = data.enabled !== false;
  const runtimeUrl = normalizeMnoRuntimeUrl(data.runtimeUrl ?? "http://127.0.0.1:7340");
  if (!runtimeUrl) return null;
  const values = {
    contextTimeoutMs: boundedInteger(data, "contextTimeoutMs", 2500, 100, 2500),
    contextResponseMaxCharacters: boundedInteger(data, "contextResponseMaxCharacters", 8192, 1, 8192),
    observeTimeoutMs: boundedInteger(data, "observeTimeoutMs", 5500, 100, 5500),
    observeQueueMaxItems: boundedInteger(data, "observeQueueMaxItems", 16, 1, 16),
    observeQueueMaxAgeSeconds: boundedInteger(data, "observeQueueMaxAgeSeconds", 60, 1, 60),
    pendingMaxItems: boundedInteger(data, "pendingMaxItems", 256, 1, 256),
    pendingTtlSeconds: boundedInteger(data, "pendingTtlSeconds", 600, 1, 600),
    capabilityCacheTtlSeconds: boundedInteger(data, "capabilityCacheTtlSeconds", 30, 1, 30),
  };
  if (Object.values(values).some((value) => value === null)) return null;
  const workSessionRaw = data.workSession === undefined ? {} : asObject(data.workSession);
  if (!workSessionRaw || (workSessionRaw.enabled !== undefined && typeof workSessionRaw.enabled !== "boolean")) return null;
  if (workSessionRaw.explicitResume !== undefined && typeof workSessionRaw.explicitResume !== "boolean") return null;
  const rawWorkstreamKey = workSessionRaw.workstreamKey;
  if (rawWorkstreamKey !== undefined && (typeof rawWorkstreamKey !== "string" || rawWorkstreamKey.length > 256)) return null;
  return Object.freeze({
    schemaVersion: SCHEMA_VERSION,
    enabled,
    runtimeUrl,
    ...values,
    workSession: Object.freeze({
      enabled: workSessionRaw.enabled !== false,
      workstreamKey: typeof rawWorkstreamKey === "string" ? rawWorkstreamKey.trim() : "",
      explicitResume: workSessionRaw.explicitResume === true,
    }),
  });
}

export function opaqueId(prefix, ...parts) {
  const raw = parts.map((part) => String(part ?? "")).join("\0");
  return `${prefix}${createHash("sha256").update(raw, "utf8").digest("hex")}`;
}

function contentText(content) {
  if (typeof content === "string") return normalizeText(content);
  if (!Array.isArray(content)) return null;
  const pieces = [];
  for (const row of content) {
    if (typeof row === "string") pieces.push(row);
    else if (asObject(row) && typeof row.text === "string") pieces.push(row.text);
  }
  return normalizeText(pieces.join("\n"));
}

function latestMessageText(messages, role) {
  if (!Array.isArray(messages)) return null;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const row = asObject(messages[index]);
    if (!row || row.role !== role) continue;
    const text = contentText(row.content ?? row.text);
    if (text) return text;
  }
  return null;
}

function preTurnText(event) {
  const messageText = latestMessageText(event?.messages, "user");
  return messageText || normalizeText(event?.prompt);
}

function assistantText(event) {
  return latestMessageText(event?.messages, "assistant") || normalizeText(event?.response);
}

function identityFor(event, ctx) {
  if (ctx?.trigger !== "user") return null;
  const rawSession = nonEmptyString(ctx?.sessionKey);
  const rawRun = nonEmptyString(ctx?.runId) || nonEmptyString(event?.runId);
  const agentId = nonEmptyString(ctx?.agentId);
  if (!rawSession || !rawRun || !agentId) return null;
  const loweredSession = rawSession.toLowerCase();
  if (loweredSession.startsWith("subagent:") || loweredSession.includes(":subagent:")) return null;
  return {
    rawSession,
    rawRun,
    agentId,
    sessionId: opaqueId("oc_session_", agentId, rawSession),
    runId: opaqueId("oc_run_", agentId, rawSession, rawRun),
    key: opaqueId("oc_pending_", agentId, rawSession, rawRun),
  };
}

function parseHandles(data) {
  const sourceRegistration = asObject(data?.source_registration);
  const retrievalReceipt = asObject(data?.retrieval_receipt);
  if (!sourceRegistration || !retrievalReceipt) return null;
  let expiryMs = Number.POSITIVE_INFINITY;
  for (const row of [sourceRegistration, retrievalReceipt]) {
    const handle = nonEmptyString(row.handle);
    const rawExpiry = nonEmptyString(row.expires_at_utc);
    const parsed = Date.parse(rawExpiry);
    if (!handle || !rawExpiry || !Number.isFinite(parsed) || parsed <= Date.now()) return null;
    expiryMs = Math.min(expiryMs, parsed);
  }
  return {
    sourceRegistration: { ...sourceRegistration },
    retrievalReceipt: { ...retrievalReceipt },
    expiryMs,
  };
}

function contextWrapper(data, maximumCharacters) {
  if (data?.agent_context_format !== CONTEXT_FORMAT || typeof data?.agent_context !== "string") return null;
  let context;
  try {
    context = JSON.parse(data.agent_context);
  } catch {
    return null;
  }
  if (!asObject(context) || context.schema_version !== CONTEXT_FORMAT) return null;
  const tokens = data.agent_context_tokens;
  if (typeof tokens !== "number" || !Number.isFinite(tokens) || tokens < 0 || tokens > MAX_CONTEXT_TOKENS) return null;
  let compact;
  try {
    compact = JSON.stringify(context);
  } catch {
    return null;
  }
  const safe = compact.replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");
  if (safe.length > maximumCharacters) return null;
  // Do not stringify the parsed object again: JSON.stringify intentionally
  // leaves '<' alone, which could let an evidence string close this wrapper.
  return `<MNO_MEMORY_CONTEXT_V1>\n{"format":"${CONTEXT_FORMAT}","context":${safe}}\n</MNO_MEMORY_CONTEXT_V1>`;
}

function requestId() {
  return `req_${randomUUID().replace(/-/g, "")}`;
}

function responseData(operation, payload) {
  if (!asObject(payload) || payload.ok !== true || payload.operation !== operation || !asObject(payload.data)) {
    throw new Error("integration_contract");
  }
  return payload.data;
}

export function createMnoHttpTransport({ runtimeUrl, token, fetchImpl = globalThis.fetch } = {}) {
  if (!normalizeMnoRuntimeUrl(runtimeUrl) || typeof token !== "string" || !token || typeof fetchImpl !== "function") {
    return null;
  }
  const base = normalizeMnoRuntimeUrl(runtimeUrl);
  const endpoint = {
    "health.get": "/api/integration/v1/health",
    "capabilities.get": "/api/integration/v1/capabilities",
    "context.build": "/api/integration/v1/context/build",
    "memory.observe": "/api/integration/v1/memory/observe",
  };
  return async (operation, envelope, timeoutMs) => {
    const path = endpoint[operation];
    if (!path) throw new Error("unsupported_operation");
    const url = new URL(path, base);
    const get = operation === "health.get" || operation === "capabilities.get";
    if (get) {
      url.searchParams.set("schema_version", "integration.v1");
      url.searchParams.set("request_id", envelope.request_id);
      if (envelope.session_id) url.searchParams.set("session_id", envelope.session_id);
      if (envelope.run_id) url.searchParams.set("run_id", envelope.run_id);
    }
    const aborter = new AbortController();
    const timer = setTimeout(() => aborter.abort(), Math.max(1, timeoutMs));
    try {
      const response = await fetchImpl(url, {
        method: get ? "GET" : "POST",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${token}`,
          ...(get ? {} : { "Content-Type": "application/json" }),
        },
        body: get ? undefined : JSON.stringify(envelope),
        redirect: "error",
        signal: aborter.signal,
      });
      const raw = await response.text();
      if (Buffer.byteLength(raw, "utf8") > MAX_HTTP_RESPONSE_BYTES) throw new Error("response_too_large");
      let payload;
      try {
        payload = JSON.parse(raw);
      } catch {
        throw new Error("invalid_json");
      }
      if (!response.ok) throw new Error("http_status");
      return responseData(operation, payload);
    } finally {
      clearTimeout(timer);
    }
  };
}

function safeReason(value) {
  return FIXED_REASONS.has(value) ? value : "unavailable";
}

export class MnoOpenClawMemoryAdapter {
  constructor({ config, token = "", transport = null, logger = null, now = () => Date.now() } = {}) {
    this.config = config && typeof config === "object" ? config : null;
    this.token = typeof token === "string" ? token : "";
    this.transport = transport || createMnoHttpTransport({ runtimeUrl: this.config?.runtimeUrl, token: this.token });
    this.logger = logger;
    this.now = now;
    this.pending = new Map();
    this.tombstones = new Map();
    this.queue = [];
    this.capabilities = null;
    this.closed = false;
    this.draining = null;
    this.diagnostics = [];
  }

  get enabled() {
    return Boolean(this.config?.enabled && this.token && this.transport && !this.closed);
  }

  snapshot() {
    return {
      enabled: this.enabled,
      pending: this.pending.size,
      queued: this.queue.length,
      diagnostics: this.diagnostics.slice(),
    };
  }

  _record(operation, reason) {
    const row = { operation, reason: safeReason(reason) };
    this.diagnostics.push(row);
    if (this.diagnostics.length > 64) this.diagnostics.splice(0, this.diagnostics.length - 64);
    try { this.logger?.debug?.(`[mno-openclaw] ${operation}:${row.reason}`); } catch { /* logging is optional */ }
  }

  _purge(now = this.now()) {
    for (const [key, item] of this.pending) if (item.expiresAtMs <= now) this.pending.delete(key);
    for (const [key, expiresAtMs] of this.tombstones) if (expiresAtMs <= now) this.tombstones.delete(key);
    while (this.tombstones.size > (this.config?.pendingMaxItems || 0)) this.tombstones.delete(this.tombstones.keys().next().value);
  }

  async _capabilityFlags() {
    if (!this.enabled) return null;
    if (this.capabilities && this.capabilities.expiresAtMs > this.now()) return this.capabilities.flags;
    const data = await this.transport("capabilities.get", { request_id: requestId() }, this.config.contextTimeoutMs);
    if (!Array.isArray(data.operations)) throw new Error("integration_contract");
    const flags = {};
    for (const row of data.operations) {
      if (asObject(row) && typeof row.name === "string") flags[row.name] = row.available === true && row.authorized === true;
    }
    this.capabilities = { flags, expiresAtMs: this.now() + this.config.capabilityCacheTtlSeconds * 1000 };
    return flags;
  }

  _workSession(identity) {
    if (!this.config.workSession.enabled) return {};
    const seed = this.config.workSession.workstreamKey || identity.agentId;
    return {
      include_work_session_context: true,
      explicit_work_session_resume: this.config.workSession.explicitResume,
      work_session_scope: {
        thread_id: opaqueId("oc_thread_", identity.agentId, identity.rawSession),
        workstream_key: opaqueId("oc_workstream_", identity.agentId, seed),
      },
    };
  }

  async beforePromptBuild(event, ctx) {
    try {
      if (!this.enabled) return undefined;
      const identity = identityFor(event, ctx);
      const userText = preTurnText(event);
      if (!identity || !userText) return undefined;
      const flags = await this._capabilityFlags();
      if (!flags?.["context.build"]) return undefined;
      const data = await this.transport("context.build", {
        schema_version: "integration.v1",
        request_id: requestId(),
        session_id: identity.sessionId,
        run_id: identity.runId,
        data: {
          message: userText,
          memory_preference: "memory_assist",
          ...this._workSession(identity),
        },
      }, this.config.contextTimeoutMs);
      const wrapper = contextWrapper(data, this.config.contextResponseMaxCharacters);
      if (!wrapper) {
        this.capabilities = null;
        this._record("context.build", "contract");
        return undefined;
      }
      if (flags["memory.observe"]) {
        const handles = parseHandles(data);
        if (handles) {
          const now = this.now();
          this._purge(now);
          if (this.pending.size < this.config.pendingMaxItems) {
            const expiresAtMs = Math.min(handles.expiryMs, now + this.config.pendingTtlSeconds * 1000);
            this.pending.set(identity.key, {
              ...identity,
              userText,
              sourceRegistration: handles.sourceRegistration,
              retrievalReceipt: handles.retrievalReceipt,
              expiresAtMs,
            });
          } else {
            this._record("memory.observe", "queue_full");
          }
        }
      }
      return { prependContext: wrapper };
    } catch {
      this.capabilities = null;
      this._record("context.build", "unavailable");
      return undefined;
    }
  }

  agentEnd(event, ctx) {
    try {
      if (!this.config || this.closed) return;
      const identity = identityFor(event, ctx);
      if (!identity) return;
      const now = this.now();
      this._purge(now);
      const pending = this.pending.get(identity.key);
      if (!pending) return;
      this.pending.delete(identity.key);
      this.tombstones.set(identity.key, now + this.config.pendingTtlSeconds * 1000);
      if (event?.success !== true) return;
      const text = assistantText(event);
      if (!text || this.tombstones.has(`${identity.key}:observed`)) return;
      if (this.queue.length >= this.config.observeQueueMaxItems) {
        this._record("memory.observe", "queue_full");
        return;
      }
      this.tombstones.set(`${identity.key}:observed`, now + this.config.pendingTtlSeconds * 1000);
      this.queue.push({ ...pending, assistantText: text, createdAtMs: now });
      void this._drain();
    } catch {
      this._record("memory.observe", "unavailable");
    }
  }

  async _drain() {
    if (this.draining) return this.draining;
    this.draining = (async () => {
      while (!this.closed && this.queue.length) {
        const item = this.queue.shift();
        if (!item || item.expiresAtMs <= this.now() || item.createdAtMs + this.config.observeQueueMaxAgeSeconds * 1000 <= this.now()) {
          this._record("memory.observe", "expired");
          continue;
        }
        try {
          await this.transport("memory.observe", {
            schema_version: "integration.v1",
            request_id: requestId(),
            session_id: item.sessionId,
            run_id: item.runId,
            data: {
              messages: [
                { role: "user", content: item.userText, source_registration: item.sourceRegistration },
                { role: "assistant", content: item.assistantText },
              ],
              retrieval_receipt: item.retrievalReceipt,
              remember_intent: "model_observed",
            },
          }, this.config.observeTimeoutMs);
        } catch {
          // A delivery outcome can be ambiguous; never retry it.
          this._record("memory.observe", "unavailable");
        }
      }
    })();
    try {
      await this.draining;
    } finally {
      this.draining = null;
    }
  }

  async flush() {
    if (this.draining) await this.draining;
  }

  close() {
    this.closed = true;
    this.pending.clear();
    this.queue.length = 0;
    this.tombstones.clear();
  }
}

export function createMnoOpenClawMemoryAdapter(options = {}) {
  const config = options.config === null ? null : parseMnoOpenClawConfig(options.config || {});
  return new MnoOpenClawMemoryAdapter({ ...options, config });
}
