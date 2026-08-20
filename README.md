# CLEMENT_STUDIO_ORCHESTRATOR

P0-04 - orchestrateur dynamique pour CLEMENT STUDIO.

## Pipeline cible

`intents -> skills -> agents -> models -> MCP -> mentalities -> coalitions -> arena -> execution -> verification -> retry`

## Principes

- aucune limite fixe du nombre d'agents ;
- coalition construite selon la couverture des skills et mentalites requises ;
- prise en compte de VRAM, latence, cout, qualite, risque, fiabilite et historique ;
- mentalites supportees : analytical, creative, skeptical, engineering, security, verification, minimalist, research, planning ;
- arena comparative de strategies A/B/C/D ;
- classement deterministe ;
- verifier final : `PASS`, `PARTIAL`, `FAIL`, `INCONCLUSIVE` ;
- retry ulterieur pilote par les preuves et non par une boucle aveugle.

## Prototype v0.1.0

Le premier noyau fournit :

- `build_coalition()` : selection dynamique sans plafond d'agents ;
- `rank_arena()` : classement de strategies par utilite composite ;
- `verify_result()` : verdict de verification explicite ;
- structures `TaskContext`, `AgentProfile`, `Coalition`, `ArenaCandidate`.

## Developpement

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Aucun merge, tag ou release n'est implique par cette branche feature.
