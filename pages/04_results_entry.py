"""
Results Entry — University of Edenberg SIS

Lecturers/coordinators enter CA1, CA2, Mid-Semester, Final, and
Supplementary scores here. The Registrar then publishes from
pages/05_results_publish.py.

Weighting adapts automatically to the programme's level:
  Diploma / Undergraduate: CA1 10% + CA2 10% + Mid-Sem 20% + Final 60%
  Postgraduate:            CA1 25% + CA2 25% + Final 50%

Bulk upload supports both .csv and .xlsx files.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login, log_action
from utils.ui import render_sidebar, page_header
from utils.results_logic import (
    recalculate_result, compute_semester_academic_status,
    course_matches_semester, get_gpa_scale
)
from models import (
    Student, Course, Registration, StudentCourse, Result,
    Programme, ProgrammeLevel, ResultStatus, PublicationStatus, UserRole,
    StudentStatus, EnrolmentStatus, AcademicYear, Exemption
)
from datetime import datetime
import pandas as pd
import io

st.set_page_config(page_title="Results Entry — UoE SIS", layout="wide")
require_login()
render_sidebar()
page_header("Results Entry", "Enter and manage student examination scores")

user = st.session_state.user
role = user["role"]

if role not in (UserRole.ADMIN.value, UserRole.REGISTRAR.value, UserRole.LECTURER.value):
    st.error("Access restricted to academic staff.")
    st.stop()

db = get_db()
gpa_scale = get_gpa_scale(db)

# ── Guard: no programmes set up yet ──────────────────────────
_all_progs = db.query(Programme).filter_by(is_active=True).all()
if not _all_progs:
    st.info("No programmes have been set up yet. Go to Settings → Programmes to add them.")
    db.close()
    st.stop()

# ── Filters ───────────────────────────────────────────────────
_academic_years = db.query(AcademicYear).filter_by(is_active=True).order_by(AcademicYear.label).all()
col1, col2, col3 = st.columns(3)
with col1:
    academic_year = (
        st.selectbox("Academic Year", [ay.label for ay in _academic_years])
        if _academic_years else st.text_input("Academic Year", "2025/2026")
    )
with col2:
    semester = st.selectbox("Semester", [1, 2])
with col3:
    programmes = _all_progs
    prog_options = {p.name: p.id for p in programmes}
    prog_sel = st.selectbox("Programme", list(prog_options.keys()))

prog_id = prog_options[prog_sel]
prog_obj = next(p for p in programmes if p.id == prog_id)
is_postgrad = (prog_obj.level == ProgrammeLevel.POSTGRADUATE)

# Weighting caption adapts to programme level
if is_postgrad:
    weight_caption = "Weighting: CA1 25% | CA2 25% | Final 50%"
else:
    weight_caption = "Weighting: CA1 10% | CA2 10% | Mid-Semester 20% | Final 60%"

# ── Course selection ──────────────────────────────────────────
all_prog_courses = db.query(Course).filter_by(
    programme_id=prog_id, is_active=True
).order_by(Course.code).all()
sem_courses = [c for c in all_prog_courses if course_matches_semester(c.semester, semester)]

if not sem_courses:
    st.info("No courses found for the selected programme and semester.")
    db.close()
    st.stop()

# Year of Study filter — narrows the course list, since cohorts at
# different intakes now sit at different years within the same programme.
available_years = sorted({c.year_level for c in sem_courses})
year_filter_sel = st.selectbox("Year of Study", available_years, key="results_year_filter")
courses = [c for c in sem_courses if c.year_level == year_filter_sel]

if not courses:
    st.info("No courses found for the selected programme, semester, and year of study.")
    db.close()
    st.stop()

course_options = {f"{c.code} — {c.name}": c.id for c in courses}
course_sel = st.selectbox("Select Course", list(course_options.keys()))
course_id = course_options[course_sel]
course_obj = next(c for c in courses if c.id == course_id)

st.markdown("---")
st.subheader(f"Results: {course_obj.code} — {course_obj.name}")
st.caption(weight_caption)

# ── Auto-enrol eligible students into this course ─────────────
# Students bulk-uploaded via ETL are assigned a programme directly from
# their programme_code column, but may never have gone through
# self-service course registration (registration is restricted to its
# own period — see pages/03_registration.py). Results entry shouldn't be
# blocked by that: any ACTIVE student whose stored programme_id/year_of_study
# matches this course is auto-enrolled (Registration + StudentCourse) the
# first time results are touched for this academic_year/semester/course.
eligible_students = db.query(Student).filter_by(
    programme_id=prog_id,
    year_of_study=course_obj.year_level,
    status=StudentStatus.ACTIVE,
).all()

for s in eligible_students:
    reg = db.query(Registration).filter_by(
        student_id=s.id, academic_year=academic_year, semester=semester
    ).first()
    if reg is None:
        reg = Registration(
            student_id=s.id,
            academic_year=academic_year,
            semester=semester,
            year_of_study=s.year_of_study,
            status=EnrolmentStatus.ENROLLED,
            registered_by=user["id"],
        )
        db.add(reg)
        db.flush()
    sc_exists = db.query(StudentCourse).filter_by(
        registration_id=reg.id, course_id=course_id
    ).first()
    if sc_exists is None:
        db.add(StudentCourse(registration_id=reg.id, course_id=course_id))
if eligible_students:
    db.commit()

# ── Load enrollments for this course ─────────────────────────
scs = (
    db.query(StudentCourse)
    .join(Registration)
    .filter(
        StudentCourse.course_id == course_id,
        Registration.academic_year == academic_year,
        Registration.semester == semester,
    )
    .all()
)

if not scs:
    st.info(
        "No students found for this programme/year/semester combination. "
        "Check that students have been imported with the correct programme_code "
        "and year_of_study."
    )
    db.close()
    st.stop()

st.info(f"{len(scs)} student(s) enrolled. Scores are out of 100.")

# ── Current results table ─────────────────────────────────────
rows = []
for sc in scs:
    r = sc.result
    exemption = sc.exemption
    student = sc.registration.student
    row = {
        "_sc_id": sc.id,
        "Student #": student.student_number,
        "Name": student.full_name,
        "CA1": r.ca1_score if r and r.ca1_score is not None else None,
        "CA2": r.ca2_score if r and r.ca2_score is not None else None,
        "Total CA": None,
        "Final": r.final_score if r and r.final_score is not None else None,
        "Supp": r.supp_score if r and r.supp_score is not None else None,
        "Total": r.total_score if r else None,
        "Grade": r.grade if r else "",
        "Status": "Exempted" if exemption else (r.status.value if r else "Pending"),
        "Published": r.publication_status.value if r else "Draft",
    }
    # Compute rolled-up Total CA for display
    ca1 = r.ca1_score or 0.0 if r else 0.0
    ca2 = r.ca2_score or 0.0 if r else 0.0
    mid = r.mid_sem_score or 0.0 if r else 0.0
    row["Total CA"] = round(ca1 + ca2 + (0 if is_postgrad else mid), 2) if r else None
    rows.append(row)

df = pd.DataFrame(rows)

if is_postgrad:
    display_cols = ["Student #", "Name", "CA1", "CA2", "Total CA", "Final", "Supp", "Total", "Grade", "Status", "Published"]
else:
    display_cols = ["Student #", "Name", "CA1", "CA2", "Total CA", "Final", "Supp", "Total", "Grade", "Status", "Published"]

st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

# ── Exemptions ──────────────────────────────────────────────────
st.markdown("---")
st.subheader("Exempt a Student from This Course")
st.caption(
    "Marks the course as waived rather than sat. Excluded from GPA and "
    "from total credits required; shown as 'EXEMPTED' on result slips/transcripts."
)
ex_col1, ex_col2 = st.columns([2, 3])
with ex_col1:
    ex_snum = st.text_input("Student Number to Exempt", key="exempt_snum")
with ex_col2:
    ex_reason = st.text_input("Reason", key="exempt_reason", placeholder="e.g. Credit transfer from prior qualification")

if ex_snum:
    ex_match = next((r for r in rows if r["Student #"] == ex_snum.strip()), None)
    if not ex_match:
        st.error("Student not found in this course.")
    else:
        ex_sc = db.query(StudentCourse).get(ex_match["_sc_id"])
        if ex_sc.exemption:
            st.warning(f"{ex_match['Name']} is already exempted from this course.")
            if st.button("Remove Exemption", key="remove_exempt"):
                db.delete(ex_sc.exemption)
                db.commit()
                log_action(db, "REMOVE_EXEMPTION", "StudentCourse", ex_sc.id,
                           f"{ex_snum} {course_obj.code}")
                st.success("Exemption removed.")
                st.rerun()
        elif ex_sc.result is not None:
            st.error(
                f"{ex_match['Name']} already has scores recorded for this course. "
                f"Clear the result first if this should be an exemption instead."
            )
        else:
            if st.button("Grant Exemption", type="primary", key="grant_exempt"):
                if not ex_reason.strip():
                    st.error("A reason is required.")
                else:
                    db.add(Exemption(
                        student_course_id=ex_sc.id,
                        reason=ex_reason.strip(),
                        granted_by=user["id"],
                    ))
                    db.commit()
                    log_action(db, "GRANT_EXEMPTION", "StudentCourse", ex_sc.id,
                               f"{ex_snum} {course_obj.code}: {ex_reason.strip()}")
                    st.success(f"{ex_match['Name']} exempted from {course_obj.code}.")
                    st.rerun()

# ── Individual score entry ────────────────────────────────────
st.markdown("---")
st.subheader("Enter / Update Scores")

snum_input = st.text_input("Student Number to Update")
if snum_input:
    match = next((r for r in rows if r["Student #"] == snum_input.strip()), None)
    if not match:
        st.error("Student not found in this course.")
    elif match["Status"] == "Exempted":
        st.warning(
            f"{match['Name']} is exempted from this course — no scores to enter. "
            f"Remove the exemption in the section above first if this was a mistake."
        )
    else:
        sc_id = match["_sc_id"]
        sc_obj = db.query(StudentCourse).get(sc_id)
        result_obj = sc_obj.result

        st.markdown(f"**{match['Name']}** — {match['Student #']}")

        # Score inputs — Mid-Semester only shown for Diploma/Undergrad
        if is_postgrad:
            c1, c2, c3, c4 = st.columns(4)
        else:
            c1, c2, c3, c4, c5 = st.columns(5)

        with c1:
            ca1 = st.number_input(
                "CA1 (0–100)", 0.0, 100.0,
                value=float(result_obj.ca1_score) if result_obj and result_obj.ca1_score else 0.0,
                step=0.5, key="ca1_in"
            )
        with c2:
            ca2 = st.number_input(
                "CA2 (0–100)", 0.0, 100.0,
                value=float(result_obj.ca2_score) if result_obj and result_obj.ca2_score else 0.0,
                step=0.5, key="ca2_in"
            )
        if not is_postgrad:
            with c3:
                mid = st.number_input(
                    "Mid-Sem (0–100)", 0.0, 100.0,
                    value=float(result_obj.mid_sem_score) if result_obj and result_obj.mid_sem_score else 0.0,
                    step=0.5, key="mid_in"
                )
            with c4:
                final = st.number_input(
                    "Final (0–100)", 0.0, 100.0,
                    value=float(result_obj.final_score) if result_obj and result_obj.final_score else 0.0,
                    step=0.5, key="fin_in"
                )
            with c5:
                supp = st.number_input(
                    "Supp (0–100, 0=none)", 0.0, 100.0,
                    value=float(result_obj.supp_score) if result_obj and result_obj.supp_score else 0.0,
                    step=0.5, key="sup_in"
                )
        else:
            mid = 0.0
            with c3:
                final = st.number_input(
                    "Final (0–100)", 0.0, 100.0,
                    value=float(result_obj.final_score) if result_obj and result_obj.final_score else 0.0,
                    step=0.5, key="fin_in"
                )
            with c4:
                supp = st.number_input(
                    "Supp (0–100, 0=none)", 0.0, 100.0,
                    value=float(result_obj.supp_score) if result_obj and result_obj.supp_score else 0.0,
                    step=0.5, key="sup_in"
                )

        supp_val = supp if supp > 0 else None

        if st.button("Save Score", type="primary"):
            if result_obj is None:
                result_obj = Result(student_course_id=sc_id, entered_by=user["id"])
                db.add(result_obj)
                db.flush()

            result_obj.ca1_score = ca1
            result_obj.ca2_score = ca2
            result_obj.mid_sem_score = mid if not is_postgrad else None
            result_obj.final_score = final
            result_obj.supp_score = supp_val
            result_obj.updated_at = datetime.utcnow()
            result_obj.publication_status = PublicationStatus.DRAFT
            recalculate_result(result_obj, session=db)
            db.commit()
            log_action(db, "ENTER_RESULT", "Result", result_obj.id,
                       f"{snum_input} {course_obj.code}")
            st.success(
                f"Saved — Total: {result_obj.total_score:.1f}, "
                f"Grade: {result_obj.grade}, "
                f"Status: {result_obj.status.value}"
            )
            st.rerun()

# ── Bulk upload (.csv or .xlsx) ───────────────────────────────
st.markdown("---")
st.subheader("Bulk Upload Scores")

if is_postgrad:
    template_caption = (
        "File must have columns: student_number, ca1_score, ca2_score, "
        "final_score. Optional: supp_score. "
        "(mid_sem_score is ignored for Postgraduate programmes.)"
    )
    required_cols = {"student_number", "ca1_score", "ca2_score", "final_score"}
else:
    template_caption = (
        "File must have columns: student_number, ca1_score, ca2_score, "
        "mid_sem_score, final_score. Optional: supp_score."
    )
    required_cols = {"student_number", "ca1_score", "ca2_score", "mid_sem_score", "final_score"}

st.caption(template_caption)

uploaded = st.file_uploader(
    "Upload Results File",
    type=["csv", "xlsx"],
    key="bulk_upload"
)

if uploaded:
    fname = uploaded.name.lower()
    raw = uploaded.read()
    try:
        if fname.endswith(".xlsx"):
            df_up = pd.read_excel(io.BytesIO(raw))
        else:
            df_up = pd.read_csv(io.BytesIO(raw))
    except Exception as e:
        st.error(f"Could not read file: {e}")
        df_up = None

    if df_up is not None:
        df_up.columns = [c.lower().strip() for c in df_up.columns]
        missing = required_cols - set(df_up.columns)
        if missing:
            st.error(f"Missing required columns: {missing}")
        else:
            st.dataframe(df_up.head(5), use_container_width=True)
            st.caption(f"{len(df_up)} row(s) in file. Preview shows first 5.")

            if st.button("Run Bulk Upload", type="primary"):
                updated, errors = 0, []
                for _, row in df_up.iterrows():
                    snum = str(row.get("student_number", "")).strip()
                    sc_match = next(
                        (s for s in scs if s.registration.student.student_number == snum),
                        None
                    )
                    if not sc_match:
                        errors.append(f"{snum}: not enrolled in this course")
                        continue
                    if sc_match.exemption:
                        errors.append(f"{snum}: exempted from this course — scores skipped")
                        continue

                    r = sc_match.result
                    if r is None:
                        r = Result(
                            student_course_id=sc_match.id,
                            entered_by=user["id"]
                        )
                        db.add(r)
                        db.flush()

                    def safe_float(val):
                        try:
                            v = float(val)
                            return v if str(val).strip() not in ("", "nan") else None
                        except (TypeError, ValueError):
                            return None

                    r.ca1_score = safe_float(row.get("ca1_score")) or 0.0
                    r.ca2_score = safe_float(row.get("ca2_score")) or 0.0
                    r.mid_sem_score = (
                        safe_float(row.get("mid_sem_score")) or 0.0
                        if not is_postgrad else None
                    )
                    r.final_score = safe_float(row.get("final_score")) or 0.0
                    r.supp_score = safe_float(row.get("supp_score"))
                    r.publication_status = PublicationStatus.DRAFT
                    r.updated_at = datetime.utcnow()
                    recalculate_result(r, session=db)
                    updated += 1

                db.commit()
                log_action(
                    db, "BULK_UPLOAD_RESULTS", "Course", course_obj.id,
                    f"{updated} results uploaded for {course_obj.code}"
                )
                st.success(f"✅ {updated} record(s) uploaded and calculated.")
                if errors:
                    with st.expander(f"{len(errors)} error(s)"):
                        for e in errors:
                            st.warning(e)
                st.rerun()

db.close()
