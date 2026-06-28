"""
University of Edenberg - Student Information System
Main entry point / Login page
"""
import streamlit as st
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from utils.db import get_db
from utils.auth import login_user
from utils.ui import render_sidebar, page_header, metric_card, status_badge
from models import Student, Registration, Result, Payment, PublicationStatus, UserRole, StudentCourse, FeeStructure
from utils.results_logic import get_payment_percentage, compute_gpa, compute_semester_academic_status, has_outstanding_balance
from utils.seed import seed_all

st.set_page_config(
    page_title="UoE Student Information System",
    page_icon="assets/favicon.ico",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Global CSS ────────────────────────────────────────────────
st.markdown("""
<style>
  [data-testid="stSidebar"] { background: #f8fafc; border-right: 1px solid #e2e8f0; }
  [data-testid="stSidebarNav"] { display: none; }
  .stButton > button {
      border-radius: 6px; font-weight: 600; transition: all .2s;
  }
  .stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,.1); }
  div[data-testid="metric-container"] { background: white; border: 1px solid #e5e7eb;
      border-radius: 10px; padding: 12px 16px; }
  .stDataFrame { border: 1px solid #e5e7eb; border-radius: 8px; }
  h1, h2, h3 { color: #1a3a5c; }
  .stSelectbox label, .stTextInput label, .stNumberInput label { font-weight: 600; color: #374151; }
  footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Seed DB on first run ──────────────────────────────────────
@st.cache_resource
def initialize():
    db = get_db()
    # seed_all(db)  # DISABLED — real data entry begins now, do not re-seed
    db.close()

initialize()


# ── Session state bootstrap ───────────────────────────────────
if "user" not in st.session_state:
    st.session_state.user = None


# ── Login page ────────────────────────────────────────────────
def render_login():
    logo_path = os.path.join(os.path.dirname(__file__), "assets", "uoelogo.png")

    col_l, col_c, col_r = st.columns([1, 1.2, 1])
    with col_c:
        if os.path.exists(logo_path):
            st.image(logo_path, width=160)
        else:
            st.markdown(
                '<div style="text-align:center;padding:20px 0;">'
                '<div style="font-size:2rem;font-weight:800;color:#1a3a5c;letter-spacing:2px;">UoE</div>'
                '<div style="font-size:0.9rem;color:#6b7280;">University of Edenberg</div>'
                '</div>',
                unsafe_allow_html=True
            )

        with st.container(border=True):
            st.markdown('<h3 style="text-align:center;color:#1a3a5c;margin-bottom:20px;">Sign In</h3>',
                        unsafe_allow_html=True)

            username = st.text_input("Username/ID", placeholder="Enter your username/ID")
            password = st.text_input("Password", type="password", placeholder="Enter your password")

            if st.button("Sign In", use_container_width=True, type="primary"):
                if username and password:
                    db = get_db()
                    user_obj = login_user(db, username, password)
                    if user_obj:
                        st.session_state.user = {
                            "id": user_obj.id,
                            "username": user_obj.username,
                            "role": user_obj.role.value,
                            "first_name": user_obj.first_name,
                            "last_name": user_obj.last_name,
                            "email": user_obj.email,
                            "student_id": user_obj.student_id,
                        }
                        db.close()
                        st.rerun()
                    else:
                        db.close()
                        st.error("Invalid username or password.")
                else:
                    st.warning("Please enter both username and password.")

        st.markdown(
            '<div style="text-align:center;margin-top:16px;color:#9ca3af;font-size:0.78rem;">'
            'University of Edenberg &copy; 2026 &bull; Student Information System</div>',
            unsafe_allow_html=True
        )


# ── Dashboard ─────────────────────────────────────────────────
def render_dashboard():
    render_sidebar()
    user = st.session_state.user
    role = user["role"]

    page_header(
        f"Welcome, {user['first_name']} {user['last_name']}",
        f"University of Edenberg SIS &bull; {role}"
    )

    db = get_db()

    if role == UserRole.STUDENT.value:
        _student_dashboard(db, user)
    else:
        _staff_dashboard(db, role)

    db.close()


def _student_dashboard(db, user):
    student_id = user.get("student_id")
    if not student_id:
        st.warning("Student profile not linked to this account.")
        return

    student = db.query(Student).get(student_id)
    if not student:
        st.error("Student record not found.")
        return

    # ── Biodata ──────────────────────────────────────────────────
    st.markdown("### My Profile")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card("Student Number", student.student_number)
    with col2:
        metric_card("Programme", student.programme.code if student.programme else "N/A")
    with col3:
        metric_card("Year of Study", student.year_of_study)
    with col4:
        metric_card("Status", student.status.value)

    with st.expander("Full Biodata"):
        b1, b2 = st.columns(2)
        with b1:
            st.markdown(f"**Full Name:** {student.full_name}")
            st.markdown(f"**Gender:** {student.gender.value if student.gender else 'Not recorded'}")
            st.markdown(f"**Date of Birth:** "
                       f"{student.date_of_birth.strftime('%d %B %Y') if student.date_of_birth else 'Not recorded'}")
            st.markdown(f"**National ID:** {student.national_id or 'Not recorded'}")
        with b2:
            st.markdown(f"**Email:** {student.email or 'Not recorded'}")
            st.markdown(f"**Phone:** {student.phone or 'Not recorded'}")
            st.markdown(f"**Programme:** {student.programme.name if student.programme else 'N/A'}")
            st.markdown(f"**Faculty:** {student.programme.faculty if student.programme else 'N/A'}")

    st.markdown("---")

    # ── Registration / Enrollment summary for the current semester ─
    st.markdown("### Current Registration")
    academic_year = student.academic_year or "2025/2026"

    # "Current semester" — show whichever semester the student has the
    # most recent registration for for this academic year; default to
    # Semester 1 if no registration exists yet at all.
    current_reg = (
        db.query(Registration)
        .filter_by(student_id=student.id, academic_year=academic_year)
        .order_by(Registration.semester.desc())
        .first()
    )

    if not current_reg:
        st.info(
            f"You are not yet registered for any courses in {academic_year}. "
            f"Visit the Registration page once the Registrar opens the registration period."
        )
    else:
        enrolled = db.query(StudentCourse).filter_by(registration_id=current_reg.id).all()
        core_count = sum(1 for sc in enrolled if sc.course.is_core)
        elective_count = len(enrolled) - core_count
        total_credits = sum(sc.course.credits or 0 for sc in enrolled)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            metric_card("Semester", current_reg.semester)
        with col2:
            metric_card("Courses Registered", len(enrolled))
        with col3:
            metric_card("Total Credits", total_credits)
        with col4:
            metric_card("Status", current_reg.status.value)

        with st.expander(f"Registered Courses — {academic_year}, Semester {current_reg.semester}"):
            for sc in enrolled:
                type_label = "Core" if sc.course.is_core else "Elective"
                st.markdown(f"- **{sc.course.code}** — {sc.course.name} "
                           f"({sc.course.credits} credits, {type_label})")
            st.caption(f"{core_count} core course(s), {elective_count} elective(s)")

    st.markdown("---")

    # ── Finance summary for the current semester ────────────────────
    st.markdown("### Finance Summary (Current Semester)")
    finance_semester = current_reg.semester if current_reg else 1

    fee_struct = db.query(FeeStructure).filter_by(
        programme_id=student.programme_id, academic_year=academic_year, semester=finance_semester
    ).first()

    if not fee_struct:
        st.info("No fee structure has been set for your programme this semester yet. Contact the Finance Office.")
    else:
        total_paid = sum(
            p.amount for p in db.query(Payment).filter_by(
                student_id=student.id, academic_year=academic_year, semester=finance_semester
            ).all()
        )
        balance = fee_struct.total_fee - total_paid
        pct_paid = get_payment_percentage(db, student.id, academic_year, finance_semester)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            metric_card("Total Fee", f"K{fee_struct.total_fee:,.2f}")
        with col2:
            metric_card("Amount Paid", f"K{total_paid:,.2f}", "#166534")
        with col3:
            metric_card("Balance", f"K{balance:,.2f}", "#991b1b" if balance > 0 else "#166534")
        with col4:
            metric_card("Payment %", f"{pct_paid * 100:.1f}%",
                        "#166534" if pct_paid >= 0.70 else "#92400e" if pct_paid >= 0.25 else "#991b1b")

        st.progress(min(pct_paid, 1.0))
        has_balance, outstanding = has_outstanding_balance(
            db,
            student.id,
            academic_year,
            finance_semester
        )

        if has_balance:
            st.caption(
                f"🔒 Registration blocked. Outstanding balance: "
                f"K{outstanding:,.2f} from previous semester(s)."
            )

        elif pct_paid < 0.25:
            st.caption(
                "🔒 Registration requires at least 25% payment "
                "for the current semester."
            )

        elif pct_paid < 0.40:
            st.caption(
                "✅ Registration requirements met. "
                "🔒 Mid-Semester results require 40% payment."
            )

        elif pct_paid < 0.70:
            st.caption(
                "✅ Registration and Mid-Semester access unlocked. "
                "🔒 Final results require 70% payment."
            )

        else:
            st.caption(
                "✅ All financial requirements satisfied."
            )

    st.markdown("---")
    st.subheader("Quick Links")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("View My Results", use_container_width=True):
            st.switch_page("pages/06_my_results.py")
    with c2:
        if st.button("Download Result Slip", use_container_width=True):
            st.switch_page("pages/09_result_slip.py")
    with c3:
        if st.button("Financial Statement", use_container_width=True):
            st.switch_page("pages/07_financials.py")


def _staff_dashboard(db, role):
    from sqlalchemy import func
    total_students = db.query(Student).filter_by(status="Active").count()
    total_published = db.query(Result).filter_by(publication_status=PublicationStatus.PUBLISHED).count()
    total_draft = db.query(Result).filter_by(publication_status=PublicationStatus.DRAFT).count()
    total_registrations = db.query(Registration).count()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card("Active Students", total_students, "#1a3a5c")
    with col2:
        metric_card("Results Published", total_published, "#166534")
    with col3:
        metric_card("Results Pending", total_draft, "#92400e")
    with col4:
        metric_card("Total Registrations", total_registrations, "#1d4ed8")

    st.markdown("---")
    st.subheader("Quick Actions")
    cols = st.columns(4)
    pages = [
        ("Students", "pages/01_students.py"),
        ("Results Entry", "pages/04_results_entry.py"),
        ("Publish Results", "pages/05_results_publish.py"),
        ("Reports", "pages/08_reports.py"),
    ]
    for i, (label, page) in enumerate(pages):
        with cols[i % 4]:
            if st.button(label, use_container_width=True):
                st.switch_page(page)

    db.close()


# ── Router ────────────────────────────────────────────────────
if st.session_state.user is None:
    render_login()
else:
    render_dashboard()
