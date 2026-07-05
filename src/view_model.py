"""View allocation layer for project, Provider, and customer economics.

This module does not replace the core feasibility model. It takes the explicit
project-level outputs and allocates revenues, costs, savings, and investment
between Provider and the customer based on visible assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .financial_model import FeasibilityInputs, MachineSpec, initial_investment, monthly_unit_economics


@dataclass(frozen=True)
class ViewAssumptions:
    """Assumptions used to split project economics into stakeholder views."""

    current_disposal_fee_usd_per_ton: float = 0.0
    provider_fertilizer_revenue_share: float = 1.0
    provider_service_fee_share: float = 1.0
    provider_rental_revenue_share: float = 1.0
    provider_cogs_share: float = 1.0
    provider_non_rental_opex_share: float = 1.0
    provider_non_operating_expense_share: float = 1.0
    customer_initial_investment_share: float = 1.0


@dataclass(frozen=True)
class ViewResult:
    """Monthly economics for one stakeholder view."""

    view: str
    monthly_revenue_or_benefit: float
    monthly_cost: float
    monthly_net_value: float
    initial_investment: float
    notes: str


def build_views(
    inputs: FeasibilityInputs,
    machine: MachineSpec,
    assumptions: ViewAssumptions,
) -> dict[str, ViewResult]:
    """Return project, Provider, and customer views for one scenario."""

    _validate_shares(assumptions)
    unit = monthly_unit_economics(inputs, machine)
    investment = initial_investment(inputs, machine)

    monthly_waste_tons = float(unit["monthly_waste_tons"])
    fertilizer_revenue = float(unit["fertilizer_revenue"])
    service_revenue = float(unit["service_revenue"])
    rental_cost = float(unit["rental_cost"])
    cogs = float(unit["cogs"])
    non_rental_opex = float(unit["operating_expenses"]) - rental_cost
    non_operating_expenses = float(unit["non_operating_expenses"])
    avoided_disposal_savings = monthly_waste_tons * assumptions.current_disposal_fee_usd_per_ton

    project_revenue = float(unit["monthly_revenue"])
    project_cost = float(unit["monthly_operating_cost"])
    project = ViewResult(
        view="project",
        monthly_revenue_or_benefit=project_revenue,
        monthly_cost=project_cost,
        monthly_net_value=float(unit["monthly_accounting_profit"]),
        initial_investment=investment,
        notes="Consolidated project view from the core feasibility model.",
    )

    provider_revenue = (
        fertilizer_revenue * assumptions.provider_fertilizer_revenue_share
        + service_revenue * assumptions.provider_service_fee_share
        + rental_cost * assumptions.provider_rental_revenue_share
    )
    provider_cost = (
        cogs * assumptions.provider_cogs_share
        + non_rental_opex * assumptions.provider_non_rental_opex_share
        + non_operating_expenses * assumptions.provider_non_operating_expense_share
    )
    provider = ViewResult(
        view="provider",
        monthly_revenue_or_benefit=provider_revenue,
        monthly_cost=provider_cost,
        monthly_net_value=provider_revenue - provider_cost,
        initial_investment=investment * (1 - assumptions.customer_initial_investment_share),
        notes="Provider view allocated by explicit revenue and cost shares.",
    )

    customer_benefit = (
        avoided_disposal_savings
        + fertilizer_revenue * (1 - assumptions.provider_fertilizer_revenue_share)
    )
    customer_cost = (
        service_revenue * assumptions.provider_service_fee_share
        + rental_cost * assumptions.provider_rental_revenue_share
        + cogs * (1 - assumptions.provider_cogs_share)
        + non_rental_opex * (1 - assumptions.provider_non_rental_opex_share)
        + non_operating_expenses * (1 - assumptions.provider_non_operating_expense_share)
    )
    customer = ViewResult(
        view="customer",
        monthly_revenue_or_benefit=customer_benefit,
        monthly_cost=customer_cost,
        monthly_net_value=customer_benefit - customer_cost,
        initial_investment=investment * assumptions.customer_initial_investment_share,
        notes="Customer view includes avoided disposal savings and allocated costs.",
    )

    return {"project": project, "provider": provider, "customer": customer}


def views_to_records(views: dict[str, ViewResult]) -> list[dict[str, float | str]]:
    """Convert view results into flat records for pandas/Streamlit."""

    return [
        {
            "view": result.view,
            "monthly_revenue_or_benefit": result.monthly_revenue_or_benefit,
            "monthly_cost": result.monthly_cost,
            "monthly_net_value": result.monthly_net_value,
            "initial_investment": result.initial_investment,
            "notes": result.notes,
        }
        for result in views.values()
    ]


def _validate_shares(assumptions: ViewAssumptions) -> None:
    share_fields = [
        "provider_fertilizer_revenue_share",
        "provider_service_fee_share",
        "provider_rental_revenue_share",
        "provider_cogs_share",
        "provider_non_rental_opex_share",
        "provider_non_operating_expense_share",
        "customer_initial_investment_share",
    ]
    for field in share_fields:
        value = getattr(assumptions, field)
        if value < 0 or value > 1:
            raise ValueError(f"{field} must be between 0 and 1")
