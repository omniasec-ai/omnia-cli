"""Workflows API."""

from __future__ import annotations

from omnia.client.base import request


def run_file_analysis(
    user_id: str,
    project_id: str,
    resource_hash: str,
    chat_id: str,
) -> dict:
    """Run the FileAnalysisWorkflow and return {analysis_id, filename, file_hash}."""
    return request(
        "POST",
        "/api/v1/workflows/FileAnalysisWorkflow/run",
        json={
            "user_id": user_id,
            "project_id": project_id,
            "resource_hash": resource_hash,
            "chat_id": chat_id,
        },
    )
