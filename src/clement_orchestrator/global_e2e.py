from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


EXPECTED_SKILLS_MCP_TOOLS = frozenset(
    {
        "skills_status",
        "skills_list",
        "skills_search",
        "skills_get",
        "skills_match",
        "skills_dependencies",
        "skills_conflicts",
        "skills_validate",
        "skills_bundle_plan",
    }
)


@dataclass(frozen=True)
class RouteEvidence:
    strategy: str
    http_status: int
    expected_marker: str
    marker_observed: bool
    response_text: str
    requested_alias: str
    final_provider: str | None
    final_model: str | None
    decision: str | None
    cache_status: str | None
    latency_ms: float | None
    technical_tokens: int | None
    provider_tokens_in: int | None
    provider_tokens_out: int | None
    provider_billable_tokens: int | None
    reported_cost_eur: float | None
    omniroute_request_id: str | None
    correlation_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def route_complete(self) -> bool:
        """True when P0-03 routing/accounting evidence is structurally complete.

        The application-level strategy marker deliberately does not participate
        in this gate. A provider may return an empty or malformed assistant
        message while OmniRoute still routed the request correctly and exposed
        provider/model/usage evidence. That is a P0-04 execution concern.
        """

        return (
            self.http_status == 200
            and bool(self.final_provider)
            and bool(self.final_model)
            and self.provider_billable_tokens is not None
            and self.technical_tokens is not None
        )

    @property
    def execution_complete(self) -> bool:
        """True when routing evidence is complete and the P0-04 marker arrived."""

        return self.route_complete and self.marker_observed

    @property
    def complete(self) -> bool:
        """Backward-compatible alias for the original strict execution gate."""

        return self.execution_complete


def strategy_marker(strategy: str) -> str:
    normalized = "".join(ch for ch in str(strategy).upper() if ch.isalnum() or ch in {"_", "-"})
    if not normalized:
        normalized = "UNKNOWN"
    return f"CLEMENT_P0_STRATEGY_{normalized}_OK"


def _normalized_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    return {str(key).strip().lower(): str(value).strip() for key, value in headers.items()}


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _message_text(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, Mapping):
        return ""
    message = first.get("message")
    if not isinstance(message, Mapping):
        return ""
    return str(message.get("content") or "")


def _technical_tokens(payload: Mapping[str, Any]) -> int | None:
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        return None
    return _as_int(usage.get("total_tokens"))


def extract_route_evidence(
    *,
    strategy: str,
    requested_alias: str,
    http_status: int,
    headers: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> RouteEvidence:
    normalized = _normalized_headers(headers)
    marker = strategy_marker(strategy)
    response_text = _message_text(payload)
    tokens_in = _as_int(normalized.get("x-omniroute-tokens-in"))
    tokens_out = _as_int(normalized.get("x-omniroute-tokens-out"))
    provider_billable_tokens = None
    if tokens_in is not None and tokens_out is not None:
        provider_billable_tokens = max(0, tokens_in) + max(0, tokens_out)

    final_model = normalized.get("x-omniroute-model") or str(payload.get("model") or "").strip() or None

    return RouteEvidence(
        strategy=strategy,
        http_status=int(http_status),
        expected_marker=marker,
        marker_observed=response_text.strip() == marker,
        response_text=response_text,
        requested_alias=requested_alias,
        final_provider=normalized.get("x-omniroute-provider") or None,
        final_model=final_model,
        decision=normalized.get("x-omniroute-decision") or None,
        cache_status=normalized.get("x-omniroute-cache") or None,
        latency_ms=_as_float(normalized.get("x-omniroute-latency-ms")),
        technical_tokens=_technical_tokens(payload),
        provider_tokens_in=tokens_in,
        provider_tokens_out=tokens_out,
        provider_billable_tokens=provider_billable_tokens,
        reported_cost_eur=_as_float(normalized.get("x-omniroute-response-cost")),
        omniroute_request_id=normalized.get("x-omniroute-request-id") or None,
        correlation_id=normalized.get("x-correlation-id") or None,
    )


def evidence_verdict(checks: Mapping[str, bool | None]) -> tuple[str, tuple[str, ...]]:
    unresolved = tuple(sorted(name for name, value in checks.items() if value is None))
    failed = tuple(sorted(name for name, value in checks.items() if value is False))
    if failed:
        return "FAIL", tuple(f"failed:{name}" for name in failed)
    if unresolved:
        return "INCONCLUSIVE", tuple(f"unresolved:{name}" for name in unresolved)
    return "PASS", ("all_required_global_checks_passed",)
