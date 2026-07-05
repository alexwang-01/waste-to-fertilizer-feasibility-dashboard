from pathlib import Path

from src.dashboard_service import (
    calculate_dashboard_result,
    load_dashboard_data,
    select_machine,
    view_assumptions_from_row,
)
from src.financial_model import (
    FeasibilityInputs,
    MachineFleetItem,
    MachineSpec,
    choose_machine,
    load_machine_specs,
    summarize_feasibility,
)
from src.view_model import ViewAssumptions, build_views, views_to_records


ROOT = Path(__file__).resolve().parents[1]


def test_base_capex_scenario_produces_positive_monthly_cash_flow():
    specs = load_machine_specs(ROOT / "data" / "processed" / "machine_specs.csv")
    inputs = FeasibilityInputs(
        business_model="capex",
        waste_tons_per_day=40,
        collection_rate=0.85,
        days_per_month=26,
        conversion_rate=0.70,
        fertilizer_price_usd_per_ton=250,
        service_fee_usd_per_ton=50,
        electricity_rate_usd_per_kwh=0.2033,
    )
    machine = choose_machine(specs, inputs.waste_tons_per_day)
    result = summarize_feasibility(inputs, machine)

    assert result["machine_count"] >= 1
    assert result["monthly_waste_tons"] > 0
    assert result["monthly_revenue"] > 0
    assert result["monthly_cash_flow"] > 0


def test_irr_is_none_when_opex_has_no_initial_investment():
    specs = load_machine_specs(ROOT / "data" / "processed" / "machine_specs.csv")
    inputs = FeasibilityInputs(business_model="opex", waste_tons_per_day=20)
    machine = choose_machine(specs, inputs.waste_tons_per_day)
    result = summarize_feasibility(inputs, machine)

    assert result["initial_investment"] == 0
    assert result["irr"] is None


def test_capex_v1_can_reconcile_excel_benchmark_outputs():
    specs = load_machine_specs(ROOT / "data" / "processed" / "machine_specs.csv")
    machine = _machine_by_capacity(specs, 100)
    inputs = FeasibilityInputs(
        business_model="capex",
        waste_tons_per_day=100,
        collection_rate=1,
        days_per_month=30,
        conversion_rate=0.3,
        fertilizer_price_usd_per_ton=300,
        service_fee_usd_per_ton=50,
        electricity_rate_usd_per_kwh=0.2033,
        electricity_load_factor=0.31972454500737824,
        enzyme_cost_usd_per_ton_waste=15,
        direct_labor_cost_usd_per_month=2800,
        indirect_labor_cost_usd_per_month=18800,
        maintenance_cost_usd_per_month=4000,
        machine_discount_rate=0.55,
        grant_rate=0.10,
        down_payment_rate=0.10,
        loan_interest_expense_usd_per_month=73718.8681329931,
        initial_investment_basis="excel_financed_principal",
        roi_denominator_basis="discounted_machine_capex",
        cashflow_months=(4, 12, 12, 12, 12, 12, 12, 12, 12, 12, 8),
    )
    result = summarize_feasibility(inputs, machine)

    assert round(result["monthly_revenue"], 2) == 420000
    assert round(result["monthly_accounting_profit"], 2) == 257897.13
    assert round(result["initial_investment"], 2) == 8415000
    assert result["payback_months"] == 33
    assert round(result["roi"], 4) == 2.1421
    assert round(result["irr"], 4) == 0.2880


def test_opex_v1_can_reconcile_excel_benchmark_outputs():
    specs = load_machine_specs(ROOT / "data" / "processed" / "machine_specs.csv")
    machine = _machine_by_capacity(specs, 60)
    inputs = FeasibilityInputs(
        business_model="opex",
        waste_tons_per_day=100,
        collection_rate=1,
        days_per_month=30,
        conversion_rate=0.7,
        fertilizer_price_usd_per_ton=250,
        service_fee_usd_per_ton=0,
        electricity_rate_usd_per_kwh=0.2033,
        electricity_load_factor=0.34431874077717656,
        enzyme_cost_usd_per_ton_waste=0,
        direct_labor_cost_usd_per_month=0,
        maintenance_cost_usd_per_month=0,
        tax_rate=0.10,
        cashflow_months=(4, 12, 12, 12, 12, 12, 12, 12, 12, 12, 8),
    )
    result = summarize_feasibility(inputs, machine)

    assert round(result["monthly_revenue"], 2) == 525000
    assert round(result["electricity_cost"], 2) == 26611.2
    assert round(result["rental_cost"], 2) == 181350
    assert round(result["tax_expense"], 2) == 31703.88
    assert round(result["monthly_accounting_profit"], 2) == 285334.92
    assert result["initial_investment"] == 0
    assert result["roi"] is None
    assert result["irr"] is None


def test_manual_machine_quantity_override_flags_insufficient_capacity():
    specs = load_machine_specs(ROOT / "data" / "processed" / "machine_specs.csv")
    machine = _machine_by_capacity(specs, 60)
    inputs = FeasibilityInputs(
        business_model="capex",
        waste_tons_per_day=100,
        machine_quantity_override=1,
    )
    result = summarize_feasibility(inputs, machine)

    assert result["machine_count"] == 1
    assert result["machine_capacity_tons_per_day"] == 60
    assert result["machine_capacity_sufficient"] is False


def test_manual_machine_fleet_supports_mixed_models():
    specs = load_machine_specs(ROOT / "data" / "processed" / "machine_specs.csv")
    machine = _machine_by_capacity(specs, 60)
    fleet = (
        _fleet_item_by_capacity(specs, 40, 1),
        _fleet_item_by_capacity(specs, 20, 2),
    )
    inputs = FeasibilityInputs(
        business_model="opex",
        waste_tons_per_day=75,
        machine_fleet=fleet,
    )
    result = summarize_feasibility(inputs, machine)

    assert result["machine_count"] == 3
    assert result["machine_model"] == "1 x 80000 L + 2 x 40000 L"
    assert result["machine_capacity_tons_per_day"] == 80
    assert result["machine_capacity_sufficient"] is True
    assert round(result["machine_utilization"], 4) == 0.9375
    assert result["gross_machine_capex"] > 0
    assert result["rental_cost"] > 0


def test_view_model_splits_project_provider_and_customer_views():
    specs = load_machine_specs(ROOT / "data" / "processed" / "machine_specs.csv")
    machine = _machine_by_capacity(specs, 60)
    inputs = FeasibilityInputs(
        business_model="opex",
        waste_tons_per_day=100,
        collection_rate=1,
        days_per_month=30,
        conversion_rate=0.7,
        fertilizer_price_usd_per_ton=250,
        service_fee_usd_per_ton=0,
        electricity_rate_usd_per_kwh=0.2033,
        electricity_load_factor=0.34431874077717656,
        enzyme_cost_usd_per_ton_waste=0,
        direct_labor_cost_usd_per_month=0,
        maintenance_cost_usd_per_month=0,
        tax_rate=0.10,
    )
    assumptions = ViewAssumptions(
        current_disposal_fee_usd_per_ton=70,
        provider_fertilizer_revenue_share=0.5,
        provider_rental_revenue_share=1.0,
        provider_cogs_share=0.0,
        provider_non_rental_opex_share=0.0,
        provider_non_operating_expense_share=0.0,
        customer_initial_investment_share=0.0,
    )

    views = build_views(inputs, machine, assumptions)
    records = views_to_records(views)

    assert set(views) == {"project", "provider", "customer"}
    assert len(records) == 3
    assert views["project"].monthly_net_value > 0
    assert views["provider"].monthly_revenue_or_benefit > 0
    assert views["customer"].monthly_revenue_or_benefit > 0


def test_dashboard_service_loads_data_and_calculates_tables():
    data = load_dashboard_data(ROOT)
    scenario_row = data["scenarios"].loc[data["scenarios"]["scenario"].eq("base")].iloc[0]
    view_row = data["view_assumptions"].loc[
        data["view_assumptions"]["scenario"].eq("opex_provider_rental")
    ].iloc[0]
    inputs = FeasibilityInputs(
        business_model="opex",
        waste_tons_per_day=float(scenario_row["waste_tons_per_day"]),
        collection_rate=float(scenario_row["collection_rate"]),
        days_per_month=int(scenario_row["days_per_month"]),
        fertilizer_price_usd_per_ton=float(scenario_row["fertilizer_price_usd_per_ton"]),
        service_fee_usd_per_ton=float(scenario_row["service_fee_usd_per_ton"]),
        electricity_rate_usd_per_kwh=float(scenario_row["electricity_rate_usd_per_kwh"]),
        enzyme_cost_usd_per_ton_waste=float(scenario_row["enzyme_cost_usd_per_ton_waste"]),
        labor_cost_usd_per_month=float(scenario_row["labor_cost_usd_per_month"]),
        machine_discount_rate=float(scenario_row["machine_discount_rate"]),
        grant_rate=float(scenario_row["grant_rate"]),
    )
    machine = select_machine(data["machine_specs"], inputs)
    assumptions = view_assumptions_from_row(view_row)
    result = calculate_dashboard_result(inputs, machine, assumptions)

    assert set(result) == {
        "summary",
        "unit",
        "deal_summary",
        "provider_statement",
        "customer_statement",
        "provider_report",
        "customer_report",
        "provider_investment_metrics",
        "customer_investment_metrics",
        "provider_returns",
        "customer_returns",
        "investment_recovery_timeline",
        "break_even_timeline",
        "sensitivity",
        "provider_sensitivity",
        "customer_sensitivity",
        "monthly_value_split",
        "view_table",
        "revenue_table",
        "cost_table",
    }
    assert result["summary"]["monthly_revenue"] > 0
    assert result["deal_summary"]["status"]
    assert len(result["provider_statement"]) > 0
    assert len(result["customer_statement"]) > 0
    assert len(result["provider_report"]) == len(result["customer_report"])
    assert "Provider monthly net profit" in result["provider_report"]["line_item"].to_list()
    assert "Customer monthly net saving" in result["customer_report"]["line_item"].to_list()
    assert "Initial investment" in result["provider_investment_metrics"]["metric"].to_list()
    assert "Initial investment" in result["customer_investment_metrics"]["metric"].to_list()
    assert "Equipment cost to recover" not in result["provider_investment_metrics"]["metric"].to_list()
    assert "Payback / break-even" in result["provider_investment_metrics"]["metric"].to_list()
    assert "roi" in result["provider_returns"]
    assert "roi" in result["customer_returns"]
    assert len(result["investment_recovery_timeline"]) == 241
    assert {
        "month",
        "equipment_cost_to_recover",
        "provider_cumulative_net_profit",
        "customer_cumulative_net_saving",
    }.issubset(
        result["investment_recovery_timeline"].columns
    )
    assert result["investment_recovery_timeline"]["year"].max() == 20
    assert result["investment_recovery_timeline"]["equipment_cost_to_recover"].iloc[0] > 0
    assert {"lever", "provider_impact", "customer_impact", "interpretation"}.issubset(
        result["sensitivity"].columns
    )
    assert {"provider_impact_value", "customer_impact_value", "impact_score"}.issubset(
        result["sensitivity"].columns
    )
    assert len(result["sensitivity"]) > 0
    assert {"stakeholder", "component", "amount", "net_result"}.issubset(
        result["monthly_value_split"].columns
    )
    assert len(result["monthly_value_split"]) > 0
    assert len(result["view_table"]) == 3
    assert result["revenue_table"]["amount"].sum() > 0
    assert result["cost_table"]["amount"].sum() > 0


def _machine_by_capacity(specs, capacity_ton: float) -> MachineSpec:
    row = specs.loc[specs["capacity_ton"].eq(capacity_ton)].iloc[0]
    return MachineSpec(
        model=str(row["model"]),
        capacity_ton=float(row["capacity_ton"]),
        total_load_kw=float(row["total_load_kw"]),
        operation_hours_per_day=float(row["operation_hours_per_day"]),
        asia_price_no_ce_usd=float(row["asia_price_no_ce_usd"]),
        monthly_rental_ratio=float(row["monthly_rental_ratio"]),
    )


def _fleet_item_by_capacity(specs, capacity_ton: float, quantity: int) -> MachineFleetItem:
    row = specs.loc[specs["capacity_ton"].eq(capacity_ton)].iloc[0]
    return MachineFleetItem(
        model=str(row["model"]),
        quantity=quantity,
        capacity_ton=float(row["capacity_ton"]),
        total_load_kw=float(row["total_load_kw"]),
        operation_hours_per_day=float(row["operation_hours_per_day"]),
        asia_price_no_ce_usd=float(row["asia_price_no_ce_usd"]),
        monthly_rental_ratio=float(row["monthly_rental_ratio"]),
    )
