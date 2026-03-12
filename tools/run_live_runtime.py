#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.continuity import ContinuityBuilder, ContinuityStore, SharedLanguageRegistry
from engine.memory import MutationReviewQueue, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, load_inmemory_store_from_json, start_runtime_server, stop_runtime_server


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


def _default_episode_cards_path() -> Path | None:
    episodes_dir = REPO_ROOT / "runtime" / "episodes"
    if not episodes_dir.exists():
        return None
    candidates = sorted(episodes_dir.glob("episode_cards_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    manual = episodes_dir / "episode_cards.json"
    if manual.exists():
        return manual
    return None


def _project_version() -> str:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except Exception:
        return "0.0.0"
    project = payload.get("project") if isinstance(payload, dict) else {}
    version = str((project or {}).get("version") or "").strip()
    return version or "0.0.0"


def _setup_mode_store_path(explicit: str = "") -> Path:
    if str(explicit or "").strip():
        return Path(explicit).expanduser().resolve()
    return (REPO_ROOT / "runtime" / "desktop_shell" / "setup_mode.sqlite3").resolve()


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest must be a JSON object")
    return payload


def _resolve_memories_path(*, memories: str, from_live_manifest: str) -> Path:
    if memories and from_live_manifest:
        raise ValueError("--memories and --from-live-manifest are mutually exclusive")

    if from_live_manifest:
        manifest_path = Path(from_live_manifest).expanduser().resolve()
        if not manifest_path.exists():
            raise ValueError(f"live manifest not found: {manifest_path}")
        payload = _load_manifest(manifest_path)
        store_path = str(payload.get("store_path") or "").strip()
        if not store_path:
            raise ValueError("live manifest missing required field: store_path")
        return Path(store_path).expanduser().resolve()

    if memories:
        return Path(memories).expanduser().resolve()
    return _default_memory_path().resolve()


def _open_store(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return SqliteAtomStore(path), "sqlite", True
    if suffix == ".json":
        return load_inmemory_store_from_json(path), "json", False
    raise ValueError(f"unsupported memories path: {path}")


def _store_backend_label(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".sqlite3", ".sqlite", ".db"}:
        return "sqlite"
    if suffix == ".json":
        return "json"
    raise ValueError(f"unsupported memories path: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch local runtime server against a real memory store.")
    parser.add_argument("--memories", default="", help="Path to sqlite store (.sqlite3/.db) or memories.json.")
    parser.add_argument(
        "--from-live-manifest",
        default="",
        help="Path to runtime/live_runs/live_*/live_manifest.json. Uses store_path from manifest.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7340)
    parser.add_argument("--model-name", default="numquam-oblita-runtime")
    parser.add_argument("--episodes", default="", help="Optional path to episode_cards JSON artifact.")
    parser.add_argument("--setup-mode", action="store_true", help="Start the runtime only for setup/wizard flows.")
    parser.add_argument("--setup-store", default="", help="Optional sqlite path to use for setup-mode runtime state.")
    parser.add_argument("--max-seconds", type=float, default=0.0, help="Auto-stop after N seconds (0 = run until Ctrl+C).")
    parser.add_argument("--plan-only", action="store_true", help="Validate inputs and print resolved launch config.")
    args = parser.parse_args()

    launch_mode = "setup_mode" if bool(args.setup_mode) else "normal"
    if args.setup_mode and (str(args.memories).strip() or str(args.from_live_manifest).strip()):
        print("error=--setup-mode cannot be combined with --memories or --from-live-manifest")
        return 2
    if args.setup_mode and str(args.episodes).strip():
        print("error=--setup-mode cannot be combined with --episodes")
        return 2

    if args.setup_mode:
        memories_path = _setup_mode_store_path(args.setup_store)
    else:
        try:
            memories_path = _resolve_memories_path(memories=args.memories, from_live_manifest=args.from_live_manifest)
        except ValueError as exc:
            print(f"error={exc}")
            return 2
        if not memories_path.exists():
            print(f"error=memories path not found: {memories_path}")
            return 2

    episode_cards_path = None if args.setup_mode else (Path(args.episodes).expanduser().resolve() if str(args.episodes).strip() else _default_episode_cards_path())
    if episode_cards_path is not None and not episode_cards_path.exists():
        print(f"error=episode cards path not found: {episode_cards_path}")
        return 2

    runtime_url = f"http://{args.host}:{int(args.port)}"
    if args.plan_only and args.setup_mode:
        print("mode=plan_only")
        print(f"launch_mode={launch_mode}")
        print(f"memories_path={memories_path}")
        print(f"store_backend={_store_backend_label(memories_path)}")
        print("atom_count=0")
        print(f"episode_cards_path={episode_cards_path if episode_cards_path is not None else ''}")
        print(f"runtime_url={runtime_url}")
        return 0

    if args.setup_mode:
        memories_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        store, backend_name, close_store = _open_store(memories_path)
    except ValueError as exc:
        print(f"error={exc}")
        return 2

    try:
        atoms = store.list_atoms()
        atom_count = len(atoms)
        if args.plan_only:
            print("mode=plan_only")
            print(f"launch_mode={launch_mode}")
            print(f"memories_path={memories_path}")
            print(f"store_backend={backend_name}")
            print(f"atom_count={atom_count}")
            print(f"episode_cards_path={episode_cards_path if episode_cards_path is not None else ''}")
            print(f"runtime_url={runtime_url}")
            return 0

        continuity = ContinuityStore()
        shared_language_keys = store.list_shared_language_keys() if hasattr(store, "list_shared_language_keys") else []
        continuity.set_snapshot(
            ContinuityBuilder().build(atoms, shared_language_keys=shared_language_keys)
        )
        runtime = RuntimeSession(
            retriever=MemoryRetriever(store),
            verifier=ClaimVerifier(),
            continuity_store=continuity,
            model_name=str(args.model_name).strip() or "numquam-oblita-runtime",
            episode_cards_path=str(episode_cards_path) if episode_cards_path is not None else None,
        )
        review_queue = MutationReviewQueue(store, default_retention_days=14)
        server, thread = start_runtime_server(
            runtime,
            host=str(args.host),
            port=int(args.port),
            review_queue=review_queue,
        )
        server.runtime_version = _project_version()
        server.runtime_launch_mode = launch_mode
        server.desktop_shutdown_requested = False
        server.active_runtime_binding = {
            **dict(getattr(server, "active_runtime_binding", {}) or {}),
            "store_path": str(memories_path.resolve()),
            "episodes_path": str(episode_cards_path.resolve()) if episode_cards_path is not None else "",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "backend": backend_name,
            "artifact_mode": "setup" if args.setup_mode else ("published" if episode_cards_path is not None else ""),
            "build_id": "",
        }
        host, port = server.server_address
        print(f"runtime_url=http://{host}:{port}")
        print(f"launch_mode={launch_mode}")
        print(f"memories_path={memories_path}")
        print(f"store_backend={backend_name}")
        print(f"atom_count={atom_count}")
        if episode_cards_path is not None:
            print(f"episode_cards_path={episode_cards_path}")
        print("Press Ctrl+C to stop.")

        max_seconds = max(0.0, float(args.max_seconds))
        started = time.monotonic()
        try:
            while True:
                if bool(getattr(server, "desktop_shutdown_requested", False)):
                    break
                if max_seconds > 0.0 and (time.monotonic() - started) >= max_seconds:
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            stop_runtime_server(server, thread, runtime=runtime)
        return 0
    finally:
        if close_store:
            closer = getattr(store, "close", None)
            if callable(closer):
                closer()


if __name__ == "__main__":
    raise SystemExit(main())
