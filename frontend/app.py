"""Заглушка frontend (Фаза 1). Реальный UI — Фаза 8."""

from __future__ import annotations

import os

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://backend:8000")

st.set_page_config(page_title="boasi_s", page_icon="📚", layout="wide")
st.title("boasi_s")
st.caption("Локальная научная платформа на PaperQA2 — интерфейс в разработке (Фаза 8)")

try:
    health = requests.get(f"{API_URL}/api/health", timeout=5).json()
    st.success(f"API доступен: {health.get('app')} {health.get('version')}")
    st.json(health)
except Exception as exc:  # noqa: BLE001
    st.error(f"API недоступен: {type(exc).__name__}: {exc}")
