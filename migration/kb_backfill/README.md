# kb_backfill

One-shot migration tool: reads the `nbx_projects` / `nbx_units` Mongo mirror and
backfills `tenant_data.projects` / `tenant_data.units` on Postgres for tenant
**noble**. Standalone — does not import `noble_agent`.

## Install

```bash
pip install -r migration/kb_backfill/requirements.txt
```

## Run

From the repo root (`PYTHONPATH=migration` puts the `kb_backfill` package on
the path; alternatively `pip install -e migration` once a `setup.py`/`pyproject`
is added — not required today):

```bash
# dry run — reads Mongo, transforms, prints stats, writes nothing to Postgres
PYTHONPATH=migration python -m kb_backfill --dry-run

# real run — upserts projects + replaces units, one transaction per project
PYTHONPATH=migration python -m kb_backfill
```

Flags: `--mongo-uri` / `--mongo-db` / `--pg-dsn` / `--tenant` (default `noble`) /
`--dry-run` / `--limit N` (cap the number of projects processed).

## Env vars

Defaults are read from the repo-root `.env` (via `python-dotenv`) when a flag
is omitted:

- `MONGODB_URI` — Mongo connection string.
- `MONGODB_DATABASE` — Mongo database name (default `noble_agent`).
- `POSTGRES_ADMIN_DSN` — Postgres DSN with write access (RLS-bypassing
  admin/superuser role — the sink writes `tenant_id` explicitly).

## Contract

- Migrates **projects + units only**, scoped to tenant `noble`.
- Idempotent: projects are upserted by `(tenant_id, project_code)`; a
  project's units are fully replaced (delete-then-insert) each run, since
  the units table has no natural unique key.
- Projects with an empty/blank `projectCode` are skipped and counted in
  `projects_skipped_no_code`.
- Upsert-only: the tool never deletes a project (or its units) that exists in
  Postgres but was removed from `nbx_projects` upstream. That's fine for a
  one-shot backfill into empty tables; a reconcile-delete pass would be needed
  if this tool were ever reused as an ongoing sync.
