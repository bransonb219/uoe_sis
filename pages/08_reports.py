"""
Reports — University of Edenberg SIS
Programme/course performance, enrolment summary, fee collection reports.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login
from utils.ui import render_sidebar, page_header, metric_card
from models import (
    Student, Course, Registration, StudentCourse, Result,
    Programme, Payment, FeeStructure, PublicationStatus, ResultStatus, UserRole,
    AcademicYear, Intake
)
import pandas as pd

st.set_page_config(page_title="Reports — UoE SIS", layout="wide")
require_login()
render_sidebar()
page_header("Reports", "Programme performance, enrolment, and fee collection reports")

user = st.session_state.user
role = user["role"]

if role not in (UserRole.ADMIN.value, UserRole.REGISTRAR.value):
    st.error("Access restricted to Registrar and Admin.")
    st.stop()

db = get_db()
_academic_years = db.query(AcademicYear).filter_by(is_active=True).order_by(AcademicYear.label).all()


def _academic_year_picker(label, default_label, key):
    if _academic_years:
        labels = [ay.label for ay in _academic_years]
        idx = labels.index(default_label) if default_label in labels else 0
        return st.selectbox(label, labels, index=idx, key=key)
    return st.text_input(label, default_label, key=key)

tab_perf, tab_enrol, tab_fee = st.tabs([
    "Programme/Course Performance", "Enrolment Summary", "Fee Collection"
])

# ─────────────────────────── PERFORMANCE REPORT ──────────────
with tab_perf:
    st.subheader("Programme & Course Performance Report")
    col1, col2 = st.columns(2)
    with col1:
        p_year = _academic_year_picker("Academic Year", "2025/2026", "p_year")
    with col2:
        p_sem = st.selectbox("Semester", [1, 2], key="p_sem")

    programmes = db.query(Programme).filter_by(is_active=True).all()
    rows = []
    for prog in programmes:
        courses = db.query(Course).filter_by(programme_id=prog.id, semester=p_sem).all()
        for course in courses:
            results = (
                db.query(Result)
                .join(StudentCourse)
                .join(Registration)
                .filter(
                    StudentCourse.course_id == course.id,
                    Registration.academic_year == p_year,
                    Registration.semester == p_sem,
                    Result.total_score.isnot(None)
                ).all()
            )
            if not results:
                continue
            total = len(results)
            passed = sum(1 for r in results if r.status == ResultStatus.PASS)
            failed = sum(1 for r in results if r.status == ResultStatus.FAIL)
            supp = sum(1 for r in results if r.status == ResultStatus.SUPPLEMENTARY)
            avg_score = sum(r.total_score for r in results) / total

            rows.append({
                "Programme": prog.code,
                "Course": course.code,
                "Course Name": course.name,
                "Enrolled": total,
                "Pass": passed,
                "Fail": failed,
                "Supplementary": supp,
                "Pass Rate": f"{(passed/total*100):.1f}%",
                "Avg Score": f"{avg_score:.1f}",
            })

    if rows:
        df_perf = pd.DataFrame(rows)
        st.dataframe(df_perf, use_container_width=True, hide_index=True)
        st.download_button(
            "Export Performance Report (CSV)",
            df_perf.to_csv(index=False),
            f"performance_report_{p_year.replace('/', '-')}_sem{p_sem}.csv",
            "text/csv"
        )
    else:
        st.info("No results data available for the selected period.")


# ─────────────────────────── ENROLMENT SUMMARY ───────────────
with tab_enrol:
    st.subheader("Enrolment Summary Report")
    intakes = db.query(Intake).order_by(Intake.code).all()
    intake_opts = {"All Intakes": None} | {i.code: i.id for i in intakes}

    col1, col2, col3 = st.columns(3)
    with col1:
        e_year = _academic_year_picker("Academic Year", "2025/2026", "e_year")
    with col2:
        e_sem = st.selectbox("Semester", [1, 2], key="e_sem")
    with col3:
        e_intake_sel = st.selectbox("Intake", list(intake_opts.keys()), key="e_intake")

    rows = []
    programmes = db.query(Programme).filter_by(is_active=True).all()
    for prog in programmes:
        reg_query = (
            db.query(Registration)
            .join(Student)
            .filter(
                Student.programme_id == prog.id,
                Registration.academic_year == e_year,
                Registration.semester == e_sem
            )
        )
        if intake_opts[e_intake_sel]:
            reg_query = reg_query.filter(Student.intake_id == intake_opts[e_intake_sel])
        regs = reg_query.all()
        by_year = {}
        for r in regs:
            by_year[r.year_of_study] = by_year.get(r.year_of_study, 0) + 1

        rows.append({
            "Programme": prog.name,
            "Total Enrolled": len(regs),
            "Year 1": by_year.get(1, 0),
            "Year 2": by_year.get(2, 0),
            "Year 3": by_year.get(3, 0),
            "Year 4": by_year.get(4, 0),
        })

    if rows:
        df_enrol = pd.DataFrame(rows)
        st.dataframe(df_enrol, use_container_width=True, hide_index=True)

        total_row = pd.DataFrame([{
            "Programme": "TOTAL",
            "Total Enrolled": df_enrol["Total Enrolled"].sum(),
            "Year 1": df_enrol["Year 1"].sum(),
            "Year 2": df_enrol["Year 2"].sum(),
            "Year 3": df_enrol["Year 3"].sum(),
            "Year 4": df_enrol["Year 4"].sum(),
        }])
        st.markdown("**Totals**")
        st.dataframe(total_row, use_container_width=True, hide_index=True)

        st.download_button(
            "Export Enrolment Summary (CSV)",
            df_enrol.to_csv(index=False),
            f"enrolment_summary_{e_year.replace('/', '-')}_sem{e_sem}.csv",
            "text/csv"
        )
    else:
        st.info("No enrolment data available.")


# ─────────────────────────── FEE COLLECTION ───────────────────
with tab_fee:
    st.subheader("Fee Collection Report")
    col1, col2 = st.columns(2)
    with col1:
        f_year = _academic_year_picker("Academic Year", "2025/2026", "f_year")
    with col2:
        f_sem = st.selectbox("Semester", [1, 2], key="f_sem")

    rows = []
    programmes = db.query(Programme).filter_by(is_active=True).all()
    grand_expected = 0.0
    grand_collected = 0.0

    for prog in programmes:
        students = db.query(Student).filter_by(programme_id=prog.id, status="Active").all()
        fee_struct = db.query(FeeStructure).filter_by(
            programme_id=prog.id, academic_year=f_year, semester=f_sem
        ).first()
        if not fee_struct or not students:
            continue

        expected = fee_struct.total_fee * len(students)
        collected = 0.0
        fully_paid = 0
        partial = 0
        unpaid = 0

        for s in students:
            paid = sum(
                p.amount for p in db.query(Payment).filter_by(
                    student_id=s.id, academic_year=f_year, semester=f_sem
                ).all()
            )
            collected += paid
            pct = paid / fee_struct.total_fee if fee_struct.total_fee else 0
            if pct >= 1.0:
                fully_paid += 1
            elif pct > 0:
                partial += 1
            else:
                unpaid += 1

        grand_expected += expected
        grand_collected += collected

        rows.append({
            "Programme": prog.name,
            "Students": len(students),
            "Expected (K)": round(expected, 2),
            "Collected (K)": round(collected, 2),
            "Outstanding (K)": round(expected - collected, 2),
            "Collection %": f"{(collected/expected*100) if expected else 0:.1f}%",
            "Fully Paid": fully_paid,
            "Partial": partial,
            "Unpaid": unpaid,
        })

    if rows:
        col1, col2, col3 = st.columns(3)
        with col1:
            metric_card("Total Expected", f"K{grand_expected:,.2f}")
        with col2:
            metric_card("Total Collected", f"K{grand_collected:,.2f}", "#166534")
        with col3:
            metric_card("Collection Rate",
                        f"{(grand_collected/grand_expected*100) if grand_expected else 0:.1f}%")

        df_fee = pd.DataFrame(rows)
        st.dataframe(df_fee, use_container_width=True, hide_index=True)
        st.download_button(
            "Export Fee Collection Report (CSV)",
            df_fee.to_csv(index=False),
            f"fee_collection_{f_year.replace('/', '-')}_sem{f_sem}.csv",
            "text/csv"
        )
    else:
        st.info("No fee data available for the selected period.")

db.close()
