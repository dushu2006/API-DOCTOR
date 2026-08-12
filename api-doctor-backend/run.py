#!/usr/bin/env python3
"""Start the FastAPI backend on http://127.0.0.1:8000.

Usage:
    python run.py

For the full local stack (backend + frontend + browser), run `python run.py`
from the repository root instead.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent


def main() -> int:
    env = os.environ.copy()
    env.setdefault("SANDBOX_MODE", "local")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
        cwd=BACKEND_DIR,
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
