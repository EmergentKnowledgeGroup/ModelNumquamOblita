from __future__ import annotations

import pytest

from tools.verify_distribution_artifacts import _assert_no_private_paths


def test_artifact_verifier_rejects_private_runtime_and_sqlite_paths() -> None:
    with pytest.raises(AssertionError, match="SQLite state"):
        _assert_no_private_paths({"runtime/imports/atoms.sqlite3"}, artifact="fixture")
    with pytest.raises(AssertionError, match="SQLite state"):
        _assert_no_private_paths({"runtime/imports/atoms.db-wal"}, artifact="fixture")
    with pytest.raises(AssertionError, match="private/generated"):
        _assert_no_private_paths({"runtime/checkpoints/LATEST.json"}, artifact="fixture")
    with pytest.raises(AssertionError, match="private/generated"):
        _assert_no_private_paths({"runtime/external/private/README.md"}, artifact="fixture")


def test_artifact_verifier_accepts_public_runtime_skeleton() -> None:
    _assert_no_private_paths({"runtime/imports/.gitkeep", "runtime/README.md"}, artifact="fixture")
