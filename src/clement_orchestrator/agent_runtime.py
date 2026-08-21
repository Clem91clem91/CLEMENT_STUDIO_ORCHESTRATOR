from __future__ import annotations

import itertools
import math
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping


class AgentState(str, Enum):
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    STOPPED = "STOPPED"


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    capabilities: tuple[str, ...]
    mentalities: tuple[str, ...] = ()
    description: str = ""


@dataclass(slots=True)
class AgentInstance:
    agent_id: str
    spec: AgentSpec
    state: AgentState = AgentState.CREATED
    task: Mapping[str, Any] | None = None
    inbox: list[Mapping[str, Any]] = field(default_factory=list)
    result: Any = None
    score: float | None = None
    created_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.spec.name,
            "capabilities": list(self.spec.capabilities),
            "mentalities": list(self.spec.mentalities),
            "state": self.state.value,
            "task": dict(self.task or {}),
            "inbox_size": len(self.inbox),
            "result": self.result,
            "score": self.score,
        }


@dataclass(slots=True)
class Coalition:
    coalition_id: str
    agent_ids: list[str]
    required_capabilities: tuple[str, ...]
    score: float | None = None
    promoted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "coalition_id": self.coalition_id,
            "agent_ids": list(self.agent_ids),
            "required_capabilities": list(self.required_capabilities),
            "score": self.score,
            "promoted": self.promoted,
            "metadata": dict(self.metadata),
        }


DEFAULT_AGENT_SPECS = (
    AgentSpec("planner", ("planning", "decomposition"), ("planning", "analytical")),
    AgentSpec("general", ("general", "execution"), ("analytical",)),
    AgentSpec("code", ("code", "powershell", "automation"), ("engineering",)),
    AgentSpec("documents", ("documents", "drive"), ("minimalist",)),
    AgentSpec("creative", ("creative", "image", "video"), ("creative",)),
    AgentSpec("3d", ("3d", "blender", "unreal"), ("engineering", "creative")),
    AgentSpec("verifier", ("verification", "qa"), ("verification", "skeptical")),
)


def _caps(values: Iterable[str]) -> frozenset[str]:
    return frozenset(str(value).strip().casefold() for value in values if str(value).strip())


class AgentRuntime:
    """Dynamic agent runtime with no hard-coded agent-count ceiling."""

    def __init__(self, specs: Iterable[AgentSpec] = DEFAULT_AGENT_SPECS) -> None:
        self._specs: dict[str, AgentSpec] = {spec.name: spec for spec in specs}
        self._agents: dict[str, AgentInstance] = {}
        self._coalitions: dict[str, Coalition] = {}
        self._promotion: str | None = None

    def register_spec(self, spec: AgentSpec) -> None:
        self._specs[spec.name] = spec

    def agent_spawn(self, spec_name: str, *, ready: bool = True) -> AgentInstance:
        if spec_name not in self._specs:
            raise KeyError(f"UNKNOWN_AGENT_SPEC={spec_name}")
        agent = AgentInstance(
            agent_id=f"AGENT-{uuid.uuid4().hex[:12]}",
            spec=self._specs[spec_name],
            state=AgentState.READY if ready else AgentState.CREATED,
        )
        self._agents[agent.agent_id] = agent
        return agent

    def agent_stop(self, agent_id: str) -> dict[str, Any]:
        agent = self._agent(agent_id)
        agent.state = AgentState.STOPPED
        return agent.as_dict()

    def agent_status(self, agent_id: str | None = None) -> dict[str, Any]:
        if agent_id is not None:
            return self._agent(agent_id).as_dict()
        return {"total": len(self._agents), "agents": [agent.as_dict() for agent in sorted(self._agents.values(), key=lambda item: item.agent_id)]}

    def agent_assign(self, agent_id: str, task: Mapping[str, Any]) -> dict[str, Any]:
        agent = self._agent(agent_id)
        if agent.state in {AgentState.STOPPED, AgentState.FAILED}:
            raise RuntimeError(f"AGENT_NOT_ASSIGNABLE={agent_id}:{agent.state.value}")
        agent.task = dict(task)
        agent.state = AgentState.RUNNING
        return agent.as_dict()

    def agent_message(self, agent_id: str, message: Mapping[str, Any]) -> dict[str, Any]:
        agent = self._agent(agent_id)
        if agent.state is AgentState.STOPPED:
            raise RuntimeError(f"AGENT_STOPPED={agent_id}")
        agent.inbox.append(dict(message))
        if agent.state is AgentState.CREATED:
            agent.state = AgentState.READY
        return agent.as_dict()

    def agent_result(self, agent_id: str, result: Any = None, *, failed: bool = False, verified: bool = False, score: float | None = None) -> dict[str, Any]:
        agent = self._agent(agent_id)
        if result is not None:
            agent.result = result
        if score is not None:
            agent.score = float(score)
        if failed:
            agent.state = AgentState.FAILED
        elif verified:
            agent.state = AgentState.VERIFIED
        elif result is not None:
            agent.state = AgentState.COMPLETED
        return agent.as_dict()

    def coalition_create(self, agent_ids: Iterable[str], required_capabilities: Iterable[str] = (), metadata: Mapping[str, Any] | None = None) -> Coalition:
        ids = list(dict.fromkeys(agent_ids))
        if not ids:
            raise ValueError("COALITION_EMPTY")
        for agent_id in ids:
            self._agent(agent_id)
        coalition = Coalition(
            coalition_id=f"COALITION-{uuid.uuid4().hex[:12]}",
            agent_ids=ids,
            required_capabilities=tuple(sorted(_caps(required_capabilities))),
            metadata=dict(metadata or {}),
        )
        self._coalitions[coalition.coalition_id] = coalition
        return coalition

    def coalition_score(self, coalition_id: str, *, quality: float, capability_coverage: float, verification: float, efficiency: float) -> float:
        coalition = self._coalition(coalition_id)
        values = [quality, capability_coverage, verification, efficiency]
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("SCORE_COMPONENT_OUT_OF_RANGE")
        score = 0.35 * quality + 0.30 * capability_coverage + 0.25 * verification + 0.10 * efficiency
        coalition.score = round(score, 6)
        return coalition.score

    def coalition_compare(self, coalition_ids: Iterable[str]) -> list[dict[str, Any]]:
        coalitions = [self._coalition(cid) for cid in coalition_ids]
        return [item.as_dict() for item in sorted(coalitions, key=lambda item: (-(item.score if item.score is not None else -1.0), item.coalition_id))]

    def coalition_promote(self, coalition_id: str) -> dict[str, Any]:
        selected = self._coalition(coalition_id)
        for coalition in self._coalitions.values():
            coalition.promoted = False
        selected.promoted = True
        self._promotion = coalition_id
        return selected.as_dict()

    def coalition_destroy(self, coalition_id: str) -> dict[str, Any]:
        coalition = self._coalition(coalition_id)
        if coalition.promoted:
            raise RuntimeError("CANNOT_DESTROY_PROMOTED_COALITION")
        deleted = coalition.as_dict()
        del self._coalitions[coalition_id]
        return deleted

    def adaptive_team(self, required_capabilities: Iterable[str], *, complexity: int = 1, desired_size: int | None = None) -> list[AgentInstance]:
        required = _caps(required_capabilities)
        complexity = max(1, int(complexity))
        if desired_size is None:
            breadth = max(1, len(required))
            desired_size = max(2, math.ceil(complexity * 0.72) + max(0, breadth - 2))
        desired_size = max(1, int(desired_size))
        selected_specs: list[str] = []
        uncovered = set(required)
        candidates = list(self._specs.values())
        while uncovered:
            ranked = sorted(candidates, key=lambda spec: (-len(_caps(spec.capabilities) & uncovered), spec.name))
            best = ranked[0] if ranked else None
            if best is None or not (_caps(best.capabilities) & uncovered):
                break
            selected_specs.append(best.name)
            uncovered -= set(_caps(best.capabilities))
            candidates = [item for item in candidates if item.name != best.name]
        if complexity >= 3 and "planner" in self._specs and "planner" not in selected_specs:
            selected_specs.append("planner")
        if complexity >= 4 and "verifier" in self._specs and "verifier" not in selected_specs:
            selected_specs.append("verifier")
        fallback_cycle = [name for name in ("general", "verifier", "planner", "code") if name in self._specs] or list(self._specs)
        if not fallback_cycle:
            raise RuntimeError("NO_AGENT_SPECS_REGISTERED")
        cycle = itertools.cycle(fallback_cycle)
        while len(selected_specs) < desired_size:
            selected_specs.append(next(cycle))
        return [self.agent_spawn(name) for name in selected_specs]

    def arena(self, coalitions: Iterable[str]) -> list[dict[str, Any]]:
        return self.coalition_compare(coalitions)

    @property
    def promoted_coalition_id(self) -> str | None:
        return self._promotion

    def _agent(self, agent_id: str) -> AgentInstance:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"UNKNOWN_AGENT={agent_id}") from exc

    def _coalition(self, coalition_id: str) -> Coalition:
        try:
            return self._coalitions[coalition_id]
        except KeyError as exc:
            raise KeyError(f"UNKNOWN_COALITION={coalition_id}") from exc