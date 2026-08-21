# CLEMENT STUDIO P1.1 — Evidence Contract

## Objective

P1.1 prevents an Odysseus/model summary from being accepted as machine truth unless the claimed value is traceable to raw execution evidence.

Core rule:

`NO EVIDENCE -> NO PASS`

## P1.1-01 — Raw Evidence Store

Every P1 tool execution records:

- task_id
- evidence_id
- server
- tool
- exact arguments
- raw_result
- timestamp
- execution metadata

Raw evidence is persisted in `RAW_EVIDENCE.jsonl`.

## P1.1-02 — Provenance

A claim carries:

- metric
- value
- source_evidence_id
- source_json_path
- verification state

A claim is PASS only when the value at `source_json_path` in the referenced machine evidence exactly equals the claimed value.

Model-generated text is explicitly rejected as an evidence source.

## P1.1-03 — Consistency Engine

Initial deterministic rules cover the failures reproduced during the Odysseus P1 audit:

1. Google Drive search returns no matching target but a subsequent GET returns another file -> FAIL.
2. A coalition is declared PASS while agent_count or coalition_count is zero -> FAIL.
3. skill_count and agent_count collide without distinct provenance -> PARTIAL / suspicious metric collision.

The engine is deterministic and does not depend on LLM judgement.

## P1.1-04 — Fail-Closed Verifier

Verdicts:

- PASS: all required claims have matching machine evidence and no contradiction exists.
- PARTIAL: evidence exists but a non-fatal provenance/consistency concern remains.
- INCONCLUSIVE: evidence is missing or insufficient.
- FAIL: evidence contradicts a claim, source path/value is invalid, model output is used as proof, or consistency rules detect contradiction.

The verifier never upgrades absent evidence to PASS.

## ExecutionCore integration

`ExecutionCore.execute_capability()` records raw evidence automatically for every selected P1 tool call and links the resulting `evidence_id` into the task's `tool_calls` trace.

`ExecutionCore.finish_mission()` records `TASK_REPORT.json` as machine evidence.

Additional API:

- `claim_metric(...)`
- `verify_evidence(...)`

## Certification

CI must pass:

- Windows Python 3.11 / 3.13
- Ubuntu Python 3.11 / 3.13
- existing P0/P1 tests
- P1 reference E2E
- P1.1 reference evidence certification
- Windows PowerShell parsing
- `governance-gate`

Shadow certification additionally runs the real P1 MCP E2E and verifies that:

- raw tool evidence was persisted;
- TASK_REPORT tool calls are linked to evidence IDs;
- the real Google Drive upload file ID is provable from raw output;
- the reproduced Drive false-PASS is blocked;
- the reproduced agent false-PASS is blocked;
- fabricated model evidence is rejected.

No merge, tag, or release is authorized by P1.1 implementation or certification itself.
