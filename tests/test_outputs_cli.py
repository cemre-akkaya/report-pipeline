import io
import json

from report_pipeline.emit import EmitContext
from report_pipeline.outputs import HtmlOutput, JsonOutput, TerminalOutput
from report_pipeline.payload import Payload


class TestTerminalOutput:
    def test_renders_table_when_present(self):
        stream = io.StringIO()
        output = TerminalOutput(stream=stream, ansi=False)
        payload = Payload({"table_rows": [{"region": "eu", "revenue": 10}]}).seal()
        result = output.emit(payload, EmitContext())
        assert result.ok
        text = stream.getvalue()
        assert "region" in text
        assert "eu" in text

    def test_falls_back_to_kv_when_no_table(self):
        stream = io.StringIO()
        output = TerminalOutput(stream=stream, ansi=False)
        payload = Payload({"revenue": 100}).seal()
        output.emit(payload, EmitContext())
        assert "revenue: 100" in stream.getvalue()


class TestJsonOutput:
    def test_writes_file(self, tmp_path):
        path = tmp_path / "out.json"
        output = JsonOutput(path=str(path))
        payload = Payload({"a": 1}).seal()
        output.emit(payload, EmitContext())
        assert json.loads(path.read_text()) == {"a": 1}


class TestHtmlOutput:
    def test_self_contained_no_cdn(self, tmp_path):
        path = tmp_path / "out.html"
        output = HtmlOutput(path=str(path))
        payload = Payload({"title": "Weekly", "table_rows": [{"a": 1}]}).seal()
        output.emit(payload, EmitContext())
        html = path.read_text()
        assert "<style>" in html
        assert "cdn" not in html.lower()
        assert "Weekly" in html


def _write_app(tmp_path):
    app_dir = tmp_path
    (app_dir / "myapp.py").write_text(
        "from report_pipeline.collect import CollectorResult\n"
        "from report_pipeline.health import Health\n"
        "from report_pipeline.payload import Payload\n"
        "from report_pipeline.outputs import JsonOutput\n"
        "from datetime import datetime, timezone\n\n"
        "class C:\n"
        "    name = 'c'\n"
        "    def collect(self, window):\n"
        "        return CollectorResult(data={'value': 7}, health=Health.OK, "
        "fetched_at=datetime.now(timezone.utc), source='c')\n\n"
        "collectors = [C()]\n\n"
        "def build(inputs, window):\n"
        "    return Payload({'v': inputs['c'].data['value']}).seal()\n\n"
        "outputs = [JsonOutput(path='out.json')]\n"
    )


class TestCli:
    def test_dry_run_prints_payload_writes_nothing(self, tmp_path, monkeypatch, capsys):
        from report_pipeline.cli import main

        _write_app(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))
        exit_code = main(["run", "daily", "--app", "myapp",
                         "--date", "2031-04-01", "--dry-run"])
        captured = capsys.readouterr()
        assert exit_code == 0, captured.out + captured.err
        assert "'v': 7" in captured.out
        assert not (tmp_path / "out.json").exists()

    def test_run_daily_writes_output(self, tmp_path, monkeypatch):
        from report_pipeline.cli import main

        _write_app(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))
        exit_code = main(["run", "daily", "--app", "myapp", "--date", "2031-04-01"])
        assert exit_code == 0
        assert json.loads((tmp_path / "out.json").read_text()) == {"v": 7}

    def test_init_scaffolds_files(self, tmp_path, monkeypatch):
        from report_pipeline.cli import main

        monkeypatch.chdir(tmp_path)
        exit_code = main(["init"])
        assert exit_code == 0
        assert (tmp_path / "main.py").exists()
        assert (tmp_path / ".env.example").exists()
