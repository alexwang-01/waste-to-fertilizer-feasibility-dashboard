"""Core financial logic for waste-to-fertilizer feasibility analysis.

The module intentionally uses explicit formulas instead of hidden spreadsheet
logic. It is designed for early-stage decision support, not prediction.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MachineSpec:
    """Waste-to-Fertilizer machine specification used by the model."""

    model: str
    capacity_ton: float
    total_load_kw: float
    operation_hours_per_day: float
    asia_price_no_ce_usd: float
    asia_price_with_ce_usd: float | None = None
    europe_price_with_ce_usd: float | None = None
    monthly_rental_ratio: float = 0.0065

    @property
    def monthly_rental_no_ce_usd(self) -> float:
        return self.asia_price_no_ce_usd * self.monthly_rental_ratio


@dataclass(frozen=True)
class MachineFleetItem:
    """One machine model and quantity inside a manual fleet setup."""

    model: str
    quantity: int
    capacity_ton: float
    total_load_kw: float
    operation_hours_per_day: float
    asia_price_no_ce_usd: float
    monthly_rental_ratio: float = 0.0065

    @property
    def monthly_rental_no_ce_usd(self) -> float:
        return self.asia_price_no_ce_usd * self.monthly_rental_ratio


@dataclass(frozen=True)
class FeasibilityInputs:
    """Inputs for a single customer feasibility scenario."""

    business_model: str = "capex"
    waste_tons_per_day: float = 40.0
    collection_rate: float = 0.85
    days_per_month: int = 26
    conversion_rate: float = 0.70
    fertilizer_price_usd_per_ton: float = 250.0
    fertilizer_sales_completion_rate: float = 1.0
    service_fee_usd_per_ton: float = 50.0
    electricity_rate_usd_per_kwh: float = 0.2033
    electricity_load_factor: float = 1.0
    enzyme_cost_usd_per_ton_waste: float = 15.0
    direct_labor_cost_usd_per_month: float | None = None
    indirect_labor_cost_usd_per_month: float = 0.0
    labor_cost_usd_per_month: float = 10_000.0
    other_cost_usd_per_month: float = 0.0
    maintenance_rate_annual: float = 0.05
    maintenance_cost_usd_per_month: float | None = None
    machine_discount_rate: float = 0.20
    rental_discount_rate: float = 0.0
    grant_rate: float = 0.10
    down_payment_rate: float = 0.0
    loan_interest_expense_usd_per_month: float = 0.0
    tax_rate: float = 0.0
    initial_investment_basis: str = "net_capex_after_grant"
    roi_denominator_basis: str = "initial_investment"
    analysis_years: int = 10
    cashflow_months: tuple[int, ...] | None = None
    machine_quantity_override: int | None = None
    machine_fleet: tuple[MachineFleetItem, ...] | None = None


def load_machine_specs(path: str) -> pd.DataFrame:
    """Load machine specs and coerce numeric columns."""

    df = pd.read_csv(path)
    numeric_cols = [
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
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def choose_machine(machine_specs: pd.DataFrame, required_tons_per_day: float) -> MachineSpec:
    """Choose the smallest machine whose nominal capacity covers daily waste.

    This is a first-pass assumption. The original materials should be reviewed
    to confirm whether capacity_ton represents daily throughput, batch capacity,
    or a sales sizing proxy.
    """

    if required_tons_per_day <= 0:
        raise ValueError("required_tons_per_day must be positive")

    specs = machine_specs.sort_values("capacity_ton")
    eligible = specs[specs["capacity_ton"] >= required_tons_per_day]
    row = eligible.iloc[0] if not eligible.empty else specs.iloc[-1]

    return MachineSpec(
        model=str(row["model"]),
        capacity_ton=float(row["capacity_ton"]),
        total_load_kw=float(row["total_load_kw"]),
        operation_hours_per_day=float(row["operation_hours_per_day"]),
        asia_price_no_ce_usd=float(row["asia_price_no_ce_usd"]),
        asia_price_with_ce_usd=_nullable_float(row.get("asia_price_with_ce_usd")),
        europe_price_with_ce_usd=_nullable_float(row.get("europe_price_with_ce_usd")),
        monthly_rental_ratio=float(row.get("monthly_rental_ratio", 0.0065)),
    )


def machine_count(required_tons_per_day: float, machine: MachineSpec) -> int:
    """Return the number of machines required to cover daily waste volume."""

    return max(1, math.ceil(required_tons_per_day / machine.capacity_ton))


def scenario_machine_count(inputs: FeasibilityInputs, machine: MachineSpec) -> int:
    """Return machine count using an explicit manual override when provided."""

    if inputs.machine_fleet is not None:
        return sum(item.quantity for item in inputs.machine_fleet)
    if inputs.machine_quantity_override is not None:
        return max(1, int(inputs.machine_quantity_override))
    return machine_count(inputs.waste_tons_per_day, machine)


def monthly_unit_economics(inputs: FeasibilityInputs, machine: MachineSpec) -> dict[str, float | int | str | bool]:
    """Calculate monthly economics for one customer scenario."""

    fleet = _fleet_for_inputs(inputs, machine)
    count = sum(item.quantity for item in fleet)
    machine_capacity_tons_per_day = sum(item.capacity_ton * item.quantity for item in fleet)
    monthly_waste_tons = inputs.waste_tons_per_day * inputs.collection_rate * inputs.days_per_month
    monthly_fertilizer_tons = monthly_waste_tons * inputs.conversion_rate

    fertilizer_revenue = (
        monthly_fertilizer_tons
        * inputs.fertilizer_price_usd_per_ton
        * inputs.fertilizer_sales_completion_rate
    )
    service_revenue = monthly_waste_tons * inputs.service_fee_usd_per_ton
    monthly_revenue = fertilizer_revenue + service_revenue

    enzyme_cost = monthly_waste_tons * inputs.enzyme_cost_usd_per_ton_waste
    electricity_cost = (
        sum(
            item.quantity * item.total_load_kw * item.operation_hours_per_day
            for item in fleet
        )
        * inputs.days_per_month
        * inputs.electricity_rate_usd_per_kwh
        * inputs.electricity_load_factor
    )

    gross_machine_capex = sum(item.asia_price_no_ce_usd * item.quantity for item in fleet)
    discounted_machine_capex = gross_machine_capex * (1 - inputs.machine_discount_rate)
    if inputs.maintenance_cost_usd_per_month is None:
        maintenance_cost = discounted_machine_capex * inputs.maintenance_rate_annual / 12
    else:
        maintenance_cost = inputs.maintenance_cost_usd_per_month

    rental_cost = 0.0
    if inputs.business_model.lower() == "opex":
        rental_cost = (
            sum(item.monthly_rental_no_ce_usd * item.quantity for item in fleet)
            * (1 - inputs.rental_discount_rate)
        )

    direct_labor_cost = (
        inputs.labor_cost_usd_per_month
        if inputs.direct_labor_cost_usd_per_month is None
        else inputs.direct_labor_cost_usd_per_month
    )
    cogs = enzyme_cost + direct_labor_cost + electricity_cost + maintenance_cost
    operating_expenses = rental_cost + inputs.indirect_labor_cost_usd_per_month + inputs.other_cost_usd_per_month
    gross_profit = monthly_revenue - cogs
    operating_profit = gross_profit - operating_expenses
    tax_expense = max(operating_profit, 0.0) * inputs.tax_rate
    non_operating_expenses = inputs.loan_interest_expense_usd_per_month + tax_expense
    monthly_operating_cost = (
        cogs
        + operating_expenses
        + non_operating_expenses
    )
    monthly_accounting_profit = operating_profit - non_operating_expenses
    monthly_cash_flow = monthly_revenue - monthly_operating_cost

    return {
        "business_model": inputs.business_model.lower(),
        "machine_model": _fleet_label(fleet),
        "machine_count": count,
        "machine_capacity_tons_per_day": machine_capacity_tons_per_day,
        "machine_capacity_sufficient": machine_capacity_tons_per_day >= inputs.waste_tons_per_day,
        "machine_utilization": (
            inputs.waste_tons_per_day / machine_capacity_tons_per_day
            if machine_capacity_tons_per_day > 0
            else None
        ),
        "monthly_waste_tons": monthly_waste_tons,
        "monthly_fertilizer_tons": monthly_fertilizer_tons,
        "fertilizer_revenue": fertilizer_revenue,
        "service_revenue": service_revenue,
        "monthly_revenue": monthly_revenue,
        "enzyme_cost": enzyme_cost,
        "electricity_cost": electricity_cost,
        "direct_labor_cost": direct_labor_cost,
        "labor_cost": direct_labor_cost,
        "maintenance_cost": maintenance_cost,
        "rental_cost": rental_cost,
        "indirect_labor_cost": inputs.indirect_labor_cost_usd_per_month,
        "other_cost": inputs.other_cost_usd_per_month,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "operating_expenses": operating_expenses,
        "operating_profit": operating_profit,
        "non_operating_expenses": non_operating_expenses,
        "loan_interest_expense": inputs.loan_interest_expense_usd_per_month,
        "tax_expense": tax_expense,
        "monthly_operating_cost": monthly_operating_cost,
        "monthly_accounting_profit": monthly_accounting_profit,
        "monthly_cash_flow": monthly_cash_flow,
        "gross_machine_capex": gross_machine_capex,
        "discounted_machine_capex": discounted_machine_capex,
        "grant_value": discounted_machine_capex * inputs.grant_rate,
        "down_payment": discounted_machine_capex * inputs.down_payment_rate,
    }


def initial_investment(inputs: FeasibilityInputs, machine: MachineSpec) -> float:
    """Calculate upfront investment for CapEx scenarios."""

    if inputs.business_model.lower() != "capex":
        return 0.0
    fleet = _fleet_for_inputs(inputs, machine)
    gross = sum(item.asia_price_no_ce_usd * item.quantity for item in fleet)
    discounted = gross * (1 - inputs.machine_discount_rate)
    grant = discounted * inputs.grant_rate
    down_payment = discounted * inputs.down_payment_rate

    if inputs.initial_investment_basis == "excel_financed_principal":
        return max(discounted - grant - down_payment, 0.0)
    if inputs.initial_investment_basis == "down_payment_only":
        return down_payment
    if inputs.initial_investment_basis != "net_capex_after_grant":
        raise ValueError(
            "initial_investment_basis must be one of: "
            "net_capex_after_grant, excel_financed_principal, down_payment_only"
        )
    return discounted - grant


def annual_cashflows(inputs: FeasibilityInputs, machine: MachineSpec) -> list[float]:
    """Return year 0 plus annual operating cash flows."""

    unit = monthly_unit_economics(inputs, machine)
    year_0 = -initial_investment(inputs, machine)
    monthly_operating_cash_flow = float(unit["monthly_cash_flow"])
    months = inputs.cashflow_months or tuple([12] * inputs.analysis_years)
    return [year_0] + [monthly_operating_cash_flow * month_count for month_count in months]


def payback_months(cashflows: Iterable[float]) -> int | None:
    """Return first month where cumulative cash flow becomes non-negative."""

    flows = list(cashflows)
    if not flows:
        return None

    cumulative = flows[0]
    if cumulative >= 0:
        return 0

    monthly_flow = flows[1] / 12 if len(flows) > 1 else 0
    if monthly_flow <= 0:
        return None

    return math.ceil(abs(cumulative) / monthly_flow)


def roi(cashflows: Iterable[float]) -> float | None:
    """Return ROI over the analysis horizon."""

    flows = list(cashflows)
    if not flows or flows[0] >= 0:
        return None
    return sum(flows) / abs(flows[0])


def irr(cashflows: Iterable[float], low: float = -0.95, high: float = 2.0) -> float | None:
    """Estimate annual IRR using bisection."""

    flows = list(cashflows)
    if not any(v < 0 for v in flows) or not any(v > 0 for v in flows):
        return None

    def npv(rate: float) -> float:
        return sum(value / ((1 + rate) ** period) for period, value in enumerate(flows))

    low_value = npv(low)
    high_value = npv(high)
    if low_value * high_value > 0:
        return None

    for _ in range(200):
        mid = (low + high) / 2
        mid_value = npv(mid)
        if abs(mid_value) < 1e-6:
            return mid
        if low_value * mid_value <= 0:
            high = mid
            high_value = mid_value
        else:
            low = mid
            low_value = mid_value
    return (low + high) / 2


def summarize_feasibility(inputs: FeasibilityInputs, machine: MachineSpec) -> dict[str, float | int | str | None]:
    """Return core monthly economics and investment metrics."""

    unit = monthly_unit_economics(inputs, machine)
    flows = annual_cashflows(inputs, machine)
    initial = initial_investment(inputs, machine)
    payback = _payback_months_from_monthly(initial, float(unit["monthly_cash_flow"]))
    roi_denominator = _roi_denominator(inputs, unit, initial)
    roi_value = None if roi_denominator <= 0 else sum(flows) / roi_denominator

    return {
        **unit,
        "initial_investment": initial,
        "roi_denominator": roi_denominator,
        "annual_cash_flow": flows[1] if len(flows) > 1 else None,
        "payback_months": payback,
        "payback_years": None if payback is None else payback / 12,
        "roi": roi_value,
        "irr": irr(flows),
    }


def _roi_denominator(inputs: FeasibilityInputs, unit: dict[str, float | str], initial: float) -> float:
    if inputs.roi_denominator_basis == "discounted_machine_capex":
        return float(unit["discounted_machine_capex"])
    if inputs.roi_denominator_basis == "initial_investment":
        return initial
    raise ValueError(
        "roi_denominator_basis must be one of: "
        "initial_investment, discounted_machine_capex"
    )


def _payback_months_from_monthly(initial: float, monthly_cash_flow: float) -> int | None:
    if initial <= 0:
        return 0
    if monthly_cash_flow <= 0:
        return None
    return math.ceil(initial / monthly_cash_flow)


def _fleet_for_inputs(inputs: FeasibilityInputs, machine: MachineSpec) -> tuple[MachineFleetItem, ...]:
    if inputs.machine_fleet is not None:
        return tuple(
            item
            for item in inputs.machine_fleet
            if item.quantity > 0
        )
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


def _fleet_label(fleet: tuple[MachineFleetItem, ...]) -> str:
    return " + ".join(f"{item.quantity} x {item.model}" for item in fleet)


def _nullable_float(value: object) -> float | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
