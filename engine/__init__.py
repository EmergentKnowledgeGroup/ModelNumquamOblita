"""NumquamOblita core engine package."""

from .config import NumquamOblitaConfig, default_config, load_config
from .continuity import ContinuityBuilder, ContinuityStore, Consolidator
from .contracts import (
    AtomType,
    CandidateAtom,
    MemoryPack,
    MemoryPackItem,
    NormalizedTurn,
    SourceRef,
    WriteAction,
    WriteDecision,
    contract_to_dict,
)
from .retrieval import ClaimVerifier, MemoryRetriever
from .runtime import RuntimeSession
from .write_gate import StageAWriteGate, StageBWriteGate

__all__ = [
    "AtomType",
    "CandidateAtom",
    "ContinuityBuilder",
    "ContinuityStore",
    "Consolidator",
    "MemoryPack",
    "MemoryPackItem",
    "MemoryRetriever",
    "NormalizedTurn",
    "NumquamOblitaConfig",
    "ClaimVerifier",
    "RuntimeSession",
    "SourceRef",
    "StageAWriteGate",
    "StageBWriteGate",
    "WriteAction",
    "WriteDecision",
    "contract_to_dict",
    "default_config",
    "load_config",
]
