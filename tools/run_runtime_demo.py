#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.continuity import ContinuityBuilder, ContinuityStore, SharedLanguageRegistry
from engine.contracts import AtomType, CandidateAtom, SourceRef
from engine.memory import AtomStore, MutationReviewQueue, SqliteAtomStore
from engine.retrieval import ClaimVerifier, MemoryRetriever
from engine.runtime import RuntimeSession, start_runtime_server, stop_runtime_server


def _seed_candidate(candidate_id: str, text: str, source_id: str, topic: str) -> CandidateAtom:
    return CandidateAtom(
        candidate_id=candidate_id,
        atom_type=AtomType.EPISODE,
        canonical_text=text,
        source_refs=[
            SourceRef(
                source_id=source_id,
                message_id=f"{candidate_id}_msg",
                timestamp=datetime.now(timezone.utc),
                span_start=0,
                span_end=max(len(text), 1),
            )
        ],
        entities=["user", "assistant"],
        topics=[topic],
        confidence=0.85,
        salience=0.72,
    )


def _build_store(backend: str, sqlite_path: Path) -> AtomStore | SqliteAtomStore:
    kind = backend.strip().lower()
    if kind == "sqlite":
        return SqliteAtomStore(sqlite_path)
    if kind == "inmemory":
        return AtomStore()
    raise ValueError(f"unsupported backend: {backend}")


def build_demo_runtime(
    *,
    backend: str,
    sqlite_path: Path,
) -> tuple[RuntimeSession, AtomStore | SqliteAtomStore, MutationReviewQueue]:
    store = _build_store(backend, sqlite_path)
    seeded = [
        _seed_candidate("seed_1", "You prefer tea during late-night debugging.", "seed_conv_1", "preferences"),
        _seed_candidate("seed_2", "We agreed that continuity must stay evidence-backed.", "seed_conv_2", "continuity"),
        _seed_candidate("seed_3", "Forever times with multiplicity became a shared key.", "seed_conv_3", "identity"),
    ]
    atoms = []
    for candidate in seeded:
        atoms.append(store.add_candidate(candidate))
    review_queue = MutationReviewQueue(store, default_retention_days=14)
    review_queue.propose_delete(target_atom_id=atoms[0].atom_id, reason_code="demo_pending_cleanup")
    review_queue.propose_edit(
        target_atom_id=atoms[1].atom_id,
        replacement_candidate=_seed_candidate(
            "seed_4",
            "Continuity should stay evidence-backed and explicitly cited.",
            "seed_conv_4",
            "continuity",
        ),
        reason_code="demo_growth_edit",
    )

    continuity_store = ContinuityStore()
    registry = SharedLanguageRegistry(store)
    shared_keys = registry.list_keys()
    continuity_store.set_snapshot(ContinuityBuilder().build(store.list_atoms(), shared_language_keys=shared_keys))
    retriever = MemoryRetriever(store)
    verifier = ClaimVerifier()
    runtime = RuntimeSession(retriever=retriever, verifier=verifier, continuity_store=continuity_store)
    return runtime, store, review_queue


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NumquamOblita local runtime demo UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7340)
    parser.add_argument(
        "--store-backend",
        choices=["sqlite", "inmemory"],
        default="sqlite",
        help="Memory store backend for demo runtime.",
    )
    parser.add_argument(
        "--sqlite-path",
        default=str(REPO_ROOT / ".runtime" / "demo" / "atoms.sqlite3"),
        help="Path used when --store-backend=sqlite.",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    runtime, store, review_queue = build_demo_runtime(backend=args.store_backend, sqlite_path=sqlite_path)
    server, thread = start_runtime_server(runtime, host=args.host, port=args.port, review_queue=review_queue)
    host, port = server.server_address
    print(f"Runtime demo listening at http://{host}:{port}")
    print(f"Store backend: {args.store_backend}")
    if args.store_backend == "sqlite":
        print(f"Store path: {sqlite_path}")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_runtime_server(server, thread, runtime=runtime)
        closer = getattr(store, "close", None)
        if callable(closer):
            closer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
