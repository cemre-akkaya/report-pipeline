from report_pipeline.collect import CollectorResult, retry, run_collectors
from report_pipeline.emit import EmitContext, EmitResult, build_run_result, run_outputs
from report_pipeline.health import Health
from report_pipeline.payload import Payload
from report_pipeline.window import Window

from .conftest import FakeCollector


class TestRunCollectors:
    def test_one_collector_failing_never_aborts_the_run(self):
        good = FakeCollector("good", schedule={None: (1.0, Health.OK)})
        bad = FakeCollector("bad", schedule={}, raises_on={Window.day(__import__("datetime").date(2031, 1, 1)).start})
        window = Window.day(__import__("datetime").date(2031, 1, 1))
        results = run_collectors([good, bad], window)
        assert results["good"].health == Health.OK
        assert results["bad"].health == Health.UNAVAILABLE
        assert "failed" in results["bad"].reason

    def test_default_max_workers_is_sequential_deterministic(self):
        from datetime import date

        order = []

        class OrderTrackingCollector:
            def __init__(self, name):
                self.name = name

            def collect(self, window):
                order.append(self.name)
                return CollectorResult(data={}, health=Health.OK,
                                       fetched_at=__import__("datetime").datetime.now(
                                           __import__("datetime").timezone.utc
                                       ), source=self.name)

        collectors = [OrderTrackingCollector(f"c{i}") for i in range(5)]
        run_collectors(collectors, Window.day(date(2031, 1, 1)))
        assert order == ["c0", "c1", "c2", "c3", "c4"]


class TestRetry:
    def test_retries_then_succeeds(self):
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("transient")
            return "ok"

        result = retry(flaky, attempts=5, _sleep=lambda s: None, _random=lambda: 0.0)
        assert result == "ok"
        assert attempts["n"] == 3

    def test_exhausts_and_raises(self):
        def always_fails():
            raise ConnectionError("down")

        try:
            retry(always_fails, attempts=2, _sleep=lambda s: None, _random=lambda: 0.0)
            raised = False
        except ConnectionError:
            raised = True
        assert raised


class TestFanOut:
    def test_chat_down_does_not_stop_spreadsheet(self):
        class BrokenOutput:
            name = "chat"

            def emit(self, payload, ctx):
                raise RuntimeError("webhook 500")

        class WorkingOutput:
            name = "sheet"

            def emit(self, payload, ctx):
                return EmitResult(name=self.name, ok=True)

        payload = Payload({"a": 1}).seal()
        results = run_outputs([BrokenOutput(), WorkingOutput()], payload)
        by_name = {r.name: r for r in results}
        assert by_name["chat"].ok is False
        assert by_name["sheet"].ok is True

    def test_run_result_ok_only_if_all_succeed(self):
        class Failing:
            name = "x"

            def emit(self, payload, ctx):
                return EmitResult(name=self.name, ok=False, error="boom")

        payload = Payload({}).seal()
        run_result = build_run_result([Failing()], payload, EmitContext())
        assert run_result.ok is False

    def test_each_output_receives_a_sealed_independent_copy(self):
        seen = []

        class Peeker:
            name = "peek"

            def emit(self, payload, ctx):
                seen.append(payload.to_dict())
                return EmitResult(name=self.name, ok=True)

        payload = Payload({"nested": {"x": 1}})
        payload.set("extra", "value")
        payload.seal()
        run_outputs([Peeker(), Peeker()], payload)
        assert seen[0] == seen[1] == {"nested": {"x": 1}, "extra": "value"}
