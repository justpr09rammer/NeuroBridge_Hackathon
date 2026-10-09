"""Vacancy / candidate pickers shared by several pages."""
from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from talentlens.core import db, services
from talentlens.core.models import Candidate, Vacancy


def pick_vacancy(label: str = "Vacancy") -> int | None:
    with db.session_scope() as s:
        vs = [(v.id, f"{v.title}" + (f" · {v.company}" if v.company else "") + f" ({len(v.candidates)} candidates)")
              for v in s.scalars(select(Vacancy).order_by(Vacancy.id)).all()]
    if not vs:
        st.info("No vacancies yet. Create one, or load the demo scenario from Settings & Demo Guide.")
        return None
    ids = [v[0] for v in vs]
    current = st.session_state.get("vacancy_id")
    names = dict(vs)
    wkey = f"pick_vac_{st.session_state.get('_page', '')}"
    if current in ids and st.session_state.get(wkey) != current:
        st.session_state[wkey] = current  # sync with selection made on another page
    elif st.session_state.get(wkey) not in ids:
        st.session_state[wkey] = ids[0]
    vid = st.selectbox(label, ids, format_func=lambda x: names[x], key=wkey,
                       on_change=lambda: st.session_state.update(vacancy_id=st.session_state[wkey]))
    st.session_state["vacancy_id"] = vid
    return vid


def pick_candidate(vacancy_id: int, label: str = "Candidate") -> int | None:
    with db.session_scope() as s:
        blind = bool(services.get_setting(s, "blind_mode"))
        v = s.get(Vacancy, vacancy_id)
        rows = services.candidate_rows(s, v, blind=blind)
        labels = {r["candidate_id"]: f"#{r['rank']} {services.display_label(s.get(Candidate, r['candidate_id']), blind)} · score {r['score']:.1f}"
                  + (" · review" if r["needs_review"] else "") for r in rows}
    if not rows:
        st.info("No assessed candidates for this vacancy yet. Upload CVs in Candidate Screening.")
        return None
    ids = [r["candidate_id"] for r in rows]
    current = st.session_state.get("candidate_id")
    wkey = f"pick_cand_{st.session_state.get('_page', '')}"
    if current in ids and st.session_state.get(wkey) != current:
        st.session_state[wkey] = current
    elif st.session_state.get(wkey) not in ids:
        st.session_state[wkey] = ids[0]
    cid = st.selectbox(label, ids, format_func=lambda x: labels[x], key=wkey,
                       on_change=lambda: st.session_state.update(candidate_id=st.session_state[wkey]))
    st.session_state["candidate_id"] = cid
    return cid
