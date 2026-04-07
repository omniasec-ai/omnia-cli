"""Projects and chats API."""
from __future__ import annotations

from omnia.client.base import request


def list_projects(user_id: str, search: str = "", limit: int = 50) -> list[dict]:
    params: dict = {"limit": limit}
    if search:
        params["search"] = search
    data = request("GET", f"/api/v1/app/users/{user_id}/projects", params=params)
    return data.get("projects", [])


def create_project(user_id: str, name: str, description: str = "") -> dict:
    payload: dict = {"user_id": user_id, "name": name}
    if description:
        payload["description"] = description
    data = request("POST", f"/api/v1/app/users/{user_id}/projects", json=payload)
    return data.get("project", data)


def get_project(user_id: str, project_id: str) -> dict:
    data = request("GET", f"/api/v1/app/users/{user_id}/projects/{project_id}")
    return data.get("project", data)


def delete_project(user_id: str, project_id: str) -> dict:
    return request("DELETE", f"/api/v1/app/users/{user_id}/projects/{project_id}")


def list_chats(user_id: str, project_id: str) -> list[dict]:
    data = request(
        "GET",
        f"/api/v1/app/users/{user_id}/projects/{project_id}/chats",
    )
    return data.get("chats", [])


def create_chat(user_id: str, project_id: str, name: str = "Chat") -> dict:
    data = request(
        "POST",
        f"/api/v1/app/users/{user_id}/projects/{project_id}/chats",
        json={"user_id": user_id, "project_id": project_id, "name": name},
    )
    return data.get("chat", data)


def get_or_create_chat(user_id: str, project_id: str) -> dict:
    """Return the first chat of a project, creating one if none exists."""
    chats = list_chats(user_id, project_id)
    if chats:
        return chats[0]
    return create_chat(user_id, project_id)


def create_project_with_chat(user_id: str, name: str) -> tuple[dict, dict]:
    """Create a project and its first chat, return (project, chat)."""
    project = create_project(user_id, name)
    chat = create_chat(user_id, project["id"])
    return project, chat
