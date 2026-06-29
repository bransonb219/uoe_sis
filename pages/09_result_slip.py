"""
Result Slip — University of Edenberg SIS
Generates a printable HTML result slip with university letterhead, GPA,
and a download button. Respects the same payment-gating rules as My Results.
"""
import streamlit as st
import sys, os, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login, log_action
from utils.ui import render_sidebar, page_header
from utils.results_logic import can_view_results, compute_gpa, compute_semester_academic_status
from models import Student, Registration, StudentCourse, PublicationStatus, UserRole, AcademicYear
from datetime import datetime

st.set_page_config(page_title="Result Slip — UoE SIS", page_icon="assets/favicon.ico", layout="wide")
require_login()
render_sidebar()
page_header("Result Slip", "Generate a printable official result slip")

user = st.session_state.user
db = get_db()

# ── Determine target student ────────────────────────────────
if user["role"] == UserRole.STUDENT.value:
    student = db.query(Student).get(user.get("student_id"))
    if not student:
        st.error("Your account is not linked to a student record.")
        db.close()
        st.stop()
else:
    snum = st.text_input("Enter Student Number")
    if not snum:
        st.info("Enter a student number to generate their result slip.")
        db.close()
        st.stop()
    student = db.query(Student).filter_by(student_number=snum.strip()).first()
    if not student:
        st.error("Student not found.")
        db.close()
        st.stop()

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
    st.info("No registration found for this period.")
    db.close()
    st.stop()

scs = db.query(StudentCourse).filter_by(registration_id=reg.id).all()
published_results = [
    sc.result for sc in scs
    if sc.result and sc.result.publication_status == PublicationStatus.PUBLISHED
]
exempted_courses = [sc for sc in scs if sc.exemption]

if not published_results and not exempted_courses:
    st.warning("No published results available for this semester yet.")
    db.close()
    st.stop()

can_view, reason = can_view_results(db, student.id)

if not can_view:
    st.error(f"🔒 {reason}")
    db.close()
    st.stop()

# ── Build result slip HTML ──────────────────────────────────
logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "uoelogo.png")
logo_b64 = ""
if os.path.exists(logo_path):
    with open(logo_path, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode()

gpa = compute_gpa(published_results)
academic_status = compute_semester_academic_status(published_results)
generated_on = datetime.now().strftime("%d %B %Y, %H:%M")


def fmt(v):
    return f"{v:.1f}" if v is not None else "—"


prog_level = student.programme.level.value if student.programme and student.programme.level else "Undergraduate"
is_postgrad = prog_level == "Postgraduate"

score_cols = 3 if is_postgrad else 4  # CA1, CA2, [Mid], Final

rows_html = ""
for r in published_results:
    sc = r.student_course
    rows_html += f"""
    <tr>
      <td>{sc.course.code}</td>
      <td>{sc.course.name}</td>
      <td style="text-align:center;">{sc.course.credits}</td>
      <td style="text-align:center;">{fmt(r.ca1_score)}</td>
      <td style="text-align:center;">{fmt(r.ca2_score)}</td>
      {"" if is_postgrad else f'<td style="text-align:center;">{fmt(r.mid_sem_score)}</td>'}
      <td style="text-align:center;">{fmt(r.final_score)}</td>
      <td style="text-align:center;">{fmt(r.supp_score)}</td>
      <td style="text-align:center;font-weight:600;">{fmt(r.total_score)}</td>
      <td style="text-align:center;font-weight:700;">{r.grade or '—'}</td>
      <td style="text-align:center;">{r.status.value if r.status else '—'}</td>
    </tr>
    """

for sc in exempted_courses:
    rows_html += f"""
    <tr style="background:#fef9c3;">
      <td>{sc.course.code}</td>
      <td>{sc.course.name}</td>
      <td style="text-align:center;">{sc.course.credits}</td>
      <td colspan="{score_cols}" style="text-align:center;font-style:italic;">
        EXEMPTED — {sc.exemption.reason or 'No reason recorded'}
      </td>
      <td style="text-align:center;">—</td>
      <td style="text-align:center;font-weight:700;">EX</td>
      <td style="text-align:center;">Exempted</td>
    </tr>
    """

logo_tag = f'<img src="data:image/png;base64,{logo_b64}">' if logo_b64 else ""

slip_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Result Slip - {student.student_number}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #1f2937; margin: 0; padding: 30px; background: #fff; }}
  .header {{ display: flex; align-items: center; border-bottom: 3px solid #1a3a5c; padding-bottom: 16px; margin-bottom: 20px; }}
  .header img {{ height: 70px; margin-right: 20px; }}
  .header-text h1 {{ margin: 0; color: #1a3a5c; font-size: 1.4rem; }}
  .header-text p {{ margin: 2px 0; color: #6b7280; font-size: 0.85rem; }}
  .title {{ text-align: center; font-size: 1.1rem; font-weight: 700; color: #1a3a5c; margin: 16px 0; text-transform: uppercase; letter-spacing: 1px; }}
  .info-table {{ width: 100%; margin-bottom: 20px; font-size: 0.9rem; }}
  .info-table td {{ padding: 4px 8px; }}
  .info-table .label {{ color: #6b7280; font-weight: 600; width: 160px; }}
  table.results {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 0.85rem; }}
  table.results th {{ background: #1a3a5c; color: white; padding: 8px; text-align: left; }}
  table.results td {{ padding: 7px 8px; border-bottom: 1px solid #e5e7eb; }}
  table.results tr:nth-child(even) {{ background: #f9fafb; }}
  .summary {{ display: flex; justify-content: space-between; background: #f0f9ff; border: 1px solid #bae6fd;
             border-radius: 8px; padding: 14px 20px; margin-bottom: 20px; }}
  .summary-item {{ text-align: center; }}
  .summary-item .label {{ font-size: 0.75rem; color: #6b7280; text-transform: uppercase; }}
  .summary-item .value {{ font-size: 1.3rem; font-weight: 700; color: #1a3a5c; }}
  .footer {{ font-size: 0.75rem; color: #9ca3af; text-align: center; margin-top: 30px; border-top: 1px solid #e5e7eb; padding-top: 10px; }}
  .signature {{ margin-top: 40px; display: flex; justify-content: space-between; }}
  .signature div {{ text-align: center; width: 200px; border-top: 1px solid #1f2937; padding-top: 6px; font-size: 0.8rem; }}
  @media print {{ body {{ padding: 10px; }} }}
</style>
</head>
<body>
  <div class="header">
    {logo_tag}
    <div class="header-text">
      <h1>UNIVERSITY OF EDENBERG</h1>
      <p>Office of the Registrar &bull; Academic Records Division</p>
      <p>Ariyapatta Campus (Main): Stand No. 7, Enock Kavu Road</p>
      <p>Maslow Campus: St. Eugene Office Park, Stand No. 22866, Ibex Hill, Leopards Hill Road</p>
      <p>P.O. Box 37209, Lusaka, Zambia</p>
    </div>
  </div>

  <div class="title">Official Result Slip</div>

  <table class="info-table">
    <tr><td class="label">Student Name:</td><td>{student.full_name}</td>
        <td class="label">Student Number:</td><td>{student.student_number}</td></tr>
    <tr><td class="label">Programme:</td><td>{student.programme.name if student.programme else 'N/A'}</td>
        <td class="label">Year of Study:</td><td>{student.year_of_study}</td></tr>
    <tr><td class="label">Intake:</td><td>{student.intake.code if student.intake else 'N/A'}</td>
        <td class="label">Academic Year:</td><td>{academic_year}</td></tr>
    <tr><td class="label">Semester:</td><td>{semester}</td>
        <td class="label">Mode of Study:</td><td>{student.mode_of_study.value if student.mode_of_study else 'N/A'}</td></tr>
    <tr><td class="label">Level:</td><td>{prog_level}</td>
        <td></td><td></td></tr>
  </table>

  <table class="results">
    <thead>
      <tr>
        <th>Code</th><th>Course Name</th><th>Credits</th>
        {"<th>CA1 (25%)</th><th>CA2 (25%)</th><th>Final (50%)</th>" if is_postgrad else "<th>CA1 (10%)</th><th>CA2 (10%)</th><th>Mid (20%)</th><th>Final (60%)</th>"}
        <th>Supp</th><th>Total</th><th>Grade</th><th>Status</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  <div class="summary">
    <div class="summary-item"><div class="label">Semester GPA</div><div class="value">{gpa:.2f}</div></div>
    <div class="summary-item"><div class="label">Courses Sat</div><div class="value">{len(published_results)}</div></div>
    <div class="summary-item"><div class="label">Exempted</div><div class="value">{len(exempted_courses)}</div></div>
    <div class="summary-item"><div class="label">Academic Status</div><div class="value" style="font-size:1rem;">{academic_status}</div></div>
  </div>
  <p style="font-size:0.75rem;color:#6b7280;">GPA and academic status are computed from courses sat only — exempted courses are excluded from GPA and credit totals.</p>

  <div class="signature">
    <div>Dr. Chola, Evaristo (Ph.D)<br>Registrar's Signature</div>
    <div>Official Seal</div>
  </div>

  <div class="footer">
    This is a system-generated result slip from the University of Edenberg Student Information System.<br>
    Generated on {generated_on}. Results subject to verification by the Office of the Registrar.<br>
    Registrar's Office: registrar@ue.ac.zm &bull; +260 96 196 3254 &nbsp;|&nbsp; Admissions: admission@ue.ac.zm
  </div>
</body>
</html>
"""

# ── Preview & download ──────────────────────────────────────
st.markdown("### Preview")
st.components.v1.html(slip_html, height=700, scrolling=True)

st.download_button(
    "Download Result Slip (HTML)",
    slip_html,
    f"result_slip_{student.student_number}_{academic_year.replace('/', '-')}_sem{semester}.html",
    "text/html",
    type="primary"
)

log_action(db, "VIEW_RESULT_SLIP", "Student", student.id,
           f"{student.student_number} {academic_year} Sem {semester}")

db.close()
