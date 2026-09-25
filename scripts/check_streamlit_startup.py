"""Start a fresh Streamlit server and exercise city selection without generating a trip.

Uses the optional Playwright/Chrome browser check. The temporary server inherits
the environment unchanged and is stopped afterwards. No API-key handling occurs.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


def main():
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryFile(mode="w+b") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py",
             "--server.headless=true", "--server.address=127.0.0.1",
             f"--server.port={port}", "--browser.gatherUsageStats=false", "--theme.base=dark"],
            cwd=root, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError("The temporary Streamlit server exited during startup.")
                try:
                    with urlopen(url + "/_stcore/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Streamlit did not become healthy within 30 seconds.")
            # Health alone does not execute app.py; a browser session is essential.
            subprocess.run(
                [sys.executable, "-B", "scripts/check_location_ui.py", "--url", url],
                cwd=root, check=True, timeout=90,
            )
            print("PASS: fresh 'streamlit run app.py' startup and browser-rendered location UI.")
        finally:
            if server.poll() is None:
                if os.name == "nt":
                    # Stop only the process tree started by this check (venv launchers
                    # may have a child interpreter). Leave the user's app untouched.
                    subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    main()
