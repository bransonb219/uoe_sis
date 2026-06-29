"""
Students Management Page — University of Edenberg SIS
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login, log_action
from utils.ui import render_sidebar, page_header, status_badge
from models import Student, Programme, User, StudentStatus, Gender, UserRole, ModeOfStudy, Intake
from utils.auth import hash_password
from utils.results_logic import get_academic_year_for_progress
from datetime import datetime
import pandas as pd

st.set_page_config(page_title="Students — UoE SIS", page_icon="assets/favicon.ico", layout="wide")

require_login()
render_sidebar()
page_header("Student Management", "Register, view, and manage student records")

user = st.session_state.user
role = user["role"]
db = get_db()

can_manage = role in (UserRole.ADMIN.value, UserRole.REGISTRAR.value, UserRole.ADMIN_SUPPORT.value)

if can_manage:
    tab_list, tab_add, tab_edit = st.tabs(["Student List", "Add Student", "Edit Student"])
else:
    tab_list = st.tabs(["Student List"])[0]

with tab_list:
    st.subheader("All Students")
    programmes = db.query(Programme).filter_by(is_active=True).all()
    prog_options = {"All": None} | {p.name: p.id for p in programmes}

    query = db.query(Student)

    if can_manage:
        intakes = db.query(Intake).order_by(Intake.code).all()
        intake_options = {"All": None} | {i.code: i.id for i in intakes}

        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            search = st.text_input("Search by name or student number", placeholder="e.g. Alice or BCS2024001")
        with col2:
            prog_filter = st.selectbox("Programme", list(prog_options.keys()))
        with col3:
            status_filter = st.selectbox("Status", ["All"] + [s.value for s in StudentStatus])

        col4, col5, col6 = st.columns(3)
        with col4:
            intake_filter = st.selectbox("Intake", list(intake_options.keys()))
        with col5:
            year_filter = st.selectbox("Year of Study", ["All", 1, 2, 3, 4, 5, 6])
        with col6:
            semester_filter = st.selectbox("Semester", ["All", 1, 2])

        if search:
            query = query.filter(
                (Student.first_name.ilike(f"%{search}%")) |
                (Student.last_name.ilike(f"%{search}%")) |
                (Student.student_number.ilike(f"%{search}%"))
            )
        if prog_options[prog_filter]:
            query = query.filter_by(programme_id=prog_options[prog_filter])
        if status_filter != "All":
            query = query.filter_by(status=status_filter)
        if intake_options[intake_filter]:
            query = query.filter_by(intake_id=intake_options[intake_filter])
        if year_filter != "All":
            query = query.filter_by(year_of_study=year_filter)
        if semester_filter != "All":
            query = query.filter_by(current_semester=semester_filter)
    else:
        # Students only ever see Active students within their own programme —
        # no programme/status filters shown, and the query is locked down
        # server-side regardless of what the UI does or doesn't show.
        search = st.text_input("Search by name or student number", placeholder="e.g. Alice or BCS2024001")
        own_programme_id = None
        if user.get("student_id"):
            own_student = db.query(Student).get(user["student_id"])
            if own_student:
                own_programme_id = own_student.programme_id

        query = query.filter_by(status=StudentStatus.ACTIVE)
        if own_programme_id:
            query = query.filter_by(programme_id=own_programme_id)
        if search:
            query = query.filter(
                (Student.first_name.ilike(f"%{search}%")) |
                (Student.last_name.ilike(f"%{search}%")) |
                (Student.student_number.ilike(f"%{search}%"))
            )

    students = query.order_by(Student.student_number).all()

    if students:
        data = []
        for s in students:
            data.append({
                "Student #": s.student_number,
                "Full Name": s.full_name,
                "Gender": s.gender.value if s.gender else "",
                "Programme": s.programme.code if s.programme else "",
                "Intake": s.intake.code if s.intake else "",
                "Year": s.year_of_study,
                "Semester": s.current_semester,
                "Academic Year": s.academic_year or "",
                "Status": s.status.value if s.status else "",
                "Email": s.email or "",
            })
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(students)} student(s) found")

        csv = df.to_csv(index=False)
        st.download_button("Export CSV", csv, "students.csv", "text/csv")
    else:
        st.info("No students match your search.")

if can_manage:
    with tab_add:
        st.subheader("Register New Student")
        intake_opts = db.query(Intake).order_by(Intake.code).all()
        st.caption(
            "Academic Year is no longer picked separately — it's derived "
            "automatically from Intake + Year of Study + Current Semester, "
            "via the cohort-progress mapping in Settings → Intakes & "
            "Cohorts. This keeps it from ever drifting out of sync with the "
            "student's actual cohort."
        )
        with st.form("add_student_form"):
            c1, c2 = st.columns(2)
            with c1:
                first_name = st.text_input("First Name *")
                last_name = st.text_input("Last Name *")
                other_names = st.text_input("Other Names")
                student_number = st.text_input("Student Number *")
                gender = st.selectbox("Gender", [g.value for g in Gender])
                intake_sel = st.selectbox("Intake *", [i.code for i in intake_opts]) if intake_opts else None
            with c2:
                prog_sel = st.selectbox("Programme *", [p.name for p in programmes])
                year_of_study = st.number_input("Year of Study", 1, 6, 1)
                current_semester_sel = st.selectbox("Current Semester", [1, 2])
                mode_sel = st.selectbox("Mode of Study *", [m.value for m in ModeOfStudy])
                email = st.text_input("Email")
                phone = st.text_input("Phone")
                dob = st.date_input("Date of Birth", value=datetime(2000, 1, 1))

            with st.expander("Additional Bio Data (optional)"):
                c3, c4 = st.columns(2)
                with c3:
                    national_id_add = st.text_input("National ID / Passport")
                    nationality_add = st.text_input("Nationality")
                    address_add = st.text_area("Address")
                with c4:
                    marital_status_add = st.text_input("Marital Status")
                    nok_name_add = st.text_input("Next of Kin Name")
                    nok_phone_add = st.text_input("Next of Kin Phone")

            submitted = st.form_submit_button("Register Student", type="primary")

        if submitted:
            intake_obj = next((i for i in intake_opts if i.code == intake_sel), None) if intake_sel else None
            derived_academic_year = (
                get_academic_year_for_progress(db, intake_obj.id, year_of_study, current_semester_sel)
                if intake_obj else None
            )
            if not all([first_name, last_name, student_number]):
                st.error("First Name, Last Name, and Student Number are required.")
            elif db.query(Student).filter_by(student_number=student_number).first():
                st.error(f"Student number {student_number} already exists.")
            elif not intake_obj:
                st.error("Select an Intake — add one in Settings → Intakes & Cohorts first if none exist.")
            elif not derived_academic_year:
                st.error(
                    f"No cohort-progress mapping for intake '{intake_sel}' Year {year_of_study} "
                    f"Semester {current_semester_sel}. Set this up in Settings → Intakes & Cohorts "
                    f"(or via Promote Cohort) before registering students into this period."
                )
            else:
                prog_obj = next(p for p in programmes if p.name == prog_sel)
                academic_year = derived_academic_year
                s = Student(
                    student_number=student_number,
                    first_name=first_name, last_name=last_name, other_names=other_names or None,
                    gender=gender, date_of_birth=datetime.combine(dob, datetime.min.time()),
                    email=email or None, phone=phone or None,
                    national_id=national_id_add or None,
                    nationality=nationality_add or None,
                    address=address_add or None,
                    marital_status=marital_status_add or None,
                    next_of_kin_name=nok_name_add or None,
                    next_of_kin_phone=nok_phone_add or None,
                    programme_id=prog_obj.id,
                    intake_id=intake_obj.id if intake_obj else None,
                    year_of_study=year_of_study,
                    current_semester=current_semester_sel,
                    academic_year=academic_year,
                    mode_of_study=mode_sel,
                    status=StudentStatus.ACTIVE
                )
                db.add(s)
                db.flush()
                # Create login user
                u = User(
                    username=student_number.lower(),
                    password_hash=hash_password("Student@2026"),
                    role=UserRole.STUDENT,
                    first_name=first_name, last_name=last_name,
                    email=email, is_active=True,
                    student_id=s.id
                )
                db.add(u)
                db.commit()
                log_action(db, "ADD_STUDENT", "Student", s.id, f"Registered {student_number}")
                st.success(f"Student {student_number} registered. Default password: Student@2026")

if can_manage:
    with tab_edit:
        st.subheader("Edit Student Record")
        st.caption(
            "Full registration details and bio data. Bio fields below "
            "Registration are optional — leave blank if not collected."
        )
        snum = st.text_input("Enter Student Number to Edit")
        if snum:
            s = db.query(Student).filter_by(student_number=snum.strip()).first()
            if not s:
                st.error("Student not found.")
            else:
                edit_intakes = db.query(Intake).order_by(Intake.code).all()
                edit_programmes = db.query(Programme).filter_by(is_active=True).all()
                st.caption(
                    f"Current academic year on record: **{s.academic_year or 'none'}**. "
                    f"This is derived from Intake + Year of Study + Current Semester on save — "
                    f"it's not editable directly."
                )

                with st.form("edit_student"):
                    st.markdown("##### Registration Details")
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        prog_codes = [p.name for p in edit_programmes]
                        cur_prog_idx = prog_codes.index(s.programme.name) if s.programme and s.programme.name in prog_codes else 0
                        prog_edit_sel = st.selectbox("Programme", prog_codes, index=cur_prog_idx) if prog_codes else None

                        intake_codes = [i.code for i in edit_intakes]
                        cur_intake_idx = intake_codes.index(s.intake.code) if s.intake and s.intake.code in intake_codes else 0
                        intake_edit_sel = st.selectbox("Intake", intake_codes, index=cur_intake_idx) if intake_codes else None
                    with c2:
                        yr = st.number_input("Year of Study", 1, 6, value=s.year_of_study or 1)
                        sem_edit = st.selectbox("Current Semester", [1, 2],
                                                 index=(s.current_semester - 1) if s.current_semester in (1, 2) else 0)
                    with c3:
                        mode_edit_sel = st.selectbox("Mode of Study", [m.value for m in ModeOfStudy],
                                                      index=[m.value for m in ModeOfStudy].index(s.mode_of_study.value) if s.mode_of_study else 0)
                        st_status = st.selectbox("Status", [x.value for x in StudentStatus],
                                                  index=[x.value for x in StudentStatus].index(s.status.value))
                        fee_adj_edit = st.number_input(
                            "Fee Adjustment (K)", value=float(s.fee_adjustment or 0.0), step=50.0,
                            help="Net scholarship/discount (negative) or additional charge (positive) vs the standard fee structure."
                        )

                    st.markdown("---")
                    st.markdown("##### Personal Details")
                    c4, c5 = st.columns(2)
                    with c4:
                        fn = st.text_input("First Name", value=s.first_name)
                        ln = st.text_input("Last Name", value=s.last_name)
                        on = st.text_input("Other Names", value=s.other_names or "")
                        gender_edit = st.selectbox("Gender", [g.value for g in Gender],
                                                    index=[g.value for g in Gender].index(s.gender.value) if s.gender else 0)
                        dob_edit = st.date_input("Date of Birth", value=s.date_of_birth.date() if s.date_of_birth else datetime(2000, 1, 1).date())
                    with c5:
                        em = st.text_input("Email", value=s.email or "")
                        ph = st.text_input("Phone", value=s.phone or "")
                        national_id_edit = st.text_input("National ID / Passport", value=s.national_id or "")
                        nationality_edit = st.text_input("Nationality", value=s.nationality or "")

                    st.markdown("---")
                    st.markdown("##### Additional Bio Data (optional)")
                    c6, c7 = st.columns(2)
                    with c6:
                        address_edit = st.text_area("Address", value=s.address or "")
                        marital_status_edit = st.text_input("Marital Status", value=s.marital_status or "")
                    with c7:
                        nok_name_edit = st.text_input("Next of Kin Name", value=s.next_of_kin_name or "")
                        nok_phone_edit = st.text_input("Next of Kin Phone", value=s.next_of_kin_phone or "")

                    if st.form_submit_button("Save Changes", type="primary"):
                        target_intake = next((i for i in edit_intakes if i.code == intake_edit_sel), None) if intake_edit_sel else s.intake
                        # UNCONFIRMED/LEGACY are deliberate placeholder buckets with no
                        # cohort-progress mapping by design — don't block ordinary edits
                        # (e.g. fixing a phone number) for students still in them pending
                        # reconciliation. Only real intakes require a valid mapping.
                        is_placeholder_intake = bool(target_intake and target_intake.code in ("UNCONFIRMED", "LEGACY"))
                        if is_placeholder_intake:
                            derived_academic_year = s.academic_year
                        elif target_intake:
                            derived_academic_year = get_academic_year_for_progress(db, target_intake.id, yr, sem_edit)
                        else:
                            derived_academic_year = None
                        if not target_intake:
                            st.error("Select an Intake — add one in Settings → Intakes & Cohorts first if none exist.")
                        elif not derived_academic_year and not is_placeholder_intake:
                            st.error(
                                f"No cohort-progress mapping for intake '{target_intake.code}' Year {yr} "
                                f"Semester {sem_edit}. Set this up in Settings → Intakes & Cohorts "
                                f"(or via Promote Cohort) before saving this combination."
                            )
                        else:
                            s.first_name = fn; s.last_name = ln; s.other_names = on or None
                            s.email = em or None; s.phone = ph or None
                            s.gender = gender_edit
                            s.date_of_birth = datetime.combine(dob_edit, datetime.min.time())
                            s.national_id = national_id_edit or None
                            s.nationality = nationality_edit or None
                            s.address = address_edit or None
                            s.marital_status = marital_status_edit or None
                            s.next_of_kin_name = nok_name_edit or None
                            s.next_of_kin_phone = nok_phone_edit or None

                            if prog_edit_sel:
                                s.programme_id = next(p.id for p in edit_programmes if p.name == prog_edit_sel)
                            s.intake_id = target_intake.id
                            s.year_of_study = yr
                            s.current_semester = sem_edit
                            s.academic_year = derived_academic_year
                            s.mode_of_study = mode_edit_sel
                            s.fee_adjustment = fee_adj_edit
                            s.status = st_status
                            s.updated_at = datetime.utcnow()
                            db.commit()
                            log_action(db, "EDIT_STUDENT", "Student", s.id, f"Updated {snum}")
                            st.success("Record updated successfully.")
                            st.rerun()

db.close()
