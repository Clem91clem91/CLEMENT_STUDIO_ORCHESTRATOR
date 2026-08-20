from __future__ import annotations

import json
from dataclasses import asdict

from clement_orchestrator.core import AgentProfile, Mentality, TaskContext
from clement_orchestrator.pipeline import MCPToolRef, ModelCandidate, SkillMatch, build_plan


def main() -> int:
    task = TaskContext(
        objective="CLEMENT P0-04 certification smoke",
        required_skills=frozenset({"planning", "orchestration", "verification"}),
        required_mentalities=frozenset({Mentality.PLANNING, Mentality.ENGINEERING, Mentality.VERIFICATION}),
        available_vram_gb=20.0,
        risk_tolerance=0.4,
    )
    agents = [
        AgentProfile("planner", frozenset({"planning"}), mentalities=frozenset({Mentality.PLANNING}), quality=0.9, reliability=0.9),
        AgentProfile("orchestrator", frozenset({"orchestration"}), mentalities=frozenset({Mentality.ENGINEERING}), quality=0.9, reliability=0.9),
        AgentProfile("verifier", frozenset({"verification"}), mentalities=frozenset({Mentality.VERIFICATION}), quality=0.95, reliability=0.95),
    ]
    skills = [
        SkillMatch("planning", 1.0, estimated_context_cost=100),
        SkillMatch("orchestration", 0.95, dependencies=("planning",), estimated_context_cost=100),
        SkillMatch("verification", 0.9, estimated_context_cost=100),
    ]
    models = [
        ModelCandidate(
            "qwen/qwen3-30b-a3b",
            "LOCAL",
            quality=0.9,
            reliability=0.9,
            latency_ms=500,
            cost_eur=0.0,
            risk=0.1,
            capabilities=frozenset({"planning", "orchestration", "verification"}),
        )
    ]
    tools = [
        MCPToolRef("mcp__skills__skills_search", True, frozenset({"planning", "orchestration"})),
        MCPToolRef("mcp__skills__skills_validate", True, frozenset({"verification"})),
    ]
    plan = build_plan(task=task, skill_matches=skills, agents=agents, models=models, tools=tools)
    payload = {
        "task_id": plan.task_id,
        "verdict": plan.verdict,
        "coalition_size": len(plan.coalition.agents),
        "coalition_complete": plan.coalition.complete,
        "selected_model": plan.selected_model.name if plan.selected_model else None,
        "selected_tools": [item.qualified_name for item in plan.selected_tools],
        "arena": [item.name for item in plan.arena],
        "strategies": [item.name for item in plan.strategies],
        "reasons": list(plan.reasons),
    }
    print(json.dumps(payload, indent=2))
    required = (
        plan.coalition.complete
        and plan.selected_model is not None
        and len(plan.selected_tools) == 2
        and {item.name for item in plan.arena} == {"A", "B", "C", "D"}
    )
    print(f"RESULT={'PASS' if required else 'FAIL'}")
    return 0 if required else 1


if __name__ == "__main__":
    raise SystemExit(main())
