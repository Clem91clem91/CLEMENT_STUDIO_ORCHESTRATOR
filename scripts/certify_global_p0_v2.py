from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from clement_orchestrator.core import AgentProfile, Mentality, TaskContext, verify_result
from clement_orchestrator.global_e2e import EXPECTED_SKILLS_MCP_TOOLS, evidence_verdict
from clement_orchestrator.pipeline import MCPToolRef, ModelCandidate, build_plan
from clement_orchestrator.reasoning import infer_mentalities
from clement_orchestrator.skills_mcp import skill_matches_from_search


MAX_STRATEGY_ATTEMPTS = 3


def _load_legacy_module():
    path = Path(__file__).with_name("certify_global_p0.py")
    spec = importlib.util.spec_from_file_location("clement_global_certifier_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"GLOBAL_V1_IMPORT_FAILED={path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


legacy = _load_legacy_module()


def _markdown(report: Mapping[str, Any]) -> str:
    plan = report["p0_04_plan"]
    execution = report["p0_04"]["execution"]
    lines = [
        "# CLEMENT STUDIO - Global P0 Certification V2",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Global result: **{report['global_result']}**",
        "",
        "## P0 gates",
        "",
        f"- P0-01: **{report['p0_01']['result']}** - {report['p0_01']['total_entries']} skills, state `{report['p0_01']['state']}`",
        f"- P0-02: **{report['p0_02']['result']}** - {report['p0_02']['tool_count']} MCP tools, search total {report['p0_02']['search_total']}",
        f"- P0-03: **{report['p0_03']['result']}** - routing/accounting/cache evidence only",
        f"- P0-04: **{report['p0_04']['result']}** - plan + strategy execution markers + verifier",
        "",
        "## Plan",
        "",
        f"- Task: `{plan['task_id']}`",
        f"- Best skill: `{report['p0_02']['best_skill_id']}`",
        f"- Coalition: {', '.join(plan['coalition_agents'])}",
        f"- Model alias: `{plan['selected_model']}`",
        f"- Arena: {','.join(plan['arena'])}",
        "",
        "## P0-04 strategy execution",
        "",
    ]
    for name in ("A", "B", "C", "D"):
        entry = execution["strategies"].get(name, {})
        lines.append(
            f"- {name}: **{'PASS' if entry.get('passed') else 'FAIL'}**, attempts={entry.get('attempts', 0)}"
        )

    lines.extend(
        [
            "",
            "## Live route attempts",
            "",
            "| Strategy | Attempt | Marker | Provider | Final model | HTTP | Cache | Technical tokens | Billable tokens | Cost EUR | Route | Accounting |",
            "|---|---:|---|---|---|---:|---|---:|---:|---:|---|---|",
        ]
    )
    for item in report["p0_03"]["executions"]:
        lines.append(
            f"| {item['strategy']} | {item['attempt']} | {item['marker_observed']} | {item['final_provider']} | "
            f"{item['final_model']} | {item['http_status']} | {item['cache_status']} | {item['technical_tokens']} | "
            f"{item['billable_tokens']} | {item['cost_eur']} | {item['route_pass']} | {item['accounting_verdict']} |"
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
    omniroute_url = os.environ.get("CLEMENT_OMNIROUTE_URL", legacy.DEFAULT_OMNIROUTE).rstrip("/")
    odysseus_health_url = os.environ.get("CLEMENT_ODYSSEUS_HEALTH_URL", legacy.DEFAULT_ODYSSEUS_HEALTH)
    model_alias = os.environ.get("CLEMENT_GLOBAL_MODEL_ALIAS", legacy.DEFAULT_MODEL_ALIAS)

    attempts_raw = os.environ.get("CLEMENT_GLOBAL_MAX_STRATEGY_ATTEMPTS", str(MAX_STRATEGY_ATTEMPTS))
    try:
        max_attempts = int(attempts_raw)
    except ValueError:
        max_attempts = MAX_STRATEGY_ATTEMPTS
    max_attempts = max(1, min(MAX_STRATEGY_ATTEMPTS, max_attempts))

    artifact_dir = repo / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    json_report = artifact_dir / "GLOBAL_P0_CERTIFICATION.json"
    md_report = artifact_dir / "GLOBAL_P0_CERTIFICATION.md"

    print("============================================================")
    print("CLEMENT STUDIO - GLOBAL P0 CERTIFICATION V2")
    print("MODE=REAL_E2E_FAIL_CLOSED_SEPARATED_GATES")
    print(f"MAX_STRATEGY_ATTEMPTS={max_attempts}")
    print("============================================================")

    try:
        for path, label in (
            (hub_root, "P0_01_ROOT"),
            (mcp_repo, "P0_02_ROOT"),
            (omniroute_repo, "P0_03_ROOT"),
            (repo, "P0_04_ROOT"),
        ):
            legacy._require_path(path, label)

        heads = {
            "P0-01": legacy._git_head(hub_root),
            "P0-02": legacy._git_head(mcp_repo),
            "P0-03": legacy._git_head(omniroute_repo),
            "P0-04": legacy._git_head(repo),
        }
        branches = {
            "P0-01": legacy._git_branch(hub_root),
            "P0-02": legacy._git_branch(mcp_repo),
            "P0-03": legacy._git_branch(omniroute_repo),
            "P0-04": legacy._git_branch(repo),
        }
        clean = {
            "P0-01": legacy._git_clean(hub_root),
            "P0-02": legacy._git_clean(mcp_repo),
            "P0-03": legacy._git_clean(omniroute_repo),
            "P0-04": legacy._git_clean(repo),
        }

        for name, expected in legacy.EXPECTED_HEADS.items():
            if heads[name] != expected:
                raise legacy.GlobalCertificationError(
                    f"{name}_HEAD_MISMATCH expected={expected} actual={heads[name]}"
                )
        if branches["P0-04"] != "feat/p0-dynamic-orchestrator":
            raise legacy.GlobalCertificationError(f"P0_04_WRONG_BRANCH={branches['P0-04']}")
        if not all(clean.values()):
            dirty = [name for name, value in clean.items() if not value]
            raise legacy.GlobalCertificationError(f"DIRTY_WORKTREES={','.join(dirty)}")

        registry_path = hub_root / "registry" / "skills_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        total_entries = int(registry.get("stats", {}).get("total_entries", -1))
        registry_state = str(registry.get("state") or "")
        p0_01_pass = total_entries == 905 and registry_state == "IMPORTED"

        odysseus_health = legacy._probe_json_get(odysseus_health_url)
        odysseus_ok = str(odysseus_health.get("status") or "").lower() == "healthy"

        mcp_evidence = asyncio.run(legacy._probe_skills_mcp(hub_root, mcp_repo))
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
            raise legacy.GlobalCertificationError("P0_04_SKILL_ADAPTER_RETURNED_ZERO_MATCHES")

        mentalities = infer_mentalities(legacy.OBJECTIVE, minimum=3)
        task = TaskContext(
            objective=legacy.OBJECTIVE,
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
        q = f"mcp__{legacy.P0_02_SERVER_ID}__"
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
        strategy_execution: dict[str, dict[str, Any]] = {}
        all_route_pass = True
        all_accounting_pass = True
        all_cache_miss = True
        all_execution_pass = True

        for strategy in plan.strategies:
            strategy_pass = False
            attempts_used = 0

            for attempt in range(1, max_attempts + 1):
                attempts_used = attempt
                evidence = legacy._post_strategy(
                    base_url=omniroute_url,
                    model_alias=model_alias,
                    strategy_name=strategy.name,
                    strategy_description=strategy.description,
                    objective=legacy.OBJECTIVE,
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

                route_pass = evidence.route_complete and final_kind in {EndpointKind.LOCAL, EndpointKind.CLOUD}
                cache_miss = (evidence.cache_status or "").upper() == "MISS"
                accounting_pass = accounting.verdict == "PASS"
                execution_pass = evidence.execution_complete

                all_route_pass = all_route_pass and route_pass
                all_accounting_pass = all_accounting_pass and accounting_pass
                all_cache_miss = all_cache_miss and cache_miss

                item = evidence.as_dict()
                item.update(
                    {
                        "attempt": attempt,
                        "final_provider_kind": final_kind.value,
                        "billing_mode": accounting.billing_mode,
                        "billable_tokens": accounting.billable_tokens,
                        "quota_used": accounting.quota_used,
                        "cost_eur": accounting.cost_eur,
                        "accounting_verdict": accounting.verdict,
                        "route_pass": route_pass,
                        "execution_pass": execution_pass,
                        "cache_miss": cache_miss,
                    }
                )
                live_executions.append(item)

                if not route_pass or not accounting_pass or not cache_miss:
                    break
                if execution_pass:
                    strategy_pass = True
                    break
                # Route/accounting/cache were all valid but the application-level
                # marker was missing. Retry produces new evidence for P0-04 only.

            strategy_execution[strategy.name] = {
                "passed": strategy_pass,
                "attempts": attempts_used,
            }
            all_execution_pass = all_execution_pass and strategy_pass

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
                all_execution_pass,
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
            "omniroute_cache_miss_all_attempts": all_cache_miss,
            "p0_04_strategy_markers_all": all_execution_pass,
            "final_verifier_pass": final_verification.verdict == "PASS",
        }
        global_result, reasons = evidence_verdict(checks)

        report: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "certifier_version": "2",
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
                "server_id": legacy.P0_02_SERVER_ID,
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
                "result": "PASS" if p0_04_plan_pass and all_execution_pass and final_verification.verdict == "PASS" else "FAIL",
                "execution": {
                    "all_markers_pass": all_execution_pass,
                    "max_attempts_per_strategy": max_attempts,
                    "strategies": strategy_execution,
                },
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
        attempts_summary = ",".join(
            f"{name}:{strategy_execution[name]['attempts']}"
            for name in ("A", "B", "C", "D")
        )

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
        print(f"STRATEGY_ATTEMPTS={attempts_summary}")
        print(f"P0_04_EXECUTION_MARKERS={'PASS' if all_execution_pass else 'FAIL'}")
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
            "certifier_version": "2",
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
