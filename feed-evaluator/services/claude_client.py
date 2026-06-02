"""
Shared Anthropic Claude client and conversation store.
"""

import os
import uuid
from anthropic import Anthropic


# Singleton client
_client = None
_conversations: dict[str, list] = {}


def get_client() -> Anthropic:
    """Get or create the Anthropic client singleton."""
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def get_model() -> str:
    """Get the configured Claude model."""
    return os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")


def get_conversation(session_id: str) -> list:
    """Get or create a conversation history for a session."""
    if session_id not in _conversations:
        _conversations[session_id] = []
    return _conversations[session_id]


def clear_conversation(session_id: str):
    """Clear a conversation history."""
    _conversations.pop(session_id, None)


def new_session_id() -> str:
    """Generate a new session ID."""
    return str(uuid.uuid4())
