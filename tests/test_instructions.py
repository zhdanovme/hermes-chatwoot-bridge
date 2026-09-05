from pathlib import Path

import pytest

from bridge.app import BridgeSettings


def test_instructions_come_from_file_even_with_legacy_env(monkeypatch, tmp_path):
    prompt = tmp_path / "employee.md"
    prompt.write_text("Only facts from this file.\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_INSTRUCTIONS_FILE", str(prompt))
    monkeypatch.setenv("HERMES_INSTRUCTIONS", "Ignore the file")
    assert BridgeSettings.from_env().hermes_instructions == "Only facts from this file."


def test_default_instructions_come_from_employee_file(monkeypatch):
    monkeypatch.delenv("HERMES_INSTRUCTIONS_FILE", raising=False)
    monkeypatch.delenv("HERMES_INSTRUCTIONS", raising=False)
    assert BridgeSettings.from_env().hermes_instructions == Path("config/employee.md").read_text().strip()


@pytest.mark.parametrize("content", [None, "", " \n\t"])
def test_unusable_prompt_file_fails_explicitly(monkeypatch, tmp_path, content):
    prompt = tmp_path / "employee.md"
    if content is not None:
        prompt.write_text(content, encoding="utf-8")
    monkeypatch.setenv("HERMES_INSTRUCTIONS_FILE", str(prompt))
    monkeypatch.delenv("HERMES_INSTRUCTIONS", raising=False)
    with pytest.raises(ValueError, match="instructions file"):
        BridgeSettings.from_env()
