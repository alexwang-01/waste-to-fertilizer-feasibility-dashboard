"""Forecasting methods aligned with Applied Data Science in Operations notes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SEASON_LENGTH = 12


@dataclass(frozen=True)
class ForecastModelSpec:
    """Metadata shown in the Streamlit model-selection UI."""

    key: str
    label: str
    description: str
    best_for: str


@dataclass(frozen=True)
class DemandForecastResult:
    """Forecast outputs used by notebooks and the Streamlit app."""

    model_key: str
    model_label: str
    train: pd.DataFrame
    test: pd.DataFrame
    holdout_forecast: pd.DataFrame
    future_forecast: pd.DataFrame
    metrics: dict[str, float]
    summary: dict[str, float]


FORECAST_MODELS: dict[str, ForecastModelSpec] = {
    "sma": ForecastModelSpec(
        key="sma",
        label="Simple Moving Average (SMA)",
        description="Uses the recent average as the next forecast level.",
        best_for="No trend and no seasonality.",
    ),
    "ses": ForecastModelSpec(
        key="ses",
        label="Single Exponential Smoothing (SES)",
        description="Applies exponentially decreasing weights to past observations.",
        best_for="No trend and no seasonality, with more weight on recent data.",
    ),
    "holt": ForecastModelSpec(
        key="holt",
        label="Double Exponential Smoothing (Holt's 2-Parameter)",
        description="Smooths both level and trend.",
        best_for="Strong linear upward or downward trend.",
    ),
    "holt_winters": ForecastModelSpec(
        key="holt_winters",
        label="Triple Exponential Smoothing (Holt's 3-Parameter)",
        description="Smooths level, trend, and seasonal indices.",
        best_for="Trend plus seasonality; requires at least two full seasonal cycles.",
    ),
}


def evaluate_forecast_model(
    history: pd.DataFrame,
    model_key: str = "holt_winters",
    test_periods: int = 6,
    horizon_periods: int = 6,
    test_days: int | None = None,
    horizon_days: int | None = None,
) -> DemandForecastResult:
    """Train a forecasting method, evaluate it on holdout periods, and forecast forward."""

    if test_days is not None:
        test_periods = max(1, int(round(test_days / 30.4375)))
    if horizon_days is not None:
        horizon_periods = max(1, int(round(horizon_days / 30.4375)))

    df = _prepare_history(history)
    if model_key not in FORECAST_MODELS:
        raise ValueError(f"Unknown forecasting model: {model_key}")
    if test_periods < 1:
        raise ValueError("test_periods must be positive")
    if horizon_periods < 1:
        raise ValueError("horizon_periods must be positive")
    if len(df) <= test_periods + SEASON_LENGTH:
        raise ValueError("history must contain more than one season plus the holdout window")

    split_idx = len(df) - int(test_periods)
    train = df.iloc[:split_idx].copy().reset_index(drop=True)
    test = df.iloc[split_idx:].copy().reset_index(drop=True)

    holdout_values = _forecast_values(train["demand_tons"].to_numpy(dtype=float), int(test_periods), model_key)
    future_values = _forecast_values(df["demand_tons"].to_numpy(dtype=float), int(horizon_periods), model_key)

    holdout = pd.DataFrame(
        {
            "date": test["date"],
            "forecast_mean": np.maximum(holdout_values, 0.0),
            "actual": test["demand_tons"].to_numpy(dtype=float),
        }
    )
    holdout["error"] = holdout["actual"] - holdout["forecast_mean"]

    future_dates = pd.date_range(df["date"].iloc[-1] + pd.DateOffset(months=1), periods=horizon_periods, freq="MS")
    future = pd.DataFrame(
        {
            "date": future_dates,
            "forecast_mean": np.maximum(future_values, 0.0),
        }
    )
    future = _add_forecast_intervals(future, holdout["error"])

    metrics = _forecast_metrics(holdout["actual"], holdout["forecast_mean"])
    spec = FORECAST_MODELS[model_key]
    summary = {
        "history_avg_demand_tons": float(df["demand_tons"].mean()),
        "holdout_avg_demand_tons": float(test["demand_tons"].mean()),
        "future_avg_demand_tons": float(future["forecast_mean"].mean()),
        "future_peak_demand_tons": float(future["forecast_mean"].max()),
    }

    return DemandForecastResult(
        model_key=model_key,
        model_label=spec.label,
        train=train,
        test=test,
        holdout_forecast=holdout,
        future_forecast=future,
        metrics=metrics,
        summary=summary,
    )


def compare_forecast_models(history: pd.DataFrame, test_periods: int = 6, test_days: int | None = None) -> pd.DataFrame:
    """Evaluate all supported methods on the same holdout period."""

    if test_days is not None:
        test_periods = max(1, int(round(test_days / 30.4375)))

    rows = []
    for model_key, spec in FORECAST_MODELS.items():
        result = evaluate_forecast_model(history, model_key=model_key, test_periods=test_periods, horizon_periods=test_periods)
        rows.append(
            {
                "model_key": model_key,
                "Model": spec.label,
                "ME": result.metrics["me"],
                "MAD": result.metrics["mad"],
                "MSE": result.metrics["mse"],
                "Best for": spec.best_for,
            }
        )
    return pd.DataFrame(rows).sort_values("MSE", ascending=True).reset_index(drop=True)


def forecast_daily_waste(history: pd.DataFrame, horizon_days: int = 90) -> DemandForecastResult:
    """Backward-compatible default forecast used by earlier notebooks."""

    horizon_periods = max(1, int(round(horizon_days / 30.4375)))
    test_periods = min(6, max(1, len(history) // 5))
    return evaluate_forecast_model(
        history,
        model_key="holt_winters",
        test_periods=test_periods,
        horizon_periods=horizon_periods,
    )


def _prepare_history(history: pd.DataFrame) -> pd.DataFrame:
    if "demand_tons" in history.columns:
        value_column = "demand_tons"
    elif "waste_tons" in history.columns:
        value_column = "waste_tons"
    else:
        raise ValueError("history must contain demand_tons or waste_tons")
    if "date" not in history.columns:
        raise ValueError("history must contain date")

    df = history[["date", value_column]].copy()
    df = df.rename(columns={value_column: "demand_tons"})
    df["date"] = pd.to_datetime(df["date"]).dt.to_period("M").dt.to_timestamp()
    df = df.sort_values("date").dropna(subset=["date", "demand_tons"]).reset_index(drop=True)
    if len(df) < 24:
        raise ValueError("history must contain at least 24 monthly observations")
    df["period_index"] = np.arange(len(df), dtype=float)
    return df


def _forecast_values(values: np.ndarray, periods: int, model_key: str) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if model_key == "sma":
        return _sma_forecast(values, periods)
    if model_key == "ses":
        alpha = _best_ses_alpha(values)
        return _ses_forecast(values, periods, alpha)
    if model_key == "holt":
        alpha, beta = _best_holt_params(values)
        return _holt_forecast(values, periods, alpha, beta)
    if model_key == "holt_winters":
        alpha, beta, gamma = _best_holt_winters_params(values)
        return _holt_winters_forecast(values, periods, alpha, beta, gamma)
    raise ValueError(f"Unknown forecasting model: {model_key}")


def _sma_forecast(values: np.ndarray, periods: int, window: int = 3) -> np.ndarray:
    level = float(np.mean(values[-window:]))
    return np.repeat(level, periods)


def _ses_forecast(values: np.ndarray, periods: int, alpha: float) -> np.ndarray:
    level = float(values[0])
    for actual in values[1:]:
        level = alpha * float(actual) + (1 - alpha) * level
    return np.repeat(level, periods)


def _holt_forecast(values: np.ndarray, periods: int, alpha: float, beta: float) -> np.ndarray:
    level = float(values[0])
    trend = float(values[1] - values[0]) if len(values) > 1 else 0.0
    for actual in values[1:]:
        previous_level = level
        level = alpha * float(actual) + (1 - alpha) * (level + trend)
        trend = beta * (level - previous_level) + (1 - beta) * trend
    steps = np.arange(1, periods + 1, dtype=float)
    return level + trend * steps


def _holt_winters_forecast(values: np.ndarray, periods: int, alpha: float, beta: float, gamma: float) -> np.ndarray:
    level, trend, seasonal = _initial_holt_winters_state(values)
    for index, actual in enumerate(values):
        seasonal_index = index % SEASON_LENGTH
        previous_level = level
        level = alpha * (float(actual) - seasonal[seasonal_index]) + (1 - alpha) * (level + trend)
        trend = beta * (level - previous_level) + (1 - beta) * trend
        seasonal[seasonal_index] = gamma * (float(actual) - level) + (1 - gamma) * seasonal[seasonal_index]
    forecasts = []
    start = len(values)
    for step in range(1, periods + 1):
        seasonal_index = (start + step - 1) % SEASON_LENGTH
        forecasts.append(level + trend * step + seasonal[seasonal_index])
    return np.asarray(forecasts, dtype=float)


def _initial_holt_winters_state(values: np.ndarray) -> tuple[float, float, np.ndarray]:
    first_season = values[:SEASON_LENGTH]
    second_season = values[SEASON_LENGTH : 2 * SEASON_LENGTH]
    if len(second_season) < SEASON_LENGTH:
        second_season = first_season
    first_avg = float(np.mean(first_season))
    second_avg = float(np.mean(second_season))
    level = first_avg
    trend = (second_avg - first_avg) / SEASON_LENGTH
    seasonal = first_season - first_avg
    return level, trend, seasonal.astype(float)


def _best_ses_alpha(values: np.ndarray) -> float:
    candidates = np.arange(0.1, 1.0, 0.1)
    return float(min(candidates, key=lambda alpha: _one_step_mse(values, "ses", (alpha,))))


def _best_holt_params(values: np.ndarray) -> tuple[float, float]:
    candidates = np.arange(0.1, 1.0, 0.2)
    best = min(
        ((alpha, beta) for alpha in candidates for beta in candidates),
        key=lambda params: _one_step_mse(values, "holt", params),
    )
    return float(best[0]), float(best[1])


def _best_holt_winters_params(values: np.ndarray) -> tuple[float, float, float]:
    candidates = (0.2, 0.4, 0.6, 0.8)
    best = min(
        ((alpha, beta, gamma) for alpha in candidates for beta in candidates for gamma in candidates),
        key=lambda params: _one_step_mse(values, "holt_winters", params),
    )
    return float(best[0]), float(best[1]), float(best[2])


def _one_step_mse(values: np.ndarray, model_key: str, params: tuple[float, ...]) -> float:
    min_train = SEASON_LENGTH * 2 if model_key == "holt_winters" else 6
    errors = []
    for end in range(min_train, len(values)):
        train = values[:end]
        if model_key == "ses":
            forecast = _ses_forecast(train, 1, params[0])[0]
        elif model_key == "holt":
            forecast = _holt_forecast(train, 1, params[0], params[1])[0]
        elif model_key == "holt_winters":
            forecast = _holt_winters_forecast(train, 1, params[0], params[1], params[2])[0]
        else:
            raise ValueError(f"Unsupported one-step model: {model_key}")
        errors.append(float(values[end] - forecast))
    return float(np.mean(np.square(errors))) if errors else float("inf")


def _add_forecast_intervals(forecast: pd.DataFrame, errors: pd.Series) -> pd.DataFrame:
    std_error = float(errors.std(ddof=1))
    if not np.isfinite(std_error) or std_error <= 0:
        std_error = 0.01
    output = forecast.copy()
    output["lower_80"] = np.maximum(output["forecast_mean"] - 1.2816 * std_error, 0.0)
    output["upper_80"] = output["forecast_mean"] + 1.2816 * std_error
    output["lower_95"] = np.maximum(output["forecast_mean"] - 1.9600 * std_error, 0.0)
    output["upper_95"] = output["forecast_mean"] + 1.9600 * std_error
    return output


def _forecast_metrics(actual: pd.Series, forecast: pd.Series) -> dict[str, float]:
    actual_values = actual.to_numpy(dtype=float)
    forecast_values = forecast.to_numpy(dtype=float)
    errors = actual_values - forecast_values
    return {
        "me": float(np.mean(errors)),
        "mad": float(np.mean(np.abs(errors))),
        "mse": float(np.mean(errors**2)),
    }
