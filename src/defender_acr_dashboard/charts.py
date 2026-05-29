from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def acr_trend_figure(series: pd.DataFrame, customer: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=series["period_start"],
            y=series["total_acr"],
            mode="lines+markers",
            name="Total ACR",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=series["period_start"],
            y=series["defender_acr"],
            mode="lines+markers",
            name="Defender for Cloud ACR",
        )
    )
    fig.update_layout(
        title=f"Total vs Defender ACR trend: {customer}",
        yaxis_title="ACR ($)",
        xaxis_title="Month",
        hovermode="x unified",
    )
    return apply_layout(fig)


def defender_share_figure(series: pd.DataFrame, customer: str) -> go.Figure:
    fig = go.Figure(
        go.Scatter(
            x=series["period_start"],
            y=series["defender_share"],
            mode="lines+markers",
            name="Defender share",
            fill="tozeroy",
        )
    )
    fig.update_layout(
        title=f"Defender share of total ACR: {customer}",
        yaxis_title="Share",
        xaxis_title="Month",
        hovermode="x unified",
    )
    fig.update_yaxes(tickformat=".1%")
    return apply_layout(fig)


def service_trends_figure(trends: pd.DataFrame, customer: str) -> go.Figure:
    fig = go.Figure()
    for service, group in trends.groupby("service_group"):
        fig.add_trace(
            go.Scatter(
                x=group["period_start"],
                y=group["acr"],
                mode="lines+markers",
                name=service,
            )
        )
    fig.update_layout(
        title=f"Top non-Defender service trends: {customer}",
        yaxis_title="ACR ($)",
        xaxis_title="Month",
        hovermode="x unified",
    )
    return apply_layout(fig)


def apply_layout(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        margin={"l": 48, "r": 24, "t": 64, "b": 48},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        font={"family": "Segoe UI, Aptos, Calibri, sans-serif", "size": 13},
    )
    fig.update_yaxes(gridcolor="rgba(145,145,145,0.25)", separatethousands=True)
    fig.update_xaxes(gridcolor="rgba(145,145,145,0.18)")
    return fig
