"""
Student Course Registration — University of Edenberg SIS

Two distinct flows live in this single page, branched by role:

  Staff (Admin/Registrar): the original manual enrolment tool — look up
  any student by number, enrol them into courses, view a registration
  summary across all students. Plus a new Registration Period control
  (global on/off switch for self-service registration).

  Student: a new self-service flow. Registration is pinned to the single
  coming registration period (2025/2026 Semester 2) — students are not
  prompted to pick an academic year/semester, so no staff intervention or
  manual enrolment is needed after a bulk student upload. A student can
  only register for themselves, only while the Registrar has this period
  open, and only once they've met the payment gate. They see their core
  courses pre-selected and can opt into electives (including electives
  marked semester=0, meaning "offered either semester"). After submitting,
  they get a detailed confirmation view and can download an HTML
  confirmation slip (printable to PDF via the browser's print dialog).
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login, log_action
from utils.ui import render_sidebar, page_header, status_badge, metric_card
from utils.results_logic import (
    can_register, is_registration_open, course_matches_semester,
    get_payment_percentage, is_past_semester
)
from models import (
    Student, Course, Registration, StudentCourse,
    EnrolmentStatus, UserRole, RegistrationPeriod, AcademicYear
)
from datetime import datetime
import pandas as pd

# Self-service registration is restricted to this single coming period.
# Students don't choose an academic year/semester — this removes the need
# for staff to manually enrol students into a programme/period after a
# bulk upload; they self-register directly into the upcoming period.
UPCOMING_ACADEMIC_YEAR = "2025/2026"
UPCOMING_SEMESTER = 2

st.set_page_config(page_title="Registration — UoE SIS", layout="wide")
require_login()
render_sidebar()
page_header("Course Registration", "Register for semester courses")

user = st.session_state.user
role = user["role"]
db = get_db()
_academic_years = db.query(AcademicYear).filter_by(is_active=True).order_by(AcademicYear.label).all()


def _academic_year_picker(label, default_label, key):
    """Dropdown sourced from AcademicYear, falling back to free text if none configured."""
    if _academic_years:
        labels = [ay.label for ay in _academic_years]
        idx = labels.index(default_label) if default_label in labels else 0
        return st.selectbox(label, labels, index=idx, key=key)
    return st.text_input(label, default_label, key=key)


# ════════════════════════════════════════════════════════════════
# STUDENT SELF-SERVICE REGISTRATION
# ════════════════════════════════════════════════════════════════
if role == UserRole.STUDENT.value:
    student = db.query(Student).get(user.get("student_id"))
    if not student:
        st.error("Your account is not linked to a student record. Contact the Registrar.")
        db.close()
        st.stop()

    st.markdown(
        f'<div style="background:white;border:1px solid #e5e7eb;border-radius:10px;'
        f'padding:16px 20px;margin-bottom:16px;">'
        f'<strong>{student.full_name}</strong> &bull; {student.student_number} &bull; '
        f'{student.programme.name if student.programme else "N/A"} &bull; Year {student.year_of_study}'
        f'</div>',
        unsafe_allow_html=True
    )

    academic_year = UPCOMING_ACADEMIC_YEAR
    semester = UPCOMING_SEMESTER
    st.caption(f"Registering for the coming period: **{academic_year}, Semester {semester}**")

    period_open = is_registration_open(db, academic_year, semester)
    past = is_past_semester(db, academic_year, semester)
    payment_ok, payment_reason = can_register(db, student.id, academic_year, semester, is_past=past)
    pct_paid = get_payment_percentage(db, student.id, academic_year, semester)

    col1, col2 = st.columns(2)
    with col1:
        metric_card("Registration Period", "Open" if period_open else "Closed",
                    "#166534" if period_open else "#991b1b")
    with col2:
        metric_card("Fee Payment", f"{pct_paid * 100:.1f}%",
                    "#166534" if payment_ok else "#991b1b")

    existing_reg = db.query(Registration).filter_by(
        student_id=student.id, academic_year=academic_year, semester=semester
    ).first()

    if existing_reg:
        st.success(f"You are registered for {academic_year}, Semester {semester}.")
        st.markdown("### Registration Details")

        enrolled = db.query(StudentCourse).filter_by(registration_id=existing_reg.id).all()
        rows = []
        total_credits = 0
        for sc in enrolled:
            c = sc.course
            rows.append({
                "Code": c.code,
                "Course Name": c.name,
                "Type": "Core" if c.is_core else "Elective",
                "Credits": c.credits,
                "Repeat": "Yes" if sc.is_repeat else "No",
            })
            total_credits += c.credits or 0

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        col1, col2, col3 = st.columns(3)
        with col1:
            metric_card("Courses Registered", len(enrolled))
        with col2:
            metric_card("Total Credits", total_credits)
        with col3:
            metric_card("Status", existing_reg.status.value)

        rows_html = "".join(
            f"<tr><td>{r['Code']}</td><td>{r['Course Name']}</td>"
            f"<td style='text-align:center;'>{r['Type']}</td>"
            f"<td style='text-align:center;'>{r['Credits']}</td></tr>"
            for r in rows
        )
        generated_on = datetime.now().strftime("%d %B %Y, %H:%M")

        confirmation_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Registration Confirmation - {student.student_number}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #1f2937; margin: 0; padding: 30px; }}
  .header {{ border-bottom: 3px solid #1a3a5c; padding-bottom: 16px; margin-bottom: 20px; }}
  .header h1 {{ margin: 0; color: #1a3a5c; font-size: 1.4rem; }}
  .header p {{ margin: 2px 0; color: #6b7280; font-size: 0.85rem; }}
  .title {{ text-align: center; font-size: 1.1rem; font-weight: 700; color: #1a3a5c;
            margin: 16px 0; text-transform: uppercase; letter-spacing: 1px; }}
  .info-table {{ width: 100%; margin-bottom: 20px; font-size: 0.9rem; }}
  .info-table td {{ padding: 4px 8px; }}
  .info-table .label {{ color: #6b7280; font-weight: 600; width: 160px; }}
  table.courses {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 0.85rem; }}
  table.courses th {{ background: #1a3a5c; color: white; padding: 8px; text-align: left; }}
  table.courses td {{ padding: 7px 8px; border-bottom: 1px solid #e5e7eb; }}
  table.courses tr:nth-child(even) {{ background: #f9fafb; }}
  .summary {{ background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px;
              padding: 14px 20px; margin-bottom: 20px; display: flex; justify-content: space-between; }}
  .summary-item {{ text-align: center; }}
  .summary-item .label {{ font-size: 0.75rem; color: #6b7280; text-transform: uppercase; }}
  .summary-item .value {{ font-size: 1.3rem; font-weight: 700; color: #1a3a5c; }}
  .footer {{ font-size: 0.75rem; color: #9ca3af; text-align: center; margin-top: 30px;
             border-top: 1px solid #e5e7eb; padding-top: 10px; }}
  @media print {{ body {{ padding: 10px; }} }}
</style>
</head>
<body>
  <div class="header">
    <h1>UNIVERSITY OF EDENBERG</h1>
    <p>Office of the Registrar &bull; Academic Records Division</p>
    <p>Ariyapatta Campus (Main): Stand No. 7, Enock Kavu Road</p>
    <p>Maslow Campus (Faculty of Medical &amp; Health Sciences): St. Eugene Office Park, Stand No. 22866, Ibex Hill, Leopards Hill Road</p>
    <p>P.O. Box 37209, Lusaka, Zambia</p>
  </div>

  <div class="title">Course Registration Confirmation</div>

  <table class="info-table">
    <tr><td class="label">Student Name:</td><td>{student.full_name}</td>
        <td class="label">Student Number:</td><td>{student.student_number}</td></tr>
    <tr><td class="label">Programme:</td><td>{student.programme.name if student.programme else 'N/A'}</td>
        <td class="label">Year of Study:</td><td>{student.year_of_study}</td></tr>
    <tr><td class="label">Academic Year:</td><td>{academic_year}</td>
        <td class="label">Semester:</td><td>{semester}</td></tr>
  </table>

  <table class="courses">
    <thead><tr><th>Code</th><th>Course Name</th><th>Type</th><th>Credits</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>

  <div class="summary">
    <div class="summary-item"><div class="label">Courses</div><div class="value">{len(enrolled)}</div></div>
    <div class="summary-item"><div class="label">Total Credits</div><div class="value">{total_credits}</div></div>
    <div class="summary-item"><div class="label">Status</div><div class="value" style="font-size:1rem;">{existing_reg.status.value}</div></div>
  </div>

  <div class="footer">
    This is a system-generated registration confirmation from the University of Edenberg Student Information System.<br>
    Generated on {generated_on}.<br>
    Registrar's Office: registrar@ue.ac.zm &bull; +260 96 196 3254 &nbsp;|&nbsp; Admissions: admission@ue.ac.zm
  </div>
</body>
</html>
"""
        st.markdown("### Confirmation Slip")
        st.caption("Download the slip below, then use your browser's Print dialog (Ctrl+P) and choose "
                   "'Save as PDF' if you need a PDF copy.")
        st.components.v1.html(confirmation_html, height=500, scrolling=True)
        st.download_button(
            "Download Confirmation Slip (HTML)",
            confirmation_html,
            f"registration_confirmation_{student.student_number}_{academic_year.replace('/', '-')}_sem{semester}.html",
            "text/html",
            type="primary"
        )

    else:
        if not past and not period_open:
            st.warning(
                "Course registration is currently **closed** for this semester. "
                "Registration opens only during the period set by the Registrar's Office. "
                "Please check back once the registration period has been announced."
            )
            db.close()
            st.stop()

        if not payment_ok:
            st.error(f"🔒 {payment_reason}")
            db.close()
            st.stop()

        if past:
            st.info(f"✅ Backdating registration for a past semester — no payment gate applies.")
        else:
            st.info(f"✅ Registration is open and your payment meets the 25% requirement ({payment_reason}).")

        all_eligible = db.query(Course).filter(
            Course.programme_id == student.programme_id,
            Course.year_level == student.year_of_study,
            Course.is_active == True
        ).all()
        eligible_for_semester = [c for c in all_eligible if course_matches_semester(c.semester, semester)]
        core_courses = [c for c in eligible_for_semester if c.is_core]
        elective_courses = [c for c in eligible_for_semester if not c.is_core]

        if not core_courses and not elective_courses:
            st.warning("No courses are currently configured for your programme/year/semester. "
                       "Please contact the Registrar's Office.")
            db.close()
            st.stop()

        st.markdown("### Core Courses (automatically included)")
        if core_courses:
            for c in core_courses:
                st.markdown(f"- **{c.code}** — {c.name} ({c.credits} credits)")
        else:
            st.caption("No core courses configured for this semester.")

        selected_elective_ids = []
        if elective_courses:
            st.markdown("### Electives (optional — select any you'd like to take)")
            for c in elective_courses:
                if st.checkbox(f"{c.code} — {c.name} ({c.credits} credits)", key=f"elective_{c.id}"):
                    selected_elective_ids.append(c.id)
        else:
            st.caption("No electives available for this semester.")

        if st.button("Submit Registration", type="primary"):
            reg = Registration(
                student_id=student.id,
                academic_year=academic_year,
                semester=semester,
                year_of_study=student.year_of_study,
                status=EnrolmentStatus.ENROLLED,
                registered_by=user["id"]
            )
            db.add(reg)
            db.flush()

            all_selected_ids = [c.id for c in core_courses] + selected_elective_ids
            for cid in all_selected_ids:
                db.add(StudentCourse(registration_id=reg.id, course_id=cid))
            db.commit()
            log_action(db, "STUDENT_SELF_REGISTER", "Registration", reg.id,
                       f"{student.student_number} self-registered, {len(all_selected_ids)} course(s)")
            st.success(f"Registration submitted — {len(all_selected_ids)} course(s) enrolled.")
            st.rerun()

    db.close()
    st.stop()


# ════════════════════════════════════════════════════════════════
# STAFF (ADMIN / REGISTRAR): MANUAL ENROLMENT + REGISTRATION PERIOD CONTROL
# ════════════════════════════════════════════════════════════════
if role not in (UserRole.ADMIN.value, UserRole.REGISTRAR.value):
    st.error("Access restricted to Registrar and Admin.")
    db.close()
    st.stop()

tab_period, tab_reg, tab_view = st.tabs(
    ["Registration Period", "Manual Enrolment", "View Registrations"]
)

with tab_period:
    st.subheader("Self-Service Registration Period")
    st.caption(
        "Controls whether students can register themselves online. "
        "This is a single global switch per academic year + semester — "
        "it applies to the whole university, not per programme."
    )

    col1, col2 = st.columns(2)
    with col1:
        p_year = _academic_year_picker("Academic Year", UPCOMING_ACADEMIC_YEAR, "period_year")
    with col2:
        p_sem = st.selectbox("Semester", [1, 2], index=1, key="period_sem")

    period = db.query(RegistrationPeriod).filter_by(
        academic_year=p_year, semester=p_sem
    ).first()

    is_past_deadline = bool(period and period.deadline_at and datetime.utcnow() > period.deadline_at)
    current_state = "Open" if (period and period.is_open and not is_past_deadline) else "Closed"
    metric_card("Current Status", current_state,
                "#166534" if current_state == "Open" else "#991b1b")
    if period and period.deadline_at:
        st.caption(
            f"Deadline: {period.deadline_at.strftime('%d %B %Y, %H:%M')}"
            + (" — passed, registration auto-closed." if is_past_deadline else "")
        )

    deadline_date = st.date_input(
        "Registration Deadline (optional)",
        value=period.deadline_at.date() if period and period.deadline_at else None,
        key="period_deadline",
    )
    st.caption(
        "Once set, the system automatically treats registration as closed after this "
        "date — no need to remember to manually close it."
    )

    col_open, col_close = st.columns(2)
    with col_open:
        if st.button("Open Registration", type="primary", use_container_width=True,
                     disabled=(period is not None and period.is_open)):
            if period is None:
                period = RegistrationPeriod(academic_year=p_year, semester=p_sem)
                db.add(period)
            period.is_open = True
            period.opened_at = datetime.utcnow()
            period.opened_by = user["id"]
            if deadline_date:
                period.deadline_at = datetime.combine(deadline_date, datetime.max.time())
            db.commit()
            log_action(db, "OPEN_REGISTRATION_PERIOD", "RegistrationPeriod", period.id,
                       f"{p_year} Sem {p_sem}")
            st.success(f"Registration opened for {p_year}, Semester {p_sem}.")
            st.rerun()
    with col_close:
        if st.button("Close Registration", use_container_width=True,
                     disabled=(period is None or not period.is_open)):
            period.is_open = False
            period.closed_at = datetime.utcnow()
            db.commit()
            log_action(db, "CLOSE_REGISTRATION_PERIOD", "RegistrationPeriod", period.id,
                       f"{p_year} Sem {p_sem}")
            st.warning(f"Registration closed for {p_year}, Semester {p_sem}.")
            st.rerun()

with tab_reg:
    st.subheader("Enrol Student in Courses")
    col1, col2 = st.columns(2)
    with col1:
        snum = st.text_input("Student Number")
        academic_year = _academic_year_picker("Academic Year", UPCOMING_ACADEMIC_YEAR, "manual_enrol_year")
    with col2:
        semester = st.selectbox("Semester", [1, 2], index=1)

    student = None
    if snum:
        student = db.query(Student).filter_by(student_number=snum.strip()).first()
        if not student:
            st.error("Student not found.")
        else:
            st.success(f"Found: {student.full_name} — {student.programme.name if student.programme else 'N/A'}")

    if student:
        existing_reg = db.query(Registration).filter_by(
            student_id=student.id, academic_year=academic_year, semester=semester
        ).first()
        if existing_reg:
            st.warning(f"Student already registered for {academic_year} Sem {semester}. "
                       f"Status: {existing_reg.status.value}")
            enrolled_courses = db.query(StudentCourse).filter_by(registration_id=existing_reg.id).all()
            if enrolled_courses:
                st.markdown("**Enrolled Courses:**")
                for sc in enrolled_courses:
                    st.markdown(f"- {sc.course.code}: {sc.course.name}")
        else:
            all_candidates = db.query(Course).filter_by(
                programme_id=student.programme_id,
                year_level=student.year_of_study,
                is_active=True
            ).all()
            courses = [c for c in all_candidates if course_matches_semester(c.semester, semester)]

            if not courses:
                st.warning("No courses found for this programme/year/semester combination.")
            else:
                st.markdown("**Available Courses:**")
                course_sel = {}
                for c in courses:
                    type_label = "Core" if c.is_core else "Elective"
                    course_sel[c.id] = st.checkbox(
                        f"{c.code} — {c.name} ({c.credits} cr, {type_label})",
                        value=c.is_core, key=f"c_{c.id}"
                    )

                is_repeat = st.checkbox("Mark as Repeat Registration")

                if st.button("Confirm Registration", type="primary"):
                    selected = [cid for cid, sel in course_sel.items() if sel]
                    if not selected:
                        st.error("Select at least one course.")
                    else:
                        reg = Registration(
                            student_id=student.id,
                            academic_year=academic_year,
                            semester=semester,
                            year_of_study=student.year_of_study,
                            status=EnrolmentStatus.ENROLLED,
                            registered_by=user["id"]
                        )
                        db.add(reg)
                        db.flush()
                        for cid in selected:
                            sc = StudentCourse(registration_id=reg.id, course_id=cid, is_repeat=is_repeat)
                            db.add(sc)
                        db.commit()
                        log_action(db, "REGISTER_STUDENT", "Registration", reg.id,
                                   f"{snum} Sem {semester} {academic_year}")
                        st.success(f"Registration complete — {len(selected)} course(s) enrolled.")
                        st.rerun()

with tab_view:
    st.subheader("Registration Summary")
    col1, col2 = st.columns(2)
    with col1:
        fy = _academic_year_picker("Academic Year", UPCOMING_ACADEMIC_YEAR, "fy")
    with col2:
        fs = st.selectbox("Semester", [1, 2], index=1, key="fs")

    regs = db.query(Registration).filter_by(academic_year=fy, semester=fs).all()
    if regs:
        rows = []
        for r in regs:
            course_count = db.query(StudentCourse).filter_by(registration_id=r.id).count()
            rows.append({
                "Student #": r.student.student_number,
                "Name": r.student.full_name,
                "Programme": r.student.programme.code if r.student.programme else "",
                "Year": r.year_of_study,
                "Courses": course_count,
                "Status": r.status.value,
                "Registered": r.registered_at.strftime("%Y-%m-%d") if r.registered_at else "",
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(regs)} registration(s)")
        st.download_button("Export CSV", df.to_csv(index=False), "registrations.csv", "text/csv")
    else:
        st.info("No registrations found for the selected period.")

db.close()