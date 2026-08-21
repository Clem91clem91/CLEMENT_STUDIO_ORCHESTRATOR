from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable, Mapping


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    SENSITIVE = "SENSITIVE"
    DESTRUCTIVE = "DESTRUCTIVE"


class PermissionDecision(str, Enum):
    ACTION_ALLOWED = "ACTION_ALLOWED"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    ACTION_REQUIRES_APPROVAL = "ACTION_REQUIRES_APPROVAL"


class ExecutionStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"


Executor = Callable[[Mapping[str, Any]], Any]
HealthCheck = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    tool: str
    server: str
    capabilities: tuple[str, ...] = ()
    risk: RiskLevel = RiskLevel.SAFE
    available: bool = True
    read_only: bool = False
    retryable: bool = True
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.server}.{self.tool}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "server": self.server,
            "capabilities": list(self.capabilities),
            "risk": self.risk.value,
            "available": self.available,
            "read_only": self.read_only,
            "retryable": self.retryable,
            "description": self.description,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ExecutionResult:
    execution_id: str
    tool_key: str
    status: ExecutionStatus
    permission: PermissionDecision
    attempts: int
    started_at: float
    finished_at: float
    output: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is ExecutionStatus.PASS

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "tool_key": self.tool_key,
            "status": self.status.value,
            "permission": self.permission.value,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output": self.output,
            "error": self.error,
        }


@dataclass(slots=True)
class _Binding:
    descriptor: ToolDescriptor
    executor: Executor | None = None
    healthcheck: HealthCheck | None = None


def _normalise_caps(values: Iterable[str]) -> frozenset[str]:
    return frozenset(str(value).strip().upper() for value in values if str(value).strip())


def _infer_risk(tool_name: str, capabilities: Iterable[str]) -> RiskLevel:
    name = tool_name.casefold()
    caps = _normalise_caps(capabilities)
    destructive_markers = (
        "delete", "remove", "trash", "purge", "format", "force_push",
        "reset_hard", "terminate", "kill", "drop",
    )
    sensitive_markers = (
        "write", "move", "copy", "upload", "create", "replace",
        "powershell", "execute", "run_", "update", "rename", "append",
    )
    safe_markers = (
        "read", "list", "status", "search", "get_", "stat",
        "hash", "compare", "validate", "health", "discover",
    )
    if any(marker in name for marker in destructive_markers):
        return RiskLevel.DESTRUCTIVE
    if any(marker in name for marker in safe_markers) and not any(
        marker in name for marker in sensitive_markers
    ):
        return RiskLevel.SAFE
    if "EXECUTE" in caps or "WRITE" in caps or any(marker in name for marker in sensitive_markers):
        return RiskLevel.SENSITIVE
    return RiskLevel.SAFE


def _infer_tool_capabilities(tool_name: str, server_capabilities: Iterable[str]) -> frozenset[str]:
    name = tool_name.casefold()
    server_caps = _normalise_caps(server_capabilities)
    caps = set(server_caps - {"READ", "WRITE", "EXECUTE", "DELETE"})
    if any(marker in name for marker in ("read", "list", "status", "search", "get_", "stat", "hash", "compare", "validate", "health")):
        caps.add("READ")
    if any(marker in name for marker in ("write", "append", "create", "replace", "upload", "copy", "move", "rename", "update")):
        caps.add("WRITE")
    if any(marker in name for marker in ("powershell", "execute", "run_")):
        caps.add("EXECUTE")
    if "text" in name:
        caps.add("TEXT")
    if any(marker in name for marker in ("file", "path", "directory", "folder")):
        caps.add("FILESYSTEM")
    if "powershell" in name:
        caps.add("POWERSHELL")
    if "prepare_powershell" in name:
        caps.add("POWERSHELL_PREPARE")
    if "run_powershell" in name:
        caps.add("POWERSHELL_RUN")
    if "drive" in name:
        caps.add("GOOGLE_DRIVE")
    if "drive_upload" in name or ("upload" in name and "drive" in name):
        caps.add("DRIVE_UPLOAD")
    if "move" in name:
        caps.add("MOVE")
    if any(marker in name for marker in ("copy", "upload")):
        caps.add("COPY")
    return frozenset(caps)


class ExecutionFabric:
    """Unified deterministic registry/selector/executor for MCP and external tools."""

    def __init__(self) -> None:
        self._bindings: dict[str, _Binding] = {}
        self._results: dict[str, ExecutionResult] = {}

    def register(self, descriptor: ToolDescriptor, executor: Executor | None = None, healthcheck: HealthCheck | None = None) -> ToolDescriptor:
        self._bindings[descriptor.key] = _Binding(descriptor, executor, healthcheck)
        return descriptor

    def register_many(self, descriptors: Iterable[ToolDescriptor]) -> None:
        for descriptor in descriptors:
            self.register(descriptor)

    def ingest_mcp_registry(self, registry: Mapping[str, Any]) -> list[ToolDescriptor]:
        descriptors: list[ToolDescriptor] = []
        for component in registry.get("components", []):
            server = str(component.get("key") or component.get("name") or "").strip()
            if not server:
                continue
            caps = tuple(sorted(_normalise_caps(component.get("capabilities", []))))
            descriptor = ToolDescriptor(
                tool="__server__", server=server, capabilities=caps,
                risk=RiskLevel.SAFE,
                available=bool(component.get("current_odysseus_enabled", False)),
                read_only="WRITE" not in caps and "EXECUTE" not in caps,
                retryable=False, description=str(component.get("name") or server),
                metadata={"id": component.get("id"), "version": component.get("version"), "transport": component.get("transport"), "status": component.get("status")},
            )
            self.register(descriptor)
            descriptors.append(descriptor)
        return descriptors

    def ingest_tool_catalog(self, server: str, tools: Iterable[Mapping[str, Any]], server_capabilities: Iterable[str] = ()) -> list[ToolDescriptor]:
        registered: list[ToolDescriptor] = []
        server_caps = _normalise_caps(server_capabilities)
        for tool in tools:
            name = str(tool.get("name") or "").strip()
            if not name:
                continue
            annotations = tool.get("annotations") or {}
            own_caps = _normalise_caps(tool.get("capabilities") or ())
            caps = tuple(sorted(_infer_tool_capabilities(name, server_caps) | own_caps))
            read_only = bool(annotations.get("readOnlyHint") or annotations.get("read_only") or annotations.get("readOnly"))
            risk = RiskLevel.SAFE if read_only else _infer_risk(name, caps)
            descriptor = ToolDescriptor(
                tool=name, server=server, capabilities=caps, risk=risk,
                available=True, read_only=read_only,
                retryable=not bool(annotations.get("destructiveHint")),
                description=str(tool.get("description") or ""),
                metadata={"annotations": dict(annotations)},
            )
            self.register(descriptor)
            registered.append(descriptor)
        return registered

    def bind_executor(self, tool_key: str, executor: Executor, healthcheck: HealthCheck | None = None) -> None:
        if tool_key not in self._bindings:
            raise KeyError(f"UNKNOWN_TOOL={tool_key}")
        self._bindings[tool_key].executor = executor
        if healthcheck is not None:
            self._bindings[tool_key].healthcheck = healthcheck

    def tools_discover(self, *, server: str | None = None, capability: str | None = None, available_only: bool = False) -> list[dict[str, Any]]:
        items = [binding.descriptor for binding in self._bindings.values()]
        if server:
            items = [item for item in items if item.server == server]
        if capability:
            cap = capability.strip().upper()
            items = [item for item in items if cap in _normalise_caps(item.capabilities)]
        if available_only:
            items = [item for item in items if item.available]
        return [item.as_dict() for item in sorted(items, key=lambda item: item.key)]

    async def tools_health_async(self) -> dict[str, dict[str, Any]]:
        report: dict[str, dict[str, Any]] = {}
        for key, binding in sorted(self._bindings.items()):
            available = binding.descriptor.available
            error: str | None = None
            if binding.healthcheck is not None:
                try:
                    value = binding.healthcheck()
                    if inspect.isawaitable(value):
                        value = await value
                    available = bool(value.get("available", value.get("ok", True))) if isinstance(value, Mapping) else bool(value)
                except Exception as exc:
                    available = False
                    error = f"{type(exc).__name__}:{exc}"
            report[key] = {"available": available, "error": error}
        return report

    def tools_health(self) -> dict[str, dict[str, Any]]:
        return _run_sync(self.tools_health_async())

    def tools_capabilities(self, tool_key: str | None = None) -> dict[str, Any]:
        if tool_key is not None:
            return self._descriptor(tool_key).as_dict()
        by_capability: dict[str, list[str]] = {}
        for key, binding in sorted(self._bindings.items()):
            for cap in sorted(_normalise_caps(binding.descriptor.capabilities)):
                by_capability.setdefault(cap, []).append(key)
        return by_capability

    def tools_select(self, required_capabilities: Iterable[str], *, preferred_servers: Iterable[str] = (), max_risk: RiskLevel = RiskLevel.DESTRUCTIVE, available_only: bool = True) -> ToolDescriptor:
        required = _normalise_caps(required_capabilities)
        preferred = tuple(preferred_servers)
        risk_rank = {RiskLevel.SAFE: 0, RiskLevel.SENSITIVE: 1, RiskLevel.DESTRUCTIVE: 2}
        candidates: list[tuple[tuple[int, int, str], ToolDescriptor]] = []
        for binding in self._bindings.values():
            item = binding.descriptor
            if item.tool == "__server__" or (available_only and not item.available):
                continue
            caps = _normalise_caps(item.capabilities)
            if not required.issubset(caps) or risk_rank[item.risk] > risk_rank[max_risk]:
                continue
            preferred_rank = preferred.index(item.server) if item.server in preferred else len(preferred)
            candidates.append(((len(caps - required), preferred_rank, item.key), item))
        if not candidates:
            raise LookupError("NO_TOOL_MATCH required=" + ",".join(sorted(required)))
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    def tools_permissions(self, tool: ToolDescriptor | str, *, approved: bool = False, allow_destructive: bool = False) -> PermissionDecision:
        descriptor = self._descriptor(tool) if isinstance(tool, str) else tool
        if descriptor.risk is RiskLevel.SAFE:
            return PermissionDecision.ACTION_ALLOWED
        if descriptor.risk is RiskLevel.SENSITIVE:
            return PermissionDecision.ACTION_ALLOWED if approved else PermissionDecision.ACTION_REQUIRES_APPROVAL
        if not allow_destructive:
            return PermissionDecision.ACTION_BLOCKED
        return PermissionDecision.ACTION_ALLOWED if approved else PermissionDecision.ACTION_REQUIRES_APPROVAL

    async def tools_execute_async(self, tool: ToolDescriptor | str, payload: Mapping[str, Any] | None = None, *, approved: bool = False, allow_destructive: bool = False, attempts: int = 1) -> ExecutionResult:
        descriptor = self._descriptor(tool) if isinstance(tool, str) else tool
        permission = self.tools_permissions(descriptor, approved=approved, allow_destructive=allow_destructive)
        started = time.time()
        execution_id = f"EXEC-{uuid.uuid4().hex[:16]}"
        if permission is PermissionDecision.ACTION_BLOCKED:
            result = ExecutionResult(execution_id, descriptor.key, ExecutionStatus.BLOCKED, permission, attempts, started, time.time(), error="ACTION_BLOCKED")
            self._results[execution_id] = result
            return result
        if permission is PermissionDecision.ACTION_REQUIRES_APPROVAL:
            result = ExecutionResult(execution_id, descriptor.key, ExecutionStatus.APPROVAL_REQUIRED, permission, attempts, started, time.time(), error="ACTION_REQUIRES_APPROVAL")
            self._results[execution_id] = result
            return result
        binding = self._bindings.get(descriptor.key)
        if binding is None or not descriptor.available or binding.executor is None:
            result = ExecutionResult(execution_id, descriptor.key, ExecutionStatus.UNAVAILABLE, permission, attempts, started, time.time(), error="TOOL_UNAVAILABLE")
            self._results[execution_id] = result
            return result
        try:
            output = binding.executor(dict(payload or {}))
            if inspect.isawaitable(output):
                output = await output
            status = ExecutionStatus.PASS
            error = None
            if isinstance(output, Mapping) and output.get("ok") is False:
                status = ExecutionStatus.FAIL
                error = str(output.get("error") or output.get("message") or "TOOL_REPORTED_FAILURE")
        except Exception as exc:
            output = None
            status = ExecutionStatus.FAIL
            error = f"{type(exc).__name__}:{exc}"
        result = ExecutionResult(execution_id, descriptor.key, status, permission, attempts, started, time.time(), output=output, error=error)
        self._results[execution_id] = result
        return result

    def tools_execute(self, tool: ToolDescriptor | str, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> ExecutionResult:
        return _run_sync(self.tools_execute_async(tool, payload, **kwargs))

    def tools_result(self, execution_id: str) -> dict[str, Any]:
        if execution_id not in self._results:
            raise KeyError(f"UNKNOWN_EXECUTION={execution_id}")
        return self._results[execution_id].as_dict()

    async def tools_retry_async(self, tool: ToolDescriptor | str, payload: Mapping[str, Any] | None = None, *, max_attempts: int = 3, approved: bool = False, allow_destructive: bool = False) -> ExecutionResult:
        descriptor = self._descriptor(tool) if isinstance(tool, str) else tool
        max_attempts = max(1, int(max_attempts))
        last: ExecutionResult | None = None
        for attempt in range(1, max_attempts + 1):
            last = await self.tools_execute_async(descriptor, payload, approved=approved, allow_destructive=allow_destructive, attempts=attempt)
            if last.ok or last.status in {ExecutionStatus.BLOCKED, ExecutionStatus.APPROVAL_REQUIRED, ExecutionStatus.UNAVAILABLE} or not descriptor.retryable:
                return last
        assert last is not None
        return last

    def tools_retry(self, tool: ToolDescriptor | str, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> ExecutionResult:
        return _run_sync(self.tools_retry_async(tool, payload, **kwargs))

    def _descriptor(self, tool_key: str) -> ToolDescriptor:
        try:
            return self._bindings[tool_key].descriptor
        except KeyError as exc:
            raise KeyError(f"UNKNOWN_TOOL={tool_key}") from exc


def _run_sync(awaitable: Awaitable[Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("EVENT_LOOP_RUNNING_USE_ASYNC_API")