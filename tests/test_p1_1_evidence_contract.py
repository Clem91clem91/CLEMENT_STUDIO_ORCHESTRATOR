from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from clement_orchestrator.evidence_contract import (
    EvidenceSource,
    EvidenceStore,
    EvidenceVerdict,
    json_path_get,
)
from clement_orchestrator.execution_core import ExecutionCore
from clement_orchestrator.execution_fabric import ExecutionFabric, RiskLevel, ToolDescriptor


def test_json_path_get_supports_object_and_array() -> None:
    value = {"files": [{"id": "abc", "name": "x"}]}
    assert json_path_get(value, "$.files[0].id") == "abc"


def test_json_path_get_rejects_missing_path() -> None:
    with pytest.raises(KeyError):
        json_path_get({"files": []}, "$.files[0].id")


def test_no_source_means_inconclusive() -> None:
    store = EvidenceStore()
    claim = store.claim(
        task_id="TASK-20260821-0001",
        metric="agent_count",
        value=6,
        source_evidence_id=None,
    )
    store.verify_claim(claim)
    assert claim.verdict is EvidenceVerdict.INCONCLUSIVE
    assert claim.verified is False
    assert claim.reason == "NO_SOURCE_EVIDENCE"


def test_model_output_is_never_machine_evidence() -> None:
    store = EvidenceStore()
    model = store.record_model_statement(task_id="TASK-20260821-0001", statement={"agent_count": 905})
    claim = store.claim(
        task_id="TASK-20260821-0001",
        metric="agent_count",
        value=905,
        source_evidence_id=model.evidence_id,
        source_json_path="$.agent_count",
    )
    store.verify_claim(claim)
    assert claim.verdict is EvidenceVerdict.FAIL
    assert claim.reason == "MODEL_OUTPUT_IS_NOT_EVIDENCE"


def test_claim_passes_only_when_raw_source_matches() -> None:
    store = EvidenceStore()
    raw = store.record_tool_call(
        task_id="TASK-20260821-0001",
        server="google_drive",
        tool="drive_search_files",
        arguments={"text": "target.txt"},
        raw_result={"files": [{"id": "1REAL", "name": "target.txt"}]},
    )
    claim = store.claim(
        task_id="TASK-20260821-0001",
        metric="drive_file_id",
        value="1REAL",
        source_evidence_id=raw.evidence_id,
        source_json_path="$.files[0].id",
    )
    store.verify_claim(claim)
    assert claim.verified is True
    assert claim.verdict is EvidenceVerdict.PASS


def test_claim_fails_when_raw_source_value_differs() -> None:
    store = EvidenceStore()
    raw = store.record_system(task_id="TASK-20260821-0001", metric="agent_count", value=6)
    claim = store.claim(
        task_id="TASK-20260821-0001",
        metric="agent_count",
        value=905,
        source_evidence_id=raw.evidence_id,
        source_json_path="$.value",
    )
    store.verify_claim(claim)
    assert claim.verdict is EvidenceVerdict.FAIL
    assert claim.reason == "SOURCE_VALUE_MISMATCH"


def test_drive_empty_search_plus_unrelated_get_is_fail() -> None:
    store = EvidenceStore()
    search = store.record_tool_call(
        task_id="TASK-20260821-0001",
        server="google_drive",
        tool="drive_search_files",
        arguments={"text": "CLEMENT_P1_ODYSSEUS_DRIVE_TEST.txt"},
        raw_result={"ok": True, "files": []},
    )
    get = store.record_tool_call(
        task_id="TASK-20260821-0001",
        server="google_drive",
        tool="drive_get_file",
        arguments={"file_id": "1OTHER"},
        raw_result={"ok": True, "file": {"id": "1OTHER", "name": "CLEMENT_SHADOW_MASTER_CONTROL_v1.0.xlsx"}},
    )
    finding = store.check_drive_lookup(
        requested_name="CLEMENT_P1_ODYSSEUS_DRIVE_TEST.txt",
        search_evidence_id=search.evidence_id,
        get_evidence_id=get.evidence_id,
    )
    assert finding.verdict is EvidenceVerdict.FAIL
    assert finding.code == "DRIVE_TARGET_PROVENANCE"


def test_drive_matching_search_and_get_is_pass() -> None:
    store = EvidenceStore()
    search = store.record_tool_call(
        task_id="TASK-20260821-0001",
        server="google_drive",
        tool="drive_search_files",
        arguments={"text": "target.txt"},
        raw_result={"files": [{"id": "1REAL", "name": "target.txt"}]},
    )
    get = store.record_tool_call(
        task_id="TASK-20260821-0001",
        server="google_drive",
        tool="drive_get_file",
        arguments={"file_id": "1REAL"},
        raw_result={"file": {"id": "1REAL", "name": "target.txt"}},
    )
    finding = store.check_drive_lookup(
        requested_name="target.txt",
        search_evidence_id=search.evidence_id,
        get_evidence_id=get.evidence_id,
    )
    assert finding.verdict is EvidenceVerdict.PASS


def test_agent_zero_with_coalition_pass_is_fail() -> None:
    store = EvidenceStore()
    finding = store.check_agent_coalition_consistency(
        agent_count=0,
        coalition_count=0,
        coalition_pass=True,
    )
    assert finding.verdict is EvidenceVerdict.FAIL
    assert finding.code == "AGENT_COALITION_CONTRADICTION"


def test_agent_and_coalition_counts_consistent_is_pass() -> None:
    store = EvidenceStore()
    finding = store.check_agent_coalition_consistency(
        agent_count=6,
        coalition_count=1,
        coalition_pass=True,
    )
    assert finding.verdict is EvidenceVerdict.PASS


def test_skill_agent_equal_without_distinct_sources_is_partial() -> None:
    store = EvidenceStore()
    finding = store.check_metric_collision(
        metric_a="skill_count",
        value_a=905,
        evidence_a=None,
        metric_b="agent_count",
        value_b=905,
        evidence_b=None,
    )
    assert finding.verdict is EvidenceVerdict.PARTIAL
    assert finding.code == "SUSPICIOUS_METRIC_COLLISION"


def test_verify_task_cannot_pass_without_claims() -> None:
    store = EvidenceStore()
    store.record_system(task_id="TASK-20260821-0001", metric="healthy", value=True)
    report = store.verify_task("TASK-20260821-0001")
    assert report.verdict is EvidenceVerdict.INCONCLUSIVE


def test_verify_task_fails_on_one_contradiction() -> None:
    store = EvidenceStore()
    raw = store.record_system(task_id="TASK-20260821-0001", metric="agent_count", value=6)
    store.claim(
        task_id="TASK-20260821-0001",
        metric="agent_count",
        value=6,
        source_evidence_id=raw.evidence_id,
        source_json_path="$.value",
    )
    store.check_agent_coalition_consistency(agent_count=0, coalition_count=0, coalition_pass=True)
    report = store.verify_task("TASK-20260821-0001")
    assert report.verdict is EvidenceVerdict.FAIL


def test_evidence_is_persisted_as_raw_jsonl_and_report(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    raw = store.record_system(task_id="TASK-20260821-0001", metric="agent_count", value=6)
    store.claim(
        task_id="TASK-20260821-0001",
        metric="agent_count",
        value=6,
        source_evidence_id=raw.evidence_id,
        source_json_path="$.value",
    )
    report = store.verify_task("TASK-20260821-0001")
    raw_path = tmp_path / "TASK-20260821-0001" / "RAW_EVIDENCE.jsonl"
    report_path = tmp_path / "TASK-20260821-0001" / "EVIDENCE_REPORT.json"
    assert raw_path.is_file()
    assert report_path.is_file()
    assert report.verdict is EvidenceVerdict.PASS
    parsed = json.loads(report_path.read_text(encoding="utf-8"))
    assert parsed["verdict"] == "PASS"


def test_execution_core_records_raw_tool_evidence(tmp_path: Path) -> None:
    fabric = ExecutionFabric()
    descriptor = ToolDescriptor(
        tool="files_read_text",
        server="files_plus",
        capabilities=("READ", "TEXT", "FILESYSTEM"),
        risk=RiskLevel.SAFE,
        available=True,
        read_only=True,
    )
    fabric.register(descriptor, executor=lambda payload: {"text": "hello", "path": payload["path"]})
    core = ExecutionCore(log_root=tmp_path / "logs", fabric=fabric)
    mission = core.begin_mission(
        "read",
        "test",
        skills=[],
        models=[],
        required_agent_capabilities=["execution"],
        complexity=1,
        desired_agent_count=1,
        task_id="TASK-20260821-0001",
    )
    result = asyncio.run(
        core.execute_capability(
            mission,
            ("READ", "TEXT", "FILESYSTEM"),
            {"path": "probe.txt"},
        )
    )
    assert result.ok
    evidence = core.evidence.evidence_for_task(mission.task_id)
    assert len(evidence) == 1
    assert evidence[0]["server"] == "files_plus"
    assert evidence[0]["tool"] == "files_read_text"
    assert evidence[0]["arguments"] == {"path": "probe.txt"}
    assert evidence[0]["raw_result"]["text"] == "hello"


def test_execution_core_finish_records_task_report(tmp_path: Path) -> None:
    core = ExecutionCore(log_root=tmp_path / "logs")
    mission = core.begin_mission(
        "observe",
        "test",
        skills=["verification"],
        models=["local"],
        required_agent_capabilities=["verification"],
        complexity=1,
        desired_agent_count=1,
        task_id="TASK-20260821-0001",
    )
    json_path, _ = core.finish_mission(mission, result="PASS", verification="PASS")
    assert json_path.is_file()
    evidence = core.evidence.evidence_for_task(mission.task_id)
    reports = [item for item in evidence if item["source"] == EvidenceSource.TASK_REPORT.value]
    assert len(reports) == 1
    assert reports[0]["raw_result"]["task_id"] == mission.task_id
