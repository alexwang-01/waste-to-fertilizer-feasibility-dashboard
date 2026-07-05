# Model Validation: Excel Benchmark Reconciliation

Date: 2026-07-03

## Purpose

This validation pass compares the new Python feasibility model against the original Provider Excel workbook used as an internal reference source. The workbook itself is not included in this public repository.

The goal is not to force the Python model to reproduce every Excel number. The goal is to identify which parts of the original model are clear, which parts are ambiguous, and which formulas need redesign before a dashboard is built.

## Benchmark Cases

Two source dashboard cases were extracted from the workbook's cached values.

### CapEx Benchmark

Source sheet: `Dashboard(CapEx)`

Key inputs:

- Waste generation: 100 tons/day
- Collection rate: 100%
- Collection frequency: 30 days/month
- Waste-to-fertilizer conversion rate: 30%
- Machine size: 100 tons
- Machine count: 1
- Machine cost before discount: USD 23,375,000
- Machine discount: 55%
- Discounted machine cost: USD 10,518,750
- Government grant: USD 1,051,875
- Down payment: USD 1,051,875
- Fertilizer price: USD 300/ton
- Waste collection service fee: USD 50/ton

Key Excel outputs:

- Monthly waste processed: 3,000 tons
- Monthly fertilizer output: 900 tons
- Monthly revenue: USD 420,000
- Monthly net profit: USD 257,897
- Initial cash outflow: USD 8,415,000
- Payback: 33 months
- Year 10 ROI: 214.2%
- Year 10 IRR: 28.8%

### OpEx Benchmark

Source sheet: `Dashboard(OpEx)`

Key inputs:

- Waste generation: 100 tons/day
- Collection rate: 100%
- Collection frequency: 30 days/month
- Waste-to-fertilizer conversion rate: 70%
- Machine size: 60 tons
- Machine count: 2
- Monthly rental per machine: USD 90,675
- Monthly total rental: USD 181,350
- Fertilizer price: USD 250/ton
- Waste service fee is shown as customer savings, not operating revenue.

Key Excel outputs:

- Monthly waste processed: 3,000 tons
- Monthly fertilizer output: 2,100 tons
- Monthly revenue: USD 525,000
- Monthly net profit: USD 285,335
- Initial investment: USD 0
- Payback: 1 month
- ROI: `#DIV/0!`
- IRR: `#NUM!`

## Reconciliation Summary

The detailed comparison is stored in:

```text
data/validation/reconciliation_summary.csv
```

High-level findings:

1. Revenue logic matches well.
   - Waste volume, fertilizer output, fertilizer revenue, and service revenue can be reproduced cleanly.

2. Electricity cost does not reconcile.
   - CapEx Excel monthly electricity cost is USD 17,784, while Python v0 calculates USD 55,623 using the extracted 100-ton machine load.
   - OpEx Excel monthly electricity cost is USD 26,611, while Python v0 calculates USD 77,287 using two 60-ton machines.
   - This suggests the Excel model may be using an effective load, utilization adjustment, or a different lookup source than the extracted machine table.

3. Maintenance logic does not reconcile.
   - CapEx Excel uses USD 4,000/month.
   - Python v0 uses 5% of discounted machine capex per year, which produces USD 43,828/month.
   - This must be redesigned as an explicit assumption rather than hidden inside the model.

4. Initial investment logic differs.
   - Excel subtracts both government grant and down payment from the initial cash outflow.
   - Python v0 subtracts only the government grant.
   - This is a conceptual issue: down payment is not the same as a subsidy. It may reduce financed amount, but it is still a cash outflow for the customer unless the view is specifically measuring financed principal.

5. OpEx ROI and IRR should be guarded.
   - Excel returns `#DIV/0!` and `#NUM!` because initial investment is zero.
   - Python v0 returns `None`, which is better for a future dashboard because it avoids showing spreadsheet errors to users.

6. Customer view and Provider view are mixed.
   - In OpEx, waste collection service fee appears as customer savings, not revenue.
   - In CapEx, service fee appears as revenue.
   - The model should eventually separate:
     - Provider economics
     - customer economics
     - project economics

## Validation Status

Current status: **v0 partially reconciled; v1 benchmark-reconciled with explicit assumptions**.

The original mismatch table is retained in:

```text
data/validation/reconciliation_summary.csv
```

The updated v1 reconciliation table is stored in:

```text
data/validation/reconciliation_v1_summary.csv
```

The explicit v1 benchmark inputs are stored in:

```text
data/validation/excel_benchmark_scenarios.csv
```

The v1 table shows that the Python model can reproduce the key cached Excel benchmark outputs after the hidden or ambiguous Excel assumptions are made explicit:

- `electricity_load_factor`
- `maintenance_cost_usd_per_month`
- `direct_labor_cost_usd_per_month`
- `indirect_labor_cost_usd_per_month`
- `loan_interest_expense_usd_per_month`
- `tax_rate`
- `initial_investment_basis`
- `roi_denominator_basis`
- `cashflow_months`

What is reliable enough to keep:

- Waste volume calculation
- Fertilizer output calculation
- Fertilizer revenue calculation
- Service revenue calculation, if the business-model view is clearly defined
- Rental fee calculation for OpEx
- Guarded ROI/IRR behavior for zero-investment cases

What needs redesign:

- Electricity cost methodology for real sales cases, because the Excel benchmark uses an implied load factor rather than full machine load
- Machine capacity interpretation
- Maintenance cost assumption for non-benchmark scenarios
- CapEx initial investment and financing treatment for customer-facing cash-flow views
- Loan principal treatment
- Calendar-year timing for non-benchmark scenarios
- Separation of accounting profit vs cash flow
- Separation of Provider view vs customer view

## Recommended Next Model Changes

1. Add explicit cost assumptions.
   - `electricity_load_factor`
   - `maintenance_cost_usd_per_month`
   - `direct_labor_cost_usd_per_month`
   - `indirect_labor_cost_usd_per_month`
   - `loan_payment_usd_per_month`

2. Split model views.
   - `provider_view`
   - `customer_view`
   - `project_view`

3. Separate accounting profit from cash flow.
   - Profit should include operating and non-operating expenses.
   - Cash flow should separately handle capex, down payment, grants, debt drawdown, principal repayment, and interest.

4. Build a `Checks` layer in Python.
   - Revenue tie-out
   - Waste-to-output tie-out
   - Machine count tie-out
   - ROI/IRR validity checks
   - Missing source assumptions

5. Update the notebook with a validation section before building Streamlit.

## Conclusion

The original Excel model contains useful business logic, especially for waste volume, fertilizer output, and revenue generation. However, its cost, financing, and return metrics are not yet clean enough to become a dashboard without redesign.

The next phase should improve the Python model structure rather than copy the Excel formulas directly.
