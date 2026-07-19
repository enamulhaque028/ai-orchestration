"""Environment checks for Engineering Manager."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from em.platform_paths import (
    path_hint,
    primary_user_bin,
    python_install_hint,
    which_command,
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    hint: str = ""


def run_checks() -> list[CheckResult]:
    results: list[CheckResult] = []

    py_ok = sys.version_info >= (3, 11)
    results.append(
        CheckResult(
            name="Python",
            ok=py_ok,
            detail=f"{sys.version.split()[0]} ({sys.executable})",
            hint="" if py_ok else python_install_hint(),
        )
    )

    local_bin = primary_user_bin()
    path_dirs = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    local_on_path = False
    try:
        local_resolved = local_bin.resolve()
        local_on_path = any(Path(p).resolve() == local_resolved for p in path_dirs)
    except OSError:
        local_on_path = str(local_bin) in path_dirs

    results.append(
        CheckResult(
            name="User bin on PATH",
            ok=local_on_path,
            detail=f"{local_bin} — {'yes' if local_on_path else 'no'}",
            hint="" if local_on_path else path_hint(),
        )
    )

    em_path = shutil.which("em") or which_command("em")
    results.append(
        CheckResult(
            name="em command",
            ok=bool(em_path),
            detail=em_path or "not found on PATH",
            hint=(
                ""
                if em_path
                else "Re-run the installer for your OS (see README), or: "
                "pipx install --force git+https://github.com/enamulhaque028/ai-orchestration.git"
            ),
        )
    )

    agents = [
        ("Cursor Agent", ("agent", "cursor-agent"), "Install Cursor Agent CLI, then: agent login"),
        ("Claude Code", ("claude",), "Install Claude Code CLI and log in"),
        ("Codex", ("codex",), "Install Codex CLI and log in"),
        ("Gemini", ("gemini",), "Install Gemini CLI and log in"),
    ]
    for label, bins, hint in agents:
        found = which_command(*bins)
        results.append(
            CheckResult(
                name=label,
                ok=bool(found),
                detail=found or "not installed (optional)",
                hint="" if found else hint,
            )
        )

    return results


def print_doctor(console: Console | None = None) -> int:
    """Print check table. Exit code 0 if em itself is usable; agent CLIs are optional."""
    console = console or Console()
    results = run_checks()

    table = Table(title="em doctor", show_header=True, header_style="bold")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    for r in results:
        optional = r.name in ("Cursor Agent", "Claude Code", "Codex", "Gemini")
        if r.ok:
            status = "[green]ok[/green]"
        elif optional:
            status = "[yellow]missing[/yellow]"
        else:
            status = "[red]fail[/red]"
        table.add_row(r.name, status, r.detail)

    console.print(table)

    hints = [r for r in results if not r.ok and r.hint]
    if hints:
        console.print("\n[bold]Next steps[/bold]")
        for r in hints:
            console.print(f"  • {r.name}: {r.hint}")

    console.print(
        "\nAgent CLIs are optional — install only the providers your workflow uses."
    )
    console.print(f"Platform: [cyan]{sys.platform}[/cyan]")

    hard = [r for r in results if r.name in ("Python", "em command") and not r.ok]
    return 1 if hard else 0
