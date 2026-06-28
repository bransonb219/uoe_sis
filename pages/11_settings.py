"""
Settings & User Management — University of Edenberg SIS
Admin-only: manage staff users, programmes, fee structures, view audit log.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login, log_action, hash_password
from utils.ui import render_sidebar, page_header
from models import (
    User, UserRole, Programme, FeeStructure, AuditLog, ModeOfStudy,
    Intake, AcademicYear, IntakeProgress, Student
)
from utils.results_logic import promote_cohort, backfill_all_enrolment
from datetime import datetime
import pandas as pd

st.set_page_config(page_title="Settings — UoE SIS", page_icon="assets/favicon.ico", layout="wide")
require_login()
render_sidebar()
page_header("Settings & Administration", "Manage users, programmes, fees, and audit logs")

user = st.session_state.user
role = user["role"]

if role != UserRole.ADMIN.value:
    st.error("Access restricted to System Administrators.")
    st.stop()

db = get_db()

tab_users, tab_programmes, tab_fees, tab_academic_years, tab_intakes, tab_audit = st.tabs(
    ["Staff Users", "Programmes", "Fee Structures", "Academic Years", "Intakes & Cohorts", "Audit Log"]
)

# ─────────────────────────── USERS ────────────────────────────
with tab_users:
    st.subheader("Staff User Accounts")
    staff_users = db.query(User).filter(User.role != UserRole.STUDENT).order_by(User.role).all()

    rows = []
    for u in staff_users:
        rows.append({
            "_id": u.id,
            "Username": u.username,
            "Name": f"{u.first_name} {u.last_name}",
            "Role": u.role.value,
            "Email": u.email or "",
            "Active": "Yes" if u.is_active else "No",
            "Last Login": u.last_login.strftime("%Y-%m-%d %H:%M") if u.last_login else "Never",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows).drop(columns=["_id"]), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Add Staff User")
    with st.form("add_staff"):
        c1, c2 = st.columns(2)
        with c1:
            new_username = st.text_input("Username *")
            new_fn = st.text_input("First Name *")
            new_ln = st.text_input("Last Name *")
        with c2:
            new_role = st.selectbox("Role *", [r.value for r in UserRole if r != UserRole.STUDENT])
            new_email = st.text_input("Email")
            new_password = st.text_input("Initial Password *", type="password", value="Welcome@2024")

        if st.form_submit_button("Create User", type="primary"):
            if not all([new_username, new_fn, new_ln, new_password]):
                st.error("Please fill all required fields.")
            elif db.query(User).filter_by(username=new_username).first():
                st.error("Username already exists.")
            else:
                u = User(
                    username=new_username,
                    password_hash=hash_password(new_password),
                    role=new_role,
                    first_name=new_fn, last_name=new_ln,
                    email=new_email, is_active=True
                )
                db.add(u)
                db.commit()
                log_action(db, "ADD_USER", "User", u.id, f"{new_username} ({new_role})")
                st.success(f"User {new_username} created.")
                st.rerun()

    st.markdown("---")
    st.subheader("Deactivate / Reactivate User")
    target_username = st.text_input("Username to toggle")
    if target_username:
        target = db.query(User).filter_by(username=target_username.strip()).first()
        if not target:
            st.error("User not found.")
        else:
            action_label = "Deactivate" if target.is_active else "Reactivate"
            if st.button(f"{action_label} {target.username}"):
                target.is_active = not target.is_active
                db.commit()
                log_action(db, f"{action_label.upper()}_USER", "User", target.id, target.username)
                st.success(f"{target.username} has been {'reactivated' if target.is_active else 'deactivated'}.")
                st.rerun()


# ─────────────────────────── PROGRAMMES ───────────────────────
with tab_programmes:
    st.subheader("Programmes")
    programmes = db.query(Programme).all()
    rows = [{
        "Code": p.code, "Name": p.name, "Department": p.department,
        "Faculty": p.faculty, "Duration (yrs)": p.duration_years,
        "Total Credits": p.total_credits, "Active": "Yes" if p.is_active else "No"
    } for p in programmes]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Add Programme")
    with st.form("add_programme"):
        c1, c2 = st.columns(2)
        with c1:
            p_code = st.text_input("Programme Code *")
            p_name = st.text_input("Programme Name *")
            p_dept = st.text_input("Department")
        with c2:
            p_faculty = st.text_input("Faculty")
            p_duration = st.number_input("Duration (years)", 1, 6, 3)
            p_credits = st.number_input("Total Credits", 60, 600, 360)

        if st.form_submit_button("Add Programme", type="primary"):
            if not p_code or not p_name:
                st.error("Code and Name are required.")
            elif db.query(Programme).filter_by(code=p_code).first():
                st.error("Programme code already exists.")
            else:
                p = Programme(code=p_code, name=p_name, department=p_dept,
                              faculty=p_faculty, duration_years=p_duration, total_credits=p_credits)
                db.add(p)
                db.commit()
                log_action(db, "ADD_PROGRAMME", "Programme", p.id, p_code)
                st.success(f"Programme {p_code} added.")
                st.rerun()


# ─────────────────────────── FEE STRUCTURES ───────────────────
with tab_fees:
    st.subheader("Fee Structures")
    programmes = db.query(Programme).filter_by(is_active=True).all()
    fee_structs = db.query(FeeStructure).all()

    rows = [{
        "Programme": fs.programme.code if fs.programme else "",
        "Academic Year": fs.academic_year, "Semester": fs.semester,
        "Mode": fs.mode_of_study.value if fs.mode_of_study else "",
        "Total Fee (K)": f"{fs.total_fee:,.2f}",
    } for fs in fee_structs]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Set / Update Fee Structure")
    academic_years_list = db.query(AcademicYear).filter_by(is_active=True).order_by(AcademicYear.label).all()
    if not academic_years_list:
        st.warning("No academic years configured yet. Add one in the 'Academic Years' tab first.")
    else:
        with st.form("set_fee"):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                fee_prog = st.selectbox("Programme", [p.name for p in programmes])
            with c2:
                fee_year = st.selectbox("Academic Year", [ay.label for ay in academic_years_list])
            with c3:
                fee_sem = st.selectbox("Semester", [1, 2])
            with c4:
                fee_mode = st.selectbox("Mode of Study", [m.value for m in ModeOfStudy])
            fee_amount = st.number_input("Total Fee (K)", 0.0, step=500.0)

            if st.form_submit_button("Save Fee Structure", type="primary"):
                prog_obj = next(p for p in programmes if p.name == fee_prog)
                existing = db.query(FeeStructure).filter_by(
                    programme_id=prog_obj.id, academic_year=fee_year,
                    semester=fee_sem, mode_of_study=fee_mode,
                ).first()
                if existing:
                    existing.total_fee = fee_amount
                    msg = "updated"
                else:
                    existing = FeeStructure(
                        programme_id=prog_obj.id, academic_year=fee_year,
                        semester=fee_sem, mode_of_study=fee_mode, total_fee=fee_amount
                    )
                    db.add(existing)
                    msg = "created"
                db.commit()
                log_action(db, "SET_FEE_STRUCTURE", "FeeStructure", existing.id,
                           f"{prog_obj.code} {fee_year} Sem{fee_sem} {fee_mode}")
                st.success(f"Fee structure {msg} successfully.")
                st.rerun()


# ─────────────────────────── ACADEMIC YEARS ───────────────────
with tab_academic_years:
    st.subheader("Academic Years")
    st.caption(
        "Managed list used by every academic year dropdown system-wide "
        "(Fee Structures, Registration Period, Results Entry, Reports). "
        "Add a new year here before it's needed elsewhere."
    )
    academic_years = db.query(AcademicYear).order_by(AcademicYear.label).all()
    rows = [{
        "Label": ay.label, "Active": "Yes" if ay.is_active else "No",
    } for ay in academic_years]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    with st.form("add_academic_year"):
        ay_label = st.text_input("New Academic Year (e.g. 2027/2028)")
        if st.form_submit_button("Add", type="primary"):
            if not ay_label.strip():
                st.error("Enter a label.")
            elif db.query(AcademicYear).filter_by(label=ay_label.strip()).first():
                st.error("That academic year already exists.")
            else:
                ay = AcademicYear(label=ay_label.strip())
                db.add(ay)
                db.commit()
                log_action(db, "ADD_ACADEMIC_YEAR", "AcademicYear", ay.id, ay.label)
                st.success(f"Added {ay.label}.")
                st.rerun()


# ─────────────────────────── INTAKES & COHORTS ────────────────
with tab_intakes:
    st.subheader("Intakes")
    st.caption(
        "An Intake is a student's cohort — set once at enrolment, never "
        "changes. Distinct from year_of_study/current_semester, which "
        "advance via 'Promote Cohort' below."
    )
    intakes = db.query(Intake).order_by(Intake.code).all()
    intake_rows = [{
        "Code": i.code, "Label": i.label, "Active": "Yes" if i.is_active else "No",
        "Students": db.query(Student).filter_by(intake_id=i.id).count(),
    } for i in intakes]
    st.dataframe(pd.DataFrame(intake_rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    with st.form("add_intake"):
        c1, c2 = st.columns(2)
        with c1:
            i_code = st.text_input("Intake Code (e.g. 2027-D)")
        with c2:
            i_label = st.text_input("Label (e.g. 'Jul 2027 intake')")
        if st.form_submit_button("Add Intake", type="primary"):
            if not i_code.strip() or not i_label.strip():
                st.error("Both code and label are required.")
            elif db.query(Intake).filter_by(code=i_code.strip()).first():
                st.error("That intake code already exists.")
            else:
                i = Intake(code=i_code.strip(), label=i_label.strip())
                db.add(i)
                db.commit()
                log_action(db, "ADD_INTAKE", "Intake", i.id, i.code)
                st.success(f"Added intake {i.code}.")
                st.rerun()

    st.markdown("---")
    st.subheader("Cohort Progress")
    st.caption(
        "Each row records what calendar academic year a cohort's "
        "(year of study, semester) step happened in — set once per step, "
        "looked up everywhere else instead of being retyped."
    )
    progress_rows = db.query(IntakeProgress).join(Intake).order_by(Intake.code, IntakeProgress.year_of_study, IntakeProgress.semester_of_study).all()
    prows = [{
        "Intake": p.intake.code, "Year of Study": p.year_of_study,
        "Semester": p.semester_of_study, "Academic Year": p.academic_year.label,
        "Current": "Yes" if p.is_current else "",
    } for p in progress_rows]
    if prows:
        st.dataframe(pd.DataFrame(prows), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Promote Cohort")
    st.caption(
        "Advances every active student in an intake to a new (year of "
        "study, semester) and auto-enrols them into matching courses for "
        "that period — no manual per-student enrolment needed."
    )
    academic_years_list2 = db.query(AcademicYear).filter_by(is_active=True).order_by(AcademicYear.label).all()
    if not intakes or not academic_years_list2:
        st.info("Add at least one Intake and one Academic Year first.")
    else:
        with st.form("promote_cohort"):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                promote_intake_code = st.selectbox("Intake", [i.code for i in intakes if i.code not in ("LEGACY", "UNCONFIRMED")])
            with c2:
                promote_yos = st.number_input("New Year of Study", 1, 6, 1)
            with c3:
                promote_sos = st.selectbox("New Semester", [1, 2])
            with c4:
                promote_ay_label = st.selectbox("Academic Year", [ay.label for ay in academic_years_list2])

            if st.form_submit_button("Promote Cohort", type="primary"):
                intake_obj = next(i for i in intakes if i.code == promote_intake_code)
                ay_obj = next(a for a in academic_years_list2 if a.label == promote_ay_label)
                result = promote_cohort(
                    db, intake_obj.id, promote_yos, promote_sos, ay_obj.id, user["id"]
                )
                log_action(db, "PROMOTE_COHORT", "Intake", intake_obj.id,
                           f"{intake_obj.code} -> Y{promote_yos}S{promote_sos} ({promote_ay_label}): "
                           f"{result['students_promoted']} students, "
                           f"{result['registrations_created']} registrations, "
                           f"{result['enrolments_created']} enrolments")
                st.success(
                    f"Promoted {result['students_promoted']} student(s) in {intake_obj.code} to "
                    f"Year {promote_yos} Semester {promote_sos} ({promote_ay_label}). "
                    f"Created {result['registrations_created']} registration(s) and "
                    f"{result['enrolments_created']} course enrolment(s)."
                )
                st.rerun()

    st.markdown("---")
    st.subheader("Backfill Enrolment")
    st.caption(
        "Ensures every active student has a Registration + course enrolment "
        "(StudentCourse) for EVERY period they've progressed through so far — "
        "past and current, not just their latest one — based on their "
        "programme, intake, and year of study. Use this after loading/fixing "
        "the course catalogue, or whenever students show up with no "
        "enrolment despite having a confirmed intake/year/semester. Safe to "
        "re-run — only creates what's missing."
    )
    backfill_scope = st.radio(
        "Scope", ["All students", "One intake only"], horizontal=True, key="backfill_scope"
    )
    backfill_intake_id = None
    if backfill_scope == "One intake only":
        backfill_intake_code = st.selectbox("Intake", [i.code for i in intakes], key="backfill_intake_sel")
        backfill_intake_id = next(i.id for i in intakes if i.code == backfill_intake_code)

    if st.button("Run Backfill Enrolment", type="primary", key="run_backfill_enrolment"):
        with st.spinner("Backfilling enrolment — this may take a moment for large cohorts..."):
            result = backfill_all_enrolment(db, user["id"], intake_id=backfill_intake_id)
        log_action(db, "BACKFILL_ENROLMENT", "Student", None,
                   f"scope={backfill_scope}: {result['students_processed']} students processed, "
                   f"{result['registrations_created']} registrations, {result['enrolments_created']} enrolments")
        st.success(
            f"Processed {result['students_processed']} student(s). "
            f"Created {result['registrations_created']} registration(s) and "
            f"{result['enrolments_created']} course enrolment(s)."
        )


# ─────────────────────────── AUDIT LOG ────────────────────────
with tab_audit:
    st.subheader("System Audit Log")
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(200).all()
    rows = []
    for log in logs:
        u = db.query(User).get(log.user_id) if log.user_id else None
        rows.append({
            "Timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "",
            "User": f"{u.first_name} {u.last_name}" if u else "System",
            "Action": log.action,
            "Entity": log.entity or "",
            "Details": log.details or "",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"Showing latest {len(rows)} log entries.")
    else:
        st.info("No audit log entries yet.")

db.close()
