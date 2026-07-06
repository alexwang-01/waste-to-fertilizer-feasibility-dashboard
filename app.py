from __future__ import annotations

from dataclasses import replace
from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard_service import (
    calculate_dashboard_result,
    load_dashboard_data,
    normalize_dashboard_data,
    select_machine,
    view_assumptions_from_row,
)
from src.demand_forecasting import DemandForecastResult, forecast_daily_waste
from src.demand_simulation import CUSTOMER_PROFILES, simulate_daily_waste
from src.financial_model import FeasibilityInputs, MachineFleetItem, MachineSpec, machine_count
from src.scenario_analysis import inputs_from_scenario
from src.view_model import ViewAssumptions


ROOT = Path(__file__).resolve().parent
DEFAULT_CUSTOMER_CASE = "base"
DATA_CACHE_VERSION = "provider-anonymized-v3"
RECOVERY_CHART_HEIGHT = 456
MONTHLY_VALUE_CHART_HEIGHT = 430
CAPACITY_UTILIZATION_CHART_HEIGHT = 456
RECOVERY_CHART_BOTTOM_MARGIN = 105
MONTHLY_VALUE_CHART_BOTTOM_MARGIN = 80
CAPACITY_CHART_BOTTOM_MARGIN = 80
DEAL_STRUCTURES = {
    "CapEx (Customer-owned Machine)": {
        "view_preset": "capex_customer_owned",
        "business_model": "capex",
        "customer_investment_share": 1.0,
    },
    "OpEx (Provider-owned Machine)": {
        "view_preset": "opex_provider_rental",
        "business_model": "opex",
        "customer_investment_share": 0.0,
    },
    "Co-investment (Shared Machine Cost)": {
        "view_preset": "capex_customer_owned",
        "business_model": "capex",
        "customer_investment_share": None,
    },
}


st.set_page_config(
    page_title="Deal Calculator",
    page_icon=None,
    layout="wide",
)


@st.cache_data
def _load_data(version: str = DATA_CACHE_VERSION) -> dict[str, pd.DataFrame]:
    _ = version
    return load_dashboard_data(ROOT)


def _session_machine_master(source: pd.DataFrame) -> pd.DataFrame:
    if "machine_master_data" not in st.session_state:
        st.session_state["machine_master_data"] = _sanitize_machine_master(source, fallback=source)
    return _sanitize_machine_master(st.session_state["machine_master_data"], fallback=source)


def _session_personnel_master(source: pd.DataFrame) -> pd.DataFrame:
    if "personnel_master_data" not in st.session_state:
        st.session_state["personnel_master_data"] = _sanitize_personnel_master(source, fallback=source)
    return _sanitize_personnel_master(st.session_state["personnel_master_data"], fallback=source)


def _sanitize_machine_master(data: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "model",
        "capacity_kg",
        "capacity_ton",
        "power_kw",
        "heater_kw",
        "total_load_kw",
        "operation_hours_per_day",
        "asia_price_no_ce_usd",
        "asia_price_with_ce_usd",
        "europe_price_with_ce_usd",
        "monthly_rental_ratio",
        "source_note",
    ]
    df = data.copy()
    for column in columns:
        if column not in df.columns:
            df[column] = "" if column in {"model", "source_note"} else 0.0
    df = df[columns].copy()
    df["model"] = df["model"].astype(str).str.strip()
    numeric_columns = [column for column in columns if column not in {"model", "source_note"}]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.loc[df["model"].ne("")].copy()
    df["capacity_ton"] = df["capacity_ton"].fillna(df["capacity_kg"] / 1000)
    df["capacity_kg"] = df["capacity_kg"].fillna(df["capacity_ton"] * 1000)
    df["power_kw"] = df["power_kw"].fillna(0.0).clip(lower=0.0)
    df["heater_kw"] = df["heater_kw"].fillna(0.0).clip(lower=0.0)
    df["total_load_kw"] = df["total_load_kw"].fillna(df["power_kw"] + df["heater_kw"]).clip(lower=0.0)
    df["operation_hours_per_day"] = df["operation_hours_per_day"].fillna(24.0).clip(lower=0.0)
    df["asia_price_no_ce_usd"] = df["asia_price_no_ce_usd"].fillna(0.0).clip(lower=0.0)
    df["asia_price_with_ce_usd"] = df["asia_price_with_ce_usd"].clip(lower=0.0)
    df["europe_price_with_ce_usd"] = df["europe_price_with_ce_usd"].clip(lower=0.0)
    df["monthly_rental_ratio"] = df["monthly_rental_ratio"].fillna(0.0065).clip(lower=0.0)
    df["source_note"] = df["source_note"].fillna("Session edit").astype(str)
    df = df.loc[df["capacity_ton"].fillna(0.0).gt(0.0)].copy()
    if df.empty:
        return _sanitize_machine_master(fallback, fallback=fallback)
    return df.reset_index(drop=True)


def _sanitize_personnel_master(data: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "labor_type",
        "role",
        "headcount",
        "monthly_salary_usd",
        "monthly_total_usd",
        "source_note",
    ]
    df = data.copy()
    for column in columns:
        if column not in df.columns:
            df[column] = "" if column in {"labor_type", "role", "source_note"} else 0.0
    df = df[columns].copy()
    df["labor_type"] = df["labor_type"].astype(str).str.strip().str.title()
    df.loc[~df["labor_type"].isin(["Direct", "Indirect"]), "labor_type"] = "Direct"
    df["role"] = df["role"].astype(str).str.strip()
    df["headcount"] = pd.to_numeric(df["headcount"], errors="coerce").fillna(0.0).clip(lower=0.0)
    df["monthly_salary_usd"] = (
        pd.to_numeric(df["monthly_salary_usd"], errors="coerce").fillna(0.0).clip(lower=0.0)
    )
    df["monthly_total_usd"] = df["headcount"] * df["monthly_salary_usd"]
    df["source_note"] = df["source_note"].fillna("Session edit").astype(str)
    df = df.loc[df["role"].ne("")].copy()
    if df.empty:
        return _sanitize_personnel_master(fallback, fallback=fallback)
    return df.reset_index(drop=True)


def _personnel_labor_totals(personnel: pd.DataFrame) -> dict[str, float]:
    direct = personnel.loc[personnel["labor_type"].eq("Direct"), "monthly_total_usd"].sum()
    indirect = personnel.loc[personnel["labor_type"].eq("Indirect"), "monthly_total_usd"].sum()
    return {"direct": float(direct), "indirect": float(indirect)}


def _blank_machine_row(index: int) -> dict[str, object]:
    return {
        "model": f"New model {index}",
        "capacity_kg": 1000.0,
        "capacity_ton": 1.0,
        "power_kw": 0.0,
        "heater_kw": 0.0,
        "total_load_kw": 0.0,
        "operation_hours_per_day": 24.0,
        "asia_price_no_ce_usd": 0.0,
        "asia_price_with_ce_usd": 0.0,
        "europe_price_with_ce_usd": 0.0,
        "monthly_rental_ratio": 0.0065,
        "source_note": "Session edit",
    }


def _blank_personnel_row(index: int) -> dict[str, object]:
    return {
        "labor_type": "Direct",
        "role": f"New role {index}",
        "headcount": 1.0,
        "monthly_salary_usd": 0.0,
        "monthly_total_usd": 0.0,
        "source_note": "Session edit",
    }


def _apply_global_styles() -> None:
    st.markdown(
        """
<style>
a[href^="#"],
[data-testid="stHeaderActionElements"] {
  display: none !important;
  visibility: hidden !important;
}
.setup-card-title {
  font-weight: 700;
  font-size: 0.96rem;
  margin-bottom: 0.35rem;
}
.setup-control-label {
  font-size: 0.78rem;
  font-weight: 650;
  margin: 0.28rem 0 0.04rem 0;
  opacity: 0.82;
}
.setup-subnote {
  display: flex;
  flex-wrap: wrap;
  gap: 0.18rem 0.35rem;
  font-size: 0.80rem;
  line-height: 1.35;
  margin: 0.02rem 0 0.42rem 0;
  opacity: 0.82;
}
.setup-subnote strong {
  color: inherit;
  font-weight: 750;
}
.setup-subnote-separator {
  opacity: 0.55;
}
div[data-testid="stNumberInput"] label,
div[data-testid="stSlider"] label,
div[data-testid="stSelectbox"] label,
div[data-testid="stRadio"] label {
  font-size: 0.78rem !important;
}
div[data-testid="stNumberInput"],
div[data-testid="stSlider"],
div[data-testid="stSelectbox"],
div[data-testid="stRadio"] {
  margin-bottom: 0.12rem;
}
.st-key-deal_setup_section,
.st-key-deal_diagnostics_section,
.st-key-provider_report_section,
.st-key-customer_report_section,
.st-key-negotiation_lab_section,
.st-key-machine_reference_section,
.st-key-personnel_reference_section,
div[data-testid="stVerticalBlockBorderWrapper"] {
  background: rgba(100, 116, 139, 0.055);
  border: 1px solid rgba(100, 116, 139, 0.22);
  border-radius: 8px;
  padding: 0.8rem 0.9rem;
}
.chart-status {
  box-sizing: border-box;
  height: 4.35rem;
  border-radius: 6px;
  padding: 0.58rem 0.7rem;
  margin: 0.15rem 0 0.35rem 0;
  display: flex;
  align-items: center;
  overflow: hidden;
  font-size: 0.82rem;
  font-weight: 700;
  line-height: 1.25;
  white-space: pre-line;
}
.chart-status.success {
  color: inherit;
  background: rgba(42, 157, 143, 0.18);
  border: 1px solid rgba(42, 157, 143, 0.38);
}
.chart-status.warning {
  color: inherit;
  background: rgba(217, 164, 65, 0.20);
  border: 1px solid rgba(217, 164, 65, 0.42);
}
.chart-status.danger {
  color: inherit;
  background: rgba(209, 73, 91, 0.18);
  border: 1px solid rgba(209, 73, 91, 0.38);
}
.chart-status.neutral {
  color: inherit;
  background: rgba(100, 116, 139, 0.14);
  border: 1px solid rgba(100, 116, 139, 0.28);
}
@media print {
  button,
  [data-testid="stToolbar"],
  [data-testid="stDecoration"] {
    display: none !important;
  }
}
</style>
""",
        unsafe_allow_html=True,
    )


def main() -> None:
    data = normalize_dashboard_data(_load_data())
    scenarios = data["scenarios"]
    machine_specs = _session_machine_master(data["machine_specs"])
    personnel_defaults = _session_personnel_master(data["personnel_defaults"])
    view_presets = data["view_assumptions"]

    _apply_global_styles()
    st.title("Deal Calculator")

    labor_totals = _personnel_labor_totals(personnel_defaults)
    inputs, view_assumptions, deal_structure, machine = _sidebar_inputs(
        scenarios,
        view_presets,
        machine_specs,
        labor_totals,
    )
    result = calculate_dashboard_result(inputs, machine, view_assumptions)

    deal_summary = result["deal_summary"]
    provider_report = result["provider_report"]
    customer_report = result["customer_report"]
    provider_investment_metrics = result["provider_investment_metrics"]
    customer_investment_metrics = result["customer_investment_metrics"]
    sensitivity = result["sensitivity"]
    monthly_value_split = result["monthly_value_split"]
    investment_timeline = result["investment_recovery_timeline"]

    dashboard_tab, demand_tab, machine_tab, personnel_tab = st.tabs(["Dashboard", "Demand Forecast", "Machine", "Personnel"])

    with dashboard_tab:
        with st.container(border=True, key="deal_setup_section"):
            _render_deal_setup_summary(
                deal_summary,
                inputs,
                view_assumptions,
                deal_structure,
                result["unit"],
            )
        with st.container(border=True, key="deal_diagnostics_section"):
            _render_deal_diagnostics(
                investment_timeline,
                monthly_value_split,
                deal_summary,
            )

        provider_col, customer_col = st.columns(2)
        with provider_col:
            with st.container(border=True, key="provider_report_section"):
                _render_stakeholder_section(
                    "Provider",
                    provider_report,
                    provider_investment_metrics,
                )
        with customer_col:
            with st.container(border=True, key="customer_report_section"):
                _render_stakeholder_section(
                    "Customer",
                    customer_report,
                    customer_investment_metrics,
                )
        with st.container(border=True, key="negotiation_lab_section"):
            _render_negotiation_lab(inputs, view_assumptions, machine, result)

    with machine_tab:
        _render_machine_tab(machine_specs)

    with personnel_tab:
        _render_personnel_tab(personnel_defaults)



def _render_demand_forecast_tab() -> None:
    with st.container(border=True, key="demand_forecast_section"):
        st.subheader("Demand Forecast")
        control_col, chart_col = st.columns([0.30, 0.70], gap="large")
        with control_col:
            st.markdown("**Synthetic History Setup**")
            customer_type = st.selectbox(
                "Customer type",
                list(CUSTOMER_PROFILES),
                index=0,
                key="forecast_customer_type",
            )
            profile = CUSTOMER_PROFILES[customer_type]
            baseline = st.number_input(
                "Baseline waste, tons/day",
                min_value=1.0,
                max_value=250.0,
                value=float(profile.baseline_tons_per_day),
                step=1.0,
                key=f"forecast_baseline_{customer_type}",
            )
            history_days = st.slider(
                "History length, days",
                min_value=180,
                max_value=1095,
                value=730,
                step=30,
                key="forecast_history_days",
            )
            horizon_days = st.slider(
                "Forecast horizon, days",
                min_value=30,
                max_value=180,
                value=90,
                step=15,
                key="forecast_horizon_days",
            )
            weekly_strength = st.slider(
                "Weekly seasonality",
                min_value=0.0,
                max_value=1.5,
                value=1.0,
                step=0.05,
                key="forecast_weekly_strength",
            )
            annual_strength = st.slider(
                "Annual seasonality",
                min_value=0.0,
                max_value=0.4,
                value=float(profile.annual_seasonality_strength),
                step=0.01,
                key=f"forecast_annual_strength_{customer_type}",
            )
            trend_percent = st.slider(
                "Monthly trend",
                min_value=-2.0,
                max_value=3.0,
                value=float(profile.monthly_growth_rate * 100),
                step=0.1,
                key=f"forecast_monthly_trend_{customer_type}",
            )
            noise_percent = st.slider(
                "Noise level",
                min_value=1.0,
                max_value=30.0,
                value=float(profile.noise_ratio * 100),
                step=0.5,
                key=f"forecast_noise_{customer_type}",
            )
            event_rate_percent = st.slider(
                "Abnormal event rate",
                min_value=0.0,
                max_value=10.0,
                value=float(profile.event_rate * 100),
                step=0.25,
                key=f"forecast_event_rate_{customer_type}",
            )
            random_seed = st.number_input(
                "Simulation seed",
                min_value=1,
                max_value=9999,
                value=42,
                step=1,
                key="forecast_random_seed",
            )

        history = simulate_daily_waste(
            customer_type=customer_type,
            history_days=int(history_days),
            baseline_tons_per_day=float(baseline),
            weekly_strength=float(weekly_strength),
            annual_strength=float(annual_strength),
            monthly_growth_rate=float(trend_percent) / 100,
            noise_ratio=float(noise_percent) / 100,
            event_rate=float(event_rate_percent) / 100,
            random_seed=int(random_seed),
        )
        forecast_result = forecast_daily_waste(history, horizon_days=int(horizon_days))

        with chart_col:
            st.markdown("**Historical Waste + Forecast**")
            _render_demand_forecast_chart(history, forecast_result.forecast)

        _render_demand_forecast_summary(forecast_result.summary)
        _render_demand_decomposition(forecast_result)


def _render_demand_forecast_chart(history: pd.DataFrame, forecast: pd.DataFrame) -> None:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=forecast["date"],
            y=forecast["lower_95"],
            mode="lines",
            line={"width": 0},
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=forecast["date"],
            y=forecast["upper_95"],
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(37, 109, 123, 0.14)",
            line={"width": 0},
            name="95% interval",
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=forecast["date"],
            y=forecast["lower_80"],
            mode="lines",
            line={"width": 0},
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=forecast["date"],
            y=forecast["upper_80"],
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(42, 157, 143, 0.18)",
            line={"width": 0},
            name="80% interval",
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=history["date"],
            y=history["waste_tons"],
            mode="lines",
            name="Historical waste",
            line={"color": "rgba(148, 163, 184, 0.75)", "width": 1.8},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=forecast["date"],
            y=forecast["forecast_mean"],
            mode="lines",
            name="Forecast mean",
            line={"color": "#D1495B", "width": 3},
        )
    )
    fig.add_vline(
        x=history["date"].max(),
        line_width=1,
        line_dash="dot",
        line_color="rgba(148, 163, 184, 0.55)",
    )
    fig.update_layout(
        height=520,
        margin={"l": 45, "r": 24, "t": 10, "b": 78},
        yaxis_title="Tons/day",
        xaxis_title="Date",
        legend={"orientation": "h", "y": -0.24, "x": 0.5, "xanchor": "center"},
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_demand_forecast_summary(summary: dict[str, float]) -> None:
    cols = st.columns(5)
    metrics = [
        ("History avg", summary["history_avg_waste_tons"]),
        ("Forecast avg", summary["forecast_avg_waste_tons"]),
        ("Forecast peak", summary["forecast_peak_waste_tons"]),
        ("Planning P80", summary["planning_p80_waste_tons"]),
        ("Planning P95", summary["planning_p95_waste_tons"]),
    ]
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, _format_tons(value))


def _render_demand_decomposition(result: DemandForecastResult) -> None:
    st.markdown("**Forecast Decomposition**")
    trend_col, seasonality_col, residual_col = st.columns([0.36, 0.34, 0.30], gap="large")
    with trend_col:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=result.fitted_history["date"],
                y=result.fitted_history["trend"],
                mode="lines",
                name="Trend",
                line={"color": "#256D7B", "width": 2.5},
            )
        )
        fig.update_layout(
            height=280,
            margin={"l": 38, "r": 14, "t": 8, "b": 42},
            yaxis_title="Tons/day",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    with seasonality_col:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=result.weekly_pattern["day_name"],
                y=result.weekly_pattern["seasonal_effect"],
                name="Weekly",
                marker_color="#5DA399",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=result.monthly_pattern["month_name"],
                y=result.monthly_pattern["seasonal_effect"],
                mode="lines+markers",
                name="Monthly",
                line={"color": "#D1495B", "width": 2},
                yaxis="y2",
            )
        )
        fig.update_layout(
            height=280,
            margin={"l": 38, "r": 38, "t": 8, "b": 42},
            yaxis={"title": "Weekly"},
            yaxis2={"title": "Monthly", "overlaying": "y", "side": "right"},
            legend={"orientation": "h", "y": -0.24, "x": 0.5, "xanchor": "center"},
        )
        st.plotly_chart(fig, use_container_width=True)

    with residual_col:
        fig = go.Figure()
        fig.add_trace(
            go.Histogram(
                x=result.fitted_history["residual"],
                nbinsx=28,
                name="Residual",
                marker_color="#B87445",
            )
        )
        fig.update_layout(
            height=280,
            margin={"l": 38, "r": 14, "t": 8, "b": 42},
            xaxis_title="Forecast error, tons/day",
            yaxis_title="Days",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)


def _format_tons(value: float) -> str:
    return f"{float(value):,.1f} tons/day"
def _sidebar_inputs(
    scenarios: pd.DataFrame,
    view_presets: pd.DataFrame,
    machine_specs: pd.DataFrame,
    labor_totals: dict[str, float],
):
    scenario_row = scenarios.loc[scenarios["scenario"].eq(DEFAULT_CUSTOMER_CASE)].iloc[0]
    selected_model = None
    machine_fleet = None

    with st.sidebar:
        st.header("Deal Inputs")
        deal_structure = st.selectbox("Deal Structure", list(DEAL_STRUCTURES), index=1)
        selected_structure = DEAL_STRUCTURES[deal_structure]
        view_matches = view_presets.loc[
            view_presets["scenario"].eq(selected_structure["view_preset"])
        ]
        if view_matches.empty:
            st.error(
                "Deal setup data is out of sync. Please refresh the app; "
                f"missing view preset: {selected_structure['view_preset']}"
            )
            st.stop()
        view_row = view_matches.iloc[0]

        business_model = selected_structure["business_model"]
        base_inputs = inputs_from_scenario(scenario_row, business_model=business_model)
        base_view = view_assumptions_from_row(view_row)
        default_investment_share = selected_structure["customer_investment_share"]

        with st.expander("Equipment Terms", expanded=True):
            if default_investment_share is None:
                customer_investment_share = _percent_control(
                    "Customer equipment cost share",
                    0.5,
                    "customer_equipment_cost_share",
                    step_percent=5.0,
                )
            else:
                customer_investment_share = float(default_investment_share)
            if st.session_state.get("machine_sizing") == "Auto":
                st.session_state["machine_sizing"] = "Auto size by capacity"
            if st.session_state.get("machine_sizing") == "Manual":
                st.session_state["machine_sizing"] = "Manual fleet setup"
            mode = st.radio(
                "Machine sizing",
                ["Auto size by capacity", "Manual fleet setup"],
                horizontal=True,
                key="machine_sizing",
            )
            machine_quantity_override = None
            if mode == "Manual fleet setup":
                fleet_rows = int(
                    st.number_input(
                        "Fleet rows",
                        min_value=1,
                        max_value=5,
                        value=2,
                        step=1,
                        key="fleet_rows",
                    )
                )
                machine_fleet = _fleet_inputs(machine_specs, fleet_rows)
            machine_discount = _percent_control(
                "Machine discount",
                base_inputs.machine_discount_rate,
                "machine_discount",
                max_percent=80.0,
            )
            grant_rate = _percent_control(
                "Grant rate",
                base_inputs.grant_rate,
                "grant_rate",
                max_percent=80.0,
            )
            rental_discount = _percent_control(
                "Rental discount",
                base_inputs.rental_discount_rate,
                "rental_discount",
                max_percent=80.0,
            )

        with st.expander("Customer Operating Profile", expanded=True):
            waste_tons_per_day = st.number_input(
                "Waste volume, tons/day",
                min_value=0.1,
                value=float(base_inputs.waste_tons_per_day),
                step=1.0,
                key="waste_tons_per_day",
            )
            collection_rate = _percent_control(
                "Collection rate",
                base_inputs.collection_rate,
                "collection_rate",
            )
            days_per_month = st.number_input(
                "Operating days/month",
                min_value=1,
                max_value=31,
                value=int(base_inputs.days_per_month),
                step=1,
                key="days_per_month",
            )
            disposal_fee = st.number_input(
                "Current disposal fee, USD/ton",
                min_value=0.0,
                value=float(base_view.current_disposal_fee_usd_per_ton),
                step=5.0,
                key="disposal_fee",
            )

        with st.expander("Output Assumptions", expanded=True):
            conversion_rate = _percent_control(
                "Fertilizer conversion rate",
                base_inputs.conversion_rate,
                "conversion_rate",
            )
            sales_completion = _percent_control(
                "Fertilizer sales completion",
                base_inputs.fertilizer_sales_completion_rate,
                "sales_completion",
            )

        with st.expander("Revenue Terms", expanded=True):
            fertilizer_price = st.number_input(
                "Fertilizer $/ton",
                min_value=0.0,
                value=float(base_inputs.fertilizer_price_usd_per_ton),
                step=10.0,
                key="fertilizer_price",
            )
            fertilizer_share = _percent_control(
                "Provider fertilizer revenue share",
                base_view.provider_fertilizer_revenue_share,
                "fertilizer_share",
                step_percent=5.0,
            )
            service_fee = st.number_input(
                "Provider service fee, USD/ton waste",
                min_value=0.0,
                value=float(base_inputs.service_fee_usd_per_ton),
                step=5.0,
                key="service_fee",
            )
            service_share = 1.0
            rental_share = 1.0

        with st.expander("Operating Cost Assumptions", expanded=False):
            electricity_rate = st.number_input(
                "Electricity rate, USD/kWh",
                min_value=0.0,
                value=float(base_inputs.electricity_rate_usd_per_kwh),
                step=0.01,
                format="%.4f",
                key="electricity_rate",
            )
            electricity_load_factor = _percent_control(
                "Average power usage",
                base_inputs.electricity_load_factor,
                "electricity_load_factor",
            )
            enzyme_cost = st.number_input(
                "Enzyme cost, USD/ton waste",
                min_value=0.0,
                value=float(base_inputs.enzyme_cost_usd_per_ton_waste),
                step=1.0,
                key="enzyme_cost",
            )
            direct_labor = float(labor_totals["direct"])
            indirect_labor = float(labor_totals["indirect"])
            st.markdown(
                "<div class='setup-control-label'>Labor from Personnel</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                (
                    "<div class='setup-subnote'>"
                    f"<span>Direct <strong>{_money(direct_labor)}/mo.</strong></span>"
                    "<span class='setup-subnote-separator'>|</span>"
                    f"<span>Indirect <strong>{_money(indirect_labor)}/mo.</strong></span>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            other_cost = st.number_input(
                "Other operating cost, USD/month",
                min_value=0.0,
                value=float(base_inputs.other_cost_usd_per_month),
                step=500.0,
                key="other_cost",
            )
            maintenance_rate = _percent_control(
                "Annual maintenance rate",
                base_inputs.maintenance_rate_annual,
                "maintenance_rate",
                max_percent=20.0,
                step_percent=0.5,
            )
            cogs_share = base_view.provider_cogs_share
            opex_share = base_view.provider_non_rental_opex_share

        with st.expander("Finance / Tax", expanded=False):
            tax_rate = _percent_control(
                "Tax rate",
                base_inputs.tax_rate,
                "tax_rate",
                max_percent=50.0,
            )
            loan_interest = st.number_input(
                "Loan interest expense, USD/month",
                min_value=0.0,
                value=float(base_inputs.loan_interest_expense_usd_per_month),
                step=500.0,
                key="loan_interest",
            )
            non_op_share = base_view.provider_non_operating_expense_share

    inputs = replace(
        base_inputs,
        business_model=business_model,
        waste_tons_per_day=waste_tons_per_day,
        collection_rate=collection_rate,
        days_per_month=days_per_month,
        conversion_rate=conversion_rate,
        fertilizer_price_usd_per_ton=fertilizer_price,
        fertilizer_sales_completion_rate=sales_completion,
        service_fee_usd_per_ton=service_fee,
        electricity_rate_usd_per_kwh=electricity_rate,
        electricity_load_factor=electricity_load_factor,
        enzyme_cost_usd_per_ton_waste=enzyme_cost,
        direct_labor_cost_usd_per_month=direct_labor,
        indirect_labor_cost_usd_per_month=indirect_labor,
        other_cost_usd_per_month=other_cost,
        maintenance_rate_annual=maintenance_rate,
        machine_discount_rate=machine_discount,
        grant_rate=grant_rate,
        rental_discount_rate=rental_discount,
        loan_interest_expense_usd_per_month=loan_interest,
        tax_rate=tax_rate,
        machine_quantity_override=machine_quantity_override,
        machine_fleet=machine_fleet,
    )
    view_assumptions = ViewAssumptions(
        current_disposal_fee_usd_per_ton=disposal_fee,
        provider_fertilizer_revenue_share=fertilizer_share,
        provider_service_fee_share=service_share,
        provider_rental_revenue_share=rental_share,
        provider_cogs_share=cogs_share,
        provider_non_rental_opex_share=opex_share,
        provider_non_operating_expense_share=non_op_share,
        customer_initial_investment_share=customer_investment_share,
    )
    machine = select_machine(machine_specs, inputs, selected_model)
    return inputs, view_assumptions, deal_structure, machine


def _setup_block_title(title: str) -> None:
    st.markdown(
        f"<div class='setup-card-title'>{escape(title)}</div>",
        unsafe_allow_html=True,
    )


def _render_deal_setup_summary(
    deal_summary: dict[str, object],
    inputs: FeasibilityInputs,
    view_assumptions: ViewAssumptions,
    deal_structure: str,
    unit: dict[str, object],
) -> None:
    st.subheader("Deal Setup")
    monthly_labor = (
        float(inputs.direct_labor_cost_usd_per_month or inputs.labor_cost_usd_per_month)
        + float(inputs.indirect_labor_cost_usd_per_month)
    )
    provider_equipment_share = 1 - view_assumptions.customer_initial_investment_share
    sections = {
        "Deal": [
            ("Structure", _deal_structure_summary_label(deal_structure)),
            ("Cost owner", str(deal_summary["machine_cost_owner"])),
            ("Machine", _compact_setup_label(str(deal_summary["machine_setup"]))),
            ("Equip. cost", _money(deal_summary["equipment_cost_to_recover"])),
        ],
        "Waste": [
            ("Waste/day", f"{inputs.waste_tons_per_day:,.1f} tons"),
            ("Monthly waste", f"{float(deal_summary['monthly_waste_tons']):,.0f} tons"),
            ("Collection", _percent(inputs.collection_rate)),
            ("Disposal fee", f"{_money(view_assumptions.current_disposal_fee_usd_per_ton)}/ton"),
        ],
        "Output": [
            ("Fertilizer/mo.", f"{float(deal_summary['monthly_fertilizer_tons']):,.0f} tons"),
            ("Conversion", _percent(inputs.conversion_rate)),
            ("Sales", _percent(inputs.fertilizer_sales_completion_rate)),
            ("Power use", _percent(inputs.electricity_load_factor)),
        ],
        "Commercial": [
            ("Fert. price", f"{_money(inputs.fertilizer_price_usd_per_ton)}/ton"),
            ("Provider service", f"{_money(inputs.service_fee_usd_per_ton)}/ton"),
            ("Rental/mo.", _money(unit["rental_cost"])),
            ("Rental disc.", _percent(inputs.rental_discount_rate)),
        ],
        "Cost": [
            ("Power", f"${inputs.electricity_rate_usd_per_kwh:,.4f}/kWh"),
            ("Enzyme", f"{_money(inputs.enzyme_cost_usd_per_ton_waste)}/ton"),
            ("Labor/mo.", _money(monthly_labor)),
            ("Maint./yr", _percent(inputs.maintenance_rate_annual)),
        ],
        "Sharing": [
            ("Provider fertilizer", _percent(view_assumptions.provider_fertilizer_revenue_share)),
            ("Provider equipment", _percent(provider_equipment_share)),
            ("Customer equip.", _percent(view_assumptions.customer_initial_investment_share)),
            ("Machine disc.", _percent(inputs.machine_discount_rate)),
        ],
    }
    st.markdown(_summary_cards_html(sections), unsafe_allow_html=True)


def _render_machine_tab(machine_specs: pd.DataFrame) -> None:
    with st.container(border=True, key="machine_reference_section"):
        st.markdown(_master_data_styles(), unsafe_allow_html=True)
        st.subheader("Machine")

        column_widths = [1.45, 0.82, 0.95, 0.72, 0.72, 0.72, 0.95, 1.02, 0.68]
        headers = [
            "Model",
            "Capacity",
            "Price",
            "Rental",
            "Power",
            "Heater",
            "Hours",
            "Calculated",
            "",
        ]
        header_cols = st.columns(column_widths)
        for header, column in zip(headers, header_cols):
            with column:
                st.markdown(f"<div class='master-header-label'>{escape(header)}</div>", unsafe_allow_html=True)

        updated_rows: list[dict[str, object]] = []
        for index, row in machine_specs.reset_index(drop=True).iterrows():
            row_cols = st.columns(column_widths)
            current_model = str(row["model"])
            with row_cols[0]:
                model = st.text_input(
                    "Machine model",
                    value=current_model,
                    key=f"machine_model_{index}",
                    label_visibility="collapsed",
                )
            with row_cols[1]:
                capacity_ton = st.number_input(
                    "Capacity tons/day",
                    min_value=0.01,
                    value=float(row["capacity_ton"]),
                    step=0.10,
                    key=f"machine_capacity_{index}",
                    label_visibility="collapsed",
                )
            with row_cols[2]:
                price = st.number_input(
                    "Asia price no CE",
                    min_value=0.0,
                    value=float(row["asia_price_no_ce_usd"]),
                    step=1000.0,
                    key=f"machine_price_{index}",
                    label_visibility="collapsed",
                )
            with row_cols[3]:
                rental_ratio = st.number_input(
                    "Monthly rental ratio",
                    min_value=0.0,
                    max_value=0.10,
                    value=float(row["monthly_rental_ratio"]),
                    step=0.0001,
                    format="%.4f",
                    key=f"machine_rental_ratio_{index}",
                    label_visibility="collapsed",
                )
            with row_cols[4]:
                power = st.number_input(
                    "Power kW",
                    min_value=0.0,
                    value=float(row["power_kw"]),
                    step=1.0,
                    key=f"machine_power_{index}",
                    label_visibility="collapsed",
                )
            with row_cols[5]:
                heater = st.number_input(
                    "Heater kW",
                    min_value=0.0,
                    value=float(row["heater_kw"]),
                    step=1.0,
                    key=f"machine_heater_{index}",
                    label_visibility="collapsed",
                )
            with row_cols[6]:
                hours = st.number_input(
                    "Operation hours per day",
                    min_value=0.0,
                    max_value=24.0,
                    value=float(row["operation_hours_per_day"]),
                    step=1.0,
                    key=f"machine_hours_{index}",
                    label_visibility="collapsed",
                )
            total_load = float(power) + float(heater)
            default_rental = float(price) * float(rental_ratio)
            with row_cols[7]:
                st.markdown(
                    (
                        "<div class='master-calculated'>"
                        f"<span>{total_load:,.1f} kW</span>"
                        f"<small>{_money(default_rental)}/mo.</small>"
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )
            with row_cols[8]:
                if st.button(
                    "Remove",
                    key=f"remove_machine_{index}",
                    disabled=len(machine_specs) <= 1,
                    use_container_width=True,
                ):
                    updated = machine_specs.drop(machine_specs.index[index]).reset_index(drop=True)
                    st.session_state["machine_master_data"] = updated
                    st.rerun()

            updated_rows.append(
                {
                    "model": model,
                    "capacity_kg": float(capacity_ton) * 1000,
                    "capacity_ton": float(capacity_ton),
                    "power_kw": float(power),
                    "heater_kw": float(heater),
                    "total_load_kw": total_load,
                    "operation_hours_per_day": float(hours),
                    "asia_price_no_ce_usd": float(price),
                    "asia_price_with_ce_usd": float(row.get("asia_price_with_ce_usd", 0.0)),
                    "europe_price_with_ce_usd": float(row.get("europe_price_with_ce_usd", 0.0)),
                    "monthly_rental_ratio": float(rental_ratio),
                    "source_note": str(row.get("source_note", "Session edit")),
                }
            )
            st.markdown("<div class='master-row-divider'></div>", unsafe_allow_html=True)

        add_cols = st.columns(column_widths)
        with add_cols[8]:
            _render_add_machine_button(machine_specs)

        sanitized = _sanitize_machine_master(pd.DataFrame(updated_rows), fallback=machine_specs)
        if not sanitized.equals(machine_specs.reset_index(drop=True)):
            st.session_state["machine_master_data"] = sanitized
            st.rerun()


def _render_add_machine_button(machine_specs: pd.DataFrame) -> None:
    if st.button("Add Machine", key="add_machine_row", use_container_width=True):
        new_row = _blank_machine_row(len(machine_specs) + 1)
        st.session_state["machine_master_data"] = pd.concat(
            [machine_specs, pd.DataFrame([new_row])],
            ignore_index=True,
        )
        st.rerun()


def _render_personnel_tab(personnel_defaults: pd.DataFrame) -> None:
    with st.container(border=True, key="personnel_reference_section"):
        st.subheader("Personnel")
        st.markdown(_master_data_styles(), unsafe_allow_html=True)

        direct_rows, direct_total = _render_personnel_section(
            personnel_defaults,
            labor_type="Direct",
            title="Direct Labor",
        )
        indirect_rows, indirect_total = _render_personnel_section(
            personnel_defaults,
            labor_type="Indirect",
            title="Indirect Labor",
        )

        total_labor_cost = direct_total + indirect_total
        summary_cols = st.columns([2.35, 0.95, 1.1, 1.15, 0.72])
        with summary_cols[2]:
            st.markdown("<div class='personnel-grand-total-label'>Total monthly labor cost</div>", unsafe_allow_html=True)
        with summary_cols[3]:
            st.markdown(
                f"<div class='personnel-grand-total'>{_money(total_labor_cost)}</div>",
                unsafe_allow_html=True,
            )

        updated_rows = direct_rows + indirect_rows
        sanitized = _sanitize_personnel_master(pd.DataFrame(updated_rows), fallback=personnel_defaults)
        if not sanitized.equals(personnel_defaults.reset_index(drop=True)):
            st.session_state["personnel_master_data"] = sanitized
            st.rerun()


def _render_personnel_section(
    personnel_defaults: pd.DataFrame,
    labor_type: str,
    title: str,
) -> tuple[list[dict[str, object]], float]:
    section = personnel_defaults.loc[personnel_defaults["labor_type"].eq(labor_type)].reset_index()
    section_key = labor_type.lower()
    st.markdown("<div class='personnel-section-rule'></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='personnel-section-title'>{escape(title)}</div>", unsafe_allow_html=True)
    action_cols = st.columns([0.84, 0.16])
    with action_cols[1]:
        _render_add_personnel_role_button(personnel_defaults, labor_type, section_key)

    if section.empty:
        st.markdown("<div class='personnel-empty-note'>No role added yet.</div>", unsafe_allow_html=True)
        return [], 0.0

    column_widths = [2.35, 0.95, 1.1, 1.15, 0.72]
    headers = ["Role", "Headcount", "Salary/mo.", "Monthly cost", ""]
    header_cols = st.columns(column_widths)
    for header, column in zip(headers, header_cols):
        with column:
            st.markdown(f"<div class='master-header-label'>{escape(header)}</div>", unsafe_allow_html=True)

    updated_rows: list[dict[str, object]] = []
    section_total = 0.0
    for local_index, row in section.iterrows():
        original_index = int(row["index"])
        row_cols = st.columns(column_widths)
        with row_cols[0]:
            role = st.text_input(
                "Role",
                value=str(row["role"]),
                key=f"personnel_{section_key}_role_{original_index}",
                label_visibility="collapsed",
            )
        with row_cols[1]:
            headcount = st.number_input(
                "Headcount",
                min_value=0.0,
                value=float(row["headcount"]),
                step=1.0,
                key=f"personnel_{section_key}_headcount_{original_index}",
                label_visibility="collapsed",
            )
        with row_cols[2]:
            salary = st.number_input(
                "Monthly salary",
                min_value=0.0,
                value=float(row["monthly_salary_usd"]),
                step=100.0,
                key=f"personnel_{section_key}_salary_{original_index}",
                label_visibility="collapsed",
            )
        monthly_total = float(headcount) * float(salary)
        section_total += monthly_total
        with row_cols[3]:
            st.markdown(
                f"<div class='master-calculated single'>{_money(monthly_total)}</div>",
                unsafe_allow_html=True,
            )
        with row_cols[4]:
            if st.button(
                "Remove",
                key=f"remove_personnel_{section_key}_{original_index}",
                disabled=len(personnel_defaults) <= 1,
                use_container_width=True,
            ):
                updated = personnel_defaults.drop(personnel_defaults.index[original_index]).reset_index(drop=True)
                st.session_state["personnel_master_data"] = updated
                st.rerun()

        updated_rows.append(
            {
                "labor_type": labor_type,
                "role": role,
                "headcount": float(headcount),
                "monthly_salary_usd": float(salary),
                "monthly_total_usd": monthly_total,
                "source_note": str(row.get("source_note", "Session edit")),
            }
        )
        st.markdown("<div class='master-row-divider'></div>", unsafe_allow_html=True)

    total_cols = st.columns(column_widths)
    with total_cols[2]:
        st.markdown(
            f"<div class='personnel-section-total-label'>{escape(title)} total monthly cost</div>",
            unsafe_allow_html=True,
        )
    with total_cols[3]:
        st.markdown(
            f"<div class='personnel-section-total'>{_money(section_total)}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("<div class='personnel-section-spacer'></div>", unsafe_allow_html=True)
    return updated_rows, section_total


def _render_add_personnel_role_button(
    personnel_defaults: pd.DataFrame,
    labor_type: str,
    section_key: str,
) -> None:
    if st.button("Add Role", key=f"add_personnel_{section_key}_row", use_container_width=True):
        new_row = _blank_personnel_row(len(personnel_defaults) + 1)
        new_row["labor_type"] = labor_type
        st.session_state["personnel_master_data"] = pd.concat(
            [personnel_defaults, pd.DataFrame([new_row])],
            ignore_index=True,
        )
        st.rerun()


def _master_data_styles() -> str:
    return """
<style>
.master-header-label {
  color: inherit;
  font-size: 0.80rem;
  font-weight: 700;
  padding: 0.2rem 0 0.35rem 0;
  text-align: center;
}
.master-calculated {
  align-items: center;
  display: flex;
  flex-direction: column;
  font-size: 0.80rem;
  font-weight: 700;
  justify-content: center;
  min-height: 2.35rem;
  text-align: center;
  white-space: nowrap;
}
.master-calculated small {
  color: #D1495B;
  font-size: 0.76rem;
  font-weight: 700;
  margin-top: 0.05rem;
}
.master-calculated.single {
  color: #D1495B;
}
.master-row-divider {
  height: 1px;
  margin: 0.05rem 0 0.4rem 0;
  background: rgba(100, 116, 139, 0.18);
}
.personnel-section-rule {
  border-top: 1px solid rgba(100, 116, 139, 0.22);
  margin: 0.9rem 0 0.25rem 0;
}
.personnel-section-title {
  font-size: 1.0rem;
  font-weight: 800;
  margin: 0;
  min-height: 1.65rem;
  padding-top: 0.42rem;
}
.personnel-empty-note {
  border: 1px dashed rgba(100, 116, 139, 0.34);
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 650;
  margin: 0.35rem 0 0.7rem 0;
  opacity: 0.76;
  padding: 0.75rem;
  text-align: center;
}
.personnel-section-total-label,
.personnel-section-total,
.personnel-grand-total-label,
.personnel-grand-total {
  font-size: 0.86rem;
  font-weight: 800;
}
.personnel-section-total-label,
.personnel-grand-total-label {
  text-align: center;
}
.personnel-section-total,
.personnel-grand-total {
  color: #D1495B;
  text-align: center;
}
.personnel-section-spacer {
  height: 0.85rem;
}
.personnel-grand-total-label,
.personnel-grand-total {
  border-top: 1px solid rgba(100, 116, 139, 0.24);
  margin-top: 0.15rem;
  margin-bottom: 0.95rem;
  min-height: 2.35rem;
  padding-top: 0.68rem;
}
.st-key-personnel_reference_section {
  padding-bottom: 1.15rem !important;
}
.st-key-machine_reference_section div[data-testid="stNumberInput"],
.st-key-machine_reference_section div[data-testid="stTextInput"],
.st-key-personnel_reference_section div[data-testid="stNumberInput"],
.st-key-personnel_reference_section div[data-testid="stTextInput"],
.st-key-personnel_reference_section div[data-testid="stSelectbox"] {
  margin-bottom: 0;
}
.st-key-machine_reference_section div[data-testid="stNumberInput"] input,
.st-key-personnel_reference_section div[data-testid="stNumberInput"] input {
  text-align: right;
}
.st-key-machine_reference_section div[data-testid="stNumberInput"] button,
.st-key-personnel_reference_section div[data-testid="stNumberInput"] button {
  display: none !important;
}
.st-key-machine_reference_section button,
.st-key-personnel_reference_section button {
  min-height: 2.35rem;
}
</style>
"""


def _selected_fleet(inputs: FeasibilityInputs, machine: MachineSpec) -> tuple[MachineFleetItem, ...]:
    if inputs.machine_fleet is not None:
        return tuple(item for item in inputs.machine_fleet if item.quantity > 0)
    count = (
        max(1, int(inputs.machine_quantity_override))
        if inputs.machine_quantity_override is not None
        else machine_count(inputs.waste_tons_per_day, machine)
    )
    return (
        MachineFleetItem(
            model=machine.model,
            quantity=count,
            capacity_ton=machine.capacity_ton,
            total_load_kw=machine.total_load_kw,
            operation_hours_per_day=machine.operation_hours_per_day,
            asia_price_no_ce_usd=machine.asia_price_no_ce_usd,
            monthly_rental_ratio=machine.monthly_rental_ratio,
        ),
    )


def _selected_fleet_rows(
    fleet: tuple[MachineFleetItem, ...],
    inputs: FeasibilityInputs,
) -> list[dict[str, str]]:
    rows = []
    for item in fleet:
        rental_before_discount = item.monthly_rental_no_ce_usd * item.quantity
        electricity_month = (
            item.quantity
            * item.total_load_kw
            * item.operation_hours_per_day
            * inputs.days_per_month
            * inputs.electricity_rate_usd_per_kwh
            * inputs.electricity_load_factor
        )
        rows.append(
            {
                "Machine": item.model,
                "Qty": f"{item.quantity:,}",
                "Capacity/day": f"{item.capacity_ton:,.1f} tons",
                "Total capacity/day": f"{item.capacity_ton * item.quantity:,.1f} tons",
                "Total load": f"{item.total_load_kw * item.quantity:,.1f} kW",
                "Unit price": _money(item.asia_price_no_ce_usd),
                "Rental ratio": _percent(item.monthly_rental_ratio),
                "Rental/mo. before discount": _money(rental_before_discount),
                "Electricity/mo.": _money(electricity_month),
            }
        )
    return rows


def _machine_master_rows(machine_specs: pd.DataFrame) -> list[dict[str, str]]:
    rows = []
    for _, row in machine_specs.iterrows():
        price = float(row["asia_price_no_ce_usd"])
        rental_ratio = float(row["monthly_rental_ratio"])
        rows.append(
            {
                "Machine": str(row["model"]),
                "Capacity/day": f"{float(row['capacity_ton']):,.1f} tons",
                "Power": f"{float(row['power_kw']):,.1f} kW",
                "Heater": f"{float(row['heater_kw']):,.1f} kW",
                "Total load": f"{float(row['total_load_kw']):,.1f} kW",
                "Hours/day": f"{float(row['operation_hours_per_day']):,.0f}",
                "Asia price no CE": _money(price),
                "Asia price with CE": _optional_money(row.get("asia_price_with_ce_usd")),
                "Europe price": _optional_money(row.get("europe_price_with_ce_usd")),
                "Rental ratio": _percent(rental_ratio),
                "Default rental/mo.": _money(price * rental_ratio),
            }
        )
    return rows


def _personnel_rows(personnel_defaults: pd.DataFrame) -> list[dict[str, str]]:
    rows = []
    for _, row in personnel_defaults.iterrows():
        rows.append(
            {
                "Type": str(row["labor_type"]),
                "Role": str(row["role"]),
                "Headcount": f"{float(row['headcount']):,.0f}",
                "Monthly salary": _money(row["monthly_salary_usd"]),
                "Monthly cost": _money(row["monthly_total_usd"]),
            }
        )
    return rows


def _weighted_rental_ratio(fleet: tuple[MachineFleetItem, ...]) -> float:
    total_price = sum(item.asia_price_no_ce_usd * item.quantity for item in fleet)
    if total_price <= 0:
        return 0.0
    total_rental = sum(item.monthly_rental_no_ce_usd * item.quantity for item in fleet)
    return total_rental / total_price


def _optional_money(value: object) -> str:
    if pd.isna(value):
        return "N/A"
    return _money(value)


def _deal_structure_summary_label(deal_structure: str) -> str:
    if deal_structure.startswith("CapEx"):
        return "CapEx"
    if deal_structure.startswith("OpEx"):
        return "OpEx"
    if deal_structure.startswith("Co-investment"):
        return "Co-investment"
    return deal_structure


def _fleet_inputs(machine_specs: pd.DataFrame, fleet_rows: int) -> tuple[MachineFleetItem, ...]:
    fleet_items = []
    model_options = machine_specs["model"].tolist()
    for index in range(fleet_rows):
        st.markdown(
            f"<div class='setup-control-label'>Machine {index + 1}</div>",
            unsafe_allow_html=True,
        )
        model_col, qty_col = st.columns([0.65, 0.35], gap="small")
        with model_col:
            model = st.selectbox(
                f"Machine {index + 1} model",
                model_options,
                index=min(index, len(model_options) - 1),
                label_visibility="collapsed",
                key=f"fleet_model_{index}",
            )
        with qty_col:
            quantity = int(
                st.number_input(
                    f"Machine {index + 1} quantity",
                    min_value=0,
                    max_value=20,
                    value=1 if index == 0 else 0,
                    step=1,
                    label_visibility="collapsed",
                    key=f"fleet_qty_{index}",
                )
            )
        if quantity > 0:
            fleet_items.append(_fleet_item_from_model(machine_specs, model, quantity))

    if not fleet_items:
        fleet_items.append(_fleet_item_from_model(machine_specs, model_options[0], 1))
    _render_fleet_preview(fleet_items)
    return tuple(fleet_items)


def _fleet_item_from_model(
    machine_specs: pd.DataFrame,
    model: str,
    quantity: int,
) -> MachineFleetItem:
    row = machine_specs.loc[machine_specs["model"].eq(model)].iloc[0]
    return MachineFleetItem(
        model=str(row["model"]),
        quantity=quantity,
        capacity_ton=float(row["capacity_ton"]),
        total_load_kw=float(row["total_load_kw"]),
        operation_hours_per_day=float(row["operation_hours_per_day"]),
        asia_price_no_ce_usd=float(row["asia_price_no_ce_usd"]),
        monthly_rental_ratio=float(row["monthly_rental_ratio"]),
    )


def _render_fleet_preview(fleet_items: list[MachineFleetItem]) -> None:
    total_capacity = sum(item.capacity_ton * item.quantity for item in fleet_items)
    total_capex = sum(item.asia_price_no_ce_usd * item.quantity for item in fleet_items)
    total_rental = sum(item.monthly_rental_no_ce_usd * item.quantity for item in fleet_items)
    st.caption(
        "Fleet total: "
        f"{total_capacity:,.1f} tons/day | "
        f"{_usd_text(total_capex)} equipment | "
        f"{_usd_text(total_rental)}/mo. rental before discount"
    )


def _compact_setup_label(value: str) -> str:
    if len(value) <= 42:
        return value
    parts = value.split(" + ")
    if len(parts) <= 2:
        return value
    return f"{parts[0]} + {len(parts) - 1} more"


def _percent_control(
    label: str,
    default_fraction: float,
    key: str,
    max_percent: float = 100.0,
    step_percent: float = 1.0,
) -> float:
    value_key = f"{key}_pct_value"
    number_key = f"{key}_pct_number"
    slider_key = f"{key}_pct_slider"
    default_percent = _clamp_percent(float(default_fraction) * 100, max_percent)

    if value_key not in st.session_state:
        st.session_state[value_key] = default_percent

    current_percent = _clamp_percent(float(st.session_state[value_key]), max_percent)

    def sync_from_number() -> None:
        value = _clamp_percent(float(st.session_state[number_key]), max_percent)
        st.session_state[value_key] = value
        st.session_state[slider_key] = value

    def sync_from_slider() -> None:
        value = _clamp_percent(float(st.session_state[slider_key]), max_percent)
        st.session_state[value_key] = value
        st.session_state[number_key] = value

    st.markdown(
        f"<div class='setup-control-label'>{escape(label)} (%)</div>",
        unsafe_allow_html=True,
    )
    number_col, slider_col = st.columns([0.42, 0.58], gap="small")
    with number_col:
        st.number_input(
            f"{label} percentage input",
            min_value=0.0,
            max_value=float(max_percent),
            value=float(current_percent),
            step=float(step_percent),
            format="%.1f",
            label_visibility="collapsed",
            key=number_key,
            on_change=sync_from_number,
        )
    with slider_col:
        st.slider(
            f"{label} percentage bar",
            min_value=0.0,
            max_value=float(max_percent),
            value=float(current_percent),
            step=float(step_percent),
            label_visibility="collapsed",
            key=slider_key,
            on_change=sync_from_slider,
        )

    return float(st.session_state[value_key]) / 100


def _clamp_percent(value: float, max_percent: float) -> float:
    return min(max(value, 0.0), float(max_percent))


def _summary_cards_html(sections: dict[str, list[tuple[str, str]]]) -> str:
    cards = []
    for title, rows in sections.items():
        row_html = "\n".join(
            "<div class='summary-row'><span>{label}</span><strong>{value}</strong></div>".format(
                label=escape(label),
                value=escape(value),
            )
            for label, value in rows
        )
        cards.append(
            """
<section class="summary-card">
  <h4>{title}</h4>
  {rows}
</section>
""".format(
                title=escape(title),
                rows=row_html,
            )
        )
    return """
<style>
.summary-grid {{
  display: grid;
  grid-template-columns: repeat(6, minmax(145px, 1fr));
  gap: 0.6rem;
  margin: 0.5rem 0 1rem 0;
}}
.summary-card {{
  border: 1px solid rgba(100, 116, 139, 0.28);
  border-radius: 6px;
  padding: 0.72rem 0.75rem;
  min-height: 170px;
  background: rgba(100, 116, 139, 0.04);
}}
.summary-card h4 {{
  margin: 0 0 0.5rem 0;
  font-size: 0.95rem;
}}
.summary-row {{
  min-height: 29px;
  display: grid;
  grid-template-columns: 0.95fr 1.05fr;
  gap: 0.4rem;
  align-items: center;
  border-top: 1px solid rgba(100, 116, 139, 0.18);
  font-size: 0.82rem;
}}
.summary-row:first-of-type {{
  border-top: none;
}}
.summary-row span {{
  opacity: 0.72;
}}
.summary-row strong {{
  text-align: right;
  font-weight: 700;
}}
@media (max-width: 1280px) {{
  .summary-grid {{
    grid-template-columns: repeat(3, minmax(180px, 1fr));
  }}
}}
@media print {{
  .summary-grid {{
    grid-template-columns: repeat(6, minmax(130px, 1fr));
  }}
  .summary-card {{
    break-inside: avoid;
  }}
}}
</style>
<div class="summary-grid">
  {cards}
</div>
""".format(cards="\n".join(cards))


def _money(value: object) -> str:
    if value is None:
        return "N/A"
    amount = float(value)
    if abs(amount) < 0.5:
        return "$0"
    if amount < 0:
        return f"-${abs(amount):,.0f}"
    return f"${amount:,.0f}"


def _usd_text(value: object) -> str:
    if value is None:
        return "N/A"
    amount = float(value)
    if abs(amount) < 0.5:
        return "USD 0"
    if amount < 0:
        return f"-USD {abs(amount):,.0f}"
    return f"USD {amount:,.0f}"


def _percent(value: object) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:,.1f}%"


def _render_investment_recovery_chart(
    timeline: pd.DataFrame,
    deal_summary: dict[str, object],
    horizon_years: int = 10,
) -> None:
    chart_data = timeline.groupby("year", as_index=False).tail(1).copy()
    chart_data = chart_data.loc[chart_data["year"].between(0, horizon_years)].copy()
    baseline = float(chart_data["equipment_cost_to_recover"].iloc[0])
    cost_owner = str(chart_data["machine_cost_owner"].iloc[0])

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=chart_data["year"],
            y=chart_data["provider_cumulative_net_profit"],
            mode="lines+markers+text",
            name="Provider cumulative net profit",
            text=chart_data["provider_cumulative_net_profit"].map(_compact_money),
            textfont={"size": 10},
            textposition="top center",
            line={"color": "#256D7B", "width": 3},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=chart_data["year"],
            y=chart_data["customer_cumulative_net_saving"],
            mode="lines+markers+text",
            name="Customer cumulative net saving",
            text=chart_data["customer_cumulative_net_saving"].map(_compact_money),
            textfont={"size": 10},
            textposition="bottom center",
            line={"color": "#C46A3A", "width": 3},
        )
    )
    if cost_owner == "Shared":
        fig.add_trace(
            go.Scatter(
                x=chart_data["year"],
                y=chart_data["provider_machine_cost_baseline"],
                mode="lines",
                name="Provider equipment cost to recover",
                line={"color": "#D1495B", "width": 3, "dash": "dash"},
            )
        )
        fig.add_trace(
            go.Scatter(
                x=chart_data["year"],
                y=chart_data["customer_machine_cost_baseline"],
                mode="lines",
                name="Customer equipment cost to recover",
                line={"color": "#A8324A", "width": 3, "dash": "dot"},
            )
        )
    else:
        fig.add_trace(
            go.Scatter(
                x=chart_data["year"],
                y=[baseline] * len(chart_data),
                mode="lines",
                name="Equipment cost to recover",
                line={"color": "#D1495B", "width": 3, "dash": "dash"},
            )
        )
    _add_break_even_marker(fig, timeline, cost_owner, horizon_years=horizon_years)
    fig.update_layout(
        xaxis_title="Year",
        yaxis_title="Cumulative USD",
        xaxis={
            "range": [0, horizon_years],
            "tickmode": "array",
            "tickvals": list(range(1, horizon_years + 1)),
            "ticktext": [str(year) for year in range(1, horizon_years + 1)],
        },
        legend_title=None,
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.28,
            "xanchor": "center",
            "x": 0.5,
        },
        margin={"l": 10, "r": 10, "t": 8, "b": RECOVERY_CHART_BOTTOM_MARGIN},
        height=RECOVERY_CHART_HEIGHT,
    )
    st.markdown("**Investment Recovery Timeline**")
    _render_chart_status(*_recovery_status(timeline, deal_summary, horizon_years, cost_owner))
    st.plotly_chart(fig, use_container_width=True)


def _recovery_status(
    timeline: pd.DataFrame,
    deal_summary: dict[str, object],
    horizon_years: int,
    cost_owner: str,
) -> tuple[str, str]:
    deal_variant, deal_message = _deal_status_message(deal_summary)
    notes = []
    checks = {
        "Provider": "provider_break_even",
        "Customer": "customer_break_even",
    }
    owners = ["Provider", "Customer"] if cost_owner == "Shared" else [cost_owner]
    has_delayed_recovery = False
    for owner in owners:
        column = checks.get(owner)
        if column is None:
            continue
        rows = timeline.loc[timeline[column]]
        if rows.empty:
            notes.append(f"{owner} break-even not reached under current assumptions")
            has_delayed_recovery = True
            continue
        month = int(rows.iloc[0]["month"])
        if month > horizon_years * 12:
            notes.append(f"{owner} break-even exceeds {horizon_years} years")
            has_delayed_recovery = True
        else:
            notes.append(f"{owner} break-even in {month} months")
    if notes:
        recovery_variant = "warning" if has_delayed_recovery else "success"
        variant = _combine_status_variants(deal_variant, recovery_variant)
        return variant, f"{deal_message} | {'; '.join(notes)}"
    return deal_variant, f"{deal_message} | No equipment recovery target is active"


def _deal_status_message(deal_summary: dict[str, object]) -> tuple[str, str]:
    status = str(deal_summary["status"])
    if status == "Mutually positive":
        return "success", status
    if "needs improvement" in status:
        return "warning", status
    return "danger", status


def _combine_status_variants(*variants: str) -> str:
    if "danger" in variants:
        return "danger"
    if "warning" in variants:
        return "warning"
    if "success" in variants:
        return "success"
    return "neutral"


def _render_chart_status(variant: str, message: str) -> None:
    safe_variant = variant if variant in {"success", "warning", "danger", "neutral"} else "neutral"
    st.markdown(
        f"<div class='chart-status {safe_variant}'>{escape(message)}</div>",
        unsafe_allow_html=True,
    )


def _add_break_even_marker(
    fig: go.Figure,
    timeline: pd.DataFrame,
    cost_owner: str,
    horizon_years: int | None = None,
) -> None:
    marker_config = {
        "Provider": ("provider_break_even", "provider_cumulative_net_profit", "#256D7B", "Provider break-even"),
        "Customer": (
            "customer_break_even",
            "customer_cumulative_net_saving",
            "#C46A3A",
            "Customer break-even",
        ),
    }
    if cost_owner == "Shared":
        for owner in ("Provider", "Customer"):
            _add_break_even_marker(fig, timeline, owner, horizon_years=horizon_years)
        return

    if cost_owner not in marker_config:
        return
    flag_col, value_col, color, label = marker_config[cost_owner]
    break_even_rows = timeline.loc[timeline[flag_col]]
    if break_even_rows.empty:
        return

    first = break_even_rows.iloc[0]
    month = int(first["month"])
    if horizon_years is not None and month > horizon_years * 12:
        return
    fig.add_trace(
        go.Scatter(
            x=[month / 12],
            y=[float(first[value_col])],
            mode="markers+text",
            name=label,
            marker={"color": color, "size": 12, "symbol": "diamond"},
            text=[f"{month} months"],
            textposition="top center",
            showlegend=True,
        )
    )


def _compact_money(value: object) -> str:
    amount = float(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1_000_000:
        return f"{sign}${amount / 1_000_000:,.1f}M"
    if amount >= 1_000:
        return f"{sign}${amount / 1_000:,.0f}K"
    return f"{sign}${amount:,.0f}"


def _render_stakeholder_section(
    stakeholder: str,
    report: pd.DataFrame,
    metrics: pd.DataFrame,
) -> None:
    st.subheader(stakeholder)
    st.markdown("**Monthly Run-rate Report**")
    st.markdown(
        _report_html(report, "USD / normal operating month"),
        unsafe_allow_html=True,
    )
    _render_metrics("Investment Metrics", metrics)


def _render_deal_diagnostics(
    investment_timeline: pd.DataFrame,
    monthly_value_split: pd.DataFrame,
    deal_summary: dict[str, object],
) -> None:
    st.subheader("Deal Diagnostics")
    timeline_col, value_col, capacity_col = st.columns([0.50, 0.25, 0.25])
    with timeline_col:
        _render_investment_recovery_chart(
            investment_timeline,
            deal_summary,
            horizon_years=10,
        )
    with value_col:
        _render_monthly_value_split_chart(monthly_value_split)
    with capacity_col:
        _render_capacity_utilization_chart(deal_summary)


def _render_monthly_value_split_chart(monthly_value_split: pd.DataFrame) -> None:
    fig = go.Figure()
    colors = {
        "Fertilizer revenue": "#256D7B",
        "Service fee": "#2A9D8F",
        "Rental": "#6B7280",
        "Avoided disposal": "#C46A3A",
    }
    chart_data = monthly_value_split.copy()
    totals = chart_data.groupby("stakeholder")["amount"].transform("sum")
    chart_data["share"] = chart_data["amount"].where(totals.ne(0), 0) / totals.where(
        totals.ne(0),
        1,
    )
    chart_data["component_label"] = chart_data["component"].map(_short_component_label)
    chart_data["segment_label"] = chart_data.apply(_monthly_value_segment_label, axis=1)
    for component, rows in chart_data.groupby("component", sort=False):
        fig.add_trace(
            go.Bar(
                x=rows["stakeholder"],
                y=rows["amount"],
                name=str(component),
                marker_color=colors.get(str(component), "#64748B"),
                text=rows["segment_label"],
                textposition="inside",
                insidetextanchor="middle",
                textfont={"size": 10},
                hovertemplate=(
                    "%{x}<br>"
                    + f"{_short_component_label(str(component))}: "
                    + "%{y:$,.0f}/mo.<extra></extra>"
                ),
                showlegend=False,
            )
        )
    fig.update_layout(
        title="",
        barmode="stack",
        xaxis_title="",
        yaxis_title="USD/mo.",
        legend_title=None,
        showlegend=False,
        uniformtext={"mode": "hide", "minsize": 9},
        margin={"l": 8, "r": 8, "t": 8, "b": MONTHLY_VALUE_CHART_BOTTOM_MARGIN},
        height=MONTHLY_VALUE_CHART_HEIGHT,
    )
    st.markdown("**Monthly Value Composition**")
    _add_monthly_value_annotations(fig, monthly_value_split)
    _render_chart_status(*_monthly_value_status(monthly_value_split))
    st.plotly_chart(fig, use_container_width=True)


def _short_component_label(component: str) -> str:
    labels = {
        "Fertilizer revenue": "Fertilizer",
        "Service fee": "Service",
        "Rental": "Rental",
        "Avoided disposal": "Disposal saving",
    }
    return labels.get(component, component)


def _monthly_value_segment_label(row: pd.Series) -> str:
    amount = float(row["amount"])
    if abs(amount) < 0.5:
        return ""
    share = float(row["share"])
    return f"{row['component_label']}<br>{_compact_money(amount)} | {share * 100:,.0f}%"


def _add_monthly_value_annotations(fig: go.Figure, monthly_value_split: pd.DataFrame) -> None:
    gross_values = monthly_value_split.groupby("stakeholder")["amount"].sum()
    max_value = max((float(gross_values.get(stakeholder, 0.0)) for stakeholder in ("Provider", "Customer")), default=0.0)
    if max_value > 0:
        fig.update_yaxes(range=[0, max_value * 1.18])
    for stakeholder in ("Provider", "Customer"):
        value = float(gross_values.get(stakeholder, 0.0))
        fig.add_annotation(
            x=stakeholder,
            y=value,
            xref="x",
            yref="y",
            text=f"{_compact_money(value)}/mo.",
            showarrow=False,
            font={"color": "#D1495B", "size": 12},
            align="center",
            yshift=10,
        )


def _monthly_value_status(monthly_value_split: pd.DataFrame) -> tuple[str, str]:
    gross_values = monthly_value_split.groupby("stakeholder")["amount"].sum()
    provider_value = float(gross_values.get("Provider", 0.0))
    customer_value = float(gross_values.get("Customer", 0.0))
    larger = max(provider_value, customer_value)
    if larger <= 0:
        return "danger", "No monthly gross value under current assumptions"
    gap = abs(provider_value - customer_value) / larger
    if gap <= 0.20:
        return "success", "Balanced (within 20%)"
    if gap <= 0.50:
        return "warning", "Moderate Gap (20-50%)"
    return "danger", "Large Gap (>50%)"


def _render_capacity_utilization_chart(deal_summary: dict[str, object]) -> None:
    utilization = float(deal_summary.get("machine_utilization") or 0.0)
    capacity = float(deal_summary.get("machine_capacity_tons_per_day") or 0.0)
    daily_waste = utilization * capacity
    utilization_pct = utilization * 100
    if utilization > 1:
        bar_color = "#D1495B"
        status_text = "Shortfall"
    elif utilization < 0.70:
        bar_color = "#D9A441"
        status_text = "Over-sized"
    else:
        bar_color = "#2A9D8F"
        status_text = "Workable"

    y_max = max(120, utilization_pct + 20)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=["Current setup"],
            y=[utilization_pct],
            name="Utilization",
            marker_color=bar_color,
            text=[
                f"{utilization_pct:,.1f}%<br>"
                f"({daily_waste:,.1f} / {capacity:,.1f} tons/day)"
            ],
            textposition="inside",
            insidetextanchor="middle",
            textfont={"size": 12},
            showlegend=False,
        )
    )
    fig.add_hline(
        y=100,
        line_width=2,
        line_dash="dash",
        line_color="#D1495B",
    )
    fig.update_layout(
        yaxis_title="Utilization",
        yaxis={"range": [0, y_max], "ticksuffix": "%"},
        xaxis_title="",
        legend_title=None,
        showlegend=False,
        margin={"l": 8, "r": 8, "t": 8, "b": CAPACITY_CHART_BOTTOM_MARGIN},
        height=CAPACITY_UTILIZATION_CHART_HEIGHT,
    )
    st.markdown("**Capacity Utilization**")
    _render_chart_status(
        *_capacity_status(status_text, utilization, utilization_pct, daily_waste, capacity)
    )
    st.plotly_chart(fig, use_container_width=True)


def _capacity_status(
    status_text: str,
    utilization: float,
    utilization_pct: float,
    daily_waste: float,
    capacity: float,
) -> tuple[str, str]:
    if utilization > 1:
        variant = "danger"
    elif utilization < 0.70:
        variant = "warning"
    else:
        variant = "success"
    return variant, status_text


def _render_negotiation_lab(
    inputs: FeasibilityInputs,
    view_assumptions: ViewAssumptions,
    machine: MachineSpec,
    base_result: dict[str, object],
) -> None:
    st.subheader("Negotiation Lab")
    control_col, result_col = st.columns([0.48, 0.52])
    with control_col:
        adjustments = _render_adjustment_package(inputs, view_assumptions)
        changed_inputs, changed_assumptions, active_count = _apply_negotiation_package(
            inputs,
            view_assumptions,
            adjustments,
        )

    what_if_result = calculate_dashboard_result(changed_inputs, machine, changed_assumptions)
    with result_col:
        _render_negotiation_impact_chart(base_result, what_if_result, active_count)
        st.markdown(_negotiation_table_html(base_result, what_if_result), unsafe_allow_html=True)


def _render_adjustment_package(
    inputs: FeasibilityInputs,
    view_assumptions: ViewAssumptions,
) -> dict[str, float]:
    configs = _negotiation_package_configs(inputs, view_assumptions)
    column_widths = [0.36, 0.17, 0.25, 0.22]
    st.markdown(_negotiation_package_styles(), unsafe_allow_html=True)
    header_name, header_current, header_adjustment, header_adjusted = st.columns(column_widths)
    with header_name:
        st.markdown("<div class='package-header-label'>Lever</div>", unsafe_allow_html=True)
    with header_current:
        st.markdown("<div class='package-header-label'>Current</div>", unsafe_allow_html=True)
    with header_adjustment:
        st.markdown("<div class='package-header-label'>Adjustment</div>", unsafe_allow_html=True)
    with header_adjusted:
        st.markdown("<div class='package-header-label'>Adjusted</div>", unsafe_allow_html=True)
    adjustments: dict[str, float] = {}
    for config in configs:
        col_name, col_current, col_adjustment, col_adjusted = st.columns(column_widths)
        key = str(config["key"])
        current = float(config["current"])
        with col_name:
            st.markdown(f"<div class='package-row-name'>{escape(str(config['name']))}</div>", unsafe_allow_html=True)
        with col_current:
            st.markdown(
                f"<div class='package-row-value'>{escape(_format_package_value(current, str(config['format'])))}</div>",
                unsafe_allow_html=True,
            )
        with col_adjustment:
            adjustment = st.number_input(
                str(config["label"]),
                min_value=float(config["min"]),
                max_value=float(config["max"]),
                value=float(config["default"]),
                step=float(config["step"]),
                key=f"negotiation_package_{key}",
                label_visibility="collapsed",
            )
        with col_adjusted:
            adjusted = _adjusted_package_value(current, float(adjustment), str(config["mode"]))
            adjusted = min(max(adjusted, float(config["adjusted_min"])), float(config["adjusted_max"]))
            st.markdown(
                f"<div class='package-row-value adjusted'>{escape(_format_package_value(adjusted, str(config['format'])))}</div>",
                unsafe_allow_html=True,
            )
        adjustments[key] = float(adjustment)
        st.markdown("<div class='package-row-divider'></div>", unsafe_allow_html=True)
    return adjustments


def _negotiation_package_styles() -> str:
    return """
<style>
.package-header-label,
.package-row-name,
.package-row-value {
  font-size: 0.80rem;
}
.package-header-label {
  color: inherit;
  font-weight: 700;
  padding: 0.1rem 0 0.12rem 0;
  text-align: center;
}
.package-row-name {
  font-weight: 700;
  padding-top: 0.44rem;
}
.package-row-value {
  font-weight: 700;
  padding-top: 0.44rem;
  text-align: center;
  white-space: nowrap;
}
.package-row-value.adjusted {
  color: #D1495B;
}
.package-row-divider {
  height: 1px;
  margin: 0.05rem 0 0.25rem 0;
  background: rgba(100, 116, 139, 0.18);
}
.st-key-negotiation_lab_section div[data-testid="stNumberInput"] {
  max-width: 11.5rem;
  margin-left: auto;
  margin-right: auto;
}
</style>
"""


def _negotiation_package_configs(
    inputs: FeasibilityInputs,
    view_assumptions: ViewAssumptions,
) -> list[dict[str, float | str]]:
    return [
        {
            "key": "service_fee",
            "name": "Provider service fee",
            "current": inputs.service_fee_usd_per_ton,
            "label": "Provider service fee adjustment",
            "format": "money_per_ton",
            "mode": "absolute",
            "min": -100.0,
            "max": 100.0,
            "default": 0.0,
            "step": 1.0,
            "adjusted_min": 0.0,
            "adjusted_max": 500.0,
        },
        {
            "key": "rental_discount",
            "name": "Rental discount",
            "current": inputs.rental_discount_rate * 100,
            "label": "Rental discount adjustment",
            "format": "percent",
            "mode": "absolute",
            "min": -80.0,
            "max": 80.0,
            "default": 0.0,
            "step": 1.0,
            "adjusted_min": 0.0,
            "adjusted_max": 80.0,
        },
        {
            "key": "fertilizer_price",
            "name": "Fertilizer price",
            "current": inputs.fertilizer_price_usd_per_ton,
            "label": "Fertilizer price adjustment",
            "format": "money_per_ton",
            "mode": "absolute",
            "min": -200.0,
            "max": 200.0,
            "default": 0.0,
            "step": 1.0,
            "adjusted_min": 0.0,
            "adjusted_max": 1000.0,
        },
        {
            "key": "provider_fertilizer_share",
            "name": "Provider fertilizer share",
            "current": view_assumptions.provider_fertilizer_revenue_share * 100,
            "label": "Provider fertilizer share adjustment",
            "format": "percent",
            "mode": "absolute",
            "min": -100.0,
            "max": 100.0,
            "default": 0.0,
            "step": 1.0,
            "adjusted_min": 0.0,
            "adjusted_max": 100.0,
        },
        {
            "key": "machine_discount",
            "name": "Machine discount",
            "current": inputs.machine_discount_rate * 100,
            "label": "Machine discount adjustment",
            "format": "percent",
            "mode": "absolute",
            "min": -80.0,
            "max": 80.0,
            "default": 0.0,
            "step": 1.0,
            "adjusted_min": 0.0,
            "adjusted_max": 80.0,
        },
        {
            "key": "disposal_fee",
            "name": "Disposal fee",
            "current": view_assumptions.current_disposal_fee_usd_per_ton,
            "label": "Disposal fee adjustment",
            "format": "money_per_ton",
            "mode": "absolute",
            "min": -150.0,
            "max": 150.0,
            "default": 0.0,
            "step": 1.0,
            "adjusted_min": 0.0,
            "adjusted_max": 500.0,
        },
        {
            "key": "conversion_rate",
            "name": "Conversion rate",
            "current": inputs.conversion_rate * 100,
            "label": "Conversion rate adjustment",
            "format": "percent",
            "mode": "absolute",
            "min": -50.0,
            "max": 50.0,
            "default": 0.0,
            "step": 1.0,
            "adjusted_min": 0.0,
            "adjusted_max": 100.0,
        },
    ]


def _apply_negotiation_package(
    inputs: FeasibilityInputs,
    view_assumptions: ViewAssumptions,
    adjustments: dict[str, float],
) -> tuple[FeasibilityInputs, ViewAssumptions, int]:
    changed_inputs = replace(
        inputs,
        service_fee_usd_per_ton=max(inputs.service_fee_usd_per_ton + adjustments["service_fee"], 0.0),
        rental_discount_rate=_clamp_ratio(inputs.rental_discount_rate + adjustments["rental_discount"] / 100, 0.0, 0.8),
        fertilizer_price_usd_per_ton=max(inputs.fertilizer_price_usd_per_ton + adjustments["fertilizer_price"], 0.0),
        machine_discount_rate=_clamp_ratio(inputs.machine_discount_rate + adjustments["machine_discount"] / 100, 0.0, 0.8),
        conversion_rate=_clamp_ratio(inputs.conversion_rate + adjustments["conversion_rate"] / 100, 0.0, 1.0),
    )
    changed_assumptions = replace(
        view_assumptions,
        current_disposal_fee_usd_per_ton=max(
            view_assumptions.current_disposal_fee_usd_per_ton + adjustments["disposal_fee"],
            0.0,
        ),
        provider_fertilizer_revenue_share=_clamp_ratio(
            view_assumptions.provider_fertilizer_revenue_share + adjustments["provider_fertilizer_share"] / 100,
            0.0,
            1.0,
        ),
    )
    active_count = sum(1 for value in adjustments.values() if abs(value) > 0.0001)
    return changed_inputs, changed_assumptions, active_count


def _adjusted_package_value(current: float, adjustment: float, mode: str) -> float:
    if mode == "relative_percent":
        return current * (1 + adjustment / 100)
    return current + adjustment


def _format_package_value(value: float, value_format: str) -> str:
    if value_format == "percent":
        return f"{value:.1f}%"
    if value_format == "money_per_ton":
        return f"${value:,.0f}/ton"
    return f"{value:,.1f}"


def _render_negotiation_impact_chart(
    base_result: dict[str, object],
    what_if_result: dict[str, object],
    active_count: int,
) -> None:
    base_summary = base_result["deal_summary"]
    what_if_summary = what_if_result["deal_summary"]
    provider_delta = float(what_if_summary["provider_monthly_net_profit"]) - float(base_summary["provider_monthly_net_profit"])
    customer_delta = float(what_if_summary["customer_monthly_net_saving"]) - float(
        base_summary["customer_monthly_net_saving"]
    )
    max_abs = max(abs(provider_delta), abs(customer_delta), 1.0)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=["Customer impact"],
            x=[customer_delta],
            orientation="h",
            name="Customer",
            marker_color="#C46A3A",
            text=[_signed_money(customer_delta)],
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            y=["Provider impact"],
            x=[provider_delta],
            orientation="h",
            name="Provider",
            marker_color="#256D7B",
            text=[_signed_money(provider_delta)],
            textposition="outside",
        )
    )
    fig.add_vline(x=0, line_width=1, line_color="rgba(100, 116, 139, 0.8)")
    fig.update_layout(
        barmode="relative",
        title=f"Impact Split ({active_count} adjusted levers)",
        xaxis_title="Monthly impact, USD",
        xaxis={"range": [-max_abs * 1.35, max_abs * 1.35]},
        yaxis_title="",
        legend={"orientation": "h", "yanchor": "top", "y": -0.34, "xanchor": "center", "x": 0.5},
        bargap=0.52,
        margin={"l": 10, "r": 10, "t": 38, "b": 92},
        height=285,
    )
    st.plotly_chart(fig, use_container_width=True)


def _negotiation_table_html(
    base_result: dict[str, object],
    what_if_result: dict[str, object],
) -> str:
    base_summary = base_result["deal_summary"]
    what_if_summary = what_if_result["deal_summary"]
    provider_base_monthly = float(base_summary["provider_monthly_net_profit"])
    provider_what_if_monthly = float(what_if_summary["provider_monthly_net_profit"])
    customer_base_monthly = float(base_summary["customer_monthly_net_saving"])
    customer_what_if_monthly = float(what_if_summary["customer_monthly_net_saving"])
    rows = [
        _negotiation_comparison_row(
            "Monthly net result",
            _negotiation_value_cell(provider_base_monthly, provider_what_if_monthly, "money"),
            _negotiation_value_cell(customer_base_monthly, customer_what_if_monthly, "money"),
        ),
        _negotiation_comparison_row(
            "Payback / break-even",
            _negotiation_value_cell(
                base_result["provider_returns"]["payback_months"],
                what_if_result["provider_returns"]["payback_months"],
                "months",
            ),
            _negotiation_value_cell(
                base_result["customer_returns"]["payback_months"],
                what_if_result["customer_returns"]["payback_months"],
                "months",
            ),
        ),
        _negotiation_comparison_row(
            "Initial investment",
            _negotiation_value_cell(
                float(base_result["provider_returns"]["initial_investment"]),
                float(what_if_result["provider_returns"]["initial_investment"]),
                "money",
            ),
            _negotiation_value_cell(
                float(base_result["customer_returns"]["initial_investment"]),
                float(what_if_result["customer_returns"]["initial_investment"]),
                "money",
            ),
        ),
        _negotiation_comparison_row(
            "Annualized net result",
            _negotiation_value_cell(provider_base_monthly * 12, provider_what_if_monthly * 12, "money"),
            _negotiation_value_cell(customer_base_monthly * 12, customer_what_if_monthly * 12, "money"),
        ),
    ]
    return """
<style>
.negotiation-report {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
  table-layout: fixed;
  margin-top: 0.35rem;
}}
.negotiation-report th,
.negotiation-report td {{
  border: 1px solid rgba(100, 116, 139, 0.28);
  padding: 0.46rem 0.55rem;
}}
.negotiation-report th {{
  text-align: center;
  font-weight: 700;
  background: rgba(100, 116, 139, 0.10);
}}
.negotiation-report .amount {{
  text-align: center;
  font-weight: 700;
}}
.negotiation-report .metric {{
  font-weight: 700;
  width: 30%;
}}
.negotiation-report .value-line,
.negotiation-report .delta-line {{
  display: block;
  line-height: 1.35;
  white-space: nowrap;
}}
.negotiation-report .delta-line {{
  color: #D1495B;
  font-size: 0.78rem;
  margin-top: 0.12rem;
}}
</style>
<table class="negotiation-report">
  <colgroup>
    <col style="width: 30%;">
    <col style="width: 35%;">
    <col style="width: 35%;">
  </colgroup>
  <thead>
    <tr>
      <th>Metric</th>
      <th>Provider</th>
      <th>Customer</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
""".format(rows="\n".join(rows))


def _negotiation_comparison_row(metric: str, provider_cell: str, customer_cell: str) -> str:
    return (
        "<tr>"
        f"<td class='metric'>{escape(metric)}</td>"
        f"<td class='amount'>{provider_cell}</td>"
        f"<td class='amount'>{customer_cell}</td>"
        "</tr>"
    )


def _negotiation_value_cell(base: object, what_if: object, value_type: str) -> str:
    if value_type == "money":
        base_value = float(base)
        what_if_value = float(what_if)
        change = what_if_value - base_value
        base_text = _money(base_value)
        what_if_text = _money(what_if_value)
        change_text = _signed_money(change)
    elif value_type == "months":
        base_text = _months_text(base)
        what_if_text = _months_text(what_if)
        change_text = _month_delta_text(base, what_if)
    else:
        base_text = str(base)
        what_if_text = str(what_if)
        change_text = "Changed" if base_text != what_if_text else "-"
    return (
        f"<span class='value-line'>{escape(base_text)} -> {escape(what_if_text)}</span>"
        f"<span class='delta-line'>Delta {escape(change_text)}</span>"
    )


def _months_text(value: object) -> str:
    if value is None:
        return "N/A"
    return f"{int(value)} mo."


def _month_delta_text(base: object, what_if: object) -> str:
    if base is None or what_if is None:
        return "-"
    delta = int(what_if) - int(base)
    if delta == 0:
        return "0 mo."
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta} mo."


def _signed_money(value: float) -> str:
    if abs(value) < 0.5:
        return "$0"
    sign = "+" if value > 0 else "-"
    return f"{sign}${abs(value):,.0f}"


def _signed_number(value: float) -> str:
    if abs(value) < 0.0001:
        return "0"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:g}"


def _clamp_ratio(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _render_sensitivity_impact_chart(sensitivity: pd.DataFrame) -> None:
    chart_data = sensitivity.copy()
    chart_data["lever_label"] = chart_data["group"] + " - " + chart_data["lever"]
    chart_data = chart_data.sort_values("impact_score", ascending=True)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=chart_data["lever_label"],
            x=chart_data["provider_impact_value"],
            orientation="h",
            name="Provider impact",
            marker_color="#256D7B",
            text=chart_data["provider_impact"],
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            y=chart_data["lever_label"],
            x=chart_data["customer_impact_value"],
            orientation="h",
            name="Customer impact",
            marker_color="#C46A3A",
            text=chart_data["customer_impact"],
            textposition="outside",
        )
    )
    fig.add_vline(x=0, line_width=1, line_color="rgba(100,116,139,0.65)")
    fig.update_layout(
        barmode="group",
        xaxis_title="Monthly impact, USD",
        yaxis_title="",
        legend_title=None,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        height=max(420, 34 * len(chart_data)),
    )
    st.markdown("**Sensitivity Impact**")
    st.plotly_chart(fig, use_container_width=True)


def _render_report(title: str, report: pd.DataFrame, amount_header: str) -> None:
    st.markdown(f"**{title}**")
    st.markdown(_report_html(report, amount_header), unsafe_allow_html=True)


def _render_metrics(title: str, metrics: pd.DataFrame) -> None:
    st.markdown(f"**{title}**")
    st.markdown(_metrics_html(metrics), unsafe_allow_html=True)


def _render_sensitivity(title: str, sensitivity: pd.DataFrame) -> None:
    st.markdown(f"**{title}**")
    st.markdown(_sensitivity_html(sensitivity), unsafe_allow_html=True)


def _reference_table_html(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "<p>No records.</p>"
    headers = list(rows[0])
    header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    row_html = []
    for row in rows:
        cells = []
        for index, header in enumerate(headers):
            class_name = " class='text-cell'" if index in {0, 1} else ""
            cells.append(f"<td{class_name}>{escape(str(row[header]))}</td>")
        row_html.append(f"<tr>{''.join(cells)}</tr>")
    return """
<style>
.reference-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
  margin-bottom: 1rem;
}}
.reference-table th,
.reference-table td {{
  border: 1px solid rgba(100, 116, 139, 0.28);
  padding: 0.48rem 0.55rem;
}}
.reference-table th {{
  text-align: center;
  font-weight: 700;
  background: rgba(100, 116, 139, 0.10);
}}
.reference-table td {{
  text-align: right;
  white-space: nowrap;
}}
.reference-table .text-cell {{
  text-align: left;
}}
</style>
<table class="reference-table">
  <thead>
    <tr>{headers}</tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
""".format(headers=header_html, rows="\n".join(row_html))


def _report_html(report: pd.DataFrame, amount_header: str) -> str:
    rows = []
    for _, row in report.iterrows():
        section = str(row["section"])
        row_class = " report-total" if section in {"Subtotal", "Result", "Investment and returns"} else ""
        rows.append(
            "<tr class='{row_class}'>"
            "<td>{section}</td>"
            "<td>{line_item}</td>"
            "<td class='amount'>{value}</td>"
            "</tr>".format(
                row_class=row_class.strip(),
                section=escape(section),
                line_item=escape(str(row["line_item"])),
                value=escape(str(row["value"])),
            )
        )
    return """
<style>
.financial-report {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.92rem;
  table-layout: fixed;
}}
.financial-report th, .financial-report td {{
  border: 1px solid rgba(100, 116, 139, 0.28);
  padding: 0.55rem 0.6rem;
}}
.financial-report th {{
  text-align: center;
  font-weight: 700;
  background: rgba(100, 116, 139, 0.10);
}}
.financial-report .amount {{
  text-align: right;
  white-space: nowrap;
}}
.financial-report .report-total td {{
  font-weight: 700;
  background: rgba(100, 116, 139, 0.07);
}}
</style>
<table class="financial-report">
  <colgroup>
    <col style="width: 15%;">
    <col style="width: 43%;">
    <col style="width: 42%;">
  </colgroup>
  <thead>
    <tr>
      <th>Section</th>
      <th>Line item</th>
      <th>{amount_header}</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
""".format(rows="\n".join(rows), amount_header=escape(amount_header))


def _metrics_html(metrics: pd.DataFrame) -> str:
    rows = []
    for _, row in metrics.iterrows():
        rows.append(
            "<tr>"
            "<td>{metric}</td>"
            "<td class='amount'>{value}</td>"
            "</tr>".format(
                metric=escape(str(row["metric"])),
                value=escape(str(row["value"])),
            )
        )
    return """
<style>
.metrics-report {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
  table-layout: fixed;
  margin-top: 0.35rem;
}}
.metrics-report td:first-child {{
  text-align: left;
}}
.metrics-report td {{
  border: 1px solid rgba(100, 116, 139, 0.28);
  padding: 0.48rem 0.6rem;
}}
.metrics-report tr:last-child td {{
  border-bottom: 1px solid rgba(100, 116, 139, 0.28);
}}
.metrics-report .amount {{
  text-align: right;
  white-space: nowrap;
  font-weight: 700;
}}
</style>
<table class="metrics-report">
  <colgroup>
    <col style="width: 58%;">
    <col style="width: 42%;">
  </colgroup>
  <tbody>
    {rows}
  </tbody>
</table>
""".format(rows="\n".join(rows))


def _sensitivity_html(sensitivity: pd.DataFrame) -> str:
    rows = []
    for _, row in sensitivity.iterrows():
        rows.append(
            "<tr>"
            "<td>{group}</td>"
            "<td>{lever}</td>"
            "<td>{change}</td>"
            "<td class='amount'>{provider_impact}</td>"
            "<td class='amount'>{customer_impact}</td>"
            "<td>{interpretation}</td>"
            "</tr>".format(
                group=escape(str(row["group"])),
                lever=escape(str(row["lever"])),
                change=escape(str(row["change"])),
                provider_impact=escape(str(row["provider_impact"])),
                customer_impact=escape(str(row["customer_impact"])),
                interpretation=escape(str(row["interpretation"])),
            )
        )
    return """
<style>
.sensitivity-report {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.78rem;
  margin-top: 0.35rem;
}}
.sensitivity-report th,
.sensitivity-report td {{
  border: 1px solid rgba(100, 116, 139, 0.28);
  padding: 0.42rem 0.48rem;
  vertical-align: top;
}}
.sensitivity-report th {{
  text-align: left;
  font-weight: 700;
  background: rgba(100, 116, 139, 0.10);
}}
.sensitivity-report .amount {{
  text-align: right;
  white-space: nowrap;
  font-weight: 700;
}}
</style>
<table class="sensitivity-report">
  <thead>
    <tr>
      <th>Group</th>
      <th>Lever</th>
      <th>Change tested</th>
      <th>Provider impact</th>
      <th>Customer impact</th>
      <th>Interpretation</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
""".format(rows="\n".join(rows))


if __name__ == "__main__":
    main()
