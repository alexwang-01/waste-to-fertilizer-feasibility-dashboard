"""Run broad dashboard input QA cases.

This script checks that common and edge-case deal inputs can be calculated
without runtime failures. It is not a replacement for accounting review.
"""

from __future__ import annotations

from dataclasses import replace
from math import isfinite
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dashboard_service import (
    calculate_dashboard_result,
    load_dashboard_data,
    select_machine,
    view_assumptions_from_row,
)
from src.financial_model import MachineFleetItem
from src.scenario_analysis import inputs_from_scenario


def main() -> None:
    data = load_dashboard_data(ROOT)
    scenarios = data["scenarios"]
    view_presets = data["view_assumptions"]
    machine_specs = data["machine_specs"]
    base_row = scenarios.loc[scenarios["scenario"].eq("base")].iloc[0]

    cases = []
    for name, business_model, view_name, customer_share in [
        ("capex_customer_owned", "capex", "capex_customer_owned", 1.0),
        ("opex_provider_owned", "opex", "opex_provider_rental", 0.0),
        ("co_investment_50_50", "capex", "capex_customer_owned", 0.5),
    ]:
        base_inputs = inputs_from_scenario(base_row, business_model=business_model)
        view_row = view_presets.loc[view_presets["scenario"].eq(view_name)].iloc[0]
        assumptions = replace(
            view_assumptions_from_row(view_row),
            customer_initial_investment_share=customer_share,
        )
        cases.append((name, base_inputs, assumptions))

    base_inputs = inputs_from_scenario(base_row, business_model="opex")
    base_assumptions = replace(
        view_assumptions_from_row(
            view_presets.loc[view_presets["scenario"].eq("opex_provider_rental")].iloc[0]
        ),
        customer_initial_investment_share=0.0,
    )
    cases.extend(
        [
            (
                "manual_fleet_sufficient",
                replace(
                    base_inputs,
                    machine_fleet=(
                        _fleet_item(machine_specs, "80000 L", 1),
                        _fleet_item(machine_specs, "40000 L", 1),
                    ),
                ),
                base_assumptions,
            ),
            (
                "manual_fleet_insufficient",
                replace(
                    base_inputs,
                    machine_fleet=(_fleet_item(machine_specs, "200 L", 1),),
                ),
                base_assumptions,
            ),
            (
                "manual_fleet_oversized",
                replace(
                    base_inputs,
                    machine_fleet=(_fleet_item(machine_specs, "200000 L", 2),),
                ),
                base_assumptions,
            ),
        ]
    )

    stress_inputs = {
        "waste_min": replace(base_inputs, waste_tons_per_day=0.1),
        "waste_large": replace(base_inputs, waste_tons_per_day=200),
        "collection_zero": replace(base_inputs, collection_rate=0.0),
        "collection_full": replace(base_inputs, collection_rate=1.0),
        "days_min": replace(base_inputs, days_per_month=1),
        "days_max": replace(base_inputs, days_per_month=31),
        "conversion_zero": replace(base_inputs, conversion_rate=0.0),
        "conversion_full": replace(base_inputs, conversion_rate=1.0),
        "sales_zero": replace(base_inputs, fertilizer_sales_completion_rate=0.0),
        "sales_full": replace(base_inputs, fertilizer_sales_completion_rate=1.0),
        "fertilizer_price_zero": replace(base_inputs, fertilizer_price_usd_per_ton=0.0),
        "service_fee_zero": replace(base_inputs, service_fee_usd_per_ton=0.0),
        "electricity_high": replace(base_inputs, electricity_rate_usd_per_kwh=0.5),
        "enzyme_high": replace(base_inputs, enzyme_cost_usd_per_ton_waste=50.0),
        "labor_high": replace(base_inputs, direct_labor_cost_usd_per_month=50_000.0),
        "maintenance_max": replace(base_inputs, maintenance_rate_annual=0.20),
        "tax_max": replace(base_inputs, tax_rate=0.50),
        "loan_high": replace(base_inputs, loan_interest_expense_usd_per_month=50_000.0),
        "discount_max": replace(base_inputs, machine_discount_rate=0.80),
        "grant_max": replace(base_inputs, grant_rate=0.80),
        "rental_discount_max": replace(base_inputs, rental_discount_rate=0.80),
    }
    for name, inputs in stress_inputs.items():
        cases.append((name, inputs, base_assumptions))

    for name, share in [
        ("fertilizer_share_zero", 0.0),
        ("fertilizer_share_full", 1.0),
        ("customer_equipment_share_zero", 0.0),
        ("customer_equipment_share_full", 1.0),
    ]:
        field = (
            "provider_fertilizer_revenue_share"
            if "fertilizer" in name
            else "customer_initial_investment_share"
        )
        cases.append((name, base_inputs, replace(base_assumptions, **{field: share})))

    issues = []
    for name, inputs, assumptions in cases:
        try:
            machine = select_machine(machine_specs, inputs)
            result = calculate_dashboard_result(inputs, machine, assumptions)
            _validate_result(name, result, issues)
        except Exception as exc:  # pragma: no cover - diagnostic script
            issues.append(f"{name}: runtime error: {exc}")

    print(f"QA cases run: {len(cases)}")
    if issues:
        print("Issues:")
        for issue in issues:
            print(f"- {issue}")
    else:
        print("Issues: none found")


def _fleet_item(machine_specs, model: str, quantity: int) -> MachineFleetItem:
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


def _validate_result(name: str, result: dict[str, object], issues: list[str]) -> None:
    required_keys = [
        "deal_summary",
        "provider_report",
        "customer_report",
        "provider_investment_metrics",
        "customer_investment_metrics",
        "sensitivity",
        "provider_sensitivity",
        "customer_sensitivity",
        "monthly_value_split",
        "investment_recovery_timeline",
    ]
    for key in required_keys:
        if key not in result:
            issues.append(f"{name}: missing result key {key}")

    deal_summary = result["deal_summary"]
    for key in [
        "equipment_cost_to_recover",
        "machine_capacity_tons_per_day",
        "provider_monthly_net_profit",
        "customer_monthly_net_saving",
    ]:
        value = float(deal_summary[key])
        if not isfinite(value):
            issues.append(f"{name}: non-finite {key}")

    if len(result["provider_report"]) != len(result["customer_report"]):
        issues.append(f"{name}: Provider and customer report row counts differ")
    if result["investment_recovery_timeline"]["year"].max() != 20:
        issues.append(f"{name}: investment timeline does not show 20 years")
    if result["sensitivity"].empty:
        issues.append(f"{name}: sensitivity table is empty")
    if result["monthly_value_split"].empty:
        issues.append(f"{name}: monthly value split table is empty")


if __name__ == "__main__":
    main()
