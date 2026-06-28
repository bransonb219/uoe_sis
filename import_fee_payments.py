"""
One-off import: reconcile Payment records against a detailed fee-payment
spreadsheet ("100% Fee Paid.xlsx").

Does NOT touch the schema — only reads existing Student fields
(academic_year, current_semester, programme_id, mode_of_study, intake_id)
and writes new Payment rows where the file shows MORE paid than the DB
currently has on record.

Policy:
  - Never reduces or deletes existing payments — only tops up the gap
    between file["Overall Paid"] and the DB's current total.
  - The top-up amount is distributed oldest-period-first across the
    student's bounded relevant periods (get_relevant_fee_periods), so an
    amount that covers the current semester "in excess" transfers to clear
    older deficits first, instead of just padding the current period.
  - Idempotent: skips a student if an import-tagged payment for them
    already exists (reference starts with "IMPORT-100PCT-").
"""
import sys
sys.path.insert(0, ".")

import openpyxl
import sqlalchemy
from models import get_engine, Student, Payment, FeeStructure, User, UserRole
from sqlalchemy.orm import sessionmaker
from utils.results_logic import get_relevant_fee_periods
from datetime import datetime

XLSX_PATH = r"C:\Users\Hp\Desktop\My Projects\sis_uoe_ui_upgrade\data_uploads\payments\100% Fee Paid.xlsx"
DB_PATH = "sis_uoe.db"


def main():
    engine = get_engine(DB_PATH)
    db = sessionmaker(bind=engine)()

    staff = db.query(User).filter(User.role == UserRole.ADMIN).first()
    staff_id = staff.id if staff else None

    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb["Sheet2"]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    data = rows[1:]

    regno_idx = header.index("Reg No")
    name_idx = header.index("Student Name")
    overall_paid_idx = header.index("Overall Paid (Upto Current Sem)")

    not_found, already_covered, topped_up, skipped_idempotent = [], 0, [], 0

    for row in data:
        regno = str(row[regno_idx]).strip()
        name = row[name_idx]
        file_total_paid = float(row[overall_paid_idx] or 0)

        student = db.query(Student).filter_by(student_number=regno).first()
        if not student:
            not_found.append((regno, name))
            continue

        # Idempotency: skip if we've already run this import for this student
        existing_import = db.query(Payment).filter(
            Payment.student_id == student.id,
            Payment.reference.like(f"IMPORT-100PCT-{regno}%"),
        ).first()
        if existing_import:
            skipped_idempotent += 1
            continue

        db_total_paid = (
            db.query(sqlalchemy.func.sum(Payment.amount))
            .filter_by(student_id=student.id)
            .scalar() or 0.0
        )

        diff = round(file_total_paid - db_total_paid, 2)
        if diff <= 0:
            already_covered += 1
            continue

        # Distribute the top-up oldest-period-first.
        periods = get_relevant_fee_periods(db, student)
        if not periods:
            # No intake/progress data — fall back to current academic_year/semester only.
            periods = [(student.academic_year, student.current_semester)] if student.academic_year else []

        remaining = diff
        applied_any = False
        for ay_label, sem in periods:
            if remaining <= 0:
                break
            fs = db.query(FeeStructure).filter_by(
                programme_id=student.programme_id, academic_year=ay_label,
                semester=sem, mode_of_study=student.mode_of_study,
            ).first()
            if not fs:
                continue
            already_paid_for_period = (
                db.query(sqlalchemy.func.sum(Payment.amount))
                .filter_by(student_id=student.id, academic_year=ay_label, semester=sem)
                .scalar() or 0.0
            )
            needed = max(0.0, fs.total_fee - already_paid_for_period)
            apply_amt = min(remaining, needed)
            if apply_amt > 0:
                db.add(Payment(
                    student_id=student.id, academic_year=ay_label, semester=sem,
                    amount=round(apply_amt, 2),
                    reference=f"IMPORT-100PCT-{regno}-{ay_label.replace('/', '-')}S{sem}",
                    method="Bulk Import (fee reconciliation)",
                    status="Completed", received_by=staff_id,
                    notes="Transferred from current-semester overpayment per fee reconciliation import.",
                ))
                remaining -= apply_amt
                applied_any = True

        # Any leftover after all known periods are covered — attach to the
        # most recent (current) period so the total stays conserved.
        if remaining > 0:
            cur_ay = student.academic_year
            cur_sem = student.current_semester
            db.add(Payment(
                student_id=student.id, academic_year=cur_ay, semester=cur_sem,
                amount=round(remaining, 2),
                reference=f"IMPORT-100PCT-{regno}-CURTOPUP",
                method="Bulk Import (fee reconciliation)",
                status="Completed", received_by=staff_id,
            ))
            applied_any = True

        if applied_any:
            topped_up.append((regno, name, diff))

    db.commit()

    print(f"Not found in DB: {len(not_found)}")
    for r in not_found:
        print(f"  {r}")
    print(f"Already covered (DB >= file): {already_covered}")
    print(f"Skipped (already imported, idempotent): {skipped_idempotent}")
    print(f"Topped up: {len(topped_up)}")
    for r in topped_up:
        print(f"  {r}")

    db.close()


if __name__ == "__main__":
    main()
