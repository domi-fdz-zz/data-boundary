"""
desktop.py — run the app as a native desktop window (pywebview).

Starts FastAPI on a private localhost port in a background thread, then opens a
native OS webview window (WebKit on macOS, WebView2 on Windows, GTK on Linux)
pointed at it. No browser, no Electron, no Node — the same FastAPI + HTML the web
build uses. Pattern borrowed from statLens.

Launch:  data-boundary app
"""
from __future__ import annotations

import socket
import threading
import time
import urllib.request


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_server(url: str, timeout: float = 30.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.3)
    return False


def run_app(width: int = 1180, height: int = 860,
            server_only: bool = False) -> None:
    """Blocking: open the desktop window; returns when the window is closed.

    server_only=True starts the backend and blocks without a window (used to
    smoke-test a frozen bundle in a headless environment; also via the
    CCA_APP_SERVER_ONLY env var)."""
    import os
    server_only = server_only or bool(os.environ.get("CCA_APP_SERVER_ONLY"))

    import uvicorn
    from .main import app as fastapi_app

    port = _free_port()
    config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=port,
                            log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    if not _wait_for_server(url):
        raise SystemExit("backend failed to start.")

    if server_only:
        print(f"[data-boundary] server-only — backend live at {url}", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            server.should_exit = True
        return

    try:
        import webview  # pywebview
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "The desktop app needs pywebview. Install it with:\n"
            "    pip install pywebview\n"
            f"(import error: {e})"
        )
    webview.create_window("Data Boundary", url,
                          width=width, height=height, min_size=(900, 640))
    webview.start()
    server.should_exit = True
