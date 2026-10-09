"""Shared Streamlit UI helpers: styling, badges, cards, navigation state."""
from __future__ import annotations

import html

import streamlit as st

from talentlens.core import taxonomy as tx

ACCENT = "#4F46E5"
NAVY = "#0F172A"
MUTED = "#64748B"
STATUS_STYLE = {
    tx.DEMONSTRATED: ("Demonstrated", "#047857", "#ECFDF5", "#A7F3D0"),
    tx.UNCLEAR: ("Unclear", "#B45309", "#FFFBEB", "#FDE68A"),
    tx.NOT_FOUND: ("Not found in CV", "#B91C1C", "#FEF2F2", "#FECACA"),
}
STATUS_COLORS = {tx.DEMONSTRATED: "#10B981", tx.UNCLEAR: "#F59E0B", tx.NOT_FOUND: "#EF4444"}

PAGES: dict = {}  # filled by app.py: key -> st.Page

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea {{ font-family: 'Inter', system-ui, sans-serif; }}
.block-container {{ padding-top: 2rem; padding-bottom: 3rem; max-width: 1280px; }}
h1, h2, h3 {{ color: {NAVY}; letter-spacing: -0.01em; }}
h1 {{ font-weight: 700; font-size: 1.85rem !important; }}
.tl-sub {{ color: {MUTED}; margin-top: -0.6rem; margin-bottom: 1.2rem; font-size: 0.98rem; }}
.tl-card {{ background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 1rem 1.2rem; margin-bottom: 0.8rem; }}
.tl-kpi {{ background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 0.9rem 1.1rem; }}
.tl-kpi .v {{ font-size: 1.7rem; font-weight: 700; color: {NAVY}; line-height: 1.2; }}
.tl-kpi .l {{ font-size: 0.8rem; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.04em; }}
.tl-kpi .h {{ font-size: 0.78rem; color: {MUTED}; margin-top: 0.2rem; }}
.tl-badge {{ display: inline-block; padding: 0.12rem 0.55rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; border: 1px solid; white-space: nowrap; }}
.tl-chip {{ display: inline-block; padding: 0.1rem 0.5rem; border-radius: 6px; font-size: 0.72rem; font-weight: 600; background: #EEF2FF; color: #3730A3; margin-right: 0.3rem; }}
.tl-quote {{ border-left: 3px solid {ACCENT}; background: #F8FAFC; padding: 0.45rem 0.75rem; border-radius: 0 8px 8px 0; color: #1E293B; font-size: 0.9rem; margin: 0.35rem 0; }}
.tl-muted {{ color: {MUTED}; font-size: 0.85rem; }}
.tl-flag {{ border: 1px solid #FDE68A; background: #FFFBEB; border-radius: 10px; padding: 0.6rem 0.85rem; margin: 0.4rem 0; font-size: 0.88rem; color: #78350F; }}
.tl-danger {{ border: 1px solid #FECACA; background: #FEF2F2; border-radius: 10px; padding: 0.6rem 0.85rem; margin: 0.4rem 0; font-size: 0.88rem; color: #7F1D1D; }}
.tl-ok {{ border: 1px solid #A7F3D0; background: #ECFDF5; border-radius: 10px; padding: 0.6rem 0.85rem; margin: 0.4rem 0; font-size: 0.88rem; color: #064E3B; }}
.tl-brand {{ font-weight: 700; font-size: 1.25rem; color: {NAVY}; }}
.tl-brand span {{ color: {ACCENT}; }}
.tl-tag {{ font-size: 0.8rem; color: {MUTED}; margin-top: -0.3rem; }}
.tl-mode {{ font-size: 0.78rem; padding: 0.45rem 0.6rem; border-radius: 8px; background: #EEF2FF; color: #3730A3; border: 1px solid #C7D2FE; margin-top: 0.5rem; }}
.tl-demo {{ font-size: 0.78rem; padding: 0.45rem 0.6rem; border-radius: 8px; background: #FFFBEB; color: #92400E; border: 1px solid #FDE68A; margin-top: 0.4rem; }}
div[data-testid="stExpander"] details {{ border-radius: 10px; }}
@media (max-width: 640px) {{ .block-container {{ padding-left: 1rem; padding-right: 1rem; }} .tl-kpi .v {{ font-size: 1.35rem; }} }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


def header(title: str, subtitle: str = "") -> None:
    st.markdown(f"# {esc(title)}")
    if subtitle:
        st.markdown(f"<div class='tl-sub'>{esc(subtitle)}</div>", unsafe_allow_html=True)


def badge(status: str) -> str:
    label, fg, bg, border = STATUS_STYLE.get(status, (status, "#334155", "#F1F5F9", "#CBD5E1"))
    return f"<span class='tl-badge' style='color:{fg};background:{bg};border-color:{border}'>{esc(label)}</span>"


def chip(text: str) -> str:
    return f"<span class='tl-chip'>{esc(text)}</span>"


def kpi(label: str, value: object, hint: str = "") -> None:
    st.markdown(f"<div class='tl-kpi'><div class='l'>{esc(label)}</div><div class='v'>{esc(value)}</div>"
                f"<div class='h'>{esc(hint)}</div></div>", unsafe_allow_html=True)


def quote(text: str, page: int | None = None) -> None:
    loc = f" <span class='tl-muted'>(page {page})</span>" if page else ""
    st.markdown(f"<div class='tl-quote'>“{esc(text)}”{loc}</div>", unsafe_allow_html=True)


def box(text: str, kind: str = "flag") -> None:
    st.markdown(f"<div class='tl-{kind}'>{text}</div>", unsafe_allow_html=True)


def go(page_key: str, **state) -> None:
    for k, v in state.items():
        st.session_state[k] = v
    st.switch_page(PAGES[page_key])


def fmt_pct(v: float | None) -> str:
    return "–" if v is None else f"{v:.0%}"
