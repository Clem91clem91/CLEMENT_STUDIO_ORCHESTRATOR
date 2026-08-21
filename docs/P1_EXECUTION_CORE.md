# P1 — Execution Core

P1 adds the execution layer above the certified P0 foundation without rebuilding existing MCPs.

## P1-01 — Execution Fabric
Required surface: `tools_discover`, `tools_health`, `tools_capabilities`, `tools_select`, `tools_execute`, `tools_permissions`, `tools_result`, `tools_retry`.

The fabric ingests MCP Hub metadata and MCP `list_tools` contracts, selects tools deterministically by capability, and reuses CLEMENT MCP Hub, Windows Control, Files Plus, GitHub, Google Drive and Skills MCP.

## P1-02 — Agent Runtime
Required surface: `agent_spawn`, `agent_stop`, `agent_status`, `agent_assign`, `agent_message`, `agent_result`, `coalition_create`, `coalition_score`, `coalition_compare`, `coalition_promote`, `coalition_destroy`.

States: `CREATED → READY → RUNNING → WAITING/FAILED/COMPLETED → VERIFIED`. No hard agent-count ceiling; teams scale with mission complexity and requested parallelism.

## P1-03 — Resource Manager + Security Guard
Modes: `IDLE`, `AGENT`, `IMAGE`, `VIDEO`, `BLENDER`, `UNREAL`, `HYBRID`.
Risks: `SAFE`, `SENSITIVE`, `DESTRUCTIVE`.
Decisions: `ACTION_ALLOWED`, `ACTION_BLOCKED`, `ACTION_REQUIRES_APPROVAL`.

The resource manager consumes provider-neutral CPU/RAM/VRAM snapshots so existing Windows/GPU probes can feed it without coupling P1 to one sampler. Unknown actions fail closed as SENSITIVE; destructive actions are blocked by default.

## P1-04 — Observability
Every mission gets `TASK-YYYYMMDD-####` and produces `TASK_REPORT.json` + `TASK_REPORT.md`. Logs are split into tasks, agents, tools, mcp, models, gpu, errors, blender, comfyui and unreal. Technical and billable tokens stay separated.

## Certification gates
CI: Windows/Ubuntu, Python 3.11/3.13, compile, pytest, reference P1 E2E, PowerShell parsing, `governance-gate`.

Shadow real E2E: discover enabled Odysseus MCP servers, `list_tools`, capability-select real write/read/move/PowerShell/Drive tools, execute the requested flow, probe Skills MCP + GitHub auth, generate TASK evidence, and require clean worktree + unchanged HEAD.

Certification performs no merge, tag or release.
