from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count
from typing import Iterable

from .core import (
    AgentProfile,
    ArenaCandidate,
    Coalition,
    Mentality,
    TaskContext,
    VerificationResult,
    build_coalition,
    rank_arena,
    verify_result,
)


@dataclass(frozen=True)
class SkillMatch:
    skill_id: str
    score: float
    dependencies: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    estimated_context_cost: int = 0


@dataclass(frozen=True)
class ModelCandidate:
    name: str
    provider_kind: str
    quality: float
    reliability: float
    latency_ms: float
    cost_eur: float
    risk: float
    capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MCPToolRef:
    qualified_name: str
    read_only: bool
    capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Strategy:
    name: str
    description: str
    quality_bias: float
    latency_bias: float
    cost_bias: float
    verification_depth: int


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    retry_on: frozenset[str]
    require_new_evidence: bool = True


@dataclass(frozen=True)
class OrchestrationPlan:
    task_id: str
    objective: str
    selected_skills: tuple[SkillMatch, ...]
    coalition: Coalition
    selected_model: ModelCandidate | None
    selected_tools: tuple[MCPToolRef, ...]
    arena: tuple[ArenaCandidate, ...]
    strategies: tuple[Strategy, ...]
    retry_policy: RetryPolicy
    verdict: str
    reasons: tuple[str, ...]


_TASK_COUNTER = count(1)


def new_task_id(now: datetime | None = None, sequence: int | None = None) -> str:
    timestamp = now or datetime.now(timezone.utc)
    number = sequence if sequence is not None else next(_TASK_COUNTER)
    return f"TASK-{timestamp:%Y%m%d}-{number:04d}"


def resolve_skill_bundle(
    matches: Iterable[SkillMatch],
    *,
    max_context_cost: int = 12000,
) -> tuple[tuple[SkillMatch, ...], tuple[str, ...]]:
    ordered = sorted(matches, key=lambda item: (-item.score, item.skill_id.lower()))
    selected: list[SkillMatch] = []
    selected_ids: set[str] = set()
    reasons: list[str] = []
    context_cost = 0

    by_id = {item.skill_id: item for item in ordered}

    def add_with_dependencies(item: SkillMatch, stack: tuple[str, ...] = ()) -> bool:
        nonlocal context_cost
        if item.skill_id in selected_ids:
            return True
        if item.skill_id in stack:
            reasons.append(f"dependency_cycle:{item.skill_id}")
            return False
        for conflict in item.conflicts:
            if conflict in selected_ids:
                reasons.append(f"skill_conflict:{item.skill_id}:{conflict}")
                return False
        for dep_id in item.dependencies:
            dep = by_id.get(dep_id)
            if dep is None:
                reasons.append(f"unresolved_dependency:{item.skill_id}:{dep_id}")
                return False
            if not add_with_dependencies(dep, stack + (item.skill_id,)):
                return False
        if context_cost + item.estimated_context_cost > max_context_cost:
            reasons.append(f"context_budget_exceeded:{item.skill_id}")
            return False
        selected.append(item)
        selected_ids.add(item.skill_id)
        context_cost += item.estimated_context_cost
        return True

    for match in ordered:
        add_with_dependencies(match)

    return tuple(selected), tuple(dict.fromkeys(reasons))


def select_model(task: TaskContext, candidates: Iterable[ModelCandidate]) -> ModelCandidate | None:
    pool = list(candidates)
    if not pool:
        return None

    def score(model: ModelCandidate) -> tuple[float, str]:
        capability_bonus = len(model.capabilities & task.required_skills) * 0.1
        preferred_bonus = 0.25 if not task.preferred_models or model.name in task.preferred_models else 0.0
        latency_penalty = 0.0
        if task.max_latency_ms is not None and model.latency_ms > task.max_latency_ms:
            latency_penalty = 0.25
        cost_penalty = 0.0
        if task.max_cost_eur is not None and model.cost_eur > task.max_cost_eur:
            cost_penalty = 0.25
        risk_penalty = max(0.0, model.risk - task.risk_tolerance) * 0.25
        utility = (
            model.quality * 0.35
            + model.reliability * 0.30
            + capability_bonus
            + preferred_bonus
            - latency_penalty
            - cost_penalty
            - risk_penalty
        )
        return utility, model.name.lower()

    return max(pool, key=score)


def select_tools(required_skills: Iterable[str], tools: Iterable[MCPToolRef]) -> tuple[MCPToolRef, ...]:
    required = set(required_skills)
    selected = [tool for tool in tools if tool.capabilities & required]
    return tuple(sorted(selected, key=lambda tool: tool.qualified_name.lower()))


def default_strategies() -> tuple[Strategy, ...]:
    return (
        Strategy("A", "balanced execution", 0.50, 0.25, 0.25, 2),
        Strategy("B", "quality first", 0.70, 0.15, 0.15, 3),
        Strategy("C", "fast path", 0.30, 0.55, 0.15, 1),
        Strategy("D", "skeptical verification", 0.55, 0.15, 0.30, 4),
    )


def build_arena_for_model(model: ModelCandidate, strategies: Iterable[Strategy]) -> tuple[ArenaCandidate, ...]:
    candidates = []
    for strategy in strategies:
        quality = min(1.0, model.quality * (0.85 + strategy.quality_bias * 0.3))
        latency = max(0.0, model.latency_ms * (1.25 - strategy.latency_bias * 0.5))
        cost = max(0.0, model.cost_eur * (1.20 - strategy.cost_bias * 0.4))
        reliability = min(1.0, model.reliability + 0.02 * strategy.verification_depth)
        risk = max(0.0, model.risk - 0.03 * strategy.verification_depth)
        candidates.append(
            ArenaCandidate(
                name=strategy.name,
                quality=quality,
                reliability=reliability,
                latency_ms=latency,
                cost_eur=cost,
                risk=risk,
                historical_score=0.5,
            )
        )
    return rank_arena(candidates)


def build_plan(
    *,
    task: TaskContext,
    skill_matches: Iterable[SkillMatch],
    agents: Iterable[AgentProfile],
    models: Iterable[ModelCandidate],
    tools: Iterable[MCPToolRef],
    max_context_cost: int = 12000,
    task_id: str | None = None,
) -> OrchestrationPlan:
    selected_skills, skill_reasons = resolve_skill_bundle(skill_matches, max_context_cost=max_context_cost)
    required_skills = frozenset(item.skill_id for item in selected_skills) or task.required_skills
    effective_task = TaskContext(
        objective=task.objective,
        required_skills=required_skills,
        preferred_models=task.preferred_models,
        required_mentalities=task.required_mentalities,
        max_latency_ms=task.max_latency_ms,
        max_cost_eur=task.max_cost_eur,
        available_vram_gb=task.available_vram_gb,
        risk_tolerance=task.risk_tolerance,
    )
    coalition = build_coalition(effective_task, agents)
    model = select_model(effective_task, models)
    selected_tools = select_tools(required_skills, tools)
    strategies = default_strategies()
    arena = build_arena_for_model(model, strategies) if model else tuple()

    reasons = list(skill_reasons)
    checks: list[bool | None] = [coalition.complete]
    if model is None:
        reasons.append("no_model_candidate")
        checks.append(False)
    else:
        checks.append(True)
    if required_skills and not selected_tools:
        reasons.append("no_mcp_tool_matches_required_skills")
        checks.append(None)
    else:
        checks.append(True)

    quality = arena[0].quality if arena else 0.0
    verification = verify_result(checks=checks, quality_score=quality)
    reasons.extend(verification.reasons)

    return OrchestrationPlan(
        task_id=task_id or new_task_id(),
        objective=task.objective,
        selected_skills=selected_skills,
        coalition=coalition,
        selected_model=model,
        selected_tools=selected_tools,
        arena=arena,
        strategies=strategies,
        retry_policy=RetryPolicy(
            max_attempts=3,
            retry_on=frozenset({"PARTIAL", "INCONCLUSIVE"}),
            require_new_evidence=True,
        ),
        verdict=verification.verdict,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def should_retry(plan: OrchestrationPlan, *, attempt: int, new_evidence: bool) -> bool:
    if attempt >= plan.retry_policy.max_attempts:
        return False
    if plan.verdict not in plan.retry_policy.retry_on:
        return False
    if plan.retry_policy.require_new_evidence and not new_evidence:
        return False
    return True
