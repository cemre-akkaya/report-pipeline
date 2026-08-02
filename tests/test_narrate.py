import json

from report_pipeline.health import DataHealth, Health
from report_pipeline.narrate import MetricSpec, NarrativeSpec, narrate, summarize
from report_pipeline.payload import Payload


def make_payload(*, revenue=1000.0, revenue_health=Health.OK):
    health = DataHealth()
    health.record("revenue", revenue_health,
                  reason=None if revenue_health == Health.OK else "connector timed out")
    payload = Payload({"revenue": revenue, "data_health": health.as_dict()})
    return payload.seal()


SPEC = NarrativeSpec(metrics=(MetricSpec(key="revenue", label="Revenue"),))


class StubLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.responses[len(self.calls) - 1]


class TestSummarize:
    def test_unavailable_metric_is_null_not_zero_not_omitted(self):
        payload = make_payload(revenue_health=Health.UNAVAILABLE)
        summary = summarize(payload, SPEC)
        entry = summary["metrics"]["revenue"]
        assert entry["value"] is None
        assert entry["status"] == "unavailable"
        assert entry["reason"] == "connector timed out"

    def test_ok_metric_has_real_value(self):
        payload = make_payload(revenue=555.0)
        summary = summarize(payload, SPEC)
        assert summary["metrics"]["revenue"]["value"] == 555.0


class TestNarrativeGuard:
    def test_forbidden_decline_language_triggers_regeneration(self):
        bad = json.dumps({"headline": "Revenue dropped to zero this week",
                          "sections": ["Revenue dropped to zero this week."],
                          "caveats": []})
        good = json.dumps({"headline": "Data quality notice for revenue",
                           "sections": ["We could not measure revenue this period."],
                           "caveats": ["revenue unavailable"]})
        client = StubLLM([bad, good])
        payload = make_payload(revenue_health=Health.UNAVAILABLE)
        result = narrate(payload, client, SPEC)
        assert len(client.calls) == 2  # regenerated once
        assert "dropped" not in result.headline.lower()
        assert result.fallback is False

    def test_recurring_violation_falls_back_to_deterministic_summary(self):
        bad = json.dumps({"headline": "Revenue dropped to zero", "sections": [], "caveats": []})
        client = StubLLM([bad, bad])
        payload = make_payload(revenue_health=Health.UNAVAILABLE)
        result = narrate(payload, client, SPEC)
        assert result.fallback is True
        assert any("unavailable" in c for c in result.caveats)

    def test_worst_unavailable_opens_with_caveat(self):
        good = json.dumps({"headline": "Weekly update", "sections": ["all fine"],
                           "caveats": []})
        client = StubLLM([good])
        payload = make_payload(revenue_health=Health.UNAVAILABLE)
        result = narrate(payload, client, SPEC)
        assert result.sections[0].startswith("Data quality notice")

    def test_healthy_data_no_caveat_injected(self):
        good = json.dumps({"headline": "Weekly update", "sections": ["all fine"],
                           "caveats": []})
        client = StubLLM([good])
        payload = make_payload(revenue_health=Health.OK)
        result = narrate(payload, client, SPEC)
        assert result.caveats == ()

    def test_llm_client_none_returns_deterministic_summary(self):
        payload = make_payload()
        result = narrate(payload, None, SPEC)
        assert result.fallback is True

    def test_llm_exception_is_non_fatal(self):
        class ExplodingLLM:
            def complete(self, system, user):
                raise ConnectionError("down")

        payload = make_payload()
        result = narrate(payload, ExplodingLLM(), SPEC)
        assert result.fallback is True

    def test_malformed_json_falls_back(self):
        client = StubLLM(["not json at all"])
        payload = make_payload()
        result = narrate(payload, client, SPEC)
        assert result.fallback is True
