---
name: db-schema-change
description: Enforce the shipping discipline for the Ahmed Poly Bags / Ibrahim Traders trade ERP whenever a change touches the DB schema. Read this BEFORE modifying models.py, adding/removing/renaming columns, adding tables, or shipping a new zip. The app runs on Ibrahim's Mac AND on shared user machines (currently his cousin's Windows PC via Ahmed-Poly-Bags-app.zip). Shared users have their own wealth_tracker.db with real business data — a missed migration means their next update crashes on "no such column".
---

# Schema-change discipline for the Trade ERP

There are (at least) two live installs of this codebase running against separate databases:

1. **Ibrahim's Mac** — `wealth_tracker.db` in the project root, contains real business data.
2. **The cousin's Windows PC** — extracted from `~/Desktop/Ahmed-Poly-Bags-app.zip`, also has its own real data.

Whenever `start.bat` (or any equivalent update flow) runs on a shared user's machine, code and DB must match, or the app crashes on first request.

## When this skill fires

Read this before ANY of:

- Editing `models.py` (adding/removing/renaming a class, field, enum value, index, or FK).
- Editing anything under `alembic/versions/` (someone has already started one — verify it's complete).
- Editing `database.py` (engine or SQLModel setup changes).
- Re-zipping `Ahmed-Poly-Bags-app.zip` after any of the above.
- Anything the user asks about "how do I ship / update / migrate this to my cousin / friend / new install".

If the change is purely code — routes, templates, services that don't touch schema — this skill does NOT apply.

## The one-command discipline

Every schema change MUST land as a paired commit:

1. Edit `models.py`.
2. Immediately generate the migration:
   ```
   alembic revision --autogenerate -m "short-imperative description"
   ```
   → creates a file in `alembic/versions/<hash>_<slug>.py`.
3. Open the generated file. Confirm the `upgrade()` body actually contains the `ALTER TABLE` / `CREATE TABLE` the change needs. Fix any nulls-vs-defaults on non-nullable columns (autogenerate misses defaults).
4. Run the migration locally:
   ```
   alembic upgrade head
   ```
   Verify it applies cleanly to Ibrahim's dev DB with `sqlite3 wealth_tracker.db ".schema <table>"`.
5. Ship BOTH the `models.py` change AND the migration file. Never one without the other.

If any step is skipped, a shared user extracting the update will get an app that boots into a broken schema.

## The `start.bat` guarantee (shared installs)

`Ibrahim/start.bat` and the shipped `Ahmed Poly Bags/start.bat` are expected to run `alembic upgrade head` before uvicorn. If they don't yet, wire that in as part of the change. The safety-net line should also snapshot the DB before migrating:

```bat
copy /Y wealth_tracker.db "wealth_tracker.db.backup-!DATE:/=-!"
python -m alembic upgrade head
```

If the migration blows up, the user's data survives as a `.backup-YYYY-MM-DD` file next to the live one.

## Never do these

- **Never manually `ALTER TABLE` via a raw SQL script instead of an Alembic migration.** The shared user's `alembic_version` won't advance and the next migration will chain off the wrong parent.
- **Never delete an existing migration file** once it's shipped. It's already recorded in some user's `alembic_version`. Write a new migration to reverse or supersede it instead.
- **Never rename a column or table in-place in `models.py` without a two-step migration** (add-new + backfill + drop-old across two releases). SQLite doesn't rename columns nicely, and autogenerate will drop-and-recreate — destroying data.
- **Never zip and ship `wealth_tracker.db`** with the update. The shared user's copy contains their real trades. Their DB must survive an extract-on-top. The zip should NOT include the live DB file — first-run creates a fresh one via `SQLModel.metadata.create_all(engine)` if missing.

## Zip / re-ship checklist

After a schema change, before re-zipping `~/Desktop/Ahmed-Poly-Bags-app.zip`:

- [ ] `models.py` change committed.
- [ ] `alembic/versions/<hash>_*.py` exists AND has a real `upgrade()` body.
- [ ] `alembic upgrade head` runs cleanly on a fresh `wealth_tracker.db` locally.
- [ ] `start.bat` calls `python -m alembic upgrade head` before uvicorn (with backup step).
- [ ] Zip exclusion list still excludes `venv/`, `__pycache__/`, `.pytest_cache/`, `.DS_Store`, **AND `wealth_tracker.db`** (don't overwrite the cousin's data).
- [ ] Verify the extracted zip has an `alembic/` folder AND the new migration file inside `alembic/versions/`.

Skipping any bullet risks corrupting or crashing the cousin's real business ledger.
