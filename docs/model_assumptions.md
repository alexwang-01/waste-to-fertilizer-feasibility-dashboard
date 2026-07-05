# Model Assumptions

This document records the first-pass assumptions migrated from the original source project materials.

## Modeling Principle

The model should be treated as an **assumption-based feasibility simulator**, not a forecasting or ML model.

The first version should answer:

- Under what conditions does a customer opportunity become financially feasible?
- Which input variables drive the result most strongly?
- What minimum waste volume, fertilizer price, machine discount, or subsidy is required?

## Core Unit Economics

For each customer scenario, the model calculates monthly economics from the following chain:

```text
organic waste input
-> fertilizer conversion
-> fertilizer revenue + waste service revenue
-> direct operating costs
-> machine cost or rental cost
-> monthly cash flow
-> payback, ROI, IRR
```

## Key Formulas

### Waste Processed

```text
monthly_waste_tons = waste_tons_per_day * collection_rate * days_per_month
```

### Fertilizer Output

```text
monthly_fertilizer_tons = monthly_waste_tons * conversion_rate
```

### Revenue

```text
fertilizer_revenue = monthly_fertilizer_tons * fertilizer_price * fertilizer_sales_completion_rate
service_revenue = monthly_waste_tons * waste_service_fee
monthly_revenue = fertilizer_revenue + service_revenue
```

### Operating Costs

```text
enzyme_cost = monthly_waste_tons * enzyme_cost_per_ton_waste
electricity_cost = machine_count * total_load_kw * operation_hours_per_day * days_per_month * electricity_rate
electricity_cost = electricity_cost * electricity_load_factor
maintenance_cost = machine_capex * annual_maintenance_rate / 12
monthly_operating_cost = enzyme_cost + electricity_cost + labor_cost + maintenance_cost + other_monthly_cost
```

If a scenario has a known maintenance value, the model can use:

```text
maintenance_cost = maintenance_cost_usd_per_month
```

### CapEx Initial Investment

```text
gross_machine_capex = machine_price * machine_count
net_machine_capex = gross_machine_capex * (1 - machine_discount_rate)
grant_value = net_machine_capex * grant_rate
initial_investment = net_machine_capex - grant_value
```

For reconciliation with the source Excel model, the model also supports:

```text
initial_investment = net_machine_capex - grant_value - down_payment
```

This is labeled `excel_financed_principal` because it is closer to financed principal than true customer cash outflow.

### Tax And Non-operating Expenses

```text
tax_expense = max(operating_profit, 0) * tax_rate
non_operating_expenses = loan_interest_expense + tax_expense
monthly_accounting_profit = operating_profit - non_operating_expenses
```

### Cash Flow Timing

The source Excel benchmark uses partial first and final calendar years. To avoid hiding this inside formulas, the Python model supports an explicit month pattern:

```text
cashflow_months = (4, 12, 12, 12, 12, 12, 12, 12, 12, 12, 8)
```

This represents 120 operating months spread across 11 calendar-year columns.

### OpEx Machine Rental

```text
monthly_rental_cost = machine_rental_fee * machine_count * (1 - rental_discount_rate)
```

## Important Limitations

1. Conversion rates are scenario assumptions, not verified production averages.
2. Fertilizer selling price should be validated by country and product grade.
3. Electricity rates must be country- and customer-specific.
4. Machine capacity interpretation needs careful review because source materials mix batch capacity, daily waste input, and dashboard machine-size assumptions.
5. IRR is not meaningful when there is no negative initial investment.
6. Customer economics and Provider economics should eventually be separated into two views.
7. Tax, depreciation, working capital, logistics, installation, training, downtime, and repair costs need further validation.

## Next Validation Tasks

- Compare Python model output against the original Excel model for one known CapEx scenario.
- Compare Python model output against the original Excel model for one known OpEx scenario.
- Mark every assumption as confirmed, estimated, or placeholder.
- Add sensitivity analysis for conversion rate, fertilizer price, waste volume, electricity price, and machine discount.
