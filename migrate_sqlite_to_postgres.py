"""
One-off migration: copies every row from the local SQLite database
(sis_uoe.db) into a target Postgres database, preserving primary keys and
foreign key relationships, then resets Postgres's auto-increment sequences
to match. Run this once when moving from local SQLite to a hosted Postgres
for Streamlit Cloud deployment (the local filesystem there is ephemeral —
SQLite data would be lost on every restart/redeploy).

USAGE:
    Set the target connection string as an environment variable (don't
    paste credentials into chat or commit them):

        # PowerShell
        $env:TARGET_DATABASE_URL = "postgresql://user:pass@host:5432/dbname?sslmode=require"
        python migrate_sqlite_to_postgres.py

        # bash
        export TARGET_DATABASE_URL="postgresql://user:pass@host:5432/dbname?sslmode=require"
        python migrate_sqlite_to_postgres.py

Safe to re-run against an EMPTY target database. Will refuse to run if the
target already has data, to avoid silently duplicating rows.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from models import get_engine, init_db, Base, User
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

SQLITE_PATH = "sis_uoe.db"


def main():
    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not target_url:
        print("ERROR: set TARGET_DATABASE_URL environment variable first. See the docstring for how.")
        sys.exit(1)

    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: {SQLITE_PATH} not found in the current directory.")
        sys.exit(1)

    source_engine = get_engine(SQLITE_PATH)
    target_engine = get_engine(database_url=target_url)

    # Refuse to run against a target that already has data — avoids
    # silently duplicating rows if this is run twice.
    init_db(target_engine)
    Session = sessionmaker(bind=target_engine)
    target_session = Session()
    existing_users = target_session.query(User).count()
    if existing_users > 0:
        print(f"ERROR: target database already has {existing_users} user(s). "
              f"Refusing to migrate into a non-empty database. "
              f"Drop and recreate the target database first if you really want to re-run this.")
        target_session.close()
        sys.exit(1)
    target_session.close()

    source_conn = source_engine.connect()
    target_conn = target_engine.connect()

    total_rows = 0
    try:
        for table in Base.metadata.sorted_tables:
            rows = source_conn.execute(table.select()).mappings().all()
            if not rows:
                print(f"  {table.name}: 0 rows — skipped")
                continue
            target_conn.execute(table.insert(), [dict(r) for r in rows])
            total_rows += len(rows)
            print(f"  {table.name}: {len(rows)} row(s) copied")

        target_conn.commit()

        # Reset Postgres auto-increment sequences to match the copied data —
        # otherwise the next INSERT without an explicit id would collide
        # with the highest id we just copied in.
        for table in Base.metadata.sorted_tables:
            pk_cols = [c.name for c in table.primary_key.columns]
            if len(pk_cols) != 1:
                continue
            pk = pk_cols[0]
            seq_name = f"{table.name}_{pk}_seq"
            target_conn.execute(text(
                f"SELECT setval('{seq_name}', COALESCE((SELECT MAX({pk}) FROM {table.name}), 1))"
            ))
        target_conn.commit()
        print(f"\nMigration complete: {total_rows} row(s) total. Sequences reset.")
    finally:
        source_conn.close()
        target_conn.close()


if __name__ == "__main__":
    main()
