"""PyInstaller entry point for the macOS desktop app."""
from __future__ import annotations

from app.desktop import run_app


if __name__ == "__main__":
    run_app(width=1180, height=860)
