"""
Live SSE streaming renderer.

Drives the streaming loop: receives SSE dicts, prints content
incrementally and signals completion.
"""
from __future__ import annotations

from collections.abc import Iterator

from rich.console import Console
from rich.live import Live
from rich.text import Text

from omnia.ui.messages import render_streaming_chunk

console = Console()


def run_stream(events: Iterator[dict]) -> str:
    """
    Consume SSE events from `events` and render them to the terminal
    in real time.  Returns the full accumulated text.
    """
    buffer: list[str] = []
    current_type: str | None = None

    console.print()
    console.print("[bold blue]Omnia[/bold blue]")

    try:
        for event in events:
            component_type = event.get("component_type", "assistant")

            # Print a separator when message type changes mid-stream
            if current_type and current_type != component_type:
                console.print()

            current_type = component_type
            render_streaming_chunk(event, buffer)

    except KeyboardInterrupt:
        console.print("\n[dim](interrupted)[/dim]")
    finally:
        console.print()  # newline after streamed content

    return "".join(buffer)
