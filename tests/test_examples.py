"""Tests for bundled example workflows."""

from em.examples_data import example_text, list_examples, write_example


def test_list_examples_includes_mock():
    names = list_examples()
    assert "mock-feature" in names
    assert "flutter-checkout" in names


def test_write_example(tmp_path):
    out = write_example("mock-feature", tmp_path)
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "name:" in text
    assert example_text("mock-feature") == text
