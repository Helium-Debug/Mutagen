"""
Tests for Typer CLI commands.
"""

import pytest
from typer.testing import CliRunner
from pathlib import Path

from mutagen.cli.main import app
from mutagen.core.auth import CredentialsManager

runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "MUTAGEN" in result.output or "0.1.0" in result.output


def test_cli_doctor():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "MUTAGEN" in result.output or "Dependency Status" in result.output


def test_cli_unauthenticated_rejection(tmp_path):
    """Protected commands must halt immediately with the required message if not authenticated."""
    CredentialsManager.clear()
    py_file = tmp_path / "target.py"
    py_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    # Analyze
    result = runner.invoke(app, ["analyze", str(py_file)])
    assert result.exit_code == 1
    assert "Authentication required." in result.output
    assert "Please log in before analyzing, testing, or optimizing code." in result.output
    assert "mutagen login" in result.output
    assert "mutagen register" in result.output

    # Evaluate
    result_eval = runner.invoke(app, ["evaluate", str(py_file)])
    assert result_eval.exit_code == 1
    assert "Authentication required." in result_eval.output

    # Optimize
    result_opt = runner.invoke(app, ["optimize", str(py_file)])
    assert result_opt.exit_code == 1
    assert "Authentication required." in result_opt.output

    # Projects
    result_proj = runner.invoke(app, ["project", "list"])
    assert result_proj.exit_code == 1
    assert "Authentication required." in result_proj.output


def test_cli_register_and_login():
    """Test mutagen register, login, whoami, and logout via CLI options."""
    CredentialsManager.clear()

    # Register
    res_reg = runner.invoke(
        app,
        ["register", "-u", "bob_cli", "-e", "bob_cli@example.com", "-p", "StrongPassw0rd!"],
    )
    assert "registered successfully" in res_reg.output.lower() or "bob_cli" in res_reg.output

    # Whoami
    res_who = runner.invoke(app, ["whoami"])
    assert res_who.exit_code == 0
    assert "bob_cli" in res_who.output

    # Account
    res_acc = runner.invoke(app, ["account"])
    assert res_acc.exit_code == 0
    assert "bob_cli@example.com" in res_acc.output

    # Logout
    res_out = runner.invoke(app, ["logout"])
    assert res_out.exit_code == 0
    assert "logged out" in res_out.output.lower()

    # Now whoami should fail
    res_who_again = runner.invoke(app, ["whoami"])
    assert res_who_again.exit_code == 1
    assert "Authentication required." in res_who_again.output

    # Login
    res_login = runner.invoke(app, ["login", "-i", "bob_cli", "-p", "StrongPassw0rd!"])
    assert res_login.exit_code == 0
    assert "welcome back" in res_login.output.lower() or "session active" in res_login.output.lower()

    # Whoami should succeed again
    res_who_post_login = runner.invoke(app, ["whoami"])
    assert res_who_post_login.exit_code == 0
    assert "bob_cli" in res_who_post_login.output


def test_cli_config_show(auth_user):
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0


def test_cli_analyze(auth_user, tmp_path):
    py_file = tmp_path / "target.py"
    py_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    result = runner.invoke(app, ["analyze", str(py_file)])
    assert result.exit_code == 0
    assert "add" in result.stdout or "Analysis" in result.stdout or "add" in result.stderr


def test_cli_project_crud(auth_user):
    # Create project
    res_create = runner.invoke(app, ["project", "create", "test-project", "--description", "A CLI test project"])
    assert res_create.exit_code == 0

    # List projects
    res_list = runner.invoke(app, ["project", "list"])
    assert res_list.exit_code == 0
    assert "test-project" in res_list.stdout or "test-project" in res_list.stderr


def test_cli_memory_list(auth_user):
    result = runner.invoke(app, ["memory", "list"])
    assert result.exit_code == 0
