"""Auth-related API calls."""

from __future__ import annotations

from omnia.client.base import request


def get_me() -> dict:
    return request("GET", "/api/v1/app/users/me")


def get_agents() -> list[dict]:
    data = request("GET", "/api/v1/agents")
    return data.get("agents", [])


def get_last_user_settings(user_id: str) -> dict:
    data = request("GET", f"/api/v1/app/users/{user_id}/last_settings")
    return data.get("settings", {})


def update_user_settings(user_id: str, settings: dict) -> dict:
    data = request(
        "PATCH",
        f"/api/v1/app/users/{user_id}/last_settings",
        json=settings,
    )
    return data.get("settings", {})
