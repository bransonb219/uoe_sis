"""
Data Import (ETL) — University of Edenberg SIS
Bulk import of Students, Courses, Registrations, and Payments via Excel/CSV.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login, log_action, hash_password
from utils.ui import render_sidebar, page_header
from models import (
    Student, Programme, Course, Registration, StudentCourse,
    Payment, User, FeeStructure, Gender, StudentStatus, EnrolmentStatus,
    UserRole, PaymentStatus, ModeOfStudy, ProgrammeLevel, Result, Exemption,
    Intake,
)
from utils.results_logic import allocate_payment, get_academic_year_for_progress
from datetime import datetime
import pandas as pd
import io

st.set_page_config(page_title="Data Import — UoE SIS", page_icon="assets/favicon.ico", layout="wide")
require_login()
render_sidebar()
page_header("Data Import (ETL)", "Bulk import data from Excel or CSV files")

user = st.session_state.user
role = user["role"]

if role not in (UserRole.ADMIN.value, UserRole.REGISTRAR.value):
    st.error("Access restricted to Registrar and Admin.")
    st.stop()

db = get_db()

tab_programmes, tab_fees, tab_staff, tab_students, tab_courses, tab_payments, tab_template = st.tabs(
    ["Programmes", "Fee Structures", "Staff Users", "Students", "Courses", "Payments", "Templates"]
)


def read_table(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def clean_str(val, default=""):
    """
    Safely stringify a cell value for an optional text field. Empty cells
    come through pandas as float NaN, and str(NaN) == "nan" — without this,
    that literal text ends up stored in the database (e.g. "John nan Banda").
    """
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    return default if s.lower() in ("nan", "none", "") else s


def insert_courses_from_df(db, df, skip_existing=True):
    """
    Shared row-insert logic for both the additive 'Upload' and the
    'Replace All' flows. If skip_existing is False, every row is inserted
    unconditionally (used right after a fresh delete, where duplicate
    checks are pointless since the table is already empty).
    """
    created, skipped, errors = 0, 0, []
    for idx, row in df.iterrows():
        try:
            prog = db.query(Programme).filter_by(code=str(row["programme_code"]).strip()).first()
            if not prog:
                errors.append(f"Row {idx+2}: Unknown programme code")
                continue
            if skip_existing:
                existing = db.query(Course).filter_by(
                    code=str(row["code"]).strip(),
                    programme_id=prog.id,
                    semester=int(row["semester"])
                ).first()
                if existing:
                    skipped += 1
                    continue
            c = Course(
                code=str(row["code"]).strip(),
                name=str(row["name"]).strip(),
                programme_id=prog.id,
                semester=int(row["semester"]),
                year_level=int(row["year_level"]),
                credits=int(row["credits"]),
                is_core=bool(row.get("is_core", True))
            )
            db.add(c)
            created += 1
        except Exception as e:
            errors.append(f"Row {idx+2}: {e}")
    return created, skipped, errors


def delete_all_courses(db):
    """Cascade-safe wipe: Exemption -> Result -> StudentCourse -> Course. Registrations are kept."""
    sc_ids = [row.id for row in db.query(StudentCourse.id).all()]
    course_count = db.query(Course).count()
    sc_count = len(sc_ids)
    db.query(Exemption).filter(Exemption.student_course_id.in_(sc_ids)).delete(synchronize_session=False)
    db.query(Result).filter(Result.student_course_id.in_(sc_ids)).delete(synchronize_session=False)
    db.query(StudentCourse).filter(StudentCourse.id.in_(sc_ids)).delete(synchronize_session=False)
    db.query(Course).delete(synchronize_session=False)
    return course_count, sc_count


# ─────────────────────────── PROGRAMMES ──────────────────────
with tab_programmes:
    st.subheader("Import Programmes")
    st.caption(
        "Required columns: code, name, level, duration_years. "
        "Optional: department, faculty, total_credits. "
        "level must be: Diploma | Undergraduate | Postgraduate"
    )
    f_prog = st.file_uploader("Upload Programmes File", type=["xlsx", "xls", "csv"], key="up_prog")
    if f_prog:
        try:
            df = read_table(f_prog)
            df.columns = [c.lower().strip() for c in df.columns]
        except Exception as e:
            st.error(f"Could not read file: {e}")
            df = None
        if df is not None:
            required = {"code", "name", "level", "duration_years"}
            missing = required - set(df.columns)
            if missing:
                st.error(f"Missing required columns: {missing}")
            else:
                st.dataframe(df.head(10), use_container_width=True)
                if st.button("Run Import", type="primary", key="run_prog"):
                    created, skipped, errors = 0, 0, []
                    valid_levels = {l.value.lower(): l for l in ProgrammeLevel}
                    for idx, row in df.iterrows():
                        try:
                            code = str(row["code"]).strip().upper()
                            if db.query(Programme).filter_by(code=code).first():
                                skipped += 1
                                continue
                            level_str = str(row["level"]).strip().lower()
                            level = valid_levels.get(level_str)
                            if not level:
                                errors.append(f"Row {idx+2}: Invalid level '{row['level']}'")
                                continue
                            p = Programme(
                                code=code,
                                name=str(row["name"]).strip(),
                                level=level,
                                duration_years=int(row["duration_years"]),
                                department=clean_str(row.get("department")) or None,
                                faculty=clean_str(row.get("faculty")) or None,
                                total_credits=int(row["total_credits"]) if "total_credits" in row and str(row["total_credits"]).strip() else 360,
                            )
                            db.add(p)
                            created += 1
                        except Exception as e:
                            errors.append(f"Row {idx+2}: {e}")
                    db.commit()
                    log_action(db, "ETL_IMPORT_PROGRAMMES", "Programme", None,
                               f"Created {created}, skipped {skipped}, errors {len(errors)}")
                    st.success(f"✅ Imported {created} programme(s). Skipped {skipped}.")
                    if errors:
                        with st.expander(f"{len(errors)} error(s)"):
                            for e in errors:
                                st.warning(e)


# ─────────────────────────── FEE STRUCTURES ───────────────────
with tab_fees:
    st.subheader("Import Fee Structures")
    st.caption(
        "Required columns: programme_code, academic_year, semester, mode_of_study, total_fee. "
        "mode_of_study: Full-Time | ODeL"
    )
    f_fees = st.file_uploader("Upload Fee Structures File", type=["xlsx", "xls", "csv"], key="up_fees")
    if f_fees:
        try:
            df = read_table(f_fees)
            df.columns = [c.lower().strip() for c in df.columns]
        except Exception as e:
            st.error(f"Could not read file: {e}")
            df = None
        if df is not None:
            required = {"programme_code", "academic_year", "semester", "mode_of_study", "total_fee"}
            missing = required - set(df.columns)
            if missing:
                st.error(f"Missing required columns: {missing}")
            else:
                st.dataframe(df.head(10), use_container_width=True)
                if st.button("Run Import", type="primary", key="run_fees"):
                    created, updated, errors = 0, 0, []
                    mode_map = {m.value.lower(): m for m in ModeOfStudy}
                    for idx, row in df.iterrows():
                        try:
                            prog = db.query(Programme).filter_by(code=str(row["programme_code"]).strip().upper()).first()
                            if not prog:
                                errors.append(f"Row {idx+2}: Unknown programme '{row['programme_code']}'")
                                continue
                            mode_str = str(row["mode_of_study"]).strip().lower()
                            mode = mode_map.get(mode_str)
                            if not mode:
                                errors.append(f"Row {idx+2}: Invalid mode_of_study '{row['mode_of_study']}'")
                                continue
                            existing = db.query(FeeStructure).filter_by(
                                programme_id=prog.id,
                                academic_year=str(row["academic_year"]).strip(),
                                semester=int(row["semester"]),
                                mode_of_study=mode,
                            ).first()
                            if existing:
                                existing.total_fee = float(row["total_fee"])
                                updated += 1
                            else:
                                db.add(FeeStructure(
                                    programme_id=prog.id,
                                    academic_year=str(row["academic_year"]).strip(),
                                    semester=int(row["semester"]),
                                    mode_of_study=mode,
                                    total_fee=float(row["total_fee"]),
                                ))
                                created += 1
                        except Exception as e:
                            errors.append(f"Row {idx+2}: {e}")
                    db.commit()
                    log_action(db, "ETL_IMPORT_FEE_STRUCTURES", "FeeStructure", None,
                               f"Created {created}, updated {updated}, errors {len(errors)}")
                    st.success(f"✅ Imported {created} new, updated {updated} existing fee structure(s).")
                    if errors:
                        with st.expander(f"{len(errors)} error(s)"):
                            for e in errors:
                                st.warning(e)


# ─────────────────────────── STAFF USERS ──────────────────────
with tab_staff:
    st.subheader("Import Staff Users")
    st.caption(
        "Required columns: username, first_name, last_name, role. "
        "Optional: email. role must be: Admin | Registrar | Finance | Lecturer. "
        "Default password: Staff@2026 — users should change it after first login."
    )
    f_staff = st.file_uploader("Upload Staff Users File", type=["xlsx", "xls", "csv"], key="up_staff")
    if f_staff:
        try:
            df = read_table(f_staff)
            df.columns = [c.lower().strip() for c in df.columns]
        except Exception as e:
            st.error(f"Could not read file: {e}")
            df = None
        if df is not None:
            required = {"username", "first_name", "last_name", "role"}
            missing = required - set(df.columns)
            if missing:
                st.error(f"Missing required columns: {missing}")
            else:
                st.dataframe(df.head(10), use_container_width=True)
                if st.button("Run Import", type="primary", key="run_staff"):
                    created, skipped, errors = 0, 0, []
                    staff_roles = {r.value.lower(): r for r in UserRole if r != UserRole.STUDENT}
                    for idx, row in df.iterrows():
                        try:
                            uname = str(row["username"]).strip()
                            if db.query(User).filter_by(username=uname).first():
                                skipped += 1
                                continue
                            role_str = str(row["role"]).strip().lower()
                            role_val = staff_roles.get(role_str)
                            if not role_val:
                                errors.append(f"Row {idx+2}: Invalid role '{row['role']}'")
                                continue
                            u = User(
                                username=uname,
                                password_hash=hash_password("Staff@2026"),
                                role=role_val,
                                first_name=str(row["first_name"]).strip(),
                                last_name=str(row["last_name"]).strip(),
                                email=clean_str(row.get("email")) or None,
                                is_active=True,
                            )
                            db.add(u)
                            created += 1
                        except Exception as e:
                            errors.append(f"Row {idx+2}: {e}")
                    db.commit()
                    log_action(db, "ETL_IMPORT_STAFF", "User", None,
                               f"Created {created}, skipped {skipped}, errors {len(errors)}")
                    st.success(f"✅ Imported {created} staff user(s). Skipped {skipped} duplicates. Default password: Staff@2026")
                    if errors:
                        with st.expander(f"{len(errors)} error(s)"):
                            for e in errors:
                                st.warning(e)


# ─────────────────────────── STUDENTS ────────────────────────
with tab_students:
    st.subheader("Import Students")
    st.caption(
        "Required columns: student_number, first_name, last_name, gender, programme_code, "
        "intake_code, year_of_study, current_semester, mode_of_study. Optional: email, phone, "
        "other_names. mode_of_study: Full-Time | ODeL. Username = student_number. "
        "Default password: Student@2026"
    )
    st.info(
        "**academic_year is no longer a column you fill in.** It's derived automatically from "
        "intake_code + year_of_study + current_semester, via the cohort-progress mapping set up "
        "in Settings → Intakes & Cohorts. This is what keeps every student's academic year "
        "consistent with their intake instead of being separately (and sometimes wrongly) typed. "
        "If a row's intake/year/semester combination has no mapping yet, that row is rejected with "
        "a clear error — set up the mapping there first (or via Promote Cohort), then re-import."
    )
    f_students = st.file_uploader("Upload Students File", type=["xlsx", "xls", "csv"], key="up_students")

    if f_students:
        try:
            df = read_table(f_students)
        except Exception as e:
            st.error(f"Could not read file: {e}")
            df = None

        if df is not None:
            df.columns = [c.lower().strip() for c in df.columns]
            required = {"student_number", "first_name", "last_name", "gender", "programme_code",
                        "intake_code", "year_of_study", "current_semester", "mode_of_study"}
            missing = required - set(df.columns)

            if missing:
                st.error(f"Missing required columns: {missing}")
            else:
                st.dataframe(df.head(10), use_container_width=True)
                st.caption(f"{len(df)} row(s) found. Preview shows first 10.")

                if st.button("Run Import", type="primary", key="run_students"):
                    created, skipped, errors = 0, 0, []
                    mode_map = {m.value.lower(): m for m in ModeOfStudy}
                    for idx, row in df.iterrows():
                        try:
                            snum = str(row["student_number"]).strip()
                            if db.query(Student).filter_by(student_number=snum).first():
                                skipped += 1
                                continue
                            prog = db.query(Programme).filter_by(code=str(row["programme_code"]).strip().upper()).first()
                            if not prog:
                                errors.append(f"Row {idx+2}: Unknown programme code '{row['programme_code']}'")
                                continue
                            mode_str = str(row["mode_of_study"]).strip().lower()
                            mode = mode_map.get(mode_str)
                            if not mode:
                                errors.append(f"Row {idx+2}: Invalid mode_of_study '{row['mode_of_study']}'")
                                continue

                            intake_code = str(row["intake_code"]).strip().upper()
                            intake = db.query(Intake).filter_by(code=intake_code).first()
                            if not intake:
                                errors.append(f"Row {idx+2}: Unknown intake_code '{row['intake_code']}'")
                                continue

                            year_of_study = int(row["year_of_study"])
                            current_semester = int(row["current_semester"])
                            academic_year = get_academic_year_for_progress(
                                db, intake.id, year_of_study, current_semester
                            )
                            if not academic_year:
                                errors.append(
                                    f"Row {idx+2}: No cohort-progress mapping for intake "
                                    f"'{intake_code}' Year {year_of_study} Semester {current_semester} "
                                    f"— set this up in Settings → Intakes & Cohorts (or Promote Cohort) first."
                                )
                                continue

                            s = Student(
                                student_number=snum,
                                first_name=str(row["first_name"]).strip(),
                                last_name=str(row["last_name"]).strip(),
                                other_names=clean_str(row.get("other_names")) or None,
                                gender=str(row["gender"]).strip().capitalize(),
                                email=clean_str(row.get("email")) or None,
                                phone=clean_str(row.get("phone")) or None,
                                programme_id=prog.id,
                                intake_id=intake.id,
                                year_of_study=year_of_study,
                                current_semester=current_semester,
                                academic_year=academic_year,
                                mode_of_study=mode,
                                status=StudentStatus.ACTIVE
                            )
                            db.add(s)
                            db.flush()

                            # Username = student number as-is (three-tier login handles legacy variants)
                            u = User(
                                username=snum,
                                password_hash=hash_password("Student@2026"),
                                role=UserRole.STUDENT,
                                first_name=s.first_name, last_name=s.last_name,
                                email=s.email, is_active=True, student_id=s.id
                            )
                            db.add(u)
                            created += 1
                        except Exception as e:
                            errors.append(f"Row {idx+2}: {e}")

                    db.commit()
                    log_action(db, "ETL_IMPORT_STUDENTS", "Student", None,
                               f"Created {created}, skipped {skipped}, errors {len(errors)}")
                    st.success(
                        f"✅ Imported {created} student(s). Skipped {skipped} duplicate(s). "
                        f"Students log in with their student number as username."
                    )
                    if errors:
                        with st.expander(f"{len(errors)} error(s)"):
                            for e in errors:
                                st.warning(e)


# ─────────────────────────── COURSES ──────────────────────────
with tab_courses:
    st.subheader("Import Courses")
    st.caption(
        "Required columns: code, name, programme_code, semester, year_level, credits. "
        "Optional: is_core (true/false)."
    )
    f_courses = st.file_uploader("Upload Courses File", type=["xlsx", "xls", "csv"], key="up_courses")

    if f_courses:
        try:
            df = read_table(f_courses)
            df.columns = [c.lower().strip() for c in df.columns]
        except Exception as e:
            st.error(f"Could not read file: {e}")
            df = None

        if df is not None:
            required = {"code", "name", "programme_code", "semester", "year_level", "credits"}
            missing = required - set(df.columns)
            if missing:
                st.error(f"Missing required columns: {missing}")
            else:
                st.dataframe(df.head(10), use_container_width=True)

                col_upload, col_replace = st.columns(2)

                with col_upload:
                    st.caption("**Upload** — adds new courses, skips duplicates. Existing courses untouched.")
                    if st.button("Upload (Add/Update)", type="primary", key="run_courses"):
                        created, skipped, errors = insert_courses_from_df(db, df, skip_existing=True)
                        db.commit()
                        log_action(db, "ETL_IMPORT_COURSES", "Course", None,
                                   f"Created {created}, skipped {skipped}")
                        st.success(f"✅ Imported {created} course(s). Skipped {skipped} duplicate(s).")
                        if errors:
                            with st.expander(f"{len(errors)} error(s)"):
                                for e in errors:
                                    st.warning(e)

                with col_replace:
                    st.caption("**Replace** — wipes the *entire* course catalogue (and dependent "
                               "enrolments/results/exemptions) first, then loads this file fresh. Admin only.")
                    if role != UserRole.ADMIN.value:
                        st.info("Only Admin can replace the full catalogue.")
                    else:
                        existing_course_count = db.query(Course).count()
                        existing_sc_count = db.query(StudentCourse).count()
                        st.markdown(
                            f"Will delete **{existing_course_count}** existing course(s) and "
                            f"**{existing_sc_count}** enrolment record(s) (with their results/exemptions) "
                            f"before loading **{len(df)}** row(s) from this file."
                        )
                        replace_confirm = st.text_input(
                            "Type REPLACE to confirm", key="replace_courses_confirm", placeholder="REPLACE"
                        )
                        if st.button("Replace All Courses", key="replace_courses_btn"):
                            if replace_confirm.strip() != "REPLACE":
                                st.error("Type REPLACE (exactly, in capitals) to confirm.")
                            else:
                                deleted_courses, deleted_sc = delete_all_courses(db)
                                created, skipped, errors = insert_courses_from_df(db, df, skip_existing=False)
                                db.commit()
                                log_action(db, "REPLACE_ALL_COURSES", "Course", None,
                                           f"Deleted {deleted_courses} course(s)/{deleted_sc} enrolment(s), "
                                           f"loaded {created} new course(s)")
                                st.success(
                                    f"✅ Replaced catalogue: removed {deleted_courses} old course(s), "
                                    f"loaded {created} new course(s)."
                                )
                                if errors:
                                    with st.expander(f"{len(errors)} error(s)"):
                                        for e in errors:
                                            st.warning(e)
                                st.rerun()


# ─────────────────────────── PAYMENTS ─────────────────────────
with tab_payments:
    st.subheader("Import Payments")
    st.caption(
        "Required columns: student_number, amount. Optional: method, reference. "
        "Each amount is automatically allocated across the student's oldest "
        "unpaid semester(s) first — no single semester is ever pushed into "
        "overpayment. Leftover after clearing every known due is held as an "
        "advance toward their nearest future semester; only genuine excess "
        "beyond that is reported back and not recorded. academic_year/"
        "semester columns, if present, are kept as a note for reference "
        "only and do NOT dictate where the payment is applied. Rows are "
        "processed in file order, so list a student's payments "
        "chronologically if they have more than one."
    )
    f_payments = st.file_uploader("Upload Payments File", type=["xlsx", "xls", "csv"], key="up_payments")

    if f_payments:
        try:
            df = read_table(f_payments)
            df.columns = [c.lower().strip() for c in df.columns]
        except Exception as e:
            st.error(f"Could not read file: {e}")
            df = None

        if df is not None:
            required = {"student_number", "amount"}
            missing = required - set(df.columns)
            if missing:
                st.error(f"Missing required columns: {missing}")
            else:
                st.dataframe(df.head(10), use_container_width=True)
                if st.button("Run Import", type="primary", key="run_payments"):
                    created, fully_unallocated, errors = 0, 0, []
                    total_unallocated = 0.0
                    for idx, row in df.iterrows():
                        try:
                            student = db.query(Student).filter_by(
                                student_number=str(row["student_number"]).strip()
                            ).first()
                            if not student:
                                errors.append(f"Row {idx+2}: Student not found")
                                continue
                            file_note = None
                            if row.get("academic_year") or row.get("semester"):
                                file_note = f"File stated: {clean_str(row.get('academic_year'))} Sem{clean_str(row.get('semester'))}"
                            result = allocate_payment(
                                db, student, float(row["amount"]),
                                method=clean_str(row.get("method"), "Bank Transfer"),
                                reference=clean_str(row.get("reference")) or None,
                                received_by=user["id"], notes=file_note,
                            )
                            created += len(result["payments_created"])
                            if result["unallocated"] > 0:
                                fully_unallocated += 1
                                total_unallocated += result["unallocated"]
                                errors.append(
                                    f"Row {idx+2} ({student.student_number}): K{result['unallocated']:,.2f} "
                                    f"could not be allocated — exceeds all known dues plus one semester "
                                    f"ahead, NOT recorded."
                                )
                        except Exception as e:
                            errors.append(f"Row {idx+2}: {e}")
                    db.commit()
                    log_action(db, "ETL_IMPORT_PAYMENTS", "Payment", None,
                               f"Created {created} payment record(s) across rows; "
                               f"{fully_unallocated} row(s) had unallocated amounts totalling K{total_unallocated:,.2f}")
                    st.success(f"✅ Created {created} payment record(s) from the file's rows.")
                    if total_unallocated > 0:
                        st.warning(
                            f"K{total_unallocated:,.2f} across {fully_unallocated} row(s) could not be "
                            f"allocated and was NOT recorded — see details below."
                        )
                    if errors:
                        with st.expander(f"{len(errors)} note(s)/error(s)"):
                            for e in errors:
                                st.warning(e)


# ─────────────────────────── TEMPLATES ────────────────────────
with tab_template:
    st.subheader("Download Import Templates")
    st.caption("Download a sample CSV for each import type. Fill in your data following the same columns.")

    programmes_template = pd.DataFrame([
        {"code": "BCS", "name": "Bachelor of Computer Science", "level": "Undergraduate",
         "duration_years": 3, "department": "Computing", "faculty": "Science & Technology", "total_credits": 360},
        {"code": "MBA", "name": "Master of Business Administration", "level": "Postgraduate",
         "duration_years": 2, "department": "Business", "faculty": "Commerce", "total_credits": 120},
    ])
    fee_structures_template = pd.DataFrame([
        {"programme_code": "BCS", "academic_year": "2025/2026", "semester": 1, "mode_of_study": "Full-Time", "total_fee": 8500},
        {"programme_code": "BCS", "academic_year": "2025/2026", "semester": 1, "mode_of_study": "ODeL", "total_fee": 6000},
        {"programme_code": "BCS", "academic_year": "2025/2026", "semester": 2, "mode_of_study": "Full-Time", "total_fee": 8500},
        {"programme_code": "BCS", "academic_year": "2025/2026", "semester": 2, "mode_of_study": "ODeL", "total_fee": 6000},
    ])
    staff_template = pd.DataFrame([
        {"username": "registrar", "first_name": "Grace", "last_name": "Mwale",
         "role": "Registrar", "email": "registrar@ue.ac.zm"},
        {"username": "dr.mulenga", "first_name": "Charles", "last_name": "Mulenga",
         "role": "Lecturer", "email": "c.mulenga@ue.ac.zm"},
    ])
    students_template = pd.DataFrame([{
        "student_number": "BCS2025001", "first_name": "Jane", "last_name": "Doe",
        "other_names": "", "gender": "Female", "email": "jane.doe@student.ue.ac.zm",
        "phone": "+260971234567", "programme_code": "BCS", "intake_code": "JAN2025",
        "year_of_study": 1, "current_semester": 1, "mode_of_study": "Full-Time"
    }])
    courses_template = pd.DataFrame([{
        "code": "BCS301", "name": "Software Engineering", "programme_code": "BCS",
        "semester": 1, "year_level": 3, "credits": 4, "is_core": True
    }])
    payments_template = pd.DataFrame([{
        "student_number": "BCS2025001", "academic_year": "2025/2026", "semester": 1,
        "amount": 5000, "method": "Bank Transfer", "reference": "PAY100001"
    }])

    st.markdown("**Step 1 — Programmes** (import first)")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("01_programmes.csv", programmes_template.to_csv(index=False),
                           "01_programmes.csv", "text/csv", use_container_width=True)
    with c2:
        st.download_button("02_fee_structures.csv", fee_structures_template.to_csv(index=False),
                           "02_fee_structures.csv", "text/csv", use_container_width=True)

    st.markdown("**Step 2 — Users & Students**")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("03_staff_users.csv", staff_template.to_csv(index=False),
                           "03_staff_users.csv", "text/csv", use_container_width=True)
    with c2:
        st.download_button("05_students.csv", students_template.to_csv(index=False),
                           "05_students.csv", "text/csv", use_container_width=True)

    st.markdown("**Step 3 — Courses & Payments**")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("04_courses.csv", courses_template.to_csv(index=False),
                           "04_courses.csv", "text/csv", use_container_width=True)
    with c2:
        st.download_button("06_payments.csv", payments_template.to_csv(index=False),
                           "06_payments.csv", "text/csv", use_container_width=True)

db.close()
