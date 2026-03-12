"""Unified CLI for ChaosEngine testing servers.

Aggregates ChaosLLM and ChaosWeb under a single ``chaosengine`` command:

    chaosengine llm serve --preset=gentle
    chaosengine llm presets
    chaosengine web serve --preset=stress_scraping
    chaosengine web presets

Standalone entry points (``chaosllm``, ``chaosweb``) continue to work
unchanged — this CLI simply mounts the same Typer apps as sub-commands.
"""

from __future__ import annotations

import typer

from errorworks.llm.cli import app as llm_app
from errorworks.web.cli import app as web_app

app = typer.Typer(
    name="chaosengine",
    help="ChaosEngine: Unified chaos testing server management.",
    no_args_is_help=True,
)

app.add_typer(llm_app, name="llm", help="ChaosLLM: Fake LLM server for load testing and fault injection.")
app.add_typer(web_app, name="web", help="ChaosWeb: Fake web server for scraping pipeline resilience testing.")


def main() -> None:
    """Entry point for chaosengine CLI."""
    app()


if __name__ == "__main__":
    main()
