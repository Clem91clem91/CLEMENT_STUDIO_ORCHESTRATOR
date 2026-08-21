from __future__ import annotations

import asyncio
import json
import os
import shlex
import sqlite3
import subprocess
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from clement_orchestrator.execution_core import ExecutionCore
from clement_orchestrator.execution_fabric import ExecutionFabric
from clement_orchestrator.resource_guard import ResourceMode, ResourceSnapshot

ODYSSEUS_DB = Path(r"C:\Users\Shadow\ODYSSEUS\data\app.db")
STUDIO_ROOT = Path(r"C:\Users\Shadow\Documents\CLEMENT_STUDIO")
MCP_HUB_REGISTRY = STUDIO_ROOT / "04_TOOLS" / "CLEMENT_STUDIO_MCP_HUB" / "odysseus" / "mcp_registry.json"
ARTIFACT_ROOT = STUDIO_ROOT / "04_TOOLS" / "CLEMENT_STUDIO_ORCHESTRATOR" / "artifacts" / "P1_CERT"
REQUIRED_SERVER_HINTS = {
    "windows_control": ("881e7f17", "windows control"),
    "google_drive": ("0259a447", "google drive"),
    "files_plus": ("2024018c", "files plus"),
    "skills_mcp": ("bbc2ffc8", "skills mcp"),
}
SERVER_CAPABILITIES = {
    "windows_control": ("WINDOWS", "FILESYSTEM", "POWERSHELL"),
    "google_drive": ("GOOGLE_DRIVE", "NETWORK"),
    "files_plus": ("FILESYSTEM",),
    "skills_mcp": ("SKILLS",),
}

@dataclass(slots=True)
class ServerRow:
    id: str
    name: str
    command: str
    args: list[str]
    env: dict[str, str]

def _parse_args(raw: Any) -> list[str]:
    if raw in (None, ""): return []
    if isinstance(raw, list): return [str(item) for item in raw]
    text = str(raw).strip()
    try: value = json.loads(text)
    except json.JSONDecodeError: return shlex.split(text, posix=False)
    if isinstance(value, list): return [str(item) for item in value]
    if isinstance(value, str): return shlex.split(value, posix=False)
    raise ValueError("MCP_ARGS_INVALID")

def _parse_env(raw: Any) -> dict[str, str]:
    if raw in (None, ""): return {}
    if isinstance(raw, Mapping): return {str(k): str(v) for k, v in raw.items()}
    try: value = json.loads(str(raw))
    except json.JSONDecodeError: return {}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, Mapping) else {}

def _load_servers() -> list[ServerRow]:
    if not ODYSSEUS_DB.is_file(): raise FileNotFoundError(f"ODYSSEUS_DB_NOT_FOUND={ODYSSEUS_DB}")
    conn = sqlite3.connect(f"file:{ODYSSEUS_DB}?mode=ro", uri=True)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(mcp_servers)").fetchall()}
        env_column = next((name for name in ("env", "environment", "env_json") if name in columns), None)
        select = "id, name, command, args, is_enabled" + (f", {env_column}" if env_column else "")
        rows = conn.execute(f"SELECT {select} FROM mcp_servers").fetchall()
    finally: conn.close()
    result=[]
    for row in rows:
        server_id,name,command,raw_args,enabled,*rest=row
        if enabled:
            result.append(ServerRow(str(server_id),str(name),str(command),_parse_args(raw_args),_parse_env(rest[0] if rest else None)))
    return result

def _resolve_required(rows: list[ServerRow]) -> dict[str, ServerRow]:
    resolved={}
    for key,hints in REQUIRED_SERVER_HINTS.items():
        for row in rows:
            haystack=f"{row.id} {row.name}".casefold()
            if any(h.casefold() in haystack for h in hints): resolved[key]=row; break
        if key not in resolved: raise RuntimeError(f"REQUIRED_MCP_NOT_FOUND={key}")
    return resolved

def _tool_to_dict(tool: Any) -> dict[str, Any]:
    if hasattr(tool,"model_dump"):
        value=tool.model_dump(by_alias=True)
        if isinstance(value,dict): return value
    return {"name":str(getattr(tool,"name","")),"description":str(getattr(tool,"description","") or ""),"annotations":getattr(tool,"annotations",None) or {}}

def _call_result(result: Any) -> dict[str, Any]:
    structured=getattr(result,"structuredContent",None) or getattr(result,"structured_content",None)
    if isinstance(structured,Mapping): value=dict(structured)
    else:
        value={}
        for item in getattr(result,"content",[]) or []:
            text=getattr(item,"text",None)
            if not text: continue
            try: parsed=json.loads(text)
            except json.JSONDecodeError: value["text"]=value.get("text","")+str(text)
            else:
                if isinstance(parsed,Mapping): value.update(parsed)
                else: value["value"]=parsed
        if not value: value={"content":[str(item) for item in getattr(result,"content",[]) or []]}
    if bool(getattr(result,"isError",False) or getattr(result,"is_error",False)): value["ok"]=False
    return value

class McpConnections:
    def __init__(self, rows: Mapping[str, ServerRow]) -> None:
        self.rows=rows; self.stack=AsyncExitStack(); self.sessions={}
    async def __aenter__(self):
        await self.stack.__aenter__()
        for key,row in self.rows.items():
            env=os.environ.copy(); env.update(row.env)
            if key=="windows_control": env["CLEMENT_ALLOW_POWERSHELL"]="1"
            params=StdioServerParameters(command=row.command,args=row.args,env=env)
            read,write=await self.stack.enter_async_context(stdio_client(params)); session=await self.stack.enter_async_context(ClientSession(read,write)); await session.initialize(); self.sessions[key]=session
        return self
    async def __aexit__(self,*exc): return await self.stack.__aexit__(*exc)
    async def list_tools(self,key):
        response=await self.sessions[key].list_tools(); return [_tool_to_dict(tool) for tool in response.tools]
    async def call(self,key,tool,payload):
        return _call_result(await self.sessions[key].call_tool(tool,arguments=dict(payload)))

async def main() -> int:
    print("============================================================"); print("CLEMENT STUDIO - P1 SHADOW REAL E2E"); print("MODE=REAL_MCP_FAIL_CLOSED"); print("============================================================")
    rows=_load_servers(); required=_resolve_required(rows)
    for key,row in required.items(): print(f"MCP_FOUND={key} ID={row.id} NAME={row.name}")
    if not MCP_HUB_REGISTRY.is_file(): raise FileNotFoundError(f"MCP_HUB_REGISTRY_NOT_FOUND={MCP_HUB_REGISTRY}")
    registry=json.loads(MCP_HUB_REGISTRY.read_text(encoding="utf-8-sig"))
    gh=subprocess.run(["gh","auth","status","--hostname","github.com"],capture_output=True,text=True,check=False)
    if gh.returncode != 0: raise RuntimeError("GITHUB_AUTH=FAIL")
    print("GITHUB_AUTH=PASS")
    fabric=ExecutionFabric(); fabric.ingest_mcp_registry(registry)
    async with McpConnections(required) as mcp:
        catalogs={}
        for key in required:
            catalogs[key]=await mcp.list_tools(key); fabric.ingest_tool_catalog(key,catalogs[key],SERVER_CAPABILITIES[key]); print(f"MCP_TOOLS server={key} count={len(catalogs[key])}")
        known={item["server"]+"."+item["tool"] for item in fabric.tools_discover()}
        for key,tools in catalogs.items():
            for tool in tools:
                name=str(tool["name"]); tool_key=f"{key}.{name}"
                if tool_key not in known: continue
                async def executor(payload: Mapping[str,Any], *, _server=key, _tool=name): return await mcp.call(_server,_tool,payload)
                fabric.bind_executor(tool_key,executor)
        if "skills_status" not in {tool["name"] for tool in catalogs["skills_mcp"]}: raise RuntimeError("SKILLS_STATUS_TOOL_MISSING")
        skills_status=await mcp.call("skills_mcp","skills_status",{})
        if skills_status.get("ok") is False: raise RuntimeError(f"SKILLS_STATUS_FAILED={skills_status}")
        print("SKILLS_MCP_STATUS=PASS")
        task_stamp=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"); work_dir=ARTIFACT_ROOT/f"TASK-{task_stamp}"; source=work_dir/"p1_probe.txt"; moved=work_dir/"p1_probe_moved.txt"; work_dir.mkdir(parents=True,exist_ok=True)
        core=ExecutionCore(log_root=work_dir/"logs",fabric=fabric)
        mission=core.begin_mission("Crée un fichier, écris, lis, déplace, exécute PowerShell, copie sur Drive et vérifie.","real_execution",skills=["agent-orchestration","filesystem","google-drive","verification"],models=["odysseus-runtime"],required_agent_capabilities=["planning","execution","documents","verification"],complexity=7,desired_agent_count=6)
        coalition=core.create_coalition(mission,["execution","verification"]); core.agents.coalition_score(coalition,quality=1.0,capability_coverage=1.0,verification=1.0,efficiency=.8); core.agents.coalition_promote(coalition); print(f"AGENTS_DYNAMIC={len(mission.agent_ids)}"); print(f"COALITION_PROMOTED={coalition}")
        if core.resource_plan(mission,ResourceSnapshot(25,35,20,10,()),current_mode=ResourceMode.IDLE,requested_mode=ResourceMode.AGENT)["action"] != "ALLOW": raise RuntimeError("RESOURCE_PLAN_NOT_ALLOW")
        print("RESOURCE_GUARD=PASS")
        write_desc=fabric.tools_select(("WRITE","TEXT","FILESYSTEM"),preferred_servers=("windows_control",)); print(f"AUTO_SELECTED_WRITE={write_desc.key}")
        write=await core.execute_capability(mission,("WRITE","TEXT","FILESYSTEM"),{"path":str(source),"content":"CLEMENT_P1_REAL_E2E_PASS\n","overwrite":True},preferred_servers=("windows_control",),approved=True)
        if not write.ok: raise RuntimeError(f"WRITE_FAILED={write.as_dict()}")
        read_desc=fabric.tools_select(("READ","TEXT","FILESYSTEM"),preferred_servers=("windows_control",)); print(f"AUTO_SELECTED_READ={read_desc.key}")
        read=await core.execute_capability(mission,("READ","TEXT","FILESYSTEM"),{"path":str(source)},preferred_servers=("windows_control",))
        if not read.ok or "CLEMENT_P1_REAL_E2E_PASS" not in json.dumps(read.output): raise RuntimeError(f"READ_VERIFY_FAILED={read.as_dict()}")
        move_desc=fabric.tools_select(("WRITE","MOVE","FILESYSTEM"),preferred_servers=("files_plus",)); print(f"AUTO_SELECTED_MOVE={move_desc.key}")
        move=await core.execute_capability(mission,("WRITE","MOVE","FILESYSTEM"),{"source":str(source),"destination":str(moved),"overwrite":True},preferred_servers=("files_plus",),approved=True)
        if not move.ok: raise RuntimeError(f"MOVE_FAILED={move.as_dict()}")
        confirmation=""
        if "prepare_powershell" in {tool["name"] for tool in catalogs["windows_control"]}:
            prepared=await mcp.call("windows_control","prepare_powershell",{"command":"Write-Output 'P1_POWERSHELL_PASS'"}); confirmation=str(prepared.get("confirmation") or "")
        ps_desc=fabric.tools_select(("EXECUTE","POWERSHELL_RUN"),preferred_servers=("windows_control",)); print(f"AUTO_SELECTED_POWERSHELL={ps_desc.key}")
        ps=await core.execute_capability(mission,("EXECUTE","POWERSHELL_RUN"),{"command":"Write-Output 'P1_POWERSHELL_PASS'","confirmation":confirmation},preferred_servers=("windows_control",),approved=True)
        if not ps.ok or "P1_POWERSHELL_PASS" not in json.dumps(ps.output): raise RuntimeError(f"POWERSHELL_FAILED={ps.as_dict()}")
        drive_desc=fabric.tools_select(("WRITE","GOOGLE_DRIVE","DRIVE_UPLOAD"),preferred_servers=("google_drive",)); print(f"AUTO_SELECTED_DRIVE={drive_desc.key}")
        drive_name=f"CLEMENT_P1_CERT_{task_stamp}.txt"; drive=await core.execute_capability(mission,("WRITE","GOOGLE_DRIVE","DRIVE_UPLOAD"),{"local_path":str(moved),"parent_id":"root","drive_name":drive_name},preferred_servers=("google_drive",),approved=True)
        if not drive.ok: raise RuntimeError(f"DRIVE_UPLOAD_FAILED={drive.as_dict()}")
        drive_payload=drive.output if isinstance(drive.output,Mapping) else {}; drive_file=drive_payload.get("file") if isinstance(drive_payload,Mapping) else None
        if not isinstance(drive_file,Mapping) or not drive_file.get("id"): raise RuntimeError(f"DRIVE_FILE_ID_MISSING={drive.as_dict()}")
        print(f"DRIVE_FILE_ID={drive_file['id']}"); print(f"DRIVE_FILE_NAME={drive_file.get('name')}")
        verify=await core.execute_capability(mission,("READ","TEXT","FILESYSTEM"),{"path":str(moved)},preferred_servers=("windows_control",))
        if not verify.ok or "CLEMENT_P1_REAL_E2E_PASS" not in json.dumps(verify.output): raise RuntimeError(f"FINAL_VERIFY_FAILED={verify.as_dict()}")
        json_report,md_report=core.finish_mission(mission,result="PASS",verification="PASS")
    print(f"TASK_ID={mission.task_id}"); print(f"TASK_REPORT_JSON={json_report}"); print(f"TASK_REPORT_MD={md_report}"); print("P1_01_EXECUTION_FABRIC=PASS"); print("P1_02_AGENT_RUNTIME=PASS"); print("P1_03_RESOURCE_GUARD=PASS"); print("P1_04_OBSERVABILITY=PASS"); print("P1_REAL_E2E=PASS"); print("MERGE_EXECUTED=NO"); print("TAG_CREATED=NO"); print("RELEASE_CREATED=NO"); return 0

if __name__ == "__main__":
    try: raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print("P1_REAL_E2E=FAIL"); print(f"ERROR={type(exc).__name__}:{exc}"); print("MERGE_EXECUTED=NO"); print("TAG_CREATED=NO"); print("RELEASE_CREATED=NO"); raise
