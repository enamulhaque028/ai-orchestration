"""Tests for em doctor checks."""

import sys

from em.doctor import run_checks


def test_doctor_includes_python_and_agents():
    results = {r.name: r for r in run_checks()}
    assert "Python" in results
    assert "em command" in results
    assert "Cursor Agent" in results
    assert results["Python"].ok is (sys.version_info >= (3, 11))
