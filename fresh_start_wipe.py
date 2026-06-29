"""
One-off "fresh start" wipe: clears Student + financial data only, keeping
configuration/reference data intact (Programmes, Courses, Fee Structures,
Intakes, Academic Years, Cohort Progress mappings) and keeping every Staff
account (Admin/Registrar/Finance/Lecturer/Admin Support) so nobody is
locked out.

Wiped (in FK-safe order — Postgres enforces foreign keys strictly):
  Exemption -> Result -> ResultPublicationBatch -> StudentCourse -> Payment
  -> AuditLog (only rows belonging to a student's own login) -> Registration
  -> User (role=Student) -> Student

NOT touched: Programme, Course, FeeStructure, Intake, AcademicYear,
IntakeProgress, RegistrationPeriod, SystemSetting, and every non-Student User
(plus their AuditLog history).

Backs up every table it's about to wipe to local CSV files first
(fresh_start_backup/*.csv) — restoring is a manual re-import from these if
ever needed.

USAGE:
    export TARGET_DATABASE_URL="postgresql://..."
    python fresh_start_wipe.py            # dry run — reports counts only
    python fresh_start_wipe.py --confirm  # actually deletes
"""
import sys
import os
import csv
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from models import get_engine, Student, User, UserRole
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

BACKUP_DIR = "fresh_start_backup"

TABLES_TO_WIPE = [
    "exemptions",
    "results",
    "result_publication_batches",
    "student_courses",
    "payments",
    "registrations",
    "students",
]


def backup_table(conn, table_name):
    rows = conn.execute(text(f"SELECT * FROM {table_name}")).mappings().all()
    if not rows:
        print(f"  {table_name}: 0 rows — nothing to back up")
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"{table_name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows([dict(r) for r in rows])
    print(f"  {table_name}: backed up {len(rows)} row(s) -> {path}")


def backup_student_audit_logs(conn):
    rows = conn.execute(text("""
        SELECT al.* FROM audit_logs al
        JOIN users u ON u.id = al.user_id
        WHERE u.role = 'STUDENT'
    """)).mappings().all()
    if not rows:
        print("  audit_logs (student-owned): 0 rows — nothing to back up")
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, "audit_logs_student_owned.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows([dict(r) for r in rows])
    print(f"  audit_logs (student-owned): backed up {len(rows)} row(s) -> {path}")


def backup_student_users(conn):
    rows = conn.execute(text("SELECT * FROM users WHERE role = 'STUDENT'")).mappings().all()
    if not rows:
        print("  users (role=Student): 0 rows — nothing to back up")
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, "users_students.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows([dict(r) for r in rows])
    print(f"  users (role=Student): backed up {len(rows)} row(s) -> {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Actually perform the deletion (default is dry-run)")
    args = parser.parse_args()

    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not target_url:
        print("ERROR: set TARGET_DATABASE_URL first.")
        sys.exit(1)

    engine = get_engine(database_url=target_url)
    conn = engine.connect()

    print("=== Current counts ===")
    for table in TABLES_TO_WIPE:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        print(f"  {table}: {count}")
    student_user_count = conn.execute(text("SELECT COUNT(*) FROM users WHERE role = 'STUDENT'")).scalar()
    print(f"  users (role=Student): {student_user_count}")
    student_audit_count = conn.execute(text("""
        SELECT COUNT(*) FROM audit_logs al JOIN users u ON u.id = al.user_id WHERE u.role = 'STUDENT'
    """)).scalar()
    print(f"  audit_logs (student-owned): {student_audit_count}")

    print()
    print("=== Untouched (verified not in the wipe list) ===")
    for table in ["programmes", "courses", "fee_structures", "intakes", "academic_years",
                  "intake_progress", "registration_periods", "system_settings"]:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        print(f"  {table}: {count} (kept)")
    staff_count = conn.execute(text("SELECT COUNT(*) FROM users WHERE role != 'STUDENT'")).scalar()
    print(f"  users (staff, role != Student): {staff_count} (kept)")

    if not args.confirm:
        print()
        print("Dry run only — no changes made. Re-run with --confirm to actually wipe.")
        conn.close()
        return

    print()
    print("=== Backing up before delete ===")
    for table in TABLES_TO_WIPE:
        backup_table(conn, table)
    backup_student_audit_logs(conn)
    backup_student_users(conn)

    print()
    print("=== Deleting (FK-safe order) ===")
    # The connection already has an implicit (autobegin) transaction open
    # from the SELECTs above — commit/rollback that one directly rather
    # than calling conn.begin() again, which errors if one's already active.
    try:
        conn.execute(text("DELETE FROM exemptions"))
        conn.execute(text("DELETE FROM results"))
        conn.execute(text("DELETE FROM result_publication_batches"))
        conn.execute(text("DELETE FROM student_courses"))
        conn.execute(text("DELETE FROM payments"))
        conn.execute(text("""
            DELETE FROM audit_logs WHERE user_id IN (SELECT id FROM users WHERE role = 'STUDENT')
        """))
        conn.execute(text("DELETE FROM registrations"))
        conn.execute(text("DELETE FROM users WHERE role = 'STUDENT'"))
        conn.execute(text("DELETE FROM students"))
        conn.commit()
        print("Wipe complete.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR — rolled back, nothing was deleted: {e}")
        raise

    print()
    print("=== Final counts ===")
    for table in TABLES_TO_WIPE:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        print(f"  {table}: {count}")

    conn.close()


if __name__ == "__main__":
    main()
