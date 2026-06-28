"""
One-off calibration: set Student.fee_adjustment for every student matched in
"100% Fee Paid.xlsx" so that get_cumulative_balance()'s computed total_fees
exactly equals the file's authoritative "Overall Charged (Upto Current Sem)".

adjustment = file_overall_charged - (sum of FeeStructure.total_fee across
the student's bounded relevant periods)

This captures individual scholarships/discounts/additional charges (the
file's "Has Additional Fee"/"Has Deduction Fee" flags) that the shared
per-programme/year/semester/mode FeeStructure can't represent on its own.

Safe to re-run — recomputes and overwrites fee_adjustment each time (idempotent).
"""
import sys
sys.path.insert(0, ".")

import openpyxl
from models import get_engine, Student, FeeStructure
from sqlalchemy.orm import sessionmaker
from utils.results_logic import get_relevant_fee_periods

XLSX_PATH = r"C:\Users\Hp\Desktop\My Projects\sis_uoe_ui_upgrade\data_uploads\payments\100% Fee Paid.xlsx"
DB_PATH = "sis_uoe.db"


def main():
    engine = get_engine(DB_PATH)
    db = sessionmaker(bind=engine)()

    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb["Sheet2"]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    data = rows[1:]

    regno_idx = header.index("Reg No")
    overall_charged_idx = header.index("Overall Charged (Upto Current Sem)")

    calibrated, no_periods, not_found = 0, [], []

    for row in data:
        regno = str(row[regno_idx]).strip()
        file_charged = float(row[overall_charged_idx] or 0)

        student = db.query(Student).filter_by(student_number=regno).first()
        if not student:
            not_found.append(regno)
            continue

        periods = get_relevant_fee_periods(db, student)
        if not periods:
            no_periods.append(regno)
            continue

        flat_total = 0.0
        for ay_label, sem in periods:
            fs = db.query(FeeStructure).filter_by(
                programme_id=student.programme_id, academic_year=ay_label,
                semester=sem, mode_of_study=student.mode_of_study,
            ).first()
            if fs:
                flat_total += fs.total_fee

        adjustment = round(file_charged - flat_total, 2)
        student.fee_adjustment = adjustment
        calibrated += 1

    db.commit()

    print(f"Calibrated: {calibrated}")
    print(f"No bounded periods (intake not reconciled): {len(no_periods)} -> {no_periods}")
    print(f"Not found in DB: {len(not_found)} -> {not_found}")

    db.close()


if __name__ == "__main__":
    main()
