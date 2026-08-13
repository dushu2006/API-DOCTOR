# API Doctor frontend

React/Vite dashboard for API Doctor's current diagnosis workflow. It subscribes to live progress over Server-Sent Events and renders retrieved source context, generated diffs, sandbox results, and pull-request details. The UI has no history view: a fresh start clears the current report, and backend diagnosis data is never persisted.

## Run locally

The easiest way to start the backend, frontend, and browser together is from the repository root:

```bash
python run.py
```

To start only this frontend, start the backend first on port 8000, then:

```bash
npm install
npm run dev
```

Open the URL printed by Vite. In development, Vite proxies same-origin `/api` and `/health` requests to `http://localhost:8000`, so the browser does not need a hardcoded backend origin.

## Configuration

- `VITE_BACKEND_URL`: backend target used only by the Vite development proxy. Defaults to `http://localhost:8000`.
- `VITE_API_BASE_URL`: optional browser-facing API origin for deployments where the frontend and backend are hosted separately. Leave unset for same-origin deployments.

Example:

```bash
VITE_BACKEND_URL=http://localhost:9000 npm run dev
```

## Checks

```bash
npm run lint
npm run build
```
