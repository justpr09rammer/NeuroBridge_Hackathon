from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import select

from talentlens.core import db, services
from talentlens.core import taxonomy as tx
from talentlens.core.models import Vacancy
from talentlens.core.requirements import normalize_weights
from talentlens.ui import components as ui

COLS = ["name", "category", "priority", "weight", "description", "guidance", "synonyms", "key"]
EMPLOYMENT = ["Full-time", "Part-time", "Contract", "Internship", "Temporary"]


def _df_from(rows: list[dict]) -> pd.DataFrame:
    data = []
    for r in rows:
        syn = r.get("synonyms") or []
        data.append({"name": r.get("name", ""), "category": r.get("category", tx.TECHNICAL), "priority": r.get("priority", "must"),
                     "weight": float(r.get("weight") or 0), "description": r.get("description", ""), "guidance": r.get("guidance", ""),
                     "synonyms": ", ".join(syn) if isinstance(syn, list) else str(syn), "key": r.get("key", "")})
    return pd.DataFrame(data, columns=COLS)


def _bump() -> None:
    st.session_state["req_editor_v"] = st.session_state.get("req_editor_v", 0) + 1


def _load_context(choice_id: int | None) -> None:
    """Load a saved vacancy (or a blank draft) into session state."""
    st.session_state["vac_ctx"] = choice_id
    if choice_id is None:
        st.session_state["vac_fields"] = {"title": "", "company": "", "department": "", "location": "", "employment_type": "Full-time",
                                          "salary_range": "", "description": "", "recruiter_notes": ""}
        st.session_state["req_rows"] = []
        st.session_state["req_meta"] = {}
        st.session_state["vac_flags"] = []
        st.session_state["vac_source"] = "local"
    else:
        with db.session_scope() as s:
            v = s.get(Vacancy, choice_id)
            st.session_state["vac_fields"] = {k: getattr(v, k) for k in ("title", "company", "department", "location", "employment_type",
                                                                         "salary_range", "description", "recruiter_notes")}
            rows = [services.requirement_dict(r) for r in v.requirements]
            st.session_state["req_rows"] = rows
            st.session_state["req_meta"] = {r["key"]: {"id": r["id"], "params": r["params"]} for r in rows}
            st.session_state["vac_flags"] = v.wording_flags or []
            st.session_state["vac_source"] = v.extraction_source
    _bump()


def render() -> None:
    st.session_state["_page"] = "vacancy"
    ui.header("Create Vacancy", "Paste a job description, review the extracted requirements, then save.")
    with db.session_scope() as s:
        vacancies = [(v.id, f"{v.title} · {v.company}" if v.company else v.title) for v in s.scalars(select(Vacancy).order_by(Vacancy.id)).all()]
        mode_label = services.pipeline_label(s)

    options = [None] + [vid for vid, _ in vacancies]
    labels = {None: "New vacancy", **{vid: f"Edit: {lab}" for vid, lab in vacancies}}
    if st.session_state.pop("vacancy_mode", None) == "new":
        st.session_state["vac_select"] = None
    if "vac_select_pending" in st.session_state:
        st.session_state["vac_select"] = st.session_state.pop("vac_select_pending")
    if msg := st.session_state.pop("vac_flash", None):
        st.success(msg)
    choice = st.selectbox("Vacancy", options, format_func=lambda x: labels[x], key="vac_select")
    if st.session_state.get("vac_ctx", "unset") != choice or "vac_fields" not in st.session_state:
        _load_context(choice)

    f = st.session_state["vac_fields"]
    c1, c2, c3 = st.columns(3)
    f["title"] = c1.text_input("Job title *", f["title"])
    f["company"] = c2.text_input("Company", f["company"])
    f["department"] = c3.text_input("Department", f["department"])
    c4, c5, c6 = st.columns(3)
    f["location"] = c4.text_input("Location", f["location"])
    f["employment_type"] = c5.selectbox("Employment type", EMPLOYMENT, index=EMPLOYMENT.index(f["employment_type"]) if f["employment_type"] in EMPLOYMENT else 0)
    f["salary_range"] = c6.text_input("Salary range (optional)", f["salary_range"])
    f["description"] = st.text_area("Job description", f["description"], height=260,
                                    placeholder="Paste the full job advertisement, including requirements and nice-to-haves.")
    f["recruiter_notes"] = st.text_area("Recruiter notes (optional)", f["recruiter_notes"], height=70)

    b1, b2 = st.columns([1, 3])
    if b1.button("Analyse job description", type="primary", width="stretch", disabled=not f["description"].strip()):
        with st.spinner("Extracting requirements…"):
            with db.session_scope() as s:
                specs, flags, source, err = services.analyze_job_description(s, f["description"], f["title"])
        if err:
            st.warning(err)
        st.session_state["req_rows"] = [x.to_dict() for x in specs]
        meta = st.session_state.get("req_meta", {})
        st.session_state["req_meta"] = {x.key: {"id": meta.get(x.key, {}).get("id"), "params": x.params} for x in specs}
        st.session_state["vac_flags"] = flags
        st.session_state["vac_source"] = source
        _bump()
        st.rerun()
    b2.caption(f"Extraction uses: {mode_label}. Results are always editable.")

    flags = st.session_state.get("vac_flags", [])
    if flags:
        st.markdown("##### Wording review suggestions")
        st.caption("Automated prompts to review the advert. These are not legal judgements.")
        for fl in flags:
            ui.box(f"<b>{ui.esc(fl['label'])}</b>: “{ui.esc(fl['match'])}”. {ui.esc(fl['advice'])}"
                   + (f"<br><span class='tl-muted'>{ui.esc(fl['line'])}</span>" if fl.get("line") else ""))

    st.markdown("##### Requirements checklist")
    st.caption("Must-haves that are not clearly evidenced send a candidate to human review; nobody is rejected automatically. "
               "Soft skills are interview topics and never scored (weight is forced to 0).")
    df = _df_from(st.session_state.get("req_rows", []))
    if df.empty:
        st.info("No requirements yet. Analyse the job description, or add rows manually below.")
    edited = st.data_editor(
        df, num_rows="dynamic", width="stretch", hide_index=True, key=f"req_editor_{st.session_state.get('req_editor_v', 0)}",
        column_config={
            "name": st.column_config.TextColumn("Requirement", required=True, width="medium"),
            "category": st.column_config.SelectboxColumn("Category", options=tx.CATEGORIES, required=True, width="medium"),
            "priority": st.column_config.SelectboxColumn("Must / nice", options=["must", "nice"], required=True, width="small"),
            "weight": st.column_config.NumberColumn("Weight", min_value=0.0, max_value=100.0, step=1.0, format="%.1f", width="small"),
            "description": st.column_config.TextColumn("Description"),
            "guidance": st.column_config.TextColumn("Assessment guidance"),
            "synonyms": st.column_config.TextColumn("Synonyms (comma-separated)"),
            "key": st.column_config.TextColumn("Key", help="Internal identifier. Leave empty for new requirements.", width="small"),
        })
    total_w = float(edited.loc[edited["category"] != tx.SOFT, "weight"].fillna(0).sum()) if not edited.empty else 0.0
    st.caption(f"Total weight of scored requirements: {total_w:.1f}")

    def rows_from(ed: pd.DataFrame) -> list[dict]:
        meta = st.session_state.get("req_meta", {})
        rows = []
        for _, r in ed.iterrows():
            if not str(r.get("name") or "").strip():
                continue
            key = str(r.get("key") or "").strip()
            m = meta.get(key, {})
            rows.append({"id": m.get("id"), "key": key, "name": str(r["name"]).strip(), "category": r.get("category") or tx.OTHER,
                         "priority": r.get("priority") or "must", "weight": float(r.get("weight") or 0),
                         "description": str(r.get("description") or ""), "guidance": str(r.get("guidance") or ""),
                         "synonyms": [x.strip() for x in str(r.get("synonyms") or "").split(",") if x.strip()],
                         "params": m.get("params", {})})
        return rows

    s1, s2, s3 = st.columns([1, 1, 2])
    if s1.button("Normalise weights to 100", width="stretch", disabled=edited.empty):
        rows = rows_from(edited)
        scored = [i for i, r in enumerate(rows) if r["category"] != tx.SOFT]
        for i, w in zip(scored, normalize_weights([rows[i]["weight"] for i in scored])):
            rows[i]["weight"] = w
        st.session_state["req_rows"] = rows
        _bump()
        st.rerun()
    if s2.button("Save vacancy", type="primary", width="stretch"):
        rows = rows_from(edited)
        if not f["title"].strip():
            st.error("Job title is required.")
        elif not rows:
            st.error("Add at least one requirement.")
        else:
            try:
                with db.session_scope() as s:
                    if choice is None:
                        v = services.create_vacancy(s, f, rows, st.session_state.get("vac_flags", []), source=st.session_state.get("vac_source", "local"))
                        msg = f"Vacancy '{v.title}' created."
                    else:
                        v = s.get(Vacancy, choice)
                        services.update_vacancy(s, v, f, rows, reassess=True)
                        msg = f"Vacancy '{v.title}' saved; {len(v.candidates)} candidate(s) re-assessed."
                    vid = v.id
                st.session_state["vacancy_id"] = vid
                st.session_state["vac_ctx"] = "reload"
                st.session_state["vac_select_pending"] = vid
                st.session_state["vac_flash"] = msg
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    if choice is not None and s3.button("Go to screening for this vacancy", width="stretch"):
        ui.go("screening", vacancy_id=choice)
