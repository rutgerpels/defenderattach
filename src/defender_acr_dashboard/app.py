from __future__ import annotations

from datetime import datetime

from dash import Dash, Input, Output, State, dash_table, dcc, html
from dash.dcc import send_file

from .analytics import build_customer_metrics, customer_time_series, service_trends
from .charts import acr_trend_figure, defender_share_figure, service_trends_figure
from .config import (
    DEFAULT_DEFENDER_SHARE_THRESHOLD,
    DEFAULT_NON_DEFENDER_GROWTH_THRESHOLD,
    OUTPUT_DIR,
)
from .data import load_records
from .exports import create_powerpoint


def create_app() -> Dash:
    bundle = load_records()
    records = bundle.records
    customers = sorted(records["customer"].dropna().unique())
    default_customer = customers[0] if customers else None

    app = Dash(__name__, title="Defender ACR Opportunities", suppress_callback_exceptions=True)
    app.index_string = """<!DOCTYPE html>
<html>
  <head>
    <script>
      (() => {
        const param = new URLSearchParams(window.location.search).get("clawpilotTheme");
        const theme =
          param || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
        document.documentElement.setAttribute("data-theme", theme);
      })();
    </script>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
  </head>
  <body>
    {%app_entry%}
    <footer>
      {%config%}
      {%scripts%}
      {%renderer%}
    </footer>
  </body>
</html>"""
    app.layout = html.Div(
        className="app-shell",
        children=[
            dcc.Store(id="source-name", data=bundle.source_path.name),
            html.Header(
                className="hero",
                children=[
                    html.Div(
                        [
                            html.P("Azure ACR analytics", className="eyebrow"),
                            html.H1("Defender for Cloud growth opportunities"),
                            html.P(
                                "Compare total customer ACR with Defender for Cloud ACR, spot growth gaps, and export executive-ready findings.",
                                className="hero-copy",
                            ),
                        ]
                    ),
                    html.Div(
                        className="source-pill",
                        children=[html.Span("Source"), html.Strong(bundle.source_path.name)],
                    ),
                ],
            ),
            html.Section(
                className="controls card",
                children=[
                    html.Label("Customer drill-down"),
                    dcc.Dropdown(
                        id="customer-dropdown",
                        options=[{"label": customer, "value": customer} for customer in customers],
                        value=default_customer,
                        clearable=False,
                    ),
                    html.Label("Defender share threshold"),
                    dcc.Slider(
                        id="share-threshold",
                        min=0.01,
                        max=0.20,
                        step=0.01,
                        value=DEFAULT_DEFENDER_SHARE_THRESHOLD,
                        marks={0.05: "5%", 0.10: "10%", 0.20: "20%"},
                        tooltip={"placement": "bottom", "template": "{value:.0%}"},
                    ),
                    html.Label("Non-Defender MoM growth threshold"),
                    dcc.Slider(
                        id="growth-threshold",
                        min=0.0,
                        max=0.50,
                        step=0.05,
                        value=DEFAULT_NON_DEFENDER_GROWTH_THRESHOLD,
                        marks={0.10: "10%", 0.25: "25%", 0.50: "50%"},
                        tooltip={"placement": "bottom", "template": "{value:.0%}"},
                    ),
                    html.Button("Export PowerPoint", id="export-button", className="primary-button"),
                    dcc.Download(id="pptx-download"),
                ],
            ),
            html.Section(id="summary-cards", className="summary-grid"),
            html.Section(
                className="card",
                children=[
                    html.Div(
                        className="section-heading",
                        children=[
                            html.H2("Ranked customer opportunities"),
                            html.P("Flagged when Defender share is low while non-Defender ACR is growing."),
                        ],
                    ),
                    dash_table.DataTable(
                        id="opportunity-table",
                        page_size=12,
                        sort_action="native",
                        filter_action="native",
                        style_as_list_view=True,
                        style_cell={"fontFamily": "Segoe UI, Aptos, Calibri, sans-serif", "padding": "10px"},
                        style_header={"fontWeight": "700"},
                    ),
                ],
            ),
            html.Section(
                className="charts-grid",
                children=[
                    html.Div(className="card", children=[dcc.Graph(id="acr-trend")]),
                    html.Div(className="card", children=[dcc.Graph(id="share-trend")]),
                    html.Div(className="card wide", children=[dcc.Graph(id="service-trends")]),
                ],
            ),
        ],
    )

    @app.callback(
        Output("summary-cards", "children"),
        Output("opportunity-table", "data"),
        Output("opportunity-table", "columns"),
        Input("share-threshold", "value"),
        Input("growth-threshold", "value"),
    )
    def update_overview(share_threshold: float, growth_threshold: float):
        metrics = build_customer_metrics(records, share_threshold, growth_threshold)
        latest_total = metrics["latest_total_acr"].sum()
        latest_defender = metrics["latest_defender_acr"].sum()
        flagged = int(metrics["opportunity_flag"].sum())
        defender_share = latest_defender / latest_total if latest_total else 0
        cards = [
            _kpi_card("Total latest ACR", f"${latest_total:,.0f}"),
            _kpi_card("Defender ACR", f"${latest_defender:,.0f}"),
            _kpi_card("Defender share", f"{defender_share:.1%}"),
            _kpi_card("Flagged customers", f"{flagged:,}"),
        ]
        table = _format_metrics_table(metrics)
        columns = [{"name": name, "id": name} for name in table.columns]
        return cards, table.to_dict("records"), columns

    @app.callback(
        Output("acr-trend", "figure"),
        Output("share-trend", "figure"),
        Output("service-trends", "figure"),
        Input("customer-dropdown", "value"),
    )
    def update_customer(customer: str):
        series = customer_time_series(records, customer)
        trends = service_trends(records, customer)
        return (
            acr_trend_figure(series, customer),
            defender_share_figure(series, customer),
            service_trends_figure(trends, customer),
        )

    @app.callback(
        Output("pptx-download", "data"),
        Input("export-button", "n_clicks"),
        State("share-threshold", "value"),
        State("growth-threshold", "value"),
        State("source-name", "data"),
        prevent_initial_call=True,
    )
    def export_powerpoint(_clicks: int, share_threshold: float, growth_threshold: float, source_name: str):
        metrics = build_customer_metrics(records, share_threshold, growth_threshold)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = OUTPUT_DIR / f"defender-acr-opportunities-{stamp}.pptx"
        create_powerpoint(records, metrics, source_name, output_path)
        return send_file(str(output_path))

    return app


def _kpi_card(label: str, value: str) -> html.Div:
    return html.Div(className="kpi-card card", children=[html.Span(label), html.Strong(value)])


def _format_metrics_table(metrics):
    table = metrics.copy()
    table = table[
        [
            "customer",
            "latest_total_acr",
            "latest_defender_acr",
            "defender_share",
            "non_defender_growth_mom",
            "opportunity_flag",
            "top_growing_services",
        ]
    ]
    table.columns = [
        "Customer",
        "Total ACR",
        "Defender ACR",
        "Defender %",
        "Non-Defender MoM",
        "Opportunity",
        "Top growing services",
    ]
    table["Total ACR"] = table["Total ACR"].map(lambda value: f"${value:,.0f}")
    table["Defender ACR"] = table["Defender ACR"].map(lambda value: f"${value:,.0f}")
    table["Defender %"] = table["Defender %"].map(lambda value: f"{value:.1%}")
    table["Non-Defender MoM"] = table["Non-Defender MoM"].map(lambda value: f"{value:.1%}")
    table["Opportunity"] = table["Opportunity"].map(lambda value: "Yes" if value else "No")
    return table
