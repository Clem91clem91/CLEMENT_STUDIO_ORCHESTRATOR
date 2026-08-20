from clement_orchestrator.skills_mcp import skill_matches_from_search


def test_converts_real_p002_search_shape():
    payload = {
        "query": "agent orchestration",
        "total": 1,
        "matches": [
            {
                "score": 145,
                "reasons": ["name-tokens:2"],
                "skill": {
                    "id": "agent-orchestration",
                    "name": "Agent Orchestration",
                    "dependencies": ["planning"],
                    "conflicts": ["legacy-orchestration"],
                    "estimated_context_cost": 900,
                },
            }
        ],
    }
    matches = skill_matches_from_search(payload)
    assert len(matches) == 1
    assert matches[0].skill_id == "agent-orchestration"
    assert matches[0].score == 1.45
    assert matches[0].dependencies == ("planning",)
    assert matches[0].conflicts == ("legacy-orchestration",)
    assert matches[0].estimated_context_cost == 900


def test_invalid_or_empty_payload_is_safe():
    assert skill_matches_from_search({}) == ()
    assert skill_matches_from_search({"matches": [None, {"score": 1}]}) == ()
