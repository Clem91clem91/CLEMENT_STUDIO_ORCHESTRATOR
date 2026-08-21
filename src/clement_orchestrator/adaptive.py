from __future__ import annotations

from typing import Iterable

from .core import AgentProfile, TaskContext
from .pipeline import MCPToolRef, ModelCandidate, OrchestrationPlan, SkillMatch, build_plan
from .reasoning import infer_mentalities


def build_adaptive_plan(
    *,
    task: TaskContext,
    skill_matches: Iterable[SkillMatch],
    agents: Iterable[AgentProfile],
    models: Iterable[ModelCandidate],
    tools: Iterable[MCPToolRef],
    max_context_cost: int = 12000,
    task_id: str | None = None,
) -> OrchestrationPlan:
    """Build a plan after deriving mentalities when the caller did not pin them.

    Explicit required mentalities remain authoritative. When none are supplied,
    the orchestrator infers a variable set from the objective instead of using a
    fixed reasoning profile.
    """
    mentalities = task.required_mentalities or infer_mentalities(task.objective)
    effective = TaskContext(
        objective=task.objective,
        required_skills=task.required_skills,
        preferred_models=task.preferred_models,
        required_mentalities=mentalities,
        max_latency_ms=task.max_latency_ms,
        max_cost_eur=task.max_cost_eur,
        available_vram_gb=task.available_vram_gb,
        risk_tolerance=task.risk_tolerance,
    )
    return build_plan(
        task=effective,
        skill_matches=skill_matches,
        agents=agents,
        models=models,
        tools=tools,
        max_context_cost=max_context_cost,
        task_id=task_id,
    )
