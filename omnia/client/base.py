"""
Base HTTP client with auth headers, unified error handling and retry logic.

URLs are built as:  settings.api_url + path
  e.g.  "http://localhost:8000/api"  +  "/v1/app/users/me"
      = "http://localhost:8000/api/v1/app/users/me"

We avoid httpx's base_url merging because httpx discards the base path
component whenever the request path starts with "/".
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Generator, Iterator

import httpx
from rich.console import Console

from omnia.config.settings import settings

console = Console(stderr=True)

_RETRY_CODES = {429, 502, 503, 504}
_MAX_RETRIES = 2


class OmniaAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class NotConfiguredError(Exception):
    pass


def _url(path: str) -> str:
    """Build absolute URL from base + path."""
    return settings.api_url.rstrip("/") + path


def _auth_headers() -> dict[str, str]:
    if not settings.is_configured():
        raise NotConfiguredError("Not authenticated. Run /login first.")
    
    val = settings.api_key
    # If it's just a hex/uuid string without a scheme, it's likely an incomplete API Key auth
    if " " not in val.strip():
        # We can't fix it here without the user_id, but we can provide a better error
        raise NotConfiguredError(
            "Invalid API Key format. It should be 'Basic <base64>' or 'Bearer <token>'.\n"
            "Try running /login again to re-authenticate with your User ID and API Key."
        )
        
    return {"Authorization": val}


def _handle_response(response: httpx.Response) -> None:
    if response.is_success:
        return
    
    # For streaming responses, we must read the content to access .text or .json()
    try:
        response.read()
    except Exception:
        pass

    try:
        data = response.json()
        detail = data.get("detail", response.text)
    except Exception:
        detail = response.text
    raise OmniaAPIError(response.status_code, str(detail))


# ---------------------------------------------------------------------------
# Public helpers (no auth)
# ---------------------------------------------------------------------------

def public_request(
    method: str,
    path: str,
    *,
    json: Any = None,
    params: dict | None = None,
    timeout: float = 30.0,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.request(method, _url(path), json=json, params=params)
            _handle_response(resp)
            return resp.json()
        except OmniaAPIError as exc:
            if exc.status_code not in _RETRY_CODES or attempt == _MAX_RETRIES:
                raise
            last_exc = exc
        except httpx.RequestError as exc:
            if attempt == _MAX_RETRIES:
                raise
            last_exc = exc
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Authenticated helpers
# ---------------------------------------------------------------------------

def request(
    method: str,
    path: str,
    *,
    json: Any = None,
    params: dict | None = None,
    files: dict | None = None,
    data: dict | None = None,
    timeout: float = 30.0,
) -> Any:
    headers = _auth_headers()
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            with httpx.Client(
                headers=headers, timeout=timeout, follow_redirects=True
            ) as client:
                resp = client.request(
                    method, _url(path),
                    json=json, params=params, files=files, data=data,
                )
            _handle_response(resp)
            return resp.json()
        except OmniaAPIError as exc:
            if exc.status_code not in _RETRY_CODES or attempt == _MAX_RETRIES:
                raise
            last_exc = exc
        except httpx.RequestError as exc:
            if attempt == _MAX_RETRIES:
                raise
            last_exc = exc
    raise last_exc  # type: ignore[misc]


@contextmanager
def stream_request(
    method: str,
    path: str,
    *,
    json: Any = None,
    timeout: float = 120.0,
) -> Generator[httpx.Response, None, None]:
    """Context manager for SSE streaming requests."""
    headers = _auth_headers()
    with httpx.Client(
        headers=headers, timeout=timeout, follow_redirects=True
    ) as client:
        with client.stream(method, _url(path), json=json) as response:
            _handle_response(response)
            yield response


def iter_sse(response: httpx.Response) -> Iterator[dict]:
    """Parse Server-Sent Events from a streaming response."""
    buffer = ""
    for chunk in response.iter_text():
        buffer += chunk
        while "\n" in buffer:
            event_str, buffer = buffer.split("\n", 1)
            for line in event_str.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    raw = line[5:].strip()
                else:
                    raw = line
                
                if raw and raw != "[DONE]":
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        # If it's not JSON, skip or yield as is
                        pass
