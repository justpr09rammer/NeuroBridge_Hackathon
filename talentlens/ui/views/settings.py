from __future__ import annotations

import streamlit as st

from talentlens import config
from talentlens.core import db, services
from talentlens.core import taxonomy as tx
from talentlens.ui import components as ui

DEMO_SCRIPT = """
**Three-minute demo script**

1. **Dashboard** (15 s): 12 fictional CVs already screened.
2. **1 · Vacancy** (30 s): pick *Edit: Software Engineer*. The job ad is split into categories with must/nice and weights; "young and dynamic team" is flagged.
3. **2 · Screening** (40 s): the ranked table with category scores. Raise the *Docker* weight and the ranking changes instantly.
4. **3 · Candidate** (40 s): open *Rashad Valiyev* (high score, English level not stated → human review) and *Lala Huseynova* (prompt injection flagged and ignored). Every result has a quote from the CV.
5. **4 · Decisions & Emails** (40 s): shortlist the top 4 and click *Apply decisions*. Open a rejection email: it says what matched, what was missing by category, and gives free verified resources and a practice project.
6. **Quality Lab** (15 s): *Run evaluation*, show the results and the failed cases.
"""


def render() -> None:
    ui.header("Settings & Demo Guide", "Processing mode, privacy, scoring policy and demo data.")
    with db.session_scope() as s:
        mode = services.get_setting(s, "mode")
        consent = bool(services.get_setting(s, "llm_consent"))
        blind = bool(services.get_setting(s, "blind_mode"))
        policy = services.get_setting(s, "policy")

    st.markdown("##### Processing mode")
    key_present = config.anthropic_key_present()
    m = st.radio("Mode", ["demo", "live"], index=0 if mode != "live" else 1, horizontal=True,
                 format_func={"demo": "Demo Mode (local, no API key, default)", "live": "Live AI Mode (Anthropic API)"}.get)
    if m == "live" and not key_present:
        ui.box("ANTHROPIC_API_KEY is not set, so Live AI Mode is unavailable and the app keeps using local analysis. "
               "Add it to <code>.env</code> and restart.", "danger")
    c = st.checkbox("I consent to sending CV text (with email, phone and profile links removed; names too in blind mode) to Anthropic "
                    "for assessment, question generation and evaluation.", value=consent, disabled=m != "live")
    st.caption(f"Model: {config.ANTHROPIC_MODEL} (set ANTHROPIC_MODEL to change). The LLM never computes scores; every quotation it returns "
               "is checked against the CV and discarded if not found verbatim. Without consent, CV analysis stays local even in Live AI Mode "
               "(job-description analysis may still use the model).")
    b = st.toggle("Blind screening by default", value=blind)
    if st.button("Save settings", type="primary"):
        with db.session_scope() as s:
            services.set_setting(s, "mode", m)
            services.set_setting(s, "llm_consent", bool(c and m == "live"))
            services.set_setting(s, "blind_mode", b)
        st.toast("Settings saved.")
        st.rerun()

    st.markdown("##### Scoring policy")
    st.caption("score = 100 × Σ(weight × value) / Σ(weight). Values are configurable; changes apply to every score immediately.")
    p1, p2, p3 = st.columns(3)
    d = p1.number_input("Demonstrated", 0.0, 1.0, float(policy.get(tx.DEMONSTRATED, 1.0)), 0.05)
    u = p2.number_input("Unclear", 0.0, 1.0, float(policy.get(tx.UNCLEAR, 0.5)), 0.05)
    n = p3.number_input("Not found", 0.0, 1.0, float(policy.get(tx.NOT_FOUND, 0.0)), 0.05)
    if st.button("Save scoring policy"):
        if not (d >= u >= n):
            st.error("Values must satisfy Demonstrated ≥ Unclear ≥ Not found.")
        else:
            with db.session_scope() as s:
                services.set_setting(s, "policy", {tx.DEMONSTRATED: d, tx.UNCLEAR: u, tx.NOT_FOUND: n})
            st.toast("Scoring policy saved.")

    st.markdown("##### Demo data")
    d1, d2 = st.columns(2)
    if d1.button("Load demo scenario", width="stretch"):
        from talentlens.demo.seed import seed_demo
        with db.session_scope() as s:
            out = seed_demo(s)
        st.success("Demo scenario ready." if out["vacancy_created"] else "Demo scenario was already loaded; nothing duplicated.")
    if d2.button("Reset demo data…", width="stretch"):
        st.session_state["confirm_reset"] = True
    if st.session_state.get("confirm_reset"):
        st.warning("This deletes the demo vacancy, its candidates, reports and all evaluation runs, then reloads fresh demo data. "
                   "Vacancies you created yourself are kept.")
        r1, r2 = st.columns(2)
        if r1.button("Yes, reset demo data", type="primary"):
            from talentlens.demo.seed import reset_demo
            with db.session_scope() as s:
                reset_demo(s)
            for k in [k for k in st.session_state if k.startswith(("w_", "pick_", "iq_", "reveal_"))] + ["candidate_id", "vacancy_id", "confirm_reset"]:
                st.session_state.pop(k, None)
            st.success("Demo data reset.")
        if r2.button("Cancel"):
            st.session_state["confirm_reset"] = False
            st.rerun()

    st.markdown("##### Verified learning library")
    with st.expander("Curated resources used in emails and reports (the only links TalentLens can cite)"):
        from talentlens.ui.views.library import render_library
        render_library()

    st.markdown("##### Demo guide")
    st.markdown(DEMO_SCRIPT)
    st.markdown("##### Privacy, security and limitations")
    st.markdown(
        "- Data is stored locally in SQLite (`var/talentlens.db`); uploaded PDFs in `var/uploads/`. Delete any candidate from its detail page.\n"
        "- CVs are treated as untrusted data: instruction-like text and hidden (white or microscopic) text are flagged and never used as evidence.\n"
        "- No authentication or role-based access is implemented. The 'reveal identity' button is a UI control, not a security boundary.\n"
        "- The local analysis is rule-based: it can miss evidence written in unexpected ways, and it does not read scanned (image-only) PDFs.\n"
        "- **This is a hackathon MVP, not production-ready for real hiring decisions.** It supports recruiters; it does not replace them, "
        "and it does not eliminate bias.")
