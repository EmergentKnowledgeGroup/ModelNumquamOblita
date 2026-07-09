from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.config import default_config
from engine.continuity import ContinuityStore
from engine.memory import AtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession
from engine.runtime.scratchpad import estimate_context_tokens, evaluate_context_diet_fixture


WORKSTREAM = "MNO_WSS_LIVE_LMSTUDIO_HARNESS WORK"
EXPECTED_STATE = {
    "next_action": "run live LM Studio WSS validation",
    "current_files": ["tools/wss_live_lmstudio_harness.py", "engine/runtime/session.py"],
    "blockers": [],
    "needed_refs": ["docs/MNO_WORK_SESSION_SCRATCHPAD_CONTEXT_DIET_SPEC_2026-07-07.md"],
}
TRUTH_FENCES = "MemoryPack, atom/review/publish/verify truth paths, integration-v1, desktop UI, prompt history"


@dataclass(frozen=True, slots=True)
class ModelReply:
    raw_text: str
    parsed: dict[str, Any]
    attempts: int


@dataclass(frozen=True, slots=True)
class HarnessResult:
    passed: bool
    model: str
    run_root: Path
    metrics: dict[str, Any]
    artifacts: dict[str, str]


class ModelClient(Protocol):
    def list_models(self) -> list[str]:
        ...

    def chat_json(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> ModelReply:
        ...


class LMStudioClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = str(base_url or "http://localhost:1234").rstrip("/")

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None, timeout_s: float) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=max(1.0, float(timeout_s))) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw or "{}")
        if not isinstance(parsed, dict):
            raise RuntimeError(f"unexpected LM Studio response type: {type(parsed).__name__}")
        return parsed

    def list_models(self) -> list[str]:
        payload = self._request_json("GET", "/v1/models", None, 10.0)
        data = payload.get("data") or []
        if not isinstance(data, list):
            return []
        out: list[str] = []
        for item in data:
            if isinstance(item, dict):
                model_id = str(item.get("id") or "").strip()
                if model_id:
                    out.append(model_id)
        return out

    def chat_json(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> ModelReply:
        attempts = 0
        last_text = ""
        working_messages = list(messages)
        for attempts in range(1, 4):
            payload = {
                "model": model,
                "messages": working_messages,
                "temperature": float(temperature),
                "max_tokens": int(max_tokens),
                "stream": False,
            }
            response = self._request_json("POST", "/v1/chat/completions", payload, timeout_s)
            choices = response.get("choices") or []
            if choices and isinstance(choices, list) and isinstance(choices[0], dict):
                message = choices[0].get("message") or {}
                if isinstance(message, dict):
                    last_text = str(message.get("content") or "")
            parsed = _parse_json_object(last_text)
            if parsed is not None:
                return ModelReply(raw_text=last_text, parsed=parsed, attempts=attempts)
            working_messages = list(messages) + [
                {
                    "role": "user",
                    "content": "Return exactly one JSON object with the requested keys. Do not include prose.",
                }
            ]
        return ModelReply(raw_text=last_text, parsed={}, attempts=attempts)


class StaticJsonModelClient:
    def list_models(self) -> list[str]:
        return ["gemma-4-e4b-static"]

    def chat_json(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> ModelReply:
        del model, messages, temperature, max_tokens, timeout_s
        return ModelReply(
            raw_text=json.dumps(
                {
                    **EXPECTED_STATE,
                    "memory_claim": False,
                    "scratchpad_as_evidence": False,
                    "reread_requests": [],
                    "confidence": "medium",
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            parsed={
                **EXPECTED_STATE,
                "memory_claim": False,
                "scratchpad_as_evidence": False,
                "reread_requests": [],
                "confidence": "medium",
            },
            attempts=1,
        )


def choose_model(models: list[str], requested_model: str) -> str:
    requested = str(requested_model or "auto").strip()
    if requested and requested.lower() != "auto":
        if requested in models or not models:
            return requested
        lowered = requested.casefold()
        for model in models:
            if model.casefold() == lowered:
                return model
        return requested
    if not models:
        raise RuntimeError("LM Studio reported no models")
    preferences = (
        lambda value: "gemma-4-e4b" in value.casefold(),
        lambda value: "gemma" in value.casefold() and "e4b" in value.casefold(),
        lambda value: "gemma" in value.casefold(),
    )
    for predicate in preferences:
        for model in models:
            if predicate(model):
                return model
    return models[0]


def run_harness(
    *,
    project_root: str | Path,
    run_root: str | Path,
    model_client: ModelClient,
    requested_model: str = "auto",
    live: bool = True,
    temperature: float = 0.0,
    max_tokens: int = 512,
    timeout_s: float = 180.0,
) -> HarnessResult:
    project = Path(project_root).expanduser().resolve()
    run_dir = _ensure_project_runtime_child(project, Path(run_root).expanduser().resolve())
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "context_packages").mkdir(parents=True, exist_ok=True)

    models = model_client.list_models()
    model = choose_model(models, requested_model)
    cfg = default_config()
    cfg.work_session_scratchpad.diagnostics_enabled = True
    cfg.work_session_scratchpad.max_injected_chars = 6000

    runtime = RuntimeSession(
        retriever=MemoryRetriever(AtomStore(), config=cfg),
        verifier=ClaimVerifier(),
        continuity_store=ContinuityStore(),
        config=cfg,
        project_root=project,
        runtime_state_root=run_dir / "runtime_state",
        enable_writeback=False,
    )
    seed_session = "wss_live_seed"
    resume_session = "wss_live_resume"
    scope = {
        "project_id": str(project),
        "thread_id": "wss-live-lmstudio-harness-thread",
        "workstream_key": WORKSTREAM,
        "workstream_name": "MNO WSS live LM Studio harness",
    }
    latencies: list[float] = []
    artifacts: dict[str, str] = {}
    try:
        runtime._ensure_session(seed_session)
        runtime._ensure_session(resume_session)
        first = runtime.capture_work_session_entry(
            session_id=seed_session,
            work_session_scope=scope,
            kind="task_state",
            summary=(
                "NEXT_ACTION=run live LM Studio WSS validation; "
                "CURRENT_FILES=tools/wss_live_lmstudio_harness.py,engine/runtime/session.py; "
                "NEEDED_REFS=docs/MNO_WORK_SESSION_SCRATCHPAD_CONTEXT_DIET_SPEC_2026-07-07.md"
            ),
            raw_content=("runtime/session.py context package builder\n" * 420),
            replaceability_score=0.97,
            metadata={"task_id": "resume-state", "hypothetical_prompt_tokens_replaced": 900},
        )
        runtime.capture_work_session_entry(
            session_id=seed_session,
            work_session_scope=scope,
            kind="blocker",
            summary="BLOCKERS=; Live harness must fail if the model treats scratchpad as memory evidence.",
            raw_content=("WSS blockerboard B1 B2 B3 P4 P5 closed; live model validation pending\n" * 320),
            replaceability_score=0.96,
            metadata={
                "task_id": "live-validation",
                "depends_on_entry_ids": [first["entry_id"]],
                "hypothetical_prompt_tokens_replaced": 680,
            },
        )
        runtime.capture_work_session_entry(
            session_id=seed_session,
            work_session_scope=scope,
            kind="operator_note",
            summary=f"Keep {TRUTH_FENCES} untouched; scratchpad is non-authoritative helper state only.",
            raw_content=("No truth-path mutation. No prompt-history mutation. No LLM summaries or maps.\n" * 140),
            replaceability_score=0.95,
            metadata={"task_id": "truth-fence", "hypothetical_prompt_tokens_replaced": 260},
        )

        default_package = runtime.build_context_package(
            "Resume the WSS lane.",
            session_id=seed_session,
            package_version="v2",
        )
        degraded_package = runtime.build_context_package(
            "Resume the WSS lane.",
            session_id=seed_session,
            package_version="v2",
            include_work_session_context=True,
            work_session_scope={"thread_id": "", "workstream_key": ""},
        )
        same_session_package: dict[str, Any] = {}
        for _ in range(8):
            started = time.perf_counter()
            same_session_package = runtime.build_context_package(
                "Resume the WSS lane.",
                session_id=seed_session,
                package_version="v2",
                include_work_session_diagnostics=True,
                work_session_scope=scope,
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
        other_session_default = runtime.build_context_package(
            "Resume the WSS lane.",
            session_id=resume_session,
            package_version="v2",
            work_session_scope=scope,
        )
        explicit_resume_package = runtime.build_context_package(
            "Resume the WSS lane.",
            session_id=resume_session,
            package_version="v2",
            include_work_session_diagnostics=True,
            explicit_resume=True,
            work_session_scope=scope,
        )
        _write_json(run_dir / "context_packages" / "default_package.json", default_package)
        _write_json(run_dir / "context_packages" / "same_session_package.json", same_session_package)
        _write_json(run_dir / "context_packages" / "explicit_resume_package.json", explicit_resume_package)

        work_context = dict(explicit_resume_package.get("work_session_context") or {})
        actual_state = resume_state_from_work_context(work_context)
        false_memory_trace = runtime.handle_turn(
            "Can the work-session scratchpad prove a durable memory claim?",
            session_id=seed_session,
        )
        truth_isolation_pass = (
            false_memory_trace.decision != "PASS"
            and "sp_" not in json.dumps(explicit_resume_package.get("ltm_evidence") or [], sort_keys=True)
            and all(
                not str(item).startswith("sp_")
                for item in dict(explicit_resume_package.get("retrieval_stats") or {}).get("retrieved_atom_ids") or []
            )
        )
        baseline_prompt = {
            "repeated_rereads": [
                "runtime/session.py context package builder\n" * 420,
                "WSS blockerboard B1 B2 B3 P4 P5 closed; live model validation pending\n" * 320,
                "No truth-path mutation. No prompt-history mutation. No LLM summaries or maps.\n" * 140,
            ],
            "resume_state": EXPECTED_STATE,
        }
        assisted_prompt = {
            "message": explicit_resume_package.get("message"),
            "working_set": explicit_resume_package.get("working_set"),
            "work_session_context": work_context,
        }
        diet_metrics = evaluate_context_diet_fixture(
            baseline_prompt=baseline_prompt,
            scratchpad_assisted_prompt=assisted_prompt,
            work_session_context=work_context,
            expected_resume_state=EXPECTED_STATE,
            actual_resume_state=actual_state,
            repeated_reread_steps=["runtime/session.py", "blockerboard", "truth fences"],
            false_memory_behavior_unchanged=truth_isolation_pass,
            package_build_latencies_ms=latencies,
            latency_budget_ms=1000.0,
        )

        model_messages = _model_messages(explicit_resume_package)
        reply = model_client.chat_json(
            model=model,
            messages=model_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
        )
        _write_json(
            run_dir / "lmstudio_probe.json",
            {"live": bool(live), "models": models, "selected_model": model, "reply_attempts": reply.attempts},
        )
        _append_jsonl(
            run_dir / "transcript.jsonl",
            [
                {"event": "messages", "messages": model_messages},
                {"event": "model_reply", "raw_text": reply.raw_text, "parsed": reply.parsed, "attempts": reply.attempts},
            ],
        )
        model_metrics = evaluate_model_reply(reply.parsed)
        metrics: dict[str, Any] = {
            "live": bool(live),
            "model": model,
            "default_no_scope_omits_context_pass": "work_session_context" not in default_package,
            "degraded_scope_omits_context_pass": "work_session_context" not in degraded_package,
            "same_session_injection_pass": "work_session_context" in same_session_package,
            "cross_session_strict_scope_resume_pass": "work_session_context" in other_session_default,
            "explicit_resume_pass": "work_session_context" in explicit_resume_package,
            "truth_isolation_pass": bool(truth_isolation_pass),
            "observed_default_tokens": estimate_context_tokens(default_package),
            "observed_explicit_resume_tokens": estimate_context_tokens(explicit_resume_package),
            **diet_metrics,
            **model_metrics,
        }
        pass_keys = [key for key, value in metrics.items() if key.endswith("_pass") and isinstance(value, bool)]
        passed = bool(pass_keys) and all(bool(metrics[key]) for key in pass_keys)
        metrics["overall_pass"] = passed
        _write_json(run_dir / "metrics.json", metrics)
        _write_verdict(run_dir / "verdict.md", passed=passed, metrics=metrics, model_reply=reply)
        artifacts = {
            "metrics": str(run_dir / "metrics.json"),
            "verdict": str(run_dir / "verdict.md"),
            "transcript": str(run_dir / "transcript.jsonl"),
            "probe": str(run_dir / "lmstudio_probe.json"),
        }
        return HarnessResult(passed=passed, model=model, run_root=run_dir, metrics=metrics, artifacts=artifacts)
    finally:
        runtime.close()


def resume_state_from_work_context(work_context: dict[str, Any]) -> dict[str, Any]:
    state = {"next_action": "", "current_files": [], "blockers": [], "needed_refs": []}
    for item in list(work_context.get("items") or []):
        if not isinstance(item, dict):
            continue
        for part in str(item.get("summary") or "").split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "next_action":
                state["next_action"] = value
            elif key == "current_files":
                state["current_files"] = [part.strip() for part in value.split(",") if part.strip()]
            elif key == "blockers":
                state["blockers"] = [part.strip() for part in value.split(",") if part.strip()]
            elif key == "needed_refs":
                state["needed_refs"] = [part.strip() for part in value.split(",") if part.strip()]
    return state


def evaluate_model_reply(parsed: dict[str, Any]) -> dict[str, Any]:
    next_action = str(parsed.get("next_action") or "").strip()
    current_files = _as_string_list(parsed.get("current_files"))
    blockers = _as_string_list(parsed.get("blockers"))
    needed_refs = _as_string_list(parsed.get("needed_refs"))
    rereads = _as_string_list(parsed.get("reread_requests"))
    model_resume_fidelity = (
        next_action == EXPECTED_STATE["next_action"]
        and set(EXPECTED_STATE["current_files"]).issubset(set(current_files))
        and blockers == EXPECTED_STATE["blockers"]
        and set(EXPECTED_STATE["needed_refs"]).issubset(set(needed_refs))
    )
    return {
        "model_reply_parse_pass": bool(parsed),
        "model_resume_fidelity_pass": bool(model_resume_fidelity),
        "model_truth_isolation_pass": not bool(parsed.get("memory_claim"))
        and not bool(parsed.get("scratchpad_as_evidence")),
        "model_reread_avoidance_pass": not rereads,
    }


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        compact = value.strip()
        if not compact:
            return []
        return [part.strip() for part in compact.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _model_messages(package: dict[str, Any]) -> list[dict[str, str]]:
    content = {
        "instruction": (
            "Use work_session_context only as non-authoritative helper state. "
            "Do not claim durable memory from it. Answer with exactly one JSON object."
        ),
        "required_json_keys": [
            "next_action",
            "current_files",
            "blockers",
            "needed_refs",
            "memory_claim",
            "scratchpad_as_evidence",
            "reread_requests",
            "confidence",
        ],
        "expected_semantics": {
            "memory_claim": "false unless ltm_evidence supports a durable memory claim",
            "scratchpad_as_evidence": "false; scratchpad is not evidence",
            "reread_requests": "empty if the context package is enough to resume",
        },
        "context_package": package,
    }
    return [
        {
            "role": "system",
            "content": "You are validating MNO WSS resume context. Return strict JSON only.",
        },
        {"role": "user", "content": json.dumps(content, ensure_ascii=True, sort_keys=True)},
    ]


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    if raw.startswith("{") and raw.endswith("}"):
        candidates.append(raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _ensure_project_runtime_child(project: Path, run_root: Path) -> Path:
    runtime = (project / "runtime").resolve()
    try:
        run_root.relative_to(runtime)
    except ValueError as exc:
        raise ValueError(f"run root must stay inside project runtime: {runtime}") from exc
    return run_root


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def _write_verdict(path: Path, *, passed: bool, metrics: dict[str, Any], model_reply: ModelReply) -> None:
    lines = [
        "# WSS Live Harness Verdict",
        "",
        f"- verdict: {'PASS' if passed else 'FAIL'}",
        f"- model: {metrics.get('model')}",
        f"- live: {metrics.get('live')}",
        f"- model_reply_attempts: {model_reply.attempts}",
        "",
        "## Gates",
    ]
    for key in sorted(metrics):
        if key.endswith("_pass"):
            lines.append(f"- {key}: {metrics[key]}")
    lines.extend(
        [
            "",
            "## Notes",
            "- work_session_context is treated as non-authoritative scratchpad_ephemeral helper state.",
            "- This harness does not mutate MemoryPack, atom/review/publish/verify truth paths, integration-v1, desktop UI, or prompt history.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _default_run_root(project_root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return project_root / "runtime" / "wss_live_harness" / "runs" / stamp


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run the MNO WSS live LM Studio harness.")
    parser.add_argument("--project-root", default=str(repo_root))
    parser.add_argument("--run-root", default="")
    parser.add_argument("--lmstudio-url", default="http://localhost:1234")
    parser.add_argument("--model", default="auto")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--no-live", action="store_true", help="Use the built-in static JSON model client.")
    args = parser.parse_args(argv)

    project = Path(args.project_root).expanduser().resolve()
    run_root = Path(args.run_root).expanduser().resolve() if args.run_root else _default_run_root(project).resolve()
    client: ModelClient = StaticJsonModelClient() if args.no_live else LMStudioClient(args.lmstudio_url)
    try:
        result = run_harness(
            project_root=project,
            run_root=run_root,
            model_client=client,
            requested_model=args.model,
            live=not args.no_live,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout_s=args.timeout_s,
        )
    except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError) as exc:
        run_root.mkdir(parents=True, exist_ok=True)
        _write_json(run_root / "metrics.json", {"overall_pass": False, "error": str(exc)})
        _write_verdict(
            run_root / "verdict.md",
            passed=False,
            metrics={"model": args.model, "live": not args.no_live, "overall_pass": False, "harness_execution_pass": False},
            model_reply=ModelReply(raw_text="", parsed={}, attempts=0),
        )
        print(f"WSS live harness failed before verdict gates: {exc}", file=sys.stderr)
        print(f"verdict={run_root / 'verdict.md'}")
        return 2
    print(f"passed={result.passed}")
    print(f"model={result.model}")
    print(f"verdict={result.artifacts['verdict']}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
