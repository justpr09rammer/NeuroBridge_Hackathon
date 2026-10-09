from __future__ import annotations

import pandas as pd
import streamlit as st

from talentlens.core import db, services
from talentlens.core import taxonomy as tx
from talentlens.ui import components as ui


def render() -> None:
    ui.header("Verified Learning Library", "The only source of learning links in TalentLens. Reports can never cite anything else.")
    render_library()


def render_library() -> None:
    with db.session_scope() as s:
        res = services.resource_dicts(s)
        idx = services.resource_index(s)

    st.markdown("##### Try the retrieval")
    q1, q2 = st.columns([2, 1])
    options = [s.key for s in tx.SKILLS] + ["lang_english", "education_degree", "project_experience", "experience_years"]
    names = {s.key: s.name for s in tx.SKILLS} | {"lang_english": "English", "education_degree": "Relevant degree",
                                                    "project_experience": "Project experience", "experience_years": "Work experience"}
    skill = q1.selectbox("Skill gap", options, format_func=lambda k: names[k])
    k = q2.slider("Results", 1, 5, 3)
    hits = idx.search(skill, names[skill], k=k)
    if hits:
        for h in hits:
            r = h.resource
            with st.container(border=True):
                st.markdown(f"**[{ui.esc(r['title'])}]({r['url']})** · {ui.esc(r['provider'])} · {ui.esc(r['difficulty'])}")
                st.markdown(f"<span class='tl-muted'>Relevance {h.score:.2f}. {ui.esc(h.reason)}</span>", unsafe_allow_html=True)
    else:
        st.info("No relevant resource in the curated library. TalentLens will say so in reports rather than invent a link.")

    st.markdown("##### Library")
    st.caption("Seed entries were curated by the team. 'Verification status' only says *verified* after the app has actually requested the URL. "
               "Estimated time is shown as 'Not stated' because we do not invent completion times.")
    df = pd.DataFrame(res)
    if not df.empty:
        df["last_checked"] = df["last_checked"].apply(lambda d: d.strftime("%Y-%m-%d %H:%M") if d is not None and not pd.isna(d) else "never")
        st.dataframe(df[["title", "provider", "skill", "topic", "difficulty", "estimated_time", "verification_status", "last_checked", "url"]],
                     hide_index=True, width="stretch", column_config={"url": st.column_config.LinkColumn("URL")})
    if st.button("Check all links now"):
        with st.spinner("Requesting each URL…"):
            with db.session_scope() as s:
                out = services.verify_resource_links(s)
        ok = sum(1 for o in out if o["status"].startswith("verified"))
        st.toast(f"{ok}/{len(out)} links verified. Network failures are recorded as 'status unknown', not as broken.")
        st.rerun()
