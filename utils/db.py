"""
Database helpers for University of Edenberg SIS
"""
import streamlit as st
from models import get_engine, get_session, init_db


@st.cache_resource
def get_db_engine():
    # On Streamlit Cloud the local filesystem is ephemeral, so production
    # data must live in a real database (Postgres) reached via a connection
    # string in .streamlit/secrets.toml — DATABASE_URL = "postgresql://...".
    # Falls back to local SQLite (sis_uoe.db) when no secret is configured,
    # which is what local development uses.
    try:
        database_url = st.secrets.get("DATABASE_URL")
    except Exception:
        database_url = None  # no secrets.toml at all — local SQLite dev
    engine = get_engine("sis_uoe.db", database_url=database_url)
    init_db(engine)
    return engine


def get_db():
    """Get a new session — caller must close it"""
    engine = get_db_engine()
    return get_session(engine)
