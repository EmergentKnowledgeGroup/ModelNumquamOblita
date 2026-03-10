from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_standalone_repo_excludes_ano_runtime_and_research_surfaces() -> None:
    forbidden_paths = [
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
    missing = [str(path.relative_to(REPO_ROOT)) for path in forbidden_paths if path.exists()]
    assert missing == []


def test_public_engine_exports_no_ano_symbols() -> None:
    init_text = (REPO_ROOT / "engine" / "__init__.py").read_text(encoding="utf-8")
    assert "DocumentResearchLibrary" not in init_text
    assert ".research" not in init_text


def test_runtime_server_and_ui_expose_no_ano_controls() -> None:
    server_text = (REPO_ROOT / "engine" / "runtime" / "server.py").read_text(encoding="utf-8")
    ui_html = (REPO_ROOT / "engine" / "runtime" / "ui" / "index.html").read_text(encoding="utf-8")
    ui_js = (REPO_ROOT / "engine" / "runtime" / "ui" / "app.js").read_text(encoding="utf-8")

    forbidden_tokens = [
        "AnoIncrementalManager",
        "/api/ano/",
        "anoPaths",
        "btnAnoRun",
        "btnAnoPreflight",
        "btnAnoRetryFailed",
        "btnAnoRefresh",
        "anoStatus",
        "anoPreflight",
        "anoActiveJobId",
    ]
    for token in forbidden_tokens:
        assert token not in server_text
        assert token not in ui_html
        assert token not in ui_js
