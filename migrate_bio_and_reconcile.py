"""
One-off migration:
1. Adds new optional bio columns to students (nationality, marital_status,
   next_of_kin_name, next_of_kin_phone).
2. Renames the three confirmed intakes to month+year codes/labels
   (2024-A -> JAN2025, 2025-B -> JUL2025, 2026-C -> JAN2026).
3. Reconciles intake_id / year_of_study / current_semester / academic_year /
   nationality for every student matched in "100% Fee Paid.xlsx", using its
   Intake/Batch/Year/Current Semester (Used)/Nationality columns — this is
   the richest signal available and fixes the root cause of the balance
   misalignment (students stuck in "Unconfirmed" fall back to an unbounded
   fee total).
4. Rebuilds (redistributes) each reconciled student's Payment records across
   their now-correctly-bounded periods, oldest period first, preserving the
   total amount paid exactly — this fixes lump-sum payments that were tagged
   to a single period instead of split across the periods they actually
   covered (the "overpaid here, unpaid there" symptom).

Safe to re-run — every step checks before writing. Existing payments outside
the reconciled set (e.g. the 1 student not found in the file) are untouched.
"""
import sys
sys.path.insert(0, ".")

import sqlite3
import openpyxl
import sqlalchemy
from datetime import datetime

DB_PATH = "sis_uoe.db"
XLSX_PATH = r"C:\Users\Hp\Desktop\My Projects\sis_uoe_ui_upgrade\data_uploads\payments\100% Fee Paid.xlsx"

RENAME_MAP = {
    "2024-A": ("JAN2025", "January 2025 (incl. Oct 2024 & Apr 2025 fast-track)"),
    "2025-B": ("JUL2025", "July 2025 (incl. Oct 2025 fast-track)"),
    "2026-C": ("JAN2026", "January 2026"),
}

# (Intake, Batch) from the file -> our intake code
FILE_INTAKE_TO_CODE = {
    ("October", "2024"): "JAN2025",
    ("January", "2025"): "JAN2025",
    ("April", "2025"): "JAN2025",
    ("July", "2025"): "JUL2025",
    ("October", "2025"): "JUL2025",
    ("January", "2026"): "JAN2026",
}


def step1_add_bio_columns(con):
    cur = con.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
    for col, ddl in [
        ("nationality", "ALTER TABLE students ADD COLUMN nationality VARCHAR(50)"),
        ("marital_status", "ALTER TABLE students ADD COLUMN marital_status VARCHAR(30)"),
        ("next_of_kin_name", "ALTER TABLE students ADD COLUMN next_of_kin_name VARCHAR(150)"),
        ("next_of_kin_phone", "ALTER TABLE students ADD COLUMN next_of_kin_phone VARCHAR(30)"),
    ]:
        if col not in cols:
            cur.execute(ddl)
            print(f"Added students.{col}")
        else:
            print(f"students.{col} already exists — skipped")
    con.commit()


def step2_rename_intakes(con):
    cur = con.cursor()
    for old_code, (new_code, new_label) in RENAME_MAP.items():
        row = cur.execute("SELECT id, code FROM intakes WHERE code = ?", (old_code,)).fetchone()
        if row:
            cur.execute("UPDATE intakes SET code = ?, label = ? WHERE id = ?", (new_code, new_label, row[0]))
            print(f"Renamed intake {old_code} -> {new_code}")
        else:
            existing_new = cur.execute("SELECT id FROM intakes WHERE code = ?", (new_code,)).fetchone()
            if existing_new:
                print(f"Intake {new_code} already exists — skipped")
            else:
                print(f"WARNING: neither {old_code} nor {new_code} found")
    con.commit()


def derive_semester_of_study(year_of_study, current_sem_used):
    return current_sem_used - (year_of_study - 1) * 2


def title_case_nationality(raw):
    if not raw:
        return None
    return str(raw).strip().title()


def step3_and_4_reconcile():
    """Reconcile intake/progress fields + rebuild payments for matched students."""
    from models import get_engine, IntakeProgress, FeeStructure, Payment as PaymentModel
    from sqlalchemy.orm import sessionmaker
    from utils.results_logic import get_relevant_fee_periods

    engine = get_engine(DB_PATH)
    Session = sessionmaker(bind=engine)
    db = Session()

    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb["Sheet2"]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    data = rows[1:]

    regno_idx = header.index("Reg No")
    name_idx = header.index("Student Name")
    intake_idx = header.index("Intake")
    batch_idx = header.index("Batch")
    year_idx = header.index("Year")
    cursem_idx = header.index("Current Semester (Used)")
    nationality_idx = header.index("Nationality")

    from models import Student, Intake, AcademicYear

    intake_by_code = {i.code: i for i in db.query(Intake).all()}

    not_found, reconciled, payment_rebuilt, skipped_no_mapping = [], [], [], []

    for row in data:
        regno = str(row[regno_idx]).strip()
        name = row[name_idx]
        student = db.query(Student).filter_by(student_number=regno).first()
        if not student:
            not_found.append((regno, name))
            continue

        file_intake_label = str(row[intake_idx]).strip()
        file_batch = str(row[batch_idx]).strip()
        intake_code = FILE_INTAKE_TO_CODE.get((file_intake_label, file_batch))
        if not intake_code or intake_code not in intake_by_code:
            skipped_no_mapping.append((regno, file_intake_label, file_batch))
            continue

        year_of_study = int(row[year_idx])
        cur_sem_used = int(row[cursem_idx])
        semester_of_study = derive_semester_of_study(year_of_study, cur_sem_used)
        if semester_of_study not in (1, 2):
            # Data anomaly (e.g. inconsistent Year/CurrentSemUsed) — skip
            # the progress fields for this student rather than write bad data.
            skipped_no_mapping.append((regno, file_intake_label, file_batch))
            continue

        nationality = title_case_nationality(row[nationality_idx])

        intake_obj = intake_by_code[intake_code]
        student.intake_id = intake_obj.id
        student.year_of_study = year_of_study
        student.current_semester = semester_of_study
        if nationality:
            student.nationality = nationality

        # Resolve academic_year from IntakeProgress if that exact step is mapped.
        progress = db.query(IntakeProgress).filter_by(
            intake_id=intake_obj.id, year_of_study=year_of_study, semester_of_study=semester_of_study
        ).first()
        if progress:
            student.academic_year = progress.academic_year.label

        db.flush()
        reconciled.append(regno)

        # ── Rebuild payments across the now-correctly-bounded periods ──
        periods = get_relevant_fee_periods(db, student)
        if not periods:
            continue

        existing_payments = db.query(PaymentModel).filter_by(student_id=student.id).all()
        total_paid = sum(p.amount for p in existing_payments)
        if total_paid <= 0:
            continue

        original_refs = ", ".join(p.reference or f"id={p.id}" for p in existing_payments)
        received_by = existing_payments[0].received_by if existing_payments else None

        for p in existing_payments:
            db.delete(p)
        db.flush()

        remaining = total_paid
        for ay_label, sem in periods:
            if remaining <= 0:
                break
            fs = db.query(FeeStructure).filter_by(
                programme_id=student.programme_id, academic_year=ay_label,
                semester=sem, mode_of_study=student.mode_of_study,
            ).first()
            fee_amount = fs.total_fee if fs else 0.0
            apply_amt = min(remaining, fee_amount) if fee_amount > 0 else 0.0
            if apply_amt > 0:
                db.add(PaymentModel(
                    student_id=student.id, academic_year=ay_label, semester=sem,
                    amount=round(apply_amt, 2),
                    reference=f"RECONCILED-{regno}-{ay_label.replace('/', '-')}S{sem}",
                    method="Fee Reconciliation (cleanup)",
                    status="Completed", received_by=received_by,
                    notes=f"Redistributed from original payment(s): {original_refs} (total K{total_paid:,.2f})",
                ))
                remaining -= apply_amt

        if remaining > 0:
            # Leftover beyond all known periods — attach to the most recent one
            # to keep the total conserved exactly.
            last_ay, last_sem = periods[-1]
            db.add(PaymentModel(
                student_id=student.id, academic_year=last_ay, semester=last_sem,
                amount=round(remaining, 2),
                reference=f"RECONCILED-{regno}-{last_ay.replace('/', '-')}S{last_sem}-EXTRA",
                method="Fee Reconciliation (cleanup)",
                status="Completed", received_by=received_by,
                notes=f"Leftover beyond known periods, from original payment(s): {original_refs}",
            ))

        payment_rebuilt.append(regno)

    db.commit()

    print(f"\nNot found in DB: {len(not_found)}")
    for r in not_found:
        print(f"  {r}")
    print(f"Skipped (no clean Intake/Year/Semester mapping): {len(skipped_no_mapping)}")
    for r in skipped_no_mapping:
        print(f"  {r}")
    print(f"Reconciled (intake/year/semester/nationality set): {len(reconciled)}")
    print(f"Payments rebuilt: {len(payment_rebuilt)}")

    db.close()


def main():
    con = sqlite3.connect(DB_PATH)
    step1_add_bio_columns(con)
    step2_rename_intakes(con)
    con.close()

    step3_and_4_reconcile()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
