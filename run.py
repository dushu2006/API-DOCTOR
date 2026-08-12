#!/usr/bin/env python3
"""Run the API Doctor real project debugging system (backend + frontend).

Usage:
    python run.py

1. Verifies Python 3.11+ and Node.js environment.
2. Installs required dependencies if needed.
3. Loads environment variables from .env.
4. Validates required configuration.
5. Starts FastAPI backend.
6. Starts Vite frontend.
7. Opens browser workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = REPO_ROOT / "api-doctor-backend"
FRONTEND_DIR = REPO_ROOT / "api-doctor-frontend"
PRINT_LOCK = threading.Lock()

# Import names that must be present before uvicorn loads app.main.
# fastapi/uvicorn alone is not enough — an older or partial venv can
# import those and still crash on sqlalchemy, cryptography, etc.
REQUIRED_BACKEND_MODULES: tuple[str, ...] = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic_settings",
    "dotenv",
    "httpx",
    "tenacity",
    "docker",
    "sqlalchemy",
    "cryptography",
)


class LauncherError(RuntimeError):
    """Raised when a service cannot be prepared or started."""


def _print(message: str = "") -> None:
    with PRINT_LOCK:
        print(message, flush=True)


def _load_env_file() -> None:
    """Load environment variables from .env files if present."""
    for env_path in [REPO_ROOT / ".env", BACKEND_DIR / ".env"]:
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass


def _validate_configuration() -> None:
    """Validate and log configuration state."""
    ai_key = os.getenv("NVIDIA_API_KEY", "")
    ai_provider = os.getenv("AI_PROVIDER", "auto")
    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/api_doctor.db")

    _print("\n=== API DOCTOR CONFIGURATION ===")
    _print(f"✓ Database: {database_url}")
    _print("○ Project integrations: configured in-app and stored in the database")

    if ai_key:
        _print(f"✓ AI Provider: NVIDIA NIM (Provider={ai_provider})")
    else:
        _print(f"○ AI Provider: Local deterministic engine (Provider={ai_provider})")
    _print("=================================\n")


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _run_setup(command: Sequence[str], cwd: Path, description: str) -> None:
    _print(f"[setup] {description}...")
    try:
        subprocess.run(list(command), cwd=cwd, check=True)
    except FileNotFoundError as exc:
        raise LauncherError(f"Command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise LauncherError(f"{description} failed with exit code {exc.returncode}") from exc


def _requirements_hash(requirements: Path) -> str:
    return hashlib.sha256(requirements.read_bytes()).hexdigest()


def _requirements_stamp_path(venv_dir: Path) -> Path:
    return venv_dir / ".api-doctor-requirements.sha256"


def _requirements_are_current(venv_dir: Path, requirements: Path) -> bool:
    stamp = _requirements_stamp_path(venv_dir)
    if not stamp.is_file() or not requirements.is_file():
        return False
    try:
        return stamp.read_text(encoding="utf-8").strip() == _requirements_hash(requirements)
    except OSError:
        return False


def _write_requirements_stamp(venv_dir: Path, requirements: Path) -> None:
    venv_dir.mkdir(parents=True, exist_ok=True)
    _requirements_stamp_path(venv_dir).write_text(
        _requirements_hash(requirements), encoding="utf-8"
    )


def _missing_backend_modules(python: Path) -> list[str]:
    """Return required modules that the given interpreter cannot import."""
    script = (
        "import importlib.util, sys\n"
        "missing = [name for name in sys.argv[1:] "
        "if importlib.util.find_spec(name) is None]\n"
        "sys.stdout.write('\\n'.join(missing))\n"
    )
    try:
        result = subprocess.run(
            [str(python), "-c", script, *REQUIRED_BACKEND_MODULES],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
        )
    except OSError:
        return list(REQUIRED_BACKEND_MODULES)
    if result.returncode != 0 and not result.stdout.strip():
        return list(REQUIRED_BACKEND_MODULES)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _install_backend_requirements(python: Path, requirements: Path) -> None:
    _run_setup(
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        BACKEND_DIR,
        "Upgrading pip in the backend virtual environment",
    )
    _run_setup(
        [str(python), "-m", "pip", "install", "-r", str(requirements)],
        BACKEND_DIR,
        "Installing backend dependencies",
    )


def _prepare_backend(skip_install: bool) -> Path:
    requirements = BACKEND_DIR / "requirements.txt"
    if not requirements.is_file():
        raise LauncherError(f"Backend requirements file is missing: {requirements}")
    venv_dir = BACKEND_DIR / ".venv"
    python = _venv_python(venv_dir)

    if not python.exists():
        # Allow a fully provisioned system/conda interpreter when no venv exists.
        if not _missing_backend_modules(Path(sys.executable)):
            return Path(sys.executable)

        if skip_install:
            raise LauncherError(
                f"Backend environment is missing. Run: {sys.executable} -m venv {venv_dir}"
            )
        _run_setup(
            [sys.executable, "-m", "venv", str(venv_dir)],
            REPO_ROOT,
            "Creating backend virtual environment",
        )

    missing = _missing_backend_modules(python)
    stale_requirements = not _requirements_are_current(venv_dir, requirements)
    if missing or stale_requirements:
        if skip_install:
            detail = ", ".join(missing) if missing else "requirements.txt changed"
            raise LauncherError(
                f"Backend dependencies are missing ({detail}). Run: "
                f"{python} -m pip install -r {requirements}"
            )
        if missing:
            _print(f"[setup] Backend is missing: {', '.join(missing)}")
        elif stale_requirements:
            _print("[setup] Backend requirements.txt changed; syncing virtual environment")
        _install_backend_requirements(python, requirements)
        still_missing = _missing_backend_modules(python)
        if still_missing:
            raise LauncherError(
                "Backend still missing after install: "
                + ", ".join(still_missing)
                + f". Try: {python} -m pip install -r {requirements}"
            )
        _write_requirements_stamp(venv_dir, requirements)

    return python


def _find_npm() -> str:
    npm = shutil.which("npm.cmd") if os.name == "nt" else shutil.which("npm")
    if not npm:
        raise LauncherError("npm was not found. Install Node.js 20+ and try again.")
    return npm


def _prepare_frontend(skip_install: bool) -> str:
    npm = _find_npm()
    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.is_dir():
        if skip_install:
            raise LauncherError(
                f"Frontend dependencies are missing. Run `npm install` in {FRONTEND_DIR}."
            )
        lockfile = FRONTEND_DIR / "package-lock.json"
        install_command = [npm, "ci"] if lockfile.exists() else [npm, "install"]
        _run_setup(install_command, FRONTEND_DIR, "Installing frontend dependencies")
    return npm


def _popen(command: Sequence[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    kwargs: dict = {
        "cwd": cwd,
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(list(command), **kwargs)


def _stream_output(label: str, process: subprocess.Popen[str]) -> None:
    if process.stdout is None:
        return
    for line in process.stdout:
        _print(f"[{label}] {line.rstrip()}")


def _start_services(
    python: Path,
    npm: str,
    backend_host: str,
    backend_port: int,
    frontend_host: str,
    frontend_port: int,
    reload_backend: bool,
) -> list[tuple[str, subprocess.Popen[str]]]:
    backend_env = os.environ.copy()
    backend_env.setdefault("SANDBOX_MODE", "local")
    backend_env.setdefault("PYTHONUNBUFFERED", "1")
    backend_env.setdefault("DEMO_MODE", "false")

    backend_command = [
        str(python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        backend_host,
        "--port",
        str(backend_port),
    ]
    if reload_backend:
        backend_command.append("--reload")

    frontend_env = os.environ.copy()
    frontend_env["VITE_BACKEND_URL"] = f"http://{backend_host}:{backend_port}"
    frontend_command = [
        npm,
        "run",
        "dev",
        "--",
        "--host",
        frontend_host,
        "--port",
        str(frontend_port),
        "--strictPort",
    ]

    backend = _popen(backend_command, BACKEND_DIR, backend_env)
    frontend = _popen(frontend_command, FRONTEND_DIR, frontend_env)
    services = [("backend", backend), ("frontend", frontend)]

    for label, process in services:
        threading.Thread(
            target=_stream_output,
            args=(label, process),
            daemon=True,
            name=f"{label}-log-stream",
        ).start()

    return services


def _url_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _wait_for_url(
    name: str,
    url: str,
    services: list[tuple[str, subprocess.Popen[str]]],
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for label, process in services:
            return_code = process.poll()
            if return_code is not None:
                raise LauncherError(
                    f"{label.capitalize()} exited early with code {return_code}"
                )
        if _url_ready(url):
            _print(f"[ready] {name}: {url}")
            return
        time.sleep(0.25)
    raise LauncherError(f"Timed out waiting for {name} at {url}")


def _browser_host(host: str) -> str:
    if host in {"0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return host


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _stop_services(services: list[tuple[str, subprocess.Popen[str]]]) -> None:
    if not services:
        return
    _print("\n[shutdown] Stopping frontend and backend...")
    for _, process in reversed(services):
        _terminate_process(process)


def _monitor_services(services: list[tuple[str, subprocess.Popen[str]]]) -> int:
    while True:
        for label, process in services:
            return_code = process.poll()
            if return_code is not None:
                _print(f"[error] {label.capitalize()} stopped with exit code {return_code}.")
                return return_code or 1
        time.sleep(0.5)


def _install_signal_handlers() -> None:
    def _raise_keyboard_interrupt(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _raise_keyboard_interrupt)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start API Doctor real project debugging system (backend + frontend)."
    )
    parser.add_argument("--backend-host", default="0.0.0.0")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-host", default="0.0.0.0")
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument(
        "--reload-backend",
        action="store_true",
        help="Restart the backend automatically when Python files change.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the frontend in the default browser.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Fail instead of installing missing Python or Node dependencies.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=90.0,
        help="Seconds to wait for each service to become ready (default: 90).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    services: list[tuple[str, subprocess.Popen[str]]] = []
    frontend_url = f"http://{_browser_host(args.frontend_host)}:{args.frontend_port}"
    backend_health_url = f"http://{_browser_host(args.backend_host)}:{args.backend_port}/health"

    _install_signal_handlers()

    try:
        if sys.version_info < (3, 11):
            raise LauncherError("Python 3.11 or newer is required.")
        if not BACKEND_DIR.is_dir() or not FRONTEND_DIR.is_dir():
            raise LauncherError(
                "Run this script from an intact API Doctor repository checkout."
            )

        _load_env_file()
        _validate_configuration()

        python = _prepare_backend(args.skip_install)
        npm = _prepare_frontend(args.skip_install)

        _print("[start] Launching API Doctor backend and frontend...")
        services = _start_services(
            python=python,
            npm=npm,
            backend_host=args.backend_host,
            backend_port=args.backend_port,
            frontend_host=args.frontend_host,
            frontend_port=args.frontend_port,
            reload_backend=args.reload_backend,
        )

        _wait_for_url("backend", backend_health_url, services, args.startup_timeout)
        _wait_for_url("frontend", frontend_url, services, args.startup_timeout)

        if not args.no_browser:
            _print(f"[browser] Opening {frontend_url}")
            try:
                opened = webbrowser.open(frontend_url, new=2)
            except Exception:
                opened = False
            if not opened:
                _print(f"[browser] Visit {frontend_url}")
        else:
            _print(f"[browser] Automatic browser launch disabled. Visit {frontend_url}")

        _print("[running] API Doctor is ready. Press Ctrl+C to stop both services.")
        return _monitor_services(services)
    except KeyboardInterrupt:
        _print("\n[shutdown] Ctrl+C received.")
        return 0
    except LauncherError as exc:
        _print(f"[error] {exc}")
        return 1
    finally:
        _stop_services(services)


if __name__ == "__main__":
    raise SystemExit(main())
