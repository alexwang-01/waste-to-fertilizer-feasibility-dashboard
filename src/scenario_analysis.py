"""Scenario utilities for the feasibility model."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from .financial_model import FeasibilityInputs, choose_machine, summarize_feasibility


def load_scenarios(path: str | Path) -> pd.DataFrame:
    """Load scenario defaults from CSV."""

    return pd.read_csv(path)


def inputs_from_scenario(row: pd.Series, business_model: str = "capex") -> FeasibilityInputs:
    """Build model inputs from one scenario_defaults.csv row."""

    return FeasibilityInputs(
        business_model=business_model,
        waste_tons_per_day=float(row["waste_tons_per_day"]),
        collection_rate=float(row["collection_rate"]),
        days_per_month=int(row["days_per_month"]),
        conversion_rate=float(row.get("conversion_rate", 0.70)),
        fertilizer_price_usd_per_ton=float(row["fertilizer_price_usd_per_ton"]),
        service_fee_usd_per_ton=float(row["service_fee_usd_per_ton"]),
        electricity_rate_usd_per_kwh=float(row["electricity_rate_usd_per_kwh"]),
        electricity_load_factor=_optional_float(row, "electricity_load_factor", 1.0),
        enzyme_cost_usd_per_ton_waste=float(row["enzyme_cost_usd_per_ton_waste"]),
        direct_labor_cost_usd_per_month=_optional_float(row, "direct_labor_cost_usd_per_month", None),
        indirect_labor_cost_usd_per_month=_optional_float(row, "indirect_labor_cost_usd_per_month", 0.0),
        labor_cost_usd_per_month=float(row.get("labor_cost_usd_per_month", 0.0)),
        maintenance_rate_annual=_optional_float(row, "maintenance_rate_annual", 0.05),
        maintenance_cost_usd_per_month=_optional_float(row, "maintenance_cost_usd_per_month", None),
        machine_discount_rate=float(row["machine_discount_rate"]),
        rental_discount_rate=_optional_float(row, "rental_discount_rate", 0.0),
        grant_rate=float(row["grant_rate"]),
        down_payment_rate=_optional_float(row, "down_payment_rate", 0.0),
        loan_interest_expense_usd_per_month=_optional_float(row, "loan_interest_expense_usd_per_month", 0.0),
        tax_rate=_optional_float(row, "tax_rate", 0.0),
        initial_investment_basis=str(row.get("initial_investment_basis", "net_capex_after_grant")),
        roi_denominator_basis=str(row.get("roi_denominator_basis", "initial_investment")),
        cashflow_months=_optional_month_tuple(row, "cashflow_months"),
    )


def run_scenarios(machine_specs: pd.DataFrame, scenarios: pd.DataFrame, business_model: str = "capex") -> pd.DataFrame:
    """Evaluate all scenarios and return a tidy results table."""

    records = []
    for _, row in scenarios.iterrows():
        inputs = inputs_from_scenario(row, business_model=business_model)
        machine = choose_machine(machine_specs, inputs.waste_tons_per_day)
        result = summarize_feasibility(inputs, machine)
        result["scenario"] = row["scenario"]
        records.append(result)
    return pd.DataFrame(records)


def apply_conversion_rate(inputs: FeasibilityInputs, conversion_rate: float) -> FeasibilityInputs:
    """Return a copy of inputs with a different conversion rate."""

    return replace(inputs, conversion_rate=conversion_rate)


def _optional_float(row: pd.Series, column: str, default: float | None) -> float | None:
    if column not in row.index:
        return default
    value = row[column]
    if pd.isna(value) or value == "":
        return default
    return float(value)


def _optional_month_tuple(row: pd.Series, column: str) -> tuple[int, ...] | None:
    if column not in row.index:
        return None
    value = row[column]
    if pd.isna(value) or value == "":
        return None
    return tuple(int(part.strip()) for part in str(value).split(";") if part.strip())
