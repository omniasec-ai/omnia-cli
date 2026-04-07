"""
Public API endpoints — no authentication required.

Endpoints:
  GET  /api/versions
  GET  /api/v1/public/analysis/{id}
  GET  /api/v1/public/analysis/{id}/children
  GET  /api/v1/public/templates/{id}
  GET  /api/v1/public/market-intelligence/search
  GET  /api/v1/public/market-intelligence/package/{market}/{id}
  GET  /api/v1/public/market-intelligence/package/{market}/{id}/versions
  GET  /api/v1/public/project_backups/{token}/preview
"""
from __future__ import annotations

from omnia.client.base import public_request


def get_api_version() -> dict:
    return public_request("GET", "/api/versions")


# ---------------------------------------------------------------------------
# Public analysis
# ---------------------------------------------------------------------------

def get_public_analysis(analysis_id: str) -> dict:
    return public_request("GET", f"/api/v1/public/analysis/{analysis_id}")


def get_public_analysis_children(analysis_id: str) -> list[dict]:
    data = public_request("GET", f"/api/v1/public/analysis/{analysis_id}/children")
    return data.get("analyses", [])


# ---------------------------------------------------------------------------
# Public templates
# ---------------------------------------------------------------------------

def get_public_template(template_id: str) -> dict:
    return public_request("GET", f"/api/v1/public/templates/{template_id}")


# ---------------------------------------------------------------------------
# Market intelligence (fully public)
# ---------------------------------------------------------------------------

def search_market(query: str, page: int = 1, limit: int = 20) -> dict:
    return public_request(
        "GET",
        "/api/v1/public/market-intelligence/search",
        params={"search_expression": query, "page": page, "limit": limit},
    )


def get_market_package(market: str, market_id: str, version: str = "") -> dict:
    params = {}
    if version:
        params["version"] = version
    return public_request(
        "GET",
        f"/api/v1/public/market-intelligence/package/{market}/{market_id}",
        params=params or None,
    )


def get_market_package_versions(market: str, market_id: str) -> dict:
    return public_request(
        "GET",
        f"/api/v1/public/market-intelligence/package/{market}/{market_id}/versions",
    )


# ---------------------------------------------------------------------------
# Shared chat preview
# ---------------------------------------------------------------------------

def get_shared_chat(token: str) -> dict:
    data = public_request(
        "GET", f"/api/v1/public/project_backups/{token}/preview"
    )
    return data.get("project_backup_preview", data)
