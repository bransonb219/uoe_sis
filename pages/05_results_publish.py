"""
Results Publication — University of Edenberg SIS
PRIMARY FEATURE: Registrar/Admin publishes, withholds, or reverts results.
Supports batch and selective publication with full audit trail.
"""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.db import get_db
from utils.auth import require_login, log_action
from utils.ui import render_sidebar, page_header, status_badge, metric_card
from utils.results_logic import compute_semester_academic_status
from models import (
    Student, Course, Registration, StudentCourse, Result,
    Programme, ResultPublicationBatch, PublicationStatus,
    ResultStatus, UserRole, ExamType, User, AcademicYear
)
from datetime import datetime
import pandas as pd

st.set_page_config(page_title="Publish Results — UoE SIS", layout="wide")
require_login()
render_sidebar()
page_header("Results Publication", "Publish, withhold, or revert student results")

user = st.session_state.user
role = user["role"]

if role not in (UserRole.ADMIN.value, UserRole.REGISTRAR.value):
    st.error("Access restricted to Registrar and Admin only.")
    st.stop()

db = get_db()
_academic_years = db.query(AcademicYear).filter_by(is_active=True).order_by(AcademicYear.label).all()


def _academic_year_picker(label, default_label, key):
    if _academic_years:
        labels = [ay.label for ay in _academic_years]
        idx = labels.index(default_label) if default_label in labels else 0
        return st.selectbox(label, labels, index=idx, key=key)
    return st.text_input(label, default_label, key=key)

# ── Tab layout ────────────────────────────────────────────────
tab_batch, tab_individual, tab_history = st.tabs([
    "Batch Publication", "Individual Student", "Publication History"
])


# ─────────────────────────── BATCH PUBLICATION ───────────────
with tab_batch:
    st.subheader("Batch Publish Results")
    st.markdown(
        '<div style="background:#eff6ff;border-left:4px solid #2563eb;padding:12px 16px;'
        'border-radius:4px;margin-bottom:16px;font-size:0.88rem;">'
        'Publishing results makes them visible to students based on their payment status. '
        'Only results that have been entered (non-Draft component scores) can be published.'
        '</div>',
        unsafe_allow_html=True
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        b_year = _academic_year_picker("Academic Year", "2025/2026", "b_year")
    with col2:
        b_sem = st.selectbox("Semester", [1, 2], key="b_sem")
    with col3:
        programmes = db.query(Programme).filter_by(is_active=True).all()
        prog_opts = {"All Programmes": None} | {p.name: p.id for p in programmes}
        b_prog = st.selectbox("Programme", list(prog_opts.keys()), key="b_prog")

    exam_type = st.selectbox(
        "Exam Type",
        [e.value for e in ExamType],
        help="Used for audit trail — does not restrict which scores are published"
    )

    b_prog_id = prog_opts[b_prog]

    # Load results matching filters
    query = (
        db.query(Result)
        .join(StudentCourse)
        .join(Registration)
        .join(Course)
        .filter(
            Registration.academic_year == b_year,
            Registration.semester == b_sem,
        )
    )
    if b_prog_id:
        query = query.filter(Course.programme_id == b_prog_id)

    all_results = query.all()

    draft_results = [r for r in all_results if r.publication_status == PublicationStatus.DRAFT and r.total_score is not None]
    published_results = [r for r in all_results if r.publication_status == PublicationStatus.PUBLISHED]
    withheld_results = [r for r in all_results if r.publication_status == PublicationStatus.WITHHELD]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card("Total Results", len(all_results))
    with col2:
        metric_card("Draft (Ready to Publish)", len(draft_results), "#92400e")
    with col3:
        metric_card("Published", len(published_results), "#166534")
    with col4:
        metric_card("Withheld", len(withheld_results), "#991b1b")

    st.markdown("---")

    # Preview table
    if draft_results:
        st.markdown(f"**{len(draft_results)} result(s) ready for publication:**")
        preview_rows = []
        for r in draft_results[:50]:  # limit preview
            sc = r.student_course
            student = sc.registration.student
            preview_rows.append({
                "Student #": student.student_number,
                "Name": student.full_name,
                "Course": sc.course.code,
                "Total": f"{r.total_score:.1f}" if r.total_score else "—",
                "Grade": r.grade or "—",
                "Status": r.status.value if r.status else "—",
            })
        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)
        if len(draft_results) > 50:
            st.caption(f"Showing first 50 of {len(draft_results)} results.")

    col_pub, col_with, col_revert = st.columns(3)

    with col_pub:
        if st.button("Publish All Draft Results", type="primary", use_container_width=True,
                     disabled=len(draft_results) == 0):
            now = datetime.utcnow()
            for r in draft_results:
                r.publication_status = PublicationStatus.PUBLISHED
                r.published_at = now
                r.published_by = user["id"]
            # Log batch
            batch = ResultPublicationBatch(
                academic_year=b_year, semester=b_sem,
                programme_id=b_prog_id,
                exam_type=exam_type,
                total_published=len(draft_results),
                published_by=user["id"],
                published_at=now,
                notes=f"Batch publish by {user['first_name']} {user['last_name']}"
            )
            db.add(batch)
            db.commit()
            log_action(db, "BATCH_PUBLISH", "ResultPublicationBatch", batch.id,
                       f"{len(draft_results)} results published")
            st.success(f"✅ {len(draft_results)} result(s) published successfully.")
            st.rerun()

    with col_with:
        if st.button("Withhold All Published Results", use_container_width=True,
                     disabled=len(published_results) == 0):
            for r in published_results:
                r.publication_status = PublicationStatus.WITHHELD
            db.commit()
            log_action(db, "BATCH_WITHHOLD", "Result", None,
                       f"{len(published_results)} results withheld")
            st.warning(f"{len(published_results)} result(s) withheld.")
            st.rerun()

    with col_revert:
        if st.button("Revert Withheld to Draft", use_container_width=True,
                     disabled=len(withheld_results) == 0):
            for r in withheld_results:
                r.publication_status = PublicationStatus.DRAFT
                r.published_at = None
            db.commit()
            log_action(db, "BATCH_REVERT", "Result", None,
                       f"{len(withheld_results)} results reverted")
            st.info(f"{len(withheld_results)} result(s) reverted to Draft.")
            st.rerun()


# ─────────────────────────── INDIVIDUAL STUDENT ──────────────
with tab_individual:
    st.subheader("Manage Results for Individual Student")

    col1, col2 = st.columns(2)
    with col1:
        i_snum = st.text_input("Student Number")
    with col2:
        i_year = _academic_year_picker("Academic Year", "2025/2026", "i_year")
    i_sem = st.selectbox("Semester", [1, 2], key="i_sem")

    if i_snum:
        student = db.query(Student).filter_by(student_number=i_snum.strip()).first()
        if not student:
            st.error("Student not found.")
        else:
            st.success(f"{student.full_name} — {student.programme.name if student.programme else 'N/A'}")

            reg = db.query(Registration).filter_by(
                student_id=student.id,
                academic_year=i_year,
                semester=i_sem
            ).first()

            if not reg:
                st.warning("No registration found for this period.")
            else:
                scs = db.query(StudentCourse).filter_by(registration_id=reg.id).all()
                results = [sc.result for sc in scs if sc.result]

                if not results:
                    st.info("No results entered for this student.")
                else:
                    # Summary
                    academic_status = compute_semester_academic_status(results)
                    st.markdown(
                        f'<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;'
                        f'padding:12px 16px;margin:8px 0;">'
                        f'<strong>Overall Status:</strong> '
                        + status_badge(academic_status) +
                        f'</div>',
                        unsafe_allow_html=True
                    )

                    rows = []
                    for r in results:
                        sc = r.student_course
                        prog = sc.registration.student.programme
                        is_pg = (prog and prog.level and prog.level.value == "Postgraduate")
                        ca1 = r.ca1_score or 0.0
                        ca2 = r.ca2_score or 0.0
                        mid = r.mid_sem_score or 0.0
                        total_ca = round(ca1 + ca2 + (0.0 if is_pg else mid), 2)
                        rows.append({
                            "_id": r.id,
                            "Course": sc.course.code,
                            "Course Name": sc.course.name,
                            "Total CA": total_ca,
                            "Final": r.final_score,
                            "Supp": r.supp_score,
                            "Total": r.total_score,
                            "Grade": r.grade,
                            "Status": r.status.value if r.status else "",
                            "Publication": r.publication_status.value if r.publication_status else "",
                        })

                    df_i = pd.DataFrame(rows)
                    display_cols = ["Course", "Course Name", "Total CA", "Final", "Supp",
                                    "Total", "Grade", "Status", "Publication"]
                    st.dataframe(df_i[display_cols], use_container_width=True, hide_index=True)

                    draft_ids = [r["_id"] for r in rows if r["Publication"] == "Draft" and r["Total"] is not None]
                    pub_ids   = [r["_id"] for r in rows if r["Publication"] == "Published"]

                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button(f"Publish {len(draft_ids)} Draft Result(s)", type="primary",
                                     disabled=len(draft_ids) == 0):
                            now = datetime.utcnow()
                            for rid in draft_ids:
                                r_obj = db.query(Result).get(rid)
                                r_obj.publication_status = PublicationStatus.PUBLISHED
                                r_obj.published_at = now
                                r_obj.published_by = user["id"]
                            db.commit()
                            log_action(db, "PUBLISH_INDIVIDUAL", "Student", student.id,
                                       f"Published results for {i_snum}")
                            st.success(f"Published {len(draft_ids)} result(s).")
                            st.rerun()
                    with col_b:
                        if st.button(f"Withhold {len(pub_ids)} Published Result(s)",
                                     disabled=len(pub_ids) == 0):
                            for rid in pub_ids:
                                r_obj = db.query(Result).get(rid)
                                r_obj.publication_status = PublicationStatus.WITHHELD
                            db.commit()
                            log_action(db, "WITHHOLD_INDIVIDUAL", "Student", student.id, i_snum)
                            st.warning(f"Withheld {len(pub_ids)} result(s).")
                            st.rerun()


# ─────────────────────────── PUBLICATION HISTORY ─────────────
with tab_history:
    st.subheader("Publication History")
    batches = db.query(ResultPublicationBatch).order_by(
        ResultPublicationBatch.published_at.desc()
    ).limit(50).all()

    if batches:
        rows = []
        for b in batches:
            publisher = db.query(User).get(b.published_by)
            rows.append({
                "Date": b.published_at.strftime("%Y-%m-%d %H:%M") if b.published_at else "",
                "Year": b.academic_year,
                "Sem": b.semester,
                "Programme": b.programme.code if b.programme else "All",
                "Exam Type": b.exam_type.value if b.exam_type else "",
                "Count": b.total_published,
                "Published By": f"{publisher.first_name} {publisher.last_name}" if publisher else "—",
                "Notes": b.notes or "",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No publication history found.")

db.close()
