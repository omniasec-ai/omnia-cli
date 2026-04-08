"""
Live SSE streaming renderer.

Drives the streaming loop: receives SSE dicts, prints content
incrementally and signals completion.
"""

from __future__ import annotations

from collections.abc import Iterator

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text  # used by Spinner(text=Text(...))

from omnia.ui.messages import render_streaming_chunk

console = Console()


def run_stream(events: Iterator[dict], model: str = "") -> str:
    """
    Consume SSE events from `events` and render them to the terminal
    in real time.  Returns the full accumulated text.
    """
    buffer: list[str] = []
    current_type: str | None = None

    model_hint = f" [dim]({model})[/dim]" if model else ""
    console.print()
    console.print(f"[bold blue]Omnia[/bold blue]{model_hint}")

    spinner = Spinner("dots2", text=Text(" thinking…", style="dim italic"), style="bold blue")

    events_iter = iter(events)

    # Show spinner until the first event arrives
    first_event = None
    try:
        with Live(
            spinner,
            console=console,
            refresh_per_second=15,
            transient=True,
        ):
            first_event = next(events_iter)
    except StopIteration:
        console.print()
        return ""
    except KeyboardInterrupt:
        console.print("\n[dim](interrupted)[/dim]")
        return ""

    # Process all events (first + rest) normally
    try:
        import itertools

        for event in itertools.chain([first_event], events_iter):
            component_type = event.get("component_type", "assistant")

            if current_type and current_type != component_type:
                console.print()

            current_type = component_type
            render_streaming_chunk(event, buffer)

    except KeyboardInterrupt:
        console.print("\n[dim](interrupted)[/dim]")
    finally:
        console.print()

    return "".join(buffer)
