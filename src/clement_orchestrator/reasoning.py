from __future__ import annotations

import re

from .core import Mentality


_RULES: tuple[tuple[Mentality, tuple[str, ...]], ...] = (
    (Mentality.SECURITY, ("security", "secure", "permission", "auth", "credential", "secret", "risk", "delete", "destructive")),
    (Mentality.SKEPTICAL, ("verify", "audit", "evidence", "proof", "compare", "critical", "risk", "uncertain", "research")),
    (Mentality.ENGINEERING, ("build", "develop", "code", "system", "architecture", "pipeline", "mcp", "api", "install", "deploy")),
    (Mentality.VERIFICATION, ("test", "verify", "validate", "certify", "qa", "proof", "pass", "fail")),
    (Mentality.CREATIVE, ("creative", "design", "visual", "concept", "image", "video", "story", "brand")),
    (Mentality.RESEARCH, ("research", "search", "study", "benchmark", "investigate", "source")),
    (Mentality.PLANNING, ("plan", "roadmap", "schedule", "orchestrate", "cascade", "workflow", "strategy")),
    (Mentality.MINIMALIST, ("minimal", "simple", "fast", "quick", "lightweight", "concise")),
)


def infer_mentalities(objective: str, *, minimum: int = 2) -> frozenset[Mentality]:
    text = " ".join(re.findall(r"[a-z0-9_-]+", (objective or "").lower()))
    selected: set[Mentality] = {Mentality.ANALYTICAL}
    for mentality, keywords in _RULES:
        if any(keyword in text for keyword in keywords):
            selected.add(mentality)

    defaults = (
        Mentality.PLANNING,
        Mentality.ENGINEERING,
        Mentality.VERIFICATION,
        Mentality.SKEPTICAL,
    )
    for mentality in defaults:
        if len(selected) >= max(1, minimum):
            break
        selected.add(mentality)
    return frozenset(selected)
