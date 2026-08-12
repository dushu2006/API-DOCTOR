"""Start the backend and the trigger in two separate terminals.

Usage:
- Run this from the `api-doctor-backend` folder with `python run.py`.
- On Windows this opens two PowerShell windows: one running the backend
  (with `SANDBOX_MODE=local`) and one running the repo-level
  `auto_trigger.py` script. On POSIX it spawns two background processes.

This makes it easy to see backend logs in one terminal while the
automatic trigger/poller runs in the other.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path


def _is_windows() -> bool:
    return platform.system().lower().startswith("windows")


def start_terminals() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    api_dir = Path(__file__).resolve().parent
    trigger_script = repo_root / "auto_trigger.py"

    # Backend command: run uvicorn with SANDBOX_MODE=local so the MockAIClient is used.
    if _is_windows():
            # Use a single PowerShell -Command invocation that sets the env var
            # and then runs uvicorn. Keep the console open with -NoExit so logs
            # are visible.
            backend_cmd = (
                'start "" powershell -NoExit -Command "$Env:SANDBOX_MODE=\'local\'; '
                "python -u -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
                '"'
            )

        trigger_cmd = f'start "" powershell -NoExit -Command "python -u {str(trigger_script)}"'

        # Launch two new console windows.
        subprocess.Popen(backend_cmd, shell=True, cwd=str(api_dir))
        subprocess.Popen(trigger_cmd, shell=True, cwd=str(repo_root))

    else:
        # POSIX: start processes in background and print PIDs.
        env = os.environ.copy()
        env["SANDBOX_MODE"] = "local"

        backend_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=str(api_dir),
            env=env,
        )

        trigger_proc = subprocess.Popen(
            [sys.executable, str(trigger_script)], cwd=str(repo_root)
        )

        print(f"Backend started (pid={backend_proc.pid}), trigger started (pid={trigger_proc.pid})")


if __name__ == "__main__":
    start_terminals()

