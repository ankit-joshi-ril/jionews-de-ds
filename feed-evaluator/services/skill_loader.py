"""
Parses config/skills.md and provides skill content by ID.
"""

import re
from pathlib import Path

_SKILLS_PATH = Path(__file__).parent.parent / "config" / "skills.md"
_cache: dict[str, str] = {}


def _load_skills() -> dict[str, str]:
    """Parse skills.md using ## Skill: headers as delimiters."""
    global _cache
    if _cache:
        return _cache

    content = _SKILLS_PATH.read_text(encoding="utf-8")
    sections = re.split(r"^## Skill:\s*", content, flags=re.MULTILINE)

    for section in sections[1:]:  # skip preamble
        lines = section.strip().split("\n", 1)
        skill_id = lines[0].strip()
        skill_body = lines[1].strip() if len(lines) > 1 else ""
        _cache[skill_id] = skill_body

    return _cache


def get_skill(skill_id: str) -> str:
    """Get a single skill's content by ID."""
    skills = _load_skills()
    return skills.get(skill_id, "")


def get_all_onboarding_skills() -> str:
    """Get all publisher onboarding skills combined."""
    skills = _load_skills()
    ids = [
        "headlines-publisher-onboarding",
        "native-videos-publisher-onboarding",
        "summaries-publisher-onboarding",
        "feed-analytics",
    ]
    parts = [skills[sid] for sid in ids if sid in skills]
    return "\n\n---\n\n".join(parts)


def reload_skills():
    """Force reload of skills from disk."""
    global _cache
    _cache = {}
    _load_skills()
