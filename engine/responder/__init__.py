"""External responder harness (provider-agnostic).

This layer turns a context package into an external LLM call and verifies the model output.
It exists so the memory engine can stay model/provider agnostic while evals can still run end-to-end.
"""

from .prompt_builder import build_responder_messages
from .providers import (
    ChatProvider,
    ChatProviderConfig,
    ChatResponse,
    build_provider,
)
from .verifier import (
    CANONICAL_ABSTAIN_PHRASE,
    VerifiedReply,
    enforce_reply_contract,
    verify_reply_against_package,
)

__all__ = [
    "ChatProvider",
    "ChatProviderConfig",
    "ChatResponse",
    "CANONICAL_ABSTAIN_PHRASE",
    "VerifiedReply",
    "build_provider",
    "build_responder_messages",
    "enforce_reply_contract",
    "verify_reply_against_package",
]
