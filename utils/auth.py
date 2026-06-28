"""
Authentication utilities for University of Edenberg SIS
"""
import hashlib
import hmac
import secrets
import streamlit as st
from datetime import datetime
from models import User, AuditLog, UserRole, Student


def hash_password(password: str) -> str:
    """SHA-256 password hashing with salt"""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash"""
    try:
        salt, hashed = stored_hash.split(":", 1)
        expected = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        return hmac.compare_digest(hashed, expected)
    except Exception:
        return False


def login_user(session, username: str, password: str):
    """
    Authenticate user. Three-tier fallback:
    1. Exact username match
    2. Username with /, spaces, hyphens stripped
    3. Student number lookup (for students whose username IS their student number)
    """
    import re
    # Tier 1: exact match
    user = session.query(User).filter_by(username=username, is_active=True).first()
    if not user:
        # Tier 2: strip slashes, spaces, hyphens from the supplied username
        stripped = re.sub(r"[/\s\-]", "", username)
        if stripped != username:
            user = session.query(User).filter_by(username=stripped, is_active=True).first()
    if not user:
        # Tier 3: student number lookup — find the Student, then their linked User
        student = session.query(Student).filter_by(student_number=username).first()
        if student and student.user and student.user.is_active:
            user = student.user
    if user and verify_password(password, user.password_hash):
        user.last_login = datetime.utcnow()
        session.commit()
        return user
    return None


def require_login():
    """Redirect to login if not authenticated"""
    if "user" not in st.session_state or st.session_state.user is None:
        st.switch_page("app.py")
        st.stop()


def require_role(*roles):
    """Require one of the given roles, else show error and stop"""
    require_login()
    user = st.session_state.user
    if user["role"] not in [r.value if hasattr(r, "value") else r for r in roles]:
        st.error("⛔ You do not have permission to access this page.")
        st.stop()


def get_current_user():
    """Return current user dict from session state"""
    return st.session_state.get("user")


def is_admin():
    u = get_current_user()
    return u and u["role"] == UserRole.ADMIN.value


def is_staff():
    u = get_current_user()
    return u and u["role"] in [
        UserRole.ADMIN.value, UserRole.REGISTRAR.value,
        UserRole.FINANCE.value, UserRole.LECTURER.value,
        UserRole.ADMIN_SUPPORT.value,
    ]


def log_action(session, action: str, entity: str = None, entity_id: int = None, details: str = None):
    """Write to audit log"""
    user = get_current_user()
    log = AuditLog(
        user_id=user["id"] if user else None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=details,
        timestamp=datetime.utcnow()
    )
    session.add(log)
    session.commit()
