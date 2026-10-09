from __future__ import annotations

import streamlit as st

from talentlens.core import db, services
from talentlens.core.models import Candidate
from talentlens.ui import components as ui
from talentlens.ui.selectors import pick_candidate, pick_vacancy


def render() -> None:
    st.session_state["_page"] = "interview"
    ui.header("Interview Preparation", "Job-related questions that verify unclear evidence and claimed skills.")
    c1, c2 = st.columns(2)
    with c1:
        vid = pick_vacancy()
    if vid is None:
        return
    with c2:
        cid = pick_candidate(vid)
    if cid is None:
        return
    render_questions(cid)


def render_questions(cid: int) -> None:
    key = f"iq_{cid}"
    if st.button("Regenerate questions", key=f"iqb_{cid}") or key not in st.session_state:
        with st.spinner("Preparing questions…"):
            with db.session_scope() as s:
                st.session_state[key] = services.interview_questions(s, s.get(Candidate, cid))
    questions, source = st.session_state[key]
    st.caption(f"Source: {source}. Questions never cover age, family, health, religion or other protected characteristics.")
    md_lines = []
    for n, q in enumerate(questions, start=1):
        with st.container(border=True):
            st.markdown(f"**{n}. {ui.esc(q['question'])}**")
            st.markdown(ui.chip(q["requirement"]), unsafe_allow_html=True)
            st.markdown(f"<span class='tl-muted'><b>Why ask:</b> {ui.esc(q['reason'])}</span>", unsafe_allow_html=True)
            st.markdown(f"<span class='tl-muted'><b>A strong answer shows:</b> {ui.esc(q['strong_answer'])}</span>", unsafe_allow_html=True)
            if q.get("follow_up"):
                st.markdown(f"<span class='tl-muted'><b>Follow-up:</b> {ui.esc(q['follow_up'])}</span>", unsafe_allow_html=True)
        md_lines += [f"{n}. **{q['question']}**", f"   - Requirement: {q['requirement']}", f"   - Why: {q['reason']}",
                     f"   - Strong answer: {q['strong_answer']}"] + ([f"   - Follow-up: {q['follow_up']}"] if q.get("follow_up") else [])
    st.download_button("Download interview guide", "\n".join(md_lines).encode(), file_name=f"interview_guide_{cid}.md", key=f"iqd_{cid}")
