"""Small per-case usage snapshots; never estimate tokens from generated text."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from uuid import uuid4

TOKEN_FIELDS = ("input_tokens", "output_tokens", "cached_tokens", "total_tokens")


def _field(value, key, default=None):
    return (
        value.get(key, default)
        if isinstance(value, Mapping)
        else getattr(value, key, default)
    )


def _count(value, *keys):
    for key in keys:
        number = _field(value, key)
        if type(number) is int and 0 <= number < 2**63:
            return number
    return None


def _extract(usage):
    other = _count(usage, "input_other")
    cached = _count(usage, "input_cached")
    if other is not None:
        incoming = other + cached if cached is not None else None
        outgoing = _count(usage, "output")
        total = (
            incoming + outgoing
            if incoming is not None and outgoing is not None
            else None
        )
    else:
        incoming = _count(
            usage,
            "prompt_tokens",
            "input_tokens",
            "prompt_token_count",
            "promptTokenCount",
        )
        outgoing = _count(
            usage,
            "completion_tokens",
            "output_tokens",
            "candidates_token_count",
            "candidatesTokenCount",
        )
        total = _count(usage, "total_tokens", "total_token_count", "totalTokenCount")
        cached = _count(
            usage,
            "cache_read_input_tokens",
            "cached_content_token_count",
            "cachedContentTokenCount",
        )
        for details in ("prompt_tokens_details", "input_tokens_details"):
            if cached is None:
                cached = _count(_field(usage, details), "cached_tokens")
        # Anthropic input excludes cache read and creation; OpenAI input includes cache.
        if incoming is not None and (
            _field(usage, "cache_read_input_tokens") is not None
            or _field(usage, "cache_creation_input_tokens") is not None
        ):
            incoming += (cached or 0) + (
                _count(usage, "cache_creation_input_tokens") or 0
            )
        if outgoing is not None and (
            _field(usage, "candidates_token_count") is not None
            or _field(usage, "candidatesTokenCount") is not None
        ):
            outgoing += _count(usage, "thoughts_token_count", "thoughtsTokenCount") or 0
        if total is None and incoming is not None and outgoing is not None:
            total = incoming + outgoing
    return dict(zip(TOKEN_FIELDS, (incoming, outgoing, cached, total)))


def extract_usage(response):
    native = _field(response, "usage")
    raw = _field(response, "raw_completion")
    # Some adapters substitute an all-zero TokenUsage when raw usage is absent.
    if raw is not None and all(
        _count(native, key) == 0 for key in ("input_other", "input_cached", "output")
    ):
        # When a raw response exists, its reported counters distinguish real zero
        # from a compatibility adapter's zero placeholder (including empty usage).
        native = None
    for candidate in (
        native,
        _field(raw, "usage"),
        _field(raw, "usage_metadata", _field(raw, "usageMetadata")),
    ):
        values = _extract(candidate)
        if any(value is not None for value in values.values()):
            return values
    return dict.fromkeys(TOKEN_FIELDS)


def usage_snapshot(*, scope="local", response=None, provider_id=""):
    """One entry per observed request; external Agent usage is explicitly unknown."""
    if scope == "local":
        return {"status": "not_used", **dict.fromkeys(TOKEN_FIELDS, 0), "calls": []}
    values = extract_usage(response)
    status = (
        "reported"
        if all(
            values[k] is not None
            for k in ("input_tokens", "output_tokens", "total_tokens")
        )
        else "partial"
        if any(v is not None for v in values.values())
        else "unknown"
    )
    if scope == "agent_context":
        status = "external"
    call = {
        "id": uuid4().hex,
        "scope": scope,
        "status": status,
        **values,
    }
    if provider_id:
        call["provider_id"] = provider_id
    return {"status": status, **values, "calls": [call]}


def merge_usage(previous, incoming):
    """Preserve actual repeat-request costs while the case itself stays deduplicated."""
    if not previous:
        # Old records have unmeasured costs; a new request cannot reconstruct them.
        previous = usage_snapshot(scope="historical")
    calls = {c["id"]: c for usage in (previous, incoming) for c in usage["calls"]}
    calls = list(calls.values())
    if not calls:
        return usage_snapshot()
    values = {
        key: sum(c[key] for c in calls)
        if all(c[key] is not None for c in calls)
        else None
        for key in TOKEN_FIELDS
    }
    states = {c["status"] for c in calls}
    status = (
        "reported"
        if states == {"reported"}
        else "external"
        if states == {"external"}
        else "partial"
        if any(c["status"] in ("reported", "partial") for c in calls)
        else "unknown"
    )
    return deepcopy({"status": status, **values, "calls": calls})


def case_token_summary(record):
    """Known total for ranking, with incomplete cases kept visible separately."""
    summary = {
        "total_tokens": 0,
        "token_known_cases": 0,
        "token_unknown_cases": 0,
        "token_unrecorded_cases": 0,
    }
    usage = record.get("token_usage")
    if not isinstance(usage, Mapping):
        summary["token_unrecorded_cases"] = 1
        return summary
    total = _count(usage, "total_tokens")
    if total is not None:
        summary.update(total_tokens=total, token_known_cases=1)
        return summary
    # A merged case may have measured calls even though its overall total is
    # unknown. Sum those calls once, without adding the case aggregate again.
    summary["token_unknown_cases"] = 1
    calls, seen = usage.get("calls"), set()
    if isinstance(calls, list):
        for call in calls:
            identity = _field(call, "id")
            if isinstance(identity, str) and identity:
                if identity in seen:
                    continue
                seen.add(identity)
            total = _count(call, "total_tokens")
            if total is not None:
                summary["total_tokens"] += total
                summary["token_known_cases"] = 1
    return summary
