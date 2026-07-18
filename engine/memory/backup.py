"""Consistent, WAL-safe snapshots for an atom store and its owned sidecars."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .proposal_store import SqliteProposalStore
from .provisional_store import SqliteProvisionalMemoryStore
from .sqlite_store import SqliteAtomStore


def backup_memory_family(store: SqliteAtomStore, target_dir: str | Path) -> dict[str, Any]:
    """Snapshot the atom DB plus present proposal/provisional sidecars.

    Each SQLite file is copied through its own SQLite backup API, so a live WAL
    is never mistaken for a complete main database.  The manifest deliberately
    records only topology/version metadata, not memory content.
    """

    destination = Path(target_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(store.db_path).expanduser().resolve()
    paths = {
        "atom": source,
        "provisional": source.with_suffix(".provisional.sqlite3") if source.suffix else source.parent / f"{source.name}.provisional.sqlite3",
        "proposal": source.with_suffix(".proposals.sqlite3") if source.suffix else source.parent / f"{source.name}.proposals.sqlite3",
    }
    artifacts: dict[str, dict[str, Any]] = {}
    atom_target = destination / paths["atom"].name
    store.backup_to(atom_target)
    artifacts["atom"] = {"path": atom_target.name, "schema_version": store.schema_version(), "present": True}
    for name, path in (("provisional", paths["provisional"]), ("proposal", paths["proposal"])):
        if not path.exists():
            artifacts[name] = {"present": False}
            continue
        target = destination / path.name
        sidecar = SqliteProvisionalMemoryStore(path) if name == "provisional" else SqliteProposalStore(path)
        try:
            sidecar.backup_to(target)
            artifacts[name] = {"path": target.name, "present": True}
        finally:
            sidecar.close()
    manifest = {"schema": "mno.memory-family-backup.v1", "artifacts": artifacts}
    manifest_path = destination / "memory_family_manifest.json"
    temp_path = manifest_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(temp_path, manifest_path)
    try:
        os.chmod(manifest_path, 0o600)
    except OSError:
        pass
    manifest["manifest_path"] = str(manifest_path)
    return manifest


__all__ = ["backup_memory_family"]
