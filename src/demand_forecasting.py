"""Lightweight time-series forecasting for synthetic waste demand."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DemandForecastResult:
    """Forecast outputs used by notebooks and the Streamlit app."""

    fitted_history: pd.DataFrame
    forecast: pd.DataFrame
    weekly_pattern: pd.DataFrame
    monthly_pattern: pd.DataFrame
    summary: dict[str, float]


def forecast_daily_waste(history: pd.DataFrame, horizon_days: int = 90) -> DemandForecastResult:
    """Forecast daily waste using trend plus weekly and monthly seasonal effects."""

    if horizon_days < 1:
        raise ValueError("horizon_days must be positive")
    if not {"date", "waste_tons"}.issubset(history.columns):
        raise ValueError("history must contain date and waste_tons columns")

    df = history[["date", "waste_tons"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").dropna(subset=["date", "waste_tons"]).reset_index(drop=True)
    if len(df) < 30:
        raise ValueError("history must contain at least 30 observations")

    df["day_index"] = np.arange(len(df), dtype=float)
    df["day_of_week"] = df["date"].dt.dayofweek
    df["month"] = df["date"].dt.month

    slope, intercept = np.polyfit(df["day_index"], df["waste_tons"], deg=1)
    df["trend"] = intercept + slope * df["day_index"]
    df["detrended"] = df["waste_tons"] - df["trend"]

    weekly_offsets = _centered_offsets(df, "day_of_week", "detrended", range(7))
    df["weekly"] = df["day_of_week"].map(weekly_offsets).astype(float)
    df["after_weekly"] = df["detrended"] - df["weekly"]

    monthly_offsets = _centered_offsets(df, "month", "after_weekly", range(1, 13))
    df["monthly"] = df["month"].map(monthly_offsets).astype(float)
    df["fitted"] = np.maximum(df["trend"] + df["weekly"] + df["monthly"], 0.0)
    df["residual"] = df["waste_tons"] - df["fitted"]

    residual_std = float(df["residual"].std(ddof=1))
    if not np.isfinite(residual_std) or residual_std <= 0:
        residual_std = max(float(df["waste_tons"].std(ddof=1)) * 0.10, 0.01)

    future_dates = pd.date_range(df["date"].iloc[-1] + pd.Timedelta(days=1), periods=horizon_days, freq="D")
    forecast = pd.DataFrame({"date": future_dates})
    forecast["day_index"] = np.arange(len(df), len(df) + horizon_days, dtype=float)
    forecast["day_of_week"] = forecast["date"].dt.dayofweek
    forecast["month"] = forecast["date"].dt.month
    forecast["trend"] = intercept + slope * forecast["day_index"]
    forecast["weekly"] = forecast["day_of_week"].map(weekly_offsets).astype(float)
    forecast["monthly"] = forecast["month"].map(monthly_offsets).astype(float)
    forecast["forecast_mean"] = np.maximum(forecast["trend"] + forecast["weekly"] + forecast["monthly"], 0.0)

    step = np.arange(1, horizon_days + 1, dtype=float)
    widening = 1 + np.sqrt(step) / 18
    forecast["std_error"] = residual_std * widening
    forecast["lower_80"] = np.maximum(forecast["forecast_mean"] - 1.2816 * forecast["std_error"], 0.0)
    forecast["upper_80"] = forecast["forecast_mean"] + 1.2816 * forecast["std_error"]
    forecast["lower_95"] = np.maximum(forecast["forecast_mean"] - 1.9600 * forecast["std_error"], 0.0)
    forecast["upper_95"] = forecast["forecast_mean"] + 1.9600 * forecast["std_error"]

    weekly_pattern = pd.DataFrame(
        {
            "day_of_week": list(range(7)),
            "day_name": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "seasonal_effect": [weekly_offsets[i] for i in range(7)],
        }
    )
    monthly_pattern = pd.DataFrame(
        {
            "month": list(range(1, 13)),
            "month_name": [pd.Timestamp(2024, month, 1).strftime("%b") for month in range(1, 13)],
            "seasonal_effect": [monthly_offsets[i] for i in range(1, 13)],
        }
    )

    summary = {
        "history_avg_waste_tons": float(df["waste_tons"].mean()),
        "forecast_avg_waste_tons": float(forecast["forecast_mean"].mean()),
        "forecast_peak_waste_tons": float(forecast["forecast_mean"].max()),
        "planning_p80_waste_tons": float(forecast["upper_80"].mean()),
        "planning_p95_waste_tons": float(forecast["upper_95"].mean()),
        "residual_std_tons": residual_std,
        "residual_cv": float(residual_std / max(df["waste_tons"].mean(), 0.01)),
    }

    return DemandForecastResult(
        fitted_history=df,
        forecast=forecast,
        weekly_pattern=weekly_pattern,
        monthly_pattern=monthly_pattern,
        summary=summary,
    )


def _centered_offsets(
    df: pd.DataFrame,
    group_column: str,
    value_column: str,
    expected_keys,
) -> dict[int, float]:
    offsets = df.groupby(group_column)[value_column].mean().to_dict()
    centered_mean = float(np.mean(list(offsets.values()))) if offsets else 0.0
    return {int(key): float(offsets.get(key, centered_mean) - centered_mean) for key in expected_keys}