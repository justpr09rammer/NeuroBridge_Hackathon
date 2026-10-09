from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from talentlens.core import db, services
from talentlens.core import taxonomy as tx
from talentlens.core.models import Candidate, RequirementAssessment
from talentlens.core.security import redact_pii
from talentlens.ui import components as ui
from talentlens.ui.selectors import pick_candidate, pick_vacancy


def render() -> None:
    st.session_state["_page"] = "candidate"
    ui.header("Candidate Detail", "Requirement-by-requirement evidence, uncertainty and recruiter actions.")
    c1, c2 = st.columns(2)
    with c1:
        vid = pick_vacancy()
    if vid is None:
        return
    with c2:
        cid = pick_candidate(vid)
    if cid is None:
        return

    with db.session_scope() as s:
        c = s.get(Candidate, cid)
        blind = bool(services.get_setting(s, "blind_mode"))
        reveal = st.session_state.get(f"reveal_{cid}", False)
        show_identity = not blind or reveal
        a = c.latest_assessment
        items = services.assessment_items(a)
        sr = services.score_assessment(s, a)
        doc = c.documents[0]
        history = [(x.created_at, x.pipeline, x.score, x.needs_review) for x in c.assessments]
        reviews = [(r.created_at, r.kind, r.decision, r.note, r.payload, r.author) for r in c.reviews]
        decision = services.latest_decision(c)
        profile = c.profile or {}
        flags = a.security_flags
        pipeline = a.pipeline
        doc_text = doc.text if show_identity else redact_pii(doc.text, c.name, c.display_id)
        name_line = f"{c.name or 'Name not detected'} · {c.email}" if show_identity else f"{c.display_id} (identity hidden)"
        synthetic = c.is_synthetic

    # Overview -----------------------------------------------------------------
    o1, o2, o3, o4 = st.columns([2, 1, 1, 1])
    with o1:
        st.markdown(f"### {ui.esc(name_line)}", unsafe_allow_html=True)
        st.markdown(ui.chip(c.display_id) + ui.chip(pipeline) + (ui.chip("Fictional") if synthetic else "")
                    + (ui.chip(f"Decision: {decision}") if decision else ""), unsafe_allow_html=True)
        if blind and not reveal and st.button("Reveal identity (authorised recruiter)"):
            st.session_state[f"reveal_{cid}"] = True
            st.rerun()
    with o2:
        ui.kpi("Evidence-match score", f"{sr.score:.1f}", "Not a measure of worth or future performance")
    with o3:
        ui.kpi("Demonstrated / Unclear / Not found", f"{sr.counts[tx.DEMONSTRATED]} / {sr.counts[tx.UNCLEAR]} / {sr.counts[tx.NOT_FOUND]}")
    with o4:
        ui.kpi("Human review", "Needed" if sr.needs_review else "Not needed")

    if sr.review_reasons:
        ui.box("<b>Why human review is needed:</b><br>" + "<br>".join("• " + ui.esc(r) for r in sr.review_reasons), "flag")
    for f in flags:
        kind = "danger" if f.get("severity") == "review" else "flag"
        ui.box(f"<b>{ui.esc(f['type'].replace('_', ' ').capitalize())}</b>: {ui.esc(f['detail'])}"
               + (f"<br><span class='tl-muted'>“{ui.esc(f['text'])}”</span>" if f.get("text") else ""), kind)

    # Score breakdown --------------------------------------------------------------
    left, right = st.columns([1, 1.4])
    with left:
        st.markdown("##### Score by category")
        cats = list(sr.category_scores.items())
        if cats:
            fig = go.Figure(go.Bar(x=[v for _, v in cats], y=[k for k, _ in cats], orientation="h", marker_color=ui.ACCENT,
                                   text=[f"{v:.0f}" for _, v in cats], textposition="outside"))
            fig.update_layout(height=60 + 42 * len(cats), margin=dict(l=10, r=30, t=10, b=10), xaxis=dict(range=[0, 110], visible=False),
                              plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.markdown("##### Job-specific summary")
        strong = [i["name"] for i in items if i["status"] == tx.DEMONSTRATED]
        gaps = [i["name"] for i in items if i["status"] == tx.NOT_FOUND and i["category"] != tx.SOFT]
        unclear = [i["name"] for i in items if i["status"] == tx.UNCLEAR and i["category"] != tx.SOFT]
        st.markdown(f"**Clear evidence:** {', '.join(strong) or 'none'}  \n**Unclear:** {', '.join(unclear) or 'none'}  \n"
                    f"**Not found in CV:** {', '.join(gaps) or 'none'}")
        st.caption("'Not found in CV' means the CV did not show it, not that the candidate lacks the skill.")
        if st.button("Go to decisions & emails", width="stretch"):
            ui.go("emails", candidate_id=cid)

    with right:
        st.markdown("##### Requirement-by-requirement evidence")
        for it in items:
            prio = "Must-have" if it["priority"] == "must" else "Nice-to-have"
            title = f"{it['name']} · {prio} · {ui.STATUS_STYLE[it['status']][0]}" + (" · corrected" if it["corrected"] else "")
            with st.expander(title, expanded=it["status"] != tx.DEMONSTRATED and it["priority"] == "must" and it["category"] != tx.SOFT):
                st.markdown(ui.badge(it["status"]) + " " + ui.chip(it["category"]) + (ui.chip(f"weight {it['weight']:.0f}") if it["category"] != tx.SOFT else ui.chip("interview only")),
                            unsafe_allow_html=True)
                if it["evidence"]:
                    ev = it["evidence"] if show_identity else redact_pii(it["evidence"], c.name, c.display_id)
                    ui.quote(ev, it["page"])
                else:
                    st.markdown("<span class='tl-muted'>No supporting quotation.</span>", unsafe_allow_html=True)
                st.markdown(ui.esc(it["explanation"]))
                if it["uncertainty"]:
                    st.markdown(f"<span class='tl-muted'><b>Uncertainty:</b> {ui.esc(it['uncertainty'])}</span>", unsafe_allow_html=True)
                if it["follow_up"] and it["status"] != tx.DEMONSTRATED:
                    st.markdown(f"<span class='tl-muted'><b>Follow-up question:</b> {ui.esc(it['follow_up'])}</span>", unsafe_allow_html=True)
                if it["corrected"]:
                    st.caption(f"Original automated status: {ui.STATUS_STYLE[it['original_status']][0]}")
                with st.form(f"corr_{it['ra_id']}", border=False):
                    cc1, cc2, cc3 = st.columns([1.2, 2, 0.8])
                    new = cc1.selectbox("Correct status", tx.STATUSES, index=tx.STATUSES.index(it["status"]),
                                        format_func=lambda x: ui.STATUS_STYLE[x][0], key=f"cs_{it['ra_id']}")
                    note = cc2.text_input("Reason", key=f"cn_{it['ra_id']}", placeholder="e.g. Confirmed in phone screen")
                    if cc3.form_submit_button("Save") and new != it["status"]:
                        with db.session_scope() as s:
                            services.apply_correction(s, s.get(RequirementAssessment, it["ra_id"]), new, note)
                        st.rerun()

    # Recruiter actions ------------------------------------------------------------
    st.markdown("##### Recruiter decision and notes")
    d1, d2 = st.columns([1, 2])
    with d1:
        with st.form("decision"):
            dec = st.radio("Decision", ["advance", "hold", "rejected"], horizontal=True,
                           format_func={"advance": "Advance", "hold": "Hold", "rejected": "Reject"}.get)
            dnote = st.text_input("Reason (recorded)")
            if st.form_submit_button("Record decision", type="primary"):
                with db.session_scope() as s:
                    services.record_decision(s, s.get(Candidate, cid), dec, dnote)
                st.rerun()
        st.caption("Decisions are only ever recorded by a person. The system never rejects a candidate.")
    with d2:
        with st.form("note", clear_on_submit=True):
            n = st.text_area("Add a note", height=80)
            if st.form_submit_button("Save note"):
                with db.session_scope() as s:
                    services.add_note(s, s.get(Candidate, cid), n)
                st.rerun()
        if reviews:
            st.dataframe(pd.DataFrame([{"When": w.strftime("%Y-%m-%d %H:%M"), "Type": k, "Decision": d, "Note": nt,
                                        "Detail": (f"{p.get('requirement')}: {p.get('from')} → {p.get('to')}" if k == "correction" else
                                                   ("marked" if p.get("on") else "cleared") if k == "flag" else ""), "By": by}
                                       for w, k, d, nt, p, by in reversed(reviews)]), hide_index=True, width="stretch")

    with st.expander("Candidate profile (extracted)"):
        if show_identity:
            st.json({k: profile.get(k) for k in ("name", "email", "phone")}, expanded=False)
        st.markdown("**Skills mentioned:** " + (", ".join(sorted({x['skill'] for x in profile.get('skills', [])})) or "none"))
        for sec in ("dated_roles", "projects", "education", "certifications", "languages"):
            vals = profile.get(sec) or []
            if vals:
                st.markdown(f"**{sec.replace('_', ' ').capitalize()}**")
                for x in vals[:8]:
                    st.markdown(f"- {ui.esc(x['text'] if show_identity else redact_pii(x['text'], c.name, c.display_id))} "
                                f"<span class='tl-muted'>(p. {x['page']})</span>", unsafe_allow_html=True)
    with st.expander("Extracted CV text (visible text only)"):
        st.text(doc_text[:8000])
        b1, b2 = st.columns(2)
        if b1.button("Re-process document"):
            with db.session_scope() as s:
                msg = services.reprocess_document(s, s.get(Candidate, cid))
            st.toast(msg)
            st.rerun()
        if b2.button("Delete candidate and stored file", type="secondary"):
            st.session_state[f"confirm_del_{cid}"] = True
        if st.session_state.get(f"confirm_del_{cid}"):
            st.warning("This permanently deletes the candidate, assessments, reports and the stored PDF.")
            if st.button("Confirm delete"):
                with db.session_scope() as s:
                    services.delete_candidate(s, s.get(Candidate, cid))
                st.session_state.pop("candidate_id", None)
                st.rerun()
    with st.expander("Assessment history"):
        st.dataframe(pd.DataFrame([{"When": w.strftime("%Y-%m-%d %H:%M:%S"), "Pipeline": p, "Score at the time": sc, "Needs review": nr}
                                   for w, p, sc, nr in reversed(history)]), hide_index=True, width="stretch")
        if st.button("Re-run assessment now"):
            with db.session_scope() as s:
                services.assess_candidate(s, s.get(Candidate, cid))
            st.rerun()

    st.markdown("##### Interview questions")
    with st.expander("Job-related questions for this candidate", expanded=False):
        from talentlens.ui.views.interview import render_questions
        render_questions(cid)
    st.markdown("##### Development report")
    with st.expander("Detailed feedback report with learning plan", expanded=False):
        from talentlens.ui.views.reports import render_report
        render_report(cid)
