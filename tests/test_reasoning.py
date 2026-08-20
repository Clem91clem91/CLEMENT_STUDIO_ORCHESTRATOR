from clement_orchestrator.core import AgentProfile, Mentality, TaskContext
from clement_orchestrator.adaptive import build_adaptive_plan
from clement_orchestrator.pipeline import MCPToolRef, ModelCandidate, SkillMatch
from clement_orchestrator.reasoning import infer_mentalities


def test_security_development_mission_activates_multiple_mentalities():
    result = infer_mentalities("Develop a secure MCP system, test it, verify evidence and plan deployment")
    assert Mentality.ANALYTICAL in result
    assert Mentality.SECURITY in result
    assert Mentality.ENGINEERING in result
    assert Mentality.VERIFICATION in result
    assert Mentality.SKEPTICAL in result
    assert Mentality.PLANNING in result


def test_creative_research_mission_is_not_forced_to_engineering_only():
    result = infer_mentalities("Research visual concepts and create a brand design")
    assert Mentality.RESEARCH in result
    assert Mentality.CREATIVE in result
    assert Mentality.ANALYTICAL in result


def test_adaptive_plan_uses_inferred_mentalities_when_not_explicit():
    task = TaskContext(objective="Plan, build and verify a secure system", required_skills=frozenset({"planning"}))
    inferred = infer_mentalities(task.objective)
    agents = [
        AgentProfile(
            name="multi",
            skills=frozenset({"planning"}),
            mentalities=inferred,
            quality=0.95,
            reliability=0.95,
        )
    ]
    models = [
        ModelCandidate(
            "local",
            "LOCAL",
            quality=0.9,
            reliability=0.9,
            latency_ms=100,
            cost_eur=0,
            risk=0.1,
            capabilities=frozenset({"planning"}),
        )
    ]
    plan = build_adaptive_plan(
        task=task,
        skill_matches=[SkillMatch("planning", 1.0)],
        agents=agents,
        models=models,
        tools=[MCPToolRef("mcp__skills__skills_search", True, frozenset({"planning"}))],
    )
    assert plan.coalition.complete is True
    assert inferred.issubset(plan.coalition.covered_mentalities)
