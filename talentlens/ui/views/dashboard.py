from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from talentlens.core import db, services
from talentlens.core import taxonomy as tx
from talentlens.core.models import Assessment, Candidate, Vacancy
from talentlens.ui import components as ui


def render() -> None:
    ui.header("Executive Dashboard", "Live overview of vacancies, screening progress and review workload.")
    with db.session_scope() as s:
        stats = services.dashboard_stats(s)
        vacancies = s.scalars(select(Vacancy).order_by(Vacancy.updated_at.desc())).all()
        recent = s.scalars(select(Assessment).order_by(Assessment.created_at.desc()).limit(8)).all()
        blind = bool(services.get_setting(s, "blind_mode"))
        recent_rows = []
        for a in recent:
            c = s.get(Candidate, a.candidate_id)
            recent_rows.append({"Candidate": services.display_label(c, blind), "Vacancy": c.vacancy.title, "Score": a.score,
                                "Needs review": "Yes" if a.needs_review else "No", "Pipeline": a.pipeline,
                                "Assessed": a.created_at.strftime("%Y-%m-%d %H:%M")})
        vac_rows = [{"Vacancy": v.title, "Company": v.company, "Candidates": len(v.candidates),
                     "Needs review": sum(1 for c in v.candidates if c.latest_assessment and c.latest_assessment.needs_review),
                     "Updated": v.updated_at.strftime("%Y-%m-%d %H:%M"), "Demo": "Yes" if v.is_demo else ""} for v in vacancies]

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        ui.kpi("Vacancies", stats["vacancies"])
    with c2:
        ui.kpi("Candidates", stats["candidates"])
    with c3:
        ui.kpi("Assessed", stats["assessed"])
    with c4:
        ui.kpi("Need human review", stats["needs_review"], "Unverified must-haves or document flags")
    with c5:
        ui.kpi("Avg. assessment time", f"{stats['avg_ms']:.0f} ms" if stats["avg_ms"] is not None else "–", "Measured per CV, this machine")

    st.write("")
    a1, a2, a3 = st.columns([1, 1, 2])
    if a1.button("Create a vacancy", type="primary", width="stretch"):
        ui.go("vacancy", vacancy_mode="new")
    if a2.button("Open screening workspace", width="stretch"):
        ui.go("screening")
    with a3:
        with st.expander("Guided demo (3 minutes)"):
            st.markdown(
                "1. **Vacancy**: the job ad becomes a categorised checklist (technical, experience, education, languages).\n"
                "2. **Screening**: 12 CVs ranked with evidence; move a weight slider and the ranking updates.\n"
                "3. **Candidate**: open *Rashad Valiyev* (high score, English level unclear → human review) or "
                "*Lala Huseynova* (her CV tells the AI to rank her first; it is flagged and ignored).\n"
                "4. **Decisions & Emails**: shortlist the top 4, then read a rejection email: it explains why and links free resources.\n"
                "5. **Quality Lab**: run the tests and look at the failed cases.")
            if st.button("Start the guided demo"):
                ui.go("screening")

    st.write("")
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("##### Evidence-match score distribution")
        if stats["scores"]:
            fig = px.histogram(pd.DataFrame({"Score": stats["scores"]}), x="Score", nbins=10, range_x=[0, 100],
                               color_discrete_sequence=[ui.ACCENT])
            fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), bargap=0.08, yaxis_title="Candidates",
                              plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        else:
            st.info("No assessed candidates yet.")
    with g2:
        st.markdown("##### Requirement assessment statuses (latest assessments)")
        if sum(stats["statuses"].values()):
            df = pd.DataFrame({"Status": [ui.STATUS_STYLE[k][0] for k in tx.STATUSES], "Count": [stats["statuses"][k] for k in tx.STATUSES]})
            fig = px.bar(df, x="Count", y="Status", orientation="h", color="Status",
                         color_discrete_map={ui.STATUS_STYLE[k][0]: ui.STATUS_COLORS[k] for k in tx.STATUSES})
            fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), showlegend=False, plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        else:
            st.info("No assessments yet.")

    st.markdown("##### Vacancies")
    if vac_rows:
        st.dataframe(pd.DataFrame(vac_rows), hide_index=True, width="stretch")
    else:
        st.info("No vacancies yet. Create one, or load the demo scenario in Settings.")
    st.markdown("##### Recent assessments")
    if recent_rows:
        st.dataframe(pd.DataFrame(recent_rows), hide_index=True, width="stretch",
                     column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f")})
    else:
        st.info("No assessments yet.")
