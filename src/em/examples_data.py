"""Bundled example workflows shipped with the em package."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

EXAMPLES_PKG = "em.data.examples"


def list_examples() -> list[str]:
    root = resources.files(EXAMPLES_PKG)
    names: list[str] = []
    for item in root.iterdir():
        if item.name.endswith(".yaml"):
            names.append(item.name.removesuffix(".yaml"))
    return sorted(names)


def example_text(name: str) -> str:
    filename = name if name.endswith(".yaml") else f"{name}.yaml"
    root = resources.files(EXAMPLES_PKG)
    path = root.joinpath(filename)
    if not path.is_file():
        known = ", ".join(list_examples()) or "(none)"
        raise FileNotFoundError(f"Unknown example '{name}'. Available: {known}")
    return path.read_text(encoding="utf-8")


def write_example(name: str, dest_dir: str | Path) -> Path:
    dest_dir = Path(dest_dir).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = name if name.endswith(".yaml") else f"{name}.yaml"
    stem = filename.removesuffix(".yaml")
    out = dest_dir / f"{stem}.yaml"
    out.write_text(example_text(stem), encoding="utf-8")
    return out


def example_path_in_package(name: str) -> Path:
    """Return a real filesystem path when available (zip/egg may not)."""
    filename = name if name.endswith(".yaml") else f"{name}.yaml"
    root = resources.files(EXAMPLES_PKG)
    path = root.joinpath(filename)
    with resources.as_file(path) as real:
        return Path(real)
