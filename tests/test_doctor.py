"""Tests for em doctor checks."""

import sys

from em.doctor import run_checks


def test_doctor_includes_python_and_agents():
    results = {r.name: r for r in run_checks()}
    assert "Python" in results
    assert "em command" in results
    assert "Cursor Agent" in results
    assert "User bin on PATH" in results
    assert results["Python"].ok is (sys.version_info >= (3, 11))


def test_which_command_finds_something_on_path():
    from em.platform_paths import which_command

    # python should resolve on any supported OS used in CI/dev
    found = which_command("python3", "python")
    assert found is not None
