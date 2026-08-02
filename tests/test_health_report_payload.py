import pytest

from report_pipeline.health import DataHealth, Health, worse
from report_pipeline.payload import Payload, PayloadFrozenError
from report_pipeline.report import pct_change, rank_by_delta, rollup, safe_div


class TestHealth:
    def test_worse_ranking(self):
        assert worse(Health.OK, Health.UNAVAILABLE) == Health.UNAVAILABLE
        assert worse(Health.STALE, Health.OK) == Health.STALE
        assert worse(Health.PARTIAL, Health.STALE) == Health.PARTIAL

    def test_worst_across_entries(self):
        health = DataHealth()
        health.record("web_traffic", Health.UNAVAILABLE, reason="auth refresh failed (401)")
        health.record("orders", Health.OK)
        assert health.worst() is Health.UNAVAILABLE

    def test_degraded_sources(self):
        health = DataHealth()
        health.record("a", Health.OK)
        health.record("b", Health.STALE)
        health.record("c", Health.UNAVAILABLE)
        assert set(health.degraded_sources()) == {"b", "c"}

    def test_roundtrip_dict(self):
        health = DataHealth()
        health.record("a", Health.PARTIAL, reason="some rows missing")
        restored = DataHealth.from_dict(health.as_dict())
        assert restored.status("a") == Health.PARTIAL
        assert restored.reason("a") == "some rows missing"

    def test_empty_health_worst_is_not_applicable(self):
        assert DataHealth().worst() == Health.NOT_APPLICABLE


class TestPctChangeSafeDiv:
    def test_pct_change_normal(self):
        assert pct_change(110, 100) == pytest.approx(0.10)

    def test_pct_change_zero_base_is_none_never_inf(self):
        assert pct_change(10, 0) is None

    def test_pct_change_missing_base_is_none(self):
        assert pct_change(10, None) is None

    def test_safe_div_zero_denominator_is_none_never_zero(self):
        assert safe_div(10, 0) is None

    def test_safe_div_normal(self):
        assert safe_div(10, 4) == 2.5


class TestRollupRank:
    def test_rollup_by_key(self):
        rows = [{"region": "eu", "revenue": 10}, {"region": "eu", "revenue": 5},
               {"region": "us", "revenue": 3}]
        result = rollup(rows, by="region", agg=sum, value_key="revenue")
        assert result == {"eu": 15, "us": 3}

    def test_rank_by_delta_missing_previous_is_none_not_fabricated(self):
        current = {"a": 100, "b": 50}
        previous = {"a": 80}
        ranked = rank_by_delta(current, previous)
        by_key = dict(ranked)
        assert by_key["a"] == pytest.approx(0.25)
        assert by_key["b"] is None

    def test_rank_by_delta_largest_move_first(self):
        current = {"a": 110, "b": 200}
        previous = {"a": 100, "b": 100}
        ranked = rank_by_delta(current, previous)
        assert ranked[0][0] == "b"  # 100% move beats 10%


class TestPayload:
    def test_set_then_seal_blocks_mutation(self):
        payload = Payload()
        payload.set("a", 1)
        payload.seal()
        with pytest.raises(PayloadFrozenError):
            payload.set("b", 2)

    def test_frozen_copy_is_independent(self):
        payload = Payload({"a": [1, 2, 3]})
        frozen = payload.frozen_copy()
        payload._data["a"].append(4)
        assert frozen["a"] == [1, 2, 3]

    def test_mapping_interface(self):
        payload = Payload({"a": 1, "b": 2})
        assert dict(payload) == {"a": 1, "b": 2}
        assert len(payload) == 2
        assert "a" in payload

    def test_json_roundtrip_catches_bad_value(self):
        payload = Payload({"a": object()})
        with pytest.raises(TypeError):
            payload.assert_json_roundtrip()

    def test_json_roundtrip_allows_dates(self):
        from datetime import date

        payload = Payload({"d": date(2031, 1, 1)})
        payload.assert_json_roundtrip()  # must not raise
