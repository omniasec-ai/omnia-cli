"""
Persistent configuration stored at ~/.omnia/config.toml

API URL is NOT user-configurable — it is resolved automatically:

  OMNIA_ENV=prod  →  https://api.omniasec.ai     (production)
  OMNIA_ENV=dev   →  http://localhost:8000         (default)
  OMNIA_API_URL=… →  explicit override (staging / custom deploys)

The only credential the user ever sets is their API key.
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
    "dev": "http://localhost:8000",
}

# Keys that the user is allowed to edit via /config set
_USER_KEYS: dict[str, str] = {
    "default_model": "gemini-2.5-pro",
    "default_provider": "google",
}


# ---------------------------------------------------------------------------
# TOML helpers (no external dependency — manual flat serialiser)
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


def _resolve_api_url() -> str:
    """Determine the API base URL — never asks the user."""
    # 1. Explicit env override (staging, custom deploys)
    if url := os.getenv("OMNIA_API_URL"):
        return url.rstrip("/")
    # 2. Environment name
    env = os.getenv("OMNIA_ENV", "dev").lower()
    return _ENV_URLS.get(env, _ENV_URLS["dev"])


# ---------------------------------------------------------------------------
# Settings class
# ---------------------------------------------------------------------------


class Settings:
    """Runtime configuration. api_url is read-only (resolved from env)."""

    def __init__(self) -> None:
        self._data: dict = {**_USER_KEYS}
        self._load()

    def _load(self) -> None:
        # 1. Persisted file (only user-editable keys)
        file_cfg = _read_toml(CONFIG_FILE)
        self._data.update({k: v for k, v in file_cfg.items() if k in _USER_KEYS})

        # 2. API key — env var overrides saved file
        self._api_key: str = os.getenv("OMNIA_API_TOKEN", "")
        if saved_key := file_cfg.get("api_key", ""):
            if not self._api_key:  # env var takes priority
                self._api_key = saved_key

    def save(self) -> None:
        """Persist user-editable values + api_key to disk."""
        payload = {**self._data, "api_key": self._api_key}
        _write_toml(payload, CONFIG_FILE)

    # ------------------------------------------------------------------
    # Read-only: api_url
    # ------------------------------------------------------------------

    @property
    def api_url(self) -> str:
        return _resolve_api_url()

    # ------------------------------------------------------------------
    # api_key (user credential)
    # ------------------------------------------------------------------

    @property
    def api_key(self) -> str:
        return self._api_key

    @api_key.setter
    def api_key(self, value: str) -> None:
        self._api_key = value

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

    def as_dict(self) -> dict:
        """Returns display-friendly config (api_url resolved, key masked)."""
        return {
            "api_url (env)": self.api_url,
            "api_key": "***" if self._api_key else "(not set)",
            "default_model": self.default_model,
            "default_provider": self.default_provider,
        }

    def set(self, key: str, value: str) -> None:
        if key not in _USER_KEYS:
            raise KeyError(
                f"Unknown config key: {key!r}. Editable keys: {list(_USER_KEYS)}"
            )
        self._data[key] = value


# Module-level singleton
settings = Settings()
