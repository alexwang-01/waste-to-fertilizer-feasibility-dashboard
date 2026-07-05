"""One-way sensitivity analysis for early feasibility testing."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import pandas as pd

from .financial_model import FeasibilityInputs, MachineSpec, summarize_feasibility


def one_way_sensitivity(
    base_inputs: FeasibilityInputs,
    machine: MachineSpec,
    variable: str,
    values: Iterable[float],
    metric: str = "monthly_cash_flow",
) -> pd.DataFrame:
    """Vary one input and track one output metric."""

    records = []
    for value in values:
        updated = replace(base_inputs, **{variable: value})
        result = summarize_feasibility(updated, machine)
        records.append({variable: value, metric: result.get(metric)})
    return pd.DataFrame(records)
