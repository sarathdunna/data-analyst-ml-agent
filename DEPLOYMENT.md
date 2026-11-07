# Deployment Guide

## Option A: Docker Compose (single machine / VM)

1. `cp .env.example .env` and fill in `ANTHROPIC_API_KEY` if desired.
2. `docker compose up --build -d`
3. Backend on port 8000, frontend on port 5173 (nginx serving the built SPA).
4. For a production VM, put nginx/Caddy in front for TLS and point it at
   ports 5173 (frontend) and 8000 (API), or bake the API URL into the
   frontend build (`--build-arg VITE_API_URL=https://api.yourdomain.com`).

## Option B: Vercel (frontend) + Render (backend)

### Backend on Render

The repo includes a `render.yaml` Blueprint, so most settings are filled in for you.

1. On Render: **New -> Blueprint** -> connect this GitHub repo.
2. Render reads `render.yaml`: web service `data-analyst-ml-agent-api`, root
   `backend/`, Python 3.12, free plan, health check `/api/health`.
3. When asked for environment variables:
   - `FRONTEND_URL`: leave a placeholder (e.g. `http://localhost:5173`) for now;
     you set the real Vercel URL after step 2 of the frontend.
   - `ANTHROPIC_API_KEY`: leave **empty** for a public demo (the keyword fallback
     answers questions without it). Setting it means visitors spend your credits.
4. Deploy and note the URL, e.g. `https://data-analyst-ml-agent-api.onrender.com`.
   Check `https://<that-url>/api/health` returns `{"status": "ok"}`.

Manual setup (without the Blueprint): New -> Web Service, root directory
`backend`, build `pip install -r requirements.txt`, start
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and set `PYTHON_VERSION=3.12.7`
(the pinned numpy/scipy versions have no Python 3.13 wheels).

Free-plan notes: the service sleeps after ~15 minutes idle, so the first request
takes ~1 minute to wake it. The filesystem is temporary: uploaded datasets,
trained models and the SQLite database reset on every restart or deploy. For a
demo that's fine; use a paid plan with a Render Disk mounted at `backend/` paths
if they must persist.

### Frontend on Vercel

1. On Vercel: **Add New -> Project** -> import this repo.
2. Set **Root Directory** to `frontend`. Vercel detects Vite (build
   `npm run build`, output `dist`).
3. Environment variable: `VITE_API_URL=https://<your-render-url>` (no trailing slash).
4. Deploy and note the URL, e.g. `https://data-analyst-ml-agent.vercel.app`.
   `frontend/vercel.json` rewrites all routes to `index.html`, so refreshing
   `/eda` or `/ml-studio` works.
5. Back on Render, set `FRONTEND_URL` to the Vercel URL (several URLs can be
   comma-separated; trailing slashes are ignored) and save; Render redeploys.

## Environment variable summary

| Variable | Where | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | backend | Enables LLM explanations; omit to run without AI |
| `LLM_PROVIDER` | backend | Currently only `anthropic` supported |
| `LLM_MODEL` | backend | Claude model ID (default `claude-opus-5-5`) |
| `FRONTEND_URL` | backend | CORS allow-origin |
| `BACKEND_URL` | backend | Informational; not required by code |
| `MAX_UPLOAD_MB` | backend | Upload size limit |
| `VITE_API_URL` | frontend | Base URL the SPA calls |

## Post-deploy checklist

- [ ] `GET /api/health` returns `{"status": "ok"}`
- [ ] CORS allows the deployed frontend origin
- [ ] File upload works end-to-end (small CSV)
- [ ] `.env` / secrets are not committed to git
- [ ] Backend logs do not show unhandled tracebacks reaching clients (500s
      return a generic message; details are server-side only)
