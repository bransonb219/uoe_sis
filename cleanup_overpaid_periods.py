"""
One-off cleanup: redistributes lump-sum-tagged payments for students whose
intake is CONFIRMED (not Unconfirmed/Legacy) and who have at least one
period showing recorded payments exceeding that period's fee — the same
"lump sum tagged to one period" symptom found and fixed for the original
144 reconciled students, but found here more broadly across the live data.

For each affected student: sums their existing total payments (preserving
the exact total — no money created or destroyed), deletes their existing
Payment rows, and re-applies the total via allocate_payment(), which
spreads it oldest-period-first, never letting any single period exceed
its fee.

Students with NO confirmed intake are deliberately left untouched — for
them we only have a single bounded period, so redistributing could
silently lose real payment data instead of correcting it.

USAGE:
    export TARGET_DATABASE_URL="postgresql://..."
    python cleanup_overpaid_periods.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from models import get_engine, Student, Payment, FeeStructure
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from utils.results_logic import allocate_payment


def main():
    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not target_url:
        print("ERROR: set TARGET_DATABASE_URL first.")
        sys.exit(1)

    engine = get_engine(database_url=target_url)
    db = sessionmaker(bind=engine)()

    affected_ids = [r[0] for r in db.execute(text("""
        SELECT DISTINCT s.id
        FROM payments p
        JOIN students s ON s.id = p.student_id
        JOIN fee_structures fs ON fs.programme_id = s.programme_id
            AND fs.academic_year = p.academic_year
            AND fs.semester = p.semester
            AND fs.mode_of_study = s.mode_of_study
        GROUP BY s.id, p.academic_year, p.semester, fs.total_fee
        HAVING SUM(p.amount) > fs.total_fee + 0.01
    """)).fetchall()]

    cleaned, skipped_unconfirmed, skipped_no_periods = [], [], []

    for sid in affected_ids:
        student = db.get(Student, sid)
        if not student.intake or student.intake.code in ("UNCONFIRMED", "LEGACY"):
            skipped_unconfirmed.append(student.student_number)
            continue

        # Each student is its own transaction — a rollback here must NEVER
        # discard another student's already-committed redistribution.
        existing_payments = db.query(Payment).filter_by(student_id=student.id).all()
        total_paid = sum(p.amount for p in existing_payments)
        if total_paid <= 0:
            continue

        original_refs = ", ".join(p.reference or f"id={p.id}" for p in existing_payments)
        received_by = existing_payments[0].received_by if existing_payments else None

        for p in existing_payments:
            db.delete(p)
        db.flush()

        result = allocate_payment(
            db, student, total_paid, method="Cleanup Redistribution",
            reference=f"CLEANUP-{student.student_number}",
            received_by=received_by,
            notes=f"Redistributed from original payment(s): {original_refs} (total K{total_paid:,.2f})",
        )

        if result["unallocated"] > 0:
            # Shouldn't happen for confirmed-intake students with a real
            # overpayment symptom (the excess always belonged to an earlier
            # period), but guard anyway — never silently drop money. Only
            # this student's pending change is discarded since we commit
            # per-student.
            skipped_no_periods.append((student.student_number, result["unallocated"]))
            db.rollback()
            continue

        db.commit()
        cleaned.append((student.student_number, total_paid, len(result["payments_created"])))

    print(f"Cleaned: {len(cleaned)} student(s)")
    for c in cleaned:
        print(f"  {c[0]}: K{c[1]:,.2f} redistributed across {c[2]} period(s)")
    print(f"\nSkipped (Unconfirmed/Legacy intake — left untouched): {len(skipped_unconfirmed)}")
    print(f"Skipped (would have lost money — rolled back, needs manual review): {len(skipped_no_periods)}")
    for s in skipped_no_periods:
        print(f"  {s}")

    db.close()


if __name__ == "__main__":
    main()
