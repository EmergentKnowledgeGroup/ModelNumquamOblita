#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PATHS = [
    REPO_ROOT / "engine" / "research",
    REPO_ROOT / "engine" / "runtime" / "ano_incremental.py",
    REPO_ROOT / "tools" / "run_document_research_real_corpus_eval.py",
    REPO_ROOT / "tools" / "run_wikipedia_scale_sweep.py",
    REPO_ROOT / "tools" / "run_wikipedia_dump_connector_eval.py",
    REPO_ROOT / "tools" / "run_with_scale_supervisor.py",
    REPO_ROOT / "tools" / "scale_safety_artifact_gate.py",
    REPO_ROOT / "tools" / "scale_qualification_config_gate.py",
    REPO_ROOT / "tools" / "scale_operability_gate.py",
]

CODE_SCAN_ROOTS = [
    REPO_ROOT / "engine",
    REPO_ROOT / "tools",
    REPO_ROOT / "tests",
]

CODE_SCAN_ALLOWLIST = {
    REPO_ROOT / "tools" / "audit_standalone_boundary.py",
    REPO_ROOT / "tests" / "unit" / "test_standalone_mno_boundary.py",
}

FORBIDDEN_CODE_TOKENS = [
    "DocumentResearchLibrary",
    "AnoIncrementalManager",
    "/api/ano/",
    "run_document_research_real_corpus_eval",
    "run_wikipedia_scale_sweep",
    "run_wikipedia_dump_connector_eval",
    "run_with_scale_supervisor",
    "scale_safety_artifact_gate",
    "scale_qualification_config_gate",
    "scale_operability_gate",
    "engine/research",
]

ACTIVE_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "INDEX.md",
    REPO_ROOT / "docs" / "SYSTEM_MASTER_OVERVIEW.md",
    REPO_ROOT / "docs" / "OPERATOR_SETUP_AND_DIAGNOSTICS.md",
    REPO_ROOT / "docs" / "guides" / "PIPELINE_END_TO_END.md",
    REPO_ROOT / "docs" / "guides" / "MONOREPO_TO_STANDALONE_MIGRATION.md",
]

FORBIDDEN_ACTIVE_DOC_TOKENS = [
    "DocumentResearchLibrary",
    "AnoIncrementalManager",
    "/api/ano/",
    "run_document_research_real_corpus_eval",
    "run_wikipedia_scale_sweep",
    "run_wikipedia_dump_connector_eval",
    "run_with_scale_supervisor",
    "scale_safety_artifact_gate",
    "scale_qualification_config_gate",
    "scale_operability_gate",
]

REQUIRED_DOCS = {
    "ownership_inventory": REPO_ROOT / "docs" / "MNO_ANO_OWNERSHIP_INVENTORY.md",
    "compatibility_matrix": REPO_ROOT / "docs" / "MNO_ANO_COMPATIBILITY_MATRIX.md",
    "migration_guide": REPO_ROOT / "docs" / "guides" / "MONOREPO_TO_STANDALONE_MIGRATION.md",
}

REQUIRED_DOC_PHRASES = {
    "ownership_inventory": [
        "## Repo Roots",
        "## Current Ownership Map",
        "## Mixed Surfaces Resolved For Standalone MNO",
        "## External Blockers Still Outside This Repo",
    ],
    "compatibility_matrix": [
        "## Canonical Policy",
        "## Supported Pairs",
        "## Stop-Ship Rules",
        "## Update Rules",
    ],
    "migration_guide": [
        "## Data Path Continuity",
        "## Repo Authority And Fallback",
        "## What Not To Do",
    ],
}


def _scan_paths(paths: Iterable[Path]) -> list[str]:
    found: list[str] = []
    for path in paths:
        if path.exists():
            found.append(str(path.relative_to(REPO_ROOT)))
    return found


def _iter_source_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return (
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".md", ".html", ".js", ".toml"}
    )


def _scan_tokens(paths: Iterable[Path], *, forbidden_tokens: list[str], allowlist: set[Path] | None = None) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    allow = allowlist or set()
    for path in paths:
        if path in allow or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                hits.append({"path": str(path.relative_to(REPO_ROOT)), "token": token})
    return hits


def _validate_required_docs() -> tuple[list[str], list[str]]:
    failures: list[str] = []
    missing_local_docs: list[str] = []
    for key, path in REQUIRED_DOCS.items():
        if not path.is_file():
            missing_local_docs.append(str(path.relative_to(REPO_ROOT)))
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in REQUIRED_DOC_PHRASES.get(key, []):
            if phrase not in text:
                failures.append(f"missing_required_phrase:{path.relative_to(REPO_ROOT)}:{phrase}")
    return failures, missing_local_docs


def _run_import_probe() -> dict[str, object]:
    code = (
        "import importlib.util; "
        "import engine; "
        "import engine.runtime.server; "
        "assert importlib.util.find_spec('engine.research') is None"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return {
        "returncode": int(proc.returncode),
        "stdout": str(proc.stdout or ""),
        "stderr": str(proc.stderr or ""),
        "ok": proc.returncode == 0,
    }


def run_audit() -> dict[str, object]:
    forbidden_paths_present = _scan_paths(FORBIDDEN_PATHS)
    code_hits = _scan_tokens(
        (path for root in CODE_SCAN_ROOTS for path in _iter_source_files(root)),
        forbidden_tokens=FORBIDDEN_CODE_TOKENS,
        allowlist=CODE_SCAN_ALLOWLIST,
    )
    active_doc_hits = _scan_tokens(
        ACTIVE_DOCS,
        forbidden_tokens=FORBIDDEN_ACTIVE_DOC_TOKENS,
    )
    required_doc_failures, missing_local_docs = _validate_required_docs()
    import_probe = _run_import_probe()

    failures: list[str] = []
    failures.extend(f"forbidden_path_present:{item}" for item in forbidden_paths_present)
    failures.extend(f"forbidden_code_token:{item['path']}:{item['token']}" for item in code_hits)
    failures.extend(f"forbidden_active_doc_token:{item['path']}:{item['token']}" for item in active_doc_hits)
    failures.extend(required_doc_failures)
    if not bool(import_probe.get("ok")):
        failures.append("import_probe_failed")

    return {
        "repo_root": str(REPO_ROOT),
        "decision": "PASS" if not failures else "FAIL",
        "forbidden_paths_present": forbidden_paths_present,
        "forbidden_code_hits": code_hits,
        "forbidden_active_doc_hits": active_doc_hits,
        "required_doc_failures": required_doc_failures,
        "missing_local_docs": missing_local_docs,
        "import_probe": import_probe,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the standalone MNO repo boundary against ANO residue.")
    parser.add_argument("--json", action="store_true", help="Emit JSON payload instead of key=value output.")
    args = parser.parse_args()

    payload = run_audit()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"decision={payload['decision']}")
        print(f"repo_root={payload['repo_root']}")
        print(f"failure_count={len(list(payload['failures']))}")
        for item in list(payload["failures"]):
            print(f"failure={item}")
    return 0 if str(payload.get("decision") or "") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
