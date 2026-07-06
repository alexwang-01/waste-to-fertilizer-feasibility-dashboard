"""Synthetic demand generation for waste-volume forecasting examples."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CustomerDemandProfile:
    """Reusable synthetic waste pattern for a customer segment."""

    name: str
    baseline_tons_per_day: float
    weekday_multipliers: tuple[float, float, float, float, float, float, float]
    annual_seasonality_strength: float
    monthly_growth_rate: float
    noise_ratio: float
    event_rate: float
    event_lift_ratio: float


CUSTOMER_PROFILES: dict[str, CustomerDemandProfile] = {
    "Hotel": CustomerDemandProfile(
        name="Hotel",
        baseline_tons_per_day=36.0,
        weekday_multipliers=(0.95, 0.98, 1.00, 1.04, 1.12, 1.18, 1.10),
        annual_seasonality_strength=0.14,
        monthly_growth_rate=0.003,
        noise_ratio=0.08,
        event_rate=0.025,
        event_lift_ratio=0.28,
    ),
    "Mall": CustomerDemandProfile(
        name="Mall",
        baseline_tons_per_day=48.0,
        weekday_multipliers=(0.86, 0.88, 0.92, 0.96, 1.10, 1.28, 1.22),
        annual_seasonality_strength=0.10,
        monthly_growth_rate=0.002,
        noise_ratio=0.09,
        event_rate=0.020,
        event_lift_ratio=0.22,
    ),
    "Food Court": CustomerDemandProfile(
        name="Food Court",
        baseline_tons_per_day=28.0,
        weekday_multipliers=(1.00, 1.03, 1.04, 1.05, 1.10, 0.94, 0.86),
        annual_seasonality_strength=0.06,
        monthly_growth_rate=0.001,
        noise_ratio=0.10,
        event_rate=0.015,
        event_lift_ratio=0.18,
    ),
    "School": CustomerDemandProfile(
        name="School",
        baseline_tons_per_day=18.0,
        weekday_multipliers=(1.16, 1.18, 1.17, 1.15, 1.10, 0.38, 0.28),
        annual_seasonality_strength=0.24,
        monthly_growth_rate=0.000,
        noise_ratio=0.11,
        event_rate=0.010,
        event_lift_ratio=0.16,
    ),
    "Factory Canteen": CustomerDemandProfile(
        name="Factory Canteen",
        baseline_tons_per_day=32.0,
        weekday_multipliers=(1.08, 1.09, 1.09, 1.08, 1.02, 0.56, 0.42),
        annual_seasonality_strength=0.05,
        monthly_growth_rate=0.001,
        noise_ratio=0.07,
        event_rate=0.012,
        event_lift_ratio=0.15,
    ),
    "Supermarket": CustomerDemandProfile(
        name="Supermarket",
        baseline_tons_per_day=24.0,
        weekday_multipliers=(0.92, 0.94, 0.98, 1.02, 1.08, 1.16, 1.10),
        annual_seasonality_strength=0.08,
        monthly_growth_rate=0.001,
        noise_ratio=0.09,
        event_rate=0.018,
        event_lift_ratio=0.20,
    ),
}


def simulate_daily_waste(
    customer_type: str = "Hotel",
    history_days: int = 730,
    end_date: str | date | pd.Timestamp = "2026-06-30",
    baseline_tons_per_day: float | None = None,
    weekly_strength: float = 1.0,
    annual_strength: float | None = None,
    monthly_growth_rate: float | None = None,
    noise_ratio: float | None = None,
    event_rate: float | None = None,
    random_seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic daily waste history with trend, seasonality, and noise."""

    if customer_type not in CUSTOMER_PROFILES:
        raise ValueError(f"Unknown customer type: {customer_type}")
    if history_days < 30:
        raise ValueError("history_days must be at least 30")

    profile = CUSTOMER_PROFILES[customer_type]
    baseline = float(baseline_tons_per_day or profile.baseline_tons_per_day)
    annual = float(profile.annual_seasonality_strength if annual_strength is None else annual_strength)
    growth = float(profile.monthly_growth_rate if monthly_growth_rate is None else monthly_growth_rate)
    noise = float(profile.noise_ratio if noise_ratio is None else noise_ratio)
    event_probability = float(profile.event_rate if event_rate is None else event_rate)

    end = pd.Timestamp(end_date).normalize()
    dates = pd.date_range(end=end, periods=int(history_days), freq="D")
    rng = np.random.default_rng(random_seed)

    day_index = np.arange(len(dates), dtype=float)
    month_index = day_index / 30.4375
    trend_multiplier = 1 + growth * month_index

    weekday = dates.dayofweek.to_numpy()
    weekly_base = np.array(profile.weekday_multipliers, dtype=float)[weekday]
    weekly_multiplier = 1 + (weekly_base - 1) * float(weekly_strength)

    day_of_year = dates.dayofyear.to_numpy(dtype=float)
    annual_multiplier = 1 + annual * np.sin(2 * np.pi * (day_of_year - 15) / 365.25)

    expected = baseline * trend_multiplier * weekly_multiplier * annual_multiplier
    noise_component = rng.normal(0.0, noise * baseline, size=len(dates))
    event_flag = rng.random(len(dates)) < event_probability
    event_multiplier = np.where(event_flag, 1 + profile.event_lift_ratio, 1.0)
    waste = np.maximum(expected * event_multiplier + noise_component, baseline * 0.05)

    return pd.DataFrame(
        {
            "date": dates,
            "customer_type": profile.name,
            "waste_tons": waste,
            "expected_waste_tons": expected,
            "trend_component": baseline * trend_multiplier,
            "weekly_multiplier": weekly_multiplier,
            "annual_multiplier": annual_multiplier,
            "event_flag": event_flag,
        }
    )