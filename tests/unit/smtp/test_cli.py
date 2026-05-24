"""Tests for ChaosSMTP CLI entry points."""

from typer.testing import CliRunner

from errorworks.engine.cli import app as engine_app
from errorworks.smtp.cli import app

runner = CliRunner()


def test_chaossmtp_cli_has_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ChaosSMTP" in result.stdout
    assert "serve" in result.stdout
    assert "presets" in result.stdout


def test_chaosengine_mounts_smtp_subcommand() -> None:
    result = runner.invoke(engine_app, ["--help"])
    assert result.exit_code == 0
    assert "smtp" in result.stdout
