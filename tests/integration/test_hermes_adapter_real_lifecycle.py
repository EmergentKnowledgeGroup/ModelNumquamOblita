"""Opt-in proof against a real pinned Hermes installation.

Run only from the dedicated Hermes proof environment described in
docs/integrations/HERMES_AGENT.md. Ordinary CI skips this because Hermes is an
external application, not an MNO runtime dependency.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest

from engine.continuity import ContinuityStore
from engine.memory import MutationReviewQueue, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server


pytestmark = pytest.mark.skipif(
    os.getenv("MNO_HERMES_REAL_PROOF") != "1",
    reason="requires the pinned Hermes v0.19.0 proof environment",
)


def _text_response(text: str) -> dict[str, object]:
    return {
        "id": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    }


class _ProviderHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []
    answers: list[str] = []
    delay_next_chat_seconds: float = 0.0
    delayed_chat_started = threading.Event()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append(request)
        if "messages" in request and type(self).delay_next_chat_seconds > 0:
            delay = type(self).delay_next_chat_seconds
            type(self).delay_next_chat_seconds = 0.0
            type(self).delayed_chat_started.set()
            time.sleep(delay)
        response = _text_response(
            type(self).answers.pop(0) if type(self).answers else "Proof response."
        )
        if request.get("stream") is True:
            content = str(response["choices"][0]["message"]["content"])  # type: ignore[index]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                {
                    "id": "m",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": content},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "m",
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": "stop"}
                    ],
                },
            ]
            try:
                for chunk in chunks:
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def _chat_requests() -> list[dict[str, object]]:
    return [row for row in _ProviderHandler.requests if "messages" in row]


def _user_messages(request: dict[str, object]) -> list[dict[str, object]]:
    return [
        row
        for row in list(request.get("messages") or [])
        if isinstance(row, dict) and row.get("role") == "user"
    ]


def _wait_for_provisional(runtime: RuntimeSession, marker: str, minimum_support: int) -> list[dict[str, object]]:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        rows = runtime.list_provisional_record_payloads(status="all", limit=100)
        matching = [
            row
            for row in rows
            if marker.casefold() in json.dumps(row, ensure_ascii=False).casefold()
        ]
        if matching and max(
            int(row.get("reinforcement_count") or row.get("independent_support_count") or 0)
            for row in matching
        ) >= minimum_support:
            return matching
        time.sleep(0.05)
    raise AssertionError("automatic provisional observation did not reach MNO")


def test_installed_plugin_runs_real_cli_and_gateway_shaped_turns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    scripts_dir = Path(sys.executable).resolve().parent
    executable_suffix = ".exe" if os.name == "nt" else ""
    mno_hermes = shutil.which("mno-hermes") or str(
        scripts_dir / f"mno-hermes{executable_suffix}"
    )
    hermes = shutil.which("hermes") or str(scripts_dir / f"hermes{executable_suffix}")
    assert Path(mno_hermes).is_file() and Path(hermes).is_file(), (
        "proof environment must expose both console scripts"
    )

    caplog.set_level("INFO", logger="engine.runtime.server")
    token = "mno-hermes-real-proof-token-not-production"
    monkeypatch.setenv("NO_INTEGRATION_HERMES_ADAPTER_TOKEN", token)
    monkeypatch.setenv("NO_INTEGRATION_DISABLE_DEFAULT_TOKENS", "1")

    atom_store = SqliteAtomStore(tmp_path / "atoms.sqlite3")
    review_queue = MutationReviewQueue(atom_store)
    runtime = RuntimeSession(
        retriever=MemoryRetriever(atom_store),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
    )
    runtime_server, runtime_thread = start_runtime_server(
        runtime,
        host="127.0.0.1",
        port=0,
        review_queue=review_queue,
    )
    runtime_host, runtime_port = runtime_server.server_address
    runtime_server.integration_audit_path = str(tmp_path / "integration-audit.jsonl")

    provider = HTTPServer(("127.0.0.1", 0), _ProviderHandler)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    provider_port = provider.server_address[1]
    _ProviderHandler.requests = []
    _ProviderHandler.delay_next_chat_seconds = 0.0
    _ProviderHandler.delayed_chat_started.clear()
    _ProviderHandler.answers = [
        "I will keep that as provisional context.",
        "I still have the same provisional observation.",
        "Gateway-shaped turn completed.",
    ]

    hermes_home = tmp_path / "hermes-home"
    install_env = dict(os.environ)
    install_env["NO_INTEGRATION_HERMES_ADAPTER_TOKEN"] = token
    install_env["PATH"] = os.pathsep.join(
        [str(scripts_dir), str(install_env.get("PATH") or "")]
    )

    try:
        installed = subprocess.run(
            [
                mno_hermes,
                "install",
                "--hermes-home",
                str(hermes_home),
                "--runtime-url",
                f"http://{runtime_host}:{runtime_port}",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=install_env,
            timeout=30,
        )
        assert json.loads(installed.stdout)["status"] == "installed"

        hermes_env = dict(install_env)
        hermes_env["HERMES_HOME"] = str(hermes_home)
        hermes_env["HERMES_CONFIG"] = str(hermes_home / "config.yaml")
        listed = subprocess.run(
            [hermes, "plugins", "list", "--json"],
            check=True,
            capture_output=True,
            text=True,
            env=hermes_env,
            timeout=30,
        )
        plugin_rows = json.loads(listed.stdout)
        assert any(
            row.get("name") == "mno-memory" and row.get("status") == "enabled"
            for row in plugin_rows
        )

        monkeypatch.setenv("HERMES_HOME", str(hermes_home))
        monkeypatch.setenv("HERMES_CONFIG", str(hermes_home / "config.yaml"))
        from hermes_cli.plugins import discover_plugins, get_plugin_manager
        from hermes_state import SessionDB
        from run_agent import AIAgent

        discover_plugins(force=True)
        assert any(
            row.get("name") == "mno-memory"
            and row.get("enabled") is True
            and not row.get("error")
            and row.get("hooks") == 5
            for row in get_plugin_manager().list_plugins()
        )

        session_db = SessionDB(db_path=tmp_path / "hermes-state.sqlite3")
        session_id = "mno-real-cli-session"

        def make_agent(*, platform: str = "cli", user_id: str | None = None) -> AIAgent:
            return AIAgent(
                api_key="proof-key",
                base_url=f"http://127.0.0.1:{provider_port}/v1",
                provider="openai-compat",
                model="proof-model",
                max_iterations=4,
                enabled_toolsets=[],
                quiet_mode=True,
                skip_context_files=True,
                skip_memory=True,
                save_trajectories=False,
                platform=platform,
                user_id=user_id,
                session_db=session_db,
                session_id=session_id if platform == "cli" else "mno-real-gateway-session",
            )

        marker = "I prefer peppermint tea after dinner."
        first_agent = make_agent()
        first_agent.run_conversation(marker, conversation_history=[], task_id="proof-1")
        first_wire = _user_messages(_chat_requests()[-1])[0]["content"]
        assert marker in str(first_wire)
        assert "<MNO_MEMORY_CONTEXT_V1>" in str(first_wire)
        first_rows = _wait_for_provisional(runtime, marker, 1)

        history = session_db.get_messages_as_conversation(session_id)
        stored_user = [
            row for row in session_db.get_messages(session_id) if row["role"] == "user"
        ][0]
        assert stored_user["content"] == marker
        assert stored_user["api_content"] == first_wire

        second_agent = make_agent()
        second_agent.run_conversation(marker, conversation_history=history, task_id="proof-2")
        second_request = _chat_requests()[-1]
        assert _user_messages(second_request)[0]["content"] == first_wire
        second_rows = _wait_for_provisional(runtime, marker, 2)
        assert max(int(row.get("reinforcement_count") or 0) for row in second_rows) >= 2

        gateway_agent = make_agent(platform="discord", user_id="human-proof-user")
        gateway_agent.run_conversation(
            "I prefer jasmine tea in the morning.",
            conversation_history=[],
            task_id="proof-gateway",
        )
        _wait_for_provisional(runtime, "jasmine tea in the morning", 1)

        log_deadline = time.monotonic() + 2
        while time.monotonic() < log_deadline and sum(
            1
            for record in caplog.records
            if '"operation":"memory.observe"' in record.getMessage()
        ) < 3:
            time.sleep(0.02)
        observed_before_interrupt = sum(
            1
            for record in caplog.records
            if '"operation":"memory.observe"' in record.getMessage()
        )
        assert observed_before_interrupt == 3
        interrupted_agent = make_agent()
        interrupted_result: dict[str, object] = {}

        def run_interrupted_turn() -> None:
            interrupted_result.update(
                interrupted_agent.run_conversation(
                    "I prefer oolong tea only in the interrupted proof.",
                    conversation_history=session_db.get_messages_as_conversation(session_id),
                    task_id="proof-interrupted",
                )
            )

        _ProviderHandler.delay_next_chat_seconds = 2.0
        interrupted_thread = threading.Thread(target=run_interrupted_turn)
        interrupted_thread.start()
        assert _ProviderHandler.delayed_chat_started.wait(3)
        interrupted_agent.interrupt()
        interrupted_thread.join(6)
        assert not interrupted_thread.is_alive()
        assert interrupted_result.get("interrupted") is True
        time.sleep(0.2)
        assert sum(
            1
            for record in caplog.records
            if '"operation":"memory.observe"' in record.getMessage()
        ) == observed_before_interrupt
        assert "oolong tea only" not in json.dumps(
            runtime.list_provisional_record_payloads(status="all", limit=100),
            ensure_ascii=False,
        ).casefold()

        audit_rows = []
        for record in caplog.records:
            try:
                row = json.loads(record.getMessage())
            except (TypeError, json.JSONDecodeError):
                continue
            if row.get("component") == "integration.v1":
                audit_rows.append(row)
        observe_run_ids = {
            str(row.get("run_id") or "")
            for row in audit_rows
            if row.get("operation") == "memory.observe"
        }
        assert len({value for value in observe_run_ids if value}) >= 3
        assert first_rows
        assert atom_store.list_atoms() == []
        assert review_queue.list_all() == []
    finally:
        try:
            subprocess.run(
                [
                    mno_hermes or "mno-hermes",
                    "uninstall",
                    "--hermes-home",
                    str(hermes_home),
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=install_env,
                timeout=30,
            )
        except Exception:
            pass
        provider.shutdown()
        provider_thread.join(timeout=2)
        stop_runtime_server(runtime_server, runtime_thread, runtime=runtime)
        atom_store.close()
