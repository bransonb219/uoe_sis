"""
Shared UI components for University of Edenberg SIS
"""
import streamlit as st
import os
from models import UserRole

# ─── SVG Icons ───────────────────────────────────────────────

ICONS = {
    "dashboard":   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>',
    "students":    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    "courses":     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
    "results":     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    "finance":     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
    "reports":     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>',
    "result_slip": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
    "settings":    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    "logout":      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>',
    "etl":         '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
    "publish":     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
    "registration":'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
}


def icon(name: str) -> str:
    return ICONS.get(name, "")


# ─── Sidebar ─────────────────────────────────────────────────

def render_sidebar():
    """
    Sidebar navigation — University of Edenberg SIS.
    Colors derived directly from the real university crest:
      Navy   #1e3c96  (outer ring, dominant)
      Green  #0f783c  (laurel wreaths)
      Deep   #0f2557  (sidebar background, darker than ring for depth)
      Light  #e8f0fe  (subtle hover tint)
    No show/hide toggle — sidebar is always visible.
    """
    user = st.session_state.get("user")
    if not user:
        return

    role = user.get("role", "")
    logo_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "assets", "uoelogo.png"
    )

    # ── Palette from the real crest ───────────────────────────
    DEEP_NAVY   = "#0f2557"   # sidebar bg — darker than the crest ring
    NAVY        = "#1e3c96"   # crest outer ring
    NAVY_LIGHT  = "#2a4fad"   # lighter navy for hover/active
    GREEN       = "#0f783c"   # laurel wreath green
    GREEN_DARK  = "#0a5c2d"   # darker green for hover
    WHITE       = "#ffffff"
    OFF_WHITE   = "#e8eef8"   # very light blue-white for secondary text
    GOLD_LINE   = "#b8a040"   # the thin gold border ring on the crest

    # ── Sidebar CSS ────────────────────────────────────────────
    st.markdown(f"""
    <style>
      /* ── Sidebar shell ── */
      [data-testid="stSidebar"] {{
          background: linear-gradient(180deg, {DEEP_NAVY} 0%, #0d1f4a 100%);
          border-right: 1px solid {NAVY};
      }}
      [data-testid="stSidebarNav"] {{ display: none; }}

      /* ── All buttons in sidebar ── */
      [data-testid="stSidebar"] .stButton > button {{
          background: transparent;
          color: {OFF_WHITE};
          border: none;
          border-left: 3px solid transparent;
          border-radius: 0 6px 6px 0;
          font-size: 0.88rem;
          font-weight: 500;
          text-align: left;
          justify-content: flex-start;
          padding: 0.55rem 0.75rem;
          width: 100%;
          transition: all 0.18s ease;
          letter-spacing: 0.2px;
      }}
      [data-testid="stSidebar"] .stButton > button:hover {{
          background: rgba(255, 255, 255, 0.08);
          border-left: 3px solid {GREEN};
          color: {WHITE};
          transform: none;
      }}
      [data-testid="stSidebar"] .stButton > button:active {{
          background: rgba(255, 255, 255, 0.14);
          border-left: 3px solid {GOLD_LINE};
          color: {WHITE};
      }}
      [data-testid="stSidebar"] .stButton > button:focus:not(:active) {{
          box-shadow: none;
          border-left: 3px solid {NAVY_LIGHT};
      }}

      /* ── Nav icon cell ── */
      .nav-icon-cell {{
          display: flex;
          align-items: center;
          justify-content: center;
          height: 2.15rem;
          color: {OFF_WHITE};
          opacity: 0.85;
      }}

      /* ── Logout button — distinct style ── */
      .logout-btn > button {{
          background: rgba(15, 120, 60, 0.18) !important;
          border-left: 3px solid {GREEN} !important;
          color: #a8f0c6 !important;
      }}
      .logout-btn > button:hover {{
          background: rgba(15, 120, 60, 0.35) !important;
          color: {WHITE} !important;
      }}

      /* ── Sidebar scrollbar ── */
      [data-testid="stSidebar"]::-webkit-scrollbar {{ width: 4px; }}
      [data-testid="stSidebar"]::-webkit-scrollbar-track {{ background: transparent; }}
      [data-testid="stSidebar"]::-webkit-scrollbar-thumb {{
          background: rgba(255,255,255,0.15); border-radius: 2px;
      }}
    </style>
    """, unsafe_allow_html=True)

    with st.sidebar:

        # ── Logo — centered ─────────────────────────────────
        if os.path.exists(logo_path):
            col_l, col_c, col_r = st.columns([1, 3, 1])
            with col_c:
                st.image(logo_path, width=140)
        else:
            st.markdown(
                f'<div style="text-align:center;padding:16px 0 4px 0;'
                f'font-size:1.05rem;font-weight:800;color:{WHITE};letter-spacing:2px;">'
                f'UoE</div>',
                unsafe_allow_html=True
            )

        # ── Institution name ────────────────────────────────
        st.markdown(
            f'<div style="text-align:center;color:{OFF_WHITE};'
            f'font-size:0.72rem;font-weight:600;letter-spacing:0.8px;'
            f'text-transform:uppercase;opacity:0.8;padding-bottom:12px;">'
            f'University of Edenberg</div>',
            unsafe_allow_html=True
        )

        # ── Thin gold divider — echoes the crest's gold ring ─
        st.markdown(
            f'<hr style="border:none;border-top:1px solid {GOLD_LINE};'
            f'opacity:0.5;margin:0 12px 12px 12px;">',
            unsafe_allow_html=True
        )

        # ── User badge ───────────────────────────────────────
        role_icon = {
            "Admin": "⚙", "Registrar": "📋", "Finance": "💰",
            "Lecturer": "🎓", "Student": "📚"
        }.get(role, "👤")
        st.markdown(
            f'<div style="margin:0 8px 4px 8px;padding:10px 12px;'
            f'background:rgba(255,255,255,0.07);border-radius:8px;'
            f'border-left:3px solid {GREEN};">'
            f'<div style="color:{WHITE};font-weight:700;font-size:0.85rem;">'
            f'{role_icon} {user.get("first_name","")} {user.get("last_name","")}'
            f'</div>'
            f'<div style="color:{OFF_WHITE};font-size:0.73rem;opacity:0.75;'
            f'margin-top:2px;letter-spacing:0.3px;">{role}</div>'
            f'</div>',
            unsafe_allow_html=True
        )

        # ── Thin white divider ───────────────────────────────
        st.markdown(
            f'<hr style="border:none;border-top:1px solid rgba(255,255,255,0.1);'
            f'margin:10px 12px;">',
            unsafe_allow_html=True
        )

        # ── Section label helper ─────────────────────────────
        def section_label(text):
            st.markdown(
                f'<div style="color:{GOLD_LINE};font-size:0.65rem;font-weight:700;'
                f'letter-spacing:1.2px;text-transform:uppercase;'
                f'padding:4px 12px 2px 12px;opacity:0.9;">{text}</div>',
                unsafe_allow_html=True
            )

        # ── Nav button helper ────────────────────────────────
        def nav_button(label, page_path, key, icon_name):
            col_icon, col_btn = st.columns([1, 5], gap="small")
            with col_icon:
                st.markdown(
                    f'<div class="nav-icon-cell">{icon(icon_name)}</div>',
                    unsafe_allow_html=True
                )
            with col_btn:
                if st.button(label, key=key, use_container_width=True):
                    st.switch_page(page_path)

        # ── Navigation ───────────────────────────────────────
        section_label("Main")
        nav_button("Dashboard", "app.py", "nav_dashboard", "dashboard")

        if role in ("Admin", "Registrar", "Lecturer", "Finance", "Admin Support"):
            section_label("Students & Courses")
            nav_button("Students", "pages/01_students.py", "nav_students", "students")
            if role in ("Admin", "Registrar", "Lecturer"):
                nav_button("Courses", "pages/02_courses.py", "nav_courses", "courses")
                nav_button("Registration", "pages/03_registration.py", "nav_registration", "registration")
        else:
            # Student — minimal list
            section_label("My Academic")
            nav_button("Students", "pages/01_students.py", "nav_students", "students")
            nav_button("Courses", "pages/02_courses.py", "nav_courses", "courses")
            nav_button("Registration", "pages/03_registration.py", "nav_registration_student", "registration")

        if role in ("Admin", "Registrar", "Lecturer"):
            section_label("Results")
            nav_button("Results Entry", "pages/04_results_entry.py", "nav_results_entry", "results")
            nav_button("Publish Results", "pages/05_results_publish.py", "nav_results_publish", "publish")

        if role in ("Admin", "Registrar", "Student"):
            if role == "Student":
                section_label("My Results")
            nav_button("My Results", "pages/06_my_results.py", "nav_my_results", "results")
            nav_button("Result Slip", "pages/09_result_slip.py", "nav_result_slip", "result_slip")

        if role in ("Admin", "Finance", "Registrar"):
            section_label("Finance")
            nav_button("Financials", "pages/07_financials.py", "nav_financials", "finance")

        if role in ("Admin", "Registrar"):
            section_label("Administration")
            nav_button("Reports", "pages/08_reports.py", "nav_reports", "reports")
            nav_button("Data Import (ETL)", "pages/10_etl.py", "nav_etl", "etl")

        if role == "Admin":
            nav_button("Settings & Users", "pages/11_settings.py", "nav_settings", "settings")

        if role == "Student":
            section_label("Finance")
            nav_button("Financials", "pages/07_financials.py", "nav_financials_student", "finance")

        # ── Divider before logout ────────────────────────────
        st.markdown(
            f'<hr style="border:none;border-top:1px solid rgba(255,255,255,0.1);'
            f'margin:10px 12px 6px 12px;">',
            unsafe_allow_html=True
        )

        # ── Logout ───────────────────────────────────────────
        col_icon, col_btn = st.columns([1, 5], gap="small")
        with col_icon:
            st.markdown(
                f'<div class="nav-icon-cell">{icon("logout")}</div>',
                unsafe_allow_html=True
            )
        with col_btn:
            st.markdown('<div class="logout-btn">', unsafe_allow_html=True)
            if st.button("Logout", use_container_width=True, key="nav_logout"):
                st.session_state.clear()
                st.switch_page("app.py")
            st.markdown('</div>', unsafe_allow_html=True)


# ─── Page header ─────────────────────────────────────────────

def page_header(title: str, subtitle: str = ""):
    st.markdown(
        f'<h2 style="color:#1a3a5c;margin-bottom:2px;">{title}</h2>'
        + (f'<p style="color:#6b7280;margin-top:0;">{subtitle}</p>' if subtitle else ""),
        unsafe_allow_html=True
    )
    st.markdown('<hr style="border:none;border-top:2px solid #e5e7eb;margin:8px 0 16px 0;">', unsafe_allow_html=True)


# ─── Status badges ───────────────────────────────────────────

STATUS_COLORS = {
    "Pass": ("#dcfce7", "#166534"),
    "Fail": ("#fee2e2", "#991b1b"),
    "Supplementary": ("#fef9c3", "#854d0e"),
    "Supplementary Required": ("#fef9c3", "#854d0e"),
    "Proceed but Repeat": ("#ffedd5", "#9a3412"),
    "Pending": ("#f3f4f6", "#374151"),
    "Draft": ("#f3f4f6", "#374151"),
    "Published": ("#dcfce7", "#166534"),
    "Withheld": ("#fee2e2", "#991b1b"),
    "Active": ("#dcfce7", "#166534"),
    "Suspended": ("#fee2e2", "#991b1b"),
    "Graduated": ("#dbeafe", "#1e40af"),
    "Enrolled": ("#dcfce7", "#166534"),
}


def status_badge(label: str) -> str:
    bg, fg = STATUS_COLORS.get(label, ("#e5e7eb", "#374151"))
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 10px;'
        f'border-radius:12px;font-size:0.78rem;font-weight:600;">{label}</span>'
    )


def metric_card(label: str, value, color: str = "#1a3a5c", sub: str = ""):
    st.markdown(
        f'<div style="background:white;border:1px solid #e5e7eb;border-radius:10px;'
        f'padding:16px 20px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.06);">'
        f'<div style="font-size:0.78rem;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:.5px;margin-bottom:4px;">{label}</div>'
        f'<div style="font-size:1.8rem;font-weight:700;color:{color};">{value}</div>'
        + (f'<div style="font-size:0.75rem;color:#9ca3af;margin-top:2px;">{sub}</div>' if sub else "")
        + "</div>",
        unsafe_allow_html=True
    )
