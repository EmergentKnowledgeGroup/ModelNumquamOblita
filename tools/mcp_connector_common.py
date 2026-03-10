#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVER_NAME = "numquamoblita-live"
WINDOWS_WSL_COMMAND = r"C:\Windows\System32\wsl.exe"
WINDOWS_USERS_ROOT_WSL = Path("/mnt/c/Users")
WINDOWS_CLAUDE_DESKTOP_REL = Path("AppData/Roaming/Claude/claude_desktop_config.json")
WINDOWS_CLAUDE_CODE_REL = Path(".claude.json")
_WINDOWS_USER_EXCLUDE = {"All Users", "Default", "Default User", "Public", "defaultuser0"}
SUPPORTED_MEMORY_SUFFIXES = {".sqlite3", ".sqlite", ".db", ".json"}


def _path_text(value: str | Path | None) -> str:
    if value is None:
        return ""
    return str(value).strip()



def is_windows_platform(*, env: Mapping[str, str] | None = None) -> bool:
    env_map = dict(env or os.environ)
    if str(env_map.get("OS") or "").strip().lower() == "windows_nt":
        return True
    return os.name == "nt"



def is_wsl_environment(*, env: Mapping[str, str] | None = None, release: str | None = None) -> bool:
    env_map = dict(env or os.environ)
    if str(env_map.get("WSL_DISTRO_NAME") or "").strip():
        return True
    kernel_release = str(release or platform.release() or "").lower()
    return "microsoft" in kernel_release or "wsl" in kernel_release



def windows_users_root(*, env: Mapping[str, str] | None = None) -> Path:
    env_map = dict(env or os.environ)
    if is_windows_platform(env=env_map):
        user_profile = str(env_map.get("USERPROFILE") or "").strip()
        if user_profile:
            return Path(user_profile).expanduser().resolve().parent
        return Path.home().resolve().parent
    return WINDOWS_USERS_ROOT_WSL



def windows_wsl_command() -> str:
    if is_windows_platform():
        return str(shutil.which("wsl.exe") or shutil.which("wsl") or WINDOWS_WSL_COMMAND)
    linux_path = Path("/mnt/c/Windows/System32/wsl.exe")
    if linux_path.exists():
        return str(linux_path)
    return WINDOWS_WSL_COMMAND



def default_memory_path(*, repo_root: Path = REPO_ROOT) -> Path:
    sqlite_default = repo_root / ".runtime" / "imports" / "atoms.sqlite3"
    if sqlite_default.exists():
        return sqlite_default
    imports_dir = repo_root / "runtime" / "imports"
    if imports_dir.exists():
        candidates = sorted(imports_dir.rglob("memories.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return sqlite_default



def default_episode_cards_path(*, repo_root: Path = REPO_ROOT) -> Path | None:
    episodes_dir = repo_root / "runtime" / "episodes"
    if not episodes_dir.exists():
        return None
    reviewed = episodes_dir / "episode_cards.reviewed.json"
    if reviewed.exists():
        return reviewed
    reviewed_candidates = sorted(
        episodes_dir.glob("episode_cards.reviewed_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if reviewed_candidates:
        return reviewed_candidates[0]
    candidates = sorted(
        (
            path
            for path in episodes_dir.glob("episode_cards_*.json")
            if not path.name.endswith(".rejects.json")
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    manual = episodes_dir / "episode_cards.json"
    if manual.exists():
        return manual
    return None



def resolve_episode_cards_path(raw: str, *, repo_root: Path = REPO_ROOT) -> Path | None:
    if str(raw or "").strip():
        return Path(raw).expanduser().resolve()
    return default_episode_cards_path(repo_root=repo_root)



def discover_memory_candidates(*, repo_root: Path = REPO_ROOT) -> list[dict[str, str]]:
    seen: set[Path] = set()
    rows: list[tuple[int, float, dict[str, str]]] = []

    def _append(path: Path, *, label: str, source: str, priority: int) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        if not resolved.exists() or resolved in seen or not resolved.is_file():
            return
        if resolved.suffix.lower() not in SUPPORTED_MEMORY_SUFFIXES:
            return
        seen.add(resolved)
        try:
            mtime = resolved.stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append(
            (
                int(priority),
                float(mtime),
                {
                    "label": label,
                    "path": str(resolved),
                    "source": source,
                    "kind": resolved.suffix.lower().lstrip("."),
                },
            )
        )

    runtime_stores = repo_root / "runtime" / "stores"
    known_named = [
        (runtime_stores / "claude_no.sqlite3", "Claude test store", "runtime/stores", 0),
        (runtime_stores / "no_lyra.sqlite3", "Lyra store", "runtime/stores", 1),
        (default_memory_path(repo_root=repo_root), "Default import store", "runtime imports", 2),
    ]
    for path, label, source, priority in known_named:
        _append(path, label=label, source=source, priority=priority)

    for base, source in (
        (runtime_stores, "runtime/stores"),
        (repo_root / ".runtime" / "imports", ".runtime/imports"),
        (repo_root / "runtime" / "imports", "runtime/imports"),
    ):
        if not base.exists():
            continue
        for pattern in ("*.sqlite3", "*.sqlite", "*.db", "*.json"):
            for path in sorted(base.glob(pattern)):
                _append(path, label=path.name, source=source, priority=10)

    rows.sort(key=lambda item: (item[0], -item[1], item[2]["label"].lower()))
    return [row for _, _, row in rows]



def format_memory_candidate_label(candidate: Mapping[str, str], *, duplicates: Counter[str] | None = None) -> str:
    label = str(candidate.get("label") or candidate.get("path") or "memory store").strip()
    source = str(candidate.get("source") or "").strip()
    path = str(candidate.get("path") or "").strip()
    needs_path = bool(duplicates and duplicates[label.lower()] > 1)
    if needs_path and path:
        return f"{label} [{source}] - {path}"
    if source:
        return f"{label} [{source}]"
    return label



def memory_candidate_labels(candidates: Iterable[Mapping[str, str]]) -> list[str]:
    rows = list(candidates)
    counts = Counter(str(row.get("label") or row.get("path") or "").strip().lower() for row in rows)
    return [format_memory_candidate_label(row, duplicates=counts) for row in rows]



def build_launcher_cli_args(
    *,
    launcher_path: str,
    memories_path: str | Path,
    episodes_path: str | Path | None,
    default_role: str,
    compat_mode: str,
    mutations_enabled: bool,
) -> list[str]:
    args = [
        str(launcher_path),
        "--memories",
        _path_text(memories_path),
        "--default-role",
        str(default_role),
        "--compat-mode",
        str(compat_mode),
    ]
    if episodes_path is not None and _path_text(episodes_path):
        args.extend(["--episodes", _path_text(episodes_path)])
    if mutations_enabled:
        args.append("--mutations-enabled")
    return args



def build_posix_stdio_entry(
    *,
    python_path: str,
    memories_path: str | Path,
    episodes_path: str | Path | None,
    default_role: str,
    compat_mode: str,
    mutations_enabled: bool,
    launcher_path: str | None = None,
) -> dict[str, Any]:
    command = str(python_path or "python3").strip() or "python3"
    if "/" in command or "\\" in command:
        try:
            command = str(Path(command).expanduser().resolve())
        except OSError:
            pass
    launcher = str(launcher_path or (REPO_ROOT / "tools" / "run_claude_live_mcp.py").resolve()).strip()
    return {
        "command": command,
        "args": build_launcher_cli_args(
            launcher_path=launcher,
            memories_path=memories_path,
            episodes_path=episodes_path,
            default_role=default_role,
            compat_mode=compat_mode,
            mutations_enabled=mutations_enabled,
        ),
    }



def _parse_wsl_unc_path(raw: str) -> tuple[str, str] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("/", "\\")
    lower = normalized.lower()
    prefixes = ("\\\\wsl$\\", "\\\\wsl.localhost\\")
    for prefix in prefixes:
        if not lower.startswith(prefix.lower()):
            continue
        tail = normalized[len(prefix) :]
        distro, _, rest = tail.partition("\\")
        distro = distro.strip()
        rest = rest.strip("\\")
        if not distro or not rest:
            return None
        return distro, "/" + rest.replace("\\", "/")
    return None



def wsl_path_from_windows(
    raw_path: str | Path,
    *,
    distro_name: str = "",
    runner: Any = subprocess.run,
) -> tuple[str, str]:
    raw = _path_text(raw_path)
    if not raw:
        raise ValueError("path is required")
    inferred_distro = str(distro_name or "").strip()
    unc = _parse_wsl_unc_path(raw)
    if unc is not None:
        unc_distro, posix_path = unc
        return posix_path, inferred_distro or unc_distro
    if raw.startswith("/"):
        return raw, inferred_distro
    convert_source = raw.replace("\\", "/") if ":" in raw[:3] else raw
    cmd = [windows_wsl_command()]
    if inferred_distro:
        cmd.extend(["-d", inferred_distro])
    cmd.extend(["wslpath", "-a", convert_source])
    proc = runner(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = str(proc.stderr or "").strip() or str(proc.stdout or "").strip() or "unknown error"
        raise ValueError(f"unable to convert Windows path to WSL path: {stderr}")
    converted = str(proc.stdout or "").strip()
    if not converted:
        raise ValueError("unable to convert Windows path to WSL path")
    return converted, inferred_distro



def build_windows_wsl_stdio_entry(
    *,
    repo_root: str | Path,
    memories_path: str | Path,
    episodes_path: str | Path | None,
    default_role: str,
    compat_mode: str,
    mutations_enabled: bool,
    distro_name: str,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    repo_root_arg, distro = wsl_path_from_windows(repo_root, distro_name=distro_name, runner=runner)
    memories_arg, distro = wsl_path_from_windows(memories_path, distro_name=distro, runner=runner)
    episodes_arg: str | None = None
    if episodes_path is not None and _path_text(episodes_path):
        episodes_arg, distro = wsl_path_from_windows(episodes_path, distro_name=distro, runner=runner)
    args: list[str] = []
    if distro:
        args.extend(["-d", distro])
    args.extend(["--cd", repo_root_arg, "--exec", "python3"])
    args.extend(
        build_launcher_cli_args(
            launcher_path="tools/run_claude_live_mcp.py",
            memories_path=memories_arg,
            episodes_path=episodes_arg,
            default_role=default_role,
            compat_mode=compat_mode,
            mutations_enabled=mutations_enabled,
        )
    )
    return {
        "command": WINDOWS_WSL_COMMAND,
        "args": args,
    }



def build_mcp_servers_payload(*, server_name: str, entry: dict[str, Any]) -> dict[str, Any]:
    return {"mcpServers": {str(server_name): dict(entry)}}



def merge_mcp_server_entry(existing: dict[str, Any] | None, *, server_name: str, entry: dict[str, Any]) -> dict[str, Any]:
    payload = dict(existing or {})
    raw_servers = payload.get("mcpServers")
    servers = dict(raw_servers) if isinstance(raw_servers, dict) else {}
    servers[str(server_name)] = dict(entry)
    payload["mcpServers"] = servers
    return payload


def remove_mcp_server_entry(existing: dict[str, Any] | None, *, server_name: str) -> tuple[dict[str, Any], bool]:
    payload = dict(existing or {})
    raw_servers = payload.get("mcpServers")
    servers = dict(raw_servers) if isinstance(raw_servers, dict) else {}
    removed = str(server_name) in servers
    servers.pop(str(server_name), None)
    payload["mcpServers"] = servers
    return payload, removed



def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload



def _backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return path.with_name(f"{path.name}.bak.{stamp}")



def write_json_with_backup(path: Path, payload: dict[str, Any]) -> Path | None:
    backup_path: Path | None = None
    if path.exists():
        backup_path = _backup_path(path)
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return backup_path



def candidate_windows_user_dirs(*, users_root: Path | None = None) -> list[Path]:
    root = users_root or windows_users_root()
    if not root.exists():
        return []
    candidates = []
    for path in root.iterdir():
        if not path.is_dir():
            continue
        if path.name in _WINDOWS_USER_EXCLUDE:
            continue
        candidates.append(path)
    candidates.sort(key=lambda path: path.name.lower())
    return candidates



def find_windows_claude_desktop_config(*, users_root: Path | None = None) -> Path | None:
    matches: list[Path] = []
    for user_dir in candidate_windows_user_dirs(users_root=users_root):
        candidate = user_dir / WINDOWS_CLAUDE_DESKTOP_REL
        if candidate.exists():
            matches.append(candidate)
    if matches:
        matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return matches[0]
    user_profile = str(os.environ.get("USERPROFILE") or "").strip()
    if user_profile:
        return Path(user_profile).expanduser().resolve() / WINDOWS_CLAUDE_DESKTOP_REL
    user_name = str(os.environ.get("USERNAME") or "").strip()
    if user_name:
        return (users_root or windows_users_root()) / user_name / WINDOWS_CLAUDE_DESKTOP_REL
    return None



def find_windows_claude_code_config(*, users_root: Path | None = None) -> Path | None:
    matches: list[Path] = []
    for user_dir in candidate_windows_user_dirs(users_root=users_root):
        candidate = user_dir / WINDOWS_CLAUDE_CODE_REL
        if candidate.exists():
            matches.append(candidate)
    if matches:
        matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return matches[0]
    user_profile = str(os.environ.get("USERPROFILE") or "").strip()
    if user_profile:
        return Path(user_profile).expanduser().resolve() / WINDOWS_CLAUDE_CODE_REL
    user_name = str(os.environ.get("USERNAME") or "").strip()
    if user_name:
        return (users_root or windows_users_root()) / user_name / WINDOWS_CLAUDE_CODE_REL
    return None



def detect_wsl_distro(
    *,
    env: Mapping[str, str] | None = None,
    runner: Any = subprocess.run,
) -> str:
    env_map = dict(env or os.environ)
    current = str(env_map.get("WSL_DISTRO_NAME") or "").strip()
    if current:
        return current
    wsl_command = windows_wsl_command()
    proc = runner([wsl_command, "-l", "-q"], check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return ""
    for raw in str(proc.stdout or "").splitlines():
        name = raw.replace("\x00", "").strip()
        if not name or name.lower().startswith("docker"):
            continue
        return name
    return ""



def ensure_valid_server_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("server name is required")
    allowed = {"-", "_"}
    if any((not ch.isalnum()) and ch not in allowed for ch in name):
        raise ValueError("server name must use only letters, numbers, hyphens, or underscores")
    return name



def build_claude_code_add_json_cmd(
    *,
    server_name: str,
    entry: dict[str, Any],
    scope: str,
    claude_bin: str = "claude",
) -> list[str]:
    normalized_scope = str(scope or "local").strip() or "local"
    return [
        str(claude_bin),
        "mcp",
        "add-json",
        "-s",
        normalized_scope,
        ensure_valid_server_name(server_name),
        json.dumps(entry, separators=(",", ":"), ensure_ascii=False),
    ]



def build_claude_code_remove_cmd(*, server_name: str, scope: str, claude_bin: str = "claude") -> list[str]:
    normalized_scope = str(scope or "local").strip() or "local"
    return [str(claude_bin), "mcp", "remove", ensure_valid_server_name(server_name), "-s", normalized_scope]



def install_claude_code_server(
    *,
    server_name: str,
    entry: dict[str, Any],
    scope: str,
    claude_bin: str = "claude",
    runner: Any = subprocess.run,
    which: Any = shutil.which,
) -> dict[str, Any]:
    if which(str(claude_bin)) is None:
        raise RuntimeError(f"claude CLI not found: {claude_bin}")
    remove_cmd = build_claude_code_remove_cmd(server_name=server_name, scope=scope, claude_bin=claude_bin)
    remove_proc = runner(remove_cmd, check=False, capture_output=True, text=True)
    add_cmd = build_claude_code_add_json_cmd(server_name=server_name, entry=entry, scope=scope, claude_bin=claude_bin)
    add_proc = runner(add_cmd, check=False, capture_output=True, text=True)
    if add_proc.returncode != 0:
        stderr = str(add_proc.stderr or "").strip() or str(add_proc.stdout or "").strip() or "unknown error"
        raise RuntimeError(f"claude mcp add-json failed: {stderr}")
    return {
        "remove_returncode": int(remove_proc.returncode),
        "remove_stdout": str(remove_proc.stdout or "").strip(),
        "remove_stderr": str(remove_proc.stderr or "").strip(),
        "add_returncode": int(add_proc.returncode),
        "add_stdout": str(add_proc.stdout or "").strip(),
        "add_stderr": str(add_proc.stderr or "").strip(),
        "scope": str(scope or "local").strip() or "local",
    }


def remove_claude_code_server(
    *,
    server_name: str,
    scope: str,
    claude_bin: str = "claude",
    runner: Any = subprocess.run,
    which: Any = shutil.which,
) -> dict[str, Any]:
    if which(str(claude_bin)) is None:
        raise RuntimeError(f"claude CLI not found: {claude_bin}")
    remove_cmd = build_claude_code_remove_cmd(server_name=server_name, scope=scope, claude_bin=claude_bin)
    remove_proc = runner(remove_cmd, check=False, capture_output=True, text=True)
    stdout = str(remove_proc.stdout or "").strip()
    stderr = str(remove_proc.stderr or "").strip()
    lowered = f"{stdout}\n{stderr}".lower()
    missing = (
        "no user-scoped mcp server found" in lowered
        or "no project-scoped mcp server found" in lowered
        or "no local-scoped mcp server found" in lowered
    )
    if remove_proc.returncode != 0 and not missing:
        detail = stderr or stdout or "unknown error"
        raise RuntimeError(f"claude mcp remove failed: {detail}")
    return {
        "remove_returncode": int(remove_proc.returncode),
        "remove_stdout": stdout,
        "remove_stderr": stderr,
        "scope": str(scope or "local").strip() or "local",
        "removed": not missing,
    }
