# Dashboard MVP

The Streamlit dashboard is now positioned as a deal calculator for conversations between Provider and a prospective customer.

It is not intended to be a formal accounting system. It is an early-stage decision support tool that helps both sides understand whether a proposed commercial structure creates value for Provider and for the customer.

## Current Layout

The app uses three main tabs:

- Dashboard
- Machine
- Personnel

The tabs keep customer-facing deal results separate from editable master data. The sidebar remains the case setup area for the current deal, while Machine and Personnel provide editable session-level assumptions used by the model.

### Dashboard

- Deal Setup: a print-friendly row of fixed-height summary blocks showing the customer-facing assumptions for the current case.
- Deal Diagnostics: a three-chart diagnostic row showing investment recovery, monthly value composition, and capacity utilization directly below Deal Setup.
- Provider: fixed-order simplified monthly revenue, cost, result, and investment metrics for Provider.
- Customer: fixed-order simplified monthly benefit, cost, result, and investment metrics for the customer.
- Investment Metrics: customer-facing investment discussion metrics are shown separately from the monthly run-rate reports.
- Negotiation Lab: a multi-lever deal adjustment package after the financial reports, with current values, adjustment inputs, adjusted values, an impact split chart, and a current vs adjusted table.

Each major section uses the same light background, subtle border, and compact spacing. The intent is to make the page easier to scan and print without turning every chart or report into a separate nested card.

### Machine

The Machine tab is the editable machine master data area for the current session. It does not replace the sidebar controls for auto/manual sizing or machine quantity.

It shows:

- machine model
- capacity
- power and heater
- operating hours per day
- Asia equipment price without CE
- monthly rental ratio
- calculated total load
- calculated default monthly rental

The visual layout is intentionally closer to the Negotiation Lab than to an Excel-style data grid. Source notes from the original extraction are kept out of the user-facing editor.

### Personnel

The Personnel tab is the editable personnel master data area for the current session. It starts from `data/processed/personnel_defaults.csv`, extracted from the original Excel `Personnel` sheet.

Personnel is split into two sections:

- Direct Labor
- Indirect Labor

It shows:

- role
- headcount
- monthly salary
- calculated monthly cost
- section-level total monthly cost

The visual layout uses compact editable rows instead of an Excel-style data grid. Source notes are not displayed in the tab.

The Dashboard calculation uses the current Direct Labor and Indirect Labor sections to calculate direct and indirect labor. These labor costs are no longer manually entered in the sidebar.

## Deal Structure

The dashboard exposes one commercial choice: `Deal Structure`.

The first MVP keeps this intentionally simple:

- CapEx (Customer-owned Machine): the customer owns the machine and carries the initial investment.
- OpEx (Provider-owned Machine): Provider owns the machine and the customer pays through rental, service fee, or other operating terms.
- Co-investment (Shared Machine Cost): Provider and the customer share the equipment cost. The customer equipment cost share is adjustable.

The UI does not expose a separate `Scenario preset` or `Business model` selector. The dashboard uses the base scenario only as a starting point for input defaults, and each deal structure automatically maps to the appropriate underlying model:

```text
CapEx (Customer-owned Machine) -> capex
OpEx (Provider-owned Machine) -> opex
Co-investment (Shared Machine Cost) -> capex
```

The equipment cost owner is locked by the selected deal structure:

```text
CapEx (Customer-owned Machine) -> customer carries 100% of equipment cost
OpEx (Provider-owned Machine) -> Provider carries 100% of equipment cost
Co-investment (Shared Machine Cost) -> Provider and customer each carry their allocated share
```

The shared investment percentage is only exposed when the co-investment structure is selected. This keeps the simpler CapEx and OpEx cases clean while still supporting a joint-purchase negotiation.

## Input Controls and Deal Setup

The sidebar acts as the model control panel. It contains the full set of adjustable inputs:

- Equipment Terms: customer equipment cost share for co-investment, machine sizing, manual fleet setup, machine discount, grant, and rental discount.
- Customer Operating Profile: waste volume, collection rate, operating days, and current disposal fee.
- Output Assumptions: conversion rate and fertilizer sales completion.
- Revenue Terms: fertilizer price, Provider service fee, and Provider fertilizer revenue share.
- Operating Cost Assumptions: electricity rate, average power usage, enzyme cost, labor cost from Personnel, other operating cost, and annual maintenance rate.
- Finance / Tax: tax rate and loan interest.

The sidebar is intentionally not being heavily restructured in this MVP. Machine and Personnel tabs now provide editable session-level assumptions, while the sidebar continues to control the current customer case.

Service fee revenue and rental revenue are fixed to Provider in this MVP. Direct cost, operating cost, interest, and tax allocation are kept in the selected deal preset rather than exposed as negotiation sliders. These can become explicit operating responsibility controls in a later version.

Machine sizing supports two modes:

- `Auto size by capacity`: selects the smallest single machine capacity that can cover the daily waste volume. It is not an optimization for lowest cost or best payback.
- `Manual fleet setup`: lets the user configure up to five machine rows, each with its own machine model and quantity. The model then aggregates total capacity, equipment cost, rental cost, and electricity load across the selected fleet.

If manual capacity is below the current waste volume, the dashboard shows a warning. If the machine setup is materially over-sized, the dashboard shows a utilization note.

Percentage assumptions use both a numeric input and a slider bar. The numeric input allows precise entry, while the slider supports quick discussion adjustments. Percentage ranges are constrained directly in the UI:

- Standard percentage assumptions: 0% to 100%.
- Discount and grant assumptions: 0% to 80%.
- Tax rate: 0% to 50%.
- Annual maintenance rate: 0% to 20%.

Quantity and price assumptions use numeric inputs with practical lower bounds, such as non-negative prices and costs, 1 to 31 operating days per month, and a positive daily waste volume.

The main-page Deal Setup is not the control panel. It is the customer-facing case summary. It keeps each block to the same number of rows so the printed page remains aligned and easy to scan.

The summary blocks are:

- Deal
- Waste
- Output
- Commercial
- Cost
- Sharing

## Financial Framing

The dashboard separates Provider and customer economics because the same deal can look attractive to one party and unattractive to the other.

The Provider view is closer to a simplified income statement:

```text
Provider Revenue
- Provider Direct Cost
- Provider Operating Cost
- Provider Interest and Tax
= Provider Monthly Net Profit
```

The Customer view is a value statement rather than a formal income statement:

```text
Avoided Disposal Cost
+ Fertilizer Revenue Retained by Customer
- Payments to Provider
- Customer Operating Cost
- Customer Interest and Tax
= Customer Monthly Net Saving
```

The monthly run-rate reports are not the first month of a time series. They represent a normal operating month under stable monthly assumptions. In the current model, annual values are simple run-rate extensions unless future versions add ramp-up, seasonality, inflation, equipment degradation, or changing market prices.

Investment Metrics focus on discussion-friendly metrics:

- Initial investment
- Monthly net profit / saving
- Annualized net profit / saving
- Payback / break-even

ROI and IRR are still calculated internally, but they are not shown in the main dashboard because the current model is a linear early-stage deal calculator rather than a full project finance model.

The Provider and Customer reports are rendered as fixed-order report tables rather than sortable data grids. The row order carries financial meaning and should not be rearranged by clicking column headers.

## Deal Diagnostics

Deal Diagnostics appears directly below Deal Setup and before the Provider and Customer report columns. It is deliberately positioned as the first discussion layer after the case assumptions, so users can read recovery, commercial value, and operating fit before going into line-item reports.

The chart row uses a 1/2, 1/4, 1/4 layout with fixed chart heights. The monthly value and capacity charts are slightly taller because they do not need the same legend space as the investment recovery chart.

- Investment Recovery Timeline: shows Provider and customer cumulative value against the equipment cost to recover. Its status bar combines the overall deal status with the active break-even signal.
- Monthly Value Composition: stacked monthly gross value bars for Provider and Customer. Provider components include fertilizer revenue, service fee, and rental. Customer components include avoided disposal cost and retained fertilizer revenue. Each segment labels the component on one line and the monthly value plus stakeholder-level share on the next line. Stakeholder gross value totals are shown above each bar.
- Capacity Utilization: a vertical bar showing waste volume as a percentage of selected machine capacity. Below 70% suggests a possible over-sized setup; above 100% indicates insufficient capacity. The waste/capacity tonnage is shown inside the bar, and the separate legend is hidden.

Each chart has its own status bar above the plot. The status bar carries the short interpretation that previously appeared as chart captions, such as overall deal status with delayed break-even, gross value split, or capacity fit. Monthly gross value split uses `Balanced (within 20%)` in green, `Moderate Gap (20-50%)` in yellow, and `Large Gap (>50%)` in red. Capacity status uses short labels such as `Workable`, `Over-sized`, or `Shortfall`; the detailed utilization and tonnage remain inside the bar.

Negotiation Lab appears after the financial reports rather than inside the chart row.

It is a multi-lever deal adjustment package. Users can adjust several major negotiation assumptions at the same time, and the dashboard recalculates the same financial model for the adjusted case.

Each row shows the current value, the adjustment amount, and the adjusted value. This keeps the negotiation context visible without requiring users to search back through the full Deal Inputs panel.

The current package includes:

- Provider service fee
- Rental discount
- Fertilizer price
- Conversion rate
- Machine discount
- Current disposal fee
- Provider fertilizer revenue share

The main Negotiation Lab output includes:

- a diverging impact split chart showing Customer impact and Provider impact around a zero baseline
- a current vs adjusted table for Provider monthly net profit, Customer monthly net saving, Provider payback, Customer payback, and deal status

The purpose is to help sales identify which assumptions are worth negotiating and which assumptions are mainly operating risks to validate before proposing a deal.

## Investment Recovery Timeline

The investment recovery chart shows the first 10 years on the x-axis. This keeps the dashboard readable during customer discussions while still making delayed recovery visible through the investment metric table and the chart status bar.

The chart appears inside Deal Diagnostics directly below Deal Setup. It is paired with monthly value composition and capacity utilization so users can read recovery, commercial value, and operating fit together.

The chart shows:

- Provider cumulative net profit
- Customer cumulative net saving
- Equipment cost to recover after machine discount and grant support
- The break-even marker for the party carrying the machine investment
- Compact value labels for annual nodes

Under the default structures:

- CapEx (Customer-owned Machine): customer recovery is judged against the equipment cost line.
- OpEx (Provider-owned Machine): Provider recovery is judged against the equipment cost line.
- Co-investment (Shared Machine Cost): Provider and customer each have their own equipment cost line and break-even marker.

Future versions can align this timeline with depreciation period, contract length, or equipment amortization assumptions.

## Deal Input QA

The current input QA script is:

```text
scripts/qa_deal_inputs.py
```

It runs the main deal structures, manual fleet sizing cases, and parameter stress cases through the dashboard calculation service. The latest run covered 31 cases and found no runtime, missing-output, non-finite-number, report-row-count, timeline, or sensitivity-output issues.
