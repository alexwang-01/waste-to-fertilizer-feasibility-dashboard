"""Service helpers used by the Streamlit dashboard.

The dashboard should stay thin: collect inputs, call the model, and display
results. This module keeps the reusable data-loading and presentation-table
logic outside the UI file.
"""

from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
from typing import Any

import pandas as pd

from .financial_model import (
    FeasibilityInputs,
    MachineSpec,
    choose_machine,
    irr,
    load_machine_specs,
    monthly_unit_economics,
    summarize_feasibility,
)
from .view_model import ViewAssumptions, build_views, views_to_records


ROOT = Path(__file__).resolve().parents[1]


def load_dashboard_data(root: Path = ROOT) -> dict[str, pd.DataFrame]:
    """Load reference CSV files for the dashboard."""

    processed = root / "data" / "processed"
    return normalize_dashboard_data(
        {
            "machine_specs": load_machine_specs(processed / "machine_specs.csv"),
            "personnel_defaults": pd.read_csv(processed / "personnel_defaults.csv"),
            "scenarios": pd.read_csv(processed / "scenario_defaults.csv"),
            "view_assumptions": pd.read_csv(processed / "view_assumptions.csv"),
        }
    )


def normalize_dashboard_data(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Normalize dashboard reference data across deployed app cache versions."""

    normalized = dict(data)
    if "view_assumptions" in normalized:
        normalized["view_assumptions"] = _normalize_view_assumptions(normalized["view_assumptions"])
    return normalized


def _normalize_view_assumptions(view_assumptions: pd.DataFrame) -> pd.DataFrame:
    df = view_assumptions.copy()
    old_provider_prefix = "l" + "g" + "_"
    rename_map = {
        column: "provider_" + column[len(old_provider_prefix) :]
        for column in df.columns
        if column.startswith(old_provider_prefix)
    }
    if rename_map:
        df = df.rename(columns=rename_map)

    if "scenario" in df.columns:
        old_provider_rental = "opex_" + "l" + "g" + "_rental"
        df.loc[df["scenario"].eq(old_provider_rental), "scenario"] = "opex_provider_rental"

    required_defaults = {
        "current_disposal_fee_usd_per_ton": 70.0,
        "provider_fertilizer_revenue_share": 0.5,
        "provider_service_fee_share": 0.0,
        "provider_rental_revenue_share": 1.0,
        "provider_cogs_share": 0.0,
        "provider_non_rental_opex_share": 0.0,
        "provider_non_operating_expense_share": 0.0,
        "customer_initial_investment_share": 0.0,
        "source_note": "Generated compatibility default.",
    }
    for column, default in required_defaults.items():
        if column not in df.columns:
            df[column] = default

    if "scenario" not in df.columns:
        df["scenario"] = "capex_customer_owned"

    if not df["scenario"].eq("opex_provider_rental").any():
        row = {"scenario": "opex_provider_rental", **required_defaults}
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)

    return df


def machine_from_model(machine_specs: pd.DataFrame, model: str) -> MachineSpec:
    """Return a machine specification by model name."""

    matches = machine_specs.loc[machine_specs["model"].eq(model)]
    if matches.empty:
        raise ValueError(f"Unknown machine model: {model}")
    row = matches.iloc[0]
    return MachineSpec(
        model=str(row["model"]),
        capacity_ton=float(row["capacity_ton"]),
        total_load_kw=float(row["total_load_kw"]),
        operation_hours_per_day=float(row["operation_hours_per_day"]),
        asia_price_no_ce_usd=float(row["asia_price_no_ce_usd"]),
        asia_price_with_ce_usd=_optional_float(row.get("asia_price_with_ce_usd")),
        europe_price_with_ce_usd=_optional_float(row.get("europe_price_with_ce_usd")),
        monthly_rental_ratio=float(row.get("monthly_rental_ratio", 0.0065)),
    )


def select_machine(
    machine_specs: pd.DataFrame,
    inputs: FeasibilityInputs,
    selected_model: str | None = None,
) -> MachineSpec:
    """Choose a machine automatically or from a user-selected model."""

    if selected_model:
        return machine_from_model(machine_specs, selected_model)
    return choose_machine(machine_specs, inputs.waste_tons_per_day)


def view_assumptions_from_row(row: pd.Series) -> ViewAssumptions:
    """Build view allocation assumptions from a CSV row."""

    return ViewAssumptions(
        current_disposal_fee_usd_per_ton=float(row["current_disposal_fee_usd_per_ton"]),
        provider_fertilizer_revenue_share=float(row["provider_fertilizer_revenue_share"]),
        provider_service_fee_share=float(row["provider_service_fee_share"]),
        provider_rental_revenue_share=float(row["provider_rental_revenue_share"]),
        provider_cogs_share=float(row["provider_cogs_share"]),
        provider_non_rental_opex_share=float(row["provider_non_rental_opex_share"]),
        provider_non_operating_expense_share=float(row["provider_non_operating_expense_share"]),
        customer_initial_investment_share=float(row["customer_initial_investment_share"]),
    )


def calculate_dashboard_result(
    inputs: FeasibilityInputs,
    machine: MachineSpec,
    view_assumptions: ViewAssumptions,
) -> dict[str, object]:
    """Calculate all dashboard tables for one scenario."""

    summary = summarize_feasibility(inputs, machine)
    unit = monthly_unit_economics(inputs, machine)
    views = build_views(inputs, machine, view_assumptions)
    economics = _stakeholder_economics(inputs, unit, view_assumptions)
    machine_baseline = _equipment_cost_to_recover(unit)
    provider_equipment_cost = machine_baseline * (1 - view_assumptions.customer_initial_investment_share)
    customer_equipment_cost = machine_baseline * view_assumptions.customer_initial_investment_share
    provider_returns = _return_metrics(
        monthly_net_value=economics["provider_net_profit"],
        initial_investment=provider_equipment_cost,
        inputs=inputs,
    )
    customer_returns = _return_metrics(
        monthly_net_value=economics["customer_net_saving"],
        initial_investment=customer_equipment_cost,
        inputs=inputs,
    )
    provider_statement = _provider_statement(economics)
    customer_statement = _customer_statement(economics)
    investment_timeline = _investment_recovery_timeline(
        inputs=inputs,
        equipment_cost_to_recover=machine_baseline,
        customer_investment_share=view_assumptions.customer_initial_investment_share,
        provider_monthly_net_value=economics["provider_net_profit"],
        customer_monthly_net_value=economics["customer_net_saving"],
    )
    sensitivity_table = _sensitivity_table(inputs, machine, view_assumptions, economics)
    monthly_value_split = _monthly_value_split_table(economics)

    return {
        "summary": summary,
        "unit": unit,
        "deal_summary": _deal_summary(summary, economics, investment_timeline),
        "provider_statement": provider_statement,
        "customer_statement": customer_statement,
        "provider_report": _report_table(provider_statement),
        "customer_report": _report_table(customer_statement),
        "provider_investment_metrics": _investment_metrics_table(
            returns=provider_returns,
            monthly_net_value=economics["provider_net_profit"],
            equipment_cost_to_recover=provider_equipment_cost,
            timeline=investment_timeline,
            break_even_column="provider_break_even",
        ),
        "customer_investment_metrics": _investment_metrics_table(
            returns=customer_returns,
            monthly_net_value=economics["customer_net_saving"],
            equipment_cost_to_recover=customer_equipment_cost,
            timeline=investment_timeline,
            break_even_column="customer_break_even",
        ),
        "provider_returns": provider_returns,
        "customer_returns": customer_returns,
        "investment_recovery_timeline": investment_timeline,
        "break_even_timeline": investment_timeline,
        "sensitivity": sensitivity_table,
        "provider_sensitivity": sensitivity_table,
        "customer_sensitivity": sensitivity_table,
        "monthly_value_split": monthly_value_split,
        "view_table": pd.DataFrame(views_to_records(views)),
        "revenue_table": _revenue_table(unit),
        "cost_table": _cost_table(unit),
    }


def _stakeholder_economics(
    inputs: FeasibilityInputs,
    unit: dict[str, float | str],
    assumptions: ViewAssumptions,
) -> dict[str, float]:
    monthly_waste_tons = float(unit["monthly_waste_tons"])
    fertilizer_revenue = float(unit["fertilizer_revenue"])
    service_revenue = float(unit["service_revenue"])
    rental_cost = float(unit["rental_cost"])
    cogs = float(unit["cogs"])
    non_rental_opex = float(unit["operating_expenses"]) - rental_cost
    non_operating_expenses = float(unit["non_operating_expenses"])

    avoided_disposal_savings = monthly_waste_tons * assumptions.current_disposal_fee_usd_per_ton

    provider_fertilizer_revenue = fertilizer_revenue * assumptions.provider_fertilizer_revenue_share
    provider_service_revenue = service_revenue * assumptions.provider_service_fee_share
    provider_rental_revenue = rental_cost * assumptions.provider_rental_revenue_share
    provider_revenue = provider_fertilizer_revenue + provider_service_revenue + provider_rental_revenue
    provider_direct_cost = cogs * assumptions.provider_cogs_share
    provider_operating_cost = non_rental_opex * assumptions.provider_non_rental_opex_share
    provider_non_operating_expense = non_operating_expenses * assumptions.provider_non_operating_expense_share
    provider_net_profit = provider_revenue - provider_direct_cost - provider_operating_cost - provider_non_operating_expense

    customer_fertilizer_revenue = fertilizer_revenue * (1 - assumptions.provider_fertilizer_revenue_share)
    customer_payments_to_provider = (
        service_revenue * assumptions.provider_service_fee_share
        + rental_cost * assumptions.provider_rental_revenue_share
    )
    customer_operating_cost = (
        cogs * (1 - assumptions.provider_cogs_share)
        + non_rental_opex * (1 - assumptions.provider_non_rental_opex_share)
    )
    customer_non_operating_expense = non_operating_expenses * (1 - assumptions.provider_non_operating_expense_share)
    customer_benefit = avoided_disposal_savings + customer_fertilizer_revenue
    customer_net_saving = (
        customer_benefit
        - customer_payments_to_provider
        - customer_operating_cost
        - customer_non_operating_expense
    )

    return {
        "monthly_waste_tons": monthly_waste_tons,
        "monthly_fertilizer_tons": float(unit["monthly_fertilizer_tons"]),
        "provider_fertilizer_revenue": provider_fertilizer_revenue,
        "provider_service_revenue": provider_service_revenue,
        "provider_rental_revenue": provider_rental_revenue,
        "provider_revenue": provider_revenue,
        "provider_direct_cost": provider_direct_cost,
        "provider_operating_cost": provider_operating_cost,
        "provider_non_operating_expense": provider_non_operating_expense,
        "provider_net_profit": provider_net_profit,
        "avoided_disposal_savings": avoided_disposal_savings,
        "customer_fertilizer_revenue": customer_fertilizer_revenue,
        "customer_benefit": customer_benefit,
        "customer_payments_to_provider": customer_payments_to_provider,
        "customer_operating_cost": customer_operating_cost,
        "customer_non_operating_expense": customer_non_operating_expense,
        "customer_net_saving": customer_net_saving,
    }


def _deal_summary(
    summary: dict[str, Any],
    economics: dict[str, float],
    investment_timeline: pd.DataFrame,
) -> dict[str, Any]:
    provider_positive = economics["provider_net_profit"] > 0
    customer_positive = economics["customer_net_saving"] > 0
    if provider_positive and customer_positive:
        status = "Mutually positive"
    elif provider_positive:
        status = "Provider positive, customer needs improvement"
    elif customer_positive:
        status = "Customer positive, Provider needs improvement"
    else:
        status = "Needs redesign"

    first_row = investment_timeline.iloc[0] if not investment_timeline.empty else {}
    return {
        "status": status,
        "business_model": summary["business_model"],
        "machine_setup": summary["machine_model"],
        "machine_capacity_tons_per_day": summary["machine_capacity_tons_per_day"],
        "machine_capacity_sufficient": summary["machine_capacity_sufficient"],
        "machine_utilization": summary["machine_utilization"],
        "monthly_waste_tons": economics["monthly_waste_tons"],
        "monthly_fertilizer_tons": economics["monthly_fertilizer_tons"],
        "provider_monthly_net_profit": economics["provider_net_profit"],
        "customer_monthly_net_saving": economics["customer_net_saving"],
        "equipment_cost_to_recover": first_row.get("equipment_cost_to_recover", 0.0),
        "machine_cost_owner": first_row.get("machine_cost_owner", "None"),
    }


def _provider_statement(economics: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"section": "Revenue", "line_item": "Fertilizer revenue retained by Provider", "amount": economics["provider_fertilizer_revenue"]},
            {"section": "Revenue", "line_item": "Service fee revenue", "amount": economics["provider_service_revenue"]},
            {"section": "Revenue", "line_item": "Rental revenue", "amount": economics["provider_rental_revenue"]},
            {"section": "Subtotal", "line_item": "Provider revenue", "amount": economics["provider_revenue"]},
            {"section": "Cost", "line_item": "Provider direct cost", "amount": -economics["provider_direct_cost"]},
            {"section": "Cost", "line_item": "Provider operating cost", "amount": -economics["provider_operating_cost"]},
            {"section": "Cost", "line_item": "Provider interest and tax", "amount": -economics["provider_non_operating_expense"]},
            {"section": "Result", "line_item": "Provider monthly net profit", "amount": economics["provider_net_profit"]},
        ]
    )


def _customer_statement(economics: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"section": "Benefit", "line_item": "Avoided disposal cost", "amount": economics["avoided_disposal_savings"]},
            {"section": "Benefit", "line_item": "Fertilizer revenue retained by customer", "amount": economics["customer_fertilizer_revenue"]},
            {"section": "Benefit", "line_item": "Additional benefit not modeled", "amount": 0.0},
            {"section": "Subtotal", "line_item": "Customer benefit", "amount": economics["customer_benefit"]},
            {"section": "Cost", "line_item": "Payments to Provider", "amount": -economics["customer_payments_to_provider"]},
            {"section": "Cost", "line_item": "Customer operating cost", "amount": -economics["customer_operating_cost"]},
            {"section": "Cost", "line_item": "Customer interest and tax", "amount": -economics["customer_non_operating_expense"]},
            {"section": "Result", "line_item": "Customer monthly net saving", "amount": economics["customer_net_saving"]},
        ]
    )


def _return_metrics(
    monthly_net_value: float,
    initial_investment: float,
    inputs: FeasibilityInputs,
) -> dict[str, float | int | None]:
    months = inputs.cashflow_months or tuple([12] * inputs.analysis_years)
    total_net_value = sum(monthly_net_value * month_count for month_count in months)
    if initial_investment <= 0:
        return {
            "initial_investment": initial_investment,
            "payback_months": 0 if monthly_net_value > 0 else None,
            "roi": None,
            "irr": None,
        }
    cashflows = [-initial_investment] + [monthly_net_value * month_count for month_count in months]
    payback = None if monthly_net_value <= 0 else math.ceil(initial_investment / monthly_net_value)
    return {
        "initial_investment": initial_investment,
        "payback_months": payback,
        "roi": (total_net_value - initial_investment) / initial_investment,
        "irr": irr(cashflows),
    }


def _report_table(
    statement: pd.DataFrame,
) -> pd.DataFrame:
    rows = [
        {
            "section": row["section"],
            "line_item": row["line_item"],
            "value": _format_money(float(row["amount"])),
        }
        for _, row in statement.iterrows()
    ]
    return pd.DataFrame(rows)


def _investment_metrics_table(
    returns: dict[str, float | int | None],
    monthly_net_value: float,
    equipment_cost_to_recover: float,
    timeline: pd.DataFrame,
    break_even_column: str,
) -> pd.DataFrame:
    payback_value = "N/A"
    if equipment_cost_to_recover > 0:
        payback_value = (
            f"{_format_months(returns['payback_months'])} / "
            f"{_format_break_even_year(timeline, break_even_column)}"
        )
    return pd.DataFrame(
        [
            {
                "metric": "Initial investment",
                "value": _format_money(equipment_cost_to_recover),
            },
            {
                "metric": "Monthly net profit / saving",
                "value": _format_money(monthly_net_value),
            },
            {
                "metric": "Annualized net profit / saving",
                "value": _format_money(monthly_net_value * 12),
            },
            {
                "metric": "Payback / break-even",
                "value": payback_value,
            },
        ]
    )


def _sensitivity_table(
    inputs: FeasibilityInputs,
    machine: MachineSpec,
    assumptions: ViewAssumptions,
    base_economics: dict[str, float],
) -> pd.DataFrame:
    scenarios = [
        {
            "group": "Negotiation",
            "lever": "Provider service fee",
            "change": "+$10/ton waste",
            "inputs": replace(inputs, service_fee_usd_per_ton=inputs.service_fee_usd_per_ton + 10),
            "assumptions": assumptions,
        },
        {
            "group": "Negotiation",
            "lever": "Rental discount",
            "change": "+5 percentage points",
            "inputs": replace(
                inputs,
                rental_discount_rate=_clamp(inputs.rental_discount_rate + 0.05, 0.0, 0.8),
            ),
            "assumptions": assumptions,
        },
        {
            "group": "Negotiation",
            "lever": "Machine discount",
            "change": "+5 percentage points",
            "inputs": replace(
                inputs,
                machine_discount_rate=_clamp(inputs.machine_discount_rate + 0.05, 0.0, 0.8),
            ),
            "assumptions": assumptions,
        },
        {
            "group": "Negotiation",
            "lever": "Customer equipment share",
            "change": "+10 percentage points",
            "inputs": inputs,
            "assumptions": replace(
                assumptions,
                customer_initial_investment_share=_clamp(
                    assumptions.customer_initial_investment_share + 0.10,
                    0.0,
                    1.0,
                ),
            ),
        },
        {
            "group": "Negotiation",
            "lever": "Provider fertilizer revenue share",
            "change": "+5 percentage points",
            "inputs": inputs,
            "assumptions": replace(
                assumptions,
                provider_fertilizer_revenue_share=_clamp(
                    assumptions.provider_fertilizer_revenue_share + 0.05,
                    0.0,
                    1.0,
                ),
            ),
        },
        {
            "group": "Operational risk",
            "lever": "Waste volume",
            "change": "-10%",
            "inputs": replace(inputs, waste_tons_per_day=max(inputs.waste_tons_per_day * 0.9, 0.1)),
            "assumptions": assumptions,
        },
        {
            "group": "Operational risk",
            "lever": "Conversion rate",
            "change": "-5 percentage points",
            "inputs": replace(inputs, conversion_rate=_clamp(inputs.conversion_rate - 0.05, 0.0, 1.0)),
            "assumptions": assumptions,
        },
        {
            "group": "Operational risk",
            "lever": "Fertilizer sales completion",
            "change": "-10 percentage points",
            "inputs": replace(
                inputs,
                fertilizer_sales_completion_rate=_clamp(
                    inputs.fertilizer_sales_completion_rate - 0.10,
                    0.0,
                    1.0,
                ),
            ),
            "assumptions": assumptions,
        },
        {
            "group": "Operational risk",
            "lever": "Electricity rate",
            "change": "+10%",
            "inputs": replace(inputs, electricity_rate_usd_per_kwh=inputs.electricity_rate_usd_per_kwh * 1.1),
            "assumptions": assumptions,
        },
        {
            "group": "Operational risk",
            "lever": "Enzyme cost",
            "change": "+10%",
            "inputs": replace(inputs, enzyme_cost_usd_per_ton_waste=inputs.enzyme_cost_usd_per_ton_waste * 1.1),
            "assumptions": assumptions,
        },
        {
            "group": "Operational risk",
            "lever": "Direct labor",
            "change": "+10%",
            "inputs": replace(
                inputs,
                direct_labor_cost_usd_per_month=_labor_cost(inputs) * 1.1,
            ),
            "assumptions": assumptions,
        },
        {
            "group": "Operational risk",
            "lever": "Maintenance rate",
            "change": "+1 percentage point",
            "inputs": replace(
                inputs,
                maintenance_rate_annual=_clamp(inputs.maintenance_rate_annual + 0.01, 0.0, 0.2),
            ),
            "assumptions": assumptions,
        },
    ]

    records = []
    for scenario in scenarios:
        changed_inputs = scenario["inputs"]
        changed_assumptions = scenario["assumptions"]
        changed_unit = monthly_unit_economics(changed_inputs, machine)
        changed_economics = _stakeholder_economics(
            changed_inputs,
            changed_unit,
            changed_assumptions,
        )
        provider_delta = changed_economics["provider_net_profit"] - base_economics["provider_net_profit"]
        customer_delta = changed_economics["customer_net_saving"] - base_economics["customer_net_saving"]
        records.append(
            {
                "group": scenario["group"],
                "lever": scenario["lever"],
                "change": scenario["change"],
                "provider_impact": _format_signed_money(provider_delta),
                "customer_impact": _format_signed_money(customer_delta),
                "provider_impact_value": provider_delta,
                "customer_impact_value": customer_delta,
                "interpretation": _sensitivity_interpretation(provider_delta, customer_delta),
                "impact_score": abs(provider_delta) + abs(customer_delta),
            }
        )

    return (
        pd.DataFrame(records)
        .sort_values(["group", "impact_score"], ascending=[True, False])
        .reset_index(drop=True)
    )


def _monthly_value_split_table(economics: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "stakeholder": "Provider",
                "component": "Fertilizer revenue",
                "amount": economics["provider_fertilizer_revenue"],
                "net_result": economics["provider_net_profit"],
            },
            {
                "stakeholder": "Provider",
                "component": "Service fee",
                "amount": economics["provider_service_revenue"],
                "net_result": economics["provider_net_profit"],
            },
            {
                "stakeholder": "Provider",
                "component": "Rental",
                "amount": economics["provider_rental_revenue"],
                "net_result": economics["provider_net_profit"],
            },
            {
                "stakeholder": "Customer",
                "component": "Avoided disposal",
                "amount": economics["avoided_disposal_savings"],
                "net_result": economics["customer_net_saving"],
            },
            {
                "stakeholder": "Customer",
                "component": "Fertilizer revenue",
                "amount": economics["customer_fertilizer_revenue"],
                "net_result": economics["customer_net_saving"],
            },
        ]
    )


def _labor_cost(inputs: FeasibilityInputs) -> float:
    if inputs.direct_labor_cost_usd_per_month is not None:
        return inputs.direct_labor_cost_usd_per_month
    return inputs.labor_cost_usd_per_month


def _sensitivity_interpretation(provider_delta: float, customer_delta: float) -> str:
    if provider_delta > 0 and customer_delta < 0:
        return "Improves Provider but reduces customer value"
    if provider_delta < 0 and customer_delta > 0:
        return "Improves customer value but reduces Provider"
    if provider_delta > 0 and customer_delta > 0:
        return "Improves both sides"
    if provider_delta < 0 and customer_delta < 0:
        return "Weakens both sides"
    return "Limited impact under current case"


def _equipment_cost_to_recover(unit: dict[str, float | str]) -> float:
    """Return the visible machine cost after discount and grant support."""

    discounted_capex = float(unit["discounted_machine_capex"])
    grant = float(unit["grant_value"])
    return max(discounted_capex - grant, 0.0)


def _investment_recovery_timeline(
    inputs: FeasibilityInputs,
    equipment_cost_to_recover: float,
    customer_investment_share: float,
    provider_monthly_net_value: float,
    customer_monthly_net_value: float,
) -> pd.DataFrame:
    model_months = sum(inputs.cashflow_months) if inputs.cashflow_months else inputs.analysis_years * 12
    total_months = max(model_months, 20 * 12)
    customer_baseline = equipment_cost_to_recover * customer_investment_share
    provider_baseline = equipment_cost_to_recover * (1 - customer_investment_share)
    if customer_baseline > 0 and provider_baseline > 0:
        cost_owner = "Shared"
    elif customer_baseline > 0:
        cost_owner = "Customer"
    elif provider_baseline > 0:
        cost_owner = "Provider"
    else:
        cost_owner = "None"

    rows = []
    for month in range(0, total_months + 1):
        provider_cumulative = provider_monthly_net_value * month
        customer_cumulative = customer_monthly_net_value * month
        rows.append(
            {
                "month": month,
                "year": math.ceil(month / 12) if month else 0,
                "equipment_cost_to_recover": equipment_cost_to_recover,
                "machine_investment_baseline": equipment_cost_to_recover,
                "machine_cost_owner": cost_owner,
                "provider_machine_cost_baseline": provider_baseline,
                "customer_machine_cost_baseline": customer_baseline,
                "provider_cumulative_net_profit": provider_cumulative,
                "provider_break_even": provider_baseline > 0 and provider_cumulative >= provider_baseline,
                "customer_cumulative_net_saving": customer_cumulative,
                "customer_break_even": customer_baseline > 0 and customer_cumulative >= customer_baseline,
            }
        )
    return pd.DataFrame(rows)


def _format_break_even_year(timeline: pd.DataFrame, break_even_column: str) -> str:
    break_even_rows = timeline.loc[timeline[break_even_column]]
    if break_even_rows.empty:
        return "N/A"
    month = int(break_even_rows.iloc[0]["month"])
    if month <= 0:
        return "0.0 years"
    return f"{month / 12:,.1f} years"


def _format_money(value: float) -> str:
    if abs(value) < 0.5:
        return "$0"
    if value < 0:
        return f"-${abs(value):,.0f}"
    return f"${value:,.0f}"


def _format_signed_money(value: float) -> str:
    if abs(value) < 0.5:
        return "$0"
    if value < 0:
        return f"-${abs(value):,.0f}"
    return f"+${value:,.0f}"


def _format_percent(value: object) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:,.1f}%"


def _format_months(value: object) -> str:
    if value is None:
        return "N/A"
    return f"{int(value)} months"


def _revenue_table(unit: dict[str, float | str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"item": "Fertilizer revenue", "amount": float(unit["fertilizer_revenue"])},
            {"item": "Service revenue", "amount": float(unit["service_revenue"])},
        ]
    )


def _cost_table(unit: dict[str, float | str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"item": "Enzyme", "amount": float(unit["enzyme_cost"])},
            {"item": "Electricity", "amount": float(unit["electricity_cost"])},
            {"item": "Direct labor", "amount": float(unit["direct_labor_cost"])},
            {"item": "Maintenance", "amount": float(unit["maintenance_cost"])},
            {"item": "Rental", "amount": float(unit["rental_cost"])},
            {"item": "Indirect labor", "amount": float(unit["indirect_labor_cost"])},
            {"item": "Other operating cost", "amount": float(unit["other_cost"])},
            {"item": "Loan interest", "amount": float(unit["loan_interest_expense"])},
            {"item": "Tax", "amount": float(unit["tax_expense"])},
        ]
    )


def _optional_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)
