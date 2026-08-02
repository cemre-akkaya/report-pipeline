from datetime import UTC, date, datetime

from report_pipeline.backfill import Cell
from report_pipeline.health import Health
from report_pipeline.state import JsonStateStore


class TestJsonStateStore:
    def test_put_then_get_roundtrip(self, tmp_path):
        store = JsonStateStore(tmp_path)
        cell = Cell(source="orders", date=date(2031, 4, 1), value=100.0,
                   health=Health.OK, written_at=datetime.now(UTC))
        store.put(cell)
        fetched = store.get("orders", date(2031, 4, 1))
        assert fetched.value == 100.0
        assert fetched.health == Health.OK

    def test_get_range(self, tmp_path):
        store = JsonStateStore(tmp_path)
        for day in (1, 2, 3):
            store.put(Cell(source="orders", date=date(2031, 4, day), value=float(day),
                          health=Health.OK, written_at=datetime.now(UTC)))
        cells = store.get_range("orders", date(2031, 4, 1), date(2031, 4, 3))
        assert len(cells) == 3
        assert cells[date(2031, 4, 2)].value == 2.0

    def test_one_file_per_source(self, tmp_path):
        store = JsonStateStore(tmp_path)
        store.put(Cell(source="orders", date=date(2031, 4, 1), value=1.0,
                       health=Health.OK, written_at=datetime.now(UTC)))
        store.put(Cell(source="visitors", date=date(2031, 4, 1), value=2.0,
                       health=Health.OK, written_at=datetime.now(UTC)))
        files = sorted(p.name for p in tmp_path.iterdir())
        assert files == ["orders.json", "visitors.json"]

    def test_missing_cell_returns_none(self, tmp_path):
        store = JsonStateStore(tmp_path)
        assert store.get("orders", date(2031, 4, 1)) is None


class TestSheetStateStore:
    def test_upsert_matches_on_date_column(self):
        from report_pipeline.state import SheetStateStore

        class FakeSheetClient:
            def __init__(self):
                self.rows = []

            def read_rows(self, sheet):
                return self.rows

            def upsert_row(self, sheet, match, row):
                for i, existing in enumerate(self.rows):
                    if all(existing.get(k) == v for k, v in match.items()):
                        self.rows[i] = row
                        return
                self.rows.append(row)

        client = FakeSheetClient()
        store = SheetStateStore(client, "State")
        cell1 = Cell(source="orders", date=date(2031, 4, 1), value=1.0,
                    health=Health.OK, written_at=datetime.now(UTC))
        store.put(cell1)
        cell2 = Cell(source="orders", date=date(2031, 4, 1), value=99.0,
                    health=Health.OK, written_at=datetime.now(UTC))
        store.put(cell2)  # should overwrite, not append
        assert len(client.rows) == 1
        assert client.rows[0]["value"] == 99.0
