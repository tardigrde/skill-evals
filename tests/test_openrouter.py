from __future__ import annotations

import pytest

import agent_skill_eval.openrouter as openrouter
from agent_skill_eval.harnesses import ClaudeCodeHarness
from agent_skill_eval.models import TimingData
from agent_skill_eval.openrouter import openrouter_slug_candidates, reconcile_claude_cost

HAIKU_PRICING = {
    "anthropic/claude-haiku-4.5": {
        "prompt": "0.000001",
        "completion": "0.000005",
        "input_cache_read": "0.0000001",
        "input_cache_write": "0.00000125",
    }
}


@pytest.fixture(autouse=True)
def clear_pricing_cache(monkeypatch):
    monkeypatch.setattr(openrouter, "_pricing_cache", None)


@pytest.fixture
def pinned_pricing(monkeypatch):
    monkeypatch.setattr(openrouter, "_pricing_cache", HAIKU_PRICING)


class TestSlugCandidates:
    def test_dated_anthropic_id_maps_to_dotted_slug(self):
        candidates = openrouter_slug_candidates("claude-haiku-4-5-20251001")
        assert "anthropic/claude-haiku-4.5" in candidates

    def test_undated_id_maps_to_dotted_slug(self):
        candidates = openrouter_slug_candidates("claude-sonnet-4-6")
        assert "anthropic/claude-sonnet-4.6" in candidates

    def test_legacy_version_first_id(self):
        candidates = openrouter_slug_candidates("claude-3-5-sonnet-20241022")
        assert "anthropic/claude-3.5-sonnet" in candidates

    def test_existing_slug_passes_through(self):
        assert openrouter_slug_candidates("anthropic/claude-haiku-4.5") == ["anthropic/claude-haiku-4.5"]

    def test_empty_model(self):
        assert openrouter_slug_candidates("") == []


class TestReconcileClaudeCost:
    def test_computes_cost_from_token_counts(self, pinned_pricing):
        timing = TimingData(
            input_tokens=1000,
            output_tokens=200,
            cached_tokens=500,
            cache_creation_tokens=100,
            total_tokens=1200,
        )
        cost = reconcile_claude_cost(timing, "claude-haiku-4-5-20251001")
        # 1000*1e-6 + 200*5e-6 + 500*1e-7 + 100*1.25e-6
        assert cost == pytest.approx(0.001 + 0.001 + 0.00005 + 0.000125)

    def test_unknown_model_returns_none(self, pinned_pricing):
        timing = TimingData(input_tokens=10, total_tokens=10)
        assert reconcile_claude_cost(timing, "haiku") is None

    def test_no_model_returns_none(self, pinned_pricing):
        timing = TimingData(input_tokens=10, total_tokens=10)
        assert reconcile_claude_cost(timing, None) is None

    def test_zero_tokens_returns_none(self, pinned_pricing):
        assert reconcile_claude_cost(TimingData(), "claude-haiku-4-5-20251001") is None

    def test_fetch_failure_returns_none(self, monkeypatch):
        def boom():
            raise OSError("network down")

        monkeypatch.setattr(openrouter, "fetch_openrouter_pricing", boom)
        timing = TimingData(input_tokens=10, total_tokens=10)
        assert reconcile_claude_cost(timing, "claude-haiku-4-5-20251001") is None

    def test_zero_rate_pricing_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            openrouter,
            "_pricing_cache",
            {"anthropic/claude-haiku-4.5": {"prompt": "0", "completion": "0"}},
        )
        timing = TimingData(input_tokens=10, total_tokens=10)
        assert reconcile_claude_cost(timing, "claude-haiku-4-5-20251001") is None


class TestClaudeCodeFinalizeTiming:
    def test_reconciles_when_routed_through_openrouter(self, tmp_path, monkeypatch, pinned_pricing):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
        harness = ClaudeCodeHarness(tmp_path, model="claude-haiku-4-5-20251001")
        timing = TimingData(input_tokens=1000, output_tokens=200, total_tokens=1200, cost_usd=0.05)

        harness.finalize_timing(timing)

        assert timing.cost_usd == pytest.approx(0.002)
        assert timing.cost_usd_cli == pytest.approx(0.05)
        assert timing.cost_usd_source == "openrouter-pricing"

    def test_marks_unreconciled_when_pricing_lookup_fails(self, tmp_path, monkeypatch, pinned_pricing):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
        harness = ClaudeCodeHarness(tmp_path, model="haiku")
        timing = TimingData(input_tokens=1000, total_tokens=1000, cost_usd=0.05)

        harness.finalize_timing(timing)

        assert timing.cost_usd == pytest.approx(0.05)
        assert timing.cost_usd_cli is None
        assert timing.cost_usd_source == "cli-unreconciled"

    def test_keeps_cli_cost_off_openrouter(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        harness = ClaudeCodeHarness(tmp_path, model="claude-haiku-4-5-20251001")
        timing = TimingData(input_tokens=1000, total_tokens=1000, cost_usd=0.05)

        harness.finalize_timing(timing)

        assert timing.cost_usd == pytest.approx(0.05)
        assert timing.cost_usd_source == "cli"

    def test_explicit_base_url_takes_precedence(self, tmp_path, monkeypatch, pinned_pricing):
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        harness = ClaudeCodeHarness(
            tmp_path,
            model="claude-haiku-4-5-20251001",
            base_url="https://openrouter.ai/api",
        )
        timing = TimingData(input_tokens=1000, output_tokens=0, total_tokens=1000, cost_usd=0.05)

        harness.finalize_timing(timing)

        assert timing.cost_usd_source == "openrouter-pricing"
        assert timing.cost_usd == pytest.approx(0.001)
