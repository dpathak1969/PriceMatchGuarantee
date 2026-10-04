# Instructions – install, run, verify

Three components, one system:

| # | Component | Tech | Folder | Port |
| :- | :- | :- | :- | :- |
| 1 | **ML endpoint** | Python · Flask (served by waitress) | `ml_service/` | 5001 |
| 2 | **Backend** | Node.js · Express | `backend/` | 4000 |
| 3 | **Frontend** | React · Vite | `frontend/` | 5173 (dev) |

Start order matters: **ML → Backend → Frontend**.

## 0. Prerequisites

* Python 3.11+ (tested 3.13) and Node.js 20+ (tested 24 LTS; Windows: `winget install OpenJS.NodeJS.LTS`).
* Open a **new** terminal after installing Node so `node`/`npm` are on the PATH.

## 1. One-time install

```powershell
cd PMG_AI

# ML endpoint
python -m venv VENV_PMG
.\VENV_PMG\Scripts\Activate.ps1
pip install -r requirements.txt          # numpy, pandas, scikit-learn 1.7.2, flask, waitress ...

# Backend
cd backend
npm install
copy .env.example .env                   # optional; defaults work for local development
cd ..

# Frontend
cd frontend
npm install
cd ..
```

## 2. Start everything

**Option A – one command (Windows):** `.\start-all.ps1` opens three windows (ML, backend, frontend).

**Option B – three terminals, from `PMG_AI`:**

```powershell
# Terminal 1 – ML endpoint
.\VENV_PMG\Scripts\python.exe ml_service\serve.py        # http://127.0.0.1:5001

# Terminal 2 – backend
cd backend; npm start                                    # http://localhost:4000

# Terminal 3 – frontend
cd frontend; npm run dev                                 # http://localhost:5173
```

macOS/Linux: use `VENV_PMG/bin/python ml_service/serve.py`; the npm commands are identical.

Open **http://localhost:5173** and sign in with a demo account (password for all: `Passw0rd!`):

| Account | Profile | Typical outcome |
| :- | :- | :- |
| `alice@example.com` | Gold, 5/5 prior claims approved | strong claims → APPROVE |
| `carol@example.com` | Silver, 1/2 approved | mixed |
| `bob@example.com` | Standard, **suspended**, 0/3 approved | weak claims → REJECT |

## 3. Verify each component

```powershell
curl http://127.0.0.1:5001/health          # {"model":"Random Forest","status":"ok"}
curl http://localhost:4000/api/health      # {"backend":"ok","ml":"ok"}   (503 + "unreachable" if the ML is down)
curl http://localhost:5173/                # the React page (HTML)
```

Call the ML endpoint directly (needs the API key):

```powershell
curl -X POST http://127.0.0.1:5001/v1/predict -H "X-API-Key: dev-ml-key-change-me" -H "Content-Type: application/json" `
  -d (python -c "import json,demo_claims as d;print(json.dumps(d.DEMO_CLAIMS[0]))")
```

Automated end-to-end test (ML + backend must be running; it logs in, requests a claim ID, uploads proof,
checks decisions, claim-ID reuse, validation and auth rules – 8 tests; the full `npm test` runs 12 incl. logging):

```powershell
cd backend; npm test
```

## 4. Using the app

1. **Sign in.**
2. The form opens with a freshly generated **Claim ID** (top right). It is single-use and is the same ID sent to the
   model and shown on the result.
3. Fill the three cards using chips, dropdowns, Yes/No toggles and date pickers. The refund amount is calculated as
   you type. Loyalty tier, account status, history, filing time and channel are filled from your account – not asked.
4. **Submit claim** → result page with the decision (Approve / Advisor review / Reject), probability meter and key facts.
   **My claims** lists previous results.

## 5. Production-style run (single origin)

Build the React app once; the Node backend then serves it, so the whole product is on one port with no CORS.

```powershell
cd frontend; npm run build; cd ..
$env:NODE_ENV="production"; $env:JWT_SECRET="<long random string>"; $env:ML_API_KEY="<long random string>"
# ML endpoint must use the SAME key:
$env:ML_HOST="127.0.0.1"
.\VENV_PMG\Scripts\python.exe ml_service\serve.py          # terminal 1 (with ML_API_KEY set)
cd backend; npm start                                      # terminal 2 -> http://localhost:4000
```

In production also: terminate **HTTPS** at a reverse proxy (nginx / cloud LB) – the login cookie is marked `Secure`
when `NODE_ENV=production`; keep port 5001 private (bind to loopback / private network); replace `backend/src/users.js`
with your real identity provider and `data/claims.jsonl` + `uploads/` with a database and object storage.
Linux ML alternative: `gunicorn -w 2 -b 127.0.0.1:5001 "ml_service.app:create_app()"` (run from `PMG_AI`, `pip install gunicorn`).

## 6. Configuration reference

| Variable | Used by | Default | Meaning |
| :- | :- | :- | :- |
| `ML_API_KEY` | ML + backend | `dev-ml-key-change-me` | shared secret (must match; non-default required in prod) |
| `ML_PORT` / `ML_HOST` | ML | 5001 / 127.0.0.1 | listen address |
| `ML_URL` | backend | `http://127.0.0.1:5001` | where the backend finds the ML endpoint |
| `ML_TIMEOUT_MS` | backend | 8000 | max wait for a prediction |
| `PORT` | backend | 4000 | backend port |
| `JWT_SECRET` | backend | random per start (dev) | signs login tokens; required in prod |
| `JWT_TTL` | backend | 2h | session length |
| `CORS_ORIGINS` | backend | localhost:5173 | allowed browser origins |
| `LOG_LEVEL` | backend + ML | `debug` | `debug` / `info` / `summary` / `error` (see section 7) |
| `VITE_LOG_LEVEL` | frontend | `debug` | same, for the browser |
| `NODE_ENV` | backend | – | `production` enables secure cookies + strict config checks |

## 7. Logging and tracing

All three components print the same line format to **their own terminal** (the window opened by `start-all.ps1`):

```
07:35:04.846 INFO    [BE] [CLM-20261004-2611FE] -> ML endpoint  POST http://127.0.0.1:5001/v1/predict
          time        level  comp  trace id (= Claim ID)  message  (+ indented JSON at DEBUG)
```

| Level | What it shows | Typical use |
| :- | :- | :- |
| `debug` | everything: customer answers, the full payload sent to the model, the **engineered features the model sees**, raw model output | development / troubleshooting (**current default**) |
| `info` | one line per step: `STEP 3a … 3g`, which component is called, HTTP status + latency | following the flow |
| `summary` | exactly one line per finished claim / login | production dashboards |
| `error` | failures only (ML down, rejected requests) | alerting |

A level shows itself **and everything above it** (`debug` > `info` > `summary` > `error` in verbosity).

| Component | Tag | Where to read it | How to set the level |
| :- | :- | :- | :- |
| React (browser) | `[FE]` | browser console (F12) **and** the backend terminal | `frontend/.env`: `VITE_LOG_LEVEL=debug` (restart `npm run dev`) |
| Node backend | `[BE]` | backend terminal | `LOG_LEVEL` env var / `backend/.env` |
| Flask ML | `[ML]` | ML terminal | `LOG_LEVEL` env var (set before starting `ml_service/serve.py`) |

Examples: `$env:LOG_LEVEL="info"` before starting a service; `$env:NO_COLOR="1"` turns colours off.

**Tracing one claim.** Opening the form generates the Claim ID, which becomes the *trace id*: the browser sends it as
`X-Trace-Id`, the backend forwards it to Flask, and every line from every component carries it. To follow a claim, search the
terminals for its id, e.g. `CLM-20261004-2611FE`. What you will see when you press **Submit claim** (debug level):

1. `[FE]` submit pressed → `-> POST /api/claims` with the answers (files listed by name/size)
2. `[BE]` `STEP 3a` answers received · `3b` validation · `3c` proof files · `3d` claim ID locked · `3e` model payload built
   (full JSON incl. the trusted loyalty profile merged in)
3. `[BE]` `STEP 3f` `-> ML endpoint POST …` + the exact JSON sent
4. `[ML]` `<- POST /v1/predict received` · claim JSON · validation · **model input features** (non-zero ones) ·
   `predicted P(approved)=… -> DECISION` · decision rule · response JSON · `SCORED …` summary
5. `[BE]` `<- ML endpoint answered 200 in …ms` + raw response · `STEP 3g` saved · `CLAIM … -> APPROVE (P=…) total=…ms` summary
6. `[FE]` `<- 201 POST /api/claims` · `claim … result: APPROVE`

**The ML exchange (what goes to the model and what comes back).** At `info` and `debug` both terminals print the complete
exchange as two clearly marked blocks, with the API key masked as `***`:

| Terminal | Block | Contents |
| :- | :- | :- |
| backend | `==== ML REQUEST  (backend -> ML model) ====` | method, URL, headers, the full claim JSON sent |
| ML | `==== ML REQUEST RECEIVED  (backend -> ML model) ====` | what the model service actually received |
| ML | `model input: …` *(debug)* | the engineered features the Random Forest scores |
| ML | `==== ML RESPONSE SENT  (ML model -> backend) ====` | decision, `probabilityApproved`, threshold, signals |
| backend | `==== ML RESPONSE  (ML model -> backend) ====` | HTTP status, round-trip ms and the response body |

**Log files** (everything printed is also saved; no colour codes; each file rotates at 10 MB; set `LOG_DIR` to move them):

| File | Content |
| :- | :- |
| `backend/logs/pmg-backend.log` | every backend line (including `[FE]` lines from the browser) |
| `ml_service/logs/pmg-ml.log` | every ML line |
| `backend/logs/ml-exchange.jsonl` | audit trail: **one JSON line per ML call** (`ts, claimId, url, request, status, latencyMs, response`), written at every log level |

Quick looks: `Get-Content backend\logs\pmg-backend.log -Wait` (live tail), or
`Select-String -Path backend\logs\*,ml_service\logs\* -Pattern CLM-20261004-2611FE` (one claim across all files).

Safety: passwords, tokens, cookies and API keys are replaced with `***` in all three loggers; newlines in user text are
collapsed so nobody can forge log lines; the browser log feed (`POST /api/logs`) is rate-limited and size-limited.
Personal data (e-mail, free-text comments) **is** printed at `debug` – lower the level before using real customer data.

Test the logging: `cd backend; npm test` (includes `test/logging.test.js`, which starts its own ML + backend on ports
5101/4100 and checks the terminal output at each level, trace ids, redaction and the browser feed).

## 8. Troubleshooting

| Symptom | Fix |
| :- | :- |
| `node`/`npm` not recognised | Node was installed after your terminal/VS Code opened. Close **and reopen VS Code** (a new terminal tab is not enough), or run `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`. `start-all.ps1` now does this itself. |
| `/api/health` shows `"ml":"unreachable"` | start the ML endpoint; check `ML_URL` / port 5001 |
| "The scoring service is temporarily unavailable" on submit | ML endpoint down or slower than `ML_TIMEOUT_MS` |
| Everything 401 after restarting the backend | dev JWT secret changes on restart → sign in again (set `JWT_SECRET` to keep sessions) |
| Port already in use | change `PORT` / `ML_PORT`, and update `ML_URL` / `vite.config.js` proxy |
| Backend returns 404 for `/` | run `npm run build` in `frontend/`, then restart the backend |
