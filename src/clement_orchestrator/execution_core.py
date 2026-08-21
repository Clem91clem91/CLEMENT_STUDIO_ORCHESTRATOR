from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .agent_runtime import AgentRuntime
from .execution_fabric import ExecutionFabric, ExecutionResult, PermissionDecision, RiskLevel, ToolDescriptor
from .observability import TaskObserver
from .resource_guard import ActionDecision, ActionRisk, ResourceManager, ResourceMode, ResourceSnapshot, SecurityGuard

@dataclass(slots=True)
class MissionContext:
    task_id: str
    agent_ids: list[str]
    coalition_id: str | None = None

class ExecutionCore:
    """P1 integration point used by the existing Orchestrator."""
    def __init__(self, *, log_root: str | Path, fabric: ExecutionFabric | None = None, agents: AgentRuntime | None = None, resources: ResourceManager | None = None, security: SecurityGuard | None = None) -> None:
        self.fabric = fabric or ExecutionFabric(); self.agents = agents or AgentRuntime(); self.resources = resources or ResourceManager(); self.security = security or SecurityGuard(); self.observer = TaskObserver(log_root)

    def begin_mission(self, prompt: str, intent: str, *, skills: Iterable[str], models: Iterable[str], required_agent_capabilities: Iterable[str], complexity: int, desired_agent_count: int | None = None, task_id: str | None = None) -> MissionContext:
        trace = self.observer.start_task(prompt, intent, task_id=task_id); self.observer.add_skills(trace.task_id, skills); self.observer.add_models(trace.task_id, models)
        team = self.agents.adaptive_team(required_agent_capabilities, complexity=complexity, desired_size=desired_agent_count)
        ids = [agent.agent_id for agent in team]; self.observer.add_agents(trace.task_id, ids); return MissionContext(task_id=trace.task_id, agent_ids=ids)

    def create_coalition(self, mission: MissionContext, required_capabilities: Iterable[str]) -> str:
        coalition = self.agents.coalition_create(mission.agent_ids, required_capabilities, metadata={"task_id": mission.task_id}); mission.coalition_id = coalition.coalition_id; self.observer.add_coalition(mission.task_id, coalition.as_dict()); return coalition.coalition_id

    def authorize_tool(self, descriptor: ToolDescriptor, *, approved: bool = False) -> PermissionDecision:
        security_decision = self.security.decide(descriptor.tool, approved=approved, explicit_risk=ActionRisk(descriptor.risk.value))
        mapping = {ActionDecision.ACTION_ALLOWED: PermissionDecision.ACTION_ALLOWED, ActionDecision.ACTION_BLOCKED: PermissionDecision.ACTION_BLOCKED, ActionDecision.ACTION_REQUIRES_APPROVAL: PermissionDecision.ACTION_REQUIRES_APPROVAL}
        return mapping[security_decision.decision]

    def resource_plan(self, mission: MissionContext, snapshot: ResourceSnapshot, *, current_mode: ResourceMode, requested_mode: ResourceMode, requested_priority: int = 50, current_priority: int = 50) -> dict[str, Any]:
        plan = self.resources.evaluate(snapshot, current_mode=current_mode, requested_mode=requested_mode, requested_priority=requested_priority, current_priority=current_priority); self.observer.add_gpu(mission.task_id, plan.as_dict()); return plan.as_dict()

    async def execute_capability(self, mission: MissionContext, required_capabilities: Iterable[str], payload: Mapping[str, Any], *, preferred_servers: Iterable[str] = (), approved: bool = False, max_attempts: int = 3, max_risk: RiskLevel = RiskLevel.DESTRUCTIVE) -> ExecutionResult:
        descriptor = self.fabric.tools_select(required_capabilities, preferred_servers=preferred_servers, max_risk=max_risk); self.observer.add_mcp(mission.task_id, [descriptor.server]); permission = self.authorize_tool(descriptor, approved=approved)
        if permission is PermissionDecision.ACTION_BLOCKED:
            result = await self.fabric.tools_execute_async(descriptor, payload, approved=False, allow_destructive=False)
        else:
            result = await self.fabric.tools_retry_async(descriptor, payload, approved=(permission is PermissionDecision.ACTION_ALLOWED), allow_destructive=approved, max_attempts=max_attempts)
        self.observer.add_tool_call(mission.task_id, result.as_dict())
        if result.attempts > 1:
            for _ in range(result.attempts - 1): self.observer.add_retry(mission.task_id, reason=result.error or "")
        if not result.ok and result.error: self.observer.add_error(mission.task_id, result.error)
        return result

    def add_token_usage(self, mission: MissionContext, *, technical: int, billable: int) -> None:
        self.observer.add_tokens(mission.task_id, technical=technical, billable=billable)

    def finish_mission(self, mission: MissionContext, *, result: str, verification: str) -> tuple[Path, Path]:
        return self.observer.finish(mission.task_id, result=result, verification=verification)