"""
Financials — University of Edenberg SIS
NOTE: This page was rebuilt to fix the v2 bug where Streamlit column widgets
were mixed inside raw HTML strings. All layout below uses either pure
st.columns() with native widgets, OR pure HTML in a single st.markdown call
— never both combined in one HTML string.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login, log_action
from utils.ui import render_sidebar, page_header, metric_card, status_badge
from utils.results_logic import get_payment_percentage, get_cumulative_balance, allocate_payment
from models import Student, Payment, FeeStructure, Programme, PaymentStatus, UserRole, AcademicYear, Intake
from datetime import datetime
import pandas as pd
import sqlalchemy
import io

st.set_page_config(page_title="Financials — UoE SIS", page_icon="assets/favicon.ico", layout="wide")
require_login()
render_sidebar()
page_header("Financial Management", "Student fee payments and statements")

user = st.session_state.user
role = user["role"]
db = get_db()
_academic_years = db.query(AcademicYear).filter_by(is_active=True).order_by(AcademicYear.label).all()


def _academic_year_picker(label, default_label, key):
    if _academic_years:
        labels = [ay.label for ay in _academic_years]
        idx = labels.index(default_label) if default_label in labels else 0
        return st.selectbox(label, labels, index=idx, key=key)
    return st.text_input(label, default_label, key=key)

tab_statement, tab_record, tab_overview, tab_export = st.tabs(
    ["Student Statement", "Record Payment", "Fee Overview", "Student Payments Report"]
)

# ─────────────────────────── STUDENT STATEMENT ───────────────
with tab_statement:
    st.subheader("Student Financial Statement")

    if role == UserRole.STUDENT.value:
        student = db.query(Student).get(user.get("student_id"))
        if not student:
            st.error("Student record not linked.")
            st.stop()
    else:
        snum = st.text_input("Student Number")
        student = None
        if snum:
            student = db.query(Student).filter_by(student_number=snum.strip()).first()
            if not student:
                st.error("Student not found.")

    if student:
        st.markdown(f"**{student.full_name}** — {student.student_number}")

        academic_year = _academic_year_picker("Academic Year", student.academic_year or "2024/2025", "stmt_year")

        # Per-semester breakdown — pure widgets, no mixed HTML
        for semester in [1, 2]:
            fee_struct = db.query(FeeStructure).filter_by(
                programme_id=student.programme_id,
                academic_year=academic_year,
                semester=semester,
                mode_of_study=student.mode_of_study,
            ).first()

            if not fee_struct:
                continue

            payments = db.query(Payment).filter_by(
                student_id=student.id, academic_year=academic_year, semester=semester
            ).all()
            total_paid = sum(p.amount for p in payments)
            balance = fee_struct.total_fee - total_paid
            pct = (total_paid / fee_struct.total_fee) if fee_struct.total_fee else 0

            st.markdown(f"#### Semester {semester}")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                metric_card("Total Fee", f"K{fee_struct.total_fee:,.2f}")
            with c2:
                metric_card("Amount Paid", f"K{total_paid:,.2f}", "#166534")
            with c3:
                metric_card("Balance", f"K{balance:,.2f}", "#991b1b" if balance > 0 else "#166534")
            with c4:
                metric_card("Payment %", f"{pct*100:.1f}%",
                            "#166534" if pct >= 0.70 else "#92400e" if pct >= 0.40 else "#991b1b")

            st.progress(min(pct, 1.0))

            gate_msgs = []
            if pct >= 0.25:
                gate_msgs.append("✅ Course registration unlocked (25% threshold met)")
            else:
                gate_msgs.append(f"🔒 Course registration locked — 25% required, {pct*100:.1f}% paid")
            for m in gate_msgs:
                st.caption(m)
            st.caption("ℹ️ Results access requires 100% of ALL outstanding balances cleared.")

            if payments:
                with st.expander(f"Payment History — Semester {semester}"):
                    rows = [{
                        "Date": p.payment_date.strftime("%Y-%m-%d") if p.payment_date else "",
                        "Amount": f"K{p.amount:,.2f}",
                        "Method": p.method or "",
                        "Reference": p.reference or "",
                        "Status": p.status.value if p.status else "",
                    } for p in payments]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.markdown("---")


# ─────────────────────────── RECORD PAYMENT ──────────────────
with tab_record:
    if role not in (UserRole.ADMIN.value, UserRole.FINANCE.value):
        st.warning("Only Finance or Admin can record payments.")
    else:
        st.subheader("Record New Payment")
        st.caption(
            "Enter the total amount received. It's automatically allocated "
            "across the student's oldest unpaid semester(s) first — no "
            "single semester is ever pushed into overpayment. Any amount "
            "beyond all known dues is reported back, not recorded."
        )

        lookup_snum = st.text_input("Student Number", key="record_payment_lookup")
        lookup_student = None
        if lookup_snum:
            lookup_student = db.query(Student).filter_by(student_number=lookup_snum.strip()).first()
            if not lookup_student:
                st.error("Student not found.")
            else:
                preview_fees, preview_paid, preview_outstanding = get_cumulative_balance(db, lookup_student.id)
                c1, c2, c3 = st.columns(3)
                with c1:
                    metric_card("Name", lookup_student.full_name)
                with c2:
                    metric_card("Total Paid to Date", f"K{preview_paid:,.2f}", "#166534")
                with c3:
                    metric_card("Current Outstanding", f"K{preview_outstanding:,.2f}",
                                "#166534" if preview_outstanding <= 0 else "#991b1b")

        with st.form("record_payment"):
            c1, c2 = st.columns(2)
            with c1:
                p_snum = st.text_input("Student Number * (confirm)", value=lookup_snum)
                p_amount = st.number_input("Amount Received (K) *", 0.0, step=50.0)
            with c2:
                p_method = st.selectbox("Payment Method", ["Bank Transfer", "Mobile Money", "Cash", "Cheque"])
                p_ref = st.text_input("Reference Number")

            submitted = st.form_submit_button("Record Payment", type="primary")

        if submitted:
            student = db.query(Student).filter_by(student_number=p_snum.strip()).first()
            if not student:
                st.error("Student not found.")
            elif p_amount <= 0:
                st.error("Amount must be greater than zero.")
            else:
                ref = p_ref or f"PAY{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                result = allocate_payment(
                    db, student, p_amount, method=p_method, reference=ref,
                    received_by=user["id"],
                )
                db.commit()
                for p in result["payments_created"]:
                    log_action(db, "RECORD_PAYMENT", "Payment", p.id,
                               f"{p_snum}: K{p.amount:,.2f} -> {p.academic_year} Sem{p.semester}")

                if result["payments_created"]:
                    st.success(f"Allocated K{result['allocated']:,.2f} for {student.full_name}:")
                    for p in result["payments_created"]:
                        st.caption(f"  • {p.academic_year} Semester {p.semester}: K{p.amount:,.2f}")
                if result["unallocated"] > 0:
                    st.warning(
                        f"K{result['unallocated']:,.2f} could NOT be allocated — it exceeds all "
                        f"known dues through {student.full_name}'s current semester. This amount "
                        f"has NOT been recorded. If it's an advance for an upcoming semester, wait "
                        f"until that period is opened (Promote Cohort) before recording it."
                    )
                if not result["payments_created"] and result["unallocated"] == 0:
                    st.info("Nothing to allocate — no fee structure found for this student's periods.")


# ─────────────────────────── FEE OVERVIEW ─────────────────────
with tab_overview:
    if role not in (UserRole.ADMIN.value, UserRole.FINANCE.value, UserRole.REGISTRAR.value):
        st.warning("Access restricted.")
    else:
        st.subheader("Fee Collection Overview")
        programmes = db.query(Programme).filter_by(is_active=True).all()
        o_year = _academic_year_picker("Academic Year", "2024/2025", "o_year")
        o_sem = st.selectbox("Semester", [1, 2], key="o_sem")

        from models import ModeOfStudy
        rows = []
        for prog in programmes:
            students = db.query(Student).filter_by(programme_id=prog.id).all()
            if not students:
                continue
            for mode in ModeOfStudy:
                mode_students = [s for s in students if s.mode_of_study == mode]
                if not mode_students:
                    continue
                fee_struct = db.query(FeeStructure).filter_by(
                    programme_id=prog.id, academic_year=o_year,
                    semester=o_sem, mode_of_study=mode,
                ).first()
                if not fee_struct:
                    continue
                total_expected = fee_struct.total_fee * len(mode_students)
                total_collected = 0.0
                for s in mode_students:
                    paid = db.query(Payment).filter_by(
                        student_id=s.id, academic_year=o_year, semester=o_sem
                    ).all()
                    total_collected += sum(p.amount for p in paid)

                rows.append({
                    "Programme": prog.name,
                    "Mode": mode.value,
                    "Students": len(mode_students),
                    "Expected (K)": f"{total_expected:,.2f}",
                    "Collected (K)": f"{total_collected:,.2f}",
                    "Collection %": f"{(total_collected/total_expected*100) if total_expected else 0:.1f}%",
                })

        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No fee data available for the selected period.")


# ───────────────────── STUDENT PAYMENTS REPORT (EXCEL) ────────────────
with tab_export:
    if role not in (UserRole.ADMIN.value, UserRole.FINANCE.value, UserRole.REGISTRAR.value):
        st.warning("Access restricted.")
    else:
        st.subheader("Generate Student Payments Report")
        st.caption(
            "Produces a detailed payments workbook for every student — Overall "
            "Charged/Paid/Outstanding (bounded to each student's own enrolment "
            "window) and Current Semester Total/Paid/Balance — computed live "
            "from the database. Useful for cross-checking against external "
            "fee reconciliation spreadsheets."
        )

        programmes = db.query(Programme).filter_by(is_active=True).all()
        intakes = db.query(Intake).order_by(Intake.code).all()
        prog_opts = {"All Programmes": None} | {p.name: p.id for p in programmes}
        intake_opts = {"All Intakes": None} | {i.code: i.id for i in intakes}

        c1, c2 = st.columns(2)
        with c1:
            export_prog_sel = st.selectbox("Programme", list(prog_opts.keys()), key="export_prog")
        with c2:
            export_intake_sel = st.selectbox("Intake", list(intake_opts.keys()), key="export_intake")

        if st.button("Generate Report", type="primary"):
            query = db.query(Student).filter_by(status="Active")
            if prog_opts[export_prog_sel]:
                query = query.filter_by(programme_id=prog_opts[export_prog_sel])
            if intake_opts[export_intake_sel]:
                query = query.filter_by(intake_id=intake_opts[export_intake_sel])
            students = query.order_by(Student.student_number).all()

            if not students:
                st.info("No students match the selected filters.")
            else:
                rows = []
                for s in students:
                    overall_charged, overall_paid, outstanding = get_cumulative_balance(db, s.id)

                    cur_ay, cur_sem = s.academic_year, s.current_semester
                    cur_total, cur_paid = 0.0, 0.0
                    if cur_ay and cur_sem:
                        fs = db.query(FeeStructure).filter_by(
                            programme_id=s.programme_id, academic_year=cur_ay,
                            semester=cur_sem, mode_of_study=s.mode_of_study,
                        ).first()
                        cur_total = fs.total_fee if fs else 0.0
                        cur_paid = (
                            db.query(sqlalchemy.func.sum(Payment.amount))
                            .filter_by(student_id=s.id, academic_year=cur_ay, semester=cur_sem)
                            .scalar() or 0.0
                        )

                    rows.append({
                        "Reg No": s.student_number,
                        "Student Name": s.full_name,
                        "Programme": s.programme.name if s.programme else "",
                        "Programme Code": s.programme.code if s.programme else "",
                        "Mode of Study": s.mode_of_study.value if s.mode_of_study else "",
                        "Intake": s.intake.code if s.intake else "",
                        "Year of Study": s.year_of_study,
                        "Current Semester": s.current_semester,
                        "Academic Year": s.academic_year,
                        "Overall Charged (Upto Current Sem)": round(overall_charged, 2),
                        "Overall Paid (Upto Current Sem)": round(overall_paid, 2),
                        "Outstanding (Upto Current Sem)": round(outstanding, 2),
                        "Current Sem Total": round(cur_total, 2),
                        "Current Sem Paid": round(cur_paid, 2),
                        "Current Sem Balance": round(cur_total - cur_paid, 2),
                    })

                df_export = pd.DataFrame(rows)
                st.dataframe(df_export, use_container_width=True, hide_index=True)
                st.caption(f"{len(rows)} student(s).")

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    df_export.to_excel(writer, index=False, sheet_name="Payments Report")
                buffer.seek(0)

                st.download_button(
                    "Download Payments Report (Excel)",
                    buffer,
                    f"student_payments_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                )
                log_action(db, "GENERATE_PAYMENTS_REPORT", "Student", None,
                           f"{len(rows)} student(s), programme={export_prog_sel}, intake={export_intake_sel}")

db.close()
