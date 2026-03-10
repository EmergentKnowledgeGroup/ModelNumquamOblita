#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.mcp_connector_common import (
    DEFAULT_SERVER_NAME,
    SUPPORTED_MEMORY_SUFFIXES,
    build_launcher_cli_args,
    build_claude_code_add_json_cmd,
    build_mcp_servers_payload,
    build_posix_stdio_entry,
    build_windows_wsl_stdio_entry,
    default_episode_cards_path,
    default_memory_path,
    detect_wsl_distro,
    discover_memory_candidates,
    ensure_valid_server_name,
    find_windows_claude_code_config,
    find_windows_claude_desktop_config,
    format_memory_candidate_label,
    install_claude_code_server,
    is_windows_platform,
    is_wsl_environment,
    load_json_object,
    merge_mcp_server_entry,
    remove_claude_code_server,
    remove_mcp_server_entry,
    resolve_episode_cards_path,
    windows_wsl_command,
    write_json_with_backup,
    wsl_path_from_windows,
)

EXPORT_BUNDLE_SIGNATURE = "numquamoblita_mcp_connector_bundle_v1"
DEFAULT_HELP_PROMPT = "Hover over or click a ? icon to see what a setting means."
HELP_TEXT = {
    "episode_cards": "Optional extra memory cards. Leave this empty unless you already have an episode-cards JSON file you want the server to use.",
    "default_role": "Viewer is safest for normal testing. Operator and admin unlock stronger tools and should only be used when you really need them.",
    "claude_code_scope": "Local = this checkout only. User = your whole machine profile. Project = the current Claude Code project config.",
    "compat_mode": "Strict uses the current MCP contract and is the default. Lenient v1 only exists for older clients that need the legacy shape.",
    "mutations_enabled": "Off keeps the memory server read-only. Turn this on only if you explicitly want memory-changing tools available.",
    "wsl_distro": "Used for Claude Desktop and any WSL-based Claude Code fallback on Windows. If Claude Code is installed natively on Windows, this setting does not affect it.",
    "server_name": "The MCP server key shown inside the client config. Most people should leave this alone.",
}
MEMORY_FILETYPES = [
    ("Memory stores", "*.sqlite3 *.sqlite *.db *.json"),
    ("SQLite databases", "*.sqlite3 *.sqlite *.db"),
    ("JSON files", "*.json"),
    ("All files", "*.*"),
]
EPISODE_FILETYPES = [
    ("Episode cards JSON", "*.json"),
    ("All files", "*.*"),
]
EXPORT_FILETYPES = [
    ("JSON files", "*.json"),
    ("All files", "*.*"),
]

THEMES = {
    "dark": {
        "bg":           "#0C1525",
        "panel":        "#111E32",
        "panel_alt":    "#162840",
        "input":        "#0A1220",
        "line":         "#1E3254",
        "text":         "#E4E9F1",
        "muted":        "#7B8FA8",
        "accent":       "#D4A855",
        "accent_hover": "#E0BA6A",
        "accent_deep":  "#B08930",
        "accent_soft":  "#1F1E14",
        "ok":           "#5BC68A",
        "ok_bg":        "#0F2A1A",
        "error":        "#E86464",
        "error_bg":     "#2A0F0F",
        "info":         "#6CB4E8",
        "busy_bg":      "#0F1A2A",
        "select":       "#1A3050",
    },
    "light": {
        "bg":           "#D8DEE8",
        "panel":        "#E2E7EF",
        "panel_alt":    "#CDD4E0",
        "input":        "#EFF1F5",
        "line":         "#B0BAC8",
        "text":         "#1A2540",
        "muted":        "#506070",
        "accent":       "#9E7B30",
        "accent_hover": "#B8923A",
        "accent_deep":  "#7D6020",
        "accent_soft":  "#E8E0D0",
        "ok":           "#2D8C5A",
        "ok_bg":        "#D0EADC",
        "error":        "#C04040",
        "error_bg":     "#F0D0D0",
        "info":         "#3070A8",
        "busy_bg":      "#C8D0DC",
        "select":       "#B8C8E0",
    },
}


class ResolvedPayload:
    def __init__(
        self,
        *,
        server_name: str,
        default_role: str,
        compat_mode: str,
        claude_code_scope: str,
        memories_path: Path,
        episodes_path: Path | None,
        mutations_enabled: bool,
        wsl_distro: str,
        repo_root_wsl: str,
        launcher_path_wsl: str,
        memories_path_wsl: str,
        episodes_path_wsl: str | None,
        windows_desktop_config: str,
        windows_claude_code_config: str,
    ) -> None:
        self.server_name = server_name
        self.default_role = default_role
        self.compat_mode = compat_mode
        self.claude_code_scope = claude_code_scope
        self.memories_path = memories_path
        self.episodes_path = episodes_path
        self.mutations_enabled = mutations_enabled
        self.wsl_distro = wsl_distro
        self.repo_root_wsl = repo_root_wsl
        self.launcher_path_wsl = launcher_path_wsl
        self.memories_path_wsl = memories_path_wsl
        self.episodes_path_wsl = episodes_path_wsl
        self.windows_desktop_config = windows_desktop_config
        self.windows_claude_code_config = windows_claude_code_config


class ConnectorControlPanel:
    def __init__(
        self,
        *,
        repo_root: Path = REPO_ROOT,
        python_path: str = "python3",
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.python_path = self._normalize_launcher_python_path(str(python_path).strip() or "python3")
        self.runner = runner
        self.which = which

    def current_state(self) -> dict[str, Any]:
        desktop_path = find_windows_claude_desktop_config()
        windows_claude_code = find_windows_claude_code_config()
        raw_candidates = discover_memory_candidates(repo_root=self.repo_root)
        labels = [format_memory_candidate_label(row) for row in raw_candidates]
        memory_candidates = [dict(row, display_label=labels[index]) for index, row in enumerate(raw_candidates)]
        default_memory = default_memory_path(repo_root=self.repo_root)
        default_episodes = default_episode_cards_path(repo_root=self.repo_root)
        distro = detect_wsl_distro(runner=self.runner)
        install_context = self._claude_code_install_context(distro_name=distro)
        return {
            "repo_root": str(self.repo_root),
            "python_path": self.python_path,
            "server_name": DEFAULT_SERVER_NAME,
            "default_memory_path": str(default_memory.resolve()),
            "default_episodes_path": str(default_episodes.resolve()) if default_episodes is not None else "",
            "memory_candidates": memory_candidates,
            "claude_code_available": install_context != "missing",
            "claude_code_install_context": install_context,
            "claude_code_display": self._claude_code_display_label(install_context),
            "claude_code_scope": "local",
            "windows_claude_desktop_config": str(desktop_path) if desktop_path is not None else "",
            "windows_claude_code_config": str(windows_claude_code) if windows_claude_code is not None else "",
            "wsl_distro": distro,
            "help_text": dict(HELP_TEXT),
            "supported_memory_suffixes": sorted(SUPPORTED_MEMORY_SUFFIXES),
        }

    def build_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._resolve_payload(payload)
        claude_code_install_context = self._claude_code_install_context(distro_name=resolved.wsl_distro)
        posix_entry = build_posix_stdio_entry(
            python_path="python3",
            launcher_path=resolved.launcher_path_wsl,
            memories_path=resolved.memories_path_wsl,
            episodes_path=resolved.episodes_path_wsl,
            default_role=resolved.default_role,
            compat_mode=resolved.compat_mode,
            mutations_enabled=resolved.mutations_enabled,
        )
        windows_entry = build_windows_wsl_stdio_entry(
            repo_root=resolved.repo_root_wsl,
            memories_path=resolved.memories_path_wsl,
            episodes_path=resolved.episodes_path_wsl,
            default_role=resolved.default_role,
            compat_mode=resolved.compat_mode,
            mutations_enabled=resolved.mutations_enabled,
            distro_name=resolved.wsl_distro,
            runner=self.runner,
        )
        claude_code_entry = self._build_claude_code_entry(
            resolved=resolved,
            install_context=claude_code_install_context,
            posix_entry=posix_entry,
        )
        claude_code_bin = self._claude_code_preview_bin(install_context=claude_code_install_context)
        return {
            "server_name": resolved.server_name,
            "claude_code_scope": resolved.claude_code_scope,
            "memories_path": str(resolved.memories_path),
            "episodes_path": str(resolved.episodes_path) if resolved.episodes_path is not None else "",
            "default_role": resolved.default_role,
            "compat_mode": resolved.compat_mode,
            "mutations_enabled": resolved.mutations_enabled,
            "wsl_distro": resolved.wsl_distro,
            "claude_code_install_context": claude_code_install_context,
            "claude_code_display": self._claude_code_display_label(claude_code_install_context),
            "posix_entry": posix_entry,
            "windows_entry": windows_entry,
            "claude_code_entry": claude_code_entry,
            "posix_payload": build_mcp_servers_payload(server_name=resolved.server_name, entry=posix_entry),
            "windows_payload": build_mcp_servers_payload(server_name=resolved.server_name, entry=windows_entry),
            "claude_code_add_cmd": build_claude_code_add_json_cmd(
                server_name=resolved.server_name,
                entry=claude_code_entry,
                scope=resolved.claude_code_scope,
                claude_bin=claude_code_bin,
            ),
            "windows_claude_desktop_config": resolved.windows_desktop_config,
            "windows_claude_code_config": resolved.windows_claude_code_config,
        }

    def install_claude_code(self, payload: dict[str, Any]) -> dict[str, Any]:
        preview = self.build_preview(payload)
        resolved = self._resolve_payload(payload)
        install_context = str(preview["claude_code_install_context"] or "").strip() or "missing"
        runner = self.runner
        which = self.which
        claude_bin = self._claude_code_preview_bin(install_context=install_context)
        if install_context == "wsl-claude":
            runner = self._wsl_claude_runner(resolved.repo_root_wsl, resolved.wsl_distro)
            which = self._wsl_claude_which(resolved.repo_root_wsl, resolved.wsl_distro)
            claude_bin = "claude"
        elif install_context == "native-windows-claude":
            native_bin = self._native_claude_bin()
            if native_bin is None:
                raise RuntimeError("native Claude Code CLI not found on Windows")
            claude_bin = native_bin
            which = lambda _binary: native_bin
        elif install_context == "missing":
            raise RuntimeError("claude CLI not found. Install Claude Code on Windows or in WSL before using this action.")
        result = install_claude_code_server(
            server_name=str(preview["server_name"]),
            entry=dict(preview["claude_code_entry"]),
            scope=str(preview["claude_code_scope"]),
            claude_bin=claude_bin,
            runner=runner,
            which=which,
        )
        result.update(
            {
                "server_name": preview["server_name"],
                "memories_path": preview["memories_path"],
                "claude_code_add_cmd": preview["claude_code_add_cmd"],
                "install_context": install_context,
            }
        )
        return result

    def remove_claude_code(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._resolve_payload(payload)
        install_context = self._claude_code_install_context(distro_name=resolved.wsl_distro)
        runner = self.runner
        which = self.which
        claude_bin = self._claude_code_preview_bin(install_context=install_context)
        if install_context == "wsl-claude":
            runner = self._wsl_claude_runner(resolved.repo_root_wsl, resolved.wsl_distro)
            which = self._wsl_claude_which(resolved.repo_root_wsl, resolved.wsl_distro)
            claude_bin = "claude"
        elif install_context == "native-windows-claude":
            native_bin = self._native_claude_bin()
            if native_bin is None:
                raise RuntimeError("native Claude Code CLI not found on Windows")
            claude_bin = native_bin
            which = lambda _binary: native_bin
        elif install_context == "missing":
            raise RuntimeError("claude CLI not found. Install Claude Code on Windows or in WSL before using this action.")
        result = remove_claude_code_server(
            server_name=resolved.server_name,
            scope=resolved.claude_code_scope,
            claude_bin=claude_bin,
            runner=runner,
            which=which,
        )
        result.update(
            {
                "server_name": resolved.server_name,
                "windows_claude_code_config": resolved.windows_claude_code_config,
                "install_context": install_context,
            }
        )
        return result

    def install_claude_desktop(self, payload: dict[str, Any]) -> dict[str, Any]:
        preview = self.build_preview(payload)
        config_path = find_windows_claude_desktop_config()
        if config_path is None:
            raise RuntimeError("unable to locate Claude Desktop config")
        existing = load_json_object(config_path)
        merged = merge_mcp_server_entry(existing, server_name=str(preview["server_name"]), entry=dict(preview["windows_entry"]))
        backup_path = write_json_with_backup(config_path, merged)
        return {
            "server_name": preview["server_name"],
            "config_path": str(config_path),
            "backup_path": str(backup_path) if backup_path is not None else "",
            "windows_payload": preview["windows_payload"],
        }

    def remove_claude_desktop(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._resolve_payload(payload)
        config_path = find_windows_claude_desktop_config()
        if config_path is None:
            raise RuntimeError("unable to locate Claude Desktop config")
        existing = load_json_object(config_path)
        updated, removed = remove_mcp_server_entry(existing, server_name=resolved.server_name)
        backup_path = write_json_with_backup(config_path, updated)
        return {
            "server_name": resolved.server_name,
            "config_path": str(config_path),
            "backup_path": str(backup_path) if backup_path is not None else "",
            "removed": removed,
        }

    def export_bundle(self, payload: dict[str, Any]) -> dict[str, Any]:
        preview = self.build_preview(payload)
        preview["windows_claude_desktop_config"] = str(find_windows_claude_desktop_config() or "")
        preview["windows_claude_code_config"] = str(find_windows_claude_code_config() or "")
        return preview

    def save_export_bundle(self, payload: dict[str, Any], *, export_path: str | Path) -> dict[str, Any]:
        bundle = self.export_bundle(payload)
        target = Path(export_path).expanduser()
        if not str(target).lower().endswith(".json"):
            target = target.with_suffix(".json")
        signature = {
            "generated_by": EXPORT_BUNDLE_SIGNATURE,
            "generated_at": self._timestamp(),
            "server_name": bundle["server_name"],
            "bundle": {
                "posix_payload": bundle["posix_payload"],
                "windows_payload": bundle["windows_payload"],
                "claude_code_add_cmd": bundle["claude_code_add_cmd"],
            },
        }
        backup_path = write_json_with_backup(target, signature)
        return {
            "export_path": str(target),
            "backup_path": str(backup_path) if backup_path is not None else "",
            **bundle,
        }

    def export_bundle_has_connector_signature(self, path: str | Path) -> bool:
        try:
            payload = load_json_object(Path(path))
        except Exception:
            return False
        return str(payload.get("generated_by") or "").strip() == EXPORT_BUNDLE_SIGNATURE

    def _resolve_payload(self, payload: dict[str, Any]) -> ResolvedPayload:
        server_name = ensure_valid_server_name(str(payload.get("server_name") or DEFAULT_SERVER_NAME))
        default_role = str(payload.get("default_role") or "viewer").strip() or "viewer"
        if default_role not in {"viewer", "operator", "admin"}:
            raise ValueError("default role must be viewer, operator, or admin")
        compat_mode = str(payload.get("compat_mode") or "strict").strip() or "strict"
        if compat_mode not in {"strict", "lenient_v1"}:
            raise ValueError("compat mode must be strict or lenient_v1")
        claude_code_scope = str(payload.get("claude_code_scope") or "local").strip() or "local"
        if claude_code_scope not in {"local", "user", "project"}:
            raise ValueError("Claude Code scope must be local, user, or project")

        memories_raw = str(payload.get("memories_path") or "").strip() or str(default_memory_path(repo_root=self.repo_root))
        memories_path = self._resolve_existing_path(memories_raw)
        if memories_path.suffix.lower() not in SUPPORTED_MEMORY_SUFFIXES:
            raise ValueError("memories path must be .sqlite3, .sqlite, .db, or .json")
        self._validate_memories_path(memories_path)

        episodes_raw = str(payload.get("episodes_path") or "").strip()
        episodes_path = resolve_episode_cards_path(episodes_raw, repo_root=self.repo_root)
        if episodes_path is not None and not episodes_path.exists():
            raise ValueError(f"episode cards path not found: {episodes_path}")

        distro = str(payload.get("wsl_distro") or "").strip() or detect_wsl_distro(runner=self.runner)
        repo_root_wsl, distro = self._path_for_wsl(self.repo_root, distro_name=distro)
        launcher_path_wsl, distro = self._path_for_wsl(self.repo_root / "tools" / "run_claude_live_mcp.py", distro_name=distro)
        memories_path_wsl, distro = self._path_for_wsl(memories_path, distro_name=distro)
        episodes_path_wsl: str | None = None
        if episodes_path is not None:
            episodes_path_wsl, distro = self._path_for_wsl(episodes_path, distro_name=distro)

        desktop_config = find_windows_claude_desktop_config()
        claude_code_config = find_windows_claude_code_config()
        return ResolvedPayload(
            server_name=server_name,
            default_role=default_role,
            compat_mode=compat_mode,
            claude_code_scope=claude_code_scope,
            memories_path=memories_path,
            episodes_path=episodes_path,
            mutations_enabled=bool(payload.get("mutations_enabled")),
            wsl_distro=distro,
            repo_root_wsl=repo_root_wsl,
            launcher_path_wsl=launcher_path_wsl,
            memories_path_wsl=memories_path_wsl,
            episodes_path_wsl=episodes_path_wsl,
            windows_desktop_config=str(desktop_config) if desktop_config is not None else "",
            windows_claude_code_config=str(claude_code_config) if claude_code_config is not None else "",
        )

    def _resolve_existing_path(self, raw: str) -> Path:
        path = Path(raw).expanduser()
        if not path.is_absolute() and not str(raw).startswith("\\\\"):
            path = (self.repo_root / path).resolve()
        else:
            path = path.resolve()
        if not path.exists():
            raise ValueError(f"path not found: {path}")
        if not path.is_file():
            raise ValueError(f"path is not a file: {path}")
        return path

    def _validate_memories_path(self, path: Path) -> None:
        if path.suffix.lower() != ".json":
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        has_memory_rows = any(isinstance(payload.get(key), list) for key in ("atoms", "memory_atoms", "items"))
        has_conversations = isinstance(payload.get("conversations"), list)
        if has_conversations and not has_memory_rows:
            raise ValueError(
                "Selected JSON looks like an IA transcript archive (db.json), not an MNO memory store. "
                "Run tools/import_ia_db.py first, then point this connector at the imported sqlite store."
            )

    def _path_for_wsl(self, value: str | Path, *, distro_name: str) -> tuple[str, str]:
        raw = str(value)
        if raw.startswith("/"):
            return raw, distro_name
        return wsl_path_from_windows(raw, distro_name=distro_name, runner=self.runner)

    def _build_claude_code_entry(
        self,
        *,
        resolved: ResolvedPayload,
        install_context: str,
        posix_entry: dict[str, Any],
    ) -> dict[str, Any]:
        if install_context == "native-windows-claude":
            return {
                "command": str(self.python_path).strip() or "python",
                "args": build_launcher_cli_args(
                    launcher_path=str((self.repo_root / "tools" / "run_claude_live_mcp.py").resolve()),
                    memories_path=resolved.memories_path,
                    episodes_path=resolved.episodes_path,
                    default_role=resolved.default_role,
                    compat_mode=resolved.compat_mode,
                    mutations_enabled=resolved.mutations_enabled,
                ),
            }
        return dict(posix_entry)

    def _claude_code_preview_bin(self, *, install_context: str) -> str:
        if install_context == "native-windows-claude":
            return self._native_claude_bin() or "claude"
        return "claude"

    def _claude_code_install_context(self, *, distro_name: str) -> str:
        if is_windows_platform():
            if self._native_claude_bin() is not None:
                return "native-windows-claude"
            if self._wsl_claude_available(distro_name=distro_name):
                return "wsl-claude"
            return "missing"
        return "local-claude" if bool(self.which("claude")) else "missing"

    @staticmethod
    def _claude_code_display_label(install_context: str) -> str:
        labels = {
            "native-windows-claude": "native Windows CLI",
            "wsl-claude": "WSL CLI fallback",
            "local-claude": "available",
            "missing": "not found",
        }
        return labels.get(str(install_context or "").strip(), "not found")

    def _native_claude_bin(self) -> str | None:
        for candidate in ("claude", "claude.exe", "claude.cmd", "claude.bat"):
            found = self.which(candidate)
            if found:
                return found
        return None

    @staticmethod
    def _normalize_launcher_python_path(raw: str) -> str:
        python_path = str(raw or "").strip() or "python3"
        lower = python_path.lower()
        if not lower.endswith("pythonw.exe"):
            return python_path
        preferred = Path(python_path[:-len("pythonw.exe")] + "python.exe")
        if preferred.exists():
            return str(preferred)
        return str(preferred)

    def _wsl_claude_available(self, *, distro_name: str) -> bool:
        if not is_windows_platform():
            return False
        repo_root_wsl, distro = self._path_for_wsl(self.repo_root, distro_name=distro_name)
        prefix = self._wsl_exec_prefix(repo_root_wsl, distro)
        proc = self.runner(prefix + ["sh", "-lc", "command -v claude >/dev/null 2>&1"], check=False, capture_output=True, text=True)
        return proc.returncode == 0

    def _wsl_exec_prefix(self, repo_root_wsl: str, distro_name: str) -> list[str]:
        prefix = [windows_wsl_command()]
        if distro_name:
            prefix.extend(["-d", distro_name])
        prefix.extend(["--cd", repo_root_wsl, "--exec"])
        return prefix

    def _wsl_claude_runner(self, repo_root_wsl: str, distro_name: str) -> Callable[..., subprocess.CompletedProcess[str]]:
        prefix = self._wsl_exec_prefix(repo_root_wsl, distro_name)

        def _runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return self.runner(prefix + list(cmd), **kwargs)

        return _runner

    def _wsl_claude_which(self, repo_root_wsl: str, distro_name: str) -> Callable[[str], str | None]:
        prefix = self._wsl_exec_prefix(repo_root_wsl, distro_name)

        def _which(binary: str) -> str | None:
            quoted = shlex.quote(str(binary))
            proc = self.runner(prefix + ["sh", "-lc", f"command -v {quoted}"], check=False, capture_output=True, text=True)
            if proc.returncode != 0:
                return None
            path = str(proc.stdout or "").strip()
            return path or None

        return _which

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
#  GUI
# ---------------------------------------------------------------------------

class ConnectorWindow:
    def __init__(self, controller: ConnectorControlPanel) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog, messagebox, ttk
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("tkinter is unavailable in this Python environment") from exc
        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.controller = controller
        self.state = controller.current_state()

        self._theme_name = "dark"
        self._tooltip_window: Any = None
        self._last_result_text = ""
        self._last_open_path = ""
        self._last_status_kind = "ready"
        self._env_expanded = True
        self._action_buttons: list[Any] = []
        self._info_badges: list[Any] = []

        self.root = tk.Tk()
        self.root.title("NumquamOblita MCP Connector")
        self.root.configure(bg=self._t["bg"])
        self.root.geometry("1200x780")
        self.root.minsize(1080, 700)
        self.root.option_add("*tearOff", False)

        self._detect_mono_font()
        self._apply_theme()
        self._build_vars()
        self._build_layout()
        self._bind_initial_values()
        self._set_status("Ready. Pick a store, then preview or install.", kind="ready")
        self._set_output({"hint": "Choose a detected store or browse to one, then click Preview Config."})
        self.root.after(40, self._center_window)

    @property
    def _t(self) -> dict[str, str]:
        return THEMES[self._theme_name]

    def run(self) -> int:
        self.root.mainloop()
        return 0

    # -- fonts ---------------------------------------------------------------

    def _detect_mono_font(self) -> None:
        try:
            import tkinter.font as tkfont
            available = tkfont.families(self.root)
            if "Cascadia Mono" in available:
                self._mono_family = "Cascadia Mono"
            elif "Cascadia Code" in available:
                self._mono_family = "Cascadia Code"
            else:
                self._mono_family = "Consolas"
        except Exception:
            self._mono_family = "Consolas"

    # -- theming -------------------------------------------------------------

    def _apply_theme(self) -> None:
        t = self._t
        style = self.ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        body_font = ("Segoe UI", 10)
        body_bold = ("Segoe UI", 10, "bold")
        hero_font = ("Bahnschrift SemiCondensed", 22, "bold")
        section_font = ("Bahnschrift SemiCondensed", 12, "bold")
        small_font = ("Segoe UI", 9)

        # -- frames --
        style.configure("NO.TFrame", background=t["bg"])
        style.configure("Card.TFrame", background=t["panel"])
        style.configure("Hero.TFrame", background=t["panel_alt"])

        # -- labels --
        style.configure("NO.TLabel", background=t["bg"], foreground=t["text"], font=body_font)
        style.configure("Muted.TLabel", background=t["panel"], foreground=t["muted"], font=small_font)
        style.configure("HeroTitle.TLabel", background=t["panel_alt"], foreground=t["accent"], font=hero_font)
        style.configure("HeroSub.TLabel", background=t["panel_alt"], foreground=t["muted"], font=body_font)
        style.configure("Section.TLabel", background=t["panel"], foreground=t["accent"], font=section_font)
        style.configure("FieldLabel.TLabel", background=t["panel"], foreground=t["text"], font=body_bold)
        style.configure("EnvKey.TLabel", background=t["panel_alt"], foreground=t["muted"], font=("Segoe UI", 9, "bold"))
        style.configure("EnvVal.TLabel", background=t["panel_alt"], foreground=t["text"], font=body_font)

        # -- buttons --
        style.configure("Primary.TButton", font=body_bold, padding=(16, 10),
                        background=t["accent"], foreground="#0C0C0C")
        style.map("Primary.TButton",
                  background=[("active", t["accent_deep"]), ("disabled", t["line"])],
                  foreground=[("disabled", t["muted"])])

        style.configure("Secondary.TButton", font=body_bold, padding=(16, 10),
                        background=t["panel_alt"], foreground=t["accent"])
        style.map("Secondary.TButton",
                  background=[("active", t["line"]), ("disabled", t["panel"])],
                  foreground=[("disabled", t["muted"])])

        style.configure("Ghost.TButton", font=body_font, padding=(14, 9),
                        background=t["panel"], foreground=t["muted"])
        style.map("Ghost.TButton",
                  background=[("active", t["panel_alt"]), ("disabled", t["panel"])],
                  foreground=[("active", t["text"]), ("disabled", t["line"])])

        style.configure("Theme.TButton", font=("Segoe UI", 12), padding=(10, 6),
                        background=t["panel_alt"], foreground=t["accent"])
        style.map("Theme.TButton",
                  background=[("active", t["line"])],
                  foreground=[("active", t["accent_hover"])])

        style.configure("Info.TButton", font=("Segoe UI", 8, "bold"), padding=(6, 2),
                        background=t["panel"], foreground=t["accent"])
        style.map("Info.TButton",
                  background=[("active", t["panel_alt"])])

        # -- combobox --
        style.configure("NO.TCombobox",
                        fieldbackground=t["input"], background=t["input"],
                        foreground=t["text"], arrowcolor=t["accent"],
                        selectbackground=t["select"], selectforeground=t["text"])
        style.map(
            "NO.TCombobox",
            fieldbackground=[
                ("readonly", t["input"]),
                ("disabled", t["panel_alt"]),
            ],
            background=[
                ("readonly", t["input"]),
                ("disabled", t["panel_alt"]),
            ],
            foreground=[
                ("readonly", t["text"]),
                ("focus", t["text"]),
                ("disabled", t["muted"]),
            ],
            selectbackground=[
                ("readonly", t["select"]),
                ("focus", t["select"]),
            ],
            selectforeground=[
                ("readonly", t["text"]),
                ("focus", t["text"]),
            ],
            arrowcolor=[
                ("readonly", t["accent"]),
                ("disabled", t["muted"]),
            ],
        )

        # -- checkbutton --
        style.configure("NO.TCheckbutton", background=t["panel"], foreground=t["text"], font=body_font)
        style.map("NO.TCheckbutton",
                  background=[("active", t["panel"]), ("selected", t["panel"])])

        # -- separator --
        style.configure("Gold.TSeparator", background=t["accent"])

        # -- global tk widget options --
        self.root.option_add("*Font", body_font)
        self.root.option_add("*Entry.background", t["input"])
        self.root.option_add("*Entry.foreground", t["text"])
        self.root.option_add("*Entry.insertBackground", t["accent"])
        self.root.option_add("*Entry.highlightThickness", 1)
        self.root.option_add("*Text.background", t["input"])
        self.root.option_add("*Text.foreground", t["text"])
        self.root.option_add("*Text.insertBackground", t["accent"])
        self.root.option_add("*TCombobox*Listbox.background", t["input"])
        self.root.option_add("*TCombobox*Listbox.foreground", t["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", t["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#0C0C0C")

    def _toggle_theme(self) -> None:
        saved_output = self._last_result_text
        saved_open_path = self._last_open_path
        saved_status_text = self.status_var.get()
        saved_status_kind = self._last_status_kind

        self._theme_name = "light" if self._theme_name == "dark" else "dark"

        for child in self.root.winfo_children():
            child.destroy()
        self._tooltip_window = None
        self._action_buttons = []
        self._info_badges = []

        self.root.configure(bg=self._t["bg"])
        self._apply_theme()
        self._build_layout()

        # restore non-var state
        if saved_output:
            self._last_result_text = saved_output
            self.output_text.configure(state="normal")
            self.output_text.delete("1.0", "end")
            self.output_text.insert("1.0", saved_output)
            self.output_text.configure(state="disabled")
        self._last_open_path = saved_open_path
        self.open_folder_button.state(["!disabled"] if saved_open_path else ["disabled"])
        self._set_status(saved_status_text, kind=saved_status_kind)

    # -- variables -----------------------------------------------------------

    def _build_vars(self) -> None:
        self.memory_path_var = self.tk.StringVar()
        self.episodes_path_var = self.tk.StringVar()
        self.server_name_var = self.tk.StringVar()
        self.default_role_var = self.tk.StringVar(value="viewer")
        self.scope_var = self.tk.StringVar(value="local")
        self.compat_var = self.tk.StringVar(value="strict")
        self.wsl_distro_var = self.tk.StringVar()
        self.mutations_var = self.tk.BooleanVar(value=False)
        self.status_var = self.tk.StringVar(value="Ready.")
        self.help_var = self.tk.StringVar(value=DEFAULT_HELP_PROMPT)
        self.memory_choice_var = self.tk.StringVar()

    # -- layout --------------------------------------------------------------

    def _build_layout(self) -> None:
        t = self._t
        main = self.ttk.Frame(self.root, style="NO.TFrame", padding=16)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(1, weight=0)
        main.rowconfigure(2, weight=1)

        # ---- hero bar ----
        hero = self.ttk.Frame(main, style="Hero.TFrame", padding=(24, 16))
        hero.grid(row=0, column=0, columnspan=2, sticky="ew")
        hero.columnconfigure(0, weight=1)
        hero.columnconfigure(1, weight=0)

        title_area = self.ttk.Frame(hero, style="Hero.TFrame")
        title_area.grid(row=0, column=0, sticky="w")
        self.ttk.Label(title_area, text="\u2726  NumquamOblita MCP Connector",
                       style="HeroTitle.TLabel").pack(anchor="w")
        self.ttk.Label(title_area,
                       text="Pick a store. Install safely. Skip the CLI.",
                       style="HeroSub.TLabel").pack(anchor="w", pady=(4, 0))

        toggle_label = "\u263E" if self._theme_name == "dark" else "\u2600"
        self.theme_button = self.ttk.Button(hero, text=toggle_label,
                                            command=self._toggle_theme,
                                            style="Theme.TButton")
        self.theme_button.grid(row=0, column=1, sticky="ne", padx=(16, 0))

        # ---- left column: setup ----
        setup = self.ttk.Frame(main, style="Card.TFrame", padding=20)
        setup.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(0, 10), pady=(12, 0))
        setup.columnconfigure(0, weight=1)
        setup.columnconfigure(1, weight=0)

        self._section_header(setup, "Setup", row=0)

        row = 1
        self._build_candidate_selector(setup, row)
        row += 1
        self._build_path_field(setup, row, label="Memory DB / JSON path",
                               variable=self.memory_path_var,
                               browse_command=self._browse_memory, clear_command=None)
        row += 1
        self._build_path_field(setup, row, label="Episode cards path (optional)",
                               variable=self.episodes_path_var,
                               browse_command=self._browse_episodes,
                               clear_command=self._clear_episodes,
                               help_key="episode_cards")
        row += 1

        # advanced sub-section
        advanced = self.ttk.Frame(setup, style="Card.TFrame", padding=(14, 14))
        advanced.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        advanced.columnconfigure(0, weight=1)
        advanced.columnconfigure(1, weight=1)
        self._section_header(advanced, "Advanced", row=0, span=2)

        self._build_labeled_entry(advanced, 1, 0, "Server name", self.server_name_var, help_key="server_name")
        self._build_labeled_combo(advanced, 1, 1, "Default role", self.default_role_var,
                                  ["viewer", "operator", "admin"], help_key="default_role")
        self._build_labeled_combo(advanced, 2, 0, "Claude Code scope", self.scope_var,
                                  ["local", "user", "project"], help_key="claude_code_scope")
        self._build_labeled_combo(advanced, 2, 1, "Compat mode", self.compat_var,
                                  ["strict", "lenient_v1"], help_key="compat_mode")
        self._build_labeled_entry(advanced, 3, 0, "WSL distro", self.wsl_distro_var, help_key="wsl_distro")
        self._build_checkbox(
            advanced,
            3,
            1,
            "Mutation tools",
            self.mutations_var,
            help_key="mutations_enabled",
            check_text="Enable memory-changing tools",
        )

        # action buttons — 2x2 grid
        actions = self.ttk.Frame(setup, style="Card.TFrame", padding=(0, 18, 0, 0))
        actions.grid(row=row + 1, column=0, columnspan=2, sticky="ew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self._action_buttons.extend([
            self._action_button(actions, "Preview Config", self._run_preview,
                                "Primary.TButton", 0, 0),
            self._action_button(actions, "Install \u2192 Claude Code", self._run_install_claude_code,
                                "Secondary.TButton", 0, 1),
            self._action_button(actions, "Install \u2192 Claude Desktop", self._run_install_claude_desktop,
                                "Secondary.TButton", 1, 0),
            self._action_button(actions, "Export MCP Bundle", self._run_export,
                                "Ghost.TButton", 1, 1),
            self._action_button(actions, "Remove \u2192 Claude Code", self._run_remove_claude_code,
                                "Ghost.TButton", 2, 0),
            self._action_button(actions, "Remove \u2192 Claude Desktop", self._run_remove_claude_desktop,
                                "Ghost.TButton", 2, 1),
        ])

        # ---- right column: environment + status + output ----
        right = self.ttk.Frame(main, style="Card.TFrame", padding=20)
        right.grid(row=1, column=1, sticky="new", pady=(12, 0))
        right.columnconfigure(0, weight=1)
        self._build_environment_panel(right)

        # ---- right lower: output ----
        output_card = self.ttk.Frame(main, style="Card.TFrame", padding=20)
        output_card.grid(row=2, column=1, sticky="nsew", pady=(12, 0))
        output_card.columnconfigure(0, weight=1)
        output_card.rowconfigure(1, weight=1)
        self._section_header(output_card, "Output Log", row=0)

        output_body = self.tk.Frame(output_card, bg=t["panel"])
        output_body.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        output_body.columnconfigure(0, weight=1)
        output_body.rowconfigure(0, weight=1)

        self.output_text = self.tk.Text(output_body, wrap="word", relief="flat",
                                        borderwidth=0, height=22, padx=16, pady=14,
                                        font=(self._mono_family, 9))
        self.output_text.grid(row=0, column=0, sticky="nsew")
        self.output_text.configure(bg=t["input"], fg=t["text"],
                                   insertbackground=t["accent"],
                                   selectbackground=t["select"])
        self.output_scrollbar = self.tk.Scrollbar(output_body, orient="vertical",
                                                  command=self.output_text.yview,
                                                  bg=t["panel_alt"], troughcolor=t["panel"],
                                                  activebackground=t["accent"], bd=0,
                                                  highlightthickness=0, relief="flat")
        self.output_scrollbar.grid(row=0, column=1, sticky="ns")
        self.output_text.configure(yscrollcommand=self.output_scrollbar.set)
        self.output_text.configure(state="disabled")

    # -- section header with gold accent line --------------------------------

    def _section_header(self, parent: Any, text: str, *, row: int, span: int = 1) -> None:
        t = self._t
        frame = self.ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=row, column=0, columnspan=span, sticky="ew", pady=(0, 4))
        frame.columnconfigure(0, weight=1)
        self.ttk.Label(frame, text=text, style="Section.TLabel").grid(row=0, column=0, sticky="w")
        bar = self.tk.Frame(frame, bg=t["accent"], height=2)
        bar.grid(row=1, column=0, sticky="ew", pady=(6, 0))

    # -- environment panel ---------------------------------------------------

    def _build_environment_panel(self, parent: Any) -> None:
        t = self._t
        header = self.ttk.Frame(parent, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
        self.ttk.Label(header, text="Environment", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.env_toggle_button = self.ttk.Button(
            header,
            text="Hide Details",
            command=self._toggle_environment_panel,
            style="Ghost.TButton",
        )
        self.env_toggle_button.grid(row=0, column=1, sticky="e")
        bar = self.tk.Frame(header, bg=t["accent"], height=2)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.env_body = self.ttk.Frame(parent, style="Card.TFrame")
        self.env_body.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.env_body.columnconfigure(0, weight=1)

        self.env_frame = self.ttk.Frame(self.env_body, style="Card.TFrame")
        self.env_frame.grid(row=0, column=0, sticky="ew")
        self.env_frame.columnconfigure(0, weight=1)
        self._render_environment()

        status_frame = self.ttk.Frame(self.env_body, style="Card.TFrame", padding=(0, 14, 0, 0))
        status_frame.grid(row=1, column=0, sticky="ew")

        self.status_label = self.tk.Label(status_frame, textvariable=self.status_var,
                                          bg=t["accent_soft"], fg=t["text"],
                                          padx=14, pady=10, anchor="w",
                                          font=("Segoe UI", 10))
        self.status_label.pack(fill="x")

        self.help_label = self.tk.Label(status_frame, textvariable=self.help_var,
                                        bg=t["panel"], fg=t["muted"],
                                        padx=4, pady=8, justify="left",
                                        wraplength=340, anchor="w",
                                        font=("Segoe UI", 9))
        self.help_label.pack(fill="x")

        utility = self.ttk.Frame(self.env_body, style="Card.TFrame", padding=(0, 10, 0, 0))
        utility.grid(row=2, column=0, sticky="ew")
        utility.columnconfigure(0, weight=1)
        utility.columnconfigure(1, weight=1)
        utility.columnconfigure(2, weight=1)
        self.copy_button = self._action_button(utility, "Copy Result", self._copy_result,
                                               "Ghost.TButton", 0, 0)
        self.open_folder_button = self._action_button(utility, "Open Folder", self._open_last_folder,
                                                      "Ghost.TButton", 0, 1)
        self.open_folder_button.state(["disabled"])
        self.quit_button = self._action_button(utility, "Quit", self.root.destroy,
                                               "Ghost.TButton", 0, 2)
        self._sync_environment_panel()

    def _toggle_environment_panel(self) -> None:
        self._env_expanded = not self._env_expanded
        self._sync_environment_panel()

    def _sync_environment_panel(self) -> None:
        label = "\u25be Hide Details" if self._env_expanded else "\u25b8 Show Details"
        self.env_toggle_button.configure(text=label)
        if self._env_expanded:
            self.env_body.grid()
        else:
            self.env_body.grid_remove()

    def _render_environment(self) -> None:
        t = self._t
        rows = [
            ("Repo root", self.state["repo_root"]),
            ("Claude Code", self.state["claude_code_display"]),
            ("Desktop config", self.state["windows_claude_desktop_config"] or "not found"),
            ("Code config", self.state["windows_claude_code_config"] or "not found"),
            ("WSL distro", self.state["wsl_distro"] or "not detected"),
        ]
        for index, (label, value) in enumerate(rows):
            row_frame = self.tk.Frame(self.env_frame, bg=t["panel_alt"],
                                      highlightbackground=t["line"], highlightthickness=1)
            row_frame.grid(row=index, column=0, sticky="ew", pady=(0, 6))
            row_frame.columnconfigure(0, weight=0)
            row_frame.columnconfigure(1, weight=1)
            self.tk.Label(row_frame, text=label, bg=t["panel_alt"], fg=t["muted"],
                          font=("Segoe UI", 9, "bold"), anchor="w",
                          width=14).grid(row=0, column=0, sticky="w", padx=(10, 6), pady=8)
            self.tk.Label(row_frame, text=value, bg=t["panel_alt"], fg=t["text"],
                          font=("Segoe UI", 9), anchor="w",
                          wraplength=260, justify="left").grid(row=0, column=1, sticky="w",
                                                                padx=(0, 10), pady=8)

    # -- form builders -------------------------------------------------------

    def _build_candidate_selector(self, parent: Any, row: int) -> None:
        frame = self.ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        frame.columnconfigure(0, weight=1)
        self.ttk.Label(frame, text="Detected memory stores",
                       style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w")
        values = [r["display_label"] for r in self.state["memory_candidates"]]
        if not values:
            values = ["No known stores detected"]
        self.memory_combo = self.ttk.Combobox(frame, textvariable=self.memory_choice_var,
                                              values=values, state="readonly",
                                              style="NO.TCombobox")
        self.memory_combo.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.memory_combo.bind("<<ComboboxSelected>>", self._on_memory_choice)
        self.ttk.Label(frame, text="Pick a known store or browse to another file below.",
                       style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))

    def _build_path_field(
        self,
        parent: Any,
        row: int,
        *,
        label: str,
        variable: Any,
        browse_command: Callable[[], None],
        clear_command: Callable[[], None] | None,
        help_key: str | None = None,
    ) -> None:
        t = self._t
        frame = self.ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        frame.columnconfigure(0, weight=1)

        label_row = self.tk.Frame(frame, bg=t["panel"])
        label_row.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.tk.Label(label_row, text=label, bg=t["panel"], fg=t["text"],
                      font=("Segoe UI", 10, "bold")).pack(side="left")
        if help_key:
            self._make_info_badge(label_row, HELP_TEXT[help_key]).pack(side="left", padx=(8, 0))

        entry = self.tk.Entry(frame, textvariable=variable, relief="flat", bd=0, highlightthickness=1)
        entry.grid(row=1, column=0, sticky="ew", pady=(6, 0), ipady=8)
        entry.configure(bg=t["input"], fg=t["text"], insertbackground=t["accent"],
                        highlightbackground=t["line"], highlightcolor=t["accent"])

        browse = self.ttk.Button(frame, text="Browse\u2026", command=browse_command,
                                 style="Ghost.TButton")
        browse.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        if clear_command is not None:
            clear = self.ttk.Button(frame, text="Clear", command=clear_command,
                                    style="Ghost.TButton")
            clear.grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=(6, 0))

    def _build_labeled_entry(self, parent: Any, row: int, column: int, label: str,
                             variable: Any, *, help_key: str | None = None) -> None:
        t = self._t
        frame = self.ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=row, column=column, sticky="ew",
                   padx=(0, 8) if column == 0 else (8, 0), pady=(10, 0))
        frame.columnconfigure(0, weight=1)

        label_row = self.tk.Frame(frame, bg=t["panel"])
        label_row.grid(row=0, column=0, sticky="ew")
        self.tk.Label(label_row, text=label, bg=t["panel"], fg=t["text"],
                      font=("Segoe UI", 10, "bold")).pack(side="left")
        if help_key:
            self._make_info_badge(label_row, HELP_TEXT[help_key]).pack(side="left", padx=(8, 0))

        entry = self.tk.Entry(frame, textvariable=variable, relief="flat", bd=0, highlightthickness=1)
        entry.grid(row=1, column=0, sticky="ew", pady=(6, 0), ipady=8)
        entry.configure(bg=t["input"], fg=t["text"], insertbackground=t["accent"],
                        highlightbackground=t["line"], highlightcolor=t["accent"])

    def _build_labeled_combo(self, parent: Any, row: int, column: int, label: str,
                             variable: Any, values: list[str], *, help_key: str) -> None:
        t = self._t
        frame = self.ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=row, column=column, sticky="ew",
                   padx=(0, 8) if column == 0 else (8, 0), pady=(10, 0))
        frame.columnconfigure(0, weight=1)

        label_row = self.tk.Frame(frame, bg=t["panel"])
        label_row.grid(row=0, column=0, sticky="ew")
        self.tk.Label(label_row, text=label, bg=t["panel"], fg=t["text"],
                      font=("Segoe UI", 10, "bold")).pack(side="left")
        self._make_info_badge(label_row, HELP_TEXT[help_key]).pack(side="left", padx=(8, 0))

        combo = self.ttk.Combobox(frame, textvariable=variable, values=values,
                                  state="readonly", style="NO.TCombobox")
        combo.grid(row=1, column=0, sticky="ew", pady=(6, 0))

    def _build_checkbox(
        self,
        parent: Any,
        row: int,
        column: int,
        label: str,
        variable: Any,
        *,
        help_key: str,
        check_text: str,
    ) -> None:
        t = self._t
        frame = self.ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=row, column=column, sticky="ew", padx=(8, 0), pady=(10, 0))

        label_row = self.tk.Frame(frame, bg=t["panel"])
        label_row.grid(row=0, column=0, sticky="w")
        self.tk.Label(label_row, text=label, bg=t["panel"], fg=t["text"],
                      font=("Segoe UI", 10, "bold")).pack(side="left")
        self._make_info_badge(label_row, HELP_TEXT[help_key]).pack(side="left", padx=(8, 0))

        check = self.ttk.Checkbutton(frame, variable=variable, text=check_text,
                                     style="NO.TCheckbutton")
        check.grid(row=1, column=0, sticky="w", pady=(6, 0))

    # -- info badges & tooltips ----------------------------------------------

    def _make_info_badge(self, parent: Any, text: str) -> Any:
        badge = self.ttk.Button(parent, text="?", style="Info.TButton", takefocus=True)
        badge.configure(command=lambda t=text: self._show_help_dialog(t))
        badge.bind("<Enter>", lambda _event, t=text, w=badge: self._show_tooltip(w, t))
        badge.bind("<Leave>", lambda _event: self._hide_tooltip())
        badge.bind("<FocusIn>", lambda _event, t=text, w=badge: self._show_tooltip(w, t))
        badge.bind("<FocusOut>", lambda _event: self._hide_tooltip())
        self._info_badges.append(badge)
        return badge

    def _show_tooltip(self, widget: Any, text: str) -> None:
        t = self._t
        self._hide_tooltip()
        tip = self.tk.Toplevel(self.root)
        tip.wm_overrideredirect(True)
        tip.configure(bg=t["accent"])
        inner = self.tk.Frame(tip, bg=t["panel_alt"], padx=1, pady=1)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        x = widget.winfo_rootx() + widget.winfo_width() + 8
        y = widget.winfo_rooty() - 4
        tip.wm_geometry(f"+{x}+{y}")
        label = self.tk.Label(inner, text=text, bg=t["panel_alt"], fg=t["text"],
                              padx=12, pady=8, justify="left", wraplength=280,
                              font=("Segoe UI", 9))
        label.pack()
        self._tooltip_window = tip

    def _hide_tooltip(self) -> None:
        if self._tooltip_window is not None:
            self._tooltip_window.destroy()
            self._tooltip_window = None
        self.help_var.set(DEFAULT_HELP_PROMPT)

    def _show_help_dialog(self, text: str) -> None:
        self.messagebox.showinfo("What this means", text, parent=self.root)

    # -- buttons -------------------------------------------------------------

    def _action_button(self, parent: Any, text: str, command: Callable[[], None],
                       style: str, row: int, column: int) -> Any:
        button = self.ttk.Button(parent, text=text, command=command, style=style)
        button.grid(row=row, column=column, padx=3, pady=3, sticky="ew")
        parent.columnconfigure(column, weight=1)
        return button

    # -- binding initial values ----------------------------------------------

    def _bind_initial_values(self) -> None:
        candidates = self.state["memory_candidates"]
        if candidates:
            self.memory_choice_var.set(candidates[0]["display_label"])
            self.memory_path_var.set(candidates[0]["path"])
        else:
            self.memory_choice_var.set("No known stores detected")
            self.memory_path_var.set(self.state["default_memory_path"])
        self.episodes_path_var.set(self.state["default_episodes_path"])
        self.server_name_var.set(self.state["server_name"])
        self.scope_var.set(self.state["claude_code_scope"])
        self.wsl_distro_var.set(self.state["wsl_distro"])

    # -- payload collection --------------------------------------------------

    def _collect_payload(self) -> dict[str, Any]:
        return {
            "memories_path": self.memory_path_var.get().strip(),
            "episodes_path": self.episodes_path_var.get().strip(),
            "server_name": self.server_name_var.get().strip(),
            "default_role": self.default_role_var.get(),
            "claude_code_scope": self.scope_var.get(),
            "compat_mode": self.compat_var.get(),
            "wsl_distro": self.wsl_distro_var.get().strip(),
            "mutations_enabled": bool(self.mutations_var.get()),
        }

    # -- file dialogs --------------------------------------------------------

    def _browse_memory(self) -> None:
        current = self.memory_path_var.get().strip()
        path = self.filedialog.askopenfilename(parent=self.root, title="Choose a memory store",
                                               initialdir=self._initial_dir(current),
                                               filetypes=MEMORY_FILETYPES)
        if path:
            self.memory_path_var.set(path)
            self.memory_choice_var.set("Manual file selection")

    def _browse_episodes(self) -> None:
        current = self.episodes_path_var.get().strip()
        path = self.filedialog.askopenfilename(parent=self.root, title="Choose episode cards JSON",
                                               initialdir=self._initial_dir(current),
                                               filetypes=EPISODE_FILETYPES)
        if path:
            self.episodes_path_var.set(path)

    def _clear_episodes(self) -> None:
        self.episodes_path_var.set("")

    # -- actions -------------------------------------------------------------

    def _run_preview(self) -> None:
        self._run_action("Building preview\u2026",
                         lambda: self.controller.build_preview(self._collect_payload()),
                         success_message="Preview ready.")

    def _run_install_claude_code(self) -> None:
        self._run_action("Installing Claude Code MCP\u2026",
                         lambda: self.controller.install_claude_code(self._collect_payload()),
                         success_message="Claude Code MCP installed.",
                         open_path_key="windows_claude_code_config")

    def _run_install_claude_desktop(self) -> None:
        self._run_action("Updating Claude Desktop config\u2026",
                         lambda: self.controller.install_claude_desktop(self._collect_payload()),
                         success_message="Claude Desktop config updated.",
                         open_path_key="config_path")

    def _run_remove_claude_code(self) -> None:
        self._run_action("Removing Claude Code MCP\u2026",
                         lambda: self.controller.remove_claude_code(self._collect_payload()),
                         success_message="Claude Code MCP removed.",
                         open_path_key="windows_claude_code_config")

    def _run_remove_claude_desktop(self) -> None:
        self._run_action("Removing Claude Desktop MCP\u2026",
                         lambda: self.controller.remove_claude_desktop(self._collect_payload()),
                         success_message="Claude Desktop MCP removed.",
                         open_path_key="config_path")

    def _run_export(self) -> None:
        default_name = f"numquamoblita_mcp_bundle_{self.server_name_var.get().strip() or DEFAULT_SERVER_NAME}.json"
        target = self.filedialog.asksaveasfilename(
            parent=self.root,
            title="Save MCP export bundle",
            initialdir=self._initial_dir(self.memory_path_var.get().strip()),
            initialfile=default_name,
            defaultextension=".json",
            filetypes=EXPORT_FILETYPES,
        )
        if not target:
            self._set_status("Export canceled.", kind="ready")
            return
        target_path = Path(target)
        if target_path.exists() and not self.controller.export_bundle_has_connector_signature(target_path):
            confirmed = self.messagebox.askyesno(
                "Overwrite existing file?",
                "That export file already exists and was not generated by this connector. Overwrite it anyway?",
                parent=self.root,
            )
            if not confirmed:
                self._set_status("Export canceled.", kind="ready")
                return
        self._run_action("Writing export bundle\u2026",
                         lambda: self.controller.save_export_bundle(self._collect_payload(),
                                                                    export_path=target_path),
                         success_message="Export bundle written.",
                         open_path_key="export_path")

    def _run_action(
        self,
        working_message: str,
        action: Callable[[], dict[str, Any]],
        *,
        success_message: str,
        open_path_key: str | None = None,
    ) -> None:
        self._set_busy(True)
        self._set_status(working_message, kind="busy")

        def _worker() -> None:
            try:
                result = action()
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self._finish_action(error=str(exc)))
                return
            self.root.after(0, lambda: self._finish_action(result=result,
                                                           success_message=success_message,
                                                           open_path_key=open_path_key))

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_action(
        self,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        success_message: str = "Done.",
        open_path_key: str | None = None,
    ) -> None:
        self._set_busy(False)
        if error is not None:
            self._set_status(error, kind="error")
            self._set_output({"ok": False, "error": error})
            self.messagebox.showerror("NumquamOblita MCP Connector", error, parent=self.root)
            return
        payload = dict(result or {})
        self._set_output(payload)
        self._set_status(success_message, kind="ok")
        self._last_open_path = ""
        if open_path_key and str(payload.get(open_path_key) or "").strip():
            self._last_open_path = str(payload.get(open_path_key) or "").strip()
        elif str(payload.get("export_path") or "").strip():
            self._last_open_path = str(payload.get("export_path") or "").strip()
        self.open_folder_button.state(["!disabled"] if self._last_open_path else ["disabled"])

    # -- utility actions -----------------------------------------------------

    def _copy_result(self) -> None:
        if not self._last_result_text:
            self._set_status("Nothing to copy yet.", kind="ready")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self._last_result_text)
        self._set_status("Copied result to clipboard.", kind="ok")

    def _open_last_folder(self) -> None:
        if not self._last_open_path:
            self._set_status("Nothing to open yet.", kind="ready")
            return
        target = Path(self._last_open_path)
        folder = target if target.is_dir() else target.parent
        try:
            os.startfile(str(folder))
        except Exception as exc:  # noqa: BLE001
            self.messagebox.showerror("Unable to open folder", str(exc), parent=self.root)

    def _on_memory_choice(self, _event: Any = None) -> None:
        choice = self.memory_choice_var.get().strip()
        for row in self.state["memory_candidates"]:
            if row["display_label"] == choice:
                self.memory_path_var.set(row["path"])
                return

    # -- state management ----------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        for button in self._action_buttons:
            button.state(["disabled"] if busy else ["!disabled"])
        self.copy_button.state(["disabled"] if busy else ["!disabled"])
        self.quit_button.state(["disabled"] if busy else ["!disabled"])

    def _set_output(self, payload: dict[str, Any]) -> None:
        self._last_result_text = json.dumps(payload, indent=2, ensure_ascii=False)
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", self._last_result_text)
        self.output_text.configure(state="disabled")

    def _set_status(self, text: str, *, kind: str) -> None:
        t = self._t
        self._last_status_kind = kind
        bg_map = {
            "ready": t["accent_soft"],
            "busy":  t["busy_bg"],
            "ok":    t["ok_bg"],
            "error": t["error_bg"],
        }
        fg_map = {
            "ready": t["text"],
            "busy":  t["info"],
            "ok":    t["ok"],
            "error": t["error"],
        }
        self.status_var.set(text)
        self.status_label.configure(bg=bg_map.get(kind, t["accent_soft"]),
                                    fg=fg_map.get(kind, t["text"]))

    def _initial_dir(self, current: str) -> str:
        if current:
            path = Path(current)
            candidate = path if path.is_dir() else path.parent
            if candidate.exists():
                return str(candidate)
        return str(self.controller.repo_root)

    def _center_window(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = max((self.root.winfo_screenwidth() - width) // 2, 40)
        y = max((self.root.winfo_screenheight() - height) // 2, 40)
        self.root.geometry(f"{width}x{height}+{x}+{y}")


# ---------------------------------------------------------------------------
#  WSL launch helpers
# ---------------------------------------------------------------------------

def build_wsl_proxy_launch_cmd(*, cmd_windows_path: str) -> list[str]:
    return ["cmd.exe", "/c", "start", "", cmd_windows_path]



def _wsl_to_windows_path(path: Path, *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> str:
    proc = runner(["wslpath", "-w", str(path)], check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = str(proc.stderr or "").strip() or str(proc.stdout or "").strip() or "unknown error"
        raise RuntimeError(f"unable to translate WSL path for Windows launch: {stderr}")
    converted = str(proc.stdout or "").strip()
    if not converted:
        raise RuntimeError("unable to translate WSL path for Windows launch")
    return converted



def launch_windows_gui_from_wsl(
    *,
    cmd_path: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    cmd_windows_path = _wsl_to_windows_path(cmd_path, runner=runner)
    launch_cmd = build_wsl_proxy_launch_cmd(cmd_windows_path=cmd_windows_path)
    # In WSL, `cmd.exe /c start` can block when invoked via subprocess.run with captured pipes.
    # Use fire-and-forget launch for the default runtime path, while keeping runner-injected
    # behavior for tests.
    if runner is subprocess.run:
        proc = subprocess.Popen(launch_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        return {"ok": True, "launch_cmd": launch_cmd, "cmd_windows_path": cmd_windows_path, "pid": int(proc.pid)}

    proc = runner(launch_cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = str(proc.stderr or "").strip() or str(proc.stdout or "").strip() or "unknown error"
        raise RuntimeError(f"unable to start Windows GUI launcher: {stderr}")
    return {"ok": True, "launch_cmd": launch_cmd, "cmd_windows_path": cmd_windows_path}



def main() -> int:
    if not is_windows_platform():
        if is_wsl_environment():
            try:
                launch_windows_gui_from_wsl(cmd_path=Path(__file__).with_suffix(".cmd"))
            except Exception as exc:  # noqa: BLE001
                print(f"NumquamOblita MCP Connector must be launched from Windows. {exc}", file=sys.stderr)
                return 2
            return 0
        print("NumquamOblita MCP Connector must be launched from Windows.", file=sys.stderr)
        return 2

    try:
        window = ConnectorWindow(ConnectorControlPanel(repo_root=REPO_ROOT, python_path=sys.executable))
    except Exception as exc:  # noqa: BLE001
        print(f"error={exc}", file=sys.stderr)
        return 2
    return window.run()


if __name__ == "__main__":
    raise SystemExit(main())
