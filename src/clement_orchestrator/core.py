from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class Mentality(str, Enum):
    ANALYTICAL = "analytical"
    CREATIVE = "creative"
    SKEPTICAL = "skeptical"
    ENGINEERING = "engineering"
    SECURITY = "security"
    VERIFICATION = "verification"
    MINIMALIST = "minimalist"
    RESEARCH = "research"
    PLANNING = "planning"


@dataclass(frozen=True)
class TaskContext:
    objective: str
    required_skills: frozenset[str] = frozenset()
    preferred_models: frozenset[str] = frozenset()
    required_mentalities: frozenset[Mentality] = frozenset()
    max_latency_ms: float | None = None
    max_cost_eur: float | None = None
    available_vram_gb: float | None = None
    risk_tolerance: float = 0.5


@dataclass(frozen=True)
class AgentProfile:
    name: str
    skills: frozenset[str]
    models: frozenset[str] = frozenset()
    mentalities: frozenset[Mentality] = frozenset()
    mcp_tools: frozenset[str] = frozenset()
    estimated_latency_ms: float = 0.0
    estimated_cost_eur: float = 0.0
    vram_gb: float = 0.0
    quality: float = 0.5
    reliability: float = 0.5
    risk: float = 0.5
    historical_score: float = 0.5


@dataclass(frozen=True)
class Coalition:
    agents: tuple[AgentProfile, ...]
    covered_skills: frozenset[str]
    covered_mentalities: frozenset[Mentality]
    score: float
    complete: bool
    reason: str


@dataclass(frozen=True)
class ArenaCandidate:
    name: str
    quality: float
    reliability: float
    latency_ms: float
    cost_eur: float
    risk: float
    historical_score: float = 0.5


@dataclass(frozen=True)
class VerificationResult:
    verdict: str
    score: float
    reasons: tuple[str, ...]


def _agent_score(agent: AgentProfile, task: TaskContext, uncovered: set[str]) -> float:
    skill_gain = len(agent.skills & uncovered)
    mentality_gain = len(agent.mentalities & set(task.required_mentalities))
    model_bonus = 1.0 if not task.preferred_models or bool(agent.models & task.preferred_models) else 0.0

    latency_penalty = 0.0
    if task.max_latency_ms is not None and agent.estimated_latency_ms > task.max_latency_ms:
        latency_penalty = min(3.0, (agent.estimated_latency_ms - task.max_latency_ms) / max(task.max_latency_ms, 1.0))

    cost_penalty = 0.0
    if task.max_cost_eur is not None and agent.estimated_cost_eur > task.max_cost_eur:
        cost_penalty = min(3.0, (agent.estimated_cost_eur - task.max_cost_eur) / max(task.max_cost_eur, 0.001))

    vram_penalty = 0.0
    if task.available_vram_gb is not None and agent.vram_gb > task.available_vram_gb:
        vram_penalty = 5.0

    risk_penalty = max(0.0, agent.risk - task.risk_tolerance) * 2.0

    return (
        skill_gain * 8.0
        + mentality_gain * 2.0
        + model_bonus
        + agent.quality * 3.0
        + agent.reliability * 3.0
        + agent.historical_score * 2.0
        - latency_penalty
        - cost_penalty
        - vram_penalty
        - risk_penalty
    )


def build_coalition(task: TaskContext, agents: Iterable[AgentProfile]) -> Coalition:
    """Build a dynamic coalition without a fixed agent-count ceiling.

    The algorithm greedily adds the agent with the highest marginal score while
    required skills remain uncovered. It may select one agent or dozens; the
    stopping condition is coverage and marginal utility, never a hard count.
    """

    pool = list(agents)
    uncovered = set(task.required_skills)
    selected: list[AgentProfile] = []
    covered_mentalities: set[Mentality] = set()
    total_score = 0.0

    while uncovered:
        ranked = sorted(
            ((agent, _agent_score(agent, task, uncovered)) for agent in pool if agent not in selected),
            key=lambda item: (-item[1], item[0].name.lower()),
        )
        if not ranked:
            break

        best, score = ranked[0]
        gain = best.skills & uncovered
        if not gain:
            break

        selected.append(best)
        uncovered -= set(gain)
        covered_mentalities |= set(best.mentalities)
        total_score += score

    # Add mentality specialists only when required mentalities remain uncovered.
    missing_mentalities = set(task.required_mentalities) - covered_mentalities
    while missing_mentalities:
        candidates = [
            agent
            for agent in pool
            if agent not in selected and bool(agent.mentalities & missing_mentalities)
        ]
        if not candidates:
            break
        best = max(candidates, key=lambda a: (_agent_score(a, task, set()), a.name.lower()))
        selected.append(best)
        covered_mentalities |= set(best.mentalities)
        missing_mentalities = set(task.required_mentalities) - covered_mentalities
        total_score += _agent_score(best, task, set())

    covered_skills = frozenset().union(*(a.skills for a in selected)) if selected else frozenset()
    complete = task.required_skills.issubset(covered_skills) and task.required_mentalities.issubset(covered_mentalities)
    reason = "coverage complete" if complete else "required coverage remains unresolved"

    return Coalition(
        agents=tuple(selected),
        covered_skills=covered_skills,
        covered_mentalities=frozenset(covered_mentalities),
        score=round(total_score, 6),
        complete=complete,
        reason=reason,
    )


def _arena_score(candidate: ArenaCandidate) -> float:
    latency_component = 1.0 / (1.0 + max(candidate.latency_ms, 0.0) / 1000.0)
    cost_component = 1.0 / (1.0 + max(candidate.cost_eur, 0.0))
    return (
        candidate.quality * 0.30
        + candidate.reliability * 0.25
        + latency_component * 0.15
        + cost_component * 0.10
        + (1.0 - candidate.risk) * 0.10
        + candidate.historical_score * 0.10
    )


def rank_arena(candidates: Iterable[ArenaCandidate]) -> tuple[ArenaCandidate, ...]:
    """Rank A/B/C/D-style strategies deterministically by composite utility."""
    return tuple(
        sorted(
            candidates,
            key=lambda c: (-_arena_score(c), c.name.lower()),
        )
    )


def verify_result(*, checks: Iterable[bool | None], quality_score: float) -> VerificationResult:
    """Return PASS/PARTIAL/FAIL/INCONCLUSIVE using explicit evidence states."""
    evidence = list(checks)
    reasons: list[str] = []

    if not evidence or all(item is None for item in evidence):
        return VerificationResult("INCONCLUSIVE", quality_score, ("no conclusive verification evidence",))

    if any(item is False for item in evidence):
        reasons.append("at least one required check failed")
        return VerificationResult("FAIL", quality_score, tuple(reasons))

    if any(item is None for item in evidence):
        reasons.append("some required checks are unresolved")
        return VerificationResult("PARTIAL", quality_score, tuple(reasons))

    if quality_score < 0.7:
        reasons.append("all checks passed but quality is below threshold")
        return VerificationResult("PARTIAL", quality_score, tuple(reasons))

    return VerificationResult("PASS", quality_score, ("all required checks passed",))
