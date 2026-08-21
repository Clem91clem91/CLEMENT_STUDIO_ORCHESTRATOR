import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from clement_orchestrator.agent_runtime import AgentRuntime, AgentState
from clement_orchestrator.execution_core import ExecutionCore
from clement_orchestrator.execution_fabric import ExecutionFabric, ExecutionStatus, PermissionDecision, RiskLevel, ToolDescriptor
from clement_orchestrator.observability import TaskObserver
from clement_orchestrator.resource_guard import ActionDecision, ActionRisk, ResourceAction, ResourceManager, ResourceMode, ResourceSnapshot, SecurityGuard

ROOT = Path(__file__).resolve().parents[1]

def test_p1_01_required_surface_and_shape():
    fabric = ExecutionFabric(); fabric.register(ToolDescriptor("run_powershell", "windows-control", ("powershell", "windows", "execute"), RiskLevel.SENSITIVE, True), executor=lambda p: {"ok": True})
    item = fabric.tools_discover()[0]
    assert item["tool"] == "run_powershell" and item["server"] == "windows-control" and item["risk"] == "SENSITIVE" and item["available"] is True
    for name in ("tools_discover", "tools_health", "tools_capabilities", "tools_select", "tools_execute", "tools_permissions", "tools_result", "tools_retry"): assert hasattr(fabric, name)

def test_p1_01_selection_permissions_execute_retry():
    fabric = ExecutionFabric(); fabric.register(ToolDescriptor("files_read_text", "files-plus", ("read", "filesystem"), RiskLevel.SAFE)); fabric.register(ToolDescriptor("read_text_file", "windows-control", ("read", "filesystem"), RiskLevel.SAFE), executor=lambda p: {"ok": True, "content": "hello"})
    selected = fabric.tools_select(("read", "filesystem"), preferred_servers=("windows-control",)); assert selected.key == "windows-control.read_text_file"
    result = fabric.tools_execute(selected.key, {"path": "x"}); assert result.status is ExecutionStatus.PASS and fabric.tools_result(result.execution_id)["status"] == "PASS"
    sensitive = ToolDescriptor("write_text_file", "windows-control", ("write",), RiskLevel.SENSITIVE); destructive = ToolDescriptor("delete_path", "windows-control", ("delete",), RiskLevel.DESTRUCTIVE)
    assert fabric.tools_permissions(sensitive) is PermissionDecision.ACTION_REQUIRES_APPROVAL; assert fabric.tools_permissions(destructive) is PermissionDecision.ACTION_BLOCKED
    calls = {"count": 0}
    def flaky(payload):
        calls["count"] += 1; return {"ok": calls["count"] >= 2, "error": "TRANSIENT"}
    d = ToolDescriptor("unstable", "server", ("x",), RiskLevel.SAFE, retryable=True); fabric.register(d, executor=flaky); r = fabric.tools_retry(d.key, {}, max_attempts=3); assert r.ok and r.attempts == 2

def test_p1_01_async_and_registry_reuse():
    async def executor(payload): return {"ok": True, "value": payload["x"]}
    fabric = ExecutionFabric(); d = ToolDescriptor("async_tool", "mcp", ("async",), RiskLevel.SAFE); fabric.register(d, executor=executor); assert asyncio.run(fabric.tools_execute_async(d.key, {"x": 5})).ok
    descriptors = fabric.ingest_mcp_registry({"components": [{"key":"google_drive","id":"0259a447","capabilities":["READ","WRITE","GOOGLE_DRIVE"],"current_odysseus_enabled":True},{"key":"windows_control","id":"881e7f17","capabilities":["READ","WRITE","EXECUTE","FILESYSTEM","POWERSHELL"],"current_odysseus_enabled":True}]}); assert {x.server for x in descriptors} == {"google_drive", "windows_control"}

def test_p1_02_surface_state_dynamic_count_and_arena():
    runtime = AgentRuntime()
    for name in ("agent_spawn","agent_stop","agent_status","agent_assign","agent_message","agent_result","coalition_create","coalition_score","coalition_compare","coalition_promote","coalition_destroy"): assert hasattr(runtime, name)
    agent = runtime.agent_spawn("code", ready=False); assert agent.state is AgentState.CREATED; runtime.agent_message(agent.agent_id, {"text":"ready"}); runtime.agent_assign(agent.agent_id, {"task":"build"}); runtime.agent_result(agent.agent_id, {"ok":True}); runtime.agent_result(agent.agent_id, verified=True); assert runtime.agent_status(agent.agent_id)["state"] == "VERIFIED"
    runtime2 = AgentRuntime(); team = runtime2.adaptive_team(("code","blender","unreal","verification"), complexity=10, desired_size=12); assert len(team) == 12 and len({x.agent_id for x in team}) == 12
    a = runtime2.coalition_create([x.agent_id for x in team[:6]], ("code",)); b = runtime2.coalition_create([x.agent_id for x in team[6:]], ("verification",)); runtime2.coalition_score(a.coalition_id, quality=.8, capability_coverage=.8, verification=.7, efficiency=.9); runtime2.coalition_score(b.coalition_id, quality=.9, capability_coverage=.9, verification=.95, efficiency=.7); assert runtime2.coalition_compare([a.coalition_id,b.coalition_id])[0]["coalition_id"] == b.coalition_id; runtime2.coalition_promote(b.coalition_id); assert runtime2.promoted_coalition_id == b.coalition_id
    with pytest.raises(RuntimeError): runtime2.coalition_destroy(b.coalition_id)

def test_p1_03_resource_and_security_contract():
    assert {x.value for x in ResourceMode} == {"IDLE","AGENT","IMAGE","VIDEO","BLENDER","UNREAL","HYBRID"}
    manager = ResourceManager(); assert manager.evaluate(ResourceSnapshot(40,50,90,95,("comfyui",)), current_mode=ResourceMode.VIDEO, requested_mode=ResourceMode.BLENDER).action is ResourceAction.WAIT; assert manager.evaluate(ResourceSnapshot(40,50,93,99,("comfyui",)), current_mode=ResourceMode.VIDEO, requested_mode=ResourceMode.BLENDER, current_priority=30, requested_priority=90).action is ResourceAction.RELEASE_CURRENT; assert manager.evaluate(ResourceSnapshot(30,40,85,80,("unreal",)), current_mode=ResourceMode.UNREAL, requested_mode=ResourceMode.BLENDER).action is ResourceAction.HYBRID
    guard = SecurityGuard(); assert guard.classify("read_text_file") is ActionRisk.SAFE; assert guard.classify("write_text_file") is ActionRisk.SENSITIVE; assert guard.classify("delete folder") is ActionRisk.DESTRUCTIVE; assert guard.classify("git push --force origin develop") is ActionRisk.DESTRUCTIVE; assert guard.decide("read_text_file").decision is ActionDecision.ACTION_ALLOWED; assert guard.decide("write_text_file").decision is ActionDecision.ACTION_REQUIRES_APPROVAL; assert guard.decide("delete folder").decision is ActionDecision.ACTION_BLOCKED; assert guard.decide("new_unclassified_operation").risk is ActionRisk.SENSITIVE

def test_p1_04_reports_tree_and_sequence(tmp_path):
    observer = TaskObserver(tmp_path / "logs"); now = datetime(2026,8,21,tzinfo=timezone.utc); first = observer.start_task("a","x",now=now); second = observer.start_task("b","x",now=now); assert first.task_id == "TASK-20260821-0001" and second.task_id == "TASK-20260821-0002"
    observer.add_skills(first.task_id,["agent-orchestration"]); observer.add_agents(first.task_id,["AGENT-1"]); observer.add_models(first.task_id,["auto/best-coding"]); observer.add_mcp(first.task_id,["windows_control"]); observer.add_tool_call(first.task_id,{"tool":"read","status":"PASS"}); observer.add_gpu(first.task_id,{"mode":"AGENT","vram_percent":20}); observer.add_tokens(first.task_id,technical=100,billable=40); observer.add_retry(first.task_id,"transient"); jp, mp = observer.finish(first.task_id,result="PASS",verification="PASS"); payload=json.loads(jp.read_text()); assert payload["result"] == "PASS" and payload["tokens"]["technical_tokens"] == 100 and "RESULT=PASS" in mp.read_text()
    for name in ("tasks","agents","tools","mcp","models","gpu","errors","blender","comfyui","unreal"): assert (observer.log_root/name).is_dir()

def test_p1_global_core(tmp_path):
    fabric=ExecutionFabric(); state={}; fabric.register(ToolDescriptor("write_text_file","windows_control",("WRITE","FILESYSTEM"),RiskLevel.SENSITIVE),executor=lambda p: state.update(content=p["content"]) or {"ok":True,"path":p["path"]}); core=ExecutionCore(log_root=tmp_path/"logs",fabric=fabric); mission=core.begin_mission("Create file","execution",skills=["agent-orchestration"],models=["auto/best-coding"],required_agent_capabilities=["planning","execution","verification"],complexity=4,desired_agent_count=4,task_id="TASK-20260821-0001"); assert len(mission.agent_ids)==4; core.create_coalition(mission,["execution","verification"]); assert core.resource_plan(mission,ResourceSnapshot(20,30,10,5,()),current_mode=ResourceMode.IDLE,requested_mode=ResourceMode.AGENT)["action"]=="ALLOW"; r=asyncio.run(core.execute_capability(mission,["WRITE","FILESYSTEM"],{"path":"probe.txt","content":"P1"},preferred_servers=["windows_control"],approved=True)); assert r.ok and state["content"]=="P1"; core.add_token_usage(mission,technical=55,billable=0); jp,mp=core.finish_mission(mission,result="PASS",verification="PASS"); assert jp.exists() and "RESULT=PASS" in mp.read_text()

def test_p1_certification_contracts():
    shadow=(ROOT/"scripts"/"certify_p1_shadow.py").read_text(encoding="utf-8"); wrapper=(ROOT/"scripts"/"certify_p1_shadow.ps1").read_text(encoding="utf-8"); ref=(ROOT/"scripts"/"certify_p1_reference.py").read_text(encoding="utf-8")
    assert "DRIVE_UPLOAD" in shadow and "delete_path_permanently" not in shadow and "trash_path" not in shadow and "git push --force" not in shadow
    for marker in ('print("MERGE_EXECUTED=NO")','print("TAG_CREATED=NO")','print("RELEASE_CREATED=NO")'): assert marker in shadow
    assert "feat/p1-execution-core" in wrapper and "P1_WORKTREE_NOT_CLEAN" in wrapper and "P1_HEAD_CHANGED_DURING_CERT" in wrapper and "P1_GLOBAL=PASS" in wrapper
    for marker in ("P1_01_EXECUTION_FABRIC=PASS","P1_02_AGENT_RUNTIME=PASS","P1_03_RESOURCE_GUARD=PASS","P1_04_OBSERVABILITY=PASS","P1_REFERENCE_E2E=PASS"): assert marker in ref
