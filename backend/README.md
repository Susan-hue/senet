# Senet Backend

Multi-tenant academic operations platform for Nigerian universities.
Sprint 1 foundation: tenancy + auth + central tenant scoping.

## What's here so far
- `tenancy/` — Institution (tenant) model with per-university config, and the
  central scoping layer (`scoping.py`) + middleware that make cross-tenant access
  impossible by construction.
- `accounts/` — custom User model with role-and-scope RBAC (email login, UUID PK).
- Passing tests proving cross-tenant isolation (`tenancy/tests.py`).

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

Uses SQLite locally. Set `DATABASE_URL` to your Supabase Postgres URL for staging/prod.

## The one rule that matters most
Every tenant-owned model inherits from `tenancy.scoping.TenantScopedModel`.
Use `.objects` (auto-scoped) everywhere. `.all_objects` (unscoped) is for reviewed
cross-tenant jobs only. A query that bypasses scoping is a defect.

## Next (Sprint 2)
Academic structure (faculty/department/programme/course), enrolment, bulk CSV import.
