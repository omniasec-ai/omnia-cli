"""Resources API (files attached to projects)."""

from __future__ import annotations

from pathlib import Path

from omnia.client.base import request


def list_resources(user_id: str, project_id: str) -> list[dict]:
    data = request("GET", f"/api/v1/app/users/{user_id}/projects/{project_id}/resources")
    return data.get("resources", [])


def upload_resource(user_id: str, project_id: str, file_path: Path) -> dict:
    with open(file_path, "rb") as fh:
        files = {"file": (file_path.name, fh, "application/octet-stream")}
        data = request(
            "POST",
            f"/api/v1/app/users/{user_id}/projects/{project_id}/resources",
            files=files,
            timeout=120.0,
        )
    return data.get("resource", data)


def delete_resource(user_id: str, project_id: str, resource_id: str) -> dict:
    return request(
        "DELETE",
        f"/api/v1/app/users/{user_id}/projects/{project_id}/resources/{resource_id}",
    )
