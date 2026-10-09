from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from talentlens import config
from talentlens.core import db, services
from talentlens.core.models import EvaluationRun
from talentlens.ui import components as ui

LOWER_IS_BETTER = ("D_fp_", "D_fn_")


def render() -> None:
    ui.header("Quality & Fairness Lab", "Real tests against the matching, scoring, security and retrieval pipeline. Nothing here is hard-coded.")
    with db.session_scope() as s:
        live_ok = services.live_mode_active(s) and services.get_setting(s, "llm_consent")
    b1, b2, b3 = st.columns([1, 1.3, 2])
    if b1.button("Run evaluation", type="primary", width="stretch"):
        with st.spinner("Running 12 hand-labelled + 24 generated CVs, 4 job descriptions, injection, name-swap and document tests…"):
            from talentlens.demo.seed import run_and_store_evaluation
            with db.session_scope() as s:
                run_and_store_evaluation(s)
        st.rerun()
    if b2.button("Run with live LLM", width="stretch", disabled=not live_ok,
                 help="Requires Live AI Mode, an API key and consent in Settings. Sends the synthetic CVs to the provider."):
        with st.spinner("Running model-dependent evaluation (this calls the API many times)…"):
            from talentlens.demo.seed import run_and_store_evaluation
            try:
                with db.session_scope() as s:
                    run_and_store_evaluation(s, use_llm=True)
            except Exception as e:
                st.error(f"Live evaluation failed: {e.__class__.__name__}. The local evaluation is unaffected.")
        st.rerun()

    with db.session_scope() as s:
        runs = s.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc())).all()
        run_opts = [(r.id, f"Run #{r.id} · {r.pipeline} · {r.created_at:%Y-%m-%d %H:%M}") for r in runs]
    if not runs:
        st.info("No evaluation has been run yet. Click **Run evaluation** (takes a few seconds).")
        return
    names = dict(run_opts)
    rid = b3.selectbox("Evaluation run", [r[0] for r in run_opts], format_func=lambda x: names[x])
    with db.session_scope() as s:
        run = s.get(EvaluationRun, rid)
        metrics = run.metrics
        cfg = run.config
        cases = [{"Metric": c.metric, "Case": c.case_name, "Passed": c.passed, "Expected": c.expected, "Actual": c.actual, "Details": c.details}
                 for c in run.cases]
        pipeline, duration = run.pipeline, run.duration_s

    st.caption(f"Pipeline: **{pipeline}** · dataset: {cfg.get('dataset')} · reference date {cfg.get('reference_date')} · "
               f"ran in {duration}s. Model-dependent metrics are labelled; deterministic checks do not depend on any model.")
    ui.box("<b>Read these numbers honestly.</b> Hand-labelled = 12 demo CVs labelled by the team from each CV's intent. "
           "Generator-labelled = 24 template CVs whose labels come from how each skill was written; they test rule consistency and are "
           "<b>optimistic</b> compared with real CVs. Job descriptions were written by the team. Small samples: treat results as a smoke test, "
           "not a benchmark.", "flag")

    groups: dict[str, list] = {}
    for k, m in metrics.items():
        groups.setdefault(m["group"], []).append((k, m))
    for g, items in groups.items():
        st.markdown(f"##### {g.capitalize()}")
        cols = st.columns(4)
        for i, (k, m) in enumerate(items):
            v = m["value"]
            hint = f"n = {m['n']}" + (f" · best achievable {m['ceiling']:.0%}" if m.get("ceiling") is not None and m["ceiling"] < 1 else "")
            hint += " · lower is better" if k.startswith(LOWER_IS_BETTER) else ""
            with cols[i % 4]:
                ui.kpi(m["label"], ui.fmt_pct(v), hint)
                with st.popover("What does this measure?", width="stretch"):
                    st.write(m["explanation"])
        st.write("")

    st.markdown("##### Hand-labelled vs generator-labelled agreement")
    labels = ["3-class agreement", "False-positive rate", "False-negative rate"]
    fig = go.Figure()
    for ds, color in (("hand-labelled", ui.ACCENT), ("generator-labelled", "#94A3B8")):
        vals = [metrics.get(f"D_acc_{ds}", {}).get("value"), metrics.get(f"D_fp_{ds}", {}).get("value"), metrics.get(f"D_fn_{ds}", {}).get("value")]
        fig.add_bar(name=ds, x=labels, y=[(v or 0) * 100 for v in vals], marker_color=color, text=[ui.fmt_pct(v) for v in vals], textposition="outside")
    fig.update_layout(barmode="group", height=280, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(range=[0, 110], title="%"),
                      plot_bgcolor="white", paper_bgcolor="white", legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.markdown("##### Inspect cases")
    df = pd.DataFrame(cases)
    f1, f2 = st.columns([1, 2])
    only_failed = f1.toggle("Failed cases only", value=True)
    metric_sel = f2.multiselect("Metric", sorted(df["Metric"].unique()), default=[])
    view = df
    if only_failed:
        view = view[~view["Passed"]]
    if metric_sel:
        view = view[view["Metric"].isin(metric_sel)]
    st.caption(f"{int((~df['Passed']).sum())} failed of {len(df)} recorded cases. Failures are kept visible on purpose: they are what we fix next.")
    st.dataframe(view, hide_index=True, width="stretch",
                 column_config={"Passed": st.column_config.CheckboxColumn("Passed"), "Details": st.column_config.TextColumn(width="large")})
    st.download_button("Download cases (CSV)", df.to_csv(index=False).encode(), file_name=f"evaluation_run_{rid}.csv")
    st.caption(f"Local pipeline id: {config.LOCAL_PIPELINE_NAME}. Deterministic unit tests also run via pytest (see README).")
