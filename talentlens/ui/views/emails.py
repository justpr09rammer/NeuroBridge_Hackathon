from __future__ import annotations

import io
import zipfile

import pandas as pd
import streamlit as st

from talentlens.core import db, services
from talentlens.core.models import Candidate, Vacancy
from talentlens.ui import components as ui
from talentlens.ui.selectors import pick_vacancy

DECISION_LABEL = {"advance": "Shortlisted (invite)", "rejected": "Rejected (feedback email)", "hold": "On hold (human review)", None: "No decision yet"}


def render() -> None:
    st.session_state["_page"] = "emails"
    ui.header("Decisions & Emails", "Shortlist the top candidates, then send every applicant a clear answer. Rejections explain why and include free resources.")
    vid = pick_vacancy()
    if vid is None:
        return

    with db.session_scope() as s:
        v = s.get(Vacancy, vid)
        n = len(v.candidates)
        rows = services.candidate_rows(s, v)

    # Step 1: bulk decision (a human action) --------------------------------------
    st.markdown("##### 1. Decide")
    c1, c2, c3 = st.columns([1.2, 1, 1])
    top_n = c1.number_input("Shortlist the top N candidates", 1, max(n, 1), min(50, max(1, n // 3)), 1)
    if c2.button("Apply decisions", type="primary", width="stretch"):
        with db.session_scope() as s:
            out = services.bulk_decide(s, s.get(Vacancy, vid), int(top_n))
        st.session_state["bulk_msg"] = (f"{out['advance']} shortlisted · {out['rejected']} rejected · {out['hold']} on hold for human review"
                                        + (f" · {out['unchanged']} already decided (unchanged)" if out["unchanged"] else ""))
        st.rerun()
    if c3.button("Clear all decisions", width="stretch"):
        with db.session_scope() as s:
            services.clear_decisions(s, s.get(Vacancy, vid))
        st.rerun()
    st.caption("Candidates outside the shortlist are rejected only when their CV clearly misses requirements. "
               "Anyone with an *unclear* must-have or a document flag (e.g. prompt injection, hidden text) is put on hold for a person to check.")
    if msg := st.session_state.pop("bulk_msg", None):
        ui.box(ui.esc(msg), "ok")

    # Step 2: overview ------------------------------------------------------------
    st.markdown("##### 2. Review")
    with db.session_scope() as s:
        v = s.get(Vacancy, vid)
        table, emails = [], {}
        for r in rows:
            c = s.get(Candidate, r["candidate_id"])
            d = services.latest_decision(c)
            e = services.candidate_email(s, c)
            if e:
                emails[c.id] = (c.name or c.display_id, c.email, e)
            table.append({"Rank": r["rank"], "Candidate": c.name or c.display_id, "Score": r["score"], "Decision": DECISION_LABEL[d],
                          "Email": ("Sent" if services.email_sent(c) else "Ready") if e else "–", "_id": c.id})
    df = pd.DataFrame(table)
    st.dataframe(df.drop(columns=["_id"]), hide_index=True, width="stretch",
                 column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f")})

    if not emails:
        st.info("No emails yet. Apply decisions above, or record a decision on a candidate's page.")
        return

    # Step 3: preview and send ------------------------------------------------------
    st.markdown("##### 3. Preview and send")
    ids = list(emails)
    labels = {i: f"{emails[i][0]} · {'Invitation' if emails[i][2].kind == 'invitation' else 'Rejection with feedback'}" for i in ids}
    default = st.session_state.get("candidate_id") if st.session_state.get("candidate_id") in ids else ids[0]
    cid = st.selectbox("Email", ids, index=ids.index(default), format_func=lambda i: labels[i])
    name, address, e = emails[cid]
    with st.container(border=True):
        st.markdown(f"**To:** {ui.esc(address or 'no email address found')}  \n**Subject:** {ui.esc(e.subject)}")
        st.text(e.body)
    if e.resources:
        st.caption("Resources in this email come only from the verified library: "
                   + ", ".join(f"[{r['title']}]({r['url']})" for r in e.resources))

    b1, b2, b3 = st.columns(3)
    if b1.button("Send this email", width="stretch"):
        with db.session_scope() as s:
            services.mark_email_sent(s, s.get(Candidate, cid), e.subject)
        st.toast("Marked as sent (demo: no mail server is configured).")
        st.rerun()
    if b2.button(f"Send all {len(emails)} emails", type="primary", width="stretch"):
        with db.session_scope() as s:
            for i, (_, _, em) in emails.items():
                c = s.get(Candidate, i)
                if not services.email_sent(c):
                    services.mark_email_sent(s, c, em.subject)
        st.toast("All emails marked as sent (demo: no mail server is configured).")
        st.rerun()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (nm, addr, em) in emails.items():
            z.writestr(f"{em.kind}_{nm.replace(' ', '_')}.txt", f"To: {addr}\nSubject: {em.subject}\n\n{em.body}\n")
    b3.download_button("Download all emails (.zip)", buf.getvalue(), file_name=f"emails_vacancy_{vid}.zip", width="stretch")
    st.caption("Sending is simulated in this demo: emails are marked as sent and can be downloaded. Connecting a mail server is the next step.")
