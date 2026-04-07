"""File analysis API."""

from __future__ import annotations

from pathlib import Path

from omnia.client.base import request


def list_analyses(user_id: str, shared: bool = False) -> list[dict]:
    path = f"/api/v1/app/users/{user_id}/analysis"
    if shared:
        path += "/shared"
    data = request("GET", path)
    return data.get("analyses", [])


def get_analysis(analysis_id: str) -> dict:
    return request("GET", f"/api/v1/app/analysis/{analysis_id}")


def get_analysis_children(analysis_id: str) -> list[dict]:
    data = request("GET", f"/api/v1/app/analysis/{analysis_id}/childs")
    return data.get("analyses", [])


def upload_file(user_id: str, file_path: Path) -> dict:
    """Upload a file and trigger analysis. Returns the analysis object."""
    with open(file_path, "rb") as fh:
        files = {"file": (file_path.name, fh, "application/octet-stream")}
        return request(
            "POST",
            f"/api/v1/app/users/{user_id}/analysis",
            files=files,
            timeout=120.0,
        )
