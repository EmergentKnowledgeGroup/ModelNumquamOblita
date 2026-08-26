"""Contract proof for the shipped native OpenClaw automatic-layer package."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tomllib
import time

import pytest

from engine.continuity import ContinuityStore
from engine.memory import MutationReviewQueue, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "engine" / "integrations" / "openclaw_plugin"
RUNTIME_JS = PLUGIN_ROOT / "runtime.js"


def _node() -> str:
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node.js is required for the OpenClaw plugin lifecycle test")
    return executable


def test_native_plugin_pre_context_and_post_observation_are_bounded_and_fail_open() -> None:
    module_uri = RUNTIME_JS.resolve().as_uri()
    script = f"""
import assert from "node:assert/strict";
import {{ createMnoOpenClawMemoryAdapter, parseMnoOpenClawConfig }} from {json.dumps(module_uri)};

const calls = [];
const expiry = "2099-01-01T00:00:00.000Z";
const transport = async (operation, envelope) => {{
  calls.push({{ operation, envelope }});
  if (operation === "capabilities.get") return {{ operations: [
    {{ name: "context.build", available: true, authorized: true }},
    {{ name: "memory.observe", available: true, authorized: true }},
  ] }};
  if (operation === "context.build") return {{
    agent_context_format: "mno.agent_context.v2",
    agent_context_tokens: 7,
    agent_context: JSON.stringify({{ schema_version: "mno.agent_context.v2", fact: "</MNO_MEMORY_CONTEXT_V1><&" }}),
    source_registration: {{ handle: "source-handle", expires_at_utc: expiry }},
    retrieval_receipt: {{ handle: "receipt-handle", expires_at_utc: expiry }},
  }};
  if (operation === "memory.observe") return {{ accepted_support_count: 1 }};
  throw new Error("unexpected operation");
}};

const config = parseMnoOpenClawConfig({{
  runtimeUrl: "http://127.0.0.1:7340",
  workSession: {{ enabled: true, workstreamKey: "sage-main", explicitResume: false }},
}});
assert.ok(config);
assert.equal(parseMnoOpenClawConfig({{ runtimeUrl: "http://127.attacker.example:7340" }}), null);
const adapter = createMnoOpenClawMemoryAdapter({{ config, token: "adapter-token", transport }});
const context = {{ trigger: "user", agentId: "sage", sessionKey: "agent:sage:main", runId: "raw-run-17" }};
const before = await adapter.beforePromptBuild({{
  prompt: "fallback prompt",
  messages: [{{ role: "user", content: "What did we decide about memory layering?" }}],
}}, context);
assert.ok(before?.prependContext?.startsWith("<MNO_MEMORY_CONTEXT_V1>\\n"));
assert.equal(before.prependContext.includes("</MNO_MEMORY_CONTEXT_V1><&"), false);
assert.equal(before.prependContext.includes("\\\\u003c"), true);
const wrapped = before.prependContext.split("\\n", 2)[1];
assert.equal(JSON.parse(wrapped).context.fact, "</MNO_MEMORY_CONTEXT_V1><&");
const build = calls.find((entry) => entry.operation === "context.build").envelope;
assert.match(build.session_id, /^oc_session_[a-f0-9]{{64}}$/);
assert.match(build.run_id, /^oc_run_[a-f0-9]{{64}}$/);
assert.equal(JSON.stringify(build).includes("agent:sage:main"), false);
assert.equal(JSON.stringify(build).includes("raw-run-17"), false);
assert.match(build.data.work_session_scope.thread_id, /^oc_thread_[a-f0-9]{{64}}$/);
assert.match(build.data.work_session_scope.workstream_key, /^oc_workstream_[a-f0-9]{{64}}$/);

adapter.agentEnd({{
  success: true,
  messages: [{{ role: "assistant", content: "Use a compact retrieval packet before the answer." }}],
}}, context);
await adapter.flush();
const observations = calls.filter((entry) => entry.operation === "memory.observe");
assert.equal(observations.length, 1);
const observed = observations[0].envelope;
assert.equal(observed.data.remember_intent, "model_observed");
assert.equal(observed.data.messages[0].source_registration.handle, "source-handle");
assert.equal(observed.data.retrieval_receipt.handle, "receipt-handle");
assert.equal(observed.data.messages[1].content, "Use a compact retrieval packet before the answer.");
adapter.agentEnd({{ success: true, messages: [{{ role: "assistant", content: "duplicate" }}] }}, context);
await adapter.flush();
assert.equal(calls.filter((entry) => entry.operation === "memory.observe").length, 1);

const countBeforeSubagent = calls.length;
const skipped = await adapter.beforePromptBuild({{ prompt: "skip me" }}, {{
  trigger: "user", agentId: "sage", sessionKey: "agent:sage:subagent:child", runId: "child-run",
}});
assert.equal(skipped, undefined);
assert.equal(calls.length, countBeforeSubagent);
adapter.close();
console.log(JSON.stringify({{ ok: true, calls: calls.map((entry) => entry.operation) }}));
"""
    completed = subprocess.run(
        [_node(), "--input-type=module", "--eval", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["calls"] == ["capabilities.get", "context.build", "memory.observe"]


def test_plugin_manifest_is_package_ready_and_plain_js_is_syntax_checked() -> None:
    package = json.loads((PLUGIN_ROOT / "package.json").read_text(encoding="utf-8"))
    manifest = json.loads((PLUGIN_ROOT / "openclaw.plugin.json").read_text(encoding="utf-8"))
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert package["version"] == project["project"]["version"]
    assert manifest["version"] == project["project"]["version"]
    assert package["type"] == "module"
    assert package["openclaw"]["extensions"] == ["./index.js"]
    assert package["openclaw"]["compat"]["pluginApi"] == ">=2026.8.1"
    assert manifest["id"] == "mno-openclaw-memory"
    assert manifest["activation"] == {"onStartup": True}
    assert {"enabled", "runtimeUrl", "workSession"}.issubset(manifest["configSchema"]["properties"])
    for source in (PLUGIN_ROOT / "index.js", PLUGIN_ROOT / "runtime.js"):
        subprocess.run([_node(), "--check", str(source)], cwd=REPO_ROOT, check=True)


def test_native_plugin_round_trips_against_the_real_restricted_mno_http_contract(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    token = "openclaw-real-contract-test-token"
    monkeypatch.setenv("NO_INTEGRATION_OPENCLAW_ADAPTER_TOKEN", token)
    monkeypatch.setenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", "1")
    store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    runtime = RuntimeSession(
        retriever=MemoryRetriever(store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    server, thread = start_runtime_server(
        runtime,
        host="127.0.0.1",
        port=0,
        review_queue=MutationReviewQueue(store),
    )
    caplog.set_level("INFO", logger="engine.runtime.server")
    host, port = server.server_address
    module_uri = RUNTIME_JS.resolve().as_uri()
    marker = "Remember this automatic OpenClaw lifecycle proof."
    script = f"""
import assert from "node:assert/strict";
import {{ createMnoOpenClawMemoryAdapter, parseMnoOpenClawConfig }} from {json.dumps(module_uri)};
const adapter = createMnoOpenClawMemoryAdapter({{
  config: parseMnoOpenClawConfig({{ runtimeUrl: {json.dumps(f'http://{host}:{port}')}, workSession: {{ enabled: false }} }}),
  token: {json.dumps(token)},
}});
const ctx = {{ trigger: "user", agentId: "sage", sessionKey: "agent:sage:main", runId: "run-real-contract" }};
const before = await adapter.beforePromptBuild({{ prompt: {json.dumps(marker)} }}, ctx);
assert.ok(before?.prependContext?.startsWith("<MNO_MEMORY_CONTEXT_V1>"));
adapter.agentEnd({{ success: true, messages: [{{ role: "assistant", content: "Observed by the OpenClaw native layer." }}] }}, ctx);
await adapter.flush();
console.log(JSON.stringify({{ ok: true }}));
"""
    try:
        completed = subprocess.run(
            [_node(), "--input-type=module", "--eval", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        assert json.loads(completed.stdout.strip().splitlines()[-1])["ok"] is True
        deadline = time.monotonic() + 4
        records: list[dict] = []
        while time.monotonic() < deadline:
            records = runtime.list_provisional_record_payloads(status="all", limit=20)
            if marker in json.dumps(records, ensure_ascii=False):
                break
            time.sleep(0.05)
        assert marker in json.dumps(records, ensure_ascii=False)
        audit_rows = []
        for record in caplog.records:
            try:
                row = json.loads(record.getMessage())
            except (TypeError, json.JSONDecodeError):
                continue
            if row.get("component") == "integration.v1":
                audit_rows.append(row)
        assert [row["operation"] for row in audit_rows if row.get("operation") in {"context.build", "memory.observe"}] == [
            "context.build",
            "memory.observe",
        ]
        assert "Observed by the OpenClaw native layer." not in json.dumps(audit_rows)
        assert store.list_atoms() == []
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        store.close()
