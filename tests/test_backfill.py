"""The crown-jewel test suite, table-driven over a FakeCollector and an
in-memory store."""

from datetime import UTC, date, datetime, timedelta

from report_pipeline.backfill import Cell, verify_and_backfill
from report_pipeline.health import Health

from .conftest import FakeCollector

TODAY = date(2031, 4, 10)


class InMemoryStore:
    def __init__(self):
        self._cells: dict[tuple[str, date], Cell] = {}

    def get(self, source, day):
        return self._cells.get((source, day))

    def put(self, cell: Cell):
        self._cells[(cell.source, cell.date)] = cell

    def get_range(self, source, start, end):
        return {
            day: cell for (src, day), cell in self._cells.items()
            if src == source and start <= day <= end
        }

    def seed(self, source, day, value, health=Health.OK, written_at=None):
        self.put(Cell(source=source, date=day, value=value, health=health,
                     written_at=written_at or datetime.now(UTC)))


def seeded_store(days_back: int = 14, *, value=100.0) -> InMemoryStore:
    store = InMemoryStore()
    for n in range(days_back):
        store.seed("orders", TODAY - timedelta(days=n), value)
    return store


class TestBackfillTable:
    def test_missing_date_is_repaired(self):
        store = seeded_store()
        # blow away one cell entirely
        del store._cells[("orders", TODAY - timedelta(days=3))]
        collector = FakeCollector("orders", schedule={None: (55.0, Health.OK)})
        report = verify_and_backfill(store, [collector], days=14, today=TODAY)
        assert (TODAY - timedelta(days=3)) in [d for _, d in report.repaired]
        assert store.get("orders", TODAY - timedelta(days=3)).value == 55.0

    def test_zero_on_never_zero_metric_is_repaired(self):
        store = seeded_store()
        store.seed("orders", TODAY - timedelta(days=2), 0.0)
        collector = FakeCollector("orders", schedule={None: (42.0, Health.OK)})
        report = verify_and_backfill(
            store, [collector], days=14, today=TODAY,
            never_zero_sources=frozenset({"orders"}),
        )
        assert (TODAY - timedelta(days=2)) in [d for _, d in report.repaired]

    def test_real_zero_on_normal_metric_is_not_touched(self):
        """The false-positive case, asserted explicitly."""
        store = seeded_store()
        store.seed("orders", TODAY - timedelta(days=2), 0.0)
        collector = FakeCollector("orders", schedule={None: (999.0, Health.OK)})
        report = verify_and_backfill(
            store, [collector], days=14, today=TODAY,
            never_zero_sources=frozenset(),  # NOT declared never_zero
        )
        assert (TODAY - timedelta(days=2)) not in [d for _, d in report.repaired]
        assert store.get("orders", TODAY - timedelta(days=2)).value == 0.0

    def test_one_source_low_while_peers_healthy_is_repaired(self):
        store = seeded_store(value=100.0)
        divergent_day = TODAY - timedelta(days=2)
        store.seed("orders", divergent_day, 5.0)  # far below its own trailing median
        store.seed("visitors", divergent_day, 100.0)
        for n in range(14):
            if TODAY - timedelta(days=n) != divergent_day:
                store.seed("visitors", TODAY - timedelta(days=n), 100.0)
        collectors = [
            FakeCollector("orders", schedule={None: (98.0, Health.OK)}),
            FakeCollector("visitors", schedule={None: (100.0, Health.OK)}),
        ]
        report = verify_and_backfill(store, collectors, days=14, today=TODAY)
        assert ("orders", divergent_day) in [(s, d) for s, d in report.repaired]

    def test_repair_returning_unavailable_preserves_original_value(self):
        store = seeded_store()
        bad_day = TODAY - timedelta(days=2)
        del store._cells[("orders", bad_day)]  # missing -> suspect
        collector = FakeCollector("orders", schedule={None: (None, Health.OK)},
                                  raises_on=set())
        # simulate a repair attempt that comes back UNAVAILABLE
        original_collect = collector.collect

        def flaky_collect(window):
            if window.start == bad_day:
                from report_pipeline.collect import CollectorResult
                return CollectorResult(data={"value": None}, health=Health.UNAVAILABLE,
                                       fetched_at=datetime.now(UTC), source="orders")
            return original_collect(window)

        collector.collect = flaky_collect
        report = verify_and_backfill(store, [collector], days=14, today=TODAY)
        assert bad_day in [d for _, d in report.still_suspect]
        assert store.get("orders", bad_day) is None  # never written a worse value

    def test_repair_cap_reached_reports_remaining_as_still_suspect(self):
        store = InMemoryStore()  # everything missing -> all suspect
        collector = FakeCollector("orders", schedule={None: (1.0, Health.OK)})
        report = verify_and_backfill(store, [collector], days=14, today=TODAY, max_repairs=3)
        assert report.capped is True
        assert len(report.repaired) == 3
        assert len(report.still_suspect) == 14 - 3

    def test_convergence_three_runs_zero_writes_after_first(self):
        store = seeded_store()
        del store._cells[("orders", TODAY - timedelta(days=1))]
        collector = FakeCollector("orders", schedule={None: (77.0, Health.OK)})

        first = verify_and_backfill(store, [collector], days=14, today=TODAY)
        assert len(first.repaired) == 1

        second = verify_and_backfill(store, [collector], days=14, today=TODAY)
        assert len(second.repaired) == 0
        assert len(second.still_suspect) == 0

        third = verify_and_backfill(store, [collector], days=14, today=TODAY)
        assert len(third.repaired) == 0
