# View Model: Deal, Provider, and Customer Views

## Purpose

The feasibility model separates the deal conversation into three questions:

1. **Deal summary**: Does the proposed structure create positive value for both sides?
2. **Provider view**: What revenue, cost, and profit does Provider capture?
3. **Customer view**: What savings, costs, and net value does the customer see?

This matters because the original Excel model mixes these perspectives. For example, a machine rental payment is a cost to the customer but revenue to Provider. If both parties are shown inside one project-level P&L, the dashboard can become misleading.

## Design Principle

The view model is an allocation layer. It does not change the core technical and financial calculations:

```text
waste input -> fertilizer output -> revenue -> cost -> profit/cash flow
```

Instead, it takes those outputs and allocates them using explicit shares.

## View Assumptions

The main assumptions are stored in:

```text
data/processed/view_assumptions.csv
```

Key fields:

- `current_disposal_fee_usd_per_ton`: customer avoided disposal cost
- `provider_fertilizer_revenue_share`: share of fertilizer revenue captured by Provider
- `provider_service_fee_share`: share of waste service fee captured by Provider
- `provider_rental_revenue_share`: share of machine rental captured by Provider
- `provider_cogs_share`: share of COGS borne by Provider
- `provider_non_rental_opex_share`: share of non-rental operating expenses borne by Provider
- `provider_non_operating_expense_share`: share of interest/tax/non-operating expenses borne by Provider
- `customer_initial_investment_share`: share of initial investment borne by customer

All shares must be between 0 and 1.

## Current Formulas

### Deal Summary

```text
deal_status =
    mutually positive
    or Provider positive, customer needs improvement
    or customer positive, Provider needs improvement
    or needs redesign
```

### Provider View

```text
provider_revenue =
    fertilizer_revenue * provider_fertilizer_revenue_share
  + service_revenue * provider_service_fee_share
  + rental_cost * provider_rental_revenue_share

provider_cost =
    cogs * provider_cogs_share
  + non_rental_opex * provider_non_rental_opex_share
  + non_operating_expenses * provider_non_operating_expense_share

provider_net_value = provider_revenue - provider_cost
```

### Customer View

```text
avoided_disposal_savings =
    monthly_waste_tons * current_disposal_fee_usd_per_ton

customer_benefit =
    avoided_disposal_savings
  + fertilizer_revenue * (1 - provider_fertilizer_revenue_share)

customer_cost =
    service_revenue * provider_service_fee_share
  + rental_cost * provider_rental_revenue_share
  + cogs * (1 - provider_cogs_share)
  + non_rental_opex * (1 - provider_non_rental_opex_share)
  + non_operating_expenses * (1 - provider_non_operating_expense_share)

customer_net_value = customer_benefit - customer_cost
```

## Important Caveat

The view model is still an allocation framework, not a finalized legal or accounting model. Before using it in a client-facing dashboard, each business model needs a contract definition:

- Who owns the machine?
- Who pays electricity?
- Who pays labor?
- Who sells fertilizer?
- Who receives the waste collection fee?
- Who bears tax, loan interest, and maintenance?

Those answers should become explicit deal templates. The current dashboard keeps three high-level structures: Customer-owned CapEx, Provider-owned OpEx, and Co-investment. Co-investment is the only structure that exposes an adjustable customer equipment cost share.
