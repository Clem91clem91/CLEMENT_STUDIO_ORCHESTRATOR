from clement_orchestrator import (
    AgentProfile,
    ArenaCandidate,
    Mentality,
    TaskContext,
    build_coalition,
    rank_arena,
    verify_result,
)


def agent(name: str, skills: set[str], mentalities: set[Mentality] | None = None) -> AgentProfile:
    return AgentProfile(
        name=name,
        skills=frozenset(skills),
        mentalities=frozenset(mentalities or set()),
        quality=0.8,
        reliability=0.8,
        historical_score=0.7,
        risk=0.2,
    )


def test_coalition_has_no_fixed_agent_limit() -> None:
    skills = {f"skill-{i}" for i in range(12)}
    agents = [agent(f"agent-{i}", {f"skill-{i}"}) for i in range(12)]
    result = build_coalition(TaskContext("wide task", frozenset(skills)), agents)
    assert result.complete is True
    assert len(result.agents) == 12


def test_coalition_prefers_multi_skill_agent() -> None:
    task = TaskContext("task", frozenset({"a", "b", "c"}))
    agents = [
        agent("specialist-a", {"a"}),
        agent("specialist-b", {"b"}),
        agent("combo", {"a", "b", "c"}),
    ]
    result = build_coalition(task, agents)
    assert result.complete is True
    assert [a.name for a in result.agents] == ["combo"]


def test_coalition_reports_missing_skill() -> None:
    result = build_coalition(
        TaskContext("task", frozenset({"a", "missing"})),
        [agent("a", {"a"})],
    )
    assert result.complete is False
    assert "missing" not in result.covered_skills


def test_required_mentality_adds_specialist() -> None:
    task = TaskContext(
        "secure design",
        frozenset({"design"}),
        required_mentalities=frozenset({Mentality.SECURITY}),
    )
    result = build_coalition(
        task,
        [
            agent("designer", {"design"}),
            agent("security", set(), {Mentality.SECURITY}),
        ],
    )
    assert result.complete is True
    assert {a.name for a in result.agents} == {"designer", "security"}


def test_arena_prefers_quality_and_reliability() -> None:
    candidates = [
        ArenaCandidate("A", quality=0.9, reliability=0.9, latency_ms=500, cost_eur=0.0, risk=0.1),
        ArenaCandidate("B", quality=0.5, reliability=0.5, latency_ms=50, cost_eur=0.0, risk=0.1),
    ]
    ranked = rank_arena(candidates)
    assert ranked[0].name == "A"


def test_arena_is_deterministic_on_tie() -> None:
    a = ArenaCandidate("alpha", 0.8, 0.8, 100, 0.0, 0.2)
    b = ArenaCandidate("beta", 0.8, 0.8, 100, 0.0, 0.2)
    assert [c.name for c in rank_arena([b, a])] == ["alpha", "beta"]


def test_verifier_pass() -> None:
    result = verify_result(checks=[True, True, True], quality_score=0.9)
    assert result.verdict == "PASS"


def test_verifier_partial_for_unknown_check() -> None:
    result = verify_result(checks=[True, None], quality_score=0.9)
    assert result.verdict == "PARTIAL"


def test_verifier_fail_for_failed_check() -> None:
    result = verify_result(checks=[True, False], quality_score=0.95)
    assert result.verdict == "FAIL"


def test_verifier_inconclusive_without_evidence() -> None:
    assert verify_result(checks=[], quality_score=0.9).verdict == "INCONCLUSIVE"


def test_verifier_partial_for_low_quality() -> None:
    assert verify_result(checks=[True], quality_score=0.5).verdict == "PARTIAL"
