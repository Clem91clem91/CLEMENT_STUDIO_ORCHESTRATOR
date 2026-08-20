from __future__ import annotations

from typing import Any

from .pipeline import SkillMatch


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item))
    return ()


def skill_matches_from_search(payload: dict[str, Any]) -> tuple[SkillMatch, ...]:
    """Convert P0-02 skills_search output into P0-04 planning inputs."""
    raw_matches = payload.get("matches")
    if not isinstance(raw_matches, list):
        return ()

    converted: list[SkillMatch] = []
    for item in raw_matches:
        if not isinstance(item, dict):
            continue
        skill = item.get("skill")
        if not isinstance(skill, dict):
            continue
        skill_id = str(skill.get("id") or skill.get("name") or "").strip()
        if not skill_id:
            continue
        try:
            raw_score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            raw_score = 0.0
        score = raw_score / 100.0 if raw_score > 1.0 else raw_score
        try:
            context_cost = int(skill.get("estimated_context_cost") or 0)
        except (TypeError, ValueError):
            context_cost = 0
        converted.append(
            SkillMatch(
                skill_id=skill_id,
                score=max(0.0, score),
                dependencies=_strings(skill.get("dependencies")),
                conflicts=_strings(skill.get("conflicts")),
                estimated_context_cost=max(0, context_cost),
            )
        )

    return tuple(sorted(converted, key=lambda match: (-match.score, match.skill_id.lower())))
