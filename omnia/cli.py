"""
omnia — entry point.

Launches the interactive REPL.
"""
from __future__ import annotations

from omnia.repl import OmniaREPL


def app() -> None:
    OmniaREPL().run()


if __name__ == "__main__":
    app()
