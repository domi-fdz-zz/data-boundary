"""
cli.py — command-line entry point.

    data-boundary serve   run the web app (FastAPI + uvicorn), open browser
    data-boundary app     run as a native desktop window (pywebview)
    data-boundary info    show version + configured LLM backend
"""
from __future__ import annotations

import click

from . import CORE_VERSION, LOCAL_WEB_PORT


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(CORE_VERSION, prog_name="data-boundary")
def main():
    """Data Boundary - preliminary data-use review."""


@main.command()
@click.option("--web-port", default=LOCAL_WEB_PORT, show_default=True, type=int)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--no-browser", is_flag=True, help="don't auto-open a browser")
def serve(web_port, host, no_browser):
    """Start the web app on http://localhost:<web-port>/ ."""
    import threading
    import webbrowser
    import uvicorn
    from .main import app as fastapi_app

    url = f"http://localhost:{web_port}/"
    click.secho("══════════════════════════════════════════════════════", fg="green")
    click.secho("  Data Boundary ready", fg="green", bold=True)
    click.secho(f"     open in browser:  {url}", fg="green")
    click.secho("     Ctrl+C to stop.", fg="green")
    click.secho("══════════════════════════════════════════════════════", fg="green")
    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(fastapi_app, host=host, port=web_port, log_level="warning")


@main.command()
@click.option("--width", default=1180, show_default=True, type=int)
@click.option("--height", default=860, show_default=True, type=int)
def app(width, height):
    """Launch as a native desktop window (needs the 'desktop' extra: pywebview)."""
    from .desktop import run_app
    run_app(width, height)


@main.command()
def info():
    """Show version + the configured LLM backend (never the raw key)."""
    from .config import resolve_backend, has_llm_key
    ep, mdl, _k = resolve_backend()
    click.echo(f"data-boundary version        : {CORE_VERSION}")
    click.echo(f"LLM endpoint                 : {ep}")
    click.echo(f"LLM model                    : {mdl}")
    click.echo(f"LLM key configured           : {'yes' if has_llm_key() else 'no'}")


if __name__ == "__main__":
    main()
