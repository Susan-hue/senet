# Senet Backend

Multi-tenant academic operations platform for Nigerian universities.
Built through Sprint 6: tenancy and auth, academic structure, assessments,
the results approval pipeline, the grading engine, exports, the NUC auditor
vault, and the CBT exam engine.

## Apps

- `tenancy/` — Institution (tenant) model carrying per-university config
  (grade scale, CA/exam weights, pass mark, carryover method, classification
  bands, retention), plus the central scoping layer (`scoping.py`) and
  middleware that make cross-tenant access impossible by construction.
- `accounts/` — custom User model with role-and-scope RBAC (email login, UUID
  PK), academic structure (faculty → department → programme → course),
  sessions/semesters, enrolment, lecturer-to-course assignment, and bulk
  CSV/XLSX import run as a background job.
- `assessments/` — Continuous Assessment items, student submissions, lecturer
  grading, and weighted aggregation of a student's CA for a course term. The
  CA that enters the results pipeline is aggregated from real graded work
  rather than a retyped number.
- `results/` — the approval pipeline and the system's record of truth.
- `grading/` — the GPA/CGPA engine and academic standing.
- `auditor/` — the NUC Auditor Vault: temporary, revocable, read-only access.
- `cbt/` — the computer-based test engine.
- `notifications/` — multi-channel messaging and the SMS/USSD result check.

## Results pipeline (`results/`)

- **Five-state approval chain**: draft → submitted to HOD → approved by HOD →
  approved by Dean → ratified by Senate, plus a `returned` state with a
  mandatory reason. Every legal move is enumerated in one rule table
  (`services.TRANSITIONS`) with its required role and scope check; anything
  absent is rejected, so states cannot be skipped and a ratified result has no
  exit. Transitions read the row-locked current state, so a stale client
  cannot double-apply or skip a step.
- **Append-only history**: score rows are never overwritten after submission.
  Corrections arrive as new rows that supersede the old ones via an
  `is_current` flip; the replaced row keeps its values forever.
- **DB-level immutability triggers**: PostgreSQL triggers
  (`migrations/0004`) enforce score immutability and audit-log append-only at
  the database, below the ORM, so no code path or manual `UPDATE` can rewrite
  history. The triggers are Postgres DDL; on SQLite the migration is a no-op
  and the model-level guards still apply.
- **Amendments**: a correction to a student's score on an already-ratified
  sheet runs its own HOD → Dean → Senate chain, then supersedes the original
  row. Amendment transitions are labelled in the audit trail with their own
  action.
- **Transactional audit log**: every score change and state transition is
  written inside the same transaction as the change, so both commit or
  neither does.
- **External examiner reports**: the NUC-required record that an examiner
  audited a programme's questions/scripts for a session + semester, captured
  at faculty/Dean level.
- **Anomaly statistics**: failure rate, grade distribution, class average and
  flags for an unusually high failure rate or an abnormally high share of top
  grades — the numbers a Departmental Board vets a submitted sheet on. Purely
  informational; they never block a transition.

## Grading engine (`grading/`)

Quality-points GPA/CGPA with all rules read from institution config.
Everything is `Decimal`, rounding is explicit (2 dp, half-up), and only
results in the institution's configured source state (senate-ratified by
default) count. Supports both carryover CGPA methods (all attempts vs best
attempt only), outstanding-carryover listing, degree classification with a
Senate-review borderline flag, and academic standing
(good / probation / withdrawal).

## Exports (`results/exports.py`)

- **OGR** — the Official Grade Report as a PDF, encrypted with a randomly
  generated owner password.
- **Broadsheet** — the full class sheet as an `.xlsx` workbook.

Small classes render inline in the request; classes above
`EXPORT_ASYNC_THRESHOLD` are generated on a Celery worker and stored on an
`ExportJob` for download. Export generation is read-only with respect to the
result.

## NUC Auditor Vault (`auditor/`)

A school admin mints a token scoped to specific programmes and/or sessions
with an expiry; an external NUC auditor presents it on the read-only auditor
endpoints. Only the token hash is stored, the raw token is shown once, and
tokens are revocable. The auditor is not a Django user — authentication
resolves to a role-less principal, so no role-gated write endpoint will ever
accept it, and the tenant comes from the token rather than a logged-in user.
Every access is appended to an access log.

## CBT engine (`cbt/`)

- **Question banks and exams** — banks of MCQ/true-false/short-answer
  questions; an exam draws `num_questions` per student at start time, with
  optional question and option shuffling.
- **Attempts** — one attempt per (exam, student). The drawn paper is frozen on
  the attempt, so a reload replays exactly the same paper in the same order.
  Timing is server-side; the client clock is never consulted.
- **Disconnection resilience** — answers save individually or in batches, a
  disconnected student resumes the same paper against the original deadline,
  and a Celery beat task sweeps attempts past their deadline and auto-submits
  them. The finalizer is idempotent and row-locked, so overlapping runs and
  concurrent auto-submits are safe.
- **Proctoring** — append-only lockdown events (tab switch, focus loss,
  fullscreen exit, clipboard, heartbeat) and webcam snapshots/clips stored in
  the configured media backend with a retention window stamped from the
  institution's `webcam_retention_days`.
- **Cheating flags are review-only** — signals crossing configured thresholds
  raise a flag for human review and notify the lecturers and exam officer. A
  flag never changes a score, a grade or an attempt's status. A reviewer
  dismisses it as a false positive or escalates it to the HOD.
- **AI question generation** — draft questions from a lecturer's own notes via
  Grok, behind a swappable provider interface. Only the lecturer's notes are
  ever sent — no student data. Output is a draft returned to the lecturer for
  review; it is never written into a bank automatically, and a provider
  outage never breaks exam creation.
- **CBT as a CA item** — a graded CBT can be linked to a Continuous Assessment
  item. Attempt scores are scaled onto the item's mark scale and feed the
  existing weighted CA aggregation, so a CBT counts toward the result like any
  other assessment.

## Notifications (`notifications/`)

- **Channels** — email over the existing Resend path, SMS and WhatsApp over
  Termii, all behind one provider interface. Which provider serves a channel is
  a settings value; every credential comes from the environment. With no Termii
  key configured, sending falls back to a console provider so local runs and CI
  never reach the network.
- **Triggers** — a result returned to its lecturer, results ratified by Senate,
  a CBT scheduled, a CBT opening (a beat sweep), and integrity flags raised or
  escalated. The flag notifications used to be sent ad hoc from `cbt/`; they now
  run through here with everything else.
- **Always asynchronous** — a trigger writes log rows and hands them to Celery
  on transaction commit. No request ever waits on a provider, and a rolled-back
  transition sends nothing.
- **Append-only log** — one row per recipient per channel, recording what was
  sent, to whom, and whether it was queued, sent or failed. Content is frozen at
  creation; only delivery state changes, and rows are never deleted. Events that
  a periodic sweep may re-observe carry a dedupe key, so a repeated run queues
  nothing twice.
- **Graceful failure** — a provider outage is recorded on the row and retried
  with exponential backoff; when the retries run out the row settles on
  `failed`. A failing provider cannot crash a worker or a triggering request.

### SMS/USSD result check

A student with no data can text or dial for their GPA. Three things gate it:

1. The **sender's number** identifies the student, through a verified
   registration they created in the portal and confirmed with a one-time code
   texted to that SIM. A matric number is never used to look anyone up.
2. The **matric number** must match the student the binding already resolved.
3. The **PIN**, set in the portal and stored only as a hash.

Only sheets **ratified by Senate** are ever read, with that state pinned in code
rather than taken from `institution.gpa_source_status` — a tenant cannot
misconfigure its way into publishing an unapproved result over SMS. Every
failure returns one identical message, so the channel is not an oracle for
guessing a matric or a PIN; repeated failures lock the registration, and each
number is rate-limited. Inbound webhooks are authenticated by HMAC signature
over the raw body and fail closed when no secret is configured. Lookups are
cached briefly, because results day is one spike of identical queries.

## Run locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # or use the included .env for local dev
python manage.py migrate
python manage.py test
python manage.py createsuperuser
python manage.py runserver
```

Uses SQLite locally. Set `DATABASE_URL` to your Supabase Postgres URL for
staging/prod. Background work (imports, exports, CBT finalization, AI
generation) runs on Celery against Redis; `CELERY_TASK_ALWAYS_EAGER` defaults
to on in DEBUG, so a local run needs no worker.

All third-party keys (Resend, Grok, Supabase, Redis) come from the
environment. None are ever committed.

## The one rule that matters most

Every tenant-owned model inherits from `tenancy.scoping.TenantScopedModel`.
Use `.objects` (auto-scoped) everywhere. `.all_objects` (unscoped) is for
reviewed cross-tenant jobs only. A query that bypasses scoping is a defect.

## Remaining

- **Sprint 7** — the analytics dashboard and security hardening. Notifications
  and the SMS/USSD result check are built.
- **Sprint 8** — load testing and the pilot deployment.
- **Frontend** — the CBT interface (exam authoring, question banks, the
  student exam runner, proctoring review) and the approval dashboards for
  HOD/Dean/Senate are not built yet. Sprint 6 shipped backend only.
