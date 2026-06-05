"""Streamlit UI for the service-level Defender attach motion.

Run with:  streamlit run streamlit_app.py
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Make the src/ package importable without an install step.
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from defender_acr_dashboard.service_attach.engine import BookModel, build_model  # noqa: E402
from defender_acr_dashboard.service_attach.mapping import (  # noqa: E402
    AttachConfig,
    DEFENDER_SL2,
)
from defender_acr_dashboard.service_attach.parser import (  # noqa: E402
    LEVEL_LEAF,
    ParsedData,
    parse_sl2_sl4,
)
from defender_acr_dashboard.service_attach import export  # noqa: E402

DEFAULT_FILE = ROOT / "inputfolder" / "ACR Details SL2-SL4.xlsx"
UPLOAD_TMP_STATE_KEY = "_defender_attach_upload_tmp"

st.set_page_config(
    page_title="Defender Attach — Service Level", page_icon="🛡️", layout="wide"
)


@st.cache_data(show_spinner="Parsing workbook…")
def _parse_cached(path: str, sig: str) -> ParsedData:
    return parse_sl2_sl4(path)


@st.cache_data(show_spinner="Scoring book…")
def _build_cached(path: str, sig: str, cfg_key: tuple) -> BookModel:
    parsed = _parse_cached(path, sig)
    config = AttachConfig(
        target_ratio=cfg_key[0],
        weight_gap=cfg_key[1],
        weight_momentum=cfg_key[2],
        weight_breadth=cfg_key[3],
        min_denominator=cfg_key[4],
        attach_threshold=cfg_key[5],
        use_cohort_median=cfg_key[6],
    )
    return build_model(parsed, config)


def _cleanup_uploaded_temp(except_path: Path | None = None) -> None:
    previous = st.session_state.get(UPLOAD_TMP_STATE_KEY)
    if not previous:
        return
    previous_path = Path(previous)
    if except_path is not None and previous_path == except_path:
        return
    try:
        previous_path.unlink(missing_ok=True)
    except OSError as exc:
        st.sidebar.warning(f"Could not remove previous uploaded workbook temp file: {exc}")
        return
    st.session_state.pop(UPLOAD_TMP_STATE_KEY, None)


def _write_uploaded_temp(raw: bytes, sig: str) -> Path:
    tmp = Path(tempfile.gettempdir()) / f"defender_attach_{sig}.xlsx"
    _cleanup_uploaded_temp(except_path=tmp)
    if not tmp.exists() or tmp.stat().st_size != len(raw):
        tmp.write_bytes(raw)
    st.session_state[UPLOAD_TMP_STATE_KEY] = str(tmp)
    return tmp


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.0f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


# --------------------------------------------------------------------------- #
# Sidebar — data source + scoring knobs
# --------------------------------------------------------------------------- #
st.sidebar.title("🛡️ Defender Attach")
st.sidebar.caption("Service-level (SL2/SL4) attach motion")

uploaded = st.sidebar.file_uploader("Upload SL2/SL4 workbook (.xlsx)", type=["xlsx"])

using_uploaded = False
source_label = ""
if uploaded is not None:
    try:
        raw = uploaded.getbuffer()
        sig = hashlib.md5(raw).hexdigest()  # content-based key so re-uploads bust the cache
        tmp = _write_uploaded_temp(bytes(raw), sig)
    except Exception as exc:  # noqa: BLE001
        st.sidebar.error(f"❌ Could not read the uploaded file: {exc}")
        st.stop()
    data_path = tmp
    using_uploaded = True
    source_label = uploaded.name
elif DEFAULT_FILE.exists():
    _cleanup_uploaded_temp()
    data_path = DEFAULT_FILE
    stat = DEFAULT_FILE.stat()
    sig = f"{stat.st_mtime_ns}:{stat.st_size}"
    source_label = DEFAULT_FILE.name
    st.sidebar.caption(f"Using bundled file: {DEFAULT_FILE.name}")
else:
    st.info(
        "👋 Upload an SL2/SL4 `.xlsx` workbook in the sidebar to begin "
        f"(or place one at `{DEFAULT_FILE}`)."
    )
    st.stop()

st.sidebar.subheader("Scoring")
target_ratio = st.sidebar.slider(
    "Default target attach ratio", 0.01, 0.20, 0.06, 0.01,
    help="Fallback Defender $ / workload $ benchmark when cohort median is off or sample is thin.",
)
use_cohort = st.sidebar.checkbox(
    "Use cohort-median benchmark", value=True,
    help="Derive each plan's benchmark from peers who already attach it.",
)
attach_threshold = st.sidebar.slider(
    "Attached threshold ($/mo)", 0.0, 50.0, 5.0, 1.0,
    help="Defender spend at or below this counts as 'not attached'.",
)
min_denom = st.sidebar.slider(
    "Minimum workload base ($/mo)", 0.0, 1000.0, 100.0, 50.0,
    help="Suppress dollar benchmarks when the workload is smaller than this.",
)
st.sidebar.subheader("Blend weights")
w_gap = st.sidebar.slider("Gap weight", 0.0, 1.0, 0.5, 0.05)
w_mom = st.sidebar.slider("Momentum weight", 0.0, 1.0, 0.3, 0.05)
w_breadth = st.sidebar.slider("Breadth weight", 0.0, 1.0, 0.2, 0.05)

cfg_key = (
    target_ratio, w_gap, w_mom, w_breadth, min_denom, attach_threshold, use_cohort,
)

# --- Parse + score with explicit, user-facing error handling ---------------- #
try:
    parsed = _parse_cached(str(data_path), sig)
    model = _build_cached(str(data_path), sig, cfg_key)
except Exception as exc:  # noqa: BLE001
    st.error(
        f"❌ Could not read **{source_label}**.\n\n"
        "This usually means the file isn't the expected SL2/SL4 pivot export. "
        "Make sure it's an `.xlsx` with a sheet named **Export**, a two-row header "
        "(row 1 = FiscalMonth groups like `FY26-Jul`, row 2 = measures including "
        "`$ ACR`), and the dimension columns `TPAccountName`, `ServiceLevel2`, "
        "`ServiceLevel4`."
    )
    with st.expander("Technical details"):
        st.exception(exc)
    st.stop()

# --- Validate that the workbook actually matches the expected schema -------- #
problems: list[str] = []
if not parsed.months:
    problems.append(
        "No monthly **`$ ACR`** columns were detected. Expected a two-row header "
        "where row 1 holds FiscalMonth groups (e.g. `FY26-Jul`) and row 2 holds "
        "`$ ACR`."
    )
if parsed.frame.empty or (parsed.frame["level"] == LEVEL_LEAF).sum() == 0:
    problems.append("No service-level (SL4) rows were found in the workbook.")
if not parsed.frame.empty and not (parsed.frame["sl2"] == DEFENDER_SL2).any():
    problems.append(
        f"No **{DEFENDER_SL2}** rows were found — Defender attach gaps cannot be "
        "computed without them."
    )
if model.total_eligible_workload_acr <= 0:
    problems.append(
        "No mapped Azure workload spend was detected, so there is nothing to "
        "measure attach against."
    )

if problems:
    st.error(
        f"⚠️ **{source_label}** loaded, but it doesn't look like the expected "
        "SL2/SL4 export:\n\n"
        + "\n".join(f"- {p}" for p in problems)
    )
    st.stop()

# --- Success feedback -------------------------------------------------------- #
if using_uploaded:
    st.sidebar.success(
        f"✅ Loaded **{source_label}**\n\n"
        f"{len(model.dossiers)} customers · {len(model.months)} months"
    )

recon_ok = all(i.rel_diff <= 0.01 for i in model.reconciliation)

st.title("Defender for Cloud — Service-Level Attach")
_src_note = "uploaded" if using_uploaded else "bundled"
st.caption(
    f"{len(model.dossiers)} customers · {len(model.months)} months · "
    f"latest {model.latest_month} · source {model.source_name} ({_src_note})"
)
if not recon_ok:
    st.warning(
        "Some customer subtotals did not reconcile within 1%. Figures are usable "
        "but treat reconciliation-flagged customers with care."
    )

tab_mgr, tab_cust, tab_export = st.tabs(
    ["📊 Manager view", "🏢 Customer dossier", "📤 Export"]
)

# --------------------------------------------------------------------------- #
# Manager view
# --------------------------------------------------------------------------- #
with tab_mgr:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Book attach ratio", _pct(model.book_attach_ratio))
    c2.metric("Eligible workload ACR", _money(model.total_eligible_workload_acr))
    c3.metric("Defender ACR", _money(model.total_dfc_acr))
    c4.metric("Quantified gap / mo", _money(model.total_gap_dollars))

    st.subheader("Ranked opportunities")
    rows = []
    for i, d in enumerate(model.dossiers, start=1):
        rows.append(
            {
                "Rank": i,
                "Customer": d.customer,
                "Score": round(d.customer_score, 1),
                "Eligible $": round(d.eligible_workload_acr),
                "Defender $": round(d.dfc_acr),
                "Attach %": None if d.attach_ratio is None else round(d.attach_ratio * 100, 1),
                "Gap $/mo": round(d.total_gap_dollars),
                "Unprotected": f"{d.uncovered_eligible_count}/{d.present_eligible_count}",
                "Reconciled": "✓" if d.reconciliation_ok else "⚠",
            }
        )
    table = pd.DataFrame(rows)
    st.dataframe(table, use_container_width=True, hide_index=True, height=460)

    st.subheader("Top 15 customers by opportunity score")
    top = model.dossiers[:15][::-1]
    fig = go.Figure(
        go.Bar(
            x=[d.customer_score for d in top],
            y=[d.customer for d in top],
            orientation="h",
            marker_color="#0a7cff",
            customdata=[
                [round(d.total_gap_dollars), d.uncovered_eligible_count] for d in top
            ],
            hovertemplate="<b>%{y}</b><br>Score %{x:.0f}<br>"
            "Gap $%{customdata[0]:,}/mo<br>%{customdata[1]} unprotected<extra></extra>",
        )
    )
    fig.update_layout(
        height=520, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Opportunity score (0-100)",
    )
    st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------------------- #
# Customer dossier
# --------------------------------------------------------------------------- #
with tab_cust:
    names = [d.customer for d in model.dossiers]
    selected = st.selectbox("Customer", names)
    dossier = next(d for d in model.dossiers if d.customer == selected)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Customer ACR (total)", _money(dossier.customer_total_acr))
    k2.metric("Eligible workload ACR", _money(dossier.eligible_workload_acr))
    k3.metric("Defender ACR", _money(dossier.dfc_acr), _pct(dossier.attach_ratio))
    k4.metric("Quantified gap / mo", _money(dossier.total_gap_dollars))

    st.subheader("Attach opportunities")
    opp_rows = []
    for o in sorted(dossier.opportunities, key=lambda x: x.blended_score, reverse=True):
        opp_rows.append(
            {
                "Plan": o.plan_label,
                "Signal": o.signal,
                "Type": "💲 gap" if o.has_dollar_gap else "● coverage",
                "Confidence": o.confidence,
                "Workload $": round(o.workload_acr),
                "Defender $": round(o.defender_actual),
                "Benchmark %": None if o.benchmark_ratio is None else round(o.benchmark_ratio * 100, 1),
                "Gap $/mo": round(o.gap_dollars) if o.has_dollar_gap else None,
                "Score": round(o.blended_score, 1),
            }
        )
    if opp_rows:
        st.dataframe(
            pd.DataFrame(opp_rows), use_container_width=True, hide_index=True
        )
    else:
        st.info("No open attach opportunities — this customer is well covered.")

    # Workload vs Defender grouped bars for top opportunities
    st.subheader("Workload spend vs. Defender spend")
    top_opps = sorted(
        dossier.opportunities, key=lambda x: x.blended_score, reverse=True
    )[:8]
    if top_opps:
        bar = go.Figure()
        bar.add_bar(
            name="Workload $/mo",
            x=[o.plan_label for o in top_opps],
            y=[o.workload_acr for o in top_opps],
            marker_color="#9aa0a6",
        )
        bar.add_bar(
            name="Defender $/mo",
            x=[o.plan_label for o in top_opps],
            y=[o.defender_actual for o in top_opps],
            marker_color="#0a7cff",
        )
        bar.update_layout(
            barmode="group", height=380, margin=dict(l=10, r=10, t=10, b=80),
            xaxis_tickangle=-30, yaxis_title="$ ACR / mo",
        )
        st.plotly_chart(bar, use_container_width=True)

        opt = st.selectbox(
            "Trend — pick a plan", [o.plan_label for o in top_opps]
        )
        picked = next(o for o in top_opps if o.plan_label == opt)
        trend = go.Figure()
        trend.add_scatter(
            x=model.months, y=picked.workload_series, name="Workload $",
            mode="lines+markers", line=dict(color="#9aa0a6"),
        )
        trend.add_scatter(
            x=model.months, y=picked.defender_series, name="Defender $",
            mode="lines+markers", line=dict(color="#0a7cff"),
        )
        trend.update_layout(
            height=320, margin=dict(l=10, r=10, t=10, b=10),
            yaxis_title="$ ACR / mo",
        )
        st.plotly_chart(trend, use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Foundational coverage")
        if dossier.foundational:
            fnd = pd.DataFrame(
                [
                    {
                        "Plan": f.plan_label,
                        "Status": "Active" if f.present else "Not active",
                        "$ / mo": round(f.actual),
                    }
                    for f in dossier.foundational
                ]
            )
            st.dataframe(fnd, use_container_width=True, hide_index=True)
        else:
            st.caption("No foundational plan data.")
    with col_b:
        st.subheader("Top Azure spend")
        if dossier.top_spend:
            spend = pd.DataFrame(
                [{"Service": s.sl2, "$ / mo": round(s.acr)} for s in dossier.top_spend]
            )
            st.dataframe(spend, use_container_width=True, hide_index=True)
        else:
            st.caption("No spend data.")

    st.subheader("Conversation openers")
    for o in sorted(dossier.opportunities, key=lambda x: x.blended_score, reverse=True)[:6]:
        st.markdown(f"- {o.opener}")


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
with tab_export:
    st.subheader("Agentic export")
    st.write(
        "Download a machine-readable JSON (source of truth) plus a Markdown brief "
        "containing an agent-prompt block to generate a deck or dashboard."
    )
    top_n = st.slider("Customers to include in the brief", 5, len(model.dossiers), 15)
    json_text = export.build_json_text(model)
    md_text = export.build_markdown(model, "defender_attach_data.json", top_customers=top_n)

    d1, d2 = st.columns(2)
    d1.download_button(
        "⬇️ Download data (JSON)", json_text, file_name="defender_attach_data.json",
        mime="application/json",
    )
    d2.download_button(
        "⬇️ Download brief (Markdown)", md_text, file_name="defender_attach_brief.md",
        mime="text/markdown",
    )
    with st.expander("Preview Markdown brief"):
        st.markdown(md_text)
