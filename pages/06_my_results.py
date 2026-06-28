"""
My Results — University of Edenberg SIS
Student-facing page. Results visibility is payment-gated:
  Registration / Mid-Semester: requires 40% of semester fee paid
  Final: requires 70% of semester fee paid
Only PUBLISHED results are ever shown to students.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login, log_action
from utils.ui import render_sidebar, page_header, status_badge, metric_card
from utils.results_logic import (
    can_view_results, get_cumulative_balance, compute_semester_academic_status, compute_gpa
)
from models import Student, Registration, StudentCourse, Result, PublicationStatus, UserRole, AcademicYear
import pandas as pd

st.set_page_config(page_title="My Results — UoE SIS", page_icon="assets/favicon.ico", layout="wide")
require_login()
render_sidebar()
page_header("My Results", "View your published examination results")

user = st.session_state.user
db = get_db()

# ── Determine target student ────────────────────────────────
if user["role"] == UserRole.STUDENT.value:
    student_id = user.get("student_id")
    if not student_id:
        st.error("Your account is not linked to a student record. Contact the Registrar.")
        db.close()
        st.stop()
    student = db.query(Student).get(student_id)
else:
    # Staff viewing on behalf of a student
    snum = st.text_input("Enter Student Number")
    if not snum:
        st.info("Enter a student number to view their results.")
        db.close()
        st.stop()
    student = db.query(Student).filter_by(student_number=snum.strip()).first()
    if not student:
        st.error("Student not found.")
        db.close()
        st.stop()

st.markdown(
    f'<div style="background:white;border:1px solid #e5e7eb;border-radius:10px;padding:16px 20px;margin-bottom:16px;">'
    f'<strong>{student.full_name}</strong> &bull; {student.student_number} &bull; '
    f'{student.programme.name if student.programme else "N/A"} &bull; Year {student.year_of_study}'
    f'</div>',
    unsafe_allow_html=True
)

_academic_years = db.query(AcademicYear).filter_by(is_active=True).order_by(AcademicYear.label).all()
col1, col2 = st.columns(2)
with col1:
    if _academic_years:
        ay_labels = [ay.label for ay in _academic_years]
        default_idx = ay_labels.index(student.academic_year) if student.academic_year in ay_labels else 0
        academic_year = st.selectbox("Academic Year", ay_labels, index=default_idx)
    else:
        academic_year = st.text_input("Academic Year", student.academic_year or "2024/2025")
with col2:
    semester = st.selectbox("Semester", [1, 2])

reg = db.query(Registration).filter_by(
    student_id=student.id, academic_year=academic_year, semester=semester
).first()

if not reg:
    st.info(f"No registration found for {academic_year} Semester {semester}.")
    db.close()
    st.stop()

# ── Cumulative payment status summary ──────────────────────────────────
total_fees, total_paid, outstanding = get_cumulative_balance(db, student.id)
can_view_all, view_reason = can_view_results(db, student.id)
col1, col2, col3 = st.columns(3)
with col1:
    metric_card("Total Paid", f"K{total_paid:,.2f}", "#166534" if outstanding <= 0 else "#92400e")
with col2:
    metric_card("Outstanding Balance", f"K{outstanding:,.2f}",
                "#166534" if outstanding <= 0 else "#991b1b")
with col3:
    metric_card("Results Access", "Unlocked" if can_view_all else "Locked",
                "#166534" if can_view_all else "#991b1b")

st.markdown("---")

# ── Load published results only ─────────────────────────────
scs = db.query(StudentCourse).filter_by(registration_id=reg.id).all()
published_results = []
exempted_courses = []
for sc in scs:
    if sc.exemption:
        exempted_courses.append(sc)
    elif sc.result and sc.result.publication_status == PublicationStatus.PUBLISHED:
        published_results.append(sc.result)

if not published_results and not exempted_courses:
    st.warning(
        "No results have been published yet for this semester. "
        "Results are released by the Registrar's Office once finalised."
    )
    db.close()
    st.stop()

# ── Payment gate check — 100% cumulative balance required ───
if not can_view_all:
    st.error(f"🔒 {view_reason}")
    log_action(db, "RESULTS_BLOCKED_PAYMENT", "Student", student.id,
               f"{student.student_number} blocked: outstanding K{outstanding:,.2f}")
    db.close()
    st.stop()

# ── Display results ──────────────────────────────────────────
st.success(f"✅ {view_reason}")

rows = []
for r in published_results:
    sc = r.student_course
    rows.append({
        "Course Code": sc.course.code,
        "Course Name": sc.course.name,
        "Credits": sc.course.credits,
        "CA1": r.ca1_score,
        "CA2": r.ca2_score,
        "Mid-Sem (20%)": r.mid_sem_score,
        "Final (50%)": r.final_score,
        "Supp": f"{r.supp_score:.1f}" if r.supp_score else "—",
        "Total": r.total_score,
        "Grade": r.grade,
        "Status": r.status.value if r.status else "",
    })
for sc in exempted_courses:
    rows.append({
        "Course Code": sc.course.code,
        "Course Name": sc.course.name,
        "Credits": sc.course.credits,
        "CA1": "—", "CA2": "—", "Mid-Sem (20%)": "—", "Final (50%)": "—", "Supp": "—",
        "Total": "—", "Grade": "EX",
        "Status": f"Exempted ({sc.exemption.reason})" if sc.exemption.reason else "Exempted",
    })

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)
if exempted_courses:
    st.caption(
        f"{len(exempted_courses)} course(s) exempted — excluded from GPA and credit totals below."
    )

# ── Summary stats ────────────────────────────────────────────
gpa = compute_gpa(published_results)
academic_status = compute_semester_academic_status(published_results)

col1, col2, col3 = st.columns(3)
with col1:
    metric_card("Semester GPA", f"{gpa:.2f}", "#1a3a5c")
with col2:
    metric_card("Courses Taken", len(published_results), "#1a3a5c")
with col3:
    metric_card("Academic Status", status_badge(academic_status), sub="")

if academic_status == "Proceed but Repeat":
    st.warning(
        "⚠️ You have failed two or more courses this semester. "
        "You will proceed to the next level but must repeat the failed course(s). "
        "Please consult the Registrar's Office for your repeat schedule."
    )
elif academic_status == "Supplementary Required":
    st.info(
        "ℹ️ You have one or more courses requiring a Supplementary examination. "
        "Please check the Supplementary exam timetable with the Registrar's Office."
    )

st.markdown("---")
if st.button("Go to Result Slip (Printable)"):
    st.switch_page("pages/09_result_slip.py")

db.close()
