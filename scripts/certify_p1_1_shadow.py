from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from clement_orchestrator.evidence_contract import EvidenceStore, EvidenceVerdict


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "P1_CERT"


def require(condition: bool, marker: str) -> None:
    if not condition:
        raise RuntimeError(marker)


def latest_p1_artifact() -> Path:
    candidates = [path for path in ARTIFACT_ROOT.glob("TASK-*") if path.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"P1_ARTIFACT_NOT_FOUND={ARTIFACT_ROOT}")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def main() -> int:
    print("============================================================")
    print("CLEMENT STUDIO - P1.1 SHADOW EVIDENCE CERTIFICATION")
    print("MODE=REAL_MCP_PLUS_ANTI_HALLUCINATION")
    print("============================================================")

    p1_script = ROOT / "scripts" / "certify_p1_shadow.py"
    run = subprocess.run([sys.executable, str(p1_script)], cwd=ROOT, text=True, capture_output=True, check=False)
    print(run.stdout, end="")
    if run.stderr:
        print(run.stderr, file=sys.stderr, end="")
    require(run.returncode == 0, f"P1_REAL_E2E_SUBPROCESS_FAIL={run.returncode}")
    require("P1_REAL_E2E=PASS" in run.stdout, "P1_REAL_E2E_MARKER_MISSING")

    artifact = latest_p1_artifact()
    task_reports = list((artifact / "logs" / "tasks").glob("TASK-*/TASK_REPORT.json"))
    require(len(task_reports) == 1, f"TASK_REPORT_COUNT_INVALID={len(task_reports)}")
    task_report_path = task_reports[0]
    task_report = json.loads(task_report_path.read_text(encoding="utf-8"))
    task_id = str(task_report["task_id"])

    raw_path = artifact / "logs" / "evidence" / task_id / "RAW_EVIDENCE.jsonl"
    require(raw_path.is_file(), f"RAW_EVIDENCE_NOT_FOUND={raw_path}")
    raw = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(raw) >= 6, f"RAW_EVIDENCE_TOO_SMALL={len(raw)}")

    tool_evidence = [item for item in raw if item.get("source") == "TOOL"]
    report_evidence = [item for item in raw if item.get("source") == "TASK_REPORT"]
    require(len(tool_evidence) >= 5, f"TOOL_EVIDENCE_TOO_SMALL={len(tool_evidence)}")
    require(len(report_evidence) == 1, f"TASK_REPORT_EVIDENCE_COUNT={len(report_evidence)}")

    servers = {str(item.get("server")) for item in tool_evidence}
    require("files_plus" in servers or "windows_control" in servers, "FILESYSTEM_EVIDENCE_MISSING")
    require("windows_control" in servers, "WINDOWS_CONTROL_EVIDENCE_MISSING")
    require("google_drive" in servers, "GOOGLE_DRIVE_EVIDENCE_MISSING")

    evidence_ids = {str(item["evidence_id"]) for item in tool_evidence}
    calls = task_report.get("tool_calls", [])
    require(calls, "TASK_REPORT_TOOL_CALLS_EMPTY")
    linked = [call for call in calls if call.get("evidence_id") in evidence_ids]
    require(len(linked) == len(calls), "TASK_REPORT_EVIDENCE_LINK_BROKEN")

    for item in tool_evidence:
        require(bool(item.get("server")), "RAW_SERVER_EMPTY")
        require(bool(item.get("tool")), "RAW_TOOL_EMPTY")
        require("arguments" in item, "RAW_ARGUMENTS_MISSING")
        require("raw_result" in item, "RAW_RESULT_MISSING")

    print(f"TASK_ID={task_id}")
    print(f"RAW_EVIDENCE_PATH={raw_path}")
    print(f"TASK_REPORT_PATH={task_report_path}")
    print(f"RAW_TOOL_EVIDENCE_COUNT={len(tool_evidence)}")
    print("TASK_REPORT_EVIDENCE_LINK=PASS")
    print("P1_1_01_RAW_EVIDENCE=PASS")

    # Verify a real Drive file ID claim from the raw upload result.
    upload = next((item for item in tool_evidence if item.get("server") == "google_drive" and "upload" in str(item.get("tool", "")).casefold()), None)
    require(upload is not None, "REAL_DRIVE_UPLOAD_EVIDENCE_MISSING")
    payload = upload.get("raw_result")
    require(isinstance(payload, dict), "REAL_DRIVE_RAW_RESULT_NOT_OBJECT")
    drive_file = payload.get("file")
    require(isinstance(drive_file, dict) and bool(drive_file.get("id")), "REAL_DRIVE_FILE_ID_MISSING")

    store = EvidenceStore(artifact / "p1_1_verification")
    imported = store.record_tool_call(
        task_id=task_id,
        server=str(upload["server"]),
        tool=str(upload["tool"]),
        arguments=dict(upload.get("arguments") or {}),
        raw_result=payload,
        metadata={"imported_from": str(raw_path), "original_evidence_id": upload["evidence_id"]},
    )
    claim = store.claim(
        task_id=task_id,
        metric="drive_file_id",
        value=str(drive_file["id"]),
        source_evidence_id=imported.evidence_id,
        source_json_path="$.file.id",
    )
    store.verify_claim(claim)
    require(claim.verified and claim.verdict is EvidenceVerdict.PASS, "REAL_DRIVE_PROVENANCE_FAIL")
    print(f"VERIFIED_DRIVE_FILE_ID={drive_file['id']}")
    print("P1_1_02_PROVENANCE=PASS")

    # Reproduce the observed Odysseus contradiction: empty search + unrelated get must be FAIL.
    search = store.record_tool_call(
        task_id=task_id,
        server="google_drive",
        tool="drive_search_files",
        arguments={"text": "CLEMENT_P1_ODYSSEUS_DRIVE_TEST.txt"},
        raw_result={"ok": True, "files": []},
    )
    wrong = store.record_tool_call(
        task_id=task_id,
        server="google_drive",
        tool="drive_get_file",
        arguments={"file_id": "1OTHER"},
        raw_result={"ok": True, "file": {"id": "1OTHER", "name": "CLEMENT_SHADOW_MASTER_CONTROL_v1.0.xlsx"}},
    )
    drive_finding = store.check_drive_lookup(
        requested_name="CLEMENT_P1_ODYSSEUS_DRIVE_TEST.txt",
        search_evidence_id=search.evidence_id,
        get_evidence_id=wrong.evidence_id,
    )
    require(drive_finding.verdict is EvidenceVerdict.FAIL, "DRIVE_FALSE_PASS_NOT_BLOCKED")

    agent_finding = store.check_agent_coalition_consistency(agent_count=0, coalition_count=0, coalition_pass=True)
    require(agent_finding.verdict is EvidenceVerdict.FAIL, "AGENT_FALSE_PASS_NOT_BLOCKED")
    print("P1_1_03_CONSISTENCY=PASS")

    model = store.record_model_statement(task_id=task_id, statement={"agent_count": 905, "coalition": "COL-789"})
    fabricated = store.claim(
        task_id=task_id,
        metric="agent_count",
        value=905,
        source_evidence_id=model.evidence_id,
        source_json_path="$.agent_count",
    )
    store.verify_claim(fabricated)
    require(fabricated.verdict is EvidenceVerdict.FAIL, "FABRICATED_MODEL_EVIDENCE_ACCEPTED")
    report = store.verify_task(task_id)
    require(report.verdict is EvidenceVerdict.FAIL, "FAIL_CLOSED_VERIFIER_DID_NOT_FAIL")
    print("FABRICATED_EVIDENCE_BLOCKED=PASS")
    print("NO_EVIDENCE_NO_PASS=PASS")
    print("P1_1_04_FAIL_CLOSED_VERIFIER=PASS")

    print("P1_1_SHADOW_REAL=PASS")
    print("P1_1_GLOBAL=PASS")
    print("MERGE_EXECUTED=NO")
    print("TAG_CREATED=NO")
    print("RELEASE_CREATED=NO")
    print("NEXT=P1_1_MERGE_VALIDATION")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("P1_1_SHADOW_REAL=FAIL")
        print(f"ERROR={type(exc).__name__}:{exc}")
        print("MERGE_EXECUTED=NO")
        print("TAG_CREATED=NO")
        print("RELEASE_CREATED=NO")
        raise
