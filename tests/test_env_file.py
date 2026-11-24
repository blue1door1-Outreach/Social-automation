from __future__ import annotations

from pathlib import Path

from src.env_file import load_env_file, parse_env_file


def test_parse_handles_comments_quotes_and_export() -> None:
    text = (
        "# comment\n"
        "\n"
        "PLAIN=value\n"
        "export QUOTED=\"two words\"\n"
        "SINGLE='a=b'\n"
        "TRAILING=value # note\n"
        "SPACED = padded \n"
    )
    assert parse_env_file(text) == {
        "PLAIN": "value",
        "QUOTED": "two words",
        "SINGLE": "a=b",
        "TRAILING": "value",
        "SPACED": "padded",
    }


def test_real_environment_wins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KHUJE_TEST_KEY", "from-shell")
    monkeypatch.delenv("KHUJE_TEST_NEW", raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "KHUJE_TEST_KEY=from-file\nKHUJE_TEST_NEW=added\n", encoding="utf-8"
    )

    applied = load_env_file(path)

    import os

    assert os.environ["KHUJE_TEST_KEY"] == "from-shell"
    assert os.environ["KHUJE_TEST_NEW"] == "added"
    assert applied == ["KHUJE_TEST_NEW"]
    monkeypatch.delenv("KHUJE_TEST_NEW", raising=False)


def test_missing_file_is_not_an_error(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "absent.env") == []
