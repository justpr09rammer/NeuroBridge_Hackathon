"""TalentLens AI: Streamlit entry point.  Run:  streamlit run app.py"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="TalentLens AI", page_icon="◎", layout="wide", initial_sidebar_state="expanded")

from talentlens.core import db, services  # noqa: E402
from talentlens.core.models import Vacancy  # noqa: E402
from talentlens.ui import components as ui  # noqa: E402
from talentlens.ui.views import (  # noqa: E402
    candidate, dashboard, emails, quality, screening, settings, vacancy,
)


@st.cache_resource
def _init_db() -> bool:
    db.configure()
    with db.session_scope() as s:
        services.seed_resources(s)
        from sqlalchemy import func, select
        if (s.scalar(select(func.count(Vacancy.id))) or 0) == 0:
            from talentlens.demo.seed import seed_demo
            seed_demo(s)  # first launch: populate the dashboard with the fictional demo scenario
    return True


_init_db()
ui.inject_css()
st.logo("assets/logo.svg", size="large")

pages = {
    "dashboard": st.Page(dashboard.render, title="Dashboard", icon=":material/space_dashboard:", url_path="dashboard", default=True),
    "vacancy": st.Page(vacancy.render, title="1 · Vacancy", icon=":material/work:", url_path="vacancy"),
    "screening": st.Page(screening.render, title="2 · Screening", icon=":material/table_rows:", url_path="screening"),
    "candidate": st.Page(candidate.render, title="3 · Candidate", icon=":material/person_search:", url_path="candidate"),
    "emails": st.Page(emails.render, title="4 · Decisions & Emails", icon=":material/mail:", url_path="emails"),
    "quality": st.Page(quality.render, title="Quality Lab", icon=":material/science:", url_path="quality"),
    "settings": st.Page(settings.render, title="Settings", icon=":material/tune:", url_path="settings"),
}
ui.PAGES.update(pages)

nav = st.navigation({
    "Workflow": [pages["dashboard"], pages["vacancy"], pages["screening"], pages["candidate"], pages["emails"]],
    "Trust": [pages["quality"], pages["settings"]],
})

with st.sidebar:
    st.markdown("<div class='tl-tag'>Hiring that explains itself.</div>", unsafe_allow_html=True)
    with db.session_scope() as s:
        mode = services.pipeline_label(s)
        blind = bool(services.get_setting(s, "blind_mode"))
        from sqlalchemy import select
        demo = s.scalar(select(Vacancy.id).where(Vacancy.is_demo.is_(True)).limit(1)) is not None
    st.markdown(f"<div class='tl-mode'><b>Processing:</b> {ui.esc(mode)}</div>", unsafe_allow_html=True)
    if blind:
        st.markdown("<div class='tl-mode'><b>Blind screening:</b> on</div>", unsafe_allow_html=True)
    if demo:
        st.markdown("<div class='tl-demo'>Fictional demo data loaded. All people and companies are invented.</div>", unsafe_allow_html=True)
    st.caption("Hackathon MVP. Not production-ready for real hiring decisions.")

nav.run()
