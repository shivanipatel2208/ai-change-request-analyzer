# AI Change Request Analyzer — Project Report

**Prepared:** September 2026
**Scope:** Full system, Modules 1–17 (Module 17 = this working session's focus, all 7 phases complete)

---

## 1. What the system does

A change-request intake and AI-analysis tool: someone submits a proposed change (title,
description, priority, requester, target system), the AI Analysis Engine extracts
requirements, classifies it, and produces impact/dependency/risk/security analysis,
complexity & effort estimates, missing-requirement (clarification) detection, test cases,
an implementation plan, and an approval recommendation. On top of that sits a full
enterprise workflow: editing with version history, a status lifecycle, role-based
assignments, approvals, threaded comments with @mentions, and notifications.

Stack: FastAPI + SQLAlchemy 2.0 + SQLite on the backend, React 19 + Vite on the frontend,
JWT auth, a swappable AI-provider abstraction (Anthropic by default). No Docker, no
message queue, no second database — deliberately kept simple per your instruction.

---

## 2. Module map

| # | Module | What it covers | Key files |
|---|--------|-----------------|------------|
| 1 | Project Foundation | FastAPI skeleton, SQLite wiring, health check, minimal frontend, AI-provider interface | `main.py`, `core/config.py`, `database/session.py`, `api/health.py`, `services/ai/` |
| 2 | Authentication | Register/login/logout, JWT, password hashing (PBKDF2) | `api/auth.py`, `core/security.py`, `models/user.py`, `context/AuthContext.jsx` |
| 3 | Dashboard | Summary metrics, risk/category distribution, recent requests | `api/dashboard.py`, `pages/DashboardPage.jsx` |
| 4 | Change Request Creation | Submission form, validation, `pending_analysis` status | `models/change_request.py`, `schemas/change_request.py`, creation form |
| 5 | Change Request Management | List page: search, filter, sort, pagination; enriched detail endpoint | `api/change_requests.py` (list/detail), `pages/ChangeRequestsPage.jsx` |
| 6 | AI Analysis Engine | Prompting, JSON→Pydantic validation, persistence across all analysis child tables | `services/analysis_engine.py`, `schemas/ai_analysis.py` |
| 7 | Analysis Dashboard | Dedicated results page — header, summary cards, tabbed sections | `pages/AnalysisDashboardPage.jsx`, `styles/analysis-dashboard.css` |
| 8 | Impact & Dependency Graph | Visual node graph of affected components/dependencies | `components/ImpactGraph.jsx` |
| 9 | Risk Analysis & Security | 8-category risk breakdown, overall risk score, security checklist | `AnalysisDashboardPage.jsx` (Risks/Security tabs) |
| 10 | Test Cases & Implementation Plan | Filterable test-case list, numbered implementation timeline, "Regenerate Analysis" | `AnalysisDashboardPage.jsx` (Tests/Plan tabs) |
| 11 | Report Generation | 16-section CAB-review PDF built from a CR + its analysis | `services/report_generator.py` |
| 12 | Enterprise Workflow | Editing/versioning/audit trail, status lifecycle, assignments, approvals, comments/@mentions/notifications, detail-page tabs, list filters | see §3 |
| 13 | AI Analysis 2.0 | Per-finding certainty/confidence tagging, analysis-to-analysis comparison, outdated-analysis detection extended to reports/notifications, workflow recommendation text, human-override recording, frontend for all of it | see §11 |
| 14 | Analysis & Impact Intelligence | Dashboard header completeness, richer Affected Components/Dependencies, Complexity & Effort confidence, structured 7-category Impact Analysis, structured 9-category Security Findings, permission-gated Human Review of both, tied to Module 12's history/permission system throughout | see §12 |
| 15 | Repository Intelligence | Repository-aware analysis: indexes the project's own source files, extracts imports/functions/classes/API routes/DB & config references, matches a change request against them with hedged (never "definite") confidence labels, feeds those findings into the existing Impact/Dependencies/Risk/Test Cases/Implementation Plan sections, version-aware re-scan/re-match, dedicated security pass | see §13 |
| 16 | Project Knowledge Base & RAG | Upload project documentation (.txt/.md/.pdf), parse+chunk it, embed it via the existing AI-provider abstraction, retrieve genuinely-relevant excerpts (a real similarity cutoff, not "closest thing on file") as grounding context for CR analysis with Source/Section attribution, snapshot that evidence per analysis run so it stays accurate even if the source document changes, version-aware like every other analysis output, a full Knowledge Base management page, dedicated security pass | see §14 |
| 17 | Test Cases & Implementation Plan 2.0 | Richer, version-aware test-case generation (preconditions/steps/type/priority) and implementation-plan generation (owner suggestion/dependencies/effort), full Requirement → Task → Test Case traceability computed via keyword overlap (never AI-generated, to avoid hallucinated IDs), "may be outdated / Regenerate" banners reusing the existing full re-analysis action, permission-gated human editing of AI-generated test cases/tasks tied to Module 12's existing audit trail, a dedicated end-to-end version-sync test | see §15 |
| 18 | Notifications, My Work & Personal Engineering Queue | A notification bell in the header (unread count, recent notifications, mark read/mark all read, link to CR), two new notification types (risk escalation, analysis completion) plus an automatic deadline-approaching check, a personal "My Work" dashboard (My CRs/My Approvals/My Reviews/My Assignments/Changes Requested From Me/Mentions/Overdue Items) with database-level filtering throughout, Approve/Reject/Request Changes actions wired onto My Approvals, an optional due date on approval requests — all built on Module 12's existing notification/assignment tables, no second system | see §16 |
| 19 | Engineering Change Analytics | Executive/Workflow/Risk/Approval-Bottleneck/Change/Workload/AI metrics, all computed from real database records with one shared date/status/priority/risk/category/owner filter set; a new Analytics page with metric cards and hand-rolled (no library) charts; a new AI-analysis-failure history hook so "AI failures" has real data to report | see §17 |
| 20 | **Version-Aware Reports** (this session) | The existing Module 11 PDF report made version-consistent — it now refuses to silently mix one version's Change Request fields with a different version's analysis, offers an explicit, clearly-labeled historical report for any past version, and adds Approval Status/Change History/Audit sections plus a "report generated" audit hook that had existed as an unused enum value since Module 12 | see §18 |

---

## 3. Module 12 — Enterprise Workflow

Delivered in 7 phases, each confirmed by you before moving to the next:

**Phase 1 — Foundation.** New tables (`ChangeRequestVersion`, `ChangeRequestHistory`,
`ChangeRequestAssignment`, `Approval`, `ChangeRequestComment`, `Notification`), an
expanded status lifecycle, the approval matrix, "is analysis/approval outdated" checks,
and per-CR permission helpers (`services/workflow_rules.py`).

**Phase 2 — Editing, Versioning, Audit.** `PUT /change-requests/{id}` partial-update
editing; every edit snapshots a version and writes field-level history entries
(`services/versioning.py`, `services/history.py` — the single gatekeeper for history
rows); editing after an analysis exists flags that analysis outdated.

**Phase 3 — Status Workflow & Assignments.** `PUT .../status` with legal-transition
checking and a reason required for "went wrong" transitions; `POST/GET/DELETE
.../assignments` for role-based team assignment; a read-only user directory
(`api/users.py`) for the assignment picker.

**Phase 4 — Approvals.** Tag a specific person for a specific sign-off type
(`POST .../approvals`), respond/withdraw/remind, duplicate-pending rejected, recommended
approval types derived from the AI's own risk analysis, approvals flagged outdated if the
CR changes underneath them.

**Phase 5 — Comments, Mentions, Notifications.** Threaded comments with resolve/delete;
`@mention` parsing (`services/mentions.py`) that notifies mentioned users
(`services/notify.py` — the single gatekeeper for notification rows); a notification
inbox with unread badge and deep-linking back to the change request. Per your feedback,
the mention picker was rebuilt from a plain `<select>` into a real inline autocomplete
(`MentionTextarea`) — type `@`, a filtered name list pops up, arrow keys + Enter/Tab or a
click selects it.

**Phase 6 — Detail Tabs & List Filters.** The change-request detail page reorganized into
three tabs (Overview / Activity / Comments, per your choice) instead of one long scroll;
an "Assigned to me" checkbox added to the change-request list filters.

**Phase 7 — This wrap-up.** Full-system review and this report, in place of a live
walkthrough — see §7 for why, and §8 for what to run instead.

### Files touched in Module 12 (new or modified)

Backend: `models/{change_request_version,change_request_history,change_request_assignment,
approval,comment,notification}.py`, `schemas/{comment,notification,approval,assignment}.py`,
`services/{history,versioning,workflow_rules,approvals,mentions,notify,comments}.py`,
`api/{change_requests,users,notifications}.py`, `main.py`.
Frontend: `api/{comments,notifications}.js`, `pages/NotificationsPage.jsx`,
`components/{AppHeader,ChangeRequestDetail}.jsx`, `pages/{AuthenticatedHome,
ChangeRequestsPage}.jsx`, `styles/{header,workflow,change-requests-list}.css`.
Tests: `test_workflow_{foundation,status_assignments,approvals,comments_notifications}.py`,
additions to `test_change_request_editing.py` and `test_change_request_management.py`,
plus `tests/conftest.py` (new — see §6).

---

## 4. Database changes (Module 12)

Six new tables, all pointing back at `change_requests.id` and/or `users.id`:
`change_request_versions`, `change_request_history`, `change_request_assignments`,
`approvals`, `change_request_comments`, `notifications`. `ChangeRequest` and `Analysis`
cascade-delete their children (`all, delete-orphan`) — deleting a change request cleans
up its versions/history/assignments/approvals/comments and an analysis's requirements/
components/dependencies/risks/questions/test-cases/tasks automatically.
**One deliberate exception:** `Notification` is not on that cascade list, since a
notification can outlive the change request it references being viewed — the cleanup
script (`cleanup_test_users.py`) accounts for this and deletes matching notifications
by hand when it removes test data.

No destructive migrations were needed anywhere — `init_db()` creates any missing table
on startup, which is why every phase could ship without you ever needing to touch the
database by hand.

---

## 5. API changes (Module 12 additions)

```
PUT    /api/change-requests/{id}                              edit a change request
GET    /api/change-requests/{id}/history                      audit trail
GET    /api/change-requests/{id}/versions                     version list
GET    /api/change-requests/{id}/versions/{version_number}    one version's snapshot
GET    /api/change-requests/{id}/compare?from=&to=            field-by-field diff
PUT    /api/change-requests/{id}/status                       status transition
GET    /api/change-requests/{id}/assignments                  list assignments
POST   /api/change-requests/{id}/assignments                  assign someone
DELETE /api/change-requests/{id}/assignments/{assignment_id}   unassign
GET    /api/change-requests/{id}/approvals                     list approvals
GET    /api/change-requests/{id}/approvals/recommended         AI-recommended sign-off types
POST   /api/change-requests/{id}/approvals                     request an approval
POST   /api/change-requests/{id}/approvals/{approval_id}/respond
DELETE /api/change-requests/{id}/approvals/{approval_id}       withdraw
POST   /api/change-requests/{id}/approvals/{approval_id}/remind
GET    /api/change-requests/{id}/comments                      list comments
POST   /api/change-requests/{id}/comments                      post a comment
PUT    /api/change-requests/{id}/comments/{comment_id}/resolve
DELETE /api/change-requests/{id}/comments/{comment_id}
GET    /api/change-requests?assigned_to_me=true                list filter (Phase 6)
GET    /api/users                                              read-only directory (assign/@mention picker)
GET    /api/notifications                                      inbox
GET    /api/notifications/unread-count                         badge count
PUT    /api/notifications/{id}/read
PUT    /api/notifications/read-all
```

Every endpoint above requires a valid JWT and is layered on the pre-existing
`/auth`, `/api/change-requests` (create/list/get), `/api/dashboard/summary`, and
`/health` endpoints from earlier modules — nothing pre-existing was removed or
renamed.

---

## 6. Testing

**381 automated tests, all passing** as of the end of Module 20 (368 through Module 19, 327
through Module 18, 296
through Module 17, 269
through Module 16, 231
through Module 15 — 198 through Module 14, 175 through Module 13, which was itself 148
through Module 12
(Health 2, workflow foundation 19, status/assignments 17, approvals 21,
comments/notifications 30, editing 13, plus 12 in change-request management including the
"assigned to me" filter) plus 27 from Module 13's four backend phases — plus 23 from
Module 14's five backend-touching phases — plus 33 from Module 15's seven phases — plus 38
across Module 16's seven phases — plus 27 across Module 17's six backend-touching phases
(Phase 5 was frontend-only) — plus 31 new ones added across Module 18's four
test-bearing phases (Phases 4/5/6 were frontend-only) — plus 41 new ones added across
Module 19's six test-bearing phases (Phase 6 was frontend-only) — plus 13 new ones covering
Module 20's version-aware report engine (its one frontend phase reuses the existing
Re-analyze action, so there was nothing new there to test): see §18.5 for the
breakdown. Run with
`python -m pytest ../tests` from `backend/` (bare `pytest` can intermittently fail on
Windows with a launcher "Access is denied" error right after a fresh `pip install` — using
`python -m pytest` avoids it).

**A real bug class was found and fixed during this session, worth knowing about:**
pytest and your live dev server were sharing one SQLite file (`backend/data/app.db`).
Every test run was silently writing permanent junk accounts and change requests into the
same database you were testing against by hand — which is exactly what caused the
"hundreds of duplicate mention notifications" you spotted. Fixed two ways:
1. `tests/conftest.py` now points pytest at an isolated, wiped-every-run
   `backend/data/test_app.db` — future test runs can never touch your real data again.
2. `app/database/cleanup_test_users.py` (one-time cleanup for the pollution that had
   already happened) — removed 672 test accounts and the change requests/notifications
   they'd created. Safe to re-run with `--apply` if you ever suspect it's needed again
   (dry-run by default).

---

## 7. Why I didn't run the live walkthrough myself

You asked me to speed things up, so I tried to test the running app directly using
browser automation on your machine instead of asking you to click through screenshots
again. I got as far as confirming both servers are up and the app loads — but the very
next step is signing in, and typing a password into a login field is something I'm not
allowed to do myself under my own safety rules, no exceptions, even with your go-ahead.
So the live click-through still has to be you. To keep this fast, §8 is a single
condensed pass instead of the slower step-by-step-with-screenshots pattern from earlier
phases — one sitting, not seven.

---

## 8. Condensed final walkthrough (run this once, in order)

1. Start both servers (`uvicorn app.main:app --reload` in `backend/`, `npm run dev` in
   `frontend/`), log in.
2. Create a new change request → confirm it lists as **Pending Analysis**.
3. Run **Analyze** on it → confirm the Analysis Dashboard tabs (Overview, Risks, Security,
   Impact Graph, Test Cases, Implementation Plan) all populate, and **Download Report**
   produces a PDF.
4. Open the change request → **Edit** a field → confirm a new version appears under the
   Activity tab and the analysis banner flags itself outdated.
5. Change its **status** → confirm only legal next-steps are offered and the move is
   logged in Activity.
6. **Assign** a teammate → check **"Assigned to me"** on the list page as that teammate →
   confirm it shows up; as someone else, confirm it doesn't.
7. Request an **approval**, respond to it as the tagged approver → confirm it shows
   resolved and is logged.
8. Post a **comment**, type `@` and pick a name from the popup → confirm the mentioned
   user gets a notification, and clicking it deep-links back to this change request.
9. Resolve/delete a comment → confirm it updates correctly.

If every step above matches, the system is confirmed working end-to-end across all 12
modules.

---

## 9. Audit against your original Module 12 spec

You gave me a detailed 38-section spec for this module back when we started it. Rather
than just re-asserting everything was done, I went back through the actual code
section-by-section against that spec. Here's the honest result — the great majority
matches exactly, and I'm flagging every place it doesn't.

**Matches the spec exactly** (verified in code, not just claimed): field-level history
with before/after/who/when (§3); versioning with a real version number shown on the CR
(§4); version compare (§5); AI-analysis-outdated detection + re-analyze (§6); the status
lifecycle uses your exact list — Draft, Submitted, Pending Analysis, Analyzed, Under
Review, Changes Requested, Approval Required, Approved, Rejected, Implementation
Planned, In Progress, Implemented, Validated, Closed, Cancelled (§7); reason required on
status change + logged (§8); the exact role set you specified — Requester, Owner,
Technical Lead, Reviewer, Approver, Security Reviewer, QA Owner, Implementation Owner —
for both assignments and permissions (§9–§10); tagging users for approval (§11);
Approve/Reject/Request Changes with a required reason (§12); risk-based approval matrix
+ AI-recommended approval types, human-only decisions (§13, §14, §29); approval
dashboard with per-approver status (§15); approval invalidation on edit (§16); a full
activity timeline covering every event type you listed (§17); comments with
resolve/delete (§18); @mentions — I actually went beyond your "simple parser is
acceptable" and built a real inline autocomplete (§19); notifications for every trigger
you listed (§20); remind-approver (§21); append-only audit history — there's no
edit/delete endpoint for history rows (§24); the database and API shapes you asked for
(§25–§26, endpoint names differ slightly but every capability is there); backend-side
permission checks, not just frontend (§27); the AI-integration sequence on edit
(save → version → history → mark outdated → recalc approvals) (§28); a real migration
that backfills existing change requests to Version 1 with an honest "Initial version
imported" event rather than inventing fake history (§35); no Docker/Kafka/microservices
creep (§36); 148 automated tests (§34, §37 — the automated half).

**Done, but organized differently than the spec pictured — by your own choice:**
§22 asked for 10 tabs (Overview / AI Analysis / Impact / Risks / Approvals / Activity /
Comments / Versions / Tests / Implementation Plan) on one page. When I asked you
directly during Phase 6, you chose 3 tabs (Overview / Activity / Comments) instead —
nothing from the spec is missing, it's just split across two pages: AI Analysis/Impact/
Risks/Security/Tests/Implementation Plan live on the separate Analysis Dashboard (one
click away via "View Analysis"), Approvals live inside Overview, and Versions live
inside Activity.

**Real, genuine gaps — not built:**
- §23: editing doesn't show a "Priority: Medium → High" preview screen before you hit
  Save — it saves directly. You can still see exactly what changed right after (Activity
  tab / version compare), just not as a confirm-before-save step. Small to add if you
  want it.
- §30: list filters cover search, status, priority, assigned-to-me, and sort — not risk,
  category, owner/requester, approval status, or date range, all of which the spec
  mentioned.
- §31: the list only has one "Open →" action per row — View/Edit/Change Status/Analyze/
  Request Approval all live one click in in the detail page, not as buttons directly on
  the list row.
- §2: "Category" was deliberately left out as a manually-editable field — the app
  already has a working AI-derived category used everywhere else, and adding a second,
  human-editable one would just create two disagreeing answers to "what category is
  this."
- §37 (the live-click-through half): still needs you — see §7/§8 above for why and the
  condensed checklist to run.

None of the gaps above touch data integrity, permissions, or the audit trail — they're
all "a convenience the spec asked for that isn't there yet," not "the safety net has a
hole in it." Tell me if you want any of them closed before you call Module 12 done.

---

## 10. Known limitations

- Password hashing is PBKDF2 (stdlib), not bcrypt/argon2 — a deliberate call made early
  on to avoid native-compile failures on this machine; fine for a hackathon, not a
  production choice.
- User directory (`/api/users`) is read-only — no admin invite/deactivate flow.
- No migrations tool — `init_db()` creates missing tables on startup, which is simple but
  means an actual schema *change* (not just addition) would need a manual data fix.
- AI provider is swappable but only Anthropic is implemented today.
- The five "Load Test Bot" seeded accounts (`seed_bulk.py`) are intentional stress-test
  data, not a bug — they're clearly named and use a non-loginable password.
- Module 13's `RecommendationResult.decision_allowed` validator restricts the AI's own
  recommendation to `approve` / `approve_with_conditions` / `requires_clarification` —
  `reject` and `needs_more_info` remain legal values on a *human's* approval decision (and
  on old seeded rows) but the AI itself can never emit them via `/analyze`. See §11.7.

---

## 11. Module 13 — AI Analysis 2.0 (built this session)

Everything in this module sits strictly on top of Module 12's data model — no parallel
CR/approval/history system was built, per the standing architecture-lock rule agreed at
the end of Module 12: Module 12 stays the one source of truth for editing, status,
versioning, history, assignment, approvals, comments, and notifications; every new
artifact here is tied to a specific change request *and* the specific analysis version it
was generated from, never presented as current once the CR has moved on.

### 11.1 What it adds and why

Analysis 1.0 (Modules 6–11) told you *what* the AI concluded. 2.0 is about how much to
trust each conclusion, whether an old conclusion is still valid, and what to actually do
next:

- **Epistemic tagging** — every requirement, risk, and affected component now carries a
  Known/Inferred/Unknown certainty label plus a 0–100 confidence score, computed by the
  AI's own prompt rather than invented after the fact.
- **Version-to-version comparison** — a computed (not AI-written) diff between any two
  analyses of the same change request, so "what changed since the last AI run" has a
  precise, always-correct answer instead of relying on someone's memory or a re-read.
- **Outdated detection, extended** — Module 12 already flagged an *approval* as outdated
  when the CR changed underneath it; this module extends the same idea to the PDF report
  and to a dedicated banner on the Analysis Dashboard itself, and adds a distinct
  notification (`analysis_significantly_changed`) separate from the existing
  "analysis_outdated" one, so a stakeholder can tell "something changed" from "something
  changed *a lot*."
- **AI-failure safety** — if a re-analysis attempt fails for any reason (provider not
  configured, timeout, bad response), the change request's *existing* analysis is left
  completely untouched and the error message says so explicitly, so a flaky AI call can
  never silently erase a good analysis.
- **Workflow recommendation text** — one computed sentence combining the AI's decision
  with which approvals it actually requires (e.g. *"Approve — requires Technical
  approval"*), so nobody has to mentally combine "what did the AI say" with "what does the
  risk-based approval matrix require" themselves.
- **Human-override recording** — when a person's approval decision doesn't match what the
  AI recommended on the analysis version their approval was actually requested against, an
  additional audit event is recorded (never replacing the normal Approved/Rejected/
  Changes-Requested event) and the approval row shows both what the AI said and that it
  was overridden. The AI can recommend; only a human decision is ever binding — this
  module never lets an AI recommendation block, auto-approve, or auto-reject anything.

### 11.2 The 5 phases

1. **Per-finding epistemic tagging** — `Certainty` enum, `confidence`/`evidence` columns
   on Requirement/Risk/AffectedComponent, AI prompt updated to populate them, backward
   compatible with pre-Module-13 analyses (all three fields nullable).
2. **Version comparison** — `services/analysis_delta.py` computes a field-by-field diff
   plus added/removed requirements and affected components between any two analyses;
   `GET /analysis/compare` and `GET /analyses` (lightweight history list) expose it.
3. **Outdated flag + AI-failure safety** — `AnalysisRead.is_outdated`, the PDF report's
   metadata line + amber warning banner, the new significant-change notification type, and
   the "prior analysis untouched" messaging on AI failure.
4. **Workflow recommendation + override recording** — `AnalysisRead.workflow_recommendation`,
   `ApprovalRead.ai_recommendation` / `overrode_ai_recommendation` (computed from the
   analysis tied to that approval's own `cr_version`, never the CR's current analysis),
   the new `AI_RECOMMENDATION_OVERRIDDEN` history event.
5. **Frontend** — Certainty badges and confidence bars on Requirements/Risks/Affected
   Components, an outdated-analysis banner on the Analysis Dashboard, the workflow
   recommendation sentence on the Overview tab, a new **History** tab (list past analyses,
   expand any one to see its diff against the one before it), and the "AI recommended: …" /
   "Overrode AI" labels on approval rows in the change-request detail page.

### 11.3 Files touched

Backend: `models/enums.py` (`Certainty`, `NotificationType.ANALYSIS_SIGNIFICANTLY_CHANGED`,
`HistoryAction.AI_RECOMMENDATION_OVERRIDDEN`), `schemas/{requirement,risk,
affected_component,analysis,approval}.py`, `services/{analysis_engine,analysis_delta,
workflow_rules,approvals,report_generator}.py`, `api/change_requests.py`.
Frontend: `api/analysis.js`, `pages/AnalysisDashboardPage.jsx`,
`styles/analysis-dashboard.css`, `components/ChangeRequestDetail.jsx`.
Tests: `test_ai_analysis_v2.py`, `test_analysis_delta.py`, `test_ai_analysis_phase3.py`,
`test_ai_analysis_phase4.py`.

### 11.4 API / schema changes

```
GET /api/change-requests/{id}/analyses                  lightweight history (newest first)
GET /api/change-requests/{id}/analysis/compare?from=&to= computed diff between two analyses
```

`AnalysisRead` gained `is_outdated` and `workflow_recommendation` (both computed fresh per
request, never stored — same rule Module 12 used for `is_analysis_outdated`).
`ApprovalRead` gained `ai_recommendation` and `overrode_ai_recommendation` (computed from
the analysis matching that approval's `cr_version`, and only ever computed once the
approval has actually been responded to — never for a still-pending one).
Requirement/Risk/AffectedComponent gained `certainty`, `confidence`, and (Requirement/Risk
only) `evidence` — all nullable, so pre-Module-13 analyses still validate and display
normally with those fields simply absent.

No new tables — everything above is new columns on existing tables, plus two new enum
members. `init_db()` handles it the same way it has every module: creates what's missing
on startup, no manual migration.

### 11.5 Testing breakdown

27 new tests across Module 13's four backend phases (all included in the 175 total in
§6): `test_ai_analysis_v2.py` (5, Phase 1 — certainty/confidence/evidence tagging and
backward compatibility), `test_analysis_delta.py` (7, Phase 2 — the version comparison
diff), `test_ai_analysis_phase3.py` (9, Phase 3 — outdated flag, significant-change
notifications, AI-failure safety, report generation while outdated),
`test_ai_analysis_phase4.py` (6, Phase 4 — workflow recommendation text and
override recording, including the version-correctness case where a *later* re-analysis
must never change what an *earlier* approval is judged against).

### 11.6 Frontend verification (done live, this session)

Since this sandbox has no way to syntax-check JSX (the npm registry is blocked here, the
same way PyPI is for Python packages), Phase 5's frontend code could only be proofread
carefully before being sent to you rather than tested automatically. You then confirmed
it live on CR-3338, end to end:
- Requirements tab: "Known" certainty badge + 90% confidence bar + evidence text.
- Risks tab: "Inferred" certainty badge + "AI Confidence in This Assessment: 80%".
- Overview tab: the workflow recommendation sentence ("AI recommends: Approve (High
  risk) - requires Engineering Manager and Security approval before it can proceed.").
- History tab: both analyses listed, "View changes vs. previous" correctly hidden on the
  oldest one, and expanding it on the newer one showed a correct field-comparison table
  (Implementation tasks 2 → 3) and a correct requirements diff (added in green, removed
  struck through in red).
- A full re-run of the backend test suite after all of this confirmed 175/175 still
  passing — no regressions from the frontend work.

Two pieces reuse patterns already proven elsewhere (the outdated-analysis banner, and the
"Overrode AI"/"AI recommended" labels on approval rows) but weren't exercised live in this
session because CR-3338 wasn't in the right state for them (not edited-since-analyzed,
and no responded approval on it yet) — worth a quick look next time either situation comes
up naturally.

### 11.7 A real constraint discovered along the way

The AI Analysis Engine's own response schema
(`app/schemas/ai_analysis.py::RecommendationResult.decision_allowed`) only ever lets the
AI recommend `approve`, `approve_with_conditions`, or `requires_clarification` —
`reject` and `needs_more_info` are legacy `ApprovalRecommendation` values kept for old
seeded rows and for a *human's* own decision, but the AI itself can never produce them via
`/analyze`. This surfaced as a real test-data bug during Phase 4 (a canned test response
used `"decision": "reject"` and got a 422 instead of the expected 201) — fixed by testing
the override scenarios against a high-risk "requires clarification" response instead,
which is a real value the AI can actually emit.

---

## 12. Module 14 — Analysis & Impact Intelligence (built this session)

Same architecture-lock rule as Module 13, applied again: everything below sits on top of
Module 12's data model. No parallel status/history/permission/assignment system was
built for reviewing a Requirement or a Security finding — reviewing them reuses Module
12's exact `history_service.record_event` audit trail and the same
assignment-role-based permission shape as `can_manage_workflow`, just under a new,
narrower helper (`can_review_analysis_findings`). Every new artifact is tied to a
specific analysis (and, through it, a specific change-request version) — nothing here is
ever shown as current once the change request has moved past that analysis.

### 12.1 What it adds and why

Modules 6–13 told you what the AI concluded and how much to trust it. Module 14 fills in
the analysis sections that were still thin or AI-only, and — for the first time — gives a
human a first-class way to weigh in on individual AI findings, not just the change
request as a whole:

- **Dashboard header completeness** — the Analysis Dashboard's header now always shows
  which change-request version and analysis version you're looking at, its status, and
  (reusing the existing recommended-approvals endpoint from Module 12) the AI-derived
  approval types this analysis actually calls for — all in one place instead of requiring
  a trip to the change-request detail page to piece it together.
- **Affected Components & Dependencies, filled out** — Affected Components gained the same
  `evidence` field Requirements and Risks already had (Module 13 Phase 1); Dependencies
  gained `relationship_type` (direct/indirect/potential) and `risk_severity`, distinct from
  the pre-existing `impact_level` — so a dependency can now say not just "this matters" but
  "here's exactly how directly, and how risky relying on it is."
- **Complexity & Effort confidence** — a coarse Low/Medium/High confidence rating on both
  the Complexity and Effort estimates, deliberately separate from each other and from the
  overall classification confidence, and deliberately coarse (not a fake-precision number)
  since Complexity/Effort were already plain-language estimates by design.
- **Impact Analysis, structured** — a fixed 7-category breakdown (Business, Technical,
  Customer, Operational, Security, Data, Performance), each with an impact level, a
  description, and its own certainty/confidence — replacing the old free-text
  Business/Technical Impact paragraphs on the Overview tab with the same structured,
  evidence-backed shape the rest of the analysis already uses.
- **Security Findings, structured** — a fixed 9-category breakdown (Authentication,
  Authorization, Data Protection, Secrets, API Security, Rate Limiting, Privacy, Audit
  Logging, Compliance), each with a Finding, Severity, Evidence, Recommendation, and
  Status — replacing the old free-text security blob with something a security reviewer
  can actually work through category by category.
- **Human Review** — the one genuinely new capability, not just a richer AI output: an
  authorized person can mark an extracted Requirement Confirmed or Needs Clarification
  (with a required comment for the latter), and move a Security finding's Status through
  Open → Acknowledged → Resolved (or reopen one) — without ever touching that row's own
  AI-generated fields, and without the AI itself ever being able to claim Acknowledged or
  Resolved on its own. Every review is permission-gated and recorded on the change
  request's existing audit trail, exactly like every other Module 12 action.

Both fixed-category lists (Impact's 7, Security's 9) are guaranteed complete on every
response: a `model_validator` on the AI's parsed output auto-fills any category the model
skipped with an honest "no assessment"/"nothing flagged" placeholder, so the dashboard
never silently renders fewer cards than the fixed set — the same "never invent, but never
go quietly missing either" philosophy the codebase already applied to individual fields,
now applied to which categories exist at all.

### 12.2 The 7 phases

1. **Dashboard header completeness** — CR version / analysis version / status shown as a
   header strip, plus the AI-recommended-approval-types badge row (reusing Module 12's
   `GET .../approvals/recommended`) — frontend-only, no schema change.
2. **Affected Components (Evidence) + Dependencies (Relationship/Risk)** — `evidence` on
   `AffectedComponent`; `relationship_type` and `risk_severity` on `Dependency`; both
   backward compatible with pre-Module-14 analyses (all new fields nullable/defaulted).
3. **Complexity & Effort confidence** — `complexity_confidence` / `effort_confidence`
   (Low/Medium/High) on `Analysis`, falling back to "medium" if the AI's response omits
   them.
4. **Impact Analysis** — new `ImpactAssessment` table (one row per category per analysis),
   `ImpactCategory` enum, the fill-missing-categories validator, prompt + persistence
   wiring, and the Overview tab's Business/Technical Impact sections rewritten to read
   from the new structured data instead of free text.
5. **Security Findings** — new `SecurityFinding` table, `SecurityCategory` and
   `SecurityFindingStatus` enums, the same fill-missing-categories treatment, prompt +
   persistence wiring, and the Security tab rewritten to prefer the structured findings
   (falling back to the old free-text blob only for pre-Module-14 analyses that have none).
6. **Human Review** — `review_status` / `review_comment` / `reviewed_by` / `reviewed_at`
   added to `Requirement`; `review_comment` / `reviewed_by` / `reviewed_at` added to
   `SecurityFinding` (its existing `status` column is reused, now human-settable to
   Acknowledged/Resolved); `can_review_analysis_findings` permission helper; two new PATCH
   endpoints; two new `HistoryAction` values; frontend review controls on both the
   Requirements and Security tabs.
7. **This wrap-up** — full backend test-suite re-run and this report.

### 12.3 Files touched

Backend: `models/{enums,impact_assessment,security_finding,requirement,analysis}.py`,
`schemas/{impact_assessment,security_finding,requirement,ai_analysis,analysis}.py`,
`services/{analysis_engine,workflow_rules}.py`, `api/change_requests.py`.
Frontend: `api/analysis.js`, `pages/AnalysisDashboardPage.jsx`,
`styles/analysis-dashboard.css`.
Tests: `test_module14_phase{2,3,4,5,6}.py` (Phase 1 was frontend-only, reusing endpoints
already covered by existing tests, so it added no new test file).

### 12.4 API / schema changes

```
PATCH /api/change-requests/{id}/requirements/{requirement_id}/review        confirm / needs-clarification
PATCH /api/change-requests/{id}/security-findings/{finding_id}/status       open/acknowledged/resolved/not_applicable
```

`Analysis` gained `complexity_confidence`, `effort_confidence`, and two new child
collections, `impact_assessments` (`ImpactAssessmentRead[]`) and `security_findings`
(`SecurityFindingRead[]`) — both eager-loaded the same way every other analysis child
table already was.
`AffectedComponent` gained `evidence`; `Dependency` gained `relationship_type` and
`risk_severity` — all nullable, so pre-Module-14 analyses still validate and display
normally with those fields simply absent.
`Requirement` gained `review_status`, `review_comment`, `reviewed_by`, `reviewed_at`
(all nullable — `None` means "no human has reviewed this yet").
`SecurityFinding` gained `review_comment`, `reviewed_by`, `reviewed_at` (nullable, same
meaning); its `status` field is shared between the AI (which can only ever emit
`open`/`not_applicable`) and a human reviewer (who can set any of the four values via the
new endpoint above).

No tables were dropped or renamed. Two new tables (`impact_assessments`,
`security_findings`); new columns on three existing tables (`analyses`, `requirements`,
`dependencies`, `affected_components`); four new enums
(`ImpactCategory`, `SecurityCategory`, `SecurityFindingStatus`, `ReviewStatus`); two new
`HistoryAction` values (`requirement_reviewed`, `security_finding_status_changed`).
`init_db()` handles all of it the same way as every prior module — creates missing
tables and adds missing columns on startup, no manual migration needed.

### 12.5 Testing breakdown

23 new tests across Module 14's five backend-touching phases (all included in the 198
total in §6): `test_module14_phase2.py` (5 — Affected Component evidence, Dependency
relationship/risk fields, backward compatibility with pre-Module-14 responses, and the
existing placeholder-name filtering still working alongside the new fields),
`test_module14_phase3.py` (3 — Complexity/Effort confidence fields, their independence
from the overall classification confidence, and the "medium" fallback),
`test_module14_phase4.py` (4 — the 7-category Impact Analysis, the fill-missing-categories
guarantee, and backward compatibility), `test_module14_phase5.py` (4 — the 9-category
Security Findings, the same fill-missing-categories guarantee, and the fix for the
`_normalize()` / "not applicable" collision described in §12.6), `test_module14_phase6.py`
(7 — Requirement review round-trip never touching the AI's own certainty/confidence/
evidence columns, comment required for Needs Clarification (422 otherwise), 403 for an
unrelated user on both endpoints, audit-history recording for both, and the Security
finding status round-trip Open → Acknowledged → Resolved never touching finding/severity/
evidence/recommendation).

### 12.6 Frontend verification (done live, this session)

Same constraint as Module 13 (§11.6) — no JS syntax-checker available in this sandbox, so
each phase's frontend code was proofread carefully before being sent, then confirmed live
by you on CR-3338 after every phase:
- Phase 3: "Medium confidence" badges visible on both the Complexity/Effort summary cards
  and the dedicated Complexity & Effort tab.
- Phase 4: the Impact tab's new 7-card grid, and the Overview tab's Business/Technical
  Impact sections reading from the new structured data.
- Phase 5: all 9 Security category cards, including a "Not Applicable" badge on Secrets —
  the specific case the §12.7 bug fix was for.
- Phase 6: a Requirement showing a green "Confirmed" badge (with its AI-generated
  Business/Known/80% confidence/Evidence display untouched alongside it), and the
  Security tab showing a green "Resolved" badge on Authentication and a blue
  "Acknowledged" badge on Authorization — both statuses only a human review can produce.
- A full re-run of the backend test suite after every phase confirmed the running total
  (183 → 187 → 191 → 198) with no regressions at any step.

### 12.7 Two real bugs found and fixed along the way

**A process bug, not a code bug.** Phase 4's backend and frontend edits were made in this
session's own workspace but never actually copied to your machine before I asked you to
test — you correctly reported "183 passed" (Phase 3's count, unchanged) instead of the
187 Phase 4 should have produced. Fixed by pushing the missing files across immediately,
and from that point on every single file edited in any phase was pushed to your machine
right after editing it, before ever asking you to run anything — no repeat of this
mistake in Phases 5 or 6.

**A real data bug**, caught by your own test run. Phase 5 initially shipped with
`SecurityFindingStatus.NOT_APPLICABLE` silently turning into `open` every time, because
the codebase's generic "did the AI actually answer this field" helper (`_normalize()`)
treats the literal phrase "not applicable" as shorthand for "no answer given" — a
collision nobody had hit before because no earlier enum happened to use that exact
wording. You saw it as "1 failed, 190 passed" with
`test_pre_module_14_phase5_shaped_response_fills_all_categories` failing. Fixed with a
dedicated `_normalize_security_status()` function (the same pattern already used for
`Certainty`'s "unknown" value, which has the identical class of problem) that checks
Security-status values directly instead of going through the generic "no answer given"
detector. You confirmed 191/191 passing, then confirmed live that the "Not Applicable"
badge now displays correctly instead of "Open".

A related SQLite constraint worth recording for future modules: adding a new NOT-NULL
column to a table that already has real rows in it — as opposed to a brand-new table —
isn't safe here, because `init_db()`'s missing-column migration issues a bare
`ALTER TABLE ... ADD COLUMN` with no default, so existing rows read back as NULL despite
the Python model's own `nullable=False` claim. Every column added to `Requirement` (which
has existed since Module 1) in Phase 6 was declared nullable for exactly this reason;
`ImpactAssessment` and `SecurityFinding`, being brand-new tables created fresh by
`create_all()`, could safely use NOT NULL columns from day one.

---

## 13. Module 15 — Repository Intelligence (built this session)

Your own spec for this module, followed section by section: make the analyzer
repository-aware, answer "which source files may actually be affected by this change
request?", never introduce infrastructure the module doesn't need (no embeddings, no
vector database, no RAG pipeline), never claim more certainty than the evidence supports,
tie everything to a change request's exact version, feed the existing analysis sections
rather than building a second one, and never expose secrets. Module 12 workflow and
Module 13 AI version-awareness were mandatory integration points, per your spec — both
held: no parallel status/history/permission system was built, and every repository finding
is tied to an exact change-request version, AI analysis, and repository scan, computed
fresh on every response for whether any of those three has since moved on.

### 13.1 What it adds and why

Modules 6–14 told you what the AI concluded from the change request's own text. Module 15
adds a second, independent source of evidence: the project's actual source code.

- **Repository scanning** — indexes the project's own source files (defaulting to
  `hackathon_alight` itself, per your own choice when this module started), walking the
  folder tree while never descending into `node_modules`/`.git`/build/generated/cache
  directories, never opening `.env` files or anything else secret-shaped, respecting
  `.gitignore` where practical, and skipping anything over 512KB as irrelevant noise. Each
  scan is a new, independent, non-destructive row — an old scan's results are never
  overwritten, the same "history is never silently rewritten" rule Module 13 already
  applies to AI re-analysis.
- **Code understanding** — for each indexed file, extracts its imports, function/class
  names, API routes, database references, and config references. Python gets exact
  extraction via the standard library's own `ast` module (no external dependency); JS/TS,
  JSON/YAML/TOML/INI, and SQL get best-effort regex extraction. Never the file's raw
  content — only this extracted structure ever leaves the scanner, which is what makes the
  security guarantees in §13.7 possible in the first place.
- **CR → file matching, the module's headline feature** — a deterministic keyword-overlap
  pass shortlists at most 25 plausible candidate files out of however many the repository
  has (no embeddings or vector search needed for this), and only those candidates' own
  extracted structure — never raw source — is handed to the AI, which returns which of
  those *specific* files are actually affected, with a reason and evidence grounded in what
  was actually extracted.
- **Never claims certainty without evidence — enforced in code, not just prompted.** A
  finding's headline label is always one of exactly three hedged values — Possibly
  Related, Potentially Affected, Likely Affected — computed by code from the AI's numeric
  confidence score. There is no "definitely affected" value anywhere in this app; the AI's
  own wording is never trusted for this. A file the AI names that wasn't actually in the
  candidate shortlist is silently dropped, never persisted — the same hallucination-guard
  philosophy this codebase already applies elsewhere (`drop_placeholder_list_items`).
- **Version-aware, like everything else this module touches** — every finding carries the
  exact change-request version, AI analysis, and repository scan it was matched against.
  `is_outdated`/`outdated_reasons` are computed fresh on every request (never stored) from
  three independent checks: has the change request been edited since, has a newer AI
  analysis run, has a newer repository scan been taken. A "Re-scan Repository" button
  re-runs both steps and refreshes the page.
- **Feeds the existing analysis, doesn't duplicate it** — per your own explicit
  instruction not to build a second impact system, repository findings don't get their own
  standalone verdict. Instead, a computed-only `related_files` field (never stored, matched
  by keyword overlap the same way the candidate shortlist itself is built) is attached to
  Affected Components, the structured Impact Analysis, Dependencies, Risks, Test Cases, and
  Implementation Plan items wherever a real connection exists.

### 13.2 The 7 phases

1. **Foundation** — `repository_root` setting (defaults to the project's own folder);
   `RepositoryScan`/`IndexedFile` tables; the file walker with its ignore rules; 4 new
   `GET`/`POST /api/repository/...` endpoints.
2. **Code Understanding** — `code_understanding.py`'s `ast`-based Python extractor and
   regex-based JS/config/SQL extractors; 6 new columns on `IndexedFile` (imports,
   functions, classes, api_routes, database_references, config_references).
3. **CR → File Matching** — `RepositoryFinding` table; `FileMatchLabel` enum (exactly 3
   hedged values, no "definite" option); `repository_matcher.py`'s shortlist → AI call →
   hallucination-guarded persistence; 2 new endpoints
   (`POST`/`GET .../repository-findings`).
4. **Version Awareness + Re-scan** — `workflow_rules.repository_finding_outdated_reasons()`
   (a pure, DB-free rule function, same shape as `is_analysis_outdated`); `is_outdated`/
   `outdated_reasons` computed fresh on both repository-findings endpoints.
5. **Integration** — `repository_linkage.py`'s keyword-overlap `related_files` computation;
   a new field of the same name added to `AffectedComponentRead`, `ImpactAssessmentRead`,
   `DependencyRead`, `RiskRead`, `TestCaseRead`, `ImplementationTaskRead` — computed fresh
   by the API layer, never stored, no new table.
6. **Frontend** — a new "Repository" tab on the Analysis Dashboard (File/Impact/Confidence/
   Reason/Evidence per finding, a hedged-label badge, an outdated-findings banner, a
   "Re-scan Repository" button that chains scan → match → reload); a "Related files: ..."
   line added under every section Phase 5 touched, wherever non-empty.
7. **Security pass + full test + this report** — a dedicated audit (§13.7) plus this
   write-up.

### 13.3 Files touched

Backend (new): `models/{repository_scan,indexed_file,repository_finding}.py`,
`schemas/{repository_scan,repository_finding}.py`,
`services/{repository_scanner,code_understanding,repository_matcher,repository_linkage}.py`,
`api/repository.py`.
Backend (modified): `core/config.py`, `models/enums.py`, `models/__init__.py`,
`services/workflow_rules.py`, `api/change_requests.py`, `main.py`, `.env.example`,
`schemas/{affected_component,impact_assessment,dependency,risk,test_case,
implementation_task}.py` (each gained `related_files`).
Frontend (new): `api/repository.js`.
Frontend (modified): `pages/AnalysisDashboardPage.jsx` (new Repository tab + `related_files`
lines across six existing sections).
Tests: `test_module15_phase{1,2,3,4,5,7_security}.py` (Phase 6 was frontend-only — no
pytest coverage, verified live instead, see §13.6).

### 13.4 API / schema changes

```
POST /api/repository/scan                                    scans the configured repository root
GET  /api/repository                                          every scan ever run, newest first
GET  /api/repository/latest                                   the most recent scan, with its indexed files
GET  /api/repository/{scan_id}                                one specific scan, with its indexed files
POST /api/change-requests/{id}/repository-findings            matches this CR's current analysis against the latest scan
GET  /api/change-requests/{id}/repository-findings            whatever findings already exist for this CR's current analysis
```

Three new tables: `repository_scans`, `indexed_files`, `repository_findings`. Three new
enums: `RepositoryScanStatus`, `FileMatchLabel` (exactly `possibly_related` /
`potentially_affected` / `likely_affected` — no "definite" value exists), and reuses the
existing `ImpactLevel` for a finding's own impact rating. `AffectedComponentRead`,
`ImpactAssessmentRead`, `DependencyRead`, `RiskRead`, `TestCaseRead`, and
`ImplementationTaskRead` each gained `related_files: List[str] = []` — computed fresh by
the API layer, defaults to empty for every analysis that predates this module, never a
migration concern.

### 13.5 Testing breakdown

33 new tests across Module 15's phases (all included in the 231 total in §6):
`test_module15_phase1.py` (7 — the file walker's ignore rules, size cap, and `.gitignore`
handling), `test_module15_phase2.py` (7 — Python/JS/JSON extraction, a genuinely broken
Python file and an unsupported file type both degrading to empty lists rather than
failing), `test_module15_phase3.py` (6 — no-candidates-never-calls-the-AI, a real match
persisting with its label computed from confidence, a hallucinated file path silently
dropped, re-running replacing only that exact analysis/scan's own findings, a clean 404 for
a CR with no analysis yet), `test_module15_phase4.py` (4 — fresh findings are never
outdated, editing the CR marks them outdated, a new scan marks them outdated, and a direct
unit test of all three staleness branches), `test_module15_phase5.py` (4 — `related_files`
empty before any match exists, populated across all six linked sections once one does,
staying empty for an item with no genuine word overlap even when a real finding exists
elsewhere on the same analysis), `test_module15_phase7_security.py` (5 — a dedicated pass:
hardcoded secret literals in both Python and JS source never leak into any extracted
field, every secret-shaped file type is skipped before ever being opened, the exact AI
prompt payload and the two response schemas are locked to their known-safe field sets).

### 13.6 Frontend verification (done live, this session, on CR-3338)

Same constraint as Modules 13/14 — no JS syntax-checker available in the build sandbox, so
the Repository tab and the `related_files` additions were proofread carefully before being
sent, then confirmed live by you:
- The Repository tab correctly found `backend/app/schemas/auth.py` and
  `backend/app/api/change_requests.py`, both labeled "Likely Affected," for a real
  "Forget Password Functionality" change request — with confidence, reason, and evidence
  all showing.
- "Related files" lines correctly appeared under the Impact tab's Business/Technical/
  Customer/Operational cards and under the one Risk, all pointing back to the same two
  files — and correctly stayed absent on the empty Dependencies tab (no phantom lines on a
  section with nothing in it).
- Editing CR-3338 (bumping it to v2) made both the change request's own "AI analysis
  outdated" banner (Module 13) and the Repository tab's own "Some repository findings
  below may be outdated" banner appear together, each finding individually marked
  "Outdated" with "Why outdated: The change request has been edited since this finding was
  generated." — proving the version-awareness chain works end to end, live, not just in
  the test suite.

### 13.7 Security pass

Your spec's own rule 9 for this module: never expose API keys/passwords/tokens/secrets/
`.env` contents, and don't index sensitive files unnecessarily. Audited and verified with a
dedicated test file (`test_module15_phase7_security.py`), not just incidental coverage:

- **Never opened at all**: `.env` and every `.env.*` variant, `credentials.json`,
  `service-account.json`, `.npmrc`/`.pypirc`/`.netrc`, and every key/cert extension
  (`.pem`, `.key`, `.crt`, `.cer`, `.p12`, `.pfx`, `.keystore`, `.jks`) — skipped before the
  scanner ever reads their contents, not read-then-redacted.
- **Never extracted, even from files that ARE scanned**: a hardcoded secret literal —
  whether a bare module-level constant, a class attribute, or a `getenv(...)` *fallback
  default* — is never captured under any field, in either Python or JavaScript. Only the
  env-var/config-key *name* is ever extracted (e.g. `env:SECRET_KEY`), never a value —
  verified directly against real secret-shaped strings in the test file, not just asserted.
- **Never sent to the AI**: the exact shape of what `repository_matcher.py` hands the AI
  for one candidate file is locked down to 8 known-safe fields (file path, language, and
  the 6 extracted-name lists) — no raw content, and the test asserts no `content`/`source`/
  `text` key could ever sneak in.
- **Never returned by the API**: `IndexedFileRead`'s and `RepositoryFindingRead`'s own
  field sets are locked down the same way, so a future change to either model can't
  silently start returning raw file content to the frontend without that being a deliberate
  decision someone has to notice in a failing test.

### 13.8 Known limitations (disclosed, not blocking)

- `.gitignore` support is deliberately best-effort (comments, blank lines, plain `name` /
  `name/` / `*.ext` patterns, a leading `/` anchoring to the repo root) — negation
  (`!pattern`) is not supported, per the spec's own "respect `.gitignore` where practical,"
  not a full gitignore-spec implementation.
- The repository root is a single configured folder (defaults to the project's own code);
  scanning more than one repository at once isn't supported, since the spec called for
  "the simplest practical approach."
- `related_files` (Phase 5) is a keyword-overlap heuristic, the same kind of lightweight
  matching the candidate shortlist itself already uses — it can occasionally miss a real
  connection worded very differently, or (rarely) surface a coincidental one; it never
  invents a repository finding that doesn't already exist, only groups the ones that do.
- A `Claude outputs/` subfolder inside the project (holding files delivered by earlier
  Claude sessions) gets indexed like any other folder in the repo, since it isn't excluded
  by any rule — cosmetic noise in scan results, not a functional or security issue; adding
  it to `.gitignore` was offered earlier and is still available if you'd like it done.

---

## 14. Module 16 — Project Knowledge Base & RAG (built this session)

Your own spec for this module, followed section by section: let you upload project
documentation (architecture docs, API docs, engineering guidelines, security policies,
deployment docs, PRDs, specs), have CR analysis retrieve genuinely relevant excerpts as
grounding context with source attribution, reuse the existing Known/Inferred/Unknown
concept rather than inventing a new one, stay version-aware like every other analysis
output, and avoid unnecessary infrastructure (no vector database, no Docker, no separate
embedding service). All of that held: no Pinecone/FAISS/pgvector was introduced, embeddings
are JSON-encoded floats on one existing-shape column, retrieval is brute-force cosine
similarity in pure Python (fine at hackathon scale), and every piece of evidence a CR
analysis used is tied to an exact document/section/change-request-version, computed fresh
for staleness on every response the same way Module 13's outdated-analysis detection and
Module 15's repository-finding staleness already work.

### 14.1 What it adds and why

Modules 6–15 told you what the AI concluded from the change request's own text and (as of
Module 15) the project's own source code. Module 16 adds a third, independent source of
grounding: your team's own documentation.

- **Upload → parse → chunk** — `.txt`, `.md`, and `.pdf` documents are saved to plain local
  disk under `backend/data/knowledge_documents/` (already excluded from Module 15's own
  repository scanner, so an uploaded document can never accidentally get re-indexed as
  source code), then immediately parsed and split into paragraph-accumulated chunks capped
  at 1,200 characters — markdown gets heading-aware sectioning, PDFs get one section per
  page, oversized single paragraphs get a clean hard-split fallback. A document that fails
  to parse is marked FAILED with a real, visible error message — never silently dropped —
  and can be retried with a dedicated reprocess action.
- **Embed → search** — a new `embed()` method on the existing swappable `AIProvider`
  abstraction (implemented for OpenRouter via its `/api/v1/embeddings` endpoint), kept as an
  explicit, separate step from upload since it's the one part of this pipeline that makes a
  real network call. Search is brute-force cosine similarity over JSON-encoded vectors — no
  vector database, per your own instruction to keep infrastructure minimal.
- **CR analysis integration, the module's headline feature** — before building its prompt,
  the analysis engine now searches the knowledge base using the change request's own
  title/description/business objective, and only injects a "Relevant Documentation" section
  into the prompt when something scores above a real similarity cutoff (0.2) — never just
  "the closest thing on file." A knowledge-base failure (embedding provider down, nothing
  relevant) never breaks the core analysis; it degrades to no grounding context, same as
  before this module existed.
- **Source attribution & version awareness** — every chunk the AI was actually shown gets
  its own `KnowledgeEvidence` row: document title, section label, the exact excerpt, its
  similarity score, and the change-request version it was retrieved against — snapshotted
  at retrieval time so evidence stays historically accurate even if the source document is
  later reprocessed, re-embedded, retitled, or archived. `is_outdated` is computed the same
  way the parent analysis's own is — evidence has exactly one staleness axis (has the change
  request been edited since), never a second, independent check.
- **Archive, never hard-delete** — a document can be archived (dropping it out of the
  default list and out of all search/analysis retrieval) and unarchived, but its file,
  chunks, and embeddings are always kept intact, since `KnowledgeEvidence` rows carry a real
  foreign key back to their document and must stay resolvable forever, even for a document
  that's since been archived or superseded.

### 14.2 The 7 phases

1. **Foundation** — `KnowledgeDocument`/`KnowledgeChunk` tables; `KnowledgeDocumentStatus`
   enum (UPLOADED → PROCESSING → READY/FAILED, mirroring `RepositoryScanStatus`); upload/
   list/get endpoints.
2. **Parsing + Chunking** — `knowledge_chunker.py`'s `.txt`/`.md`/`.pdf` extraction and
   paragraph-accumulated chunking; upload now parses+chunks synchronously (pure local text
   processing, no queue needed); a reprocess endpoint for retrying a FAILED document.
3. **Embedding + Vector Search** — `embed()` added to the `AIProvider` base (implemented for
   OpenRouter); `knowledge_embeddings.py`'s brute-force cosine-similarity search; explicit
   `POST .../embed` and `GET .../search` endpoints, kept separate from upload/chunking.
4. **CR Analysis Integration** — `analysis_engine.py`'s `_retrieve_knowledge_context()`
   (title + description + business objective as the search query, `min_score=0.2`) and the
   rewritten system prompt describing an optional "Relevant Documentation" section with
   citation rules and an explicit anti-fabrication guard.
5. **Source Attribution & Version Awareness** — `KnowledgeEvidence` table (snapshotted
   fields, a deliberately non-FK `chunk_id` since chunks get replaced wholesale on
   reprocess); `knowledge_evidence` added to `AnalysisRead`; `is_outdated` set on each
   evidence row the same way it's set on the parent analysis.
6. **Frontend** — a new Knowledge Base page (upload, status/chunk-count table, search,
   per-document chunk preview showing embedding status, embed/reprocess/archive/unarchive
   actions); an "Evidence Used" section added to the Analysis Dashboard's Overview tab,
   reading `analysis.knowledge_evidence` directly (no new fetch needed).
7. **Security pass + full test + this report** — a dedicated audit (§14.7) plus this
   write-up.

### 14.3 Files touched

Backend (new): `models/{knowledge_document,knowledge_chunk,knowledge_evidence}.py`,
`schemas/{knowledge_document,knowledge_chunk,knowledge_search,knowledge_evidence}.py`,
`services/{knowledge_documents,knowledge_chunker,knowledge_embeddings}.py`,
`api/knowledge.py`.
Backend (modified): `models/enums.py` (`KnowledgeDocumentStatus`), `models/__init__.py`,
`models/analysis.py` (`knowledge_evidence` relationship), `schemas/analysis.py`
(`knowledge_evidence` field), `services/ai/base.py` (`embed()`),
`services/ai/providers/openrouter_provider.py` (`embed()` implementation), `core/config.py`
(`openrouter_embedding_model`), `api/change_requests.py` (evidence eager-loading +
`is_outdated` propagation), `main.py`, `requirements.txt` (`python-multipart`, `pypdf`).
Frontend (new): `api/knowledge.js`, `pages/KnowledgeBasePage.jsx`, `styles/knowledge-base.css`.
Frontend (modified): `pages/AuthenticatedHome.jsx` (routes the already-existing
"Knowledge Base" nav item), `pages/AnalysisDashboardPage.jsx` (new "Evidence Used" section
on the Overview tab).
Tests: `test_module16_phase{1,2,3,4,6,7_security}.py` (Phase 5 folded into Phase 4's own
test file since they shipped as one combined delivery; Phase 6 backend-support pieces —
`is_embedded` and the archive/unarchive endpoints — landed in `test_module16_phase6.py`,
the page itself verified live instead, see §14.6).

### 14.4 API / schema changes

```
POST /api/knowledge/documents                                 uploads a .txt/.md/.pdf file, parses+chunks it synchronously
GET  /api/knowledge/documents                                 every non-archived document, newest first (?include_archived=true to include archived ones)
GET  /api/knowledge/documents/{id}                             one document's own metadata
POST /api/knowledge/documents/{id}/reprocess                  retries parsing+chunking for a FAILED document
POST /api/knowledge/documents/{id}/embed                      embeds (or re-embeds) every chunk via the configured AI provider
GET  /api/knowledge/documents/{id}/chunks                     every chunk, in order, each reporting is_embedded (never the raw vector)
POST /api/knowledge/documents/{id}/archive                    hides a document from lists/search/analysis retrieval (file/chunks/embeddings kept intact)
POST /api/knowledge/documents/{id}/unarchive                  reverses archive
GET  /api/knowledge/search                                    ranks embedded, non-archived chunks by similarity to ?q=
```

Three new tables: `knowledge_documents`, `knowledge_chunks`, `knowledge_evidence`. One new
enum: `KnowledgeDocumentStatus` (`uploaded`/`processing`/`ready`/`failed`). `AnalysisRead`
gained `knowledge_evidence: List[KnowledgeEvidenceRead] = []` — computed and populated fresh
by the API layer, defaults to empty for every analysis that predates this module, never a
migration concern.

### 14.5 Testing breakdown

38 new tests across Module 16's phases (all included in the 269 total in §6):
`test_module16_phase1.py` (8 — upload validation: unsupported extension, empty file,
oversized file, all cleanly rejected before anything touches disk or the database),
`test_module16_phase2.py` (8 — `.txt`/`.md`/`.pdf` extraction including a real PDF built
with `fpdf2`, markdown heading-aware sectioning, an oversized single paragraph hard-split
correctly, a genuinely broken PDF marked FAILED with a real error message, the chunk schema
locked to its field set), `test_module16_phase3.py` (8 — embedding populates and hides
vectors, embedding a chunkless document is a clean 400, an unconfigured provider fails
cleanly, search ranks by similarity and excludes unembedded/archived chunks),
`test_module16_phase4.py` (5 — CR analysis genuinely injects documentation and persists
evidence, an unrelated CR gets zero evidence rather than "the closest thing on file," an
unavailable embedding provider never breaks the core analysis, evidence becomes outdated
exactly when its parent analysis does), `test_module16_phase6.py` (4 — `is_embedded`
correctly reports false-then-true without ever exposing the vector, archive/unarchive
correctly move a document in and out of the default list while keeping its chunks intact,
an archived document's chunks are excluded from search), `test_module16_phase7_security.py`
(5 — see §14.7).

### 14.6 Frontend verification (done live, this session)

Confirmed live, by you, on your machine:
- The Knowledge Base page correctly listed an uploaded document as "Ready" with its chunk
  count, and expanding its row correctly showed the chunk marked "Embedded" with its actual
  content, never the raw vector.
- Archive/Unarchive worked correctly end to end — an archived document disappeared from the
  default list, reappeared with "Show archived" checked, and "Unarchive" correctly restored
  it to the default list. (What briefly looked like a missing Archive button was just its
  intentionally low-emphasis text-link styling, matching this app's existing secondary-
  action convention — confirmed present and working once pointed out.)
- A real, non-seeded change request ("Add OTP verification to Alight.com checkout"),
  analyzed for real (not one of the synthetic stress-test rows from Module 3's bulk seed
  data, which never had a genuine "AI Summary" and can never show evidence since they never
  called the real analysis engine), correctly showed a new "Evidence Used" section on its
  Overview tab: the uploaded document's title, a similarity-confidence bar, and the exact
  excerpt the AI was shown ("OTP codes for Alight.com must expire after 5 minutes and be
  rate-limited per phone number").

### 14.7 Security pass

Verified with a dedicated test file (`test_module16_phase7_security.py`), not just
incidental coverage from earlier phases:

- **Never returned by any API response, even once a document is genuinely embedded**: the
  raw embedding vector never appears in the document, chunk-list, search, or CR-analysis-
  evidence responses — checked directly against the raw response body, not just the
  schema's declared fields.
- **Every knowledge-base endpoint requires authentication** — list, get, chunks, search,
  embed, reprocess, archive, unarchive, and upload itself all cleanly reject an
  unauthenticated request (401) rather than allowing anonymous read or write access to
  uploaded documents.
- **A path-traversal filename can never escape the storage directory** — `../../../etc/
  passwd.txt`, a Windows-style `..\..\windows\win.ini.txt`, and an absolute `/etc/cron.d/
  evil.txt` all upload successfully but land as a flat, sanitized filename directly under
  `backend/data/knowledge_documents/`, verified by inspecting the storage directory itself
  after each attempt — never a new subdirectory, never a file outside that one folder.
- **Archiving is a genuine retrieval boundary, not just a list filter** — a document with a
  perfect keyword/embedding match to a real change request contributes zero evidence to
  that CR's analysis once archived, verified through the full `/analyze` pipeline, not just
  `search_chunks()` in isolation.
- **Every response schema locked to its documented field set** — `KnowledgeDocumentRead`,
  `KnowledgeChunkRead`, `KnowledgeSearchResult`, and `KnowledgeEvidenceRead` are each checked
  against their exact expected fields, plus a blanket check that none of the four ever names
  the raw embedding or a server filesystem path under any field name — so a future change to
  any of them can't silently start returning something new without a test having to notice.

Role-based restriction (who may upload/archive vs who may only view/search) was **not**
added here — see §14.8.

### 14.8 Known limitations (disclosed, not blocking)

- **Any authenticated user can upload, embed, archive, or search the knowledge base** — the
  same "any authenticated user, for now" starting point Module 15's repository endpoints
  shipped with. Real role-based restriction (e.g. only certain roles may upload or archive)
  is a deliberate deferral, not an oversight — this hackathon's user/role model doesn't yet
  distinguish "may manage the knowledge base" from "may view change requests," and adding it
  half-built for one module while every other module stays "any authenticated user" would be
  inconsistent. Straightforward to add later using the same permission-check pattern Module
  12's approvals already established, if you want it.
- No hard delete for a knowledge document — only archive/unarchive. This is a deliberate
  data-integrity choice, not a missing feature: `KnowledgeEvidence` rows carry a real foreign
  key back to their document (unlike `chunk_id`, which is intentionally not a hard FK, since
  chunks get replaced wholesale on reprocess) specifically so past evidence never points at
  nothing. Hard-deleting a document that's already been cited as evidence would either break
  that link or require cascading deletes into analysis history — the same "never silently
  rewrite history" principle Module 12's audit trail and Module 13's outdated-analysis
  detection already hold elsewhere in this app.
- Search and retrieval are brute-force cosine similarity in pure Python, per your own
  instruction to avoid unnecessary infrastructure — perfectly fine at hackathon scale (a
  handful of documents, at most a few hundred chunks), but not something to scale to a real
  production knowledge base without revisiting.
- `min_score=0.2` (the cutoff for what counts as "relevant enough" to ground CR analysis) is
  a deliberately simple, adjustable heuristic, not a scientifically tuned value — the manual
  search endpoint itself uses no cutoff at all (0.0), so a person searching can always see
  the closest results even when weak; only the automatic CR-analysis grounding path applies
  the stricter cutoff, specifically to avoid fabrication risk.

---

## 15. Module 17 — Test Cases & Implementation Plan 2.0 (built this session)

Your own spec for this module, followed section by section: make test cases and the
implementation plan genuinely useful artifacts rather than a token gesture — real
preconditions and steps, a real requirement/risk trail, a real sense of whether either one
has gone stale since the change request last moved, and a way for a human to correct the
AI's wording without ever losing what the AI originally said or building a second,
competing editing/audit system next to the one Module 12 already established. All of that
held: `owner_suggestion` reuses Module 12's own `AssignmentRole` enum as a suggestion only,
requirement/risk references are computed by keyword overlap rather than trusted from the
AI's own wording (same reasoning Module 15 already applied to `related_files`), and every
edit is recorded on the existing `ChangeRequestHistory` timeline — no parallel table, no
parallel permission check.

### 15.1 What it adds and why

Modules 6–16 told you what the AI concluded, from the change request's own text, the
project's source code, and now its documentation. Module 17 makes two of those conclusions
— test cases and the implementation plan — richer and, for the first time, human-editable
without losing the AI's own original wording.

- **Richer generation** — `TestCaseItem` gained `preconditions` and `steps` (a real ordered
  list, not one paragraph to parse by eye), and the AI is instructed to ground both in that
  same analysis's own requirements/impact/risks/security findings rather than writing generic
  boilerplate; `ImplementationTaskItem` gained `owner_suggestion`, drawn only from Module 12's
  own `AssignmentRole` vocabulary and normalized to `null` the moment the AI's raw text isn't
  a real value, rather than ever guessing or fabricating a role.
- **Traceability, the module's headline feature** — `traceability_linkage.py` mirrors
  `repository_linkage.py`'s own keyword-overlap approach (Module 15) to compute
  `requirement_references`/`risk_references` on every test case and task, fully computed at
  read time from that same analysis's own rows — never AI-written, never able to name a
  requirement ID that doesn't actually exist. A new Traceability tab groups the whole analysis
  by requirement, showing exactly which tasks and test cases trace to it, and honestly
  labeling anything that didn't overlap enough to link automatically instead of forcing a
  match.
- **"May be outdated" banners** — reuse `analysis.is_outdated` (already true the instant the
  CR has been edited since this analysis ran) and the existing full-reanalysis action behind
  a "Regenerate" button — no second, partial-regeneration capability, and no new staleness
  computation beyond what Module 13 already established for the analysis as a whole.
- **Human editing, tied to Module 12's existing system, never a new one** — `PATCH
  .../test-cases/{id}` and `PATCH .../implementation-tasks/{id}` let an authorized human
  correct one row in place, gated by the exact same `can_review_analysis_findings` check
  Module 14 Phase 6 already uses for Requirements/Security findings. Only the fields actually
  sent change; a no-op resubmission is a cheap read, never a phantom audit entry. The AI's own
  original wording is never lost — it's preserved as the `old_value` on that edit's own
  `TEST_CASE_EDITED`/`IMPLEMENTATION_TASK_EDITED` history row, never a second "original"
  column bolted onto the row itself.

### 15.2 The 7 phases

1. **Data model foundation** — new `TestType` values (negative/boundary/api/ui/
   data_validation); new `HistoryAction` values (test_case_edited/implementation_task_edited);
   `TestCase` gained `preconditions`/`steps`(JSON list)/`edited_by`/`edited_at`/`edit_reason`;
   `ImplementationTask` gained `owner_suggestion`/`edited_by`/`edited_at`/`edit_reason`; both
   schemas expose computed `analysis_version`/`is_outdated` +
   `requirement_references`/`risk_references`, all safely empty/None for pre-Module-17 rows.
2. **Richer test-case generation** — the system prompt and `TestCaseItem` updated so the AI
   fills real preconditions/steps grounded in that analysis's own findings, using only the
   test types genuinely relevant to the change rather than padding every category.
3. **Richer implementation-plan generation** — `owner_suggestion` added the same way, reusing
   Module 12's own role vocabulary as a suggestion only, never a real assignment.
4. **Traceability** — `traceability_linkage.py`; wired into both `/analyze` and
   `GET .../analysis`; a new Traceability tab plus trace lines on the Test Cases and
   Implementation Plan tabs themselves.
5. **Outdated banners + Regenerate buttons** — frontend-only, reusing `is_outdated` and the
   existing `handleRegenerate` full-reanalysis action.
6. **Human editing** — the two `PATCH` endpoints, `_full_analysis_read()` (a shared "fully
   computed response" builder used only by these two endpoints, to avoid refactoring the
   already-tested `analyze`/`get_latest_analysis` code paths), and the frontend edit controls
   with an "Edited" badge.
7. **Dedicated version-sync test + this report** — a full lifecycle walk (§15.6) plus this
   write-up.

### 15.3 Files touched

Backend (new): `services/traceability_linkage.py`.
Backend (modified): `models/enums.py` (`TestType` additions, `HistoryAction` additions),
`models/test_case.py` (`preconditions`/`steps`/`edited_by`/`edited_at`/`edit_reason`),
`models/implementation_task.py` (`owner_suggestion`/`edited_by`/`edited_at`/`edit_reason`),
`schemas/test_case.py` (`TestCaseRead` additions, new `TestCaseUpdate`),
`schemas/implementation_task.py` (`ImplementationTaskRead` additions, new
`ImplementationTaskUpdate`), `schemas/ai_analysis.py` (`TestCaseItem`/`ImplementationTaskItem`
additions + normalizers), `services/analysis_engine.py` (prompt/persistence for both richer
shapes), `api/change_requests.py` (`_full_analysis_read`, `_apply_partial_update`,
`_stringify_field_value`, `_change_summary`, the two `PATCH` endpoints, traceability wiring in
`/analyze` and `GET .../analysis`).
Frontend (modified): `api/analysis.js` (`updateTestCase`, `updateImplementationTask`),
`pages/AnalysisDashboardPage.jsx` (Traceability tab, trace lines, outdated banners +
Regenerate buttons, `TestCaseEditControl`/`ImplementationTaskEditControl`),
`styles/analysis-dashboard.css` (traceability layout rules).
Tests: `test_module17_phase{1,2,3,4,6}.py`, `test_module17_phase7_sync.py` (Phase 5 has no
backend test file — frontend-only, verified live instead, see §15.6).

### 15.4 API / schema changes

```
PATCH /api/change-requests/{id}/test-cases/{test_case_id}              corrects one AI-generated test case in place; records TEST_CASE_EDITED
PATCH /api/change-requests/{id}/implementation-tasks/{task_id}         corrects one AI-generated task in place; records IMPLEMENTATION_TASK_EDITED
```

No new tables. `TestCaseRead` and `ImplementationTaskRead` each gained
`analysis_version`/`is_outdated`/`requirement_references` (`TestCaseRead` also gained
`risk_references`) — computed fresh by the API layer, same pattern as Module 15's
`related_files` and Module 16's `knowledge_evidence`; every field defaults safely for rows
that predate this module. `TestCaseUpdate`/`ImplementationTaskUpdate` are both "every field
optional, only what's actually sent gets changed" partial-update bodies, plus an optional
`reason` that lands on the history row, never on the test case/task itself.

### 15.5 Testing breakdown

27 new tests across Module 17's phases (all included in the 296 total in §6):
`test_module17_phase1.py` (4 — new enum values accepted, computed fields default safely for
pre-existing rows), `test_module17_phase2.py` (6 — preconditions/steps generated and
persisted correctly, widened `TestType` menu), `test_module17_phase3.py` (5 —
`owner_suggestion` generated, persisted, and normalized to `null` for anything not a real
`AssignmentRole` value), `test_module17_phase4.py` (4 — requirement/risk references computed
correctly with fixture wording carefully designed to avoid accidental keyword-overlap
collisions between unrelated rows), `test_module17_phase6.py` (7 — both `PATCH` endpoints edit
only the fields sent, record history with the AI's prior wording preserved as `old_value`, a
no-op edit never touches `edited_by`/history, a test-case/task id from another change request
404s, an unrelated user gets 403), `test_module17_phase7_sync.py` (1 — see §15.6).

### 15.6 The dedicated version-sync test (Phase 7)

Per your spec's own closing requirement — "a dedicated sync test verifying CR Version →
Analysis Version → Requirements → Test Cases → Implementation Plan all remain synchronized" —
this isn't incidental coverage left over from earlier phases. It's a single continuous
lifecycle test that walks:

1. First `/analyze` → CR v1, Analysis v1, every test case/task reports
   `analysis_version == 1`, `is_outdated == False`, and correctly traces to that analysis's
   own requirement.
2. Editing the change request bumps only the CR's own version (to 2) — the analysis row
   itself is untouched, but `GET .../analysis` immediately reports `is_outdated == True`, and
   that staleness correctly propagates onto every test case and task, exactly the way it
   already does for `knowledge_evidence` (Module 16) and repository findings (Module 15).
   `analysis_version` correctly stays at 1 — it never drifts just because the CR moved on.
3. A human can still edit a test case while its analysis is outdated (editing is never
   blocked by staleness) — and that edit's own history row is stamped with the CR's version
   *at the moment of the edit* (2), proving the audit trail's `version_number` and the
   analysis's own `change_request_version` are two independently-tracked numbers, never
   conflated.
4. Re-analyzing creates a brand-new Analysis tied to CR v2, with its own fresh requirement —
   every test case/task on it reports `analysis_version == 2`, `is_outdated == False` again,
   and traces only to this new analysis's own requirement, never back to the previous
   (now-superseded) one, even though both describe similar content.
5. The old analysis's edited test case is never resurrected as current — `GET .../analysis`
   (latest) never returns it; the edit lives on in that old analysis's own child row and
   permanently in the history trail, exactly the "never presented as current once the CR has
   moved to a newer version" rule from the Module 12 architecture lock.
6. The full history trail, read once at the end, shows both the CR field edit and the
   test-case edit, each correctly stamped with its own `version_number`, in the true order
   they happened.

Confirmed live on your machine as well, on both the Test Cases and Implementation Plan tabs:
editing a field, saving, and seeing the "Edited" badge appear — restarting the backend along
the way surfaced one unrelated environment quirk (PowerShell not recognizing the bare
`uvicorn` command on your machine), fixed the same way the earlier `pytest` launcher issue
was — `python -m uvicorn app.main:app --reload` instead of the bare command.

### 15.7 Known limitations (disclosed, not blocking)

- **No UI way to revert an edit back to the AI's original wording** — it's fully preserved
  (as the `old_value` on that edit's own history row, visible on the History tab), but
  restoring it today means retyping it into the edit form, not a one-click "revert." A
  straightforward addition later, reading the same history row.
- **Regenerating replaces the entire test-case/implementation-plan set, including any human
  edits** — this is the deliberate Phase 5 design (reusing the existing full re-analysis
  action rather than building a second, partial-regeneration capability), not an oversight:
  a human edit on a now-superseded analysis is never silently lost, it's just not part of
  the newest analysis, the same "old analyses are historical, never mutated forward" rule
  every other module here already follows.
- Same "any authenticated user with `can_review_analysis_findings`" permission scope Module
  14's own Requirement/Security review already established — no dedicated "test engineer" or
  "implementation owner" role distinct from that broader review permission.

---

## 16. Module 18 — Notifications, My Work & Personal Engineering Queue (built this session)

Your own spec for this module, followed section by section: a notification center people
can actually glance at without leaving whatever they're doing, a personal "what's on my
plate" dashboard built entirely on data Module 12 already owns, and a working reminder that
Module 12's notification/assignment tables are the permanent source of truth — no second
notification system, no second assignment system, no parallel "my tasks" table duplicating
what `Approval`/`ChangeRequestAssignment`/`Notification` already store. All of that held:
every My Work section is a differently-filtered read over those same three tables, the
notification bell reuses the exact same four endpoints the full Notifications page already
used, and the two genuinely new notification types (risk escalation, analysis completion)
plus the automatic deadline check slot into the same `Notification` row Module 12 defined,
never a row shaped any differently.

### 16.1 What it adds and why

Modules 1–17 told you what the AI concluded and let people act on a change request one at a
time, from its own detail page. Module 18 is the first module that looks across every change
request at once, from one person's point of view: what's actually waiting on *me* right now,
and a header widget that surfaces it without a page navigation.

- **An optional due date on approvals** — `Approval.due_date`, nullable, never required or
  defaulted (most approvals still have none). A due status — `"overdue"` / `"due_soon"` /
  `None` — is computed fresh at read time from it
  (`services/approvals.py::approval_due_status`), the same "never a stored boolean that can
  go stale" pattern `is_analysis_outdated`/`is_approval_outdated` already established. It's
  only ever meaningful for a still-PENDING approval.
- **Two new notification types, plus one automatic check** — `RISK_ESCALATED` fires when a
  re-analysis lands a change request in a strictly *higher* risk bucket than before (reusing
  `analysis_delta.py::compare_analyses`'s own before/after buckets — never a second risk
  computation); `ANALYSIS_COMPLETED` fires once, on a change request's very first analysis
  only, to its creator and assignees (never the person who ran it). `DEADLINE_APPROACHING`
  is different in kind — nothing schedules it. `services/deadlines.py::
  check_and_notify_approaching_deadlines()` lazily checks only the *reading* user's own
  pending approvals, called from the two endpoints the frontend already polls every 30
  seconds (`GET /api/notifications` and `/unread-count`) — deliberately no cron/background
  scheduler, per this project's own "keep architecture minimal" rule. A new
  `Notification.approval_id` link makes it idempotent: it can fire at most once, ever, per
  approval.
- **My Work — the personal dashboard, spec section 3** — seven sections (My Change Requests,
  My Approvals, My Reviews, My Assignments, Changes Requested From Me, Mentions, Overdue
  Items), each its own small `GET /api/my-work/*` endpoint, each filtered at the database
  level (a real SQL `WHERE`/`.any(...)` condition), never "load every change request and
  filter in the browser" — spec section 7's own explicit requirement. Each section is lazily
  fetched only once its tab is actually opened, not all seven up front. "Changes Requested
  From Me" is confirmed to mean change requests *you own* where an approver responded
  Changes Requested (someone waiting on you to revise) — the opposite direction from My
  Approvals, where you're the one being asked to decide on someone else's work.
- **My Approvals actions, spec section 4** — Approve (one click), Reject/Request Changes
  (an inline comment box, comment required — the same rule the backend already enforces),
  and View CR, reusing the exact same `POST .../approvals/{id}/respond` endpoint and
  `respondToApproval()` helper the Change Request detail page's own Approvals section already
  used — never a second response pathway. The same actions appear on Overdue Items, since
  it's the same underlying approval rows.
- **Priority highlighting, spec section 6** — Overdue/Due Soon/High Risk/Critical
  Risk/Waiting for Me are all computed already, server-side, and just rendered as badges;
  nothing here is a second, competing risk or staleness computation.
- **The Notification Center, spec section 1** — a bell icon next to the sidebar's logo
  (this app's "header," despite being a left sidebar — see `AppHeader.jsx`'s own long-
  standing doc comment on that naming), showing an unread-count badge and, on click, the
  most recent notifications, mark-as-read/mark-all-read, and a jump straight to the linked
  change request — built entirely on `GET /api/notifications`, `/unread-count`,
  `PUT /{id}/read`, `PUT /read-all`, the same four endpoints the full Notifications page
  already used. The full page is still there for the complete, paginated history; the bell
  is only ever a quick-glance dropdown over the last few.

### 16.2 The 7 phases

1. **Data foundation** — `Approval.due_date`, `approval_due_status()`, two new
   `NotificationType` values (`RISK_ESCALATED`/`ANALYSIS_COMPLETED`) plus
   `DEADLINE_APPROACHING`, `Notification.approval_id`, `services/deadlines.py` wired into the
   two already-polled notification endpoints.
2. **Risk Escalation + Analysis Completion notifications** — `AnalysisDelta.risk_bucket_before/
   after` + `workflow_rules.risk_bucket_rank()`; both new types wired into `/analyze`, each
   independently guarded so they fire only under their own real condition (and can fire
   together for the same re-analysis without being a duplicate of one event).
3. **My Work backend** — `api/my_work.py` (all seven `GET` endpoints + a cheap `/summary`),
   `schemas/my_work.py`, every query filtered at the database level.
4. **My Work frontend** — `MyWorkPage.jsx`, the seven-tab dashboard, lazy per-tab fetching,
   clickable summary tiles, priority badges.
5. **My Approvals actions + due-date input** — Approve/Reject/Request Changes wired onto both
   the My Approvals and Overdue Items tables; an optional Due date field added to the
   existing "Request Approval" form on the Change Request detail page.
6. **Notification Center header widget** — the bell + dropdown in `AppHeader.jsx`, no backend
   changes.
7. **Dedicated notification tests + this report** — §16.5/§16.6 below.

### 16.3 Files touched

Backend (new): `services/deadlines.py`, `api/my_work.py`, `schemas/my_work.py`.
Backend (modified): `models/approval.py` (`due_date`), `models/notification.py`
(`approval_id`), `models/enums.py` (`RISK_ESCALATED`/`ANALYSIS_COMPLETED`/
`DEADLINE_APPROACHING`), `schemas/approval.py` (`due_date`/`due_status` on
`ApprovalRequestCreate`/`ApprovalRead`), `schemas/notification.py` (`approval_id`),
`services/approvals.py` (`approval_due_status`/`DUE_SOON_WINDOW`, `due_date` param on
`request_approval`), `services/notify.py` (`approval_id` param), `services/analysis_delta.py`
(`risk_bucket_before`/`risk_bucket_after`), `services/workflow_rules.py`
(`risk_bucket_rank`), `api/notifications.py` (the two endpoints now also run the deadline
check), `api/change_requests.py` (`due_date` wiring on approval requests, `RISK_ESCALATED`/
`ANALYSIS_COMPLETED` firing in `/analyze`). No `database/init_db.py` changes needed — its
existing generic `_add_missing_columns()` migration already covers new columns on existing
tables automatically.
Frontend (new): `api/myWork.js`, `pages/MyWorkPage.jsx`, `styles/my-work.css`.
Frontend (modified): `components/AppHeader.jsx` + `components/header.css` (the notification
bell + dropdown), `components/ChangeRequestDetail.jsx` (Due date field on the Request
Approval form), `pages/AuthenticatedHome.jsx` (My Work route, bell → jump-to-CR wiring),
`pages/NotificationsPage.jsx` (labels/colors for the 3 new notification types).
Tests: `test_module18_phase{1,2,3}.py`, `test_module18_phase7_notifications.py` (Phases 4/5/6
were frontend-only — verified live instead, see §16.6).

### 16.4 API / schema changes

```
GET  /api/my-work/summary                cheap counts for all 7 sections' metric tiles
GET  /api/my-work/change-requests         change requests the current user created
GET  /api/my-work/approvals               approvals tagged to the current user (?status=pending|all)
GET  /api/my-work/reviews                 CRs where the user is Reviewer/Technical Lead/Security Reviewer/Owner
GET  /api/my-work/assignments             CRs where the user holds ANY assignment role
GET  /api/my-work/changes-requested       CRs the user owns with a Changes-Requested approval
GET  /api/my-work/mentions                every time the user was @mentioned
GET  /api/my-work/overdue                 the user's own overdue pending approvals
```

No new write endpoints — My Approvals' Approve/Reject/Request Changes buttons and the
Request Approval form's new Due date field both reuse the existing
`POST .../approvals`/`POST .../approvals/{id}/respond` endpoints, just with one more
optional field (`due_date`) or via the already-existing `respondToApproval` client helper.
`ApprovalRead` gained `due_date`/`due_status`; `NotificationRead` gained `approval_id`
(non-null only for a `DEADLINE_APPROACHING` row, letting it identify — and never
re-duplicate — the exact approval it's about).

### 16.5 Testing breakdown

31 new tests across Module 18's four test-bearing phases (all included in the 327 total in
§6): `test_module18_phase1.py` (7 — due-date round-tripping, due_soon/overdue computation,
due_status clearing once responded, the deadline notification firing exactly once via both
polled endpoints, confirmed never leaking to an unrelated user or even the CR's own owner),
`test_module18_phase2.py` (5 — `ANALYSIS_COMPLETED` only on a CR's first-ever analysis,
`RISK_ESCALATED` only on a genuine bucket increase, confirmed it can fire alongside
`ANALYSIS_SIGNIFICANTLY_CHANGED` for the same re-analysis without being a duplicate),
`test_module18_phase3.py` (9 — per-section correctness, the Reviewer-role-vs-any-role
distinction between My Reviews and My Assignments, Changes Requested's owner-only visibility,
Overdue excluding due-soon/already-resolved approvals, summary counts matching the section
endpoints, cross-user scoping), `test_module18_phase7_notifications.py` (10 — see §16.6).
Phases 4/5/6 were frontend-only (the My Work page itself, the approval action buttons +
due-date input, the notification bell) — confirmed live on your machine instead, screenshots
and click-throughs rather than a pytest count.

### 16.6 The dedicated notification tests (Phase 7)

Per your spec's own section 8 — dedicated tests for Approval, Assignment, Mention, Changes
Requested, Re-analysis, Re-approval, plus confirming users only ever see their own
notifications — this phase's own test file fills in exactly the pieces that were still
missing a real `Notification`-row assertion (several of these events already had thorough
history-event or permission coverage elsewhere in this suite; what hadn't been directly
checked before was that a `Notification` row actually gets created, for the right person,
and never for the wrong one):

- **Approval** — requesting one notifies only the tagged approver; a response (Approved,
  Rejected, or Changes Requested) notifies only the original requester — never the person
  who just took the action, in either direction.
- **Assignment** — being assigned notifies only the newly-assigned person, never whoever
  assigned them.
- **Mention** — already extensively covered by Module 12's own comments/notifications test
  file (dedup against a plain comment notification, scoping, etc.); one light test here
  keeps this module's own record self-contained.
- **Changes Requested** — the same Approval-response flow above, called out on its own since
  your spec lists it separately; also cross-checked against My Work's own "Changes Requested
  From Me" endpoint, confirming the two features agree on the same underlying event.
- **Re-analysis** — `ANALYSIS_SIGNIFICANTLY_CHANGED`/`RISK_ESCALATED`/`ANALYSIS_COMPLETED`
  already have thorough dedicated coverage (Module 13's own test file, and §16.5's own
  Phase 2 tests); this phase adds the one piece that was still missing a Notification-row
  check — `ANALYSIS_OUTDATED`, fired when a change request is edited after it was analyzed,
  telling its stakeholders a re-analysis is worth doing.
- **Re-approval** — `REAPPROVAL_REQUIRED` (a change request edited while an approval against
  an earlier version is still pending) is asserted both ways: it fires for the tagged
  approver when a pending approval is genuinely invalidated by an edit, and it never fires
  at all when there was no pending approval to begin with.
- **Scoping** — one consolidated test confirms an outsider with no stake in the change
  request sees none of Module 18's own newer notification types (risk escalation, analysis
  completion, re-approval, analysis-outdated) even while an assignee and an approver on that
  same change request are actively receiving them — closing the loop your spec's own section
  8 asked for, specific to this module's own additions (`DEADLINE_APPROACHING` already has
  its own dedicated scoping test from Phase 1; the older notification types already have
  theirs in Module 12's own test file).

### 16.7 Known limitations (disclosed, not blocking)

- **The notification bell shows only the 8 most recent notifications** — a deliberate
  quick-glance widget, not a second paginated inbox; the full Notifications page (unchanged,
  still there in the sidebar nav) is still where you'd go for the complete history or to
  filter to unread-only.
- **"Changes Requested From Me" can show a CR whose feedback has already been addressed by a
  later edit** — same disclosed simplification `api/my_work.py`'s own docstring already
  notes: there's no "has this feedback been resolved" flag anywhere else in this app to check
  against (a responded approval's own `is_outdated` is always `False`, by design), so it
  shows every change request with *any* Changes-Requested approval ever recorded, not only
  unaddressed ones.
- **`DEADLINE_APPROACHING` is the only kind of per-user deadline this app tracks** — Overdue
  Items and the due-soon/overdue badges are both built on `Approval.due_date` alone; there's
  no equivalent due-date concept yet on a change request itself or on an assignment.
- Same permission model every prior module already established — requesting an approval (and
  therefore setting its due date) stays Owner/Technical Lead/creator/Admin-gated
  (`can_request_approval`), and only the tagged approver can ever respond to it.

---

## 17. Module 19 — Engineering Change Analytics (built this session)

Your own spec for this module, followed section by section: seven kinds of metrics
(Executive, Workflow, Risk, Approval Bottlenecks, Change, Workload, AI) computed entirely
from real database records — "DO NOT generate fake statistics" was your own explicit
instruction, and every number on this page is traceable back to a real row somewhere in
this app, never an invented or placeholder figure. One shared filter set (date range,
status, priority, risk, category, owner) applies consistently across all six endpoints, and
the AI section is deliberately labeled "AI Recommendation Statistics," never "AI Accuracy" —
this app has no ground-truth record of whether an AI recommendation was actually *right* in
hindsight, so nothing here claims or implies an accuracy rate.

### 17.1 What it adds and why

Every prior module told you about one change request at a time, or one person's own queue
(Module 18's My Work). Module 19 is the first module that looks across the *whole system* at
once — is the workflow actually moving, where is it getting stuck, and what has the AI
actually been saying — the numbers a CAB or an engineering lead would actually want on one
screen.

- **Executive Metrics, spec section 1** — Total/Open/Pending Approval/Approved/Rejected/In
  Progress/Closed, mapped directly onto the existing `ChangeRequestStatus` lifecycle (no new
  status concept needed). The 6 named buckets are mutually exclusive by construction — Open
  covers every pre-approval-pipeline status (Draft through Changes Requested), In Progress
  covers every post-approval, pre-closure status (Implementation Planned through Validated).
  Cancelled deliberately sits outside every named bucket (it's genuinely not "open,"
  "approved," "rejected," "in progress," or "closed") — it's still counted in `total`, just
  not double-counted into a bucket that would misrepresent it.
- **Workflow Metrics, spec section 2** — average time to analysis/approval/implementation/
  closure (each `null`, never `0`, when nothing in the filtered set has reached that
  milestone — a stored `0` would silently understate the average once something finally
  does), CRs waiting for approval (any CR with a currently-PENDING approval — a broader,
  more real-time view than Executive Metrics' own status-based Pending Approval count), and
  CRs with requested changes (the CR's current status).
- **Risk Analytics, spec section 3** — the same low/medium/high/critical/not_analyzed
  distribution shape the existing Dashboard already uses, computed over the filtered set
  instead of the whole database, plus a new monthly trend (`RiskTrendChart.jsx`) showing what
  fraction of each month's newly-analyzed change requests landed in each bucket.
- **Approval Bottlenecks, spec section 4** — pending approvals by `ApprovalType` (this app's
  closest existing stand-in for "team" — there's no real team concept anywhere in the schema)
  and by approver name, average approval duration by type, and the approval types most often
  responsible for a Rejected or Changes Requested outcome. Person-level detail is
  deliberately limited to a name and a count — no email, no other account details — per your
  spec's own "do not expose unnecessary sensitive information" instruction.
- **Change Analytics, spec section 5** — CRs with multiple revisions and average versions per
  CR (both read `ChangeRequest.current_version` directly — it's kept in lockstep with the
  real version count by every edit, so there's no need to recount `ChangeRequestVersion` rows
  separately), the most frequently changed fields (from `FIELD_CHANGED` history events), and
  CRs still awaiting clarification (their latest analysis has an unresolved
  `ClarificationQuestion` — the same check `api/my_work.py`'s own
  `requires_clarification` status already uses).
- **Workload, spec section 6** — change requests per owner (the one per-person breakdown the
  spec actually asks for here), plus organization-wide pending-reviews/pending-approvals/
  overdue-tasks totals. This is the one section that excludes the app's own bulk-seeded
  load-test bot accounts (`loadtest{1-5}@alight.com`, from `database/seed_bulk.py`) —
  confirmed with you during planning — every other section counts them like any other real
  row.
- **AI Analytics, spec section 7** — number of analyses, re-analysis rate, average
  confidence, risk changes after edits (how many times, across each CR's own analysis
  history in order, a re-analysis landed in a different risk bucket than the one right
  before it), AI-recommended approvals (analyses whose recommendation was Approve or Approve
  with Conditions), and AI analysis failures (a genuinely new tracking hook — see 17.1's own
  callout below). Every field here is computed over every `Analysis` row in the filtered set,
  not just each CR's latest one, so "number of analyses" and "average confidence" share the
  same granularity.
- **A new AI-failure tracking hook** — before this module, a failed `/analyze` call (bad AI
  response, provider not configured, a timeout) resulted in nothing at all being persisted —
  just an HTTPException back to the caller. That was a real gap: "AI analysis failures" would
  have had zero real data to report. Fixed with one small additive change: a new
  `HistoryAction.AI_ANALYSIS_FAILED` event, logged the same way a successful analysis already
  is (`actor_label="AI Analyzer"`, no `user_id`), right before the exception is re-raised.
  Failures from before this module existed are simply not counted — there was nowhere for
  them to have been recorded.

### 17.2 The 7 phases

1. **Backend foundation** — `services/analytics.py`'s `AnalyticsFilters` dataclass and
   `filtered_change_requests()` shared query helper (SQL push-down for date/status/priority/
   owner; risk/category applied in Python afterward, since neither has a direct column —
   both derive from the latest `Analysis` row), plus the new `AI_ANALYSIS_FAILED` hook.
2. **Executive + Workflow metrics** — `GET /api/analytics/executive`, `api/analytics.py`
   (the shared `_parse_filters` dependency every later endpoint reuses), `schemas/
   analytics.py`.
3. **Risk Analytics + Approval Bottlenecks** — `GET /api/analytics/risk`,
   `GET /api/analytics/approval-bottlenecks`.
4. **Change Analytics + Workload** — `GET /api/analytics/change`, `GET /api/analytics/
   workload`.
5. **AI Analytics** — `GET /api/analytics/ai`.
6. **Frontend** — `pages/AnalyticsPage.jsx`, a new "Analytics" nav item, `components/
   RiskTrendChart.jsx`, `styles/analytics.css`.
7. **Final testing pass + this report** — §17.5/§17.6 below.

### 17.3 Files touched

Backend (new): `services/analytics.py`, `api/analytics.py`, `schemas/analytics.py`.
Backend (modified): `models/enums.py` (`HistoryAction.AI_ANALYSIS_FAILED`),
`api/change_requests.py` (the new history event logged in `/analyze`'s exception handler),
`main.py` (`analytics.router` registered).
Frontend (new): `api/analytics.js`, `pages/AnalyticsPage.jsx`, `components/
RiskTrendChart.jsx`, `styles/analytics.css`.
Frontend (modified): `components/AppHeader.jsx` (new "Analytics" nav item),
`pages/AuthenticatedHome.jsx` (the new route).
Tests: `test_module19_phase{1,2,3,4,5,7}.py` (Phase 6 was frontend-only).

### 17.4 API / schema changes

```
GET  /api/analytics/executive             Executive + Workflow Metrics (spec 1/2)
GET  /api/analytics/risk                  Risk Analytics (spec 3)
GET  /api/analytics/approval-bottlenecks  Approval Bottlenecks (spec 4)
GET  /api/analytics/change                Change Analytics (spec 5)
GET  /api/analytics/workload              Workload (spec 6)
GET  /api/analytics/ai                    AI Recommendation Statistics (spec 7)
```

All six accept the same optional query parameters: `date_from`, `date_to`, `status`,
`priority`, `risk`, `category`, `owner_id` (spec section 8). No new write endpoints — this
module is read-only reporting over data every prior module already writes.

### 17.5 Testing breakdown

41 new tests across Module 19's six test-bearing phases (Phase 6 was frontend-only):
`test_module19_phase1.py` (4 — the new `AI_ANALYSIS_FAILED` history hook via invalid-JSON/
timeout/success/repeated-failure cases through the real `/analyze` + `/history` endpoints),
`test_module19_phase2.py` (11 — each Executive Metrics bucket including the Cancelled
edge case, Workflow Metrics' average-duration fields and waiting/requested-changes counts,
owner-based filter scoping, invalid filter values), `test_module19_phase3.py` (7 — risk
distribution including the not-analyzed bucket and the monthly trend, approval-bottleneck
pending/duration/blocker counts, confirming person-level detail carries only a name and a
count), `test_module19_phase4.py` (8 — multiple-revision/versions-per-CR counts, most-
changed-fields, clarification detection, per-owner workload breakdown, bulk-seed-bot
exclusion), `test_module19_phase5.py` (7 — analysis counts and confidence averaging,
re-analysis rate across a mix of analyzed/re-analyzed CRs, risk-change detection across
consecutive analyses, AI-recommended-approval counting, AI-failure counting), and
`test_module19_phase7.py` (4 — see §17.6). Phase 6 was frontend-only (the Analytics page
itself) — not yet visually confirmed by you.

Combined with the 327 passing through Module 18, that's **368 tests total**, once you run
them (see §17.6 for what's confirmed so far).

### 17.6 The final testing pass (Phase 7)

Per your spec's own section 10 — verify calculations against database records, test empty
data, test large data, test filters — `test_module19_phase7.py` is the one dedicated pass
that exercises all 6 endpoints together, rather than one more slice of any single endpoint's
own business rules (Phases 1-5 already covered those in detail):

- **Empty data** — a freshly-registered user with zero change requests gets a real "nothing
  yet" shape from every one of the 6 endpoints (zero counts, `null` averages, empty lists,
  `200 OK`) — never an error, and never a stray row belonging to some other test in the
  shared database.
- **Large data** — this app's own 3000-row bulk-seed dataset (`database/seed_bulk.py`) is a
  standalone CLI script, never run as part of the test suite, so it was never available to
  test against directly. Instead, this test creates 60 real change requests through the
  actual API (a deliberately uneven 15/25/20 high/medium/low priority mix), independently
  counts them in Python, and confirms both the unfiltered total and a priority-filtered count
  match the endpoint exactly.
- **Filters** — the same 60-row scenario also confirms a `priority` filter narrows the result
  to exactly the expected subset, and a nonsense `owner_id` (one that matches no real user)
  returns a clean empty result rather than an error.
- **Verified against real database records** — beyond each phase's own endpoint-level
  checks, this file adds one cross-endpoint consistency check (Workload's own per-owner
  breakdown must agree with Executive Metrics' own total for the same owner) and one
  cross-*endpoint-family* check against a completely different, independently-implemented
  endpoint (`GET /api/change-requests`'s own `search` parameter, scoped to a unique title
  fragment only that test's fixtures use) — two endpoints that read the same underlying rows
  through entirely different code paths must agree on the count.

**Not yet run**: this cloud sandbox has no `pytest`/`pip` access, so every file above was
verified by careful manual tracing against the actual endpoint/schema code (including one
self-caught bug — see 17.7) rather than execution. Run `python -m pytest ../tests` from
`backend/` once these files are on your machine; 368 passed is the expected count.

### 17.7 Known limitations and one self-caught bug (disclosed, not blocking)

- **A test-fixture bug, caught and fixed before final delivery** — the AI-response fixtures
  in `test_module19_phase1/2/3.py` were all initially missing the AI schema's required
  top-level `recommendation` field, which would have made every `/analyze` call in those
  three files actually fail with `422` instead of the `201` they asserted. Caught while
  building Phase 4's own fixture (by re-reading `AIAnalysisResult`'s actual schema) and fixed
  across all three files before you ever saw it — a reminder of why this report says "not yet
  run" above rather than claiming these are confirmed.
- **Several Workflow/Change/Workload metrics will read as near-zero against this app's own
  3000-row bulk-seeded dataset** — `seed_bulk.py` creates only `ChangeRequest` + `Analysis` +
  `ClarificationQuestion` rows, never `Approval`/`ChangeRequestAssignment`/
  `ChangeRequestHistory`/`ChangeRequestVersion` rows. Average approval time, versions-per-CR,
  most-changed-fields, and workload's pending-reviews/approvals will all correctly reflect
  only your real, manually-created and manually-edited change requests — a disclosed,
  expected limitation of that synthetic dataset, not a bug in this module.
- **"Team" in Approval Bottlenecks is `ApprovalType`, not a real team** — this app's schema
  has no team/department concept anywhere; `ApprovalType` (Technical, Security, Engineering
  Manager, and so on) is the closest existing stand-in, the same one the approval matrix in
  `workflow_rules.py` already uses.
- **Risk-over-time is bucketed by each CR's own latest-analysis month, not a full history of
  every risk score a CR ever had** — this app only stores each analysis's own `risk_score`,
  never a separate time-series table; this is the most honest trend the existing data
  actually supports without inventing a new table for it.
- Same permission model as every other read-only reporting endpoint in this app — any
  authenticated user can view analytics (no role restriction yet), matching Modules 15/16's
  own repository/knowledge-base endpoints.

---

## 18. Module 20 — Version-Aware Reports (built this session)

### 18.1 What it adds and why

Module 11 (back near the start of this project) built a 16-section PDF report from a change
request's most recent analysis. It was never wrong about *what* an analysis said — but it had
one real gap: if you edited a change request after analyzing it, the report still generated
immediately. It printed an amber "this analysis may be outdated" note, but the Change Request
fields it showed (title, description, priority, and so on) were always today's live values,
while the analysis alongside them was whatever the last analysis happened to be — possibly run
against an earlier version entirely. Two different versions' data, shown side by side as if
they were one consistent snapshot.

Your spec's section 7 named this directly: "Do not mix Version 3 CR data with Version 4
analysis." Fixing that for good — not just adding another warning banner — is what this module
actually is. The fix has one core piece: `resolve_report_context()`
(`app/services/report_generator.py`) resolves a report to exactly one version before any
rendering happens, using the version snapshots Module 12 already stores. From there:

- **Report header** — every report already showed CR ID, title, CR version, analysis version,
  status, risk, generated date, and generated-by (Module 13 Phase 3 added most of this); this
  module makes the version numbers in that header actually trustworthy rather than a warning
  bolted on top of mismatched data.
- **Version warning** (spec section 3) — asking for the *current* report when the current
  version hasn't been analyzed no longer generates anything. It's a `409` naming the last
  version that *was* analyzed, so the screen can offer "Re-analyze" (reusing the exact
  Re-analyze action that already existed) or "view that version's report instead" — never a
  dead end, never a misleading PDF.
- **Historical reports** (spec sections 3 and 7) — `GET .../report?version=N` builds a report
  for any past version on purpose: the CR fields shown are reconstructed from that version's own
  snapshot (never today's live row), and the analysis shown (if any) is only ever the one that
  ran against that exact version. The PDF itself is stamped "HISTORICAL REPORT — Version N" so
  it's never mistaken for current. A version that was never analyzed at all still gets a report
  — its own CR fields, with every AI-derived section clearly stating "No analysis was performed
  against Version N" rather than being left blank or refused outright.
- **Approval Status** (spec section 4) — required/completed/pending/rejected counts plus a full
  table of every approval with its approver (name only, never an email — the same "don't expose
  unnecessary sensitive information" rule Module 19's Approval Bottlenecks section already
  follows), status, requested/responded timestamps, and comment.
- **Change History** (spec section 5) — every version this change request has ever had, who
  changed it, when, and a summary, with both the CR's actual current version and (on a
  historical report) the version that specific report represents both clearly flagged.
- **Audit** (spec section 6) — created / edited / status changes / approvals / analysis /
  implementation events, filtered to that meaningful subset (not every internal event type this
  app tracks) and, on a historical report, scoped to events at or before that version — a report
  representing an earlier point in time doesn't show events that hadn't happened yet.
- **A pre-existing gap closed in passing**: `HistoryAction.REPORT_GENERATED` has existed in
  `app/models/enums.py` since Module 12 but was never actually recorded anywhere. Downloading a
  report now logs one — the natural place to finally use it, since this module's own new Audit
  section is what would show it.
- **Business Impact / Technical Impact** (spec section 2) — these CR fields (`business_impact`,
  `technical_impact`, captured back in Module 12) existed in the database but were never
  actually printed on the report. They're now their own sections, version-aware like everything
  else.
- **PDF quality** (spec section 8) — a new bordered-table renderer (used for Approval Status,
  Change History, and Audit) replaces ad-hoc text for these list sections, with per-row height
  computed from actual text width so a long comment or detail wraps onto more lines instead of
  overflowing its cell; risk severity is now color-coded (green/amber/orange/red) in the Risk
  section; the cover page, page numbers, and footer from Module 11 are unchanged.

### 18.2 The phases

1. **Version-aware report engine + endpoint** — `resolve_report_context()` and the version-
   scoped `generate_report_pdf()` rewrite; `?version=` on the report endpoint; the 409
   version-mismatch behavior; `GET .../report/versions` for the version picker; the
   `REPORT_GENERATED` audit hook. This phase also absorbed the richer PDF content (Approval
   Status / Change History / Audit / Business Impact / Technical Impact / table rendering /
   risk color-coding) — it touches the same rendering function, so splitting it into a second
   pass would have meant re-reading and re-touching every section twice for no real benefit.
2. **Frontend** — the Analysis Dashboard's report area now shows the exact "Current CR version
   has not been analyzed" warning with Re-analyze and "view that version instead" actions when
   relevant, plus a "report for a specific version" picker listing every version and whether
   each has been analyzed.
3. **Testing** — one test file covering all 6 of your spec's required scenarios end to end.

### 18.3 Files touched

- `backend/app/services/report_generator.py` — `resolve_report_context()`, `ResolvedFields`,
  `ReportContext`, `ReportVersionError`, the rewritten `generate_report_pdf()`, the new
  `table()` renderer, and the Approval Status / Change History / Audit section builders.
- `backend/app/api/change_requests.py` — `download_report` rewritten around
  `resolve_report_context()` and the 409 mismatch response; new `GET .../report/versions`
  endpoint; the `REPORT_GENERATED` history write.
- `backend/app/schemas/change_request.py` — new `ReportableVersionRead` schema.
- `frontend/src/api/client.js` — `ApiError` now carries the backend's raw structured `.detail`
  (not just a flattened message string) so a caller can branch on specific fields like
  `last_analyzed_version`.
- `frontend/src/api/analysis.js` — `downloadReport()` takes an optional version; new
  `listReportableVersions()`.
- `frontend/src/pages/AnalysisDashboardPage.jsx` — the version-mismatch warning and the
  version-picker control.
- `frontend/src/styles/analysis-dashboard.css` — styles for both.
- `tests/test_module20_phase1.py` — 13 new tests (see 18.5).

### 18.4 API changes

- `GET /api/change-requests/{id}/report` — now accepts an optional `?version=N`. Without it,
  returns `409` (body: `{message, cr_version, last_analyzed_version, can_reanalyze}`) instead of
  a report whenever the current version hasn't been analyzed; with it, always returns an
  explicitly historical, clearly-labeled report for that version (`404` if that version number
  doesn't exist for this change request).
- `GET /api/change-requests/{id}/report/versions` (new) — every version, each flagged
  `is_current` / `has_analysis`, for the frontend's version picker.

### 18.5 Testing

`tests/test_module20_phase1.py`, 13 tests, covering your spec's own section 10 test list
directly:

- **Current version** — a report downloads successfully and its text genuinely contains the CR
  code, title, version number, and the real analysis summary (verified by reading the PDF's
  actual text back with `pypdf`, not just checking the file is non-empty).
- **Historical version** — editing a CR after analyzing it, then requesting `?version=1`,
  returns a report stamped "HISTORICAL REPORT - Version 1" containing Version 1's real
  description and Version 1's analysis — and does NOT contain the live Version 2 edit anywhere,
  the direct test of "don't mix Version 3 CR data with Version 4 analysis."
- **Outdated analysis** — both the "edited after analysis" case and the "never analyzed at all"
  case return `409` with the correct `cr_version` / `last_analyzed_version`, instead of a
  report.
- **Approved CR / Rejected CR / CR with pending approvals** — three tests confirming the
  Approval Status section reflects real `Approval` rows: an approved approval shows the
  approver's name and "Approved"; a rejected one shows "Rejected" and the approver's comment; a
  still-pending one shows up in the pending count. A fourth confirms a CR with no approvals at
  all says so plainly rather than showing an empty table.
- Also covered: a version number that doesn't exist returns `404`; the version-mismatch and
  the report endpoints both require authentication; `GET .../report/versions` correctly flags
  which versions have been analyzed; downloading a report logs exactly one `REPORT_GENERATED`
  audit event.

**Not yet run**: this cloud sandbox has no `pip`/PyPI access (confirmed again this session —
neither `fastapi` nor `fpdf2` could be installed here), so none of this module's code could be
executed directly; everything above was verified by careful manual tracing against the actual
model/schema/endpoint code, the same process used for every module in this project's later
half. Run `python -m pytest ../tests` from `backend/` once these files are on your machine —
381 passed is the expected count. This is also the first module where you'll want to actually
open the app: Phase 2 (the frontend) has never been visually confirmed by you yet, since a PDF
and a warning banner are best judged by eye, not just by test count.

### 18.6 Known limitations (disclosed, not blocking)

- **Approvals/history on a historical report are scoped to "at or before that version"** — an
  approval requested against Version 2 won't appear on a Version 1 historical report, even
  though it exists today. This is deliberate (a report representing an earlier point in time
  shouldn't show events that hadn't happened yet at that point), not a data-loss bug — the
  *current* report, and `GET .../approvals` directly, still show everything.
- **No new role restriction on who can generate a report or see its audit/approval detail** —
  this app has never restricted *viewing* a change request by role (only actions like editing
  or approving are permission-gated, all the way back to Module 12), so "an authorized user"
  here means the same thing it already means everywhere else in this app: anyone logged in who
  can already open this change request. The one thing this module does restrict, matching
  Module 19's own precedent, is exposing raw email addresses — approvers and history actors are
  always shown by name only.
- **The word-wrap height used by the new table renderer is an estimate** (based on measured
  text width, the same technique fpdf2 itself uses internally), not fpdf2's own exact
  computation — for the row heights and comment/description lengths a real change request
  produces this holds up fine, but an extremely long single-word string in an approval comment
  is a theoretical edge case where a row's border could sit slightly off from its text. Cosmetic
  only; never a data-correctness issue.

## 19. Module 21 — Administration & Configuration (built this session)

### 19.1 What it adds and why

Everything through Module 20 assumed every account could do everything a normal user can do —
there was no account-level "who's allowed to do what," only per-change-request ownership and
assignment (Module 12). Your spec asked for a genuine admin layer on top of that: user
management, practical roles, an enforced permissions matrix, admin-configurable approval rules,
scoped system settings, and a system-level audit log — without replacing Module 12's
authentication or per-CR permission system, and without turning section 4's approval rules into
a rule engine.

- **User management** (spec section 1) — a new Admin-only `/api/admin/users` (list/create/
  update) reuses the existing `User` model and the existing `UserRead` schema (which already
  excludes the password hash) rather than building a parallel "admin view of a user." An admin
  can view every account, create one directly (skipping self-registration), change its role, and
  activate/deactivate it — never see or export a password.
- **Roles** (spec section 2) — three new account-wide roles (Requester, Security Reviewer,
  Approver) complete your practical list of seven. "Manager" reuses the `product_manager` role
  that already existed in the code (this project's convention is additive-only enums, never
  renaming a wire value), just given a proper display label instead of adding a second,
  confusingly similar role.
- **Permissions** (spec section 3) — a new role x capability matrix (9 capabilities: create/edit/
  status change/assignment/approval/rejection/comments/reports/administration) is checked
  **on the backend**, inline in the 7 real endpoints that perform those actions — not just
  hidden in the UI. It's seeded to match exactly how the app already behaved (everything allowed
  except Administration, which only Admin ever had), so turning this on changes nothing on day
  one; an admin only restricts something by deliberately unchecking a box. Administration itself
  can never be changed through this matrix, in either direction — so an admin can never lock
  every admin out of the admin section by mistake.
- **Approval rules** (spec section 4) — the old hardcoded "risk level -> required approvals" and
  "category keyword -> required approvals" tables become real, admin-editable database rows,
  with the exact same two shapes your spec asked for (risk bucket, or category keyword) — not a
  general rule engine. One thing is deliberately NOT configurable: if the AI itself flags a
  security risk on an analysis, Security approval is always required, regardless of what any
  rule says. That's a safety floor, not a business rule an admin should be able to switch off.
- **System settings** (spec section 5) — scoped honestly rather than exposing everything the
  spec listed at face value. Change request categories are a genuinely editable list. AI
  provider, repository, and knowledge base settings are shown as **read-only** info (never a raw
  API key — only the provider/model name and whether a key is configured) because they come from
  your `.env` file, which this app has never allowed editing through the UI. Priority values and
  the workflow status-transition graph are **not exposed here at all** — both are load-bearing
  across risk scoring, sorting, and the status machine everywhere else in the app, and letting an
  admin edit them at runtime risks silently breaking other modules; that's a deliberate scope
  limit, not an oversight.
- **Audit** (spec section 6) — a new, append-only `SystemAuditLog`, separate from Module 12's
  per-change-request history. It records only admin-level actions (a user created, a role
  changed, an account activated/deactivated, a permission changed, an approval rule added/
  updated/deleted, a system setting changed) — never editable, only ever appended to.
  Change-request-level history is unaffected and unchanged.
  <br>**One thing this module intentionally leaves out of that log**: it only records *what
  changed*, not every admin page view — matching how Module 12's own change-request history
  never logged views either, only actual changes.
- **UI** (spec section 7) — a new Admin section in the left nav ("Settings"), visible only to
  Admin accounts (both the nav item and the page itself check this, so a non-admin can't reach
  it even by typing a URL, since there's no separate URL — this app has no router — and the page
  component checks the signed-in user's role directly).
- **A deactivated account** stops working immediately, not just on its next login: its existing
  session token is refused on its very next request (same experience as a token that expired),
  and a fresh login attempt gets a clear "this account has been deactivated" message — but only
  ever shown *after* the password is verified, so a wrong-password guess against a deactivated
  account can't be used to learn that the account exists and is deactivated.
- **A deactivated user's own change requests are completely unaffected** — still visible in
  listings, still openable, still show their full history — deactivation only stops *that
  person* from doing anything new, never other people from seeing what they already did.

### 19.2 The phases

1. **Roles, accounts, user management** — the three new `UserRole` members, the nullable
   `User.is_active` column, the deactivation checks in login and in every authenticated request.
2. **System-level audit log** — the new `SystemAuditLog` model and its single writer
   (`app/services/admin_audit.py`).
3. **Permissions matrix** — the new `RolePermission` model, `app/services/permissions.py`, and
   wiring `check_capability()` into the 7 real endpoints it gates.
4. **Approval rules** — the new `ApprovalRule` model, threading an optional `rules` parameter
   through the three existing pure functions that compute required approvals, without changing
   behavior for any caller not yet updated to pass rules in.
5. **System settings** — the new `SystemSetting` key/value table for `cr_categories`, plus the
   read-only AI provider/repository/knowledge base info panels.
6. **Frontend Admin UI** — the new Admin page (5 tabs: Users, Permissions, Approval Rules, System
   Settings, Audit Log), and hiding the nav item from non-admins.
7. **Testing** — one new test file covering your spec's own section 8 test list.

### 19.3 Files touched

- `backend/app/models/enums.py` — 3 new `UserRole` members; new `AdminAuditAction`,
  `Capability`, `ApprovalRuleType` enums.
- `backend/app/models/user.py` — new nullable `is_active` column.
- `backend/app/models/system_audit_log.py`, `role_permission.py`, `approval_rule.py`,
  `system_setting.py` (all new) — the 4 new tables this module adds.
- `backend/app/services/workflow_rules.py` — `USER_ROLE_LABELS`; `is_active_user()`; the
  approval-matrix rewrite (`required_approval_types()` now takes an optional `rules` param,
  falling back to the exact old hardcoded behavior when omitted).
- `backend/app/services/analysis_delta.py` — `compare_analyses()` threads the same `rules`
  parameter through to its own `required_approval_types()` calls.
- `backend/app/services/admin_audit.py`, `permissions.py`, `system_settings.py` (all new) — the
  audit-log writer, the permissions matrix logic, and the system-settings service.
- `backend/app/api/deps.py` — `get_current_user` now checks `is_active_user`; new
  `require_admin` and `check_capability` helpers.
- `backend/app/api/auth.py` — `login()` now checks `is_active_user` after password verification.
- `backend/app/schemas/user.py` — `UserRead` gained `is_active`.
- `backend/app/schemas/admin.py`, `backend/app/api/admin.py` (both new) — every request/response
  shape and every endpoint for the admin section.
- `backend/app/main.py` — registers the new admin router.
- `backend/app/database/init_db.py` — seeds default permissions and default approval rules on
  startup (idempotent — never overwrites an admin's later edits, never resurrects a deleted rule).
- `backend/app/api/change_requests.py` — `check_capability()` calls added to the 7 endpoints
  section 3 names; a small `_load_approval_rules()` helper feeds the database's current rules
  into every place that already computed required approvals.
- `frontend/src/api/admin.js` (new) — thin wrappers for every admin endpoint.
- `frontend/src/pages/AdminPage.jsx` (new) — the 5-tab Admin page.
- `frontend/src/styles/admin.css` (new) — its styling, matching this app's existing look.
- `frontend/src/components/AppHeader.jsx` — hides the "Settings" nav item from non-admins.
- `frontend/src/pages/AuthenticatedHome.jsx` — renders the Admin page for that nav item.
- `tests/test_module21_admin.py` (new) — 14 new tests (see 19.5).

### 19.4 API changes

All new, all under `/api/admin`, all requiring an authenticated, active Admin account:

- `GET /api/admin/users`, `POST /api/admin/users`, `PATCH /api/admin/users/{id}`
- `GET /api/admin/audit-log` (paginated, optional actor/action filters)
- `GET /api/admin/permissions`, `PUT /api/admin/permissions` (bulk update; rejects any attempt to
  touch Administration)
- `GET /api/admin/approval-rules`, `POST /api/admin/approval-rules`,
  `PATCH /api/admin/approval-rules/{id}`, `DELETE /api/admin/approval-rules/{id}`
- `GET /api/admin/system-settings`, `PUT /api/admin/system-settings/cr-categories`

No existing endpoint's URL or response shape changed; 7 existing endpoints (create/edit a change
request, change its status, assign someone, respond to an approval, comment, download a report)
now additionally 403 if the caller's role lacks the matching capability.

### 19.5 Testing

`tests/test_module21_admin.py`, 14 tests, covering your spec's own section 8 test list directly:

- **Role permissions** — turning a capability off for one role (Requester) actually blocks that
  action (creating a change request) for that role, leaves every other role unaffected, and
  turning it back on restores it. A separate test confirms Admin can never be blocked by the
  matrix, even if someone tries to turn a capability off for Admin too.
- **Admin access / unauthorized API calls** — every one of the 12 admin endpoints returns `403`
  for a signed-in non-admin, and `401` (not `403`) for a request with no token at all; a
  dedicated test confirms Administration itself can never be edited through the permissions
  endpoint, even by an admin.
- **Approval rules** — creating a rule through the real `POST /api/admin/approval-rules`
  endpoint, then re-loading it from the database and passing it into the real
  `required_approval_types()` function, actually changes which approvals are required for a
  matching change request; disabling the rule (through the real `PATCH` endpoint) takes it back
  out. Also covered: creating a rule with an invalid risk bucket or an unknown approval type is
  rejected with `422`.
- **User deactivation** — a deactivated account's existing token stops working on its very next
  request, a fresh login attempt gets `403`, and reactivating restores both; an admin can't
  deactivate or demote their own account; a wrong password against a deactivated account still
  gets the same generic `401` an active account would (never a hint that it's deactivated).
- **Existing CR access** — after its creator is deactivated, a change request they created is
  still fully visible to another user and to an admin: its detail, its history, and its listing
  entry are all unaffected.
- Also covered: the "Manager" role round-trips correctly as `product_manager`; the system
  settings endpoint never exposes a raw API key or anything containing the word "secret," and
  `cr_categories` can be added to and rejects an empty list.

Verified before delivery by careful manual tracing against the actual model/schema/service/
endpoint code (this sandbox has no `pip`/PyPI access, so nothing could be executed directly here)
and cross-checked against this project's own established test conventions (registering real
users via `/auth/register`, then promoting/deactivating them directly through the database the
same way `test_workflow_foundation.py` already does, rather than inventing a new pattern).
**CONFIRMED**: his own pytest run shows 395 passed (381 + 14), all green.

### 19.6 Known limitations (disclosed, not blocking)

- **`cr_categories` is editable but not yet wired into Dashboard's or Analytics' actual grouping
  logic.** Those two pages each already have their own separate, already-tested, intentionally
  duplicated category/alias list (their own code comments say so explicitly — "so this module
  can't accidentally change dashboard behavior"). Properly synchronizing one editable list into
  both of those already-shipped modules safely was judged a bigger, riskier change than this
  module should take on in one pass. Today, editing this list changes only what the admin section
  itself shows back to you — not how the Dashboard or Analytics group existing change requests.
- **Priority values and the workflow status-transition graph are not configurable anywhere in
  this module**, on purpose — see 19.1 above. If you want either made admin-editable later,
  that's a real, separate module (both would need careful handling of every place in the app that
  already assumes today's fixed set).
- **No new restriction on who can *view* a change request** — same as Module 20's own disclosed
  limitation: this app has never restricted viewing by role, only actions. This module adds
  enforcement for the 9 *actions* your spec named; it doesn't add a "who can see this CR" layer
  that didn't exist before.

## 20. Module 22 — Final Integration, Security & Quality (built this session)

### 20.1 What it adds and why

Your spec was explicit that this module is not about new features — it's about making the
21 modules already built actually reliable together. So the work here was: research first
(three independent passes over the whole codebase looking for real, file-and-line-specific
problems — not a generic best-practices checklist), fix what was genuinely broken or genuinely
risky, write one real end-to-end test that walks the entire pipeline your spec listed in one
pass, and disclose the couple of things deliberately left alone and why.

- **Approval bypass gate (the one real workflow-integrity bug found)** — before this module,
  nothing stopped a change request from being moved straight to **Approved** while an approval
  it had actually requested was still sitting **Pending**. Nobody had exploited this — it just
  wasn't checked. `PUT /{id}/status` now checks for any Pending approval on the change request
  before allowing a transition to Approved, and refuses with `409` if one exists. It only blocks
  on a genuinely pending approval — an old Rejected or Changes-Requested approval doesn't block
  anything (the recovery path is requesting a fresh one, same as before this fix).
- **"May be outdated" now shown on AI-recommended approvals** — Module 13 already warns you on
  the main change request view when its analysis is stale (the CR was edited since). The
  `GET /{id}/approvals/recommended` endpoint had no equivalent — editing a CR after analyzing it
  left this endpoint silently recommending approvals off stale data with no warning at all. It
  now carries the same `is_outdated` flag per recommendation, and both places in the UI that show
  AI-recommended approvals (the Analysis Dashboard and the change request detail page) surface a
  small amber "May be outdated" badge when it's true. Purely additive — nothing that already read
  this endpoint's response breaks.
- **Startup hardening against your own dev secret leaking into a real deployment** — this
  project's `backend/.env.example` used to ship with a real, working `SECRET_KEY` value (the same
  one every clone of this repo would sign login tokens with, if nobody replaced it). The example
  file's secret is now blank with instructions to generate your own; and if the app is ever run
  with `APP_ENV` set to anything other than `development` while the placeholder secret is still
  in use, it now refuses to start with a clear error instead of silently signing every token with
  a value visible in this project's own source. This never affects your local hackathon use,
  since your `APP_ENV` defaults to `development`.
- **A crashed request no longer shows a raw error page** — any unhandled exception anywhere in
  the API now returns a clean `500` with a generic message ("Something went wrong on our end.")
  instead of whatever FastAPI's default error page would otherwise show, and the real error (with
  full detail) is still logged server-side for you to see in the backend's own terminal window.
- **Two rare double-submit races closed** — registering an account and an admin creating a user
  both now return a clean `409 Conflict` ("an account with this email already exists") instead of
  a raw database error, if the exact same email is submitted twice at almost the same instant.
  Unlikely to ever happen by accident in normal use; closed because it's cheap to close correctly.
- **A failed request no longer leaves a half-written database change behind** — the database
  session used by every request now explicitly rolls back if anything goes wrong partway through,
  instead of potentially committing a partial write.
- **One comprehensive end-to-end test** (`tests/test_module22_e2e.py`) walks the entire chain
  your spec named in section 1, start to finish, against the real app (no mocking except the AI
  provider and embedding provider, which cost real money/time to call for real): register, log
  in, create a CR, upload and embed a real knowledge-base document, scan this project's own
  repository, run AI analysis, edit the CR, confirm the analysis is now flagged outdated
  everywhere it should be, re-analyze, review a requirement and a security finding, assign a
  reviewer, walk every status transition including the approval gate (proving the bypass fix
  actually blocks it, then actually unblocks it once the real approver responds), through
  implementation and closure, and finally downloads the PDF report — with an assertion at nearly
  every step that the artifact produced (analysis, evidence, repository finding, requirement,
  history event) is tagged with the *correct* change-request version, per your spec's section 2.

### 20.2 What I deliberately did not change, and why

- **Knowledge-base document permissions** — your spec's section 3 asks about "knowledge base
  permissions" generally. Today, any authenticated user can archive or reprocess any knowledge
  document, not just its uploader or an admin. I traced this and confirmed Module 16's own test
  suite (`test_module16_phase1.py`, `test_module16_phase7_security.py`) already exercises and
  relies on a non-admin engineer being able to do this — tightening it now would break existing,
  intentional behavior rather than fix a bug, and your spec didn't ask for a knowledge-base
  ownership model. Left as a disclosed gap rather than guessed at.
- **Editing a requirement/test case/task from a stale (outdated) analysis** — in principle,
  nothing at the database level stops writing a review decision against an old analysis version.
  In practice, I traced every path the real UI uses to reach these review actions and confirmed
  every ID it can ever offer you comes from whichever analysis is *currently displayed* — there
  is no button or screen in this app that can hand you an ID belonging to a stale analysis to act
  on. This is a real, low-severity gap if this API were called directly (outside the actual UI),
  but not one the app itself can ever walk you into. Documented rather than papered over with
  speculative code for a path nothing can reach.

### 20.3 Files touched

- `backend/app/core/config.py` — the placeholder-secret-key guard.
- `backend/.env.example` — the real secret removed; instructions to generate your own.
- `backend/app/main.py` — the global exception handler.
- `backend/app/database/session.py` — rollback-on-exception in `get_db()`.
- `backend/app/api/auth.py`, `admin.py` — the two double-submit races closed.
- `backend/app/api/change_requests.py` — the approval bypass gate; the `is_outdated` flag on
  `GET /{id}/approvals/recommended`.
- `backend/app/schemas/approval.py` — `RecommendedApprovalType.is_outdated`.
- `frontend/src/pages/AnalysisDashboardPage.jsx`, `frontend/src/components/ChangeRequestDetail.jsx`
  — the "May be outdated" badge on AI-recommended approvals.
- `tests/test_module22_e2e.py` (new) — the full end-to-end test.

### 20.4 Testing

`tests/test_module22_e2e.py`, one comprehensive test function walking the entire pipeline
described in 20.1, plus the existing 395 tests from every prior module — **396 tests, all
passing**, confirmed by your own `pytest` run. Two real bugs turned up and were fixed while
building this test, both in the test itself rather than the app: a wrong response-field name
(the edit endpoint's response shape doesn't put `current_version` at the top level), and a fake
AI-embedding vector that was too simple — a single 0/1 number — which meant that, only once this
suite has accumulated enough prior test data, a leftover document from a completely unrelated
earlier test could tie for "most relevant" against the document this test had just uploaded.
Neither was a defect in the app; both are exactly the kind of thing a genuinely comprehensive,
whole-history test run is supposed to surface.

### 20.5 Final result

- **Tests run**: 396 (395 from Modules 1–21, plus 1 new comprehensive end-to-end test covering
  this module's own spec).
- **Issues found**: 1 real workflow-integrity gap (approval bypass), 1 missing outdated-data
  warning (recommended approvals), 1 real committed-secret / startup-hardening gap, 1 raw-error
  page on unhandled exceptions, 2 narrow double-submit races, 1 partial-write-on-failure gap, plus
  2 bugs in my own new test (caught and fixed before delivery, never shipped to you).
- **Issues fixed**: all of the above except the 2 deliberately-disclosed, low-severity items in
  20.2 (knowledge-base permissions scope; editing against a stale analysis via direct API call) —
  both traced to confirm they're either unreachable through the real UI or would break existing,
  intentional behavior if "fixed."
- **Remaining limitations**: the two items in 20.2, plus everything already disclosed in each
  prior module's own "Known limitations" section (10, 19.6, and the equivalent in 11–18)  — this
  module didn't re-open or re-litigate any of those, only reviewed for regressions.
- **Final startup commands** (unchanged from before this module):

  ```
  # Terminal 1
  cd backend
  python -m uvicorn app.main:app --reload

  # Terminal 2
  cd frontend
  npm run dev
  ```

  Backend: http://localhost:8000 · Frontend: http://localhost:5173
