#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.continuity import ContinuityBuilder, ContinuityStore
from engine.config import default_config, load_config
from engine.memory import MutationReviewQueue, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, load_inmemory_store_from_json, start_runtime_server, stop_runtime_server
from engine.runtime.server import _wizard_runtime_store_fingerprint, _wizard_write_runtime_lock


RUNTIME_TRACE_PATH = (REPO_ROOT / "runtime" / "desktop_shell" / "runtime_child_trace.log").resolve()


def _local_log_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d | %H:%M:%S.%f")[:-3]


def _trace_runtime(line: str) -> None:
    try:
        RUNTIME_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with RUNTIME_TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{_local_log_stamp()} {line}\n")
    except Exception:
        pass


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
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
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
    parser.add_argument(
        "--config",
        default="",
        help="Optional path to the MNO runtime policy JSON. Defaults to the built-in policy.",
    )
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

    requested_config_path = Path(args.config).expanduser().resolve() if str(args.config).strip() else None
    if requested_config_path is not None and not requested_config_path.exists():
        print(f"error=config path not found: {requested_config_path}")
        return 2
    standard_config_path = (REPO_ROOT / "runtime" / "state" / "mno-runtime-policy.v1.json").resolve()
    config_path = requested_config_path or (standard_config_path if standard_config_path.exists() else None)
    try:
        runtime_config = load_config(config_path, strict=True, upgrade=config_path is not None) if config_path else default_config()
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error=invalid runtime config: {exc}")
        return 2
    if config_path is None and not args.plan_only:
        config_path = standard_config_path
        temporary = config_path.with_name(f".{config_path.name}.{os.getpid()}.tmp")
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(runtime_config.as_dict(), indent=2) + "\n", encoding="utf-8")
            temporary.replace(config_path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            print(f"error=invalid runtime config: {exc}", file=sys.stderr)
            return 2

    runtime_url = f"http://{args.host}:{int(args.port)}"
    if args.plan_only and args.setup_mode:
        try:
            setup_backend = _store_backend_label(memories_path)
        except ValueError as exc:
            print(f"error={exc}")
            return 2
        print("mode=plan_only")
        print(f"launch_mode={launch_mode}")
        print(f"memories_path={memories_path}")
        print(f"store_backend={setup_backend}")
        print("atom_count=0")
        print(f"episode_cards_path={episode_cards_path if episode_cards_path is not None else ''}")
        print(f"runtime_url={runtime_url}")
        print(f"config_path={config_path if config_path is not None else ''}")
        return 0

    if args.setup_mode:
        memories_path.parent.mkdir(parents=True, exist_ok=True)

    runtime_pid = os.getpid()
    atexit.register(lambda: _trace_runtime(f"atexit pid={runtime_pid}"))

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
            print(f"config_path={config_path if config_path is not None else ''}")
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
            config=runtime_config,
            config_path=config_path,
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
            "store_fingerprint": _wizard_runtime_store_fingerprint(runtime),
            "episodes_path": str(episode_cards_path.resolve()) if episode_cards_path is not None else "",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "backend": backend_name,
            "artifact_mode": "setup" if args.setup_mode else ("published" if episode_cards_path is not None else ""),
            "build_id": "",
        }
        host, port = server.server_address
        if not args.setup_mode and episode_cards_path is not None:
            lock_payload = _wizard_write_runtime_lock(server, binding=server.active_runtime_binding)
            server.active_runtime_lock = dict(lock_payload)
        print(f"runtime_url=http://{host}:{port}")
        print(f"launch_mode={launch_mode}")
        print(f"memories_path={memories_path}")
        print(f"store_backend={backend_name}")
        print(f"atom_count={atom_count}")
        if episode_cards_path is not None:
            print(f"episode_cards_path={episode_cards_path}")
        print("Press Ctrl+C to stop.")
        _trace_runtime(
            f"startup pid={runtime_pid} launch_mode={launch_mode} "
            f"memories={memories_path} episodes={episode_cards_path if episode_cards_path is not None else ''}"
        )

        max_seconds = max(0.0, float(args.max_seconds))
        started = time.monotonic()
        shutdown_reason = "unknown"
        received_signals: list[str] = []

        def _record_signal(signum: int, _frame: Any) -> None:
            try:
                name = signal.Signals(signum).name
            except Exception:
                name = str(signum)
            received_signals.append(name)
            print(f"runtime_signal={name}", file=sys.stderr, flush=True)
            _trace_runtime(f"signal pid={server.active_runtime_lock.get('pid', 0) if hasattr(server, 'active_runtime_lock') else 0} name={name}")

        for handled_signal in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)):
            if handled_signal is None:
                continue
            try:
                signal.signal(handled_signal, _record_signal)
            except Exception:
                pass
        try:
            _trace_runtime(f"loop_enter pid={runtime_pid}")
            while True:
                if bool(getattr(server, "desktop_shutdown_requested", False)):
                    shutdown_reason = "desktop_shutdown_requested"
                    break
                if max_seconds > 0.0 and (time.monotonic() - started) >= max_seconds:
                    shutdown_reason = f"max_seconds:{max_seconds}"
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            shutdown_reason = "keyboard_interrupt"
        except BaseException as exc:  # noqa: BLE001
            shutdown_reason = f"exception:{type(exc).__name__}"
            print(f"runtime_unhandled_exception={type(exc).__name__}:{exc}", file=sys.stderr, flush=True)
            _trace_runtime(f"exception pid={runtime_pid} type={type(exc).__name__} detail={exc}")
            raise
        finally:
            if shutdown_reason == "unknown" and received_signals:
                shutdown_reason = f"signal:{','.join(received_signals)}"
            print(f"runtime_shutdown_reason={shutdown_reason}", file=sys.stderr, flush=True)
            print(f"runtime_shutdown_reason={shutdown_reason}", flush=True)
            _trace_runtime(f"shutdown pid={server.active_runtime_lock.get('pid', 0) if hasattr(server, 'active_runtime_lock') else 0} reason={shutdown_reason}")
            stop_runtime_server(server, thread, runtime=runtime)
        return 0
    finally:
        if close_store:
            closer = getattr(store, "close", None)
            if callable(closer):
                closer()


if __name__ == "__main__":
    raise SystemExit(main())
