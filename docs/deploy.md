# AIOffice — Deployment & Ops

Thin-backend SaaS: browser runs the editors + engines; FastAPI handles
auth/tenant, model/search proxy, and blob/version storage. Stack = nginx
(static SPA + API reverse-proxy) → backend (FastAPI×N) → Postgres + MinIO/S3.

## One-click (docker compose)

```bash
cp .env.example .env      # fill MODEL_PROVIDER/MODEL_NAME + <PROVIDER>_API_KEY, set JWT_SECRET
docker compose up --build
```

- App: http://localhost/ (docs Shell: login → home → editor).
  Slides: http://localhost/slides/, PDF: /pdf/, Markdown: /markdown/, Sheets: /sheets/.
- MinIO console: http://localhost:9001 (aioffice / aioffice-secret).

Services: `frontend` (nginx :80), `backend` (:8585, internal), `postgres`,
`minio` + `createbucket` (one-shot bucket init).

## Build layout

- `frontend/Dockerfile` — multi-stage: `npm ci` → build all 5 SPAs
  `@genoffice/{docs,slides,pdf,markdown,sheets}` → copy dists into nginx.
- `frontend/nginx.conf` — serves docs at `/`, slides at `/slides/`, pdf `/pdf/`,
  markdown `/markdown/`, sheets `/sheets/` with SPA fallback; regex-proxies
  `/ai /auth /documents /projects /files /share /healthz` plus the `/sheets/<cmd>`
  endpoint set to `backend:8585`. `proxy_buffering off` keeps `/ai/stream` SSE
  live; `client_max_body_size 60m` covers 50MB blob uploads.
- `backend/Dockerfile` — Rust build stage bakes the `xlsx-sidecar` binary
  (calamine + ironcalc) to `/usr/local/bin/xlsx-sidecar`, then python:3.13-slim
  + uv, `uvicorn app.main:app :8585` (`XLSX_SIDECAR_BIN` already set).

## Prod checklist

- **JWT_SECRET**: 32+ random bytes. Rotating it invalidates all tokens.
- **Model key**: `<PROVIDER>_API_KEY` per `backend/app/config.py` `_PROVIDERS`.
- **DB**: compose uses local Postgres. Managed PG → set `DATABASE_URL`
  (`postgresql+asyncpg://...`). Tables auto-create on startup (`init_db`);
  Alembic migrations are deferred — a fresh DB is assumed.
- **Blob**: compose uses MinIO. Managed S3 → set `S3_ENDPOINT` (blank = local FS),
  `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`.
- **TLS**: terminate at nginx (add a 443 server + certs) or an upstream LB.
- **Quotas/limits**: `MAX_DOCS_PER_ORG`, `MAX_STORAGE_MB_PER_ORG`,
  `RATE_LIMIT_MAX/WINDOW_SEC`, `LOCK_TTL_SEC` (0 disables each).

## Scaling notes

- Backend is stateless → scale horizontally (compose `--scale backend=N` behind
  nginx upstream, or k8s HPA — see `k8s/`).
- **Rate limiter is per-replica in-process** (`app/ratelimit.py`): behind N
  replicas the effective limit is ~N×MAX. Swap for Redis INCR+EXPIRE before
  relying on it as a hard cap.
- Single-writer locks live in Postgres → correct across replicas.

## k8s skeleton

`k8s/` holds minimal manifests (backend Deployment+Service+HPA, frontend
Deployment+Service, ConfigMap/Secret stubs). PG + object storage are expected to
be managed/external; wire their URLs via the Secret. Apply with
`kubectl apply -f k8s/`.

## Health

`GET /healthz` → `{"ok": true}` (rate-limit exempt). Use for LB/k8s probes.
