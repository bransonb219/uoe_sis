"""
Database helpers for University of Edenberg SIS
"""
import streamlit as st
from models import get_engine, get_session, init_db


@st.cache_resource
def get_db_engine():
    engine = get_engine("sis_uoe.db")
    init_db(engine)
    return engine


def get_db():
    """Get a new session — caller must close it"""
    engine = get_db_engine()
    return get_session(engine)
