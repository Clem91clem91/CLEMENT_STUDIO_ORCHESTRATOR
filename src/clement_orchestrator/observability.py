from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

TASK_PATTERN = re.compile(r"^TASK-(\d{8})-(\d{4})$")

@dataclass(slots=True)
class TokenUsage:
    technical_tokens: int = 0
    billable_tokens: int = 0
    def add(self, *, technical: int = 0, billable: int = 0) -> None:
        technical, billable = int(technical), int(billable)
        if technical < 0 or billable < 0:
            raise ValueError("TOKEN_USAGE_NEGATIVE")
        self.technical_tokens += technical
        self.billable_tokens += billable

@dataclass(slots=True)
class TaskTrace:
    task_id: str
    prompt: str
    intent: str
    created_at: str
    skills: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    coalitions: list[dict[str, Any]] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    mcp: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    gpu: list[dict[str, Any]] = field(default_factory=list)
    tokens: TokenUsage = field(default_factory=TokenUsage)
    errors: list[str] = field(default_factory=list)
    retries: int = 0
    verification: str = "PENDING"
    result: str = "RUNNING"
    completed_at: str | None = None
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

class TaskObserver:
    CATEGORIES = ("tasks", "agents", "tools", "mcp", "models", "gpu", "errors", "blender", "comfyui", "unreal")
    def __init__(self, log_root: str | Path) -> None:
        self.log_root = Path(log_root)
        for category in self.CATEGORIES:
            (self.log_root / category).mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, TaskTrace] = {}

    def next_task_id(self, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        date = now.strftime("%Y%m%d")
        prefix = f"TASK-{date}-"
        highest = 0
        for child in (self.log_root / "tasks").iterdir():
            if child.is_dir() and child.name.startswith(prefix):
                match = TASK_PATTERN.match(child.name)
                if match:
                    highest = max(highest, int(match.group(2)))
        for task_id in self._tasks:
            if task_id.startswith(prefix):
                match = TASK_PATTERN.match(task_id)
                if match:
                    highest = max(highest, int(match.group(2)))
        return f"TASK-{date}-{highest + 1:04d}"

    def start_task(self, prompt: str, intent: str, *, task_id: str | None = None, now: datetime | None = None) -> TaskTrace:
        task_id = task_id or self.next_task_id(now=now)
        if not TASK_PATTERN.match(task_id):
            raise ValueError(f"TASK_ID_INVALID={task_id}")
        if task_id in self._tasks:
            raise ValueError(f"TASK_ALREADY_ACTIVE={task_id}")
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        trace = TaskTrace(task_id, prompt, intent, timestamp)
        self._tasks[task_id] = trace
        self._emit("tasks", task_id, {"event": "TASK_STARTED", "intent": intent})
        self.flush(task_id)
        return trace

    def add_skills(self, task_id: str, skills: Iterable[str]) -> None:
        trace = self._trace(task_id); trace.skills = list(dict.fromkeys([*trace.skills, *map(str, skills)])); self._emit("tasks", task_id, {"event": "SKILLS", "skills": trace.skills})
    def add_agents(self, task_id: str, agents: Iterable[str]) -> None:
        trace = self._trace(task_id); trace.agents = list(dict.fromkeys([*trace.agents, *map(str, agents)])); self._emit("agents", task_id, {"event": "AGENTS", "agents": trace.agents})
    def add_coalition(self, task_id: str, coalition: Mapping[str, Any]) -> None:
        trace = self._trace(task_id); value = dict(coalition); trace.coalitions.append(value); self._emit("agents", task_id, {"event": "COALITION", "coalition": value})
    def add_models(self, task_id: str, models: Iterable[str]) -> None:
        trace = self._trace(task_id); trace.models = list(dict.fromkeys([*trace.models, *map(str, models)])); self._emit("models", task_id, {"event": "MODELS", "models": trace.models})
    def add_mcp(self, task_id: str, servers: Iterable[str]) -> None:
        trace = self._trace(task_id); trace.mcp = list(dict.fromkeys([*trace.mcp, *map(str, servers)])); self._emit("mcp", task_id, {"event": "MCP", "servers": trace.mcp})
    def add_tool_call(self, task_id: str, call: Mapping[str, Any]) -> None:
        trace = self._trace(task_id); value = dict(call); trace.tool_calls.append(value); self._emit("tools", task_id, {"event": "TOOL_CALL", "call": value})
    def add_gpu(self, task_id: str, snapshot: Mapping[str, Any]) -> None:
        trace = self._trace(task_id); value = dict(snapshot); trace.gpu.append(value); self._emit("gpu", task_id, {"event": "GPU", "snapshot": value})
    def add_tokens(self, task_id: str, *, technical: int, billable: int) -> None:
        trace = self._trace(task_id); trace.tokens.add(technical=technical, billable=billable); self._emit("models", task_id, {"event": "TOKENS", "technical": technical, "billable": billable, "technical_total": trace.tokens.technical_tokens, "billable_total": trace.tokens.billable_tokens})
    def add_error(self, task_id: str, error: str) -> None:
        trace = self._trace(task_id); trace.errors.append(str(error)); self._emit("errors", task_id, {"event": "ERROR", "error": str(error)})
    def add_retry(self, task_id: str, reason: str = "") -> None:
        trace = self._trace(task_id); trace.retries += 1; self._emit("tasks", task_id, {"event": "RETRY", "retry": trace.retries, "reason": reason})

    def finish(self, task_id: str, *, result: str, verification: str, now: datetime | None = None) -> tuple[Path, Path]:
        trace = self._trace(task_id); trace.result = result; trace.verification = verification; trace.completed_at = (now or datetime.now(timezone.utc)).isoformat(); self._emit("tasks", task_id, {"event": "TASK_FINISHED", "result": result, "verification": verification}); return self.flush(task_id)

    def flush(self, task_id: str) -> tuple[Path, Path]:
        trace = self._trace(task_id); task_dir = self.log_root / "tasks" / task_id; task_dir.mkdir(parents=True, exist_ok=True); json_path = task_dir / "TASK_REPORT.json"; md_path = task_dir / "TASK_REPORT.md"; _atomic_write(json_path, json.dumps(trace.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"); _atomic_write(md_path, self._markdown(trace)); return json_path, md_path

    def _trace(self, task_id: str) -> TaskTrace:
        try: return self._tasks[task_id]
        except KeyError as exc: raise KeyError(f"UNKNOWN_TASK={task_id}") from exc

    def _emit(self, category: str, task_id: str, payload: Mapping[str, Any]) -> None:
        if category not in self.CATEGORIES: raise ValueError(f"UNKNOWN_LOG_CATEGORY={category}")
        path = self.log_root / category / "events.jsonl"; event = {"task_id": task_id, "timestamp": datetime.now(timezone.utc).isoformat(), **dict(payload)}
        with path.open("a", encoding="utf-8", newline="\n") as handle: handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    @staticmethod
    def _markdown(trace: TaskTrace) -> str:
        def csv(values: Iterable[str]) -> str:
            values = list(values); return ", ".join(values) if values else "NONE"
        return "\n".join([f"# {trace.task_id}", "", f"- RESULT={trace.result}", f"- VERIFICATION={trace.verification}", f"- INTENT={trace.intent}", f"- SKILLS_USED={csv(trace.skills)}", f"- AGENTS_USED={csv(trace.agents)}", f"- MODELS_USED={csv(trace.models)}", f"- MCP_USED={csv(trace.mcp)}", f"- TECHNICAL_TOKENS={trace.tokens.technical_tokens}", f"- BILLABLE_TOKENS={trace.tokens.billable_tokens}", f"- RETRIES={trace.retries}", f"- ERRORS={len(trace.errors)}", "", "## Prompt", "", trace.prompt, ""])

def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle: handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)