"""Hermes plugin entry point for MNO's optional automatic turn adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from .adapter import HermesMemoryAdapter


def _config_path(*, environ: Mapping[str, str] | None = None, platform_name: str | None = None, home_dir: Path | None = None) -> Path:
    environment = environ if environ is not None else os.environ
    home = environment.get("HERMES_HOME")
    if home:
        return Path(home) / "mno" / "mno-memory.json"
    if (platform_name or os.name) == "nt":
        return Path(environment.get("LOCALAPPDATA", "~")).expanduser() / "hermes" / "mno" / "mno-memory.json"
    return (home_dir or Path.home()) / ".hermes" / "mno" / "mno-memory.json"


def register(ctx: Any) -> None:
    """Register exactly the hooks available in Hermes v0.19.0.

    A malformed/missing configuration intentionally installs inert callbacks;
    plugin discovery must never make Hermes startup fail.
    """
    adapter = HermesMemoryAdapter.from_path(_config_path())
    if adapter is None:
        adapter = HermesMemoryAdapter.disabled()
    ctx.register_hook("pre_llm_call", adapter.pre_llm_call)
    ctx.register_hook("post_llm_call", adapter.post_llm_call)
    ctx.register_hook("on_session_end", adapter.on_session_end)
    ctx.register_hook("on_session_finalize", adapter.on_session_finalize)
    ctx.register_hook("on_session_reset", adapter.on_session_reset)


__all__ = ["HermesMemoryAdapter", "register"]
