from __future__ import annotations

import tempfile
from pathlib import Path

from clement_orchestrator.evidence_contract import EvidenceStore, EvidenceVerdict


def require(condition: bool, marker: str) -> None:
    if not condition:
        raise RuntimeError(marker)


def main() -> int:
    print("============================================================")
    print("CLEMENT STUDIO - P1.1 EVIDENCE CONTRACT REFERENCE")
    print("MODE=FAIL_CLOSED")
    print("============================================================")

    task_id = "TASK-20260821-9001"
    with tempfile.TemporaryDirectory() as tmp:
        store = EvidenceStore(Path(tmp))

        # P1.1-01 — raw tool evidence
        search = store.record_tool_call(
            task_id=task_id,
            server="google_drive",
            tool="drive_search_files",
            arguments={"text": "target.txt"},
            raw_result={"ok": True, "files": [{"id": "1REAL", "name": "target.txt"}]},
        )
        require(search.server == "google_drive", "RAW_EVIDENCE_SERVER_FAIL")
        require(search.tool == "drive_search_files", "RAW_EVIDENCE_TOOL_FAIL")
        require(search.arguments["text"] == "target.txt", "RAW_EVIDENCE_ARGS_FAIL")
        print("P1_1_01_RAW_EVIDENCE=PASS")

        # P1.1-02 — claim provenance
        claim = store.claim(
            task_id=task_id,
            metric="drive_file_id",
            value="1REAL",
            source_evidence_id=search.evidence_id,
            source_json_path="$.files[0].id",
        )
        store.verify_claim(claim)
        require(claim.verified, "PROVENANCE_NOT_VERIFIED")
        require(claim.verdict is EvidenceVerdict.PASS, "PROVENANCE_VERDICT_FAIL")
        print("P1_1_02_PROVENANCE=PASS")

        # P1.1-03 — consistency engine catches the exact Odysseus Drive failure.
        bad_search = store.record_tool_call(
            task_id=task_id,
            server="google_drive",
            tool="drive_search_files",
            arguments={"text": "CLEMENT_P1_ODYSSEUS_DRIVE_TEST.txt"},
            raw_result={"ok": True, "files": []},
        )
        wrong_get = store.record_tool_call(
            task_id=task_id,
            server="google_drive",
            tool="drive_get_file",
            arguments={"file_id": "1OTHER"},
            raw_result={"ok": True, "file": {"id": "1OTHER", "name": "CLEMENT_SHADOW_MASTER_CONTROL_v1.0.xlsx"}},
        )
        drive_finding = store.check_drive_lookup(
            requested_name="CLEMENT_P1_ODYSSEUS_DRIVE_TEST.txt",
            search_evidence_id=bad_search.evidence_id,
            get_evidence_id=wrong_get.evidence_id,
        )
        require(drive_finding.verdict is EvidenceVerdict.FAIL, "DRIVE_CONTRADICTION_NOT_CAUGHT")

        agent_finding = store.check_agent_coalition_consistency(
            agent_count=0,
            coalition_count=0,
            coalition_pass=True,
        )
        require(agent_finding.verdict is EvidenceVerdict.FAIL, "AGENT_CONTRADICTION_NOT_CAUGHT")
        print("P1_1_03_CONSISTENCY=PASS")

        # P1.1-04 — a model statement cannot be evidence and therefore cannot produce PASS.
        model = store.record_model_statement(task_id=task_id, statement={"agent_count": 905})
        fabricated = store.claim(
            task_id=task_id,
            metric="agent_count",
            value=905,
            source_evidence_id=model.evidence_id,
            source_json_path="$.agent_count",
        )
        store.verify_claim(fabricated)
        require(fabricated.verdict is EvidenceVerdict.FAIL, "MODEL_EVIDENCE_NOT_REJECTED")
        require(fabricated.verified is False, "MODEL_EVIDENCE_VERIFIED")

        report = store.verify_task(task_id)
        require(report.verdict is EvidenceVerdict.FAIL, "FAIL_CLOSED_REPORT_NOT_FAIL")
        print("P1_1_04_FAIL_CLOSED_VERIFIER=PASS")

        raw_path = Path(tmp) / task_id / "RAW_EVIDENCE.jsonl"
        report_path = Path(tmp) / task_id / "EVIDENCE_REPORT.json"
        require(raw_path.is_file(), "RAW_EVIDENCE_FILE_MISSING")
        require(report_path.is_file(), "EVIDENCE_REPORT_MISSING")
        print("RAW_EVIDENCE_STORE=PASS")
        print("EVIDENCE_REPORT=PASS")

    print("P1_1_REFERENCE=PASS")
    print("MERGE_EXECUTED=NO")
    print("TAG_CREATED=NO")
    print("RELEASE_CREATED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
