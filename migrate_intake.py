"""
One-off migration: intake/cohort tracking foundation.

1. Adds new columns to existing tables (students.intake_id,
   students.current_semester, registration_periods.deadline_at).
2. Creates the new tables (intakes, academic_years, intake_progress,
   exemptions) via create_all.
3. Seeds reference data: Intake rows (JAN2025, JUL2025, JAN2026, Legacy,
   Unconfirmed), AcademicYear rows, and the known IntakeProgress steps.
4. Applies the confirmed intake mappings from the reconciliation
   spreadsheet (migration_exports/intake_reconciliation (Autosaved).xlsx)
   to the matching students by student_number.
5. Buckets every other student into the "Unconfirmed" intake so nothing
   is left null or silently guessed.

Safe to re-run — every step checks before writing.
"""
import sqlite3
import sys
import openpyxl

DB_PATH = "sis_uoe.db"
XLSX_PATH = "migration_exports/intake_reconciliation (Autosaved).xlsx"

# Maps the (Excel-coerced) confirmed_intake date values to intake codes.
DATE_TO_INTAKE_CODE = {
    "2025-01-01": "JAN2025",
    "2025-07-01": "JUL2025",
    "2026-01-01": "JAN2026",
}

# Intake codes are named by month+year (not arbitrary letters) so a future
# year with two intakes (e.g. Jan + Jul) reads naturally, and a year with
# only one intake doesn't need any "1 of 2" disambiguation.
INTAKES = [
    ("JAN2025", "January 2025 (incl. Oct 2024 & Apr 2025 fast-track)"),
    ("JUL2025", "July 2025 (incl. Oct 2025 fast-track)"),
    ("JAN2026", "January 2026"),
    ("LEGACY", "Legacy / pre-October-2024"),
    ("UNCONFIRMED", "Not yet reconciled to a confirmed intake"),
]

ACADEMIC_YEARS = ["2024/2025", "2025/2026", "2026/2027"]

# (intake_code, year_of_study, semester_of_study, academic_year, is_current)
INTAKE_PROGRESS = [
    ("JAN2025", 1, 1, "2024/2025", False),
    ("JAN2025", 1, 2, "2024/2025", False),
    ("JAN2025", 2, 1, "2025/2026", True),
    ("JUL2025", 1, 1, "2025/2026", False),
    ("JUL2025", 1, 2, "2025/2026", True),
    ("JAN2026", 1, 1, "2025/2026", True),
]


def column_exists(cur, table, column):
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def step1_add_columns(con):
    cur = con.cursor()
    if not column_exists(cur, "students", "intake_id"):
        cur.execute("ALTER TABLE students ADD COLUMN intake_id INTEGER REFERENCES intakes(id)")
        print("Added students.intake_id")
    else:
        print("students.intake_id already exists — skipped")

    if not column_exists(cur, "students", "current_semester"):
        cur.execute("ALTER TABLE students ADD COLUMN current_semester INTEGER DEFAULT 1")
        print("Added students.current_semester")
    else:
        print("students.current_semester already exists — skipped")

    if not column_exists(cur, "registration_periods", "deadline_at"):
        cur.execute("ALTER TABLE registration_periods ADD COLUMN deadline_at DATETIME")
        print("Added registration_periods.deadline_at")
    else:
        print("registration_periods.deadline_at already exists — skipped")
    con.commit()


def step2_create_new_tables():
    sys.path.insert(0, ".")
    from models import get_engine, init_db
    engine = get_engine(DB_PATH)
    init_db(engine)
    print("New tables created (intakes, academic_years, intake_progress, exemptions).")


def step3_seed_reference_data(con):
    cur = con.cursor()

    intake_ids = {}
    for code, label in INTAKES:
        row = cur.execute("SELECT id FROM intakes WHERE code = ?", (code,)).fetchone()
        if row:
            intake_ids[code] = row[0]
        else:
            cur.execute(
                "INSERT INTO intakes (code, label, is_active, created_at) VALUES (?, ?, 1, datetime('now'))",
                (code, label),
            )
            intake_ids[code] = cur.lastrowid
            print(f"Created Intake {code}")
    con.commit()

    ay_ids = {}
    for label in ACADEMIC_YEARS:
        row = cur.execute("SELECT id FROM academic_years WHERE label = ?", (label,)).fetchone()
        if row:
            ay_ids[label] = row[0]
        else:
            cur.execute(
                "INSERT INTO academic_years (label, is_active, created_at) VALUES (?, 1, datetime('now'))",
                (label,),
            )
            ay_ids[label] = cur.lastrowid
            print(f"Created AcademicYear {label}")
    con.commit()

    for code, yos, sos, ay_label, is_current in INTAKE_PROGRESS:
        intake_id = intake_ids[code]
        ay_id = ay_ids[ay_label]
        existing = cur.execute(
            "SELECT id FROM intake_progress WHERE intake_id=? AND year_of_study=? AND semester_of_study=?",
            (intake_id, yos, sos),
        ).fetchone()
        if existing:
            continue
        cur.execute(
            "INSERT INTO intake_progress (intake_id, year_of_study, semester_of_study, academic_year_id, is_current, started_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (intake_id, yos, sos, ay_id, int(is_current)),
        )
        print(f"Created IntakeProgress {code} Y{yos}S{sos} -> {ay_label} (current={is_current})")
    con.commit()

    return intake_ids


def step4_apply_confirmed_mappings(con, intake_ids):
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    sn_idx = header.index("student_number")
    ci_idx = header.index("confirmed_intake")

    cur = con.cursor()
    applied, skipped_unmapped_date, skipped_not_found = 0, 0, 0

    # IntakeProgress current step per intake, to set year_of_study/current_semester
    progress_by_intake = {}
    for row in cur.execute(
        "SELECT intake_id, year_of_study, semester_of_study FROM intake_progress WHERE is_current = 1"
    ).fetchall():
        progress_by_intake[row[0]] = (row[1], row[2])

    for row in rows[1:]:
        snum = row[sn_idx]
        confirmed_val = row[ci_idx]
        if not confirmed_val:
            continue
        date_key = str(confirmed_val)[:10]
        intake_code = DATE_TO_INTAKE_CODE.get(date_key)
        if not intake_code:
            skipped_unmapped_date += 1
            continue
        intake_id = intake_ids[intake_code]
        student_row = cur.execute(
            "SELECT id FROM students WHERE student_number = ?", (str(snum),)
        ).fetchone()
        if not student_row:
            skipped_not_found += 1
            continue
        student_id = student_row[0]
        yos, sos = progress_by_intake.get(intake_id, (None, None))
        if yos is not None:
            cur.execute(
                "UPDATE students SET intake_id=?, year_of_study=?, current_semester=? WHERE id=?",
                (intake_id, yos, sos, student_id),
            )
        else:
            cur.execute("UPDATE students SET intake_id=? WHERE id=?", (intake_id, student_id))
        applied += 1

    con.commit()
    print(f"Applied {applied} confirmed mappings.")
    print(f"Skipped {skipped_unmapped_date} rows with unrecognized confirmed_intake values.")
    print(f"Skipped {skipped_not_found} rows where student_number wasn't found in the DB.")


def step5_bucket_remaining_as_unconfirmed(con, intake_ids):
    cur = con.cursor()
    unconfirmed_id = intake_ids["UNCONFIRMED"]
    cur.execute(
        "UPDATE students SET intake_id = ? WHERE intake_id IS NULL",
        (unconfirmed_id,),
    )
    print(f"Bucketed {cur.rowcount} remaining students into 'Unconfirmed'.")
    cur.execute(
        "UPDATE students SET current_semester = 1 WHERE current_semester IS NULL"
    )
    con.commit()


def main():
    con = sqlite3.connect(DB_PATH)
    step1_add_columns(con)
    con.close()

    step2_create_new_tables()

    con = sqlite3.connect(DB_PATH)
    intake_ids = step3_seed_reference_data(con)
    step4_apply_confirmed_mappings(con, intake_ids)
    step5_bucket_remaining_as_unconfirmed(con, intake_ids)
    con.close()
    print("Migration complete.")


if __name__ == "__main__":
    main()
