"""OpenRouter pricing lookup for cost reconciliation.

The claude CLI's ``total_cost_usd`` is computed from Anthropic list prices.
When the harness routes claude-code through OpenRouter (``ANTHROPIC_BASE_URL``
pointing at openrouter.ai), actual billing follows OpenRouter's per-model
pricing instead. OpenRouter's generation API would give the exact billed
amount, but it needs per-request generation ids that the claude CLI does not
expose — so we reconcile by recomputing cost from the run's token counts and
OpenRouter's published pricing (the same numbers OpenRouter bills from).
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Optional

from agent_skill_eval.models import TimingData

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_FETCH_TIMEOUT_SECONDS = 10

# model id -> pricing dict, populated once per process. The models endpoint
# is public (no API key) but we still never want it on a hot path.
_pricing_cache: Optional[dict[str, dict]] = None


def fetch_openrouter_pricing() -> dict[str, dict]:
    """Return ``{model_id: pricing}`` from the OpenRouter models endpoint.

    Cached for the process lifetime. Raises on network/parse errors; callers
    that must not fail (the harness) wrap this in try/except.
    """
    global _pricing_cache
    if _pricing_cache is not None:
        return _pricing_cache

    with urllib.request.urlopen(OPENROUTER_MODELS_URL, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    pricing: dict[str, dict] = {}
    for model in data.get("data", []):
        model_id = model.get("id")
        if model_id and isinstance(model.get("pricing"), dict):
            pricing[model_id] = model["pricing"]
    _pricing_cache = pricing
    return pricing


def openrouter_slug_candidates(model: str) -> list[str]:
    """Candidate OpenRouter slugs for an Anthropic model id.

    The claude CLI takes Anthropic ids (``claude-haiku-4-5-20251001``) while
    OpenRouter keys pricing by its own slugs (``anthropic/claude-haiku-4.5``).
    Heuristic: drop the date suffix, then also try dotted version numbers.
    Short CLI aliases like ``haiku`` resolve server-side and cannot be mapped.
    """
    model = model.strip()
    if not model:
        return []
    if "/" in model:
        return [model]

    base = re.sub(r"-\d{8}$", "", model)
    dotted = re.sub(r"(\d)-(\d)", r"\1.\2", base)

    candidates = []
    for name in (model, base, dotted):
        slug = f"anthropic/{name}"
        if slug not in candidates:
            candidates.append(slug)
    return candidates


def _find_pricing(pricing: dict[str, dict], model: str) -> Optional[dict]:
    for candidate in openrouter_slug_candidates(model):
        if candidate in pricing:
            return pricing[candidate]
    return None


def _rate(entry: dict, field: str) -> float:
    try:
        return float(entry.get(field) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def reconcile_claude_cost(timing: TimingData, model: Optional[str]) -> Optional[float]:
    """Recompute a run's USD cost from OpenRouter pricing, or None.

    Returns None when the model cannot be mapped to an OpenRouter slug, the
    pricing fetch fails, or pricing has no usable rates — the caller keeps
    the CLI's own estimate in those cases.
    """
    if not model:
        return None
    if timing.total_tokens <= 0 and timing.cached_tokens <= 0 and timing.cache_creation_tokens <= 0:
        return None

    try:
        pricing = fetch_openrouter_pricing()
    except Exception:
        return None

    entry = _find_pricing(pricing, model)
    if not entry:
        return None

    prompt = _rate(entry, "prompt")
    completion = _rate(entry, "completion")
    if prompt <= 0 and completion <= 0:
        return None

    return (
        timing.input_tokens * prompt
        + timing.output_tokens * completion
        + timing.cached_tokens * _rate(entry, "input_cache_read")
        + timing.cache_creation_tokens * _rate(entry, "input_cache_write")
    )
