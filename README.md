# AI Change Request Analyzer

Turn ambiguous change requests into engineering decisions.

Submit a plain-language description of a proposed software change, and this app's AI Analysis
Engine reads it the way a senior engineer would: it extracts concrete requirements, classifies
the change, assesses its impact across seven fixed lenses (business, technical, customer,
operational, security, data, performance), identifies risks and runs a structured 9-category
security review, finds the parts of *this actual codebase* it's likely to touch, retrieves
relevant excerpts from your own project documentation as grounding evidence, estimates
complexity and effort, writes test cases and an implementation plan, and recommends what kind
of human approval it should need. None of that is a black box: every finding is tagged with the
AI's own certainty and confidence, and every one of them can be reviewed, confirmed, or
overridden by a person.

On top of that AI core sits a full enterprise change-management workflow: editing with a real
version history, a status lifecycle from Draft through Closed, role-based team assignments,
multi-type approvals with notifications, threaded comments with @mentions, an admin-configurable
permissions and approval-rules system, and an append-only audit trail that nothing in the app can
edit after the fact. The AI recommends; only a human ever approves.

## Features

- **AI-powered analysis** — requirement extraction, classification, impact assessment, risk
  scoring, a structured security review, complexity/effort estimation, missing-information
  detection, generated test cases, and a generated implementation plan, from one written change
  request.
- **Repository Intelligence** — scans and indexes this project's own source files (imports,
  functions, classes, API routes, database/config references) and matches a change request
  against real files with honest, hedged confidence — never a claimed certainty the evidence
  doesn't support.
- **Knowledge Base & RAG** — upload your own project documentation; the AI retrieves genuinely
  relevant excerpts (a real similarity cutoff, not just "the closest thing on file") as grounding
  context, with a Source/Section citation on every piece of evidence.
- **Version-aware everything** — editing a change request creates a new version and flags every
  earlier analysis, risk, requirement, and repository finding as outdated until it's re-analyzed.
  Nothing is ever silently mixed across versions, including in the PDF report.
- **Enterprise workflow** — a full status lifecycle, role-based assignments, multi-type approvals
  (Technical/Security/Product/Engineering Manager/Director/QA/DBA/Release/General), threaded
  comments with @mentions, and notifications for every one of them.
- **Administration** — user management and roles, a role × capability permissions matrix, admin-
  configurable approval rules, and a system-level audit log — all enforced on the backend, not
  just hidden in the UI.
- **Audit & reporting** — an append-only activity trail on every change request (no API can edit
  or delete a past entry), plus a version-aware, CAB-ready PDF report.
- **Analytics** — executive, workflow, risk, approval-bottleneck, change, workload, and
  AI-recommendation metrics, computed from real records, never invented.

See `ARCHITECTURE.md` for how these fit together, and `DEMO.md` for a guided walkthrough.

## Tech stack

- **Backend:** Python, FastAPI, SQLAlchemy 2.0, Pydantic, SQLite, JWT auth (PyJWT), PBKDF2
  password hashing, fpdf2 for PDF reports.
- **Frontend:** React 19, Vite. No client-side router — a single authenticated shell switches
  between pages by local state.
- **AI:** a provider-agnostic abstraction (`app/services/ai/`) — supports Anthropic (Claude),
  Google Gemini, Ollama (fully local, no API key), and OpenRouter. Swapping providers is one
  environment variable; nothing else in the app changes.
- Deliberately **no** Docker, message queue, background worker, or second database — this
  project's whole design brief was to stay as simple as the problem allows.

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm

## Installation

### 1. Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Open `backend\.env` in a text editor and fill in at least:

- `SECRET_KEY` — generate one from inside `backend/`: `python -c "import secrets; print(secrets.token_hex(32))"`.
  Never leave this as a placeholder outside local development (the app refuses to start with the
  placeholder value once `APP_ENV` is anything other than `development`).
- An AI provider key — see **Environment variables** below for the four supported options. The
  app runs without one, but AI Analysis will return a clear error until a provider is configured.

### 2. Frontend

```powershell
cd frontend
npm install
copy .env.example .env
```

## Environment variables

All backend configuration lives in `backend/.env` (copied from `backend/.env.example`, which
documents every variable inline). The ones you're most likely to touch:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs login tokens. Generate your own — see Installation above. Never commit a real value. |
| `AI_PROVIDER` | Which AI backend to use: `anthropic`, `gemini`, `ollama`, or `openrouter`. |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OLLAMA_BASE_URL` / `OPENROUTER_API_KEY` | Credentials for whichever provider you selected above. Gemini has a free tier with no billing; Ollama runs entirely on your own machine with no key at all. |
| `DATABASE_URL` | Defaults to a local SQLite file at `backend/data/app.db` — created automatically. |
| `CORS_ORIGINS` | Which frontend origins may call this API. Defaults to the Vite dev server. |
| `REPOSITORY_ROOT` | Leave blank to have Repository Intelligence index this project's own code (the default, and what the demo uses). |
| `AI_REQUEST_TIMEOUT_SECONDS` | How long to wait for one AI call before reporting a timeout. |

Frontend configuration is in `frontend/.env` (from `frontend/.env.example`): one optional variable,
`VITE_API_BASE_URL`, defaulting to `http://localhost:8000`.

## Startup commands

### One-click launcher (recommended, especially for presenting)

Double-click **`start_all.bat`** in the project's root folder. The first time it runs, it will
automatically create the backend's virtual environment, install all backend and frontend
dependencies, and copy `.env.example` to `.env` in both folders if they don't exist yet — this
can take a minute or two, only the first time. After that (and on every later run), it opens the
backend and frontend each in their own window and automatically opens the app in your default
browser at http://localhost:5173 once both are up. No terminal typing required. Keep the two
new windows open while you use or present the app; closing either one stops that server.

`start_backend.bat` and `start_frontend.bat` are also provided if you ever want to start just one
side on its own — each does its own one-time setup the same way.

### Manual startup (two terminals, both from the project root)

**Terminal 1 — backend:**
```powershell
cd backend
python -m uvicorn app.main:app --reload
```
Runs on http://localhost:8000. Interactive API docs at http://localhost:8000/docs. Database
tables are created automatically on first startup — no separate migration step.

**Terminal 2 — frontend:**
```powershell
cd frontend
npm run dev
```
Runs on http://localhost:5173 — open this in a browser.

### Demo data (optional)

To load five demo accounts and a set of realistic sample change requests for a presentation, run
once from `backend/` (with the backend's virtual environment active):

```powershell
python -m app.database.seed_demo
```

See `DEMO.md` for the full credentials table and a step-by-step presentation script.

## Testing

```powershell
cd backend
python -m pytest ../tests
```

Runs the full backend test suite (currently 396 tests) against a throwaway SQLite database
created fresh for the test run — this never touches `backend/data/app.db`, so testing is always
safe to run alongside a live demo database.

## Project structure

```
hackathon_alight/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint, router registration, global error handler
│   │   ├── core/                # settings (config.py), password/JWT helpers (security.py)
│   │   ├── api/                 # one router module per feature area
│   │   ├── database/            # SQLAlchemy engine/session, init_db, seed scripts
│   │   ├── models/               # ORM models
│   │   ├── schemas/              # Pydantic request/response shapes
│   │   └── services/             # business logic — AI, workflow, approvals, RAG, reports, etc.
│   ├── requirements.txt
│   └── .env.example
├── frontend/                     # React + Vite, no router (see ARCHITECTURE.md)
│   └── src/
├── tests/                        # pytest suite (396 tests)
├── README.md                     # this file
├── ARCHITECTURE.md               # how the system fits together
├── DEMO.md                       # guided presentation script
└── PROJECT_REPORT.md             # the full build log, module by module
```

