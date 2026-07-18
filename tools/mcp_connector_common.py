#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping
from uuid import uuid4

from tools.preflight import PYTHON_BOOTSTRAP_PROBE, _default_memories

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVER_NAME = "numquamoblita-live"
DEFAULT_HTTP_MCP_URL = "http://127.0.0.1:8765/mcp"
WINDOWS_WSL_COMMAND = r"C:\Windows\System32\wsl.exe"
WINDOWS_USERS_ROOT_WSL = Path("/mnt/c/Users")
WINDOWS_CLAUDE_DESKTOP_REL = Path("AppData/Roaming/Claude/claude_desktop_config.json")
WINDOWS_CLAUDE_CODE_REL = Path(".claude.json")
_WINDOWS_USER_EXCLUDE = {"All Users", "Default", "Default User", "Public", "defaultuser0"}
SUPPORTED_MEMORY_SUFFIXES = {".sqlite3", ".sqlite", ".db", ".json"}
WSL_PYTHON_CANDIDATES = tuple(
    f"{prefix}/python3{suffix}"
    for suffix in (".15", ".14", ".13", ".12", "")
    for prefix in ("/usr/bin", "/usr/local/bin")
)


def _path_text(value: str | Path | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _windows_hidden_subprocess_kwargs() -> dict[str, Any]:
    if not is_windows_platform():
        return {}
    kwargs: dict[str, Any] = {}
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is not None:
        startupinfo = startupinfo_cls()
        startf_use_showwindow = int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0) or 0)
        if startf_use_showwindow:
            startupinfo.dwFlags |= startf_use_showwindow
        try:
            startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0) or 0)
        except Exception:
            pass
        kwargs["startupinfo"] = startupinfo
    return kwargs


def run_subprocess_hidden_on_windows(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, **(_windows_hidden_subprocess_kwargs() | dict(kwargs)))



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
    default_path = _default_memories(repo_root)
    if default_path.exists():
        return default_path
    imports_dir = default_path.parent
    if imports_dir.exists():
        candidates = sorted(imports_dir.rglob("memories.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return default_path



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
        (repo_root / "runtime" / "imports", "runtime/imports"),
        (repo_root / ".runtime" / "imports", ".runtime/imports"),
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
    config_path: str | Path | None = None,
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
    if config_path is not None and _path_text(config_path):
        args.extend(["--config", _path_text(config_path)])
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
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    command = str(python_path or "python3").strip() or "python3"
    if "/" in command or "\\" in command:
        try:
            command = str(Path(command).expanduser().resolve())
        except OSError:
            pass
    launcher = str(launcher_path or (REPO_ROOT / "tools" / "run_claude_live_mcp.py").resolve()).strip()
    return {
        "type": "stdio",
        "command": command,
        "args": build_launcher_cli_args(
            launcher_path=launcher,
            memories_path=memories_path,
            episodes_path=episodes_path,
            default_role=default_role,
            compat_mode=compat_mode,
            mutations_enabled=mutations_enabled,
            config_path=config_path,
        ),
        "env": {},
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
    runner: Any | None = None,
) -> tuple[str, str]:
    runner = runner or run_subprocess_hidden_on_windows
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
    if len(raw) >= 3 and raw[0].isalpha() and raw[1] == ":" and raw[2] in {"\\", "/"}:
        drive = raw[0].lower()
        remainder = raw[2:].replace("\\", "/").lstrip("/")
        converted = f"/mnt/{drive}/{remainder}" if remainder else f"/mnt/{drive}"
        return converted, inferred_distro
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
    runner: Any | None = None,
    config_path: str | Path | None = None,
    python_path: str = "",
) -> dict[str, Any]:
    runner = runner or run_subprocess_hidden_on_windows
    repo_root_arg, distro = wsl_path_from_windows(repo_root, distro_name=distro_name, runner=runner)
    memories_arg, distro = wsl_path_from_windows(memories_path, distro_name=distro, runner=runner)
    episodes_arg: str | None = None
    config_arg: str | None = None
    if episodes_path is not None and _path_text(episodes_path):
        episodes_arg, distro = wsl_path_from_windows(episodes_path, distro_name=distro, runner=runner)
    if config_path is not None and _path_text(config_path):
        config_arg, distro = wsl_path_from_windows(config_path, distro_name=distro, runner=runner)
    selected_python = str(python_path or "").strip() or discover_wsl_python_path(
        distro_name=distro,
        runner=runner,
    )
    args: list[str] = []
    if distro:
        args.extend(["-d", distro])
    args.extend(["--cd", repo_root_arg, "--exec", selected_python])
    args.extend(
        build_launcher_cli_args(
            launcher_path="tools/run_claude_live_mcp.py",
            memories_path=memories_arg,
            episodes_path=episodes_arg,
            default_role=default_role,
            compat_mode=compat_mode,
            mutations_enabled=mutations_enabled,
            config_path=config_arg,
        )
    )
    return {
        "type": "stdio",
        "command": WINDOWS_WSL_COMMAND,
        "args": args,
        "env": {},
    }


def discover_wsl_python_path(*, distro_name: str, runner: Any | None = None) -> str:
    runner = runner or run_subprocess_hidden_on_windows
    path_probe = (
        "import json,sys,venv,xml.parsers.expat; "
        "assert sys.version_info >= (3,12); "
        "print(json.dumps({'path':sys.executable,'version':[sys.version_info[0],sys.version_info[1]]}))"
    )
    path_command = [windows_wsl_command()]
    if distro_name:
        path_command.extend(["-d", distro_name])
    path_command.extend(["--exec", "/usr/bin/env", "python3", "-c", path_probe])
    try:
        path_result = runner(path_command, check=False, capture_output=True, text=True)
    except OSError:
        path_result = None
    if path_result is not None and int(path_result.returncode) == 0:
        try:
            payload = json.loads(str(path_result.stdout or "").strip().splitlines()[-1])
            selected_path = str(payload.get("path") or "").strip()
            version = tuple(int(piece) for piece in payload.get("version") or ())
            if len(version) == 2 and version >= (3, 12) and PurePosixPath(selected_path).is_absolute():
                return selected_path
        except (IndexError, TypeError, ValueError, json.JSONDecodeError):
            pass
    best: tuple[tuple[int, int], str] | None = None
    for candidate in WSL_PYTHON_CANDIDATES:
        command = [windows_wsl_command()]
        if distro_name:
            command.extend(["-d", distro_name])
        command.extend(["--exec", candidate, "-c", PYTHON_BOOTSTRAP_PROBE])
        try:
            proc = runner(command, check=False, capture_output=True, text=True)
        except OSError:
            continue
        if int(proc.returncode) != 0:
            continue
        raw = str(proc.stdout or "").strip()
        parts = raw.split(".", 1)
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            continue
        version = (int(parts[0]), int(parts[1]))
        if version < (3, 12):
            continue
        if best is None or version > best[0]:
            best = (version, candidate)
    if best is None:
        raise ValueError("no compatible Python 3.12+ interpreter found inside the selected WSL distribution")
    return best[1]



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
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if path.exists():
        backup_path = _backup_path(path)
        if backup_path.exists():
            backup_path = backup_path.with_name(f"{backup_path.name}.{uuid4().hex[:8]}")
        backup_temp = backup_path.with_name(f".{backup_path.name}.{uuid4().hex}.tmp")
        try:
            with backup_temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(path.read_text(encoding="utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(backup_temp, backup_path)
        finally:
            backup_temp.unlink(missing_ok=True)
    target_temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with target_temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(target_temp, path)
    finally:
        target_temp.unlink(missing_ok=True)
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



def _current_windows_user_dir(*, users_root: Path | None = None, env: Mapping[str, str] | None = None) -> Path | None:
    env_map = dict(os.environ if env is None else env)
    user_profile = str(env_map.get("USERPROFILE") or "").strip()
    if user_profile:
        return Path(user_profile).expanduser().resolve()
    user_name = str(env_map.get("USERNAME") or "").strip()
    if user_name:
        return (users_root or windows_users_root(env=env_map)) / user_name
    return None


def find_windows_claude_desktop_config(
    *, users_root: Path | None = None, env: Mapping[str, str] | None = None, allow_cross_profile: bool = False
) -> Path | None:
    current_user = _current_windows_user_dir(users_root=users_root, env=env)
    if current_user is not None:
        return current_user / WINDOWS_CLAUDE_DESKTOP_REL
    if not allow_cross_profile:
        return None
    matches: list[Path] = []
    for user_dir in candidate_windows_user_dirs(users_root=users_root):
        candidate = user_dir / WINDOWS_CLAUDE_DESKTOP_REL
        if candidate.exists():
            matches.append(candidate)
    if matches:
        matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return matches[0]
    return None



def find_windows_claude_code_config(
    *, users_root: Path | None = None, env: Mapping[str, str] | None = None, allow_cross_profile: bool = False
) -> Path | None:
    current_user = _current_windows_user_dir(users_root=users_root, env=env)
    if current_user is not None:
        return current_user / WINDOWS_CLAUDE_CODE_REL
    if not allow_cross_profile:
        return None
    matches: list[Path] = []
    for user_dir in candidate_windows_user_dirs(users_root=users_root):
        candidate = user_dir / WINDOWS_CLAUDE_CODE_REL
        if candidate.exists():
            matches.append(candidate)
    if matches:
        matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return matches[0]
    return None


def default_claude_code_scope(*, install_context: str = "") -> str:
    normalized = str(install_context or "").strip().lower()
    if normalized == "native-windows-claude":
        return "user"
    return "local"


def claude_code_project_key(repo_root: str | Path) -> str:
    raw = str(repo_root or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered.startswith("/mnt/") and len(raw) > 6:
        drive = raw[5]
        suffix = raw[6:].replace("\\", "/")
        if not suffix.startswith("/"):
            suffix = "/" + suffix
        return f"{drive.upper()}:{suffix}"
    if len(raw) >= 2 and raw[1] == ":":
        return raw.replace("\\", "/")
    return raw.replace("\\", "/")


def read_claude_code_scope_entries(
    config_payload: Mapping[str, Any] | None,
    *,
    repo_root: str | Path,
    server_name: str,
) -> dict[str, dict[str, Any]]:
    payload = dict(config_payload or {})
    normalized_server = str(server_name or "").strip()
    if not normalized_server:
        return {}
    found: dict[str, dict[str, Any]] = {}
    top_level = payload.get("mcpServers")
    if isinstance(top_level, Mapping):
        entry = top_level.get(normalized_server)
        if isinstance(entry, Mapping):
            found["user"] = dict(entry)
    project_key = claude_code_project_key(repo_root)
    projects = payload.get("projects")
    if isinstance(projects, Mapping) and project_key:
        project_payload = projects.get(project_key)
        if not isinstance(project_payload, Mapping):
            lowered_project_key = project_key.lower()
            for candidate_key, candidate_payload in projects.items():
                if str(candidate_key or "").strip().lower() == lowered_project_key:
                    project_payload = candidate_payload
                    break
        if not isinstance(project_payload, Mapping):
            matching_project_entries: list[dict[str, Any]] = []
            for candidate_payload in projects.values():
                if not isinstance(candidate_payload, Mapping):
                    continue
                candidate_servers = candidate_payload.get("mcpServers")
                if not isinstance(candidate_servers, Mapping):
                    continue
                entry = candidate_servers.get(normalized_server)
                if isinstance(entry, Mapping):
                    matching_project_entries.append(dict(entry))
            if len(matching_project_entries) == 1:
                project_payload = {"mcpServers": {normalized_server: matching_project_entries[0]}}
        if isinstance(project_payload, Mapping):
            project_servers = project_payload.get("mcpServers")
            if isinstance(project_servers, Mapping):
                entry = project_servers.get(normalized_server)
                if isinstance(entry, Mapping):
                    project_entry = dict(entry)
                    found["local"] = project_entry
                    found["project"] = dict(project_entry)
    return found



def detect_wsl_distro(
    *,
    env: Mapping[str, str] | None = None,
    runner: Any | None = None,
) -> str:
    runner = runner or run_subprocess_hidden_on_windows
    env_map = dict(env or os.environ)
    current = str(env_map.get("WSL_DISTRO_NAME") or "").strip()
    if current:
        return current
    wsl_command = windows_wsl_command()
    try:
        proc = runner([wsl_command, "-l", "-q"], check=False, capture_output=True, text=True)
    except OSError:
        return ""
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


def build_http_entry(
    *,
    url: str,
    managed_by: str = "modelnumquamoblita-desktop",
) -> dict[str, Any]:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        raise ValueError("http MCP url is required")
    return {
        "type": "http",
        "url": normalized_url,
        "managed_by": str(managed_by or "").strip() or "modelnumquamoblita-desktop",
    }


def normalize_mcp_entry(entry: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(entry or {})
    entry_type = str(payload.get("type") or "").strip().lower() or "stdio"
    if entry_type == "http":
        normalized: dict[str, Any] = {
            "type": "http",
            "url": str(payload.get("url") or "").strip(),
        }
    else:
        command = str(payload.get("command") or "").strip()
        args = payload.get("args")
        env = payload.get("env")
        normalized = {
            "type": "stdio",
            "command": command,
            "args": list(args) if isinstance(args, list) else [],
            "env": dict(env) if isinstance(env, Mapping) else {},
        }
    for key, value in payload.items():
        if key in {"type", "command", "args", "env", "url"}:
            continue
        normalized[key] = value
    return normalized


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
        json.dumps(normalize_mcp_entry(entry), separators=(",", ":"), ensure_ascii=False),
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
    runner: Any | None = None,
    which: Any = shutil.which,
) -> dict[str, Any]:
    runner = runner or run_subprocess_hidden_on_windows
    if which(str(claude_bin)) is None:
        raise RuntimeError(f"claude CLI not found: {claude_bin}")
    version_proc = runner([str(claude_bin), "--version"], check=False, capture_output=True, text=True)
    if version_proc.returncode != 0:
        raise RuntimeError("claude CLI version probe failed")
    help_proc = runner([str(claude_bin), "mcp", "--help"], check=False, capture_output=True, text=True)
    help_text = f"{help_proc.stdout or ''}\n{help_proc.stderr or ''}".lower()
    if help_proc.returncode != 0 or not all(command in help_text for command in ("add-json", "get", "remove")):
        raise RuntimeError("claude CLI lacks required mcp add-json/get/remove capabilities")

    normalized_name = ensure_valid_server_name(server_name)
    stage_name = ensure_valid_server_name(f"{normalized_name}-mno-stage-{uuid4().hex[:8]}")
    stage_add_cmd = build_claude_code_add_json_cmd(
        server_name=stage_name, entry=entry, scope=scope, claude_bin=claude_bin
    )
    stage_proc = runner(stage_add_cmd, check=False, capture_output=True, text=True)
    if stage_proc.returncode != 0:
        detail = str(stage_proc.stderr or stage_proc.stdout or "unknown error").strip()
        raise RuntimeError(f"claude mcp staged add-json failed; existing connector preserved: {detail}")
    stage_verified = False
    try:
        stage_get = runner([str(claude_bin), "mcp", "get", stage_name], check=False, capture_output=True, text=True)
        stage_verified = stage_get.returncode == 0
        if not stage_verified:
            detail = str(stage_get.stderr or stage_get.stdout or "unknown error").strip()
            raise RuntimeError(f"claude mcp staged verification failed; existing connector preserved: {detail}")
    finally:
        runner(
            build_claude_code_remove_cmd(server_name=stage_name, scope=scope, claude_bin=claude_bin),
            check=False, capture_output=True, text=True,
        )

    add_cmd = build_claude_code_add_json_cmd(server_name=server_name, entry=entry, scope=scope, claude_bin=claude_bin)
    add_proc = runner(add_cmd, check=False, capture_output=True, text=True)
    if add_proc.returncode != 0:
        stderr = str(add_proc.stderr or "").strip() or str(add_proc.stdout or "").strip() or "unknown error"
        raise RuntimeError(f"claude mcp add-json failed; prior connector preserved: {stderr}")
    verify_proc = runner([str(claude_bin), "mcp", "get", normalized_name], check=False, capture_output=True, text=True)
    if verify_proc.returncode != 0:
        detail = str(verify_proc.stderr or verify_proc.stdout or "unknown error").strip()
        raise RuntimeError(f"claude mcp replacement verification failed: {detail}")
    return {
        "client_version": str(version_proc.stdout or version_proc.stderr or "").strip(),
        "capability_probe": "add-json,get,remove",
        "stage_verified": stage_verified,
        "add_returncode": int(add_proc.returncode),
        "add_stdout": str(add_proc.stdout or "").strip(),
        "add_stderr": str(add_proc.stderr or "").strip(),
        "verified": True,
        "scope": str(scope or "local").strip() or "local",
    }


def remove_claude_code_server(
    *,
    server_name: str,
    scope: str,
    claude_bin: str = "claude",
    runner: Any | None = None,
    which: Any = shutil.which,
) -> dict[str, Any]:
    runner = runner or run_subprocess_hidden_on_windows
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
