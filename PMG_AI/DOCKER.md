# Dockerizing PMG_AI (React + Node + Flask ML)

This document records how the application was containerized, how to run it (including in GitHub Codespaces),
how it was tested end to end, and the problems met along the way.

## 1. Architecture

```
Browser --:8080--> frontend (nginx + React build) --/api--> backend (Node/Express :4000) --X-API-Key--> ml (Flask/waitress :5001)
```

| Service | Image base | Port | Role |
|---|---|---|---|
| `frontend` | `node:22-alpine` (build) -> `nginx:1.27-alpine` | 8080 (published) | Serves the Vite build; proxies `/api/` to the backend so the browser sees one origin and the httpOnly cookie works |
| `backend` | `node:22-alpine` | 4000 (internal) | Auth, validation, claim IDs, uploads, calls the ML service |
| `ml` | `python:3.12-slim` | 5001 (internal) | Loads `artifacts/pmg_predictor.joblib` once, serves `/v1/predict` |

## 2. What was learned from reading the repo (and why each decision was made)

| Finding | Consequence |
|---|---|
| `ml_service/serve.py` binds to `ML_HOST` (default `127.0.0.1`) | Image sets `ML_HOST=0.0.0.0`, otherwise no other container could reach it |
| Backend reads `ML_URL`, `ML_API_KEY`, `JWT_SECRET`, `LOG_DIR`, `UPLOAD_DIR`, `DATA_DIR` (`backend/src/config.js`) | All configured through environment variables; state paths point to one volume (`/var/pmg`) |
| With `NODE_ENV=production` the backend refuses to start without `JWT_SECRET` and a non-default `ML_API_KEY` | Compose requires both from `.env` (`${VAR:?message}`) |
| Login cookie is `Secure` in production | Works on `localhost` and the Codespaces HTTPS URL, not on plain http over another host name |
| `scikit-learn==1.7.2` is pinned to match the joblib model | Python 3.12 base image (3.14 is too new for that wheel) |
| `ml_service/app.py` imports `pmg_predict.py` and the artifact from the parent folder | ML build context is `PMG_AI/`, not `ml_service/` |
| The frontend calls relative `/api` URLs | nginx proxies `/api/` to the backend; no CORS needed |

## 3. Files added

| File | Purpose |
|---|---|
| `ml_service/Dockerfile` | ML image; non-root user, `/health` healthcheck |
| `backend/Dockerfile` | Backend image; `npm ci --omit=dev`, non-root `node` user, healthcheck on `/api/health` |
| `frontend/Dockerfile` | Multi-stage: Vite build, then nginx |
| `frontend/nginx.conf` | Static files, SPA fallback, `/api/` proxy to `backend:4000`, 20 MB upload limit |
| `docker-compose.yml` | Three services; only the frontend publishes a port; `backend` waits for `ml` to be healthy; named volumes `ml-logs`, `pmg-state` |
| `docker-compose.hostnet.yml` + `frontend/nginx.hostnet.conf` | Override that runs everything with `network_mode: host` (needed in this Codespace, see section 6) |
| `.env.docker.example` | Template for `ML_API_KEY`, `JWT_SECRET`, `LOG_LEVEL` |
| `.dockerignore` (root, `backend/`, `frontend/`) | Keeps `node_modules`, `.env`, logs and caches out of images |
| `.gitignore` (edited) | Ignores `.env` so secrets are never committed |

## 4. How to run

### 4.1 Normal Docker host

```bash
cd PMG_AI
cp .env.docker.example .env
# edit .env: set ML_API_KEY and JWT_SECRET (e.g. `openssl rand -hex 32`)
docker compose up --build -d
docker compose ps                      # wait until ml and backend are (healthy)
curl localhost:8080/api/health         # {"backend":"ok","ml":"ok"}
```

Open port 8080 (in Codespaces: Ports tab) and sign in as `alice@example.com` / `Passw0rd!`
(demo users: alice, bob, carol, all with the same password).

### 4.2 This Codespace (host networking)

```bash
cd PMG_AI
export COMPOSE_FILE=docker-compose.yml:docker-compose.hostnet.yml
docker compose up --build -d
docker compose ps
```

Stop with `docker compose down` (add `-v` to also delete the uploads/log volumes).

## 5. End-to-end test performed

All calls go through the nginx container on port 8080, so the whole chain is exercised.

| Step | Command / action | Result |
|---|---|---|
| 1 | `docker compose up --build -d` | 3 images built, containers started |
| 2 | Wait for health | `ml` and `backend` healthy |
| 3 | `curl localhost:8080/` | React `index.html` served by nginx |
| 4 | `curl localhost:8080/api/health` | `{"backend":"ok","ml":"ok"}` |
| 5 | `POST /api/auth/login` (alice) | 200, cookie set |
| 6 | `POST /api/claims/draft` | `CLM-20261017-054633` |
| 7 | `POST /api/claims` multipart, flight, $60 cheaper, verified proof | **APPROVE**, P(approved) 0.9214 |
| 8 | Same flow as bob (suspended account), cruise, 50% cheaper, unclear proof | **REJECT**, P(approved) 0.2052 |
| 9 | `GET /api/claims` | Alice's claim listed |
| 10 | Re-submit with the same claim ID | Rejected (replay protection) |
| 11 | `docker compose logs ml` | `model Random Forest predicted P(approved)=0.2052 -> REJECT in 143.4 ms` |
| 12 | `/var/pmg/logs/ml-exchange.jsonl` in the backend container | One audit line per ML call, HTTP 200 |

Decision rule (threshold 0.5056, band 0.07): APPROVE if P >= 0.5756, REFER TO ADVISOR within 0.07 of the threshold, otherwise REJECT.

Inference directly against the ML container (bypassing backend and UI) needs the ML port published or the host network:

```bash
curl -s localhost:5001/health
curl -s -H "X-API-Key: $ML_API_KEY" -H "Content-Type: application/json" -d @claim.json localhost:5001/v1/predict
```

The payload fields are those in `demo_claims.py`; the backend builds them for you.

## 6. Problems met and how they were solved

| Problem | Cause | Resolution |
|---|---|---|
| Backend `/api/health` returned 503 and nginx returned 504 with the plain compose file | Codespace has a stale `iptables-legacy` ruleset (`FORWARD` policy `DROP`, rules only for `docker0`), so traffic between containers on any user-defined bridge network is dropped (even `ping`) | Added `docker-compose.hostnet.yml` (host networking). A one-line firewall rule (`iptables-legacy -I FORWARD -i br+ -o br+ -j ACCEPT`) would also fix it, but changing the host firewall was not approved, so it was not applied |
| `parent snapshot ... does not exist` during `docker compose build` | Stale BuildKit cache after the Docker store was partly reset | `docker builder prune -af`, then rebuilt |

## 7. Production notes

- Users and claims are demo-grade (in-memory users, JSON file storage). Replace with a real identity provider and database before real use.
- Keep `ML_API_KEY` and `JWT_SECRET` out of git; `.env` is git-ignored.
- Images: ml ~670 MB, backend ~265 MB, frontend ~75 MB.
- Other deployment options: single combined image (backend serving `frontend/dist` via `FRONTEND_DIST`), `docker run` with a user-defined network, a dev container, or pushing the images to GHCR for Kubernetes / Azure Container Apps / Cloud Run.
