from __future__ import annotations

import pandas as pd
import streamlit as st

from talentlens import config
from talentlens.core import db, services
from talentlens.core import taxonomy as tx
from talentlens.core.models import Candidate, Vacancy
from talentlens.ui import components as ui
from talentlens.ui.selectors import pick_vacancy


def _weights_panel(vid: int, reqs: list[dict]) -> dict[str, float]:
    weights: dict[str, float] = {}
    scored = [r for r in reqs if r["category"] != tx.SOFT]
    with st.expander("Adjust requirement weights (scores update live)", expanded=False):
        st.caption("Weights only change the evidence-match score. Statuses and evidence stay the same. "
                   "Formula: score = 100 × Σ(weight × value) / Σ(weight), where Demonstrated = 1, Unclear = 0.5, Not found = 0.")
        cols = st.columns(3)
        for i, r in enumerate(scored):
            k = f"w_{vid}_{r['key']}"
            if k not in st.session_state:
                st.session_state[k] = float(r["weight"])
            label = f"{r['name']} ({'must' if r['priority'] == 'must' else 'nice'})"
            weights[r["key"]] = cols[i % 3].slider(label, 0.0, 50.0, step=1.0, key=k)
        b1, b2, _ = st.columns([1, 1, 2])
        if b1.button("Save weights to vacancy"):
            with db.session_scope() as s:
                v = s.get(Vacancy, vid)
                rows = []
                for r in v.requirements:
                    d = services.requirement_dict(r)
                    if r.key in weights:
                        d["weight"] = weights[r.key]
                    rows.append(d)
                services.update_vacancy(s, v, {}, rows, reassess=True)
            st.toast("Weights saved and candidates re-assessed.")
        if b2.button("Reset to saved weights"):
            for r in scored:
                st.session_state.pop(f"w_{vid}_{r['key']}", None)
            st.rerun()
    return weights


def _upload(vid: int) -> None:
    with st.expander("Upload CVs (PDF, batch)", expanded=False):
        st.caption(f"PDF only, up to {config.MAX_UPLOAD_BYTES // 1_048_576} MB each. Files and extracted text stay on this machine "
                   "unless Live AI Mode with consent is enabled in Settings.")
        files = st.file_uploader("Select PDF CVs", type=["pdf"], accept_multiple_files=True, key=f"up_{vid}")
        c1, c2 = st.columns(2)
        if c1.button("Process uploaded files", type="primary", disabled=not files):
            prog = st.progress(0.0, text="Processing…")
            msgs = []
            with db.session_scope() as s:
                v = s.get(Vacancy, vid)
                for i, f in enumerate(files[: config.MAX_FILES_PER_BATCH]):
                    cand, msg = services.ingest_cv(s, v, f.name, f.getvalue())
                    msgs.append(("ok" if cand else "danger", msg))
                    prog.progress((i + 1) / len(files), text=f"Processed {i + 1}/{len(files)}")
            st.session_state["upload_msgs"] = msgs
            st.rerun()
        if c2.button("Load the 12 fictional sample CVs into this vacancy"):
            from talentlens.demo.seed import demo_pdf_bytes
            msgs = []
            with db.session_scope() as s:
                v = s.get(Vacancy, vid)
                for fname, data in demo_pdf_bytes():
                    cand, msg = services.ingest_cv(s, v, fname, data, is_synthetic=True)
                    msgs.append(("ok" if cand else "danger", msg))
            st.session_state["upload_msgs"] = msgs
            st.rerun()
    for kind, msg in st.session_state.pop("upload_msgs", []):
        ui.box(ui.esc(msg), "flag" if ("Flagged" in msg or "duplicate" in msg or "Hidden" in msg) and kind == "ok" else kind)


def render() -> None:
    st.session_state["_page"] = "screening"
    ui.header("Candidate Screening", "Evidence-based ranking. Every score can be traced to quotations from the CV.")
    vid = pick_vacancy()
    if vid is None:
        return
    with db.session_scope() as s:
        v = s.get(Vacancy, vid)
        reqs = [services.requirement_dict(r) for r in v.requirements]
        blind_saved = bool(services.get_setting(s, "blind_mode"))

    t1, t2 = st.columns([1, 3])
    blind = t1.toggle("Blind screening", value=blind_saved, help="Hides names and contact details in the workspace. "
                      "In Live AI Mode, names are also removed from text sent to the model.")
    if blind != blind_saved:
        with db.session_scope() as s:
            services.set_setting(s, "blind_mode", blind)
        st.rerun()
    t2.caption("Blind mode cannot remove every proxy for bias (e.g. university names, career gaps). It reduces direct identifiers only.")

    _upload(vid)
    weights = _weights_panel(vid, reqs)

    with db.session_scope() as s:
        v = s.get(Vacancy, vid)
        rows = services.candidate_rows(s, v, weights=weights, blind=blind)
    if not rows:
        st.info("No candidates yet. Upload PDF CVs above, or load the fictional sample CVs.")
        return

    f1, f2, f3, f4 = st.columns([2, 2, 1.2, 1.2])
    q = f1.text_input("Search", placeholder="Candidate ID or name")
    statuses = sorted({r["screening_status"] for r in rows})
    sel_status = f2.multiselect("Screening status", statuses, default=statuses)
    only_review = f3.checkbox("Needs review only")
    show = f4.radio("Show", ["Top 50", "All"], horizontal=True)
    sort_by = st.selectbox("Sort by", ["Rank (score)", "Must-haves verified first, then score"] + [f"Category: {c}" for c in tx.SCORED_CATEGORIES])

    view = [r for r in rows if r["screening_status"] in sel_status and (not only_review or r["needs_review"])]
    if q.strip():
        ql = q.strip().lower()
        view = [r for r in view if ql in r["display_id"].lower() or (not blind and ql in r["name"].lower())]
    if sort_by.startswith("Must-haves"):
        view.sort(key=lambda r: (r["must_have_status"] != "Verified", r["rank"]))
    elif sort_by.startswith("Category: "):
        cat = sort_by.split(": ", 1)[1]
        view.sort(key=lambda r: (-(r.get(cat) if r.get(cat) is not None else -1), r["rank"]))
    hidden_count = 0
    if show == "Top 50" and len(view) > 50:
        hidden_count = len(view) - 50
        view = view[:50]

    df = pd.DataFrame([{
        "Rank": r["rank"], "ID": r["display_id"], "Candidate": r["name"], "Score": r["score"],
        **{c.replace(" (interview only)", ""): r.get(c) for c in tx.SCORED_CATEGORIES if any(x["category"] == c for x in reqs)},
        "Demonstrated": r["demonstrated"], "Unclear": r["unclear"], "Not found": r["not_found"],
        "Must-haves": r["must_have_status"], "Review": "Yes" if r["needs_review"] else "", "Doc flags": r["flags"],
        "Status": r["screening_status"],
    } for r in view])
    if blind:
        df = df.drop(columns=["Candidate"])
    cat_cfg = {c: st.column_config.ProgressColumn(c, min_value=0, max_value=100, format="%.0f") for c in tx.SCORED_CATEGORIES if c in df.columns}
    event = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                         column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"), **cat_cfg},
                         key=f"tbl_{vid}")
    st.caption(f"Showing {len(view)} of {len(rows)} candidates" + (f" ({hidden_count} more under 'All'; nobody is removed for a low score)." if hidden_count else ".")
               + " Select rows to act on them. Scores measure CV evidence for this vacancy, not a person's worth or future performance.")

    selected = [view[i]["candidate_id"] for i in event.selection.rows] if event and event.selection.rows else []
    a1, a2, a3, a4, a5 = st.columns(5)
    if a1.button("Open detail", disabled=len(selected) != 1, width="stretch"):
        ui.go("candidate", candidate_id=selected[0])
    compare = a2.button("Compare", disabled=not (2 <= len(selected) <= 4), width="stretch", help="Select 2-4 candidates")
    if a3.button("Mark for review", disabled=not selected, width="stretch"):
        with db.session_scope() as s:
            for cid in selected:
                services.set_review_flag(s, s.get(Candidate, cid), True, "Marked from screening table")
        st.rerun()
    if a4.button("Clear review mark", disabled=not selected, width="stretch"):
        with db.session_scope() as s:
            for cid in selected:
                services.set_review_flag(s, s.get(Candidate, cid), False, "Cleared from screening table")
        st.rerun()
    export = pd.DataFrame(rows).drop(columns=[] if not blind else ["name"])
    a5.download_button("Export CSV", export.to_csv(index=False).encode(), file_name=f"screening_vacancy_{vid}.csv",
                       mime="text/csv", width="stretch")

    if compare and selected:
        st.markdown("##### Side-by-side comparison")
        with db.session_scope() as s:
            table: dict[str, dict] = {}
            for cid in selected:
                c = s.get(Candidate, cid)
                col = services.display_label(c, blind)
                for it in services.assessment_items(c.latest_assessment):
                    row = table.setdefault(it["name"], {"Requirement": it["name"], "Must/nice": it["priority"]})
                    row[col] = ui.STATUS_STYLE[it["status"]][0]
        cmp = pd.DataFrame(list(table.values()))

        def color(v: str) -> str:
            for k, (label, fg, bg, _) in ui.STATUS_STYLE.items():
                if v == label:
                    return f"color:{fg};background-color:{bg}"
            return ""
        st.dataframe(cmp.style.map(color), hide_index=True, width="stretch")
