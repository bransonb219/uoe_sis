"""
ONE-OFF SETUP SCRIPT — University of Edenberg SIS

Creates exactly one Admin account in an otherwise EMPTY database. Use this
once, when transitioning from demo/seed data to real production data, to
get your first login without pulling in any demo programmes, courses,
students, or fake results.

USAGE:
    1. Make sure sis_uoe.db does NOT exist yet (delete it if it does).
    2. Make sure utils/seed.py's seed_all() call in app.py is disabled
       (commented out) — see the README section on going live.
    3. Run this script once from the project root:
           python init_admin.py
    4. Start the app normally:
           python -m streamlit run app.py
    5. Log in with the username/password printed below, then immediately
       go to Settings and change the password, and create any other
       staff accounts (Registrar, Finance, Lecturers) you need.
    6. Build out your real Programmes, Fee Structures, and Courses via
       the app's Settings / Courses pages — nothing is pre-populated.

This script is safe to run only once. If an Admin account already exists,
it will refuse to create a duplicate and tell you so.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from models import get_engine, get_session, init_db, User, UserRole
from utils.auth import hash_password

DB_PATH = "sis_uoe.db"

# Change these before running if you want a different initial username/password.
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "ChangeMe@2026"
ADMIN_FIRST_NAME = "System"
ADMIN_LAST_NAME = "Administrator"
ADMIN_EMAIL = "admin@ue.ac.zm"


def main():
    db_existed = os.path.exists(DB_PATH)

    engine = get_engine(DB_PATH)
    init_db(engine)  # creates all tables; harmless if they already exist
    session = get_session(engine)

    existing_admin = session.query(User).filter_by(username=ADMIN_USERNAME).first()
    if existing_admin:
        print(f"An account with username '{ADMIN_USERNAME}' already exists. "
              f"Refusing to create a duplicate. If you need to reset its "
              f"password instead, do that from the Settings page once logged in, "
              f"or ask for a password-reset script.")
        session.close()
        return

    any_user_exists = session.query(User).count() > 0
    if any_user_exists:
        print("WARNING: the database already contains other user accounts. "
              "This script only ever ADDS an Admin account — it will not "
              "touch or remove anything else. Proceeding.")

    admin = User(
        username=ADMIN_USERNAME,
        password_hash=hash_password(ADMIN_PASSWORD),
        role=UserRole.ADMIN,
        first_name=ADMIN_FIRST_NAME,
        last_name=ADMIN_LAST_NAME,
        email=ADMIN_EMAIL,
        is_active=True,
    )
    session.add(admin)
    session.commit()

    print("=" * 60)
    print("Admin account created successfully." if not db_existed
          else "Admin account added to existing database.")
    print(f"  Username: {ADMIN_USERNAME}")
    print(f"  Password: {ADMIN_PASSWORD}")
    print("=" * 60)
    print("IMPORTANT: log in and change this password immediately via "
          "the Settings page. This script will refuse to run again once "
          "this username exists, so it cannot be used to reset it later.")

    session.close()


if __name__ == "__main__":
    main()
