"""
CLI configuration — persisted at ~/.omnia/config.toml.

Handles TOML read/write. No SDK imports — the CLI creates an OmniaClient
from these values whenever it needs to make API calls.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CONFIG_DIR = Path.home() / ".omnia"
CONFIG_FILE = CONFIG_DIR / "config.toml"

_ENV_URLS: dict[str, str] = {
    "prod": "https://api.omniasec.ai",
    "staging": "https://api.staging.omniasec.ai",
    "dev": "http://localhost:8000",
}

_FRONTEND_URLS: dict[str, str] = {
    "prod": "https://app.omniasec.ai",
    "staging": "https://app.staging.omniasec.ai",
    "dev": "http://localhost:5173",
}

_USER_KEYS: dict[str, str] = {
    "default_model": "gemini-2.5-pro",
    "default_provider": "google",
}


# ---------------------------------------------------------------------------
# TOML helpers
# ---------------------------------------------------------------------------


def _write_toml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for k, v in data.items():
        if isinstance(v, str):
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{escaped}"')
        elif isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class CLISettings:
    """Manages CLI config (TOML persistence). No SDK dependency."""

    def __init__(self) -> None:
        env = os.getenv("OMNIA_ENV", "prod").lower()
        self._api_url: str = os.getenv("OMNIA_API_URL", _ENV_URLS.get(env, _ENV_URLS["prod"]))
        self._frontend_url: str = _FRONTEND_URLS.get(env, _FRONTEND_URLS["prod"])
        self._data: dict = {**_USER_KEYS}
        self._api_key: str = ""
        self._load()

    def _load(self) -> None:
        file_cfg = _read_toml(CONFIG_FILE)
        self._data.update({k: v for k, v in file_cfg.items() if k in _USER_KEYS})
        self._api_key = os.getenv("OMNIA_API_TOKEN", "") or file_cfg.get("api_key", "")

    def save(self) -> None:
        payload = {**self._data, "api_key": self._api_key}
        _write_toml(payload, CONFIG_FILE)

    # ------------------------------------------------------------------
    # api_key
    # ------------------------------------------------------------------

    @property
    def api_key(self) -> str:
        return self._api_key

    @api_key.setter
    def api_key(self, value: str) -> None:
        self._api_key = value

    # ------------------------------------------------------------------
    # Read-only URL properties (resolved once at startup from env)
    # ------------------------------------------------------------------

    @property
    def api_url(self) -> str:
        return self._api_url

    @property
    def frontend_url(self) -> str:
        return self._frontend_url

    # ------------------------------------------------------------------
    # User-editable settings
    # ------------------------------------------------------------------

    @property
    def default_model(self) -> str:
        return self._data["default_model"]

    @default_model.setter
    def default_model(self, value: str) -> None:
        self._data["default_model"] = value

    @property
    def default_provider(self) -> str:
        return self._data["default_provider"]

    @default_provider.setter
    def default_provider(self, value: str) -> None:
        self._data["default_provider"] = value

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def set(self, key: str, value: str) -> None:
        if key not in _USER_KEYS:
            raise KeyError(f"Unknown config key: {key!r}. Editable keys: {list(_USER_KEYS)}")
        setattr(self, key, value)


settings = CLISettings()
