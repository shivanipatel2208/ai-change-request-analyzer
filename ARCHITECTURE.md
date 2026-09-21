# Architecture

This document explains how the AI Change Request Analyzer is put together: what each layer does,
how they talk to each other, and the handful of deliberate design decisions that shape the rest
of the system. For what was built in which module, see `PROJECT_REPORT.md`. For a guided
walkthrough, see `DEMO.md`.

## Overview

```
React (Vite)  ──HTTP/JSON──►  FastAPI  ──SQLAlchemy──►  SQLite
                                  │
                                  ├─► AI provider abstraction (Anthropic / Gemini / Ollama / OpenRouter)
                                  ├─► Repository Intelligence (scans this project's own source tree)
                                  └─► Knowledge Base & RAG (uploaded docs, embedded, retrieved by similarity)
```

One backend process, one frontend process, one SQLite file. No message queue, no background
worker, no second database, no container orchestration — the project's guiding constraint
throughout was to stay exactly as complex as the problem requires and no further.

## Frontend

React 19 + Vite, with **no client-side router**. `AuthenticatedHome.jsx` holds a single piece of
state, `activeView`, and a plain `if/else` chain decides which page component to render — a
nav-item click just calls `setActiveView('dashboard')` and so on. This was a deliberate choice
for a hackathon-scale app: no route-matching library, no URL-state synchronization to maintain,
and it makes "jump to change request #N from a notification" a one-line state update
(`jumpToCrId`) rather than a programmatic navigation call.

Each feature area is its own page component under `frontend/src/pages/` (`DashboardPage`,
`ChangeRequestsPage`, `AnalysisDashboardPage`, `MyWorkPage`, `AnalyticsPage`, `NotificationsPage`,
`KnowledgeBasePage`, `AdminPage`, and so on), talking to the backend through small `fetch`-based
API wrapper modules in `frontend/src/api/` (one file per backend router, mirroring the backend's
own one-router-per-feature layout). Shared, reusable pieces — most notably `ChangeRequestDetail`,
the tabbed view used everywhere a single change request is displayed — live in
`frontend/src/components/`. Auth state (the JWT, the current user) is a single React context
(`AuthContext.jsx`); there is no separate state-management library.

`AnalysisDashboardPage.jsx` is the largest single page in the app by design: it's the one place
that renders every dimension of an analysis (Requirements, Impact, Repository, Dependencies,
Risks, Security, Complexity & Effort, Missing Information, Test Cases, Implementation Plan,
Traceability, History) as tabs over one shared dataset, rather than as separate pages each
re-fetching the same change request.

## Backend

FastAPI, organized as one router module per feature area under `backend/app/api/` — `auth.py`,
`change_requests.py` (by far the largest, since most of the enterprise workflow hangs off a
change request), `dashboard.py`, `users.py`, `notifications.py`, `repository.py`, `knowledge.py`,
`my_work.py`, `analytics.py`, `admin.py`, `health.py`. Each is registered once in `main.py`.

Business logic lives in `backend/app/services/`, not in the API layer — an endpoint function
typically checks permissions, calls one or two service functions, and shapes the response; the
actual rules (what counts as a valid status transition, how risk maps to required approvals, how
to diff two change-request versions, how to rank knowledge-base chunks by similarity) live in the
service modules so they're each independently readable and reusable. `workflow_rules.py` is the
closest thing this app has to a rulebook — status labels, the transition graph, required-approval
logic, and the human-facing labels used across the UI, the PDF report, and history entries all
read from it, so there's exactly one place that knowledge lives.

Every request that can fail cleanly does: real, expected failures (a missing change request, a
permission denial, an AI provider timeout, invalid input) each raise their own `HTTPException`
with a specific, user-facing message. A single global exception handler in `main.py` catches
anything else — a genuine bug — logs the full traceback server-side, and returns a generic,
non-revealing `500` response, so nothing internal ever reaches the browser.

Authentication is a signed JWT (PyJWT) returned at login, carried as a Bearer token; passwords
are hashed with PBKDF2 (stdlib `hashlib`), never a third-party dependency for something this
security-sensitive on a project this size.

## Database

A single SQLite file (`backend/data/app.db`), created and kept up to date automatically on every
startup by `app/database/init_db.py` — `Base.metadata.create_all()` for brand-new tables, plain
`ALTER TABLE` statements for columns added to an existing table by a later module (this project
never introduced a migration framework; a hackathon-scale schema doesn't need one), and a small
set of idempotent backfill/seed steps (default role permissions, default approval rules) that are
safe to run on every single startup.

SQLAlchemy 2.0 (typed `Mapped[...]` columns) is the only thing that talks to the database
directly — every model lives under `backend/app/models/`, one file per table, and every
enumerated field (status, priority, risk category, and so on) is a real Python `str` Enum rather
than a free-text column, so an invalid value is rejected at the database layer, not just by
convention.

## AI engine

`backend/app/services/ai/` defines one small interface (`AIProvider`: `complete()`,
`is_configured()`) and one implementation per provider — Anthropic, Gemini, Ollama, OpenRouter —
selected at runtime by the `AI_PROVIDER` environment variable through `factory.py`. Nothing above
this layer (the analysis engine, the RAG retrieval, anything else that calls an AI provider) knows
or cares which one is actually configured; adding a fifth provider later is one new class and one
line in the factory, not a change anywhere else.

`services/analysis_engine.py` is where an analysis actually happens: it builds a prompt from the
change request (plus, if available, repository findings and retrieved knowledge-base evidence),
calls the configured provider, and validates the raw response against a strict Pydantic schema
(`schemas/ai_analysis.py`) before anything touches the database — a malformed or incomplete AI
response is rejected with a clear error rather than partially persisted. Every finding the AI
produces (a requirement, a risk, a security finding, an affected component) carries its own
**certainty** (known / inferred / unknown) and **confidence** score, set by the AI itself and
never inferred after the fact — the app never claims more certainty than the AI actually
expressed.

If the configured AI provider is unavailable or returns something invalid, the request fails
cleanly with a specific error message (timeout, misconfiguration, malformed response) and nothing
is fabricated in its place — there is no "demo mode" that stands in with a canned response. See
`DEMO.md` for what this means for a live presentation.

## Repository Intelligence

`services/repository_scanner.py` and `code_understanding.py` walk this project's own real source
tree (or another folder, if `REPOSITORY_ROOT` is set), building a lightweight index of files,
imports, functions, classes, API routes, and database/config references —
`services/repository_matcher.py` then scores each indexed file against a specific change request
and records a `RepositoryFinding` with an honest, hedged confidence label (never a claimed
certainty the matching heuristic doesn't support). This means "affected files" shown in an
analysis are always real files that exist in this actual codebase, never invented paths — a
principle carried through explicitly into `DEMO.md`, which is why the demo script always runs a
real repository scan before showing repository findings for the flagship demo change request.

## RAG (Retrieval-Augmented Generation)

`services/knowledge_documents.py` and `knowledge_chunker.py` handle uploading and parsing project
documentation (`.txt`/`.md`/`.pdf`), splitting it into chunks; `knowledge_embeddings.py` embeds
each chunk through the same AI-provider abstraction used everywhere else, then ranks chunks
against a query by brute-force cosine similarity (`search_chunks()`) — genuinely fine at this
project's scale, and simple enough to read in full in one sitting. Retrieval used as grounding
context for an analysis (as opposed to the manual search page, which shows the closest results
regardless of quality) applies a real minimum-similarity threshold, so a barely-related chunk is
never injected into the AI's prompt as if it were solid evidence — the module's own guiding rule
is "do not fabricate project facts." Every piece of evidence used in an analysis is snapshotted
(document title, section, excerpt, similarity score) at the moment of retrieval and tagged with
the change request's version, so it stays accurate even if the source document is edited or
deleted later, and is flagged outdated the same way every other analysis artifact is.

## Workflow

A change request's lifecycle is a single `status` enum (Draft → Submitted → Pending Analysis →
Analyzed → Under Review → Changes Requested / Approval Required → Approved / Rejected →
Implementation Planned → In Progress → Implemented → Validated → Closed, with Cancelled reachable
from most non-terminal states), enforced centrally by `workflow_rules.can_transition()` — a status
change always goes through one endpoint (`PUT /change-requests/{id}/status`) that checks legality
before applying it, never a field any other code path can set directly.

Editing a change request never overwrites its own history: `services/versioning.py` diffs the
incoming change against the current row, and if anything actually changed, bumps
`current_version`, writes a `ChangeRequestVersion` snapshot, and records one `FIELD_CHANGED`
history event per changed field. Every AI-generated artifact (an analysis, a requirement, a risk,
a repository finding, a piece of retrieved evidence) is tagged with the change-request version it
was produced against, so editing a change request after analyzing it doesn't quietly leave a
stale analysis looking current — it's flagged outdated everywhere that analysis is shown,
including the PDF report, until it's re-analyzed.

## Approvals

Approvals are their own first-class model (`Approval`), separate from the status lifecycle:
requesting one (`POST /{id}/approvals`) tags a specific person for a specific approval type
(Technical, Security, Product, Engineering Manager, Director, QA, DBA, Release, General); only
that person can respond (`POST /{id}/approvals/{approval_id}/respond`) with Approved, Rejected, or
Changes Requested. `workflow_rules.required_approval_types()` computes which approval types a
given analysis *should* need (by risk-score threshold, category keywords, and admin-configurable
`ApprovalRule` rows — with one fixed exception: an AI-flagged security risk always requires
Security approval, a safety floor no admin rule can turn off), but this is a **recommendation**
only, never enforced automatically — a human always decides who to actually request approval
from. A change request cannot be moved to Approved status while any approval on it is still
Pending, closing a gap that existed before the final integration pass. Every request and response
generates a notification to the relevant person.

## Audit

Two separate, both append-only, audit trails exist on purpose, at two different scopes:

- **`ChangeRequestHistory`** — one entry per change request, per event (created, field changed,
  status changed, assigned, approval requested/responded, comment added, requirement reviewed,
  AI analysis completed/invalidated, and more). This is what the Activity tab and the PDF report's
  Audit section both read from. There is no API route that can update or delete an existing entry
  — only ever insert.
- **`SystemAuditLog`** — a separate, admin-scope log for administrative actions only (a user
  created, a role changed, a permission changed, an approval rule added/updated/deleted, a system
  setting changed). Kept entirely separate from per-change-request history so that "what happened
  to CR-104" and "what did an admin change about the system itself" are never mixed together.

Every audit entry records who did it (or, for a system actor like the AI analyzer, a labeled
`actor_label` instead of a spoofable user id), what changed, and when — the same fields a real CAB
(Change Advisory Board) review would expect to see.
