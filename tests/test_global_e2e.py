from clement_orchestrator.global_e2e import (
    EXPECTED_SKILLS_MCP_TOOLS,
    evidence_verdict,
    extract_route_evidence,
    strategy_marker,
)


def test_expected_mcp_contract_is_exactly_nine_tools():
    assert len(EXPECTED_SKILLS_MCP_TOOLS) == 9
    assert "skills_status" in EXPECTED_SKILLS_MCP_TOOLS
    assert "skills_bundle_plan" in EXPECTED_SKILLS_MCP_TOOLS


def test_route_evidence_separates_technical_and_provider_usage():
    marker = strategy_marker("B")
    evidence = extract_route_evidence(
        strategy="B",
        requested_alias="auto/best-coding",
        http_status=200,
        headers={
            "x-omniroute-provider": "antigravity",
            "x-omniroute-model": "gemini-3.6-flash-high",
            "x-omniroute-decision": "strategy=auto; provider=antigravity; latency_ms=1152",
            "x-omniroute-cache": "MISS",
            "x-omniroute-latency-ms": "1152",
            "x-omniroute-tokens-in": "91",
            "x-omniroute-tokens-out": "10",
            "x-omniroute-response-cost": "0.0000000000",
            "x-omniroute-request-id": "request-1",
            "x-correlation-id": "correlation-1",
        },
        payload={
            "model": "gemini-3.6-flash-high",
            "choices": [{"message": {"content": marker}}],
            "usage": {"prompt_tokens": 91, "completion_tokens": 10, "total_tokens": 186},
        },
    )
    assert evidence.complete is True
    assert evidence.final_provider == "antigravity"
    assert evidence.final_model == "gemini-3.6-flash-high"
    assert evidence.technical_tokens == 186
    assert evidence.provider_billable_tokens == 101
    assert evidence.reported_cost_eur == 0.0
    assert evidence.marker_observed is True


def test_route_evidence_is_incomplete_without_provider_headers():
    marker = strategy_marker("A")
    evidence = extract_route_evidence(
        strategy="A",
        requested_alias="auto/best-coding",
        http_status=200,
        headers={},
        payload={
            "model": "fallback-model",
            "choices": [{"message": {"content": marker}}],
            "usage": {"total_tokens": 20},
        },
    )
    assert evidence.complete is False
    assert evidence.final_provider is None
    assert evidence.provider_billable_tokens is None


def test_evidence_verdict_is_fail_closed():
    assert evidence_verdict({"a": True, "b": True})[0] == "PASS"
    assert evidence_verdict({"a": True, "b": None})[0] == "INCONCLUSIVE"
    assert evidence_verdict({"a": True, "b": False})[0] == "FAIL"
