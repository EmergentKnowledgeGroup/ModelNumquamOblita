#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.memory import SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession
from engine.runtime.continuity_harness import run_continuity_harness, write_continuity_artifacts
from engine.runtime.drift import compare_eval_summaries, load_summary as load_eval_summary, write_drift_report
from engine.runtime.signoff_brief import render_signoff_brief
from engine.runtime.live_eval import (
    evaluate_truthset,
    generate_truthset,
    load_inmemory_store_from_json,
    load_truthset_jsonl,
    plan_live_eval_workload,
    write_live_eval_artifacts,
    write_truthset_jsonl,
)
from engine.runtime.load_harness import plan_load_workload, run_load_harness, write_load_artifacts


PROFILES = {
    "safe": {
        "p95_latency_ms_max": 6000.0,
        "load_p95_latency_ms_max": 6500.0,
        "min_eval_cases": 6,
        "min_supported_cases": 3,
        "min_unsupported_cases": 2,
        "min_load_turns": 4,
        "max_failed_turn_rate": 0.20,
        "min_decision_accuracy": 0.80,
        "min_retrieval_hit_rate": 0.80,
        "min_abstain_precision": 0.60,
        "min_episode_hit_rate": 0.0,
        "max_episode_false_recall_rate": 0.0,
        "max_routine_over_recall_rate": 0.05,
        "min_continuity_recall_rate": 0.75,
        "min_continuity_citation_rate": 0.60,
    },
    "strict": {
        "p95_latency_ms_max": 2500.0,
        "load_p95_latency_ms_max": 3000.0,
        "min_eval_cases": 20,
        "min_supported_cases": 10,
        "min_unsupported_cases": 5,
        "min_load_turns": 20,
        "max_failed_turn_rate": 0.10,
        "min_decision_accuracy": 0.90,
        "min_retrieval_hit_rate": 0.90,
        "min_abstain_precision": 0.80,
        "min_episode_hit_rate": 0.0,
        "max_episode_false_recall_rate": 0.0,
        "max_routine_over_recall_rate": 0.02,
        "min_continuity_recall_rate": 0.90,
        "min_continuity_citation_rate": 0.85,
    },
}


def _default_memory_path() -> Path:
    sqlite_default = REPO_ROOT / ".runtime" / "imports" / "atoms.sqlite3"
    if sqlite_default.exists():
        return sqlite_default
    imports_dir = REPO_ROOT / "runtime" / "imports"
    if imports_dir.exists():
        candidates = sorted(imports_dir.rglob("memories.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return sqlite_default


def _open_store(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return SqliteAtomStore(path), True
    if suffix == ".json":
        return load_inmemory_store_from_json(path), False
    raise ValueError(f"unsupported memories path: {path}")


def _parse_kv_lines(lines: list[str]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for line in lines:
        text = str(line or "").strip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            payload[key] = value
    return payload


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _acceptance_gate_reasons(acceptance_gate: dict[str, Any], *, readout_path: Path) -> list[str]:
    reasons: list[str] = []
    if not acceptance_gate:
        reasons.append("acceptance_gate_missing")
        return reasons

    missing = [
        field
        for field in ("decision", "safety_verdict", "human_quality_verdict")
        if not str(acceptance_gate.get(field) or "").strip()
    ]
    if missing:
        reasons.append(f"acceptance_gate_missing_fields:{','.join(sorted(missing))}")
        return reasons

    quality = acceptance_gate.get("quality") if isinstance(acceptance_gate.get("quality"), dict) else {}
    if "defect_case_count" not in quality:
        reasons.append("acceptance_gate_quality_missing:defect_case_count")
    if "top_failure_examples" not in quality:
        reasons.append("acceptance_gate_quality_missing:top_failure_examples")
    if not readout_path.exists():
        reasons.append("human_readout_missing")

    safety_verdict = str(acceptance_gate.get("safety_verdict") or "").strip().upper()
    human_quality_verdict = str(acceptance_gate.get("human_quality_verdict") or "").strip().upper()
    if safety_verdict != "PASS":
        reasons.append("safety_verdict_not_pass")
    if human_quality_verdict != "PASS":
        reasons.append("human_quality_verdict_not_pass")
    for failure in list(acceptance_gate.get("failures") or []):
        token = str(failure or "").strip()
        if token:
            reasons.append(f"acceptance_gate_failure:{token}")
    return reasons


def _question_quality_reasons(question_quality_summary: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not question_quality_summary:
        reasons.append("question_quality_summary_missing")
        return reasons
    decision = str(question_quality_summary.get("decision") or "").strip().upper()
    if decision != "PASS":
        reasons.append("question_quality_verdict_not_pass")
        if int(question_quality_summary.get("weak_cases") or 0) > 0:
            reasons.append("weak_question_cases_present")
        if int(question_quality_summary.get("blocking_defect_cases") or 0) > 0:
            reasons.append("blocking_question_defect_cases_present")
    return reasons


def _signoff_reasons(
    *,
    eval_summary: dict,
    load_summary: dict,
    limits: dict[str, float],
    acceptance_gate: dict[str, Any] | None = None,
    continuity_summary: dict[str, Any] | None = None,
    drift_decision: str | None = None,
) -> list[str]:
    reasons: list[str] = []

    required_eval_metrics = [
        "false_memory_rate",
        "episode_false_recall_rate",
        "episode_hit_rate",
        "episode_supported_cases",
        "citation_hit_rate",
        "decision_accuracy",
        "retrieval_hit_rate",
        "abstain_precision",
        "routine_over_recall_rate",
        "p95_latency_ms",
        "cases",
        "supported_cases",
        "unsupported_cases",
    ]
    required_load_metrics = ["latency_p95_ms", "turns", "failed_turns", "atoms"]
    missing_eval = [metric for metric in required_eval_metrics if metric not in eval_summary]
    missing_load = [metric for metric in required_load_metrics if metric not in load_summary]
    if missing_eval:
        reasons.append(f"eval_summary_missing_metrics:{','.join(sorted(missing_eval))}")
    if missing_load:
        reasons.append(f"load_summary_missing_metrics:{','.join(sorted(missing_load))}")
    if missing_eval or missing_load:
        return reasons

    load_turns = int(load_summary.get("turns") or 0)
    if load_turns <= 0:
        reasons.append("load_summary_no_turns")
        return reasons
    load_atoms = int(load_summary.get("atoms") or 0)
    if load_atoms <= 0:
        reasons.append("load_summary_no_atoms")
        return reasons

    eval_cases = int(eval_summary.get("cases") or 0)
    supported_cases = int(eval_summary.get("supported_cases") or 0)
    unsupported_cases = int(eval_summary.get("unsupported_cases") or 0)
    failed_turns = int(load_summary.get("failed_turns") or 0)
    total_attempted_turns = load_turns + failed_turns
    failed_turn_rate = (float(failed_turns) / float(total_attempted_turns)) if total_attempted_turns > 0 else 1.0

    if eval_cases < int(limits["min_eval_cases"]):
        reasons.append("eval_case_coverage_insufficient")
    if supported_cases < int(limits["min_supported_cases"]):
        reasons.append("eval_supported_case_coverage_insufficient")
    if unsupported_cases < int(limits["min_unsupported_cases"]):
        reasons.append("eval_unsupported_case_coverage_insufficient")
    if load_turns < int(limits["min_load_turns"]):
        reasons.append("load_turn_coverage_insufficient")
    if total_attempted_turns > 0 and failed_turn_rate > float(limits["max_failed_turn_rate"]):
        reasons.append("load_failed_turn_rate_exceeded")
    if reasons:
        return reasons

    gate_metrics = acceptance_gate.get("metrics") if isinstance(acceptance_gate, dict) else {}

    def _metric(name: str) -> float:
        if isinstance(gate_metrics, dict) and name in gate_metrics:
            return float(gate_metrics.get(name) or 0.0)
        if name == "latency_p95_ms":
            return float(eval_summary.get("latency_p95_ms", eval_summary.get("p95_latency_ms")) or 0.0)
        return float(eval_summary.get(name) or 0.0)

    if _metric("false_memory_rate") > 0.02:
        reasons.append("false_memory_rate_exceeded")
    episode_false_recall_rate = _metric("episode_false_recall_rate")
    if episode_false_recall_rate > float(limits["max_episode_false_recall_rate"]):
        reasons.append("episode_false_recall_rate_exceeded")
    routine_over_recall_rate = _metric("routine_over_recall_rate")
    if routine_over_recall_rate <= 0.0:
        routine_over_recall_rate = float(eval_summary.get("over_recall_rate") or 0.0)
    if routine_over_recall_rate > float(limits["max_routine_over_recall_rate"]):
        reasons.append("routine_over_recall_rate_exceeded")
    episode_supported_cases = int(eval_summary.get("episode_supported_cases") or 0)
    if episode_supported_cases > 0:
        episode_hit_rate = _metric("episode_hit_rate")
        if episode_hit_rate < float(limits["min_episode_hit_rate"]):
            reasons.append("episode_hit_rate_below_floor")
    if _metric("citation_hit_rate") < 0.98:
        reasons.append("citation_hit_rate_below_floor")
    if _metric("decision_accuracy") < float(limits["min_decision_accuracy"]):
        reasons.append("decision_accuracy_below_floor")
    if _metric("retrieval_hit_rate") < float(limits["min_retrieval_hit_rate"]):
        reasons.append("retrieval_hit_rate_below_floor")
    if unsupported_cases > 0 and _metric("abstain_precision") < float(limits["min_abstain_precision"]):
        reasons.append("abstain_precision_below_floor")
    if _metric("latency_p95_ms") > float(limits["p95_latency_ms_max"]):
        reasons.append("eval_p95_latency_exceeded")
    if float(load_summary.get("latency_p95_ms") or 0.0) > float(limits["load_p95_latency_ms_max"]):
        reasons.append("load_p95_latency_exceeded")
    if continuity_summary is not None:
        checks = int(continuity_summary.get("checks") or 0)
        if checks < 2:
            reasons.append("continuity_coverage_insufficient")
        else:
            if float(continuity_summary.get("recall_rate") or 0.0) < float(limits["min_continuity_recall_rate"]):
                reasons.append("continuity_recall_rate_below_floor")
            if float(continuity_summary.get("citation_rate") or 0.0) < float(limits["min_continuity_citation_rate"]):
                reasons.append("continuity_citation_rate_below_floor")
    if drift_decision and str(drift_decision).strip().upper() == "FAIL":
        reasons.append("eval_drift_regression")
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 7 signoff: truthset eval + load harness + optional drift.")
    parser.add_argument("--memories", default=str(_default_memory_path()), help="Path to sqlite store or memories.json")
    parser.add_argument("--truthset", default="", help="Optional truthset.jsonl")
    parser.add_argument("--out-dir", default="", help="Output directory")
    parser.add_argument("--eval-cases", type=int, default=120)
    parser.add_argument("--load-turns", type=int, default=40)
    parser.add_argument("--scan-budget", type=int, default=600000)
    parser.add_argument("--readout-max-cases", type=int, default=24, help="Maximum cases rendered in judged eval readout.")
    parser.add_argument(
        "--fixture-mode",
        choices=["basic", "trust-v2", "trust-v3"],
        default="trust-v3",
        help="Fixture family generation mode when auto-generating truthset.",
    )
    parser.add_argument("--disable-episodes", action="store_true", help="Disable episode-card retrieval during judged eval.")
    parser.add_argument("--episode-cards", default="", help="Optional episode_cards json path to use during judged eval.")
    parser.add_argument("--skip-episode-build", action="store_true", help="Forward-compatible no-op for oneclick parity.")
    parser.add_argument("--responder-provider", default="mock", choices=["mock", "lmstudio", "openai"])
    parser.add_argument("--responder-provider-base-url", default="http://127.0.0.1:1234")
    parser.add_argument("--responder-provider-chat-path", default="/api/v1/chat")
    parser.add_argument("--responder-model", default="qwen/qwen3-32b")
    parser.add_argument("--responder-openai-api-key", default="")
    parser.add_argument("--responder-openai-base-url", default="https://api.openai.com")
    parser.add_argument("--responder-timeout-s", type=float, default=60.0)
    parser.add_argument("--max-weak-question-cases", type=int, default=0)
    parser.add_argument("--continuity-turns", type=int, default=12, help="Number of turns for long-thread continuity harness.")
    parser.add_argument("--continuity-interval", type=int, default=4, help="Run one continuity recall probe every N turns.")
    parser.add_argument("--skip-continuity-harness", action="store_true", help="Skip continuity harness checks.")
    parser.add_argument("--profile", choices=sorted(PROFILES.keys()), default="safe")
    parser.add_argument("--min-eval-cases", type=int, default=None, help="Override minimum eval cases gate.")
    parser.add_argument(
        "--min-supported-cases",
        type=int,
        default=None,
        help="Override minimum supported recall cases gate.",
    )
    parser.add_argument(
        "--min-unsupported-cases",
        type=int,
        default=None,
        help="Override minimum unsupported trap cases gate.",
    )
    parser.add_argument("--min-load-turns", type=int, default=None, help="Override minimum successful load turns gate.")
    parser.add_argument(
        "--max-failed-turn-rate",
        type=float,
        default=None,
        help="Override maximum tolerated failed-turn ratio for load harness.",
    )
    parser.add_argument(
        "--min-decision-accuracy",
        type=float,
        default=None,
        help="Override minimum decision_accuracy gate.",
    )
    parser.add_argument(
        "--min-retrieval-hit-rate",
        type=float,
        default=None,
        help="Override minimum retrieval_hit_rate gate.",
    )
    parser.add_argument(
        "--min-abstain-precision",
        type=float,
        default=None,
        help="Override minimum abstain_precision gate.",
    )
    parser.add_argument(
        "--min-episode-hit-rate",
        type=float,
        default=None,
        help="Override minimum episode_hit_rate gate (applies only when episode_supported_cases > 0).",
    )
    parser.add_argument(
        "--max-episode-false-recall-rate",
        type=float,
        default=None,
        help="Override maximum episode_false_recall_rate gate.",
    )
    parser.add_argument(
        "--max-routine-over-recall-rate",
        type=float,
        default=None,
        help="Override maximum routine_over_recall_rate gate.",
    )
    parser.add_argument(
        "--min-continuity-recall-rate",
        type=float,
        default=None,
        help="Override minimum continuity recall_rate gate.",
    )
    parser.add_argument(
        "--min-continuity-citation-rate",
        type=float,
        default=None,
        help="Override minimum continuity citation_rate gate.",
    )
    parser.add_argument(
        "--max-eval-p95-latency-ms",
        type=float,
        default=None,
        help="Override maximum eval p95 latency gate (ms).",
    )
    parser.add_argument(
        "--max-load-p95-latency-ms",
        type=float,
        default=None,
        help="Override maximum load p95 latency gate (ms).",
    )
    parser.add_argument("--drift-baseline", default="", help="Optional prior eval summary.json for drift diff")
    parser.add_argument(
        "--require-trust-regression-gate",
        action="store_true",
        help="Fail early if --drift-baseline is missing.",
    )
    parser.add_argument("--fail-on-gate", action="store_true", help="Exit non-zero when signoff decision is FAIL")
    args = parser.parse_args()

    memories_path = Path(args.memories).expanduser().resolve()
    if not memories_path.exists():
        print(f"error=memories path not found: {memories_path}")
        return 2
    if args.require_trust_regression_gate and not str(args.drift_baseline or "").strip():
        print("error=trust regression gate required but --drift-baseline is missing")
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else REPO_ROOT / "runtime" / "evals" / f"signoff_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    limits = dict(PROFILES[args.profile])
    if args.min_eval_cases is not None:
        limits["min_eval_cases"] = float(max(0, args.min_eval_cases))
    if args.min_supported_cases is not None:
        limits["min_supported_cases"] = float(max(0, args.min_supported_cases))
    if args.min_unsupported_cases is not None:
        limits["min_unsupported_cases"] = float(max(0, args.min_unsupported_cases))
    if args.min_load_turns is not None:
        limits["min_load_turns"] = float(max(0, args.min_load_turns))
    if args.max_failed_turn_rate is not None:
        limits["max_failed_turn_rate"] = min(1.0, max(0.0, float(args.max_failed_turn_rate)))
    if args.min_decision_accuracy is not None:
        limits["min_decision_accuracy"] = min(1.0, max(0.0, float(args.min_decision_accuracy)))
    if args.min_retrieval_hit_rate is not None:
        limits["min_retrieval_hit_rate"] = min(1.0, max(0.0, float(args.min_retrieval_hit_rate)))
    if args.min_abstain_precision is not None:
        limits["min_abstain_precision"] = min(1.0, max(0.0, float(args.min_abstain_precision)))
    if args.min_episode_hit_rate is not None:
        limits["min_episode_hit_rate"] = min(1.0, max(0.0, float(args.min_episode_hit_rate)))
    if args.max_episode_false_recall_rate is not None:
        limits["max_episode_false_recall_rate"] = min(1.0, max(0.0, float(args.max_episode_false_recall_rate)))
    if args.max_routine_over_recall_rate is not None:
        limits["max_routine_over_recall_rate"] = min(1.0, max(0.0, float(args.max_routine_over_recall_rate)))
    if args.min_continuity_recall_rate is not None:
        limits["min_continuity_recall_rate"] = min(1.0, max(0.0, float(args.min_continuity_recall_rate)))
    if args.min_continuity_citation_rate is not None:
        limits["min_continuity_citation_rate"] = min(1.0, max(0.0, float(args.min_continuity_citation_rate)))
    if args.max_eval_p95_latency_ms is not None:
        limits["p95_latency_ms_max"] = max(0.0, float(args.max_eval_p95_latency_ms))
    if args.max_load_p95_latency_ms is not None:
        limits["load_p95_latency_ms_max"] = max(0.0, float(args.max_load_p95_latency_ms))

    store, close_store = _open_store(memories_path)
    try:
        atoms = store.list_atoms()
        atom_count = len(atoms)

        continuity = ContinuityStore()
        shared_language_keys = store.list_shared_language_keys() if hasattr(store, "list_shared_language_keys") else []
        continuity.set_snapshot(
            ContinuityBuilder().build(atoms, shared_language_keys=shared_language_keys)
        )

        # Eval track
        eval_plan = plan_live_eval_workload(
            atom_count=atom_count,
            requested_cases=int(args.eval_cases),
            scan_budget=int(args.scan_budget),
        )
        if args.truthset:
            eval_cases = load_truthset_jsonl(Path(args.truthset).expanduser().resolve())
        else:
            eval_cases = generate_truthset(
                store,
                total_cases=eval_plan.effective_cases,
                fixture_mode=str(args.fixture_mode),
            )
        eval_cases = eval_cases[: eval_plan.effective_cases]
        requested_eval_cases = len(eval_cases)
        truthset_generated_path = out_dir / "truthset.generated.jsonl"
        write_truthset_jsonl(eval_cases, truthset_generated_path)

        runtime_eval = RuntimeSession(
            retriever=MemoryRetriever(store),
            verifier=ClaimVerifier(),
            continuity_store=continuity,
            enable_writeback=False,
            short_term_enabled=False,
        )
        try:
            eval_summary_obj, eval_records = evaluate_truthset(
                runtime_eval,
                eval_cases,
                atoms=eval_plan.atoms,
                requested_cases=requested_eval_cases,
                scan_budget=eval_plan.scan_budget,
            )
        finally:
            runtime_eval.close()
        eval_summary_json, eval_summary_md, eval_records_json = write_live_eval_artifacts(
            out_dir=out_dir / "eval",
            summary=eval_summary_obj,
            records=eval_records,
        )

        judged_eval_dir = out_dir / "judged_eval"
        judged_eval_cmd = [
            sys.executable,
            str(REPO_ROOT / "tools" / "run_oneclick_eval.py"),
            "--skip-import",
            "--store",
            str(memories_path),
            "--truthset",
            str(truthset_generated_path),
            "--run-dir",
            str(judged_eval_dir),
            "--requested-cases",
            str(max(1, requested_eval_cases)),
            "--scan-budget",
            str(max(1, int(args.scan_budget))),
            "--fixture-mode",
            str(args.fixture_mode),
            "--readout-max-cases",
            str(max(1, int(args.readout_max_cases))),
            "--responder-provider",
            str(args.responder_provider),
            "--responder-provider-base-url",
            str(args.responder_provider_base_url),
            "--responder-provider-chat-path",
            str(args.responder_provider_chat_path),
            "--responder-model",
            str(args.responder_model),
            "--responder-openai-api-key",
            str(args.responder_openai_api_key),
            "--responder-openai-base-url",
            str(args.responder_openai_base_url),
            "--responder-timeout-s",
            str(float(args.responder_timeout_s)),
            "--max-weak-question-cases",
            str(max(0, int(args.max_weak_question_cases))),
            "--min-decision-accuracy",
            str(float(limits["min_decision_accuracy"])),
            "--min-retrieval-hit-rate",
            str(float(limits["min_retrieval_hit_rate"])),
            "--min-abstain-precision",
            str(float(limits["min_abstain_precision"])),
            "--max-routine-over-recall-rate",
            str(float(limits["max_routine_over_recall_rate"])),
            "--max-total-p95-ms",
            str(float(limits["p95_latency_ms_max"])),
        ]
        if args.disable_episodes:
            judged_eval_cmd.append("--disable-episodes")
        elif str(args.episode_cards).strip():
            judged_eval_cmd.extend(["--episode-cards", str(Path(args.episode_cards).expanduser().resolve())])
        if args.skip_episode_build:
            judged_eval_cmd.append("--skip-episode-build")
        judged_eval_result = subprocess.run(
            judged_eval_cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        judged_eval_outputs = _parse_kv_lines(str(judged_eval_result.stdout or "").splitlines())
        judged_eval_manifest = Path(
            judged_eval_outputs.get("manifest", str(judged_eval_dir / "oneclick_manifest.json"))
        ).resolve()
        acceptance_gate_json = Path(
            judged_eval_outputs.get("acceptance_gate_json", str(judged_eval_dir / "eval" / "acceptance_gate.json"))
        ).resolve()
        human_readout_md = Path(
            judged_eval_outputs.get("human_readout_md", str(judged_eval_dir / "eval" / "human_readout.md"))
        ).resolve()
        question_quality_summary_json = Path(
            judged_eval_outputs.get(
                "question_validation_summary_json",
                str((judged_eval_dir / "question_quality" / "question_validation_summary.json").resolve()),
            )
        ).resolve()

        # Load track
        runtime_load = RuntimeSession(
            retriever=MemoryRetriever(store),
            verifier=ClaimVerifier(),
            continuity_store=continuity,
            enable_writeback=False,
            short_term_enabled=False,
        )
        load_plan = plan_load_workload(
            atom_count=atom_count,
            requested_turns=int(args.load_turns),
            scan_budget=int(args.scan_budget),
        )
        try:
            load_summary_obj, load_samples = run_load_harness(
                runtime_load,
                store,
                requested_turns=load_plan.effective_turns,
                scan_budget=load_plan.scan_budget,
            )
        finally:
            runtime_load.close()
        load_summary_json, load_summary_md, load_samples_json = write_load_artifacts(
            out_dir=out_dir / "load",
            summary=load_summary_obj,
            samples=load_samples,
        )

        continuity_summary_json = ""
        continuity_summary_md = ""
        continuity_checks_json = ""
        continuity_summary_data: dict[str, Any] | None = None
        if not args.skip_continuity_harness:
            runtime_continuity = RuntimeSession(
                retriever=MemoryRetriever(store),
                verifier=ClaimVerifier(),
                continuity_store=continuity,
                enable_writeback=False,
                short_term_enabled=True,
            )
            try:
                continuity_summary_obj, continuity_checks = run_continuity_harness(
                    runtime_continuity,
                    store,
                    turns=max(0, int(args.continuity_turns)),
                    recall_interval=max(1, int(args.continuity_interval)),
                    fixture_mode=str(args.fixture_mode),
                )
            finally:
                runtime_continuity.close()
            continuity_summary_path, continuity_summary_md_path, continuity_checks_path = write_continuity_artifacts(
                out_dir=out_dir / "continuity",
                summary=continuity_summary_obj,
                checks=continuity_checks,
            )
            continuity_summary_json = str(continuity_summary_path)
            continuity_summary_md = str(continuity_summary_md_path)
            continuity_checks_json = str(continuity_checks_path)
            continuity_summary_data = continuity_summary_obj.to_dict()

        drift_json = ""
        drift_md = ""
        drift_decision = ""
        trust_regression_enabled = bool(str(args.drift_baseline or "").strip())
        if args.drift_baseline:
            baseline_path = Path(args.drift_baseline).expanduser().resolve()
            baseline = load_eval_summary(baseline_path)
            candidate = json.loads(eval_summary_json.read_text(encoding="utf-8"))
            drift = compare_eval_summaries(baseline=baseline, candidate=candidate)
            drift_json_path, drift_md_path = write_drift_report(
                out_dir=out_dir / "drift",
                report=drift,
                baseline_path=baseline_path,
                candidate_path=eval_summary_json,
            )
            drift_json = str(drift_json_path)
            drift_md = str(drift_md_path)
            drift_decision = str(drift.decision)

        eval_summary = json.loads(eval_summary_json.read_text(encoding="utf-8"))
        load_summary_data = json.loads(load_summary_json.read_text(encoding="utf-8"))
        acceptance_gate = _load_json_if_exists(acceptance_gate_json)
        question_quality_summary = _load_json_if_exists(question_quality_summary_json)
        reasons = _signoff_reasons(
            eval_summary=eval_summary,
            load_summary=load_summary_data,
            limits=limits,
            acceptance_gate=acceptance_gate,
            continuity_summary=continuity_summary_data,
            drift_decision=drift_decision,
        )
        if judged_eval_result.returncode not in {0, 2, 3}:
            reasons.append(f"judged_eval_runner_failed:{judged_eval_result.returncode}")
        reasons.extend(_acceptance_gate_reasons(acceptance_gate, readout_path=human_readout_md))
        reasons.extend(_question_quality_reasons(question_quality_summary))
        reasons = list(dict.fromkeys(reasons))
        decision = "PASS" if not reasons else "FAIL"
        safety_verdict = str(acceptance_gate.get("safety_verdict") or "").strip().upper()
        human_quality_verdict = str(acceptance_gate.get("human_quality_verdict") or "").strip().upper()
        quality_payload = acceptance_gate.get("quality") if isinstance(acceptance_gate.get("quality"), dict) else {}

        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "profile": args.profile,
            "decision": decision,
            "safety_verdict": safety_verdict,
            "human_quality_verdict": human_quality_verdict,
            "reasons": reasons,
            "gates": limits,
            "memories_path": str(memories_path),
            "atom_count": atom_count,
            "eval": {
                "summary_json": str(eval_summary_json),
                "summary_md": str(eval_summary_md),
                "records_json": str(eval_records_json),
                "truthset_jsonl": str(truthset_generated_path),
            },
            "judged_eval": {
                "manifest_json": str(judged_eval_manifest),
                "acceptance_gate_json": str(acceptance_gate_json),
                "human_readout_md": str(human_readout_md),
                "question_quality_summary_json": str(question_quality_summary_json),
                "runner_returncode": int(judged_eval_result.returncode),
                "decision": str(acceptance_gate.get("decision") or "").strip(),
            },
            "load": {
                "summary_json": str(load_summary_json),
                "summary_md": str(load_summary_md),
                "samples_json": str(load_samples_json),
            },
            "continuity": {
                "summary_json": continuity_summary_json,
                "summary_md": continuity_summary_md,
                "checks_json": continuity_checks_json,
            },
            "drift": {
                "report_json": drift_json,
                "report_md": drift_md,
                "decision": drift_decision,
            },
            "trust_regression": {
                "required": bool(args.require_trust_regression_gate),
                "enabled": trust_regression_enabled,
                "decision": drift_decision or ("SKIP" if not trust_regression_enabled else "UNKNOWN"),
                "baseline": str(args.drift_baseline or ""),
                "report_json": drift_json,
                "report_md": drift_md,
            },
            "quality": {
                "defect_case_count": int(quality_payload.get("defect_case_count") or 0),
                "blocking_defect_cases": int(quality_payload.get("blocking_defect_cases") or 0),
                "top_failure_examples": list(quality_payload.get("top_failure_examples") or []),
            },
        }

        manifest_json = out_dir / "signoff_manifest.json"
        manifest_md = out_dir / "signoff_manifest.md"
        brief_md = out_dir / "signoff_brief.md"
        brief_txt = out_dir / "signoff_brief.txt"

        brief_markdown, brief_text = render_signoff_brief(
            decision=decision,
            profile=args.profile,
            reasons=reasons,
            eval_summary=eval_summary,
            load_summary=load_summary_data,
            safety_verdict=safety_verdict,
            human_quality_verdict=human_quality_verdict,
            quality_defect_case_count=int(quality_payload.get("defect_case_count") or 0),
        )
        brief_md.write_text(brief_markdown, encoding="utf-8")
        brief_txt.write_text(brief_text, encoding="utf-8")

        manifest["brief"] = {
            "markdown": str(brief_md),
            "text": str(brief_txt),
        }
        manifest_json.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        lines = [
            "# Phase 7 Signoff",
            "",
            f"- decision: `{decision}`",
            f"- safety_verdict: `{safety_verdict or 'UNKNOWN'}`",
            f"- human_quality_verdict: `{human_quality_verdict or 'UNKNOWN'}`",
            f"- profile: `{args.profile}`",
            f"- memories_path: `{memories_path}`",
            f"- atom_count: `{atom_count}`",
            f"- quality_defect_case_count: `{int(quality_payload.get('defect_case_count') or 0)}`",
            "",
            "## Gate thresholds",
            f"- min_eval_cases: `{int(limits['min_eval_cases'])}`",
            f"- min_supported_cases: `{int(limits['min_supported_cases'])}`",
            f"- min_unsupported_cases: `{int(limits['min_unsupported_cases'])}`",
            f"- min_load_turns: `{int(limits['min_load_turns'])}`",
            f"- max_failed_turn_rate: `{float(limits['max_failed_turn_rate']):.4f}`",
            f"- min_decision_accuracy: `{float(limits['min_decision_accuracy']):.2f}`",
            f"- min_retrieval_hit_rate: `{float(limits['min_retrieval_hit_rate']):.2f}`",
            f"- min_abstain_precision: `{float(limits['min_abstain_precision']):.2f}`",
            f"- min_episode_hit_rate: `{float(limits['min_episode_hit_rate']):.2f}`",
            f"- max_episode_false_recall_rate: `{float(limits['max_episode_false_recall_rate']):.4f}`",
            f"- max_routine_over_recall_rate: `{float(limits['max_routine_over_recall_rate']):.4f}`",
            f"- min_continuity_recall_rate: `{float(limits['min_continuity_recall_rate']):.2f}`",
            f"- min_continuity_citation_rate: `{float(limits['min_continuity_citation_rate']):.2f}`",
            "",
            "## Reasons",
        ]
        if reasons:
            lines.extend(f"- {reason}" for reason in reasons)
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "## Artifacts",
                f"- eval.summary_json: `{eval_summary_json}`",
                f"- eval.summary_md: `{eval_summary_md}`",
                f"- eval.truthset_jsonl: `{truthset_generated_path}`",
                f"- judged_eval.acceptance_gate_json: `{acceptance_gate_json}`",
                f"- judged_eval.human_readout_md: `{human_readout_md}`",
                f"- judged_eval.question_quality_summary_json: `{question_quality_summary_json}`",
                f"- load.summary_json: `{load_summary_json}`",
                f"- load.summary_md: `{load_summary_md}`",
                f"- continuity.summary_json: `{continuity_summary_json or '(not generated)'}`",
                f"- drift.report_json: `{drift_json or '(not generated)'}`",
                f"- trust_regression.required: `{bool(args.require_trust_regression_gate)}`",
                f"- trust_regression.decision: `{drift_decision or ('SKIP' if not trust_regression_enabled else 'UNKNOWN')}`",
                f"- brief.markdown: `{brief_md}`",
                f"- brief.text: `{brief_txt}`",
            ]
        )
        manifest_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

        print(f"decision={decision}")
        print(f"safety_verdict={safety_verdict or 'UNKNOWN'}")
        print(f"human_quality_verdict={human_quality_verdict or 'UNKNOWN'}")
        print(f"manifest_json={manifest_json}")
        print(f"manifest_md={manifest_md}")
        print(f"eval_summary_json={eval_summary_json}")
        print(f"load_summary_json={load_summary_json}")

        if args.fail_on_gate and decision != "PASS":
            return 2
        return 0
    finally:
        closer = getattr(store, "close", None)
        if callable(closer) and close_store:
            closer()


if __name__ == "__main__":
    raise SystemExit(main())
