"""One-time copy of data/jobs.db (SQLite) into the Postgres database set in .env (DB_* or DATABASE_URL).

Usage:  python migrate_to_postgres.py
Safe to re-run only on an empty target: it stops if the Postgres tables already contain users.
"""
import sys

from sqlalchemy import Integer, func, insert, select, text

from backend.db import SQLITE_URL, Base, User, engine, make_engine

if engine.dialect.name != "postgresql":
    sys.exit("Set DB_HOST/DB_USER/DB_PASSWORD (or DATABASE_URL) in .env to your Supabase database first.")

src = make_engine(SQLITE_URL)
with engine.begin() as dst:
    if dst.scalar(select(func.count()).select_from(User.__table__)):
        sys.exit("Postgres already has users — not copying again.")
    with src.connect() as s:
        for table in Base.metadata.sorted_tables:  # parents before children
            if not src.dialect.has_table(s, table.name):
                continue
            rows = [dict(r._mapping) for r in s.execute(select(table))]
            if rows:
                dst.execute(insert(table), rows)
            print(f"{table.name}: {len(rows)} rows")
    # move id sequences past the copied ids
    for table in Base.metadata.sorted_tables:
        if "id" in table.c and isinstance(table.c.id.type, Integer):
            dst.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                             f"COALESCE((SELECT MAX(id) FROM {table.name}), 0) + 1, false)"))
print("Done. Restart the app; it now uses Postgres.")
