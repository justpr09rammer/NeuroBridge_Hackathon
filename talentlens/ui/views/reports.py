from __future__ import annotations

import streamlit as st

from talentlens.core import db, services
from talentlens.core.models import Candidate
from talentlens.ui import components as ui
from talentlens.ui.selectors import pick_candidate, pick_vacancy


def render() -> None:
    st.session_state["_page"] = "reports"
    ui.header("Candidate Development Reports", "Respectful, specific feedback with verified learning resources (RAG over the curated library).")
    c1, c2 = st.columns(2)
    with c1:
        vid = pick_vacancy()
    if vid is None:
        return
    with c2:
        cid = pick_candidate(vid)
    if cid is None:
        return

    render_report(cid)


def render_report(cid: int) -> None:
    with db.session_scope() as s:
        c = s.get(Candidate, cid)
        decision = services.latest_decision(c)
        reports = [(r.id, r.created_at, r.markdown, r.resource_urls, r.source) for r in c.reports]
        label = services.display_label(c, bool(services.get_setting(s, "blind_mode")))

    st.markdown(
        ui.chip(f"Recorded decision: {decision}" if decision else "No recruiter decision recorded")
        + ui.chip("Rejection wording only appears after a recruiter records 'Reject'"), unsafe_allow_html=True)
    with st.expander("How this report is built (RAG pipeline)"):
        st.markdown(
            "1. **Evidence and gaps**: requirements marked *Unclear* or *Not found in CV* for this vacancy.\n"
            "2. **Retrieval query**: each gap is normalised (skill name + synonyms).\n"
            "3. **Curated search**: TF-IDF retrieval over the Verified Learning Library only, with a skill-tag boost.\n"
            "4. **Selection**: top resources above a relevance threshold, each with the reason it was retrieved.\n"
            "5. **Report**: template-based plan in Demo Mode. Any URL not in the library is stripped before display.")

    b1, _ = st.columns([1, 3])
    if b1.button("Generate report", type="primary", width="stretch", key=f"rep_{cid}"):
        with db.session_scope() as s:
            services.generate_report(s, s.get(Candidate, cid))
        st.rerun()

    if not reports:
        st.info(f"No report yet for {label}. Click **Generate report**.")
        return
    rid, created, md, urls, source = reports[-1]
    st.caption(f"Report #{rid} · generated {created:%Y-%m-%d %H:%M} · {source} · {len(urls)} library resource(s) linked")
    with st.container(border=True):
        st.markdown(md)
    st.download_button("Download as Markdown", md.encode(), file_name=f"development_report_{label.replace(' ', '_')}.md", mime="text/markdown", key=f"repd_{cid}")
    if len(reports) > 1:
        with st.expander(f"Earlier versions ({len(reports) - 1})"):
            for rid_, created_, md_, _, _ in reversed(reports[:-1]):
                st.markdown(f"**Report #{rid_}** · {created_:%Y-%m-%d %H:%M}")
                st.text(md_[:1500])
