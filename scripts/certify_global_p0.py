from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp import Client

from clement_orchestrator.core import AgentProfile, Mentality, TaskContext, verify_result
from clement_orchestrator.global_e2e import (
    EXPECTED_SKILLS_MCP_TOOLS,
    RouteEvidence,
    evidence_verdict,
    extract_route_evidence,
    strategy_marker,
)
from clement_orchestrator.pipeline import MCPToolRef, ModelCandidate, build_plan
from clement_orchestrator.reasoning import infer_mentalities
from clement_orchestrator.skills_mcp import skill_matches_from_search


EXPECTED_HEADS = {
    "P0-01": "583f1490063872d06c2866c5e08754c1e05cb77a",
    "P0-02": "6ecd68bc230ca3e65ddfd661897dd5a3160fe4df",
    "P0-03": "2b9ca8485d2322378e952d88400ba30767e4b187",
}

P0_02_SERVER_ID = "bbc2ffc8-cb1d-4712-a11a-1f4c0fdd8edf"
DEFAULT_MODEL_ALIAS = "auto/best-coding"
DEFAULT_OMNIROUTE = "http://127.0.0.1:20128"
DEFAULT_ODYSSEUS_HEALTH = "http://127.0.0.1:7000/api/health"

OBJECTIVE = (
    "Certify the CLEMENT P0 orchestration pipeline: plan and orchestrate a complex mission, "
    "select real skills, build an agent coalition, execute A/B/C/D strategies through OmniRoute, "
    "and verify the result with explicit evidence."
)


class GlobalCertificationError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise GlobalCertificationError(
            f"GIT_FAILED repo={repo} args={args!r} stderr={completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _git_head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _git_branch(repo: Path) -> str:
    return _git(repo, "branch", "--show-current")


def _git_clean(repo: Path) -> bool:
    return not bool(_git(repo, "status", "--porcelain"))


def _require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise GlobalCertificationError(f"{label}_NOT_FOUND={path}")


def _structured(result: Any, label: str) -> dict[str, Any]:
    if bool(getattr(result, "is_error", False)):
        raise GlobalCertificationError(f"MCP_TOOL_ERROR={label}")
    payload = getattr(result, "structured_content", None)
    if isinstance(payload, dict):
        return payload
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    return decoded
    raise GlobalCertificationError(f"MCP_STRUCTURED_CONTENT_MISSING={label}")


async def _probe_skills_mcp(hub_root: Path, mcp_repo: Path) -> dict[str, Any]:
    mcp_src = str((mcp_repo / "src").resolve())
    if mcp_src not in sys.path:
        sys.path.insert(0, mcp_src)

    from clement_skills_mcp.catalog import SkillsCatalog
    from clement_skills_mcp.server import build_server

    catalog = SkillsCatalog(hub_root=hub_root)

    async with Client(build_server(catalog)) as client:
        tools_result = await client.list_tools()
        tool_names = sorted(tool.name for tool in tools_result.tools)

        status = _structured(await client.call_tool("skills_status", {}), "skills_status")
        search = _structured(
            await client.call_tool(
                "skills_search",
                {"query": "agent orchestration", "limit": 5},
            ),
            "skills_search",
        )

        matches = search.get("matches")
        if not isinstance(matches, list) or not matches:
            raise GlobalCertificationError("P0_02_SEARCH_NO_MATCHES")
        first = matches[0]
        if not isinstance(first, dict) or not isinstance(first.get("skill"), dict):
            raise GlobalCertificationError("P0_02_SEARCH_BEST_MATCH_INVALID")
        best_skill = first["skill"]
        best_id = str(best_skill.get("id") or "").strip()
        if not best_id:
            raise GlobalCertificationError("P0_02_BEST_SKILL_ID_MISSING")

        get_payload = _structured(
            await client.call_tool(
                "skills_get",
                {"reference": best_id, "include_content": True},
            ),
            "skills_get",
        )
        dependencies = _structured(
            await client.call_tool("skills_dependencies", {"reference": best_id}),
            "skills_dependencies",
        )
        conflicts = _structured(
            await client.call_tool("skills_conflicts", {"reference": best_id}),
            "skills_conflicts",
        )
        validation = _structured(
            await client.call_tool(
                "skills_validate",
                {"reference": best_id, "check_content": True},
            ),
            "skills_validate",
        )

    return {
        "transport": "MCP_SDK_IN_PROCESS_SERVER",
        "server_id": P0_02_SERVER_ID,
        "tool_names": tool_names,
        "tool_count": len(tool_names),
        "status": status,
        "search": search,
        "best_skill": best_skill,
        "best_skill_score": first.get("score"),
        "get": get_payload,
        "dependencies": dependencies,
        "conflicts": conflicts,
        "validation": validation,
    }


def _probe_json_get(url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise GlobalCertificationError(f"HTTP_GET_FAILED={url}: {exc}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise GlobalCertificationError(f"HTTP_GET_INVALID_JSON={url}") from exc
    if not isinstance(payload, dict):
        raise GlobalCertificationError(f"HTTP_GET_NOT_OBJECT={url}")
    return payload


def _post_strategy(
    *,
    base_url: str,
    model_alias: str,
    strategy_name: str,
    strategy_description: str,
    objective: str,
    best_skill_id: str,
    best_skill_content: str,
    coalition_agents: list[str],
    timeout: float = 180.0,
) -> RouteEvidence:
    marker = strategy_marker(strategy_name)
    skill_excerpt = best_skill_content[:1600]
    prompt = (
        f"CLEMENT GLOBAL P0 CERTIFICATION\n"
        f"Mission: {objective}\n"
        f"Strategy {strategy_name}: {strategy_description}\n"
        f"Selected real skill: {best_skill_id}\n"
        f"Coalition: {', '.join(coalition_agents)}\n"
        f"Skill excerpt:\n{skill_excerpt}\n\n"
        f"This is a deterministic execution probe. Return exactly: {marker}"
    )
    body = json.dumps(
        {
            "model": model_alias,
            "stream": False,
            "temperature": 0,
            "max_tokens": 192,
            "messages": [{"role": "user", "content": prompt}],
        },
        ensure_ascii=False,
    ).encode("utf-8")

    client_request_id = f"CLEMENT-GLOBAL-{strategy_name}-{uuid.uuid4()}"
    request = Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Request-Id": client_request_id,
            "X-OmniRoute-No-Cache": "true",
        },
        method="POST",
    )

    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            response_headers = dict(response.headers.items())
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        raise GlobalCertificationError(
            f"OMNIROUTE_HTTP_ERROR strategy={strategy_name} status={exc.code} body={error_body[:500]}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise GlobalCertificationError(
            f"OMNIROUTE_REQUEST_FAILED strategy={strategy_name}: {exc}"
        ) from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GlobalCertificationError(
            f"OMNIROUTE_INVALID_JSON strategy={strategy_name} body={raw[:500]}"
        ) from exc
    if not isinstance(payload, dict):
        raise GlobalCertificationError(f"OMNIROUTE_BODY_NOT_OBJECT strategy={strategy_name}")

    evidence = extract_route_evidence(
        strategy=strategy_name,
        requested_alias=model_alias,
        http_status=status,
        headers=response_headers,
        payload=payload,
    )

    # Keep wall-clock evidence if a provider does not expose its own latency header.
    if evidence.latency_ms is None:
        evidence = RouteEvidence(
            **{
                **evidence.as_dict(),
                "latency_ms": elapsed_ms,
            }
        )
    return evidence


def _markdown(report: Mapping[str, Any]) -> str:
    plan = report["p0_04_plan"]
    lines = [
        "# CLEMENT STUDIO - Global P0 Certification",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Global result: **{report['global_result']}**",
        "",
        "## P0 gates",
        "",
        f"- P0-01: **{report['p0_01']['result']}** - {report['p0_01']['total_entries']} skills, state `{report['p0_01']['state']}`",
        f"- P0-02: **{report['p0_02']['result']}** - {report['p0_02']['tool_count']} MCP tools, search total {report['p0_02']['search_total']}",
        f"- P0-03: **{report['p0_03']['result']}** - live provider accounting resolved for all strategies",
        f"- P0-04: **{report['p0_04']['result']}** - coalition `{plan['coalition_complete']}`, arena {','.join(plan['arena'])}",
        "",
        "## Plan",
        "",
        f"- Task: `{plan['task_id']}`",
        f"- Best skill: `{report['p0_02']['best_skill_id']}`",
        f"- Coalition: {', '.join(plan['coalition_agents'])}",
        f"- Model alias: `{plan['selected_model']}`",
        f"- Winning arena strategy: `{plan['arena'][0] if plan['arena'] else '-'}`",
        "",
        "## Live strategy executions",
        "",
        "| Strategy | Provider | Final model | HTTP | Cache | Technical tokens | Billable tokens | Cost EUR | Accounting |",
        "|---|---|---|---:|---|---:|---:|---:|---|",
    ]
    for item in report["p0_03"]["executions"]:
        lines.append(
            f"| {item['strategy']} | {item['final_provider']} | {item['final_model']} | "
            f"{item['http_status']} | {item['cache_status']} | {item['technical_tokens']} | "
            f"{item['billable_tokens']} | {item['cost_eur']} | {item['billing_mode']} |"
        )
    if report.get("reasons"):
        lines.extend(["", "## Reasons", ""])
        lines.extend(f"- {reason}" for reason in report["reasons"])
    return "\n".join(lines) + "\n"


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    tools_root = repo.parent

    hub_root = Path(os.environ.get("CLEMENT_P0_01_ROOT", tools_root / "CLEMENT_STUDIO_SKILLS_HUB")).resolve()
    mcp_repo = Path(os.environ.get("CLEMENT_P0_02_ROOT", tools_root / "CLEMENT_STUDIO_SKILLS_MCP")).resolve()
    omniroute_repo = Path(os.environ.get("CLEMENT_P0_03_ROOT", tools_root / "CLEMENT_STUDIO_OMNIROUTE")).resolve()
    omniroute_url = os.environ.get("CLEMENT_OMNIROUTE_URL", DEFAULT_OMNIROUTE).rstrip("/")
    odysseus_health_url = os.environ.get("CLEMENT_ODYSSEUS_HEALTH_URL", DEFAULT_ODYSSEUS_HEALTH)
    model_alias = os.environ.get("CLEMENT_GLOBAL_MODEL_ALIAS", DEFAULT_MODEL_ALIAS)

    artifact_dir = repo / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    json_report = artifact_dir / "GLOBAL_P0_CERTIFICATION.json"
    md_report = artifact_dir / "GLOBAL_P0_CERTIFICATION.md"

    print("============================================================")
    print("CLEMENT STUDIO - GLOBAL P0 CERTIFICATION")
    print("MODE=REAL_E2E_FAIL_CLOSED")
    print("============================================================")

    try:
        for path, label in (
            (hub_root, "P0_01_ROOT"),
            (mcp_repo, "P0_02_ROOT"),
            (omniroute_repo, "P0_03_ROOT"),
            (repo, "P0_04_ROOT"),
        ):
            _require_path(path, label)

        heads = {
            "P0-01": _git_head(hub_root),
            "P0-02": _git_head(mcp_repo),
            "P0-03": _git_head(omniroute_repo),
            "P0-04": _git_head(repo),
        }
        branches = {
            "P0-01": _git_branch(hub_root),
            "P0-02": _git_branch(mcp_repo),
            "P0-03": _git_branch(omniroute_repo),
            "P0-04": _git_branch(repo),
        }
        clean = {
            "P0-01": _git_clean(hub_root),
            "P0-02": _git_clean(mcp_repo),
            "P0-03": _git_clean(omniroute_repo),
            "P0-04": _git_clean(repo),
        }

        for name, expected in EXPECTED_HEADS.items():
            if heads[name] != expected:
                raise GlobalCertificationError(
                    f"{name}_HEAD_MISMATCH expected={expected} actual={heads[name]}"
                )
        if branches["P0-04"] != "feat/p0-dynamic-orchestrator":
            raise GlobalCertificationError(f"P0_04_WRONG_BRANCH={branches['P0-04']}")
        if not all(clean.values()):
            dirty = [name for name, value in clean.items() if not value]
            raise GlobalCertificationError(f"DIRTY_WORKTREES={','.join(dirty)}")

        registry_path = hub_root / "registry" / "skills_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        total_entries = int(registry.get("stats", {}).get("total_entries", -1))
        registry_state = str(registry.get("state") or "")
        p0_01_pass = total_entries == 905 and registry_state == "IMPORTED"

        odysseus_health = _probe_json_get(odysseus_health_url)
        odysseus_ok = str(odysseus_health.get("status") or "").lower() == "healthy"

        mcp_evidence = asyncio.run(_probe_skills_mcp(hub_root, mcp_repo))
        tool_names = set(mcp_evidence["tool_names"])
        mcp_status = mcp_evidence["status"]
        search_payload = mcp_evidence["search"]
        best_skill = mcp_evidence["best_skill"]
        best_skill_id = str(best_skill.get("id") or "")
        best_skill_content = str(mcp_evidence["get"].get("content") or "")
        search_total = int(search_payload.get("total", 0) or 0)
        validation = mcp_evidence["validation"]
        dependencies = mcp_evidence["dependencies"]
        conflicts = mcp_evidence["conflicts"]

        p0_02_pass = (
            tool_names == EXPECTED_SKILLS_MCP_TOOLS
            and bool(mcp_status.get("ok"))
            and mcp_status.get("mode") == "READ_ONLY"
            and mcp_status.get("writes_supported") is False
            and int(mcp_status.get("stats", {}).get("total_entries", -1)) == 905
            and search_total > 0
            and bool(best_skill_content.strip())
            and validation.get("valid") is True
            and isinstance(dependencies.get("resolved_dependencies"), list)
            and isinstance(conflicts.get("resolved_conflicts"), list)
        )

        skill_matches = skill_matches_from_search(search_payload)
        if not skill_matches:
            raise GlobalCertificationError("P0_04_SKILL_ADAPTER_RETURNED_ZERO_MATCHES")

        mentalities = infer_mentalities(OBJECTIVE, minimum=3)
        task = TaskContext(
            objective=OBJECTIVE,
            required_skills=frozenset({"planning", "orchestration", "verification"}),
            preferred_models=frozenset({model_alias}),
            required_mentalities=mentalities,
            available_vram_gb=20.0,
            risk_tolerance=0.4,
        )
        agents = [
            AgentProfile(
                "planner",
                frozenset({"planning"}),
                mentalities=frozenset({Mentality.PLANNING, Mentality.ANALYTICAL}),
                quality=0.90,
                reliability=0.90,
                risk=0.15,
                historical_score=0.80,
            ),
            AgentProfile(
                "general",
                frozenset({"orchestration"}),
                mentalities=frozenset({Mentality.ENGINEERING, Mentality.ANALYTICAL}),
                quality=0.90,
                reliability=0.90,
                risk=0.15,
                historical_score=0.80,
            ),
            AgentProfile(
                "verifier",
                frozenset({"verification"}),
                mentalities=frozenset({Mentality.VERIFICATION, Mentality.SKEPTICAL}),
                quality=0.95,
                reliability=0.95,
                risk=0.10,
                historical_score=0.90,
            ),
        ]
        models = [
            ModelCandidate(
                name=model_alias,
                provider_kind="PROXY",
                quality=0.90,
                reliability=0.90,
                latency_ms=1200.0,
                cost_eur=0.0,
                risk=0.15,
                capabilities=frozenset({"planning", "orchestration", "verification"}),
            )
        ]
        q = f"mcp__{P0_02_SERVER_ID}__"
        tools = [
            MCPToolRef(q + "skills_search", True, frozenset({"planning", "orchestration"})),
            MCPToolRef(q + "skills_get", True, frozenset({"orchestration"})),
            MCPToolRef(q + "skills_dependencies", True, frozenset({"planning", "orchestration"})),
            MCPToolRef(q + "skills_conflicts", True, frozenset({"verification"})),
            MCPToolRef(q + "skills_validate", True, frozenset({"verification"})),
        ]
        plan = build_plan(
            task=task,
            skill_matches=skill_matches,
            agents=agents,
            models=models,
            tools=tools,
        )

        p0_04_plan_pass = (
            plan.verdict == "PASS"
            and plan.coalition.complete
            and plan.selected_model is not None
            and len(plan.selected_tools) >= 3
            and {item.name for item in plan.strategies} == {"A", "B", "C", "D"}
            and {item.name for item in plan.arena} == {"A", "B", "C", "D"}
            and bool(plan.selected_skills)
        )

        p0_03_src = str((omniroute_repo / "src").resolve())
        if p0_03_src not in sys.path:
            sys.path.insert(0, p0_03_src)
        from clement_omniroute import EndpointKind, classify_final_provider, decide_accounting

        coalition_names = [agent.name for agent in plan.coalition.agents]
        live_executions: list[dict[str, Any]] = []
        all_route_pass = True
        all_accounting_pass = True
        all_cache_miss = True

        for strategy in plan.strategies:
            evidence = _post_strategy(
                base_url=omniroute_url,
                model_alias=model_alias,
                strategy_name=strategy.name,
                strategy_description=strategy.description,
                objective=OBJECTIVE,
                best_skill_id=best_skill_id,
                best_skill_content=best_skill_content,
                coalition_agents=coalition_names,
            )
            final_kind = classify_final_provider(evidence.final_provider)
            accounting = decide_accounting(
                endpoint_kind=EndpointKind.PROXY,
                final_provider_kind=final_kind,
                technical_tokens=evidence.technical_tokens or 0,
                provider_billable_tokens=evidence.provider_billable_tokens,
                reported_cost_eur=evidence.reported_cost_eur,
            )
            route_pass = evidence.complete and final_kind in {EndpointKind.LOCAL, EndpointKind.CLOUD}
            cache_miss = (evidence.cache_status or "").upper() == "MISS"
            accounting_pass = accounting.verdict == "PASS"
            all_route_pass = all_route_pass and route_pass
            all_accounting_pass = all_accounting_pass and accounting_pass
            all_cache_miss = all_cache_miss and cache_miss

            item = evidence.as_dict()
            item.update(
                {
                    "final_provider_kind": final_kind.value,
                    "billing_mode": accounting.billing_mode,
                    "billable_tokens": accounting.billable_tokens,
                    "quota_used": accounting.quota_used,
                    "cost_eur": accounting.cost_eur,
                    "accounting_verdict": accounting.verdict,
                    "route_pass": route_pass,
                    "cache_miss": cache_miss,
                }
            )
            live_executions.append(item)

        quality = plan.arena[0].quality if plan.arena else 0.0
        final_verification = verify_result(
            checks=[
                p0_01_pass,
                p0_02_pass,
                odysseus_ok,
                p0_04_plan_pass,
                all_route_pass,
                all_accounting_pass,
                all_cache_miss,
            ],
            quality_score=quality,
        )

        checks: dict[str, bool | None] = {
            "p0_01_registry_905_imported": p0_01_pass,
            "p0_02_mcp_contract_and_real_calls": p0_02_pass,
            "odysseus_health": odysseus_ok,
            "p0_04_plan_and_coalition": p0_04_plan_pass,
            "p0_03_live_routes_resolved": all_route_pass,
            "p0_03_accounting_resolved": all_accounting_pass,
            "omniroute_cache_miss_all_strategies": all_cache_miss,
            "final_verifier_pass": final_verification.verdict == "PASS",
        }
        global_result, reasons = evidence_verdict(checks)

        report: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "global_result": global_result,
            "heads": heads,
            "branches": branches,
            "worktrees_clean": clean,
            "p0_01": {
                "result": "PASS" if p0_01_pass else "FAIL",
                "total_entries": total_entries,
                "state": registry_state,
                "head": heads["P0-01"],
            },
            "p0_02": {
                "result": "PASS" if p0_02_pass else "FAIL",
                "transport": mcp_evidence["transport"],
                "server_id": P0_02_SERVER_ID,
                "tool_count": len(tool_names),
                "tools": sorted(tool_names),
                "search_total": search_total,
                "best_skill_id": best_skill_id,
                "best_skill_name": best_skill.get("name"),
                "best_skill_score": mcp_evidence["best_skill_score"],
                "content_loaded": bool(best_skill_content.strip()),
                "validation_pass": validation.get("valid") is True,
                "dependencies_call": "PASS",
                "conflicts_call": "PASS",
                "odysseus_health": odysseus_health,
            },
            "p0_04_plan": {
                "task_id": plan.task_id,
                "verdict": plan.verdict,
                "selected_skill_ids": [item.skill_id for item in plan.selected_skills],
                "coalition_agents": coalition_names,
                "coalition_complete": plan.coalition.complete,
                "mentalities": sorted(item.value for item in mentalities),
                "selected_model": plan.selected_model.name if plan.selected_model else None,
                "selected_tools": [item.qualified_name for item in plan.selected_tools],
                "strategies": [item.name for item in plan.strategies],
                "arena": [item.name for item in plan.arena],
                "reasons": list(plan.reasons),
            },
            "p0_03": {
                "result": "PASS" if all_route_pass and all_accounting_pass and all_cache_miss else "FAIL",
                "entry_endpoint": omniroute_url,
                "entry_kind": "PROXY",
                "requested_alias": model_alias,
                "executions": live_executions,
            },
            "p0_04": {
                "result": "PASS" if p0_04_plan_pass and final_verification.verdict == "PASS" else "FAIL",
                "final_verifier": asdict(final_verification),
            },
            "checks": checks,
            "reasons": list(reasons),
        }

        json_report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        md_report.write_text(_markdown(report), encoding="utf-8")

        providers = sorted({str(item["final_provider"]) for item in live_executions})
        models_used = sorted({str(item["final_model"]) for item in live_executions})
        total_technical = sum(int(item["technical_tokens"] or 0) for item in live_executions)
        total_billable = sum(int(item["billable_tokens"] or 0) for item in live_executions)
        total_cost = sum(float(item["cost_eur"] or 0.0) for item in live_executions)

        print(f"P0_01={'PASS' if p0_01_pass else 'FAIL'}")
        print(f"P0_02={'PASS' if p0_02_pass else 'FAIL'}")
        print(f"P0_03={'PASS' if report['p0_03']['result'] == 'PASS' else 'FAIL'}")
        print(f"P0_04={'PASS' if report['p0_04']['result'] == 'PASS' else 'FAIL'}")
        print(f"ODYSSEUS_HEALTH={'PASS' if odysseus_ok else 'FAIL'}")
        print(f"SKILLS_REGISTRY={total_entries}")
        print(f"MCP_TOOLS={len(tool_names)}")
        print(f"BEST_SKILL={best_skill_id}")
        print(f"SKILL_CONTENT_LOADED={str(bool(best_skill_content.strip())).lower()}")
        print(f"COALITION_COMPLETE={str(plan.coalition.complete).lower()}")
        print(f"COALITION={','.join(coalition_names)}")
        print(f"ARENA={','.join(item.name for item in plan.arena)}")
        print(f"STRATEGIES_EXECUTED={','.join(item.name for item in plan.strategies)}")
        print(f"OMNIROUTE_ALIAS={model_alias}")
        print(f"FINAL_PROVIDERS={','.join(providers)}")
        print(f"FINAL_MODELS={','.join(models_used)}")
        print(f"TECHNICAL_TOKENS_TOTAL={total_technical}")
        print(f"BILLABLE_TOKENS_TOTAL={total_billable}")
        print(f"REPORTED_COST_EUR_TOTAL={total_cost:.10f}")
        print(f"VERIFICATION={final_verification.verdict}")
        print(f"JSON_REPORT={json_report}")
        print(f"MARKDOWN_REPORT={md_report}")
        print(f"GLOBAL_RESULT={global_result}")
        print("MERGE_EXECUTED=NO")
        print("TAG_CREATED=NO")
        print("RELEASE_CREATED=NO")
        return 0 if global_result == "PASS" else 2

    except Exception as exc:
        failure = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "global_result": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }
        json_report.write_text(json.dumps(failure, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"GLOBAL_ERROR={type(exc).__name__}: {exc}")
        print("GLOBAL_RESULT=FAIL")
        print(f"JSON_REPORT={json_report}")
        print("MERGE_EXECUTED=NO")
        print("TAG_CREATED=NO")
        print("RELEASE_CREATED=NO")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
