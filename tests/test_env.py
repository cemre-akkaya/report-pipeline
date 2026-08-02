import os

import pytest

from report_pipeline.env import MissingConfig, config_scope, load_dotenv, redact, require_env


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("FOO", "BAR", "BAZ", "REPORT_PIPELINE_ENV"):
        monkeypatch.delenv(key, raising=False)
    yield


class TestLoadDotenv:
    def test_real_env_wins_over_dotenv(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("FOO=from_file\n")
        monkeypatch.setenv("FOO", "from_real_env")
        monkeypatch.chdir(tmp_path)
        load_dotenv()
        assert os.environ["FOO"] == "from_real_env"

    def test_override_true_lets_dotenv_win(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("FOO=from_file\n")
        monkeypatch.setenv("FOO", "from_real_env")
        monkeypatch.chdir(tmp_path)
        load_dotenv(override=True)
        assert os.environ["FOO"] == "from_file"

    def test_quoted_values_stripped(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text('FOO="quoted value"\nBAR=\'single quoted\'\n')
        monkeypatch.chdir(tmp_path)
        load_dotenv()
        assert os.environ["FOO"] == "quoted value"
        assert os.environ["BAR"] == "single quoted"

    def test_export_prefix_supported(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("export FOO=bar\n")
        monkeypatch.chdir(tmp_path)
        load_dotenv()
        assert os.environ["FOO"] == "bar"

    def test_comments_and_blanks_skipped(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("# a comment\n\nFOO=bar\n")
        monkeypatch.chdir(tmp_path)
        loaded = load_dotenv()
        assert loaded == {"FOO": "bar"}

    def test_explicit_path_wins_over_env_var(self, tmp_path, monkeypatch):
        (tmp_path / "custom.env").write_text("FOO=explicit\n")
        (tmp_path / ".env").write_text("FOO=cwd\n")
        monkeypatch.setenv("REPORT_PIPELINE_ENV", str(tmp_path / ".env"))
        monkeypatch.chdir(tmp_path)
        load_dotenv(str(tmp_path / "custom.env"))
        assert os.environ["FOO"] == "explicit"


class TestRequireEnv:
    def test_multi_key_missing_config_names_all(self, monkeypatch):
        monkeypatch.setenv("FOO", "1")
        with pytest.raises(MissingConfig) as exc_info, config_scope():
            require_env("FOO")
            require_env("BAR")
            require_env("BAZ")
        assert set(exc_info.value.keys) == {"BAR", "BAZ"}

    def test_single_missing_key_outside_scope(self):
        with pytest.raises(MissingConfig) as exc_info:
            require_env("NOPE")
        assert exc_info.value.keys == ["NOPE"]

    def test_cast_applied(self, monkeypatch):
        monkeypatch.setenv("FOO", "42")
        assert require_env("FOO", cast=int) == 42


class TestRedact:
    def test_shows_first_3_last_2(self):
        assert redact("abcdefgh") == "abc***gh"

    def test_short_value_fully_masked(self):
        assert redact("ab") == "**"
