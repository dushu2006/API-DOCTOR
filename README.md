# API Doctor

AI-assisted, point-in-time backend diagnosis, repair generation, sandbox verification, and pull-request workflow with a FastAPI backend and React/Vite dashboard. Diagnosis state is ephemeral: only the current run exists, and no diagnosis history is stored.

## Run the full project locally

Prerequisites:

- Python 3.11+
- Node.js 20+ with npm
- Docker Desktop is optional; local sandbox mode is used by default when it is not configured

From the repository root, run:

```bash
python run.py
```

The launcher will:

1. Create `api-doctor-backend/.venv` and install every package in `api-doctor-backend/requirements.txt` when any runtime import (including SQLAlchemy) is missing or the requirements file has changed.
2. Install frontend packages when `node_modules` is missing.
3. Start FastAPI at `http://127.0.0.1:8000`.
4. Start Vite at `http://127.0.0.1:5173`.
5. Wait for both services and open the dashboard in your default browser.
6. Stop both services when you press Ctrl+C.

Useful options:

```bash
python run.py --no-browser          # start without opening a browser
python run.py --reload-backend      # reload FastAPI after Python changes
python run.py --skip-install        # do not install missing dependencies
python run.py --backend-port 9000 --frontend-port 3000
python run.py --help
```

The launcher passes the selected backend address to Vite's same-origin development proxy. Browser code therefore talks to `/api` and `/health` without relying on a hardcoded localhost API URL.

For service-specific configuration and API documentation, see:

- [api-doctor-backend/README.md](api-doctor-backend/README.md)
- [api-doctor-frontend/README.md](api-doctor-frontend/README.md)
