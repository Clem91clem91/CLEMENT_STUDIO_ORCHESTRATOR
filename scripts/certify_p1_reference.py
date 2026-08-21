from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from clement_orchestrator.execution_core import ExecutionCore
from clement_orchestrator.execution_fabric import ExecutionFabric, RiskLevel, ToolDescriptor
from clement_orchestrator.resource_guard import ResourceMode, ResourceSnapshot

async def main() -> int:
    state: dict[str, str] = {}; fabric = ExecutionFabric()
    def write(p): state[p["path"]] = p["content"]; return {"ok": True, "path": p["path"]}
    def read(p): return {"ok": True, "content": state[p["path"]]}
    def move(p): state[p["destination"]] = state.pop(p["source"]); return {"ok": True, **p}
    def powershell(p): return {"ok": True, "stdout": "P1_POWERSHELL_PASS"}
    def drive(p): return {"ok": True, "file": {"id": "REFERENCE", "name": p["drive_name"]}}
    tools = [
        (ToolDescriptor("write_text_file","windows_control",("WRITE","TEXT","FILESYSTEM"),RiskLevel.SENSITIVE), write),
        (ToolDescriptor("read_text_file","windows_control",("READ","TEXT","FILESYSTEM"),RiskLevel.SAFE), read),
        (ToolDescriptor("files_move","files_plus",("WRITE","MOVE","FILESYSTEM"),RiskLevel.SENSITIVE), move),
        (ToolDescriptor("run_powershell","windows_control",("EXECUTE","POWERSHELL","POWERSHELL_RUN"),RiskLevel.SENSITIVE), powershell),
        (ToolDescriptor("drive_upload_file","google_drive",("WRITE","GOOGLE_DRIVE","DRIVE_UPLOAD"),RiskLevel.SENSITIVE), drive),
    ]
    for descriptor, executor in tools: fabric.register(descriptor, executor=executor)
    with tempfile.TemporaryDirectory() as tmp:
        core=ExecutionCore(log_root=Path(tmp)/"logs",fabric=fabric); mission=core.begin_mission("P1 reference execution","execution",skills=["agent-orchestration","filesystem","verification"],models=["reference"],required_agent_capabilities=["planning","execution","verification"],complexity=6,desired_agent_count=6,task_id="TASK-20260821-0001")
        coalition=core.create_coalition(mission,["execution","verification"]); core.agents.coalition_score(coalition,quality=1.0,capability_coverage=1.0,verification=1.0,efficiency=1.0); core.agents.coalition_promote(coalition)
        assert core.resource_plan(mission,ResourceSnapshot(20,30,10,5,()),current_mode=ResourceMode.IDLE,requested_mode=ResourceMode.AGENT)["action"] == "ALLOW"
        initial="probe.txt"; moved="probe-moved.txt"
        r=await core.execute_capability(mission,("WRITE","TEXT","FILESYSTEM"),{"path":initial,"content":"P1_REFERENCE_PASS"},preferred_servers=("windows_control",),approved=True); assert r.ok
        r=await core.execute_capability(mission,("READ","TEXT","FILESYSTEM"),{"path":initial},preferred_servers=("windows_control",)); assert r.ok and r.output["content"] == "P1_REFERENCE_PASS"
        r=await core.execute_capability(mission,("WRITE","MOVE","FILESYSTEM"),{"source":initial,"destination":moved},preferred_servers=("files_plus",),approved=True); assert r.ok
        r=await core.execute_capability(mission,("EXECUTE","POWERSHELL_RUN"),{"command":"Write-Output P1_POWERSHELL_PASS"},preferred_servers=("windows_control",),approved=True); assert r.ok
        r=await core.execute_capability(mission,("WRITE","GOOGLE_DRIVE","DRIVE_UPLOAD"),{"local_path":moved,"drive_name":"P1_REFERENCE_PASS.txt"},preferred_servers=("google_drive",),approved=True); assert r.ok
        core.add_token_usage(mission,technical=0,billable=0); jp,mp=core.finish_mission(mission,result="PASS",verification="PASS"); assert jp.exists() and mp.exists()
    print("P1_01_EXECUTION_FABRIC=PASS"); print("P1_02_AGENT_RUNTIME=PASS"); print("P1_03_RESOURCE_GUARD=PASS"); print("P1_04_OBSERVABILITY=PASS"); print("P1_REFERENCE_E2E=PASS"); print("MERGE_EXECUTED=NO"); print("TAG_CREATED=NO"); print("RELEASE_CREATED=NO"); return 0

if __name__ == "__main__": raise SystemExit(asyncio.run(main()))
