from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ResourceMode(str, Enum):
    IDLE = "IDLE"
    AGENT = "AGENT"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    BLENDER = "BLENDER"
    UNREAL = "UNREAL"
    HYBRID = "HYBRID"


class ResourceAction(str, Enum):
    ALLOW = "ALLOW"
    WAIT = "WAIT"
    RELEASE_CURRENT = "RELEASE_CURRENT"
    HYBRID = "HYBRID"
    DENY = "DENY"


class ActionRisk(str, Enum):
    SAFE = "SAFE"
    SENSITIVE = "SENSITIVE"
    DESTRUCTIVE = "DESTRUCTIVE"


class ActionDecision(str, Enum):
    ACTION_ALLOWED = "ACTION_ALLOWED"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    ACTION_REQUIRES_APPROVAL = "ACTION_REQUIRES_APPROVAL"


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    cpu_percent: float
    ram_percent: float
    vram_percent: float
    gpu_percent: float = 0.0
    processes: tuple[str, ...] = ()

    def validate(self) -> None:
        for name, value in (("cpu_percent", self.cpu_percent), ("ram_percent", self.ram_percent), ("vram_percent", self.vram_percent), ("gpu_percent", self.gpu_percent)):
            if value < 0 or value > 100:
                raise ValueError(f"{name.upper()}_OUT_OF_RANGE={value}")


@dataclass(frozen=True, slots=True)
class ResourcePlan:
    requested_mode: ResourceMode
    current_mode: ResourceMode
    action: ResourceAction
    reason: str
    priority: int
    snapshot: ResourceSnapshot

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_mode": self.requested_mode.value,
            "current_mode": self.current_mode.value,
            "action": self.action.value,
            "reason": self.reason,
            "priority": self.priority,
            "snapshot": {
                "cpu_percent": self.snapshot.cpu_percent,
                "ram_percent": self.snapshot.ram_percent,
                "vram_percent": self.snapshot.vram_percent,
                "gpu_percent": self.snapshot.gpu_percent,
                "processes": list(self.snapshot.processes),
            },
        }


@dataclass(frozen=True, slots=True)
class SecurityDecision:
    action: str
    risk: ActionRisk
    decision: ActionDecision
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "risk": self.risk.value, "decision": self.decision.value, "reason": self.reason}


class ResourceManager:
    """Fail-closed CPU/RAM/VRAM concurrency arbiter."""

    def __init__(self, *, critical_vram: float = 90.0, high_vram: float = 80.0, critical_ram: float = 92.0, critical_cpu: float = 98.0) -> None:
        self.critical_vram = float(critical_vram)
        self.high_vram = float(high_vram)
        self.critical_ram = float(critical_ram)
        self.critical_cpu = float(critical_cpu)

    def evaluate(self, snapshot: ResourceSnapshot, *, current_mode: ResourceMode, requested_mode: ResourceMode, requested_priority: int = 50, current_priority: int = 50) -> ResourcePlan:
        snapshot.validate()
        requested_priority = int(requested_priority)
        current_priority = int(current_priority)
        if requested_mode is ResourceMode.IDLE:
            return ResourcePlan(requested_mode, current_mode, ResourceAction.ALLOW, "REQUESTED_IDLE", requested_priority, snapshot)
        if snapshot.ram_percent >= self.critical_ram or snapshot.cpu_percent >= self.critical_cpu:
            return ResourcePlan(requested_mode, current_mode, ResourceAction.WAIT, "SYSTEM_PRESSURE_CRITICAL", requested_priority, snapshot)
        gpu_heavy = {ResourceMode.IMAGE, ResourceMode.VIDEO, ResourceMode.BLENDER, ResourceMode.UNREAL}
        if snapshot.vram_percent >= self.critical_vram and requested_mode in gpu_heavy:
            if current_mode is ResourceMode.VIDEO and requested_mode is ResourceMode.BLENDER:
                if requested_priority > current_priority:
                    return ResourcePlan(requested_mode, current_mode, ResourceAction.RELEASE_CURRENT, "VRAM_CRITICAL_PREEMPT_VIDEO_FOR_HIGHER_PRIORITY_BLENDER", requested_priority, snapshot)
                return ResourcePlan(requested_mode, current_mode, ResourceAction.WAIT, "VRAM_CRITICAL_VIDEO_ACTIVE", requested_priority, snapshot)
            return ResourcePlan(requested_mode, current_mode, ResourceAction.WAIT, "VRAM_CRITICAL", requested_priority, snapshot)
        if snapshot.vram_percent >= self.high_vram and requested_mode in gpu_heavy and current_mode in gpu_heavy and current_mode is not requested_mode:
            return ResourcePlan(requested_mode, current_mode, ResourceAction.HYBRID, "VRAM_HIGH_USE_HYBRID_OR_SERIALIZE", requested_priority, snapshot)
        return ResourcePlan(requested_mode, current_mode, ResourceAction.ALLOW, "RESOURCE_BUDGET_AVAILABLE", requested_priority, snapshot)


class SecurityGuard:
    """Classify actions and produce one of the three P1-03 decisions."""

    DESTRUCTIVE_MARKERS = ("delete", "remove", "trash", "purge", "format", "git push --force", "push --force", "reset --hard", "drop database", "terminate", "kill_process")
    SENSITIVE_MARKERS = ("write", "create", "copy", "move", "rename", "upload", "replace", "update", "powershell", "execute", "run_", "git push", "send", "publish")
    SAFE_MARKERS = ("read", "list", "status", "search", "get_", "stat", "hash", "compare", "validate", "health", "discover")

    def __init__(self, *, destructive_policy: str = "BLOCK", sensitive_requires_approval: bool = True) -> None:
        if destructive_policy not in {"BLOCK", "APPROVAL"}:
            raise ValueError("DESTRUCTIVE_POLICY_INVALID")
        self.destructive_policy = destructive_policy
        self.sensitive_requires_approval = bool(sensitive_requires_approval)

    def classify(self, action: str, *, explicit_risk: ActionRisk | None = None) -> ActionRisk:
        if explicit_risk is not None:
            return explicit_risk
        text = action.strip().casefold()
        if any(marker in text for marker in self.DESTRUCTIVE_MARKERS):
            return ActionRisk.DESTRUCTIVE
        if any(marker in text for marker in self.SENSITIVE_MARKERS):
            return ActionRisk.SENSITIVE
        if any(marker in text for marker in self.SAFE_MARKERS):
            return ActionRisk.SAFE
        return ActionRisk.SENSITIVE

    def decide(self, action: str, *, approved: bool = False, explicit_risk: ActionRisk | None = None) -> SecurityDecision:
        risk = self.classify(action, explicit_risk=explicit_risk)
        if risk is ActionRisk.SAFE:
            return SecurityDecision(action, risk, ActionDecision.ACTION_ALLOWED, "SAFE_ACTION")
        if risk is ActionRisk.SENSITIVE:
            if approved or not self.sensitive_requires_approval:
                return SecurityDecision(action, risk, ActionDecision.ACTION_ALLOWED, "SENSITIVE_APPROVED")
            return SecurityDecision(action, risk, ActionDecision.ACTION_REQUIRES_APPROVAL, "SENSITIVE_REQUIRES_APPROVAL")
        if self.destructive_policy == "APPROVAL":
            if approved:
                return SecurityDecision(action, risk, ActionDecision.ACTION_ALLOWED, "DESTRUCTIVE_EXPLICITLY_APPROVED")
            return SecurityDecision(action, risk, ActionDecision.ACTION_REQUIRES_APPROVAL, "DESTRUCTIVE_REQUIRES_APPROVAL")
        return SecurityDecision(action, risk, ActionDecision.ACTION_BLOCKED, "DESTRUCTIVE_BLOCKED_BY_POLICY")