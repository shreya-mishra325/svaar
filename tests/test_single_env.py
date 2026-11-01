"""Default environment helpers validate one source without rotating or exporting secrets."""

import json

import pytest

from svaar import deployment, render_env

BASE = "SVAAR_DATABASE_URL=postgresql+psycopg://test:test@127.0.0.1/test\n"
VOICE = (
    "SVAAR_LLM_BASE_URL=https://model.example/v1\n"
    "SVAAR_LLM_API_KEY=private-fake-provider\n"
    "SVAAR_LLM_MODEL=offline\n"
    "SVAAR_VOICE_TURN_TOKEN=" + "t" * 32 + "\n"
    "SVAAR_VOICE_STATUS_SECRET=" + "s" * 32 + "\n"
)


def test_deployment_default_validates_without_another_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / ".env"
    source.write_text(BASE)
    before = source.read_bytes()
    assert deployment.main([]) == 0
    assert source.read_bytes() == before
    assert set(tmp_path.iterdir()) == {source}
    assert json.loads(capsys.readouterr().out)["files_created"] == 0


def test_deployment_missing_configuration_does_not_generate_defaults(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert deployment.main([]) == 1
    assert not list(tmp_path.iterdir())
    assert json.loads(capsys.readouterr().out)["valid"] is False


@pytest.mark.parametrize("configured", [True, False])
def test_render_helper_never_creates_files_or_rotates_credentials(
    tmp_path, monkeypatch, capsys, configured
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / ".env"
    source.write_text(BASE + (VOICE if configured else ""))
    before = source.read_bytes()
    assert render_env.main() == (0 if configured else 1)
    assert source.read_bytes() == before
    assert set(tmp_path.iterdir()) == {source}
    output = capsys.readouterr().out
    assert "private-fake-provider" not in output
    assert "t" * 32 not in output
    assert json.loads(output)["valid"] is configured
