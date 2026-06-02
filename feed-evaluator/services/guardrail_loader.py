"""
Loads guardrails from config/guardrails.md.
"""

from pathlib import Path

_GUARDRAILS_PATH = Path(__file__).parent.parent / "config" / "guardrails.md"
_cache: str | None = None


def get_guardrails() -> str:
    """Load and cache guardrails content."""
    global _cache
    if _cache is None:
        _cache = _GUARDRAILS_PATH.read_text(encoding="utf-8")
    return _cache


def reload_guardrails():
    """Force reload from disk."""
    global _cache
    _cache = None
    get_guardrails()
