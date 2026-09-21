# Demo Guide

A step-by-step script for presenting the AI Change Request Analyzer, built around one flagship
change request that walks through the full system end to end. See `README.md` for how to start
the app and load this demo data, and `ARCHITECTURE.md` for how everything under the hood fits
together.

## Before you present

1. Start both servers (see `README.md`'s **Startup commands**) and confirm both are running:
   backend at http://localhost:8000/health, frontend at http://localhost:5173.
2. Load the demo data once, from `backend/` with the virtual environment active:
   ```powershell
   python -m app.database.seed_demo
   ```
   This is safe to re-run — if `admin@alight.com` already exists it prints a message and exits
   without creating duplicates. It prints the flagship change request's real ID (it will vary
   run to run); note it down, since the rest of this guide just calls it "the flagship CR."
3. Confirm your configured AI provider is actually reachable (see README's **Environment
   variables**) — the one live AI call in this script (step 4 and step 12, "Analyze"/"Re-analyze")
   needs it. If you're using a paid provider, do one throwaway analysis on any other seeded CR
   beforehand to confirm it responds, so the flagship demo isn't the first time you're finding out.
4. **Rehearse the versioning step (step 12–14) once before presenting**, and read the callout box
   there — it depends on a real, live AI call and its outcome isn't 100% guaranteed on every run.

## Demo accounts

Seeded by `seed_demo.py`, all on the fictional `alight.com` domain, all with password
`AlightDemo123!`:

| Name | Email | Role | Used for |
|---|---|---|---|
| Ava Chen | admin@alight.com | Admin | Admin/permissions screen |
| Jordan Blake | manager@alight.com | Manager | Approving the flagship CR |
| Liam Carter | engineer@alight.com | Engineer | Creating & driving the flagship CR |
| Priya Nair | security@alight.com | Security Reviewer | Security approval |
| Sofia Reyes | requester@alight.com | Requester | Mentioned in a comment on a supporting CR |

These are local-only demo credentials seeded into your own SQLite database — never real
credentials, and never used anywhere outside this local demo.

## The flagship demo change request

**"Add OTP-based authentication for customers"** — OTP sent to the customer's registered mobile
number, expires after a defined period, a maximum retry count, secure OTP storage, rate limiting,
and audit logging. It's seeded already *created* but deliberately left **unanalyzed** (status
Pending Analysis) so the AI Analysis step in the walkthrough below is a real, live call, not a
replay of something already computed.

Six other change requests are also seeded, at different statuses, priorities, and risk levels
(one Approved, one with Changes Requested, one Closed with a full history, one plain Draft, one
In Progress), with real comments, @mentions, and version history, purely so the Change Requests
list, Analytics, and My Work pages don't look empty if you click around beyond the scripted path.
They're not part of the scripted walkthrough.

## Step-by-step walkthrough

**1. Login.** Go to http://localhost:5173, sign in as `engineer@alight.com` /
`AlightDemo123!`.

**2. Dashboard.** Lands on the Dashboard — point out the summary counts and the recent activity;
this is pulling real aggregate numbers from the seeded data, not placeholders.

**3. Open the flagship CR.** Click **Change Requests** in the left nav, find "Add OTP-based
authentication for customers," and open it. Its status is **Pending Analysis** and it has no
analysis yet — call this out explicitly, since it's what makes the next step a genuinely live
demo rather than a replay.

**4. AI Analysis.** Click **Analyze Change**. This is a real call to your configured AI provider
and can take up to about a minute. While it runs, this is a good moment to explain: the AI reads
the plain-language description the way a senior engineer would, and everything it returns is
tagged with its own certainty and confidence — nothing here is scripted or canned.

**5. Show requirements.** Once analysis completes, you land on the Analysis Dashboard. The
**Requirements** tab shows the concrete, extracted requirements (OTP generation, expiry window,
retry limits, storage, rate limiting, audit logging) — each tagged Confirmed or Needs
Clarification.

**6. Show risk.** The **Risks** tab shows identified risks with severity and the overall risk
score shown in the header. Given this CR touches authentication, expect Security-related risks to
dominate.

**7. Show security.** The **Security** tab runs the structured 9-category security review
(Authentication, Authorization, Data Protection, Secrets, API Security, Rate Limiting, Privacy,
Audit Logging, Compliance) — point out that for an OTP feature, several of these categories should
come back with real findings, not just a generic pass.

**8. Show affected components / affected files.** The **Impact** tab shows the seven fixed impact
lenses; the **Repository** tab shows Repository Intelligence's real scan of this actual codebase —
every file listed there genuinely exists in this project, matched with an honest, hedged
confidence score, never an invented path.

**9. Show dependencies.** Still on the Impact/Repository area — any cross-component dependencies
the AI identified.

**10. Show effort and test cases, then the implementation plan.** The **Complexity & Effort** tab
shows the estimate; **Test Cases** shows generated test cases; **Implementation Plan** shows the
step-by-step plan the AI produced. This is the point to make the "more than summarizing text"
argument explicit: nothing before this tab was prose — it's structured, actionable engineering
output.

**11. Assign users.** Back on the change request's detail page (use the breadcrumb or **Change
Requests** to get back there), scroll to **Team & Assignments**, and assign Liam Carter as
Technical Lead and Priya Nair as Security Reviewer.

**12. Request approval.** In the **Approvals** section, request a **Security** approval from Priya
Nair (`security@alight.com`) — note the AI's own recommended approval type(s) shown just above the
list, and that the app never requests one on your behalf; a person always chooses.

**13. Approver receives notification.** Log out, log in as `security@alight.com` /
`AlightDemo123!`. Click the notification bell (top of the left sidebar) — the new approval request
is there. Click it to jump straight to the change request.

**14. Request changes.** In the Approvals section, click **Respond**, choose **Changes
Requested**, and add a comment (e.g. "Please specify the OTP length and hashing approach for
stored codes"), then **Submit**.

> **Heads up — this does not change the CR's status by itself.** Requesting changes on an
> approval and the change request's own workflow status are deliberately separate things in this
> app (see `ARCHITECTURE.md`'s **Approvals** section) — an approval response records a decision on
> that specific approval, but nothing forces the CR itself out of its current status
> automatically. After this step, go to **Workflow Status** on the CR and manually move it to
> **Changes Requested** yourself before presenting the next step, so the CR's own status reflects
> what just happened.

**15. Edit the CR — version increases.** Log back in as `engineer@alight.com`. Open the flagship
CR, click **Edit**, and strengthen the description — for example, add a line specifying "OTP codes
must be hashed at rest (never stored in plaintext) and rate-limited to 5 attempts per 15 minutes
per account." Save. You'll land on a "Here's what changed" summary; go back to the CR and point
out the version badge next to the title has incremented (v1 → v2).

**16. Audit history records the change.** Open the **Versions & Activity** tab — the field change
you just made is recorded there as its own timestamped entry, alongside every other event on this
CR (created, analyzed, assigned, approval requested/responded) — this is the same append-only log
the PDF report's Audit section reads from.

**17. AI becomes outdated.** Back on the Details tab, an amber **"AI analysis outdated"** banner
now appears at the top, with its own **Re-analyze** button — because the analysis you saw in steps
5–10 was computed against v1, and the CR is now v2.

**18. Re-analyze — risk changes, new approval requirement.** Click **Re-analyze** on that banner
(or from the Analysis Dashboard). This is a second real, live AI call.

> **Heads up — this step is genuinely live, not scripted.** The risk score is computed fresh by
> the AI on every analysis with no deterministic override, so re-analyzing a CR you've made more
> specific and more security-conscious *usually* nudges the risk score and can surface a new
> recommended approval type — but it is a live model call, not a guaranteed script. **Rehearse
> this exact edit once before presenting.** If the score doesn't move on the day, the honest
> fallback narration is: "The AI re-scored this from scratch against the new version — sometimes a
> clarifying edit lowers perceived risk instead of raising it, precisely because it removes
> ambiguity. Either direction is genuine, live model output, not a canned demo response." Either
> outcome supports the same point: the analysis is real and version-aware, not a replay.

**19. Approve.** Assuming the Security approval was updated (or request a fresh one against the
new analysis if you'd like a clean Pending → Approved beat), log in as `security@alight.com`,
respond **Approved** this time.

**20. Implementation → Close.** Back as `engineer@alight.com`, use **Workflow Status** to walk the
CR forward — Approved → Implementation Planned → In Progress → Implemented → Validated → Closed —
narrating that `workflow_rules.can_transition()` is the single gate on every one of these moves,
so an illegal jump (e.g. Draft straight to Closed) simply isn't offered as an option in the
dropdown.

**21. Generate final report.** From the Analysis Dashboard, click **Download Report**. The
generated PDF includes the CR's current status, the full analysis, and the complete audit history
— call out that this is assembled entirely from already-persisted data (no AI call), and that if
the CR is ever edited after its last analysis, this same report clearly labels itself as
reflecting an outdated analysis rather than silently mixing two versions together.

## If the AI is unavailable

If your configured AI provider is down, misconfigured, or times out, **Analyze Change** /
**Re-analyze** will fail with a clear, specific error message (e.g. a timeout or a configuration
error) and nothing else happens — no canned response is substituted, and no analysis is written to
the database. There is no separate "Demo Mode" in this app; the existing failure handling *is*
the fallback, and it's honest about failing rather than faking success. If this happens during a
live presentation, the honest narration is: "This is the AI failing safely, exactly as it would in
production — it's telling you it couldn't get a reliable answer rather than making one up." Every
other step in this walkthrough (workflow, approvals, versioning, audit, reporting) works
independently of the AI and can carry the rest of the demo.

## Where "Repository" and "Reports" actually live

Two nav items from earlier builds were removed rather than kept as dead links: **Repository**
Intelligence is a tab inside the Analysis Dashboard (step 8 above), and the **report** is
generated from the **Download Report** button on that same page (step 21) — both are real,
working features, just reached from inside a change request rather than as standalone top-level
pages.

## Closing line

*"Turn ambiguous change requests into engineering decisions."* The point of this whole
walkthrough is that the system does more than summarize a paragraph of text back to you — it
extracts real requirements, scores real risk, runs a real security review against a fixed
framework, matches against this project's actual source files, estimates effort, writes test
cases and an implementation plan, and keeps every one of those artifacts honestly tied to the
exact version of the change request they were computed against — while every decision that
actually matters (who approves, whether to proceed, what "done" means) stays with a person.
