"""
Results business logic — University of Edenberg SIS

Grading scale (7-band institutional scale):
  86–100  A+   Upper Distinction       5 pts (5-pt scale) / 4.0 (4-pt scale)
  75–85   A    Lower Distinction       4 pts (5-pt scale) / 3.5 (4-pt scale)
  70–74   B+   Meritorious             3 pts (5-pt scale) / 3.0 (4-pt scale)
  60–69   B    Credit                  3 pts (5-pt scale) / 3.0 (4-pt scale)
  56–59   C+   Satisfactory/Definite Pass  2 pts         / 2.0 (4-pt scale)
  50–55   C    Pass                    1 pt  (5-pt scale) / 1.0 (4-pt scale)
  0–49    F    Fail                    0 pts (both scales)

Note: B+ and B intentionally share the same grade point on both scales.
D/D+/F all collapse to 0 — 'F' is stored as the canonical letter for the
0-39 band since the points are identical across any subdivision within it.

Weighting schemes (by ProgrammeLevel):
  Diploma / Undergraduate:
      CA1 10% + CA2 10% + Mid-Semester 20% + Final 60%
  Postgraduate:
      CA1 25% + CA2 25% + Final 50%  (no Mid-Semester component)

Pass threshold: total score >= 40
Supplementary: total score in [40, 55] — student sits a supplementary exam
Academic status: fail >= 2 courses → "Proceed but Repeat"

Payment gates:
  Course registration (past semester):       No gate — backdating always allowed
  Course registration (current/future):      25% of current semester fee paid
  Results viewing:                           100% of ALL outstanding balances cleared
"""

from datetime import datetime
import sqlalchemy
from models import (
    Result, Payment, FeeStructure, ResultStatus, PublicationStatus,
    ProgrammeLevel, SystemSetting
)


# ─────────────────────────── Grade scale tables ───────────────────────────
# Each entry: (low, high, letter, descriptor, gp_5pt, gp_4pt)
# Both scales stored here so switching requires only reading the right column,
# not maintaining two separate tables.

GRADE_SCALE = [
    (86, 100, "A+", "Upper Distinction",        5.0, 4.0),
    (75,  85, "A",  "Lower Distinction",         4.0, 3.5),
    (70,  74, "B+", "Meritorious",               3.0, 3.0),
    (60,  69, "B",  "Credit",                    3.0, 3.0),
    (56,  59, "C+", "Satisfactory/Definite Pass",2.0, 2.0),
    (50,  55, "C",  "Pass",                      1.0, 1.0),
    (0,   49, "F",  "Fail",                      0.0, 0.0),
]

# Pass threshold: any total_score >= this value is a pass.
PASS_THRESHOLD = 40.0
# Supplementary range: [SUPP_LOW, SUPP_HIGH) — inclusive on both ends.
SUPP_LOW = 40.0
SUPP_HIGH = 55.0


# ─────────────────────────── GPA scale helpers ───────────────────────────

def get_gpa_scale(session) -> int:
    """
    Returns the currently active GPA scale (4 or 5) from system settings.
    Defaults to 5 if the setting hasn't been created yet.
    """
    setting = session.query(SystemSetting).filter_by(key="gpa_scale").first()
    if setting is None:
        return 5
    return int(setting.value)


def set_gpa_scale(session, scale: int, user_id: int) -> None:
    """
    Sets the system-wide GPA scale (4 or 5) and triggers a full recompute
    of every stored grade_point value in the results table. This is a
    destructive batch operation — all existing grade_point values are
    overwritten. Always call within a try/except at the call site and only
    commit once all recomputes succeed.
    """
    assert scale in (4, 5), f"GPA scale must be 4 or 5, got {scale}"

    # Persist the setting
    setting = session.query(SystemSetting).filter_by(key="gpa_scale").first()
    if setting is None:
        setting = SystemSetting(key="gpa_scale")
        session.add(setting)
    setting.value = str(scale)
    setting.updated_at = datetime.utcnow()
    setting.updated_by = user_id

    # Recompute every stored grade_point to match the new scale.
    # We only touch grade_point — total_score and grade letter are
    # scale-independent and stay as-is.
    results = session.query(Result).filter(
        Result.total_score.isnot(None)
    ).all()
    for r in results:
        _, gp = compute_grade(r.total_score, scale=scale)
        r.grade_point = gp

    session.commit()


# ─────────────────────────── Core grading ─────────────────────────────────

def compute_grade(score: float, scale: int = 5):
    """
    Return (grade_letter, grade_point) for a given score under the
    requested GPA scale (4 or 5). Both are returned together so callers
    never need to look up the letter and the point separately — they always
    come from the same band row, guaranteeing consistency.

    Returns (None, None) if score is None.
    """
    if score is None:
        return None, None
    for low, high, letter, descriptor, gp_5, gp_4 in GRADE_SCALE:
        if low <= score <= high:
            gp = gp_5 if scale == 5 else gp_4
            return letter, gp
    return "F", 0.0


def compute_grade_descriptor(score: float) -> str:
    """Returns the text descriptor for a score (e.g. 'Upper Distinction')."""
    if score is None:
        return ""
    for low, high, letter, descriptor, gp_5, gp_4 in GRADE_SCALE:
        if low <= score <= high:
            return descriptor
    return "Fail"


def compute_total_score(
    ca1: float,
    ca2: float,
    mid: float,
    final: float,
    programme_level: str,
    supp: float = None,
) -> float:
    """
    Compute the weighted total score for a course result.

    Diploma / Undergraduate:
        CA1 10% + CA2 10% + Mid-Semester 20% + Final 60%

    Postgraduate:
        CA1 25% + CA2 25% + Final 50%  (mid is ignored entirely)

    programme_level: the ProgrammeLevel enum VALUE string
        ('Diploma', 'Undergraduate', 'Postgraduate')

    Supplementary rule: if a supp_score is provided and is higher than
    the raw final_score, the final component is replaced by supp_score
    (capped at 50 marks to reflect the supplementary pass ceiling of 50%).
    """
    ca1 = ca1 or 0.0
    ca2 = ca2 or 0.0
    mid = mid or 0.0
    final = final or 0.0

    # Apply supplementary score if it improves the final component
    if supp is not None and supp > final:
        final = min(float(supp), 50.0)

    if programme_level == ProgrammeLevel.POSTGRADUATE.value:
        total = (ca1 * 0.25) + (ca2 * 0.25) + (final * 0.50)
    else:
        # Diploma and Undergraduate use the same weighting
        total = (ca1 * 0.10) + (ca2 * 0.10) + (mid * 0.20) + (final * 0.60)

    return round(total, 2)


def determine_status(total: float, supp_score: float = None) -> ResultStatus:
    """
    Determine per-course result status from the computed total score.
    Pass threshold: >= 50%.
    Supplementary range: 40–55 (inclusive) — student sits a supplementary exam.
    Below 50: Fail.
    """
    if total is None:
        return ResultStatus.PENDING
    if total >= PASS_THRESHOLD:
        if SUPP_LOW <= total <= SUPP_HIGH:
            # Score in the supplementary band
            if supp_score is not None:
                # Supplementary already attempted — result is final
                return ResultStatus.PASS if supp_score >= PASS_THRESHOLD else ResultStatus.FAIL
            return ResultStatus.SUPPLEMENTARY
        return ResultStatus.PASS
    return ResultStatus.FAIL


def compute_semester_academic_status(results: list) -> str:
    """
    Given a list of Result objects for one semester, compute the overall
    academic status string for display on dashboard/result slip.
    """
    if not results:
        return "No Results"
    statuses = [r.status for r in results]
    fail_count = sum(1 for s in statuses if s == ResultStatus.FAIL)
    supp_count = sum(1 for s in statuses if s == ResultStatus.SUPPLEMENTARY)
    if fail_count >= 2:
        return "Proceed but Repeat"
    if supp_count > 0:
        return "Supplementary Required"
    if all(s == ResultStatus.PASS for s in statuses):
        return "Pass"
    return "Partial Pass"


def compute_gpa(results: list) -> float:
    """
    Compute weighted GPA from a list of Result objects. Uses whatever
    grade_point value is currently stored on each result (which already
    reflects the active GPA scale — no scale argument needed here since
    the recompute happens at the source when the scale is changed).
    """
    total_points = 0.0
    total_credits = 0
    for r in results:
        if r.grade_point is not None and r.student_course and r.student_course.course:
            credits = r.student_course.course.credits or 3
            total_points += r.grade_point * credits
            total_credits += credits
    if total_credits == 0:
        return 0.0
    return round(total_points / total_credits, 2)


def recalculate_result(result: Result, session=None) -> Result:
    """
    Recompute total_score, grade, grade_point, and status for a Result
    object in place. Requires access to the programme level via the
    result's StudentCourse → Registration → Student → Programme chain.

    If session is provided, it's used to lazy-load any unloaded
    relationships. If not, the relationships must already be loaded.
    """
    sc = result.student_course
    if sc is None:
        return result

    reg = sc.registration
    if reg is None:
        return result

    student = reg.student
    if student is None or student.programme is None:
        return result

    prog_level = student.programme.level.value if student.programme.level else ProgrammeLevel.UNDERGRADUATE.value

    total = compute_total_score(
        ca1=result.ca1_score,
        ca2=result.ca2_score,
        mid=result.mid_sem_score,
        final=result.final_score,
        programme_level=prog_level,
        supp=result.supp_score,
    )
    result.total_score = total

    # Get the current GPA scale so the stored grade_point always matches
    # the active system setting.
    scale = 5
    if session is not None:
        scale = get_gpa_scale(session)

    grade, gp = compute_grade(total, scale=scale)
    result.grade = grade
    result.grade_point = gp
    result.status = determine_status(total, result.supp_score)
    return result


# ─────────────────────────── Payment helpers ──────────────────────────────

# Standard programme duration by level — used to cap how far back/forward a
# student's fee periods extend, so balances never reach before their initial
# enrolment or beyond their programme's expected length.
MAX_YEARS_BY_LEVEL = {
    ProgrammeLevel.DIPLOMA: 3,
    ProgrammeLevel.UNDERGRADUATE: 4,
    ProgrammeLevel.POSTGRADUATE: 2,
}


def get_max_years_for_programme(programme) -> int:
    """Returns the standard duration (years) for a programme, by level."""
    if programme and programme.level in MAX_YEARS_BY_LEVEL:
        return MAX_YEARS_BY_LEVEL[programme.level]
    return programme.duration_years if programme and programme.duration_years else 4


def get_relevant_progress_steps(session, student) -> list:
    """
    Returns [(year_of_study, semester_of_study, academic_year_label), ...]
    for every step this student has actually progressed through: from their
    intake's first semester up to (and including) their current
    year_of_study/semester, capped at the programme level's standard
    duration. Returns [] if the student has no intake/progress data (e.g.
    not yet reconciled to a confirmed cohort).
    """
    from models import IntakeProgress
    if not student.intake_id or not student.programme:
        return []
    max_years = get_max_years_for_programme(student.programme)
    cur_yos = student.year_of_study or 1
    cur_sos = student.current_semester or 1
    progress_rows = session.query(IntakeProgress).filter_by(intake_id=student.intake_id).all()
    steps = []
    for p in progress_rows:
        if p.year_of_study > max_years:
            continue
        if (p.year_of_study, p.semester_of_study) > (cur_yos, cur_sos):
            continue  # haven't reached this period yet
        steps.append((p.year_of_study, p.semester_of_study, p.academic_year.label))
    return steps


def increment_academic_year_label(label: str) -> str:
    """"2025/2026" -> "2026/2027". Returns the label unchanged if it doesn't
    match the expected YYYY/YYYY format."""
    try:
        start, end = label.split("/")
        return f"{int(start) + 1}/{int(end) + 1}"
    except (ValueError, AttributeError):
        return label


def get_next_semester_step(session, student):
    """
    Returns (year_of_study, semester_of_study, academic_year_label) for the
    student's NEXT semester after their current one, capped at their
    programme's standard duration. Returns None if they're already at
    their final semester (nothing further to roll a payment into) or have
    no intake/progress data at all.

    If that step already has a recorded IntakeProgress mapping (the cohort
    has been promoted that far), uses its academic year. Otherwise PROJECTS
    the academic year forward using the institution's established
    convention: semester 1 -> 2 stays within the same academic year;
    semester 2 -> next year's semester 1 moves to the next academic year.
    This projection may differ from what's eventually set when the cohort
    is actually promoted — it's a best-effort estimate for holding an
    advance payment, not a substitute for Promote Cohort.
    """
    from models import IntakeProgress
    if not student.intake_id or not student.programme:
        return None
    max_years = get_max_years_for_programme(student.programme)
    cur_yos = student.year_of_study or 1
    cur_sos = student.current_semester or 1

    next_yos, next_sos = (cur_yos, 2) if cur_sos == 1 else (cur_yos + 1, 1)
    if next_yos > max_years:
        return None  # already at their final semester

    progress = session.query(IntakeProgress).filter_by(
        intake_id=student.intake_id, year_of_study=next_yos, semester_of_study=next_sos
    ).first()
    if progress:
        return (next_yos, next_sos, progress.academic_year.label)

    current_progress = session.query(IntakeProgress).filter_by(
        intake_id=student.intake_id, year_of_study=cur_yos, semester_of_study=cur_sos
    ).first()
    if not current_progress:
        return None  # no current mapping to project forward from

    current_ay = current_progress.academic_year.label
    next_ay = current_ay if cur_sos == 1 else increment_academic_year_label(current_ay)
    return (next_yos, next_sos, next_ay)


def get_relevant_fee_periods(session, student) -> list:
    """
    Returns [(academic_year_label, semester), ...] for every period this
    student has actually progressed through — see get_relevant_progress_steps.
    This is what bounds balance calculations to their real enrolment window
    — never before their initial enrolment, never beyond their programme's
    expected length. Returns [] if the student has no intake/progress data
    (e.g. not yet reconciled to a confirmed cohort) — callers should fall
    back to the programme-wide fee set in that case.
    """
    return [(ay, sos) for _, sos, ay in get_relevant_progress_steps(session, student)]


def allocate_payment(
    session, student, amount: float, method: str = None,
    reference: str = None, received_by: int = None, notes: str = None,
) -> dict:
    """
    Allocates a payment across the student's outstanding periods, oldest
    unpaid first, never letting any single semester's recorded payments
    exceed that semester's fee. Creates one Payment row per period actually
    touched (skips periods already fully paid).

    Falls back to the student's single stored (academic_year, current_semester)
    when there's no intake/progress history (e.g. "Unconfirmed" students).

    If there's still money left after clearing every known due, it's
    applied as an ADVANCE toward the student's nearest future semester
    (get_next_semester_step) rather than rejected outright — capped at
    that semester's fee if a FeeStructure already exists for it, so a
    future period can't be overpaid either. Only genuinely excess money
    (beyond even that one extra semester, or when there's no further
    semester to roll into — e.g. their final semester) is reported back
    as unallocated and NOT recorded, so money is never silently lost or
    misattributed.

    Returns {
        "payments_created": [Payment, ...],
        "allocated": float,       # total amount successfully applied
        "advance": float,         # portion of "allocated" that went to a
                                   # future (not-yet-current) semester
        "advance_period": tuple or None,  # (academic_year, semester) the
                                           # advance was applied to
        "unallocated": float,     # genuine leftover — NOT recorded.
    }
    """
    periods = get_relevant_fee_periods(session, student)
    if not periods and student.academic_year:
        periods = [(student.academic_year, student.current_semester or 1)]

    remaining = amount
    payments_created = []
    # Student.fee_adjustment is a single lump scholarship/discount (negative)
    # or surcharge (positive) vs the shared fee structure — it isn't tied to
    # a specific period. It's applied entirely against the LAST (most
    # recent/current) period, consistent with how it was originally
    # calibrated: earlier periods are filled to their flat fee first, so any
    # mismatch between the flat total and the student's true total always
    # surfaces at whichever period was current at calibration time.
    fee_adjustment = student.fee_adjustment or 0.0
    last_period_index = len(periods) - 1

    for idx, (ay_label, sem) in enumerate(periods):
        if remaining <= 0:
            break
        fs = session.query(FeeStructure).filter_by(
            programme_id=student.programme_id, academic_year=ay_label,
            semester=sem, mode_of_study=student.mode_of_study,
        ).first()
        if not fs or fs.total_fee <= 0:
            continue

        effective_fee = fs.total_fee + (fee_adjustment if idx == last_period_index else 0.0)
        already_paid = session.query(sqlalchemy.func.sum(Payment.amount)).filter_by(
            student_id=student.id, academic_year=ay_label, semester=sem
        ).scalar() or 0.0
        remaining_for_period = effective_fee - already_paid
        if remaining_for_period <= 0:
            continue  # this period is already fully paid — never push it over

        apply_amt = min(remaining, remaining_for_period)
        p = Payment(
            student_id=student.id, academic_year=ay_label, semester=sem,
            amount=round(apply_amt, 2), method=method, reference=reference,
            received_by=received_by, notes=notes,
        )
        session.add(p)
        payments_created.append(p)
        remaining -= apply_amt

    advance_amount = 0.0
    advance_period = None
    if remaining > 0:
        next_step = get_next_semester_step(session, student)
        if next_step:
            next_yos, next_sos, next_ay_label = next_step
            from models import AcademicYear
            ay_row = session.query(AcademicYear).filter_by(label=next_ay_label).first()
            if ay_row is None:
                ay_row = AcademicYear(label=next_ay_label)
                session.add(ay_row)
                session.flush()

            fs = session.query(FeeStructure).filter_by(
                programme_id=student.programme_id, academic_year=next_ay_label,
                semester=next_sos, mode_of_study=student.mode_of_study,
            ).first()
            already_paid_next = session.query(sqlalchemy.func.sum(Payment.amount)).filter_by(
                student_id=student.id, academic_year=next_ay_label, semester=next_sos
            ).scalar() or 0.0
            cap = (fs.total_fee - already_paid_next) if fs else remaining
            apply_amt = min(remaining, cap) if cap is not None else remaining
            if apply_amt > 0:
                p = Payment(
                    student_id=student.id, academic_year=next_ay_label, semester=next_sos,
                    amount=round(apply_amt, 2), method=method, reference=reference,
                    received_by=received_by,
                    notes=(f"{notes} — " if notes else "") + (
                        f"Advance toward Year {next_yos} Semester {next_sos} "
                        f"({next_ay_label}), ahead of the student's current semester."
                    ),
                )
                session.add(p)
                payments_created.append(p)
                advance_amount = round(apply_amt, 2)
                advance_period = (next_ay_label, next_sos)
                remaining -= apply_amt

    return {
        "payments_created": payments_created,
        "allocated": round(amount - remaining, 2),
        "advance": advance_amount,
        "advance_period": advance_period,
        "unallocated": round(max(0.0, remaining), 2),
    }


def get_payment_percentage(session, student_id: int, academic_year: str, semester: int) -> float:
    """Returns fraction (0.0–1.0) of the semester fee paid, scoped to student's mode_of_study."""
    from models import Student
    student = session.query(Student).get(student_id)
    if not student:
        return 0.0

    fee_struct = session.query(FeeStructure).filter_by(
        programme_id=student.programme_id,
        academic_year=academic_year,
        semester=semester,
        mode_of_study=student.mode_of_study,
    ).first()

    if not fee_struct or fee_struct.total_fee == 0:
        return 1.0  # No fee structure → treat as fully paid

    total_paid = session.query(Payment).filter_by(
        student_id=student_id,
        academic_year=academic_year,
        semester=semester
    ).with_entities(sqlalchemy.func.sum(Payment.amount)).scalar() or 0.0

    return total_paid / fee_struct.total_fee


def get_cumulative_balance(session, student_id: int) -> tuple:
    """
    Returns (total_fees, total_paid, outstanding) across every period this
    student has actually progressed through (bounded by their intake and
    programme duration via get_relevant_fee_periods — never before their
    initial enrolment, never beyond their programme's expected length).
    total_paid is summed globally (not per-period) so a surplus in one
    semester automatically nets against a deficit in another rather than
    sitting idle — i.e. an overpayment "transfers" to cover prior dues.
    Falls back to the full programme-wide fee set if the student has no
    intake/progress data yet (not reconciled to a confirmed cohort).
    """
    from models import Student
    student = session.query(Student).get(student_id)
    if not student:
        return 0.0, 0.0, 0.0

    periods = get_relevant_fee_periods(session, student)
    if periods:
        total_fees = 0.0
        for ay_label, sem in periods:
            fs = session.query(FeeStructure).filter_by(
                programme_id=student.programme_id, academic_year=ay_label,
                semester=sem, mode_of_study=student.mode_of_study,
            ).first()
            if fs:
                total_fees += fs.total_fee
    else:
        fee_structs = session.query(FeeStructure).filter_by(
            programme_id=student.programme_id,
            mode_of_study=student.mode_of_study,
        ).all()
        total_fees = sum(f.total_fee for f in fee_structs)

    # Apply any individual scholarship/discount or additional-charge
    # adjustment that doesn't fit the shared fee structure (e.g. a
    # registrar-recorded scholarship). Positive = charged more, negative =
    # discount.
    total_fees += student.fee_adjustment or 0.0

    total_paid = (
        session.query(sqlalchemy.func.sum(Payment.amount))
        .filter_by(student_id=student_id)
        .scalar() or 0.0
    )
    return total_fees, total_paid, max(0.0, total_fees - total_paid)


def has_outstanding_balance(
    session,
    student_id: int,
    current_academic_year: str = None,
    current_semester: int = None
) -> tuple:
    """
    Returns (has_balance, total_outstanding).
    True means student owes money from any PREVIOUS semester or academic
    year (the current_academic_year/current_semester period is excluded —
    that one is checked separately via get_payment_percentage/can_register).

    Periods considered are bounded to the student's actual progression
    (get_relevant_fee_periods) so this never reaches before their initial
    enrolment or past their programme's expected duration. Fee and paid
    amounts are netted per-period across that bounded set, so a surplus
    (overpayment) in one past semester transfers to cover a deficit in
    another past semester instead of being ignored.
    """
    from models import Student

    student = session.query(Student).get(student_id)
    if not student:
        return False, 0.0

    periods = get_relevant_fee_periods(session, student)
    if not periods:
        fee_structures = session.query(FeeStructure).filter_by(
            programme_id=student.programme_id,
            mode_of_study=student.mode_of_study,
        ).all()
        periods = [(f.academic_year, f.semester) for f in fee_structures]

    total_fees = 0.0
    total_paid = 0.0
    for ay_label, sem in periods:
        if (
            current_academic_year is not None
            and ay_label == current_academic_year
            and sem == current_semester
        ):
            continue  # current period — gated separately

        fs = session.query(FeeStructure).filter_by(
            programme_id=student.programme_id, academic_year=ay_label,
            semester=sem, mode_of_study=student.mode_of_study,
        ).first()
        if not fs:
            continue
        total_fees += fs.total_fee
        total_paid += sum(
            p.amount
            for p in session.query(Payment).filter_by(
                student_id=student_id, academic_year=ay_label, semester=sem
            ).all()
        )

    # Apply the student's individual fee adjustment (scholarship/discount or
    # additional charge) against the past-periods total — same lump-sum
    # treatment as get_cumulative_balance.
    total_fees += student.fee_adjustment or 0.0

    outstanding = total_fees - total_paid
    return outstanding > 0, round(max(0.0, outstanding), 2)


def is_past_semester(session, academic_year: str, semester: int) -> bool:
    """
    Returns True if the given year/semester is definitively in the past.
    Logic: if registration is currently open for a later period, this one is past.
    Falls back to calendar year comparison when no open period exists.
    """
    from models import RegistrationPeriod
    current = session.query(RegistrationPeriod).filter_by(
        academic_year=academic_year, semester=semester, is_open=True
    ).first()
    if current:
        return False
    try:
        q_start = int(academic_year.split("/")[0])
    except (IndexError, ValueError):
        return False
    open_periods = session.query(RegistrationPeriod).filter_by(is_open=True).all()
    for op in open_periods:
        try:
            op_start = int(op.academic_year.split("/")[0])
        except (IndexError, ValueError):
            continue
        if op_start > q_start:
            return True
        if op_start == q_start and op.semester > semester:
            return True
    try:
        end_year = int(academic_year.split("/")[1])
    except (IndexError, ValueError):
        return False
    now = datetime.utcnow()
    if end_year < now.year:
        return True
    if end_year == now.year and semester == 1 and now.month > 3:
        return True
    return False


def can_view_results(session, student_id: int, academic_year: str = None, semester: int = None, exam_type: str = None) -> tuple:
    """
    Returns (can_view: bool, reason: str).
    Gate: 100% of ALL outstanding balances across all semesters must be cleared.
    The academic_year/semester/exam_type arguments are accepted for API
    compatibility but do not affect the gate threshold.
    """
    total_fees, total_paid, outstanding = get_cumulative_balance(session, student_id)
    if total_fees == 0:
        return True, "No fee structures on record — access granted."
    if outstanding <= 0:
        return True, f"All fees cleared (K{total_paid:,.2f} paid)."
    return False, (
        f"Results withheld. Outstanding balance: K{outstanding:,.2f} "
        f"(K{total_paid:,.2f} paid of K{total_fees:,.2f} total). "
        f"All outstanding fees must be cleared before results can be viewed. "
        f"Please visit the Finance Office."
    )


def can_register(
    session,
    student_id: int,
    academic_year: str,
    semester: int,
    is_past: bool = False,
) -> tuple:
    """
    Registration policy:
    1. Past semesters (backdating): no gate at all.
    2. Current/future semesters:
       a. No outstanding balances from previous semesters.
       b. At least 25% payment for the current semester.
    """
    if is_past:
        return True, "Backdating — no payment gate for past semesters."

    has_balance, outstanding = has_outstanding_balance(
        session, student_id, academic_year, semester
    )
    if has_balance:
        return False, (
            f"You have an outstanding balance of K{outstanding:,.2f} from "
            f"previous semester(s). All previous balances must be cleared "
            f"before registration."
        )

    pct = get_payment_percentage(session, student_id, academic_year, semester)
    if pct >= 0.25:
        return True, f"Registration payment requirement met ({pct * 100:.1f}%)."

    return False, (
        f"You have paid only {pct * 100:.1f}% of current semester fees. "
        f"A minimum of 25% is required before registration."
    )


def is_registration_open(session, academic_year: str, semester: int) -> bool:
    """
    Returns True only if the Registrar/Admin has explicitly opened
    self-service registration for this academic year + semester, AND
    (if a deadline was set) the deadline hasn't passed. The Registrar can
    set deadline_at once and not have to remember to manually close it —
    is_open stays True for record-keeping, but the gate respects the
    deadline automatically.
    """
    from models import RegistrationPeriod
    period = session.query(RegistrationPeriod).filter_by(
        academic_year=academic_year, semester=semester
    ).first()
    if not period or not period.is_open:
        return False
    if period.deadline_at and datetime.utcnow() > period.deadline_at:
        return False
    return True


def course_matches_semester(course_semester: int, target_semester: int) -> bool:
    """
    Shared helper for the semester=0 'both semesters' elective sentinel.
    Returns True if the course applies to the target semester (exact match
    or semester=0 meaning 'offered either semester').
    """
    return course_semester == target_semester or course_semester == 0


# ─────────────────────────── Intake / cohort helpers ───────────────────────

def get_academic_year_for_progress(session, intake_id: int, year_of_study: int, semester_of_study: int):
    """
    Returns the AcademicYear.label for a cohort's (year_of_study, semester)
    step, looked up from IntakeProgress — the canonical, Registrar-set
    mapping. Returns None if that step hasn't been recorded yet.
    """
    from models import IntakeProgress
    progress = session.query(IntakeProgress).filter_by(
        intake_id=intake_id, year_of_study=year_of_study, semester_of_study=semester_of_study
    ).first()
    return progress.academic_year.label if progress else None


def _ensure_registration_and_enrolment(
    session, student, year_of_study: int, semester_of_study: int,
    academic_year_label: str, user_id: int
) -> tuple:
    """
    Shared step logic: ensures a Registration exists for this student/period,
    and that every active course matching their programme/year/semester has
    a StudentCourse row. Returns (registration_created: bool, enrolments_created: int).
    """
    from models import Registration, StudentCourse, Course, EnrolmentStatus

    reg = session.query(Registration).filter_by(
        student_id=student.id, academic_year=academic_year_label, semester=semester_of_study
    ).first()
    registration_created = False
    if reg is None:
        reg = Registration(
            student_id=student.id, academic_year=academic_year_label,
            semester=semester_of_study, year_of_study=year_of_study,
            status=EnrolmentStatus.ENROLLED, registered_by=user_id,
        )
        session.add(reg)
        session.flush()
        registration_created = True

    enrolments_created = 0
    eligible_courses = session.query(Course).filter(
        Course.programme_id == student.programme_id,
        Course.year_level == year_of_study,
        Course.is_active == True,
    ).all()
    for c in eligible_courses:
        if not course_matches_semester(c.semester, semester_of_study):
            continue
        sc_exists = session.query(StudentCourse).filter_by(
            registration_id=reg.id, course_id=c.id
        ).first()
        if sc_exists is None:
            session.add(StudentCourse(registration_id=reg.id, course_id=c.id))
            enrolments_created += 1

    return registration_created, enrolments_created


def promote_cohort(session, intake_id: int, year_of_study: int, semester_of_study: int,
                    academic_year_id: int, user_id: int, backfill_courses: bool = True) -> dict:
    """
    Promotes every ACTIVE student in an intake to (year_of_study, semester_of_study):
    1. Records/updates the IntakeProgress mapping for this cohort-step.
    2. Bulk-updates Student.year_of_study/current_semester for the intake.
    3. Auto-enrols every eligible student into the matching courses for that
       step (Registration + StudentCourse), so results entry and self-service
       registration both have something to work with immediately — this is
       what removes the need for manual enrolment after a bulk upload.

    Returns a summary dict: {students_promoted, registrations_created, enrolments_created}.
    """
    from models import Student, IntakeProgress, StudentStatus

    # Unset is_current on whichever step was previously current for this
    # intake — otherwise after promotion the OLD step would still show as
    # current alongside (or instead of) the new one.
    session.query(IntakeProgress).filter_by(
        intake_id=intake_id, is_current=True
    ).update({"is_current": False})

    progress = session.query(IntakeProgress).filter_by(
        intake_id=intake_id, year_of_study=year_of_study, semester_of_study=semester_of_study
    ).first()
    if progress is None:
        progress = IntakeProgress(
            intake_id=intake_id, year_of_study=year_of_study,
            semester_of_study=semester_of_study, academic_year_id=academic_year_id,
            is_current=True,
        )
        session.add(progress)
    else:
        progress.academic_year_id = academic_year_id
        progress.is_current = True
    session.flush()

    academic_year_label = progress.academic_year.label

    students = session.query(Student).filter_by(
        intake_id=intake_id, status=StudentStatus.ACTIVE
    ).all()

    students_promoted = 0
    registrations_created = 0
    enrolments_created = 0

    for s in students:
        s.year_of_study = year_of_study
        s.current_semester = semester_of_study
        students_promoted += 1

        if not backfill_courses:
            continue

        reg_created, enr_count = _ensure_registration_and_enrolment(
            session, s, year_of_study, semester_of_study, academic_year_label, user_id
        )
        registrations_created += int(reg_created)
        enrolments_created += enr_count

    session.commit()
    return {
        "students_promoted": students_promoted,
        "registrations_created": registrations_created,
        "enrolments_created": enrolments_created,
    }


def backfill_student_enrolment(session, student, user_id: int) -> dict:
    """
    Ensures a student has a Registration + StudentCourse rows for EVERY
    period they've progressed through so far — past and current — not just
    their current one. Uses their intake's progress history when available;
    falls back to just their current (year_of_study, current_semester) using
    their stored academic_year for students without intake/progress data
    (e.g. the "Unconfirmed" bucket).

    Returns {registrations_created, enrolments_created, steps_processed}.
    """
    steps = get_relevant_progress_steps(session, student)
    if not steps:
        if student.academic_year:
            steps = [(student.year_of_study or 1, student.current_semester or 1, student.academic_year)]
        else:
            steps = []

    registrations_created = 0
    enrolments_created = 0
    for year_of_study, semester_of_study, academic_year_label in steps:
        reg_created, enr_count = _ensure_registration_and_enrolment(
            session, student, year_of_study, semester_of_study, academic_year_label, user_id
        )
        registrations_created += int(reg_created)
        enrolments_created += enr_count

    return {
        "registrations_created": registrations_created,
        "enrolments_created": enrolments_created,
        "steps_processed": len(steps),
    }


def backfill_all_enrolment(session, user_id: int, intake_id: int = None) -> dict:
    """
    Runs backfill_student_enrolment for every ACTIVE student (optionally
    scoped to one intake). Commits once at the end. Returns a summary dict:
    {students_processed, registrations_created, enrolments_created}.
    """
    from models import Student, StudentStatus

    query = session.query(Student).filter_by(status=StudentStatus.ACTIVE)
    if intake_id is not None:
        query = query.filter_by(intake_id=intake_id)
    students = query.all()

    students_processed = 0
    registrations_created = 0
    enrolments_created = 0
    for s in students:
        result = backfill_student_enrolment(session, s, user_id)
        if result["steps_processed"] > 0:
            students_processed += 1
        registrations_created += result["registrations_created"]
        enrolments_created += result["enrolments_created"]

    session.commit()
    return {
        "students_processed": students_processed,
        "registrations_created": registrations_created,
        "enrolments_created": enrolments_created,
    }
