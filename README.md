# Waste-to-Fertilizer Feasibility Dashboard

[Live Streamlit App](https://waste-to-fertilizer-feasibility-dashboard.streamlit.app/)

This project rebuilds the source Waste-to-Fertilizer business model as a transparent, assumption-based decision support dashboard. It turns operational and commercial assumptions into an interactive app for deal discussion, financial evaluation, and scenario testing.

## Project Objective

Help sales and management teams answer early feasibility questions for waste-to-fertilizer opportunities:

- How much organic waste must a customer generate for the deal to be feasible?
- Which machine size is required?
- Is CapEx, OpEx, or a pilot-first model more suitable?
- What are the expected revenue, cost, net monthly result, and payback period?
- Which assumptions are useful negotiation levers?
- What conditions must be negotiated for the deal to work?

## Current Scope

The current rebuild focuses on a clean **unit economics, deal structure, and stakeholder value model**:

1. Extract and document core assumptions from the original source materials.
2. Rebuild the model in Python rather than relying on hidden spreadsheet formulas.
3. Calculate monthly waste processed, fertilizer output, revenue, operating costs, and deal-level metrics.
4. Support adjustable customer and operating assumptions.
5. Split the same business case into Provider and Customer financial views.
6. Package the calculation engine into an interactive Streamlit dashboard.


## Repository Structure

```text
waste-to-fertilizer-feasibility-dashboard/
|-- data/
|   |-- processed/
|   |   |-- machine_specs.csv
|   |   |-- waste_type_assumptions.csv
|   |   |-- country_defaults.csv
|   |   |-- scenario_defaults.csv
|   |   |-- personnel_defaults.csv
|   |   `-- view_assumptions.csv
|   `-- validation/
|       |-- excel_benchmark_scenarios.csv
|       |-- reconciliation_summary.csv
|       `-- reconciliation_v1_summary.csv
|-- docs/
|   |-- dashboard_mvp.md
|   |-- model_assumptions.md
|   |-- model_validation.md
|   `-- view_model.md
|-- notebooks/
|   |-- 01_unit_economics_model.ipynb
|   |-- 02_model_validation.ipynb
|   `-- 03_view_split.ipynb
|-- scripts/
|   `-- qa_deal_inputs.py
|-- src/
|   |-- __init__.py
|   |-- financial_model.py
|   |-- scenario_analysis.py
|   |-- sensitivity.py
|   `-- view_model.py
|-- tests/
|   `-- test_financial_model.py
|-- app.py
|-- requirements.txt
`-- README.md
```

## Source Reference

The original project files are treated as read-only internal reference materials and are not included in this public repository.

This repository only migrates selected assumptions and source notes into clean CSV, Markdown, Python, and notebook files.

## Quick Start

```bash
pip install -r requirements.txt
python -m pytest
python scripts/qa_deal_inputs.py
jupyter notebook notebooks/01_unit_economics_model.ipynb
python -m streamlit run app.py
```

The Streamlit MVP is available in `app.py`.

The app currently includes:

- Dashboard tab for deal setup, diagnostics, Provider report, Customer report, and negotiation what-if analysis`r`n- Demand Forecast tab for synthetic waste history, forecast intervals, and seasonality decomposition
- Machine tab for editable machine master assumptions
- Personnel tab for editable direct and indirect labor assumptions
- Python model modules in `src/` for reusable calculation, synthetic demand generation, and forecasting logic
- Notebooks in `notebooks/` for step-by-step model walkthrough and validation

## Model Status

Current model status: **draft MVP, benchmark-reconciled against the source Excel model with explicit assumptions, with Provider / Customer view splits and a Streamlit dashboard added**.

The formulas are intentionally simple and explicit. The source Excel benchmark comparison is documented in `docs/model_validation.md`, the stakeholder-view logic is documented in `docs/view_model.md`, and the dashboard MVP is documented in `docs/dashboard_mvp.md`. The next step is to refine the CapEx and OpEx deal assumptions with real provider/customer sales inputs.
