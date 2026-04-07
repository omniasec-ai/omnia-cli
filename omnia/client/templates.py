"""Templates API."""
from __future__ import annotations

from omnia.client.base import request


def list_templates(user_id: str, search: str = "") -> list[dict]:
    params = {}
    if search:
        params["search"] = search
    data = request(
        "GET", f"/api/v1/app/users/{user_id}/templates", params=params or None
    )
    return data.get("templates", [])


def get_template(user_id: str, template_id: str) -> dict:
    return request("GET", f"/api/v1/app/users/{user_id}/templates/{template_id}")


def create_template(user_id: str, payload: dict) -> dict:
    return request("POST", f"/api/v1/app/users/{user_id}/templates", json=payload)


def update_template(user_id: str, template_id: str, payload: dict) -> dict:
    return request(
        "PATCH",
        f"/api/v1/app/users/{user_id}/templates/{template_id}",
        json=payload,
    )


def delete_template(user_id: str, template_id: str) -> dict:
    return request("DELETE", f"/api/v1/app/users/{user_id}/templates/{template_id}")


def fork_template(user_id: str, template_id: str) -> dict:
    return request(
        "POST",
        f"/api/v1/app/users/{user_id}/templates/fork",
        json={"template_id": template_id},
    )
