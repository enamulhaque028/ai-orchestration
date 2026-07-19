"""Cross-platform path helpers for em."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform == "win32"


def user_bin_dirs() -> list[Path]:
    """Directories where pipx / user scripts commonly install CLIs."""
    dirs: list[Path] = []
    home = Path.home()

    # pipx default on all platforms
    dirs.append(home / ".local" / "bin")

    if is_windows():
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            dirs.append(Path(local_app) / "Programs" / "Python" / "Scripts")
            dirs.append(Path(local_app) / "pipx" / "venvs")
        # Python user Scripts (pip --user)
        try:
            import site

            user_base = site.getuserbase()
            if user_base:
                dirs.append(Path(user_base) / "Scripts")
        except Exception:  # noqa: BLE001
            pass
        dirs.append(home / "AppData" / "Local" / "Programs" / "cursor-agent")
    else:
        dirs.append(Path.home() / ".local" / "share" / "cursor-agent")
        # Homebrew
        dirs.append(Path("/opt/homebrew/bin"))
        dirs.append(Path("/usr/local/bin"))

    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def primary_user_bin() -> Path:
    return Path.home() / ".local" / "bin"


def path_hint() -> str:
    if is_windows():
        return (
            r'Add to User PATH: %USERPROFILE%\.local\bin '
            r"(Windows Settings → Environment Variables), then open a new terminal"
        )
    return 'Add to ~/.zshrc or ~/.bashrc: export PATH="$HOME/.local/bin:$PATH" then open a new terminal'


def which_command(*names: str) -> str | None:
    """Resolve an executable by name, searching PATH and common user bin dirs."""
    suffixes = [""]
    if is_windows():
        suffixes = [".exe", ".cmd", ".bat", ""]

    expanded_names: list[str] = []
    for name in names:
        expanded_names.append(name)
        if is_windows() and not name.lower().endswith((".exe", ".cmd", ".bat")):
            expanded_names.extend([f"{name}.exe", f"{name}.cmd", f"{name}.bat"])

    for name in expanded_names:
        found = shutil.which(name)
        if found:
            return found

    for name in names:
        for directory in user_bin_dirs():
            for suffix in suffixes:
                candidate = directory / f"{name}{suffix}"
                if candidate.is_file():
                    return str(candidate)
    return None


def python_install_hint() -> str:
    if is_windows():
        return (
            "Install Python 3.11+ from https://www.python.org/downloads/ "
            "(check 'Add python.exe to PATH'), then re-run the installer"
        )
    if sys.platform == "darwin":
        return "Need Python 3.11+. Install: brew install python"
    return "Need Python 3.11+. Install via your package manager (e.g. sudo apt install python3)"
