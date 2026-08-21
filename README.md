# CLEMENT_STUDIO_ORCHESTRATOR

P0-04 - dynamic orchestrator for CLEMENT STUDIO.

## Pipeline

`intent -> skills -> agents -> models -> MCP -> mentalities -> coalitions -> arena -> execution -> verification -> retry`

The orchestrator does not impose a fixed agent count. Coalitions are built from required semantic capabilities and mentalities, while real Skills Hub identifiers remain selected resources rather than replacing agent capabilities.

## Global P0 certification

Shadow certification is launched with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\certify_global_p0.ps1
```

The V2 global certifier is fail-closed and deliberately separates two evidence planes:

- **P0-03 route evidence**: HTTP 200, resolved provider/model, provider usage, accounting and cache status;
- **P0-04 execution evidence**: the expected strategy marker returned by the routed model.

A routed request may therefore be P0-03 PASS while its P0-04 application response is incomplete. In that case the certifier may retry only the execution probe, up to three total attempts per strategy, and every real retry remains included in token/cost accounting. A route/accounting/cache failure is never hidden by retry.

The global run verifies the 905-entry Skills Hub, the exact nine-tool READ-ONLY Skills MCP contract, Odysseus health, the dynamic coalition and A/B/C/D arena, real OmniRoute calls, final provider/model evidence, accounting, execution markers and the final verifier.
