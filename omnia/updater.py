"""
Update helpers: version check (with daily cache) and self-update logic.
"""

from __future__ import annotations

import json
import os
import platform
import stat
import sys
import tempfile
import urllib.request
from datetime import date
from pathlib import Path

from omnia import __version__
from omnia.config.settings import CONFIG_DIR

_REPO = "omniasec-ai/omnia-cli"
_CACHE_FILE = CONFIG_DIR / "version_check.json"
_API_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------


def _parse(tag: str) -> tuple[int, ...]:
    """'v0.2.7' → (0, 2, 7)"""
    return tuple(int(x) for x in tag.lstrip("v").split(".") if x.isdigit())


def _current_tag() -> str:
    return f"v{__version__}"


def _fetch_latest_tag() -> str | None:
    try:
        req = urllib.request.Request(_API_URL, headers={"User-Agent": "omnia-cli"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        return data.get("tag_name")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cache — check at most once per day
# ---------------------------------------------------------------------------


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_FILE.read_text())
    except Exception:
        return {}


def _save_cache(tag: str) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps({"date": str(date.today()), "latest": tag}))
    except Exception:
        pass


def check_for_update() -> str | None:
    """Return the latest tag if newer than current, else None. Non-blocking cache."""
    cache = _load_cache()
    if cache.get("date") == str(date.today()):
        latest = cache.get("latest")
    else:
        latest = _fetch_latest_tag()
        if latest:
            _save_cache(latest)

    if not latest:
        return None

    try:
        if _parse(latest) > _parse(_current_tag()):
            return latest
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Self-update
# ---------------------------------------------------------------------------


def _detect_asset() -> str:
    os_name = platform.system().lower()
    arch = platform.machine().lower()
    if os_name == "darwin":
        os_slug = "macos"
    elif os_name == "linux":
        os_slug = "linux"
    else:
        raise RuntimeError(f"Unsupported OS: {os_name}")

    if arch in ("arm64", "aarch64"):
        arch_slug = "arm64"
    elif arch == "x86_64":
        arch_slug = "amd64"
    else:
        raise RuntimeError(f"Unsupported architecture: {arch}")

    return f"omnia-{os_slug}-{arch_slug}"


def _binary_path() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    import shutil

    found = shutil.which("omnia")
    return Path(found) if found else None


def do_update() -> tuple[bool, str]:
    """
    Download the latest release binary and replace the current one.
    Returns (success, message).
    """
    latest = _fetch_latest_tag()
    if not latest:
        return False, "Could not reach GitHub to check for updates."

    current = _current_tag()
    if _parse(latest) <= _parse(current):
        return True, f"Already on the latest version ({current})."

    binary = _binary_path()
    if not binary or not binary.exists():
        return False, "Could not locate the omnia binary to replace."

    asset = _detect_asset()
    url = f"https://github.com/{_REPO}/releases/download/{latest}/{asset}"

    try:
        with tempfile.NamedTemporaryFile(
            dir=binary.parent, prefix=".omnia-update-", delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)

        req = urllib.request.Request(url, headers={"User-Agent": "omnia-cli"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            tmp_path.write_bytes(resp.read())

        tmp_path.chmod(tmp_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(tmp_path, binary)
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False, f"Update failed: {exc}"

    return True, f"Updated to {latest}. Restart omnia to use the new version."
