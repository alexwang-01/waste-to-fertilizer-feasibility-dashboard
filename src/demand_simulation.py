"""Synthetic fertilizer market-demand scenarios for forecasting demos."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DemandScenario:
    """Monthly fertilizer market-demand pattern for model-selection demos."""

    key: str
    label: str
    description: str
    expected_good_models: tuple[str, ...]
    base_demand_tons_per_month: float
    monthly_growth_rate: float
    seasonal_strength: float
    noise_ratio: float


DEMAND_SCENARIOS: dict[str, DemandScenario] = {
    "stable_market": DemandScenario(
        key="stable_market",
        label="Stable Market Demand",
        description="Market demand stays around a stable level with random month-to-month noise.",
        expected_good_models=("Simple Moving Average (SMA)", "Single Exponential Smoothing (SES)"),
        base_demand_tons_per_month=620.0,
        monthly_growth_rate=0.000,
        seasonal_strength=0.00,
        noise_ratio=0.045,
    ),
    "growing_market": DemandScenario(
        key="growing_market",
        label="Growing Market Demand",
        description="Market demand grows steadily over time with limited seasonality.",
        expected_good_models=("Double Exponential Smoothing (Holt's 2-Parameter)",),
        base_demand_tons_per_month=520.0,
        monthly_growth_rate=0.012,
        seasonal_strength=0.02,
        noise_ratio=0.045,
    ),
    "seasonal_market": DemandScenario(
        key="seasonal_market",
        label="Seasonal Market Demand",
        description="Market demand repeats a clear annual seasonal pattern with no strong trend.",
        expected_good_models=("Triple Exponential Smoothing (Holt's 3-Parameter)",),
        base_demand_tons_per_month=640.0,
        monthly_growth_rate=0.000,
        seasonal_strength=0.18,
        noise_ratio=0.045,
    ),
    "growing_seasonal_market": DemandScenario(
        key="growing_seasonal_market",
        label="Growing + Seasonal Market Demand",
        description="Market demand has both a long-term growth trend and annual seasonality.",
        expected_good_models=("Triple Exponential Smoothing (Holt's 3-Parameter)",),
        base_demand_tons_per_month=540.0,
        monthly_growth_rate=0.010,
        seasonal_strength=0.16,
        noise_ratio=0.045,
    ),
}


PLANNING_WINDOWS = {
    "standard": {
        "label": "Standard: 36M history / 6M holdout / 6M forecast",
        "history_periods": 36,
        "test_periods": 6,
        "horizon_periods": 6,
    },
    "long": {
        "label": "Long: 48M history / 12M holdout / 12M forecast",
        "history_periods": 48,
        "test_periods": 12,
        "horizon_periods": 12,
    },
}


# Backward-compatible alias for older notebooks/tests that used customer profiles.
CUSTOMER_PROFILES = DEMAND_SCENARIOS


def simulate_demand_scenario(
    scenario_key: str = "stable_market",
    history_months: int = 36,
    end_date: str | pd.Timestamp = "2026-06-01",
    random_seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic monthly fertilizer market demand for model comparison."""

    if scenario_key not in DEMAND_SCENARIOS:
        raise ValueError(f"Unknown demand scenario: {scenario_key}")
    if history_months < 24:
        raise ValueError("history_months must be at least 24 for seasonal forecasting demos")

    scenario = DEMAND_SCENARIOS[scenario_key]
    end = pd.Timestamp(end_date).to_period("M").to_timestamp()
    dates = pd.date_range(end=end, periods=int(history_months), freq="MS")
    rng = np.random.default_rng(random_seed)

    month_index = np.arange(len(dates), dtype=float)
    trend_multiplier = 1 + scenario.monthly_growth_rate * month_index
    month_of_year = dates.month.to_numpy(dtype=float)
    seasonal_multiplier = 1 + scenario.seasonal_strength * np.sin(2 * np.pi * (month_of_year - 2) / 12)
    expected = scenario.base_demand_tons_per_month * trend_multiplier * seasonal_multiplier
    noise = rng.normal(0.0, scenario.noise_ratio * scenario.base_demand_tons_per_month, size=len(dates))
    demand = np.maximum(expected + noise, scenario.base_demand_tons_per_month * 0.05)

    return pd.DataFrame(
        {
            "date": dates,
            "period": dates.to_period("M").astype(str),
            "scenario": scenario.key,
            "scenario_label": scenario.label,
            "demand_tons": demand,
            "expected_demand_tons": expected,
            "trend_multiplier": trend_multiplier,
            "seasonal_multiplier": seasonal_multiplier,
            # Compatibility with the previous waste-oriented prototype.
            "waste_tons": demand,
        }
    )


def simulate_daily_waste(
    customer_type: str = "Hotel",
    history_days: int = 730,
    end_date: str | pd.Timestamp = "2026-06-30",
    baseline_tons_per_day: float | None = None,
    weekly_strength: float = 1.0,
    annual_strength: float | None = None,
    monthly_growth_rate: float | None = None,
    noise_ratio: float | None = None,
    event_rate: float | None = None,
    random_seed: int = 42,
) -> pd.DataFrame:
    """Compatibility wrapper returning monthly market demand for older imports."""

    customer_to_scenario = {
        "Hotel": "growing_market",
        "Mall": "growing_seasonal_market",
        "Food Court": "stable_market",
        "School": "seasonal_market",
        "Factory Canteen": "growing_market",
        "Supermarket": "seasonal_market",
    }
    months = max(24, int(round(history_days / 30.4375)))
    scenario_key = customer_to_scenario.get(customer_type, "stable_market")
    return simulate_demand_scenario(
        scenario_key=scenario_key,
        history_months=months,
        end_date=pd.Timestamp(end_date).to_period("M").to_timestamp(),
        random_seed=random_seed,
    )
