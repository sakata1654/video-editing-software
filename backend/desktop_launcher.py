"""
Desktop executable launcher for Islamic Video Studio.
Starts the FastAPI backend (which also serves the bundled React frontend)
and opens the web app in the user's default browser.
"""
from __future__ import annotations

import argparse
import multiprocessing
import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from app.main import app


def _find_available_port(preferred: int = 8000) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_health(url: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(description="Islamic Video Studio Desktop Launcher")
    parser.add_argument("--port", type=int, default=0, help="Port to listen on (default: 8000 or next free)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--smoke-test", action="store_true", help="Start server, verify /health, and exit")
    args = parser.parse_args()

    port = args.port if args.port > 0 else _find_available_port(8000)
    base_url = f"http://127.0.0.1:{port}"

    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        workers=1,
    )
    server = uvicorn.Server(config)

    if args.smoke_test:
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        ok = _wait_for_health(base_url, timeout=20.0)
        server.should_exit = True
        thread.join(timeout=5.0)
        if not ok:
            print("Smoke test failed: /health did not respond")
            return 1
        print(f"Smoke test passed on {base_url}")
        return 0

    if not args.no_browser:
        def _open_when_ready() -> None:
            if _wait_for_health(base_url, timeout=25.0):
                print(f"\nIslamic Video Studio is running at {base_url}")
                print("Close this window to stop the application.\n")
                webbrowser.open(base_url)

        threading.Thread(target=_open_when_ready, daemon=True).start()

    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
