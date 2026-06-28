"""
Courses Management — University of Edenberg SIS
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login, require_role, log_action
from utils.ui import render_sidebar, page_header
from models import Course, Programme, User, UserRole, StudentCourse, Result, Exemption
import pandas as pd

st.set_page_config(page_title="Courses — UoE SIS", layout="wide")
require_login()
render_sidebar()
page_header("Course Management", "View and manage programme courses")

user = st.session_state.user
role = user["role"]
db = get_db()

can_manage = role in (UserRole.ADMIN.value, UserRole.REGISTRAR.value, UserRole.LECTURER.value)

if can_manage:
    tab_list, tab_add = st.tabs(["Course Catalogue", "Add Course"])
else:
    tab_list = st.tabs(["Course Catalogue"])[0]

with tab_list:
    if can_manage:
        # Staff/coordinators: full catalogue, browsable across all programmes.
        programmes = db.query(Programme).filter_by(is_active=True).all()
        prog_options = {"All Programmes": None} | {p.name: p.id for p in programmes}
        col1, col2 = st.columns([2, 1])
        with col1:
            prog_filter = st.selectbox("Filter by Programme", list(prog_options.keys()))
        with col2:
            sem_filter = st.selectbox("Semester", ["All", "1", "2"])

        query = db.query(Course).filter_by(is_active=True)
        if prog_options.get(prog_filter):
            query = query.filter_by(programme_id=prog_options[prog_filter])

        courses = query.order_by(Course.code).all()
        if sem_filter != "All":
            # Use course_matches_semester so electives marked semester=0
            # ("both semesters") still appear regardless of which semester
            # is selected in the filter, instead of being silently excluded
            # by a raw equality check.
            from utils.results_logic import course_matches_semester
            courses = [c for c in courses if course_matches_semester(c.semester, int(sem_filter))]
    else:
        # Students: read-only, locked to their own programme, across every
        # valid year for their programme type — no programme/semester
        # browsing controls shown, and the query itself never considers
        # other programmes regardless of what the UI does or doesn't show.
        from models import Student
        student = db.query(Student).get(user.get("student_id")) if user.get("student_id") else None

        if not student or not student.programme:
            st.warning("Your account is not linked to a programme. Contact the Registrar.")
            courses = []
        else:
            prog = student.programme
            # Undergrad: Years 1-4. Masters (duration_years <= 2): Years 1-2.
            # Derived from the programme's own duration_years rather than
            # guessing from the programme code.
            max_year = 2 if prog.duration_years <= 2 else 4
            st.caption(f"Showing the course catalogue for **{prog.name}** "
                       f"(Year 1 to Year {max_year}).")
            courses = db.query(Course).filter(
                Course.programme_id == prog.id,
                Course.year_level <= max_year,
                Course.is_active == True
            ).order_by(Course.year_level, Course.code).all()

    if courses:
        data = []
        for c in courses:
            lec = db.query(User).get(c.lecturer_id) if c.lecturer_id else None
            sem_label = "Both" if c.semester == 0 else str(c.semester)
            data.append({
                "Code": c.code,
                "Course Name": c.name,
                "Programme": c.programme.code if c.programme else "",
                "Year Level": c.year_level,
                "Semester": sem_label,
                "Credits": c.credits,
                "Core": "Yes" if c.is_core else "No",
                "Lecturer": f"{lec.first_name} {lec.last_name}" if lec else "TBA",
            })
        display_df = pd.DataFrame(data)
        if not can_manage:
            # Students don't need the Programme column repeated on every
            # row since the whole table is already scoped to one programme.
            display_df = display_df.drop(columns=["Programme"])
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        st.caption(f"{len(courses)} course(s)")
    else:
        st.info("No courses found.")

if can_manage:
    with tab_add:
        st.subheader("Add New Course")
        programmes = db.query(Programme).filter_by(is_active=True).all()
        lecturers = db.query(User).filter(User.role.in_(["Lecturer", "Admin"])).all()

        with st.form("add_course"):
            c1, c2 = st.columns(2)
            with c1:
                code = st.text_input("Course Code *", placeholder="e.g. BCS301")
                name = st.text_input("Course Name *")
                prog_sel = st.selectbox("Programme *", [p.name for p in programmes])
            with c2:
                semester_choice = st.selectbox("Semester *", ["1", "2", "Both Semesters"])
                semester = 0 if semester_choice == "Both Semesters" else int(semester_choice)
                year_level = st.selectbox("Year Level", [1, 2, 3, 4])
                credits = st.number_input("Credits", 1, 6, 3)
                is_core = st.checkbox("Core Course", value=True,
                                       help="Uncheck to mark this as an elective. Electives offered "
                                            "in either semester should use the 'Both Semesters' option above.")
                lec_options = ["None"] + [f"{l.first_name} {l.last_name}" for l in lecturers]
                lec_sel = st.selectbox("Assigned Lecturer", lec_options)

            if st.form_submit_button("Add Course", type="primary"):
                prog_obj = next(p for p in programmes if p.name == prog_sel)
                lec_obj = next((l for l in lecturers if f"{l.first_name} {l.last_name}" == lec_sel), None)
                existing = db.query(Course).filter_by(code=code, programme_id=prog_obj.id, semester=semester).first()
                if existing:
                    st.error(f"Course {code} already exists for this programme/semester.")
                elif not code or not name:
                    st.error("Code and Name are required.")
                else:
                    c = Course(code=code, name=name, programme_id=prog_obj.id,
                               semester=semester, year_level=year_level, credits=credits,
                               is_core=is_core, lecturer_id=lec_obj.id if lec_obj else None)
                    db.add(c)
                    db.commit()
                    log_action(db, "ADD_COURSE", "Course", c.id, code)
                    st.success(f"Course {code} added.")

# ─────────────────────────── DANGER ZONE (Admin only) ──────────────────
if role == UserRole.ADMIN.value:
    st.markdown("---")
    with st.expander("⚠️ Danger Zone — Delete All Courses"):
        st.warning(
            "This permanently deletes **every course** in the catalogue, along "
            "with every student's enrolment record in those courses and any "
            "scores/exemptions already entered against them. Registrations "
            "themselves (the semester sign-up) are kept — only the per-course "
            "enrolment rows are removed. Use this to wipe the catalogue clean "
            "before a bulk re-upload."
        )

        course_count = db.query(Course).count()
        sc_count = db.query(StudentCourse).count()
        result_count = db.query(Result).join(StudentCourse).count()
        exemption_count = db.query(Exemption).join(StudentCourse).count()

        st.markdown(
            f"- **{course_count}** course(s)\n"
            f"- **{sc_count}** course enrolment record(s)\n"
            f"- **{result_count}** result(s) entered against those enrolments\n"
            f"- **{exemption_count}** exemption(s) recorded against those enrolments"
        )

        confirm_text = st.text_input(
            "Type DELETE to confirm", key="delete_all_courses_confirm",
            placeholder="DELETE"
        )
        if st.button("Delete All Courses", type="primary", disabled=(course_count == 0)):
            if confirm_text.strip() != "DELETE":
                st.error("Type DELETE (exactly, in capitals) to confirm.")
            else:
                sc_ids = [row.id for row in db.query(StudentCourse.id).all()]
                db.query(Exemption).filter(Exemption.student_course_id.in_(sc_ids)).delete(synchronize_session=False)
                db.query(Result).filter(Result.student_course_id.in_(sc_ids)).delete(synchronize_session=False)
                db.query(StudentCourse).filter(StudentCourse.id.in_(sc_ids)).delete(synchronize_session=False)
                db.query(Course).delete(synchronize_session=False)
                db.commit()
                log_action(db, "DELETE_ALL_COURSES", "Course", None,
                           f"Deleted {course_count} course(s), {sc_count} enrolment(s), "
                           f"{result_count} result(s), {exemption_count} exemption(s)")
                st.success(
                    f"Deleted {course_count} course(s) and {sc_count} enrolment record(s). "
                    f"You can now bulk re-upload courses via Data Import (ETL)."
                )
                st.rerun()

db.close()
