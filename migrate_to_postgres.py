"""One-time copy of data/jobs.db (SQLite) into the Postgres database set in .env (DB_* or DATABASE_URL).

Usage:  python migrate_to_postgres.py
Safe to re-run only on an empty target: it stops if the Postgres tables already contain users.
"""
import sys
from datetime import datetime

from sqlalchemy import Integer, func, insert, select, text

from backend.db import DATA_DIR, SQLITE_URL, Base, Resume, User, engine, make_engine

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
    # older versions kept resumes as files in data/resumes/<user_id>.pdf
    have = set(dst.scalars(select(Resume.user_id)))
    users = set(dst.scalars(select(User.id)))
    n = 0
    for pdf in (DATA_DIR / "resumes").glob("*.pdf"):
        uid = int(pdf.stem) if pdf.stem.isdigit() else None
        if uid in users and uid not in have:
            txt = pdf.with_suffix(".txt")
            dst.execute(insert(Resume.__table__), [{"user_id": uid, "pdf": pdf.read_bytes(),
                        "text": txt.read_text(encoding="utf-8") if txt.exists() else "", "uploaded_at": datetime.now()}])
            n += 1
    print(f"resume files imported: {n}")
    # move id sequences past the copied ids
    for table in Base.metadata.sorted_tables:
        if "id" in table.c and isinstance(table.c.id.type, Integer):
            dst.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                             f"COALESCE((SELECT MAX(id) FROM {table.name}), 0) + 1, false)"))
print("Done. Restart the app; it now uses Postgres.")
