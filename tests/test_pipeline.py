from __future__ import annotations

from datetime import datetime, timezone

from clement_orchestrator.core import AgentProfile, Mentality, TaskContext
from clement_orchestrator.pipeline import (
    MCPToolRef,
    ModelCandidate,
    SkillMatch,
    build_plan,
    new_task_id,
    resolve_skill_bundle,
    should_retry,
)


def agent(name: str, skill: str) -> AgentProfile:
    return AgentProfile(
        name=name,
        skills=frozenset({skill}),
        mentalities=frozenset({Mentality.ENGINEERING, Mentality.VERIFICATION}),
        quality=0.9,
        reliability=0.9,
        historical_score=0.8,
    )


def model() -> ModelCandidate:
    return ModelCandidate(
        name="qwen/qwen3-30b-a3b",
        provider_kind="LOCAL",
        quality=0.9,
        reliability=0.9,
        latency_ms=500,
        cost_eur=0.0,
        risk=0.1,
        capabilities=frozenset({"planning", "verification"}),
    )


def test_task_id_format_is_stable():
    now = datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc)
    assert new_task_id(now, sequence=42) == "TASK-20260820-0042"


def test_skill_bundle_resolves_dependencies_before_parent():
    dep = SkillMatch("base", 0.5, estimated_context_cost=100)
    parent = SkillMatch("planning", 1.0, dependencies=("base",), estimated_context_cost=100)
    selected, reasons = resolve_skill_bundle([parent, dep])
    assert [item.skill_id for item in selected] == ["base", "planning"]
    assert reasons == ()


def test_skill_bundle_reports_unresolved_dependency():
    parent = SkillMatch("planning", 1.0, dependencies=("missing",))
    selected, reasons = resolve_skill_bundle([parent])
    assert selected == ()
    assert "unresolved_dependency:planning:missing" in reasons


def test_plan_builds_skills_agents_model_tools_and_arena():
    task = TaskContext(
        objective="Plan and verify",
        required_skills=frozenset({"planning", "verification"}),
        required_mentalities=frozenset({Mentality.ENGINEERING, Mentality.VERIFICATION}),
    )
    plan = build_plan(
        task=task,
        skill_matches=[SkillMatch("planning", 1.0), SkillMatch("verification", 0.9)],
        agents=[agent("planner", "planning"), agent("verifier", "verification")],
        models=[model()],
        tools=[
            MCPToolRef("mcp__skills__skills_search", True, frozenset({"planning"})),
            MCPToolRef("mcp__skills__skills_validate", True, frozenset({"verification"})),
        ],
        task_id="TASK-20260820-0001",
    )
    assert plan.task_id == "TASK-20260820-0001"
    assert plan.coalition.complete is True
    assert len(plan.coalition.agents) == 2
    assert plan.selected_model is not None
    assert len(plan.selected_tools) == 2
    assert {candidate.name for candidate in plan.arena} == {"A", "B", "C", "D"}
    assert plan.verdict in {"PASS", "PARTIAL"}


def test_real_registry_ids_do_not_replace_semantic_agent_requirements():
    task = TaskContext(
        objective="Plan and verify real registry evidence",
        required_skills=frozenset({"planning", "orchestration", "verification"}),
        required_mentalities=frozenset({Mentality.ENGINEERING, Mentality.VERIFICATION}),
    )
    plan = build_plan(
        task=task,
        skill_matches=[
            SkillMatch("clement.agent-orchestration.db91fa689e0d", 1.94),
        ],
        agents=[
            agent("planner", "planning"),
            agent("general", "orchestration"),
            agent("verifier", "verification"),
        ],
        models=[
            ModelCandidate(
                name="auto/best-coding",
                provider_kind="PROXY",
                quality=0.9,
                reliability=0.9,
                latency_ms=1200,
                cost_eur=0.0,
                risk=0.1,
                capabilities=frozenset({"planning", "orchestration", "verification"}),
            )
        ],
        tools=[
            MCPToolRef("mcp__skills__skills_search", True, frozenset({"planning", "orchestration"})),
            MCPToolRef("mcp__skills__skills_validate", True, frozenset({"verification"})),
        ],
    )
    assert plan.selected_skills[0].skill_id == "clement.agent-orchestration.db91fa689e0d"
    assert plan.coalition.complete is True
    assert {item.name for item in plan.coalition.agents} == {"planner", "general", "verifier"}
    assert plan.verdict == "PASS"


def test_no_model_is_fail():
    task = TaskContext(objective="x", required_skills=frozenset({"planning"}))
    plan = build_plan(
        task=task,
        skill_matches=[SkillMatch("planning", 1.0)],
        agents=[agent("planner", "planning")],
        models=[],
        tools=[MCPToolRef("mcp__skills__skills_search", True, frozenset({"planning"}))],
    )
    assert plan.verdict == "FAIL"
    assert "no_model_candidate" in plan.reasons


def test_retry_requires_new_evidence():
    task = TaskContext(objective="x", required_skills=frozenset({"planning"}))
    plan = build_plan(
        task=task,
        skill_matches=[SkillMatch("planning", 1.0)],
        agents=[agent("planner", "planning")],
        models=[model()],
        tools=[],
    )
    assert plan.verdict == "PARTIAL"
    assert should_retry(plan, attempt=1, new_evidence=False) is False
    assert should_retry(plan, attempt=1, new_evidence=True) is True
    assert should_retry(plan, attempt=3, new_evidence=True) is False
