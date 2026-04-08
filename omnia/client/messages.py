"""Messages API: history retrieval and streaming chat."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Optional

from omnia.client.base import iter_sse, request, stream_request
from omnia.config.settings import settings


def list_messages(user_id: str, project_id: str, chat_id: str, tag: str = "") -> list[dict]:
    params = {}
    if tag:
        params["tag"] = tag
    data = request(
        "GET",
        f"/api/v1/app/users/{user_id}/projects/{project_id}/chats/{chat_id}/messages",
        params=params or None,
    )
    return data.get("messages", data.get("chat_messages", []))


def delete_message(user_id: str, project_id: str, chat_id: str, message_id: str) -> dict:
    return request(
        "PATCH",
        f"/api/v1/app/users/{user_id}/projects/{project_id}/chats/{chat_id}/messages/{message_id}",
        json={"deleted": True},
    )


def _build_payload(
    user_id: str,
    project_id: str,
    chat_id: str,
    query: str,
    *,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    mcp_servers: Optional[list] = None,
    resources_in_context: Optional[list] = None,
    native_tools: Optional[list] = None,
    knowledges: Optional[list] = None,
    skill_ids: Optional[list] = None,
    agent_launch_id: Optional[str] = None,
    additional_info: str = "",
    streaming: bool = True,
    user_settings: Optional[dict] = None,
) -> dict:
    _model = model or settings.default_model
    _provider = provider or settings.default_provider
    payload = {
        "query": query,
        "user_id": user_id,
        "project_id": project_id,
        "chat_id": chat_id,
        "model": _model,
        "provider": _provider,
        "mcp_servers": mcp_servers or [],
        "resources_in_context": resources_in_context or [],
        "native_tools": native_tools or ["all"],
        "knowledges": knowledges or [],
        "skill_ids": skill_ids or [],
        "additional_info": additional_info,
        "streaming": streaming,
        "config": {
            "selected_model": _model,
            "selected_provider": _provider,
            "user_settings": user_settings or {},
        },
    }
    if agent_launch_id:
        payload["agent_launch_id"] = agent_launch_id
    return payload


def stream_message(
    user_id: str,
    project_id: str,
    chat_id: str,
    query: str,
    **kwargs,
) -> Iterator[dict]:
    """Yield SSE event dicts from the agent streaming endpoint."""
    payload = _build_payload(user_id, project_id, chat_id, query, streaming=True, **kwargs)
    with stream_request(
        "POST", "/api/v1/agents/OmniaMainAgent/a1/chat/run", json=payload
    ) as response:
        yield from iter_sse(response)


def send_message(
    user_id: str,
    project_id: str,
    chat_id: str,
    query: str,
    **kwargs,
) -> dict:
    """Non-streaming request (fallback)."""
    payload = _build_payload(user_id, project_id, chat_id, query, streaming=False, **kwargs)
    return request(
        "POST",
        "/api/v1/agents/OmniaMainAgent/a1/chat/run",
        json=payload,
        timeout=120.0,
    )
