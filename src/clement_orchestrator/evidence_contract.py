from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping


class EvidenceVerdict(str, Enum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class EvidenceSource(str, Enum):
    TOOL = "TOOL"
    TASK_REPORT = "TASK_REPORT"
    SYSTEM = "SYSTEM"
    MODEL = "MODEL"


@dataclass(slots=True)
class RawEvidence:
    evidence_id: str
    task_id: str
    source: EvidenceSource
    timestamp: str
    server: str | None = None
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_result: Any = None
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source"] = self.source.value
        return value


@dataclass(slots=True)
class Claim:
    claim_id: str
    task_id: str
    metric: str
    value: Any
    source_evidence_id: str | None
    source_json_path: str | None
    verdict: EvidenceVerdict = EvidenceVerdict.INCONCLUSIVE
    verified: bool = False
    reason: str = "UNVERIFIED"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["verdict"] = self.verdict.value
        return value


@dataclass(slots=True)
class ConsistencyFinding:
    code: str
    verdict: EvidenceVerdict
    message: str
    evidence_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "verdict": self.verdict.value,
            "message": self.message,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(slots=True)
class VerificationReport:
    task_id: str
    verdict: EvidenceVerdict
    claims: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    evidence_count: int
    verified_claims: int
    unverified_claims: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "verdict": self.verdict.value,
            "claims": self.claims,
            "findings": self.findings,
            "evidence_count": self.evidence_count,
            "verified_claims": self.verified_claims,
            "unverified_claims": self.unverified_claims,
        }


_JSON_TOKEN_RE = re.compile(r"(?:\.([A-Za-z_][A-Za-z0-9_]*))|(?:\[(\d+)\])")


def json_path_get(value: Any, path: str | None) -> Any:
    if path in (None, "", "$"):
        return value
    if not str(path).startswith("$"):
        raise ValueError(f"JSON_PATH_INVALID={path}")
    current = value
    consumed = "$"
    for match in _JSON_TOKEN_RE.finditer(str(path)[1:]):
        if match.group(1) is not None:
            key = match.group(1)
            if not isinstance(current, Mapping) or key not in current:
                raise KeyError(f"JSON_PATH_MISSING={consumed}.{key}")
            current = current[key]
            consumed += f".{key}"
        else:
            index = int(match.group(2))
            if not isinstance(current, (list, tuple)) or index >= len(current):
                raise KeyError(f"JSON_PATH_MISSING={consumed}[{index}]")
            current = current[index]
            consumed += f"[{index}]"
    normalised = consumed.replace("$", "", 1)
    requested = str(path).replace("$", "", 1)
    if normalised != requested:
        raise ValueError(f"JSON_PATH_UNSUPPORTED={path}")
    return current


class EvidenceStore:
    """Machine evidence store. Model-generated values are never trusted as proof."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else None
        self._evidence: dict[str, RawEvidence] = {}
        self._claims: dict[str, Claim] = {}
        self._findings: list[ConsistencyFinding] = []
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)

    def record_tool_call(
        self,
        *,
        task_id: str,
        server: str,
        tool: str,
        arguments: Mapping[str, Any] | None,
        raw_result: Any,
        metadata: Mapping[str, Any] | None = None,
    ) -> RawEvidence:
        evidence = RawEvidence(
            evidence_id=f"EVID-{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            source=EvidenceSource.TOOL,
            timestamp=datetime.now(timezone.utc).isoformat(),
            server=server,
            tool=tool,
            arguments=copy.deepcopy(dict(arguments or {})),
            raw_result=copy.deepcopy(raw_result),
            metadata=copy.deepcopy(dict(metadata or {})),
        )
        return self._record(evidence)

    def record_task_report(self, *, task_id: str, path: str | Path, report: Mapping[str, Any]) -> RawEvidence:
        evidence = RawEvidence(
            evidence_id=f"EVID-{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            source=EvidenceSource.TASK_REPORT,
            timestamp=datetime.now(timezone.utc).isoformat(),
            source_path=str(path),
            raw_result=copy.deepcopy(dict(report)),
        )
        return self._record(evidence)

    def record_system(self, *, task_id: str, metric: str, value: Any) -> RawEvidence:
        evidence = RawEvidence(
            evidence_id=f"EVID-{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            source=EvidenceSource.SYSTEM,
            timestamp=datetime.now(timezone.utc).isoformat(),
            raw_result={"metric": metric, "value": copy.deepcopy(value)},
        )
        return self._record(evidence)

    def record_model_statement(self, *, task_id: str, statement: Any) -> RawEvidence:
        evidence = RawEvidence(
            evidence_id=f"EVID-{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            source=EvidenceSource.MODEL,
            timestamp=datetime.now(timezone.utc).isoformat(),
            raw_result=copy.deepcopy(statement),
        )
        return self._record(evidence)

    def claim(
        self,
        *,
        task_id: str,
        metric: str,
        value: Any,
        source_evidence_id: str | None,
        source_json_path: str | None = "$",
    ) -> Claim:
        claim = Claim(
            claim_id=f"CLAIM-{uuid.uuid4().hex[:16]}",
            task_id=task_id,
            metric=str(metric),
            value=copy.deepcopy(value),
            source_evidence_id=source_evidence_id,
            source_json_path=source_json_path,
        )
        self._claims[claim.claim_id] = claim
        return claim

    def verify_claim(self, claim: Claim | str) -> Claim:
        item = self._claims[claim] if isinstance(claim, str) else claim
        if not item.source_evidence_id:
            item.verdict = EvidenceVerdict.INCONCLUSIVE
            item.verified = False
            item.reason = "NO_SOURCE_EVIDENCE"
            return item
        evidence = self._evidence.get(item.source_evidence_id)
        if evidence is None:
            item.verdict = EvidenceVerdict.INCONCLUSIVE
            item.verified = False
            item.reason = "SOURCE_EVIDENCE_NOT_FOUND"
            return item
        if evidence.source is EvidenceSource.MODEL:
            item.verdict = EvidenceVerdict.FAIL
            item.verified = False
            item.reason = "MODEL_OUTPUT_IS_NOT_EVIDENCE"
            return item
        try:
            source_value = json_path_get(evidence.raw_result, item.source_json_path)
        except (KeyError, ValueError, TypeError) as exc:
            item.verdict = EvidenceVerdict.FAIL
            item.verified = False
            item.reason = f"SOURCE_PATH_INVALID:{exc}"
            return item
        if source_value != item.value:
            item.verdict = EvidenceVerdict.FAIL
            item.verified = False
            item.reason = "SOURCE_VALUE_MISMATCH"
            return item
        item.verdict = EvidenceVerdict.PASS
        item.verified = True
        item.reason = "SOURCE_VALUE_MATCH"
        return item

    def add_finding(self, code: str, verdict: EvidenceVerdict, message: str, evidence_ids: Iterable[str] = ()) -> ConsistencyFinding:
        finding = ConsistencyFinding(str(code), verdict, str(message), list(evidence_ids))
        self._findings.append(finding)
        return finding

    def check_drive_lookup(
        self,
        *,
        requested_name: str,
        search_evidence_id: str,
        get_evidence_id: str | None = None,
    ) -> ConsistencyFinding:
        search = self._evidence[search_evidence_id]
        files = []
        if isinstance(search.raw_result, Mapping):
            raw_files = search.raw_result.get("files", [])
            if isinstance(raw_files, list):
                files = raw_files
        exact = [item for item in files if isinstance(item, Mapping) and item.get("name") == requested_name]
        if not exact:
            verdict = EvidenceVerdict.FAIL if get_evidence_id else EvidenceVerdict.INCONCLUSIVE
            message = "TARGET_NOT_FOUND_IN_SEARCH"
            if get_evidence_id:
                get_evidence = self._evidence[get_evidence_id]
                name = None
                if isinstance(get_evidence.raw_result, Mapping):
                    payload = get_evidence.raw_result.get("file", get_evidence.raw_result)
                    if isinstance(payload, Mapping):
                        name = payload.get("name")
                message = f"SEARCH_EMPTY_OR_TARGET_MISSING_GET_NAME={name}"
            return self.add_finding(
                "DRIVE_TARGET_PROVENANCE",
                verdict,
                message,
                [eid for eid in (search_evidence_id, get_evidence_id) if eid],
            )
        if get_evidence_id:
            expected_ids = {item.get("id") for item in exact if item.get("id")}
            get_evidence = self._evidence[get_evidence_id]
            payload = get_evidence.raw_result
            if isinstance(payload, Mapping):
                payload = payload.get("file", payload)
            get_id = payload.get("id") if isinstance(payload, Mapping) else None
            get_name = payload.get("name") if isinstance(payload, Mapping) else None
            if get_id not in expected_ids or get_name != requested_name:
                return self.add_finding(
                    "DRIVE_GET_MISMATCH",
                    EvidenceVerdict.FAIL,
                    f"EXPECTED_NAME={requested_name} EXPECTED_IDS={sorted(str(v) for v in expected_ids)} GET_ID={get_id} GET_NAME={get_name}",
                    [search_evidence_id, get_evidence_id],
                )
        return self.add_finding(
            "DRIVE_TARGET_PROVENANCE",
            EvidenceVerdict.PASS,
            "SEARCH_AND_GET_MATCH_TARGET",
            [eid for eid in (search_evidence_id, get_evidence_id) if eid],
        )

    def check_agent_coalition_consistency(
        self,
        *,
        agent_count: int,
        coalition_count: int,
        coalition_pass: bool,
        source_evidence_ids: Iterable[str] = (),
    ) -> ConsistencyFinding:
        agent_count = int(agent_count)
        coalition_count = int(coalition_count)
        if coalition_pass and (agent_count <= 0 or coalition_count <= 0):
            return self.add_finding(
                "AGENT_COALITION_CONTRADICTION",
                EvidenceVerdict.FAIL,
                f"coalition_pass=true agent_count={agent_count} coalition_count={coalition_count}",
                source_evidence_ids,
            )
        return self.add_finding(
            "AGENT_COALITION_CONSISTENCY",
            EvidenceVerdict.PASS,
            f"agent_count={agent_count} coalition_count={coalition_count} coalition_pass={str(coalition_pass).lower()}",
            source_evidence_ids,
        )

    def check_metric_collision(
        self,
        *,
        metric_a: str,
        value_a: Any,
        evidence_a: str | None,
        metric_b: str,
        value_b: Any,
        evidence_b: str | None,
    ) -> ConsistencyFinding:
        if value_a == value_b and (not evidence_a or not evidence_b or evidence_a == evidence_b):
            return self.add_finding(
                "SUSPICIOUS_METRIC_COLLISION",
                EvidenceVerdict.PARTIAL,
                f"{metric_a}={value_a} {metric_b}={value_b} lack distinct provenance",
                [eid for eid in (evidence_a, evidence_b) if eid],
            )
        return self.add_finding(
            "METRIC_PROVENANCE_DISTINCT",
            EvidenceVerdict.PASS,
            f"{metric_a} and {metric_b} have distinguishable provenance",
            [eid for eid in (evidence_a, evidence_b) if eid],
        )

    def verify_task(self, task_id: str) -> VerificationReport:
        claims = [claim for claim in self._claims.values() if claim.task_id == task_id]
        for claim in claims:
            self.verify_claim(claim)
        evidence = [item for item in self._evidence.values() if item.task_id == task_id]
        findings = [item for item in self._findings if any(eid in {ev.evidence_id for ev in evidence} for eid in item.evidence_ids) or not item.evidence_ids]
        claim_verdicts = [claim.verdict for claim in claims]
        finding_verdicts = [item.verdict for item in findings]
        all_verdicts = [*claim_verdicts, *finding_verdicts]
        if EvidenceVerdict.FAIL in all_verdicts:
            verdict = EvidenceVerdict.FAIL
        elif not claims:
            verdict = EvidenceVerdict.INCONCLUSIVE
        elif EvidenceVerdict.INCONCLUSIVE in all_verdicts:
            verdict = EvidenceVerdict.INCONCLUSIVE
        elif EvidenceVerdict.PARTIAL in all_verdicts:
            verdict = EvidenceVerdict.PARTIAL
        elif all(claim.verified for claim in claims):
            verdict = EvidenceVerdict.PASS
        else:
            verdict = EvidenceVerdict.INCONCLUSIVE
        report = VerificationReport(
            task_id=task_id,
            verdict=verdict,
            claims=[claim.as_dict() for claim in claims],
            findings=[finding.as_dict() for finding in findings],
            evidence_count=len(evidence),
            verified_claims=sum(1 for claim in claims if claim.verified),
            unverified_claims=sum(1 for claim in claims if not claim.verified),
        )
        self._flush_task(task_id, report)
        return report

    def evidence_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self._evidence.values() if item.task_id == task_id]

    def claims_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self._claims.values() if item.task_id == task_id]

    def _record(self, evidence: RawEvidence) -> RawEvidence:
        self._evidence[evidence.evidence_id] = evidence
        self._append_raw(evidence)
        return evidence

    def _append_raw(self, evidence: RawEvidence) -> None:
        if self.root is None:
            return
        path = self.root / evidence.task_id / "RAW_EVIDENCE.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(evidence.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def _flush_task(self, task_id: str, report: VerificationReport) -> None:
        if self.root is None:
            return
        task_dir = self.root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "EVIDENCE_REPORT.json").write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
