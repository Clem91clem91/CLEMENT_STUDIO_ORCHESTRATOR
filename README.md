# CLEMENT_STUDIO_ORCHESTRATOR

P0-04 - dynamic orchestrator for CLEMENT STUDIO.

## Pipeline

`intent -> Skills MCP -> dependency/conflict bundle -> mentalities -> agents -> model -> MCP tools -> coalition -> arena A/B/C/D -> verification -> evidence-gated retry`

## Current implementation

- no fixed agent-count ceiling;
- dynamic coalition based on skill and mentality coverage;
- objective-driven mentality inference when the caller does not pin a profile;
- mentalities: analytical, creative, skeptical, engineering, security, verification, minimalist, research, planning;
- quality, reliability, latency, cost, VRAM, risk and historical scoring;
- deterministic A/B/C/D arena;
- verifier verdicts: `PASS`, `PARTIAL`, `FAIL`, `INCONCLUSIVE`;
- retry only for PARTIAL/INCONCLUSIVE and only when new evidence exists;
- `TASK-YYYYMMDD-####` observability IDs;
- P0-02 adapter for the real `skills_search` payload shape, including dependencies, conflicts and context cost;
- Windows PowerShell 5.1 Shadow certification wrapper.

## Main modules

- `core.py` - coalition, arena and verifier primitives;
- `reasoning.py` - automatic mentality inference;
- `pipeline.py` - skill/model/tool selection, arena and retry policy;
- `adaptive.py` - automatic reasoning-profile entrypoint;
- `skills_mcp.py` - adapter from CLEMENT Skills MCP to orchestration inputs.

## Shadow

```powershell
cd "C:\Users\Shadow\Documents\CLEMENT_STUDIO\04_TOOLS\CLEMENT_STUDIO_ORCHESTRATOR"
git pull --ff-only origin feat/p0-dynamic-orchestrator
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\certify_shadow.ps1"
```

No merge, tag or release is performed by the certification scripts.
