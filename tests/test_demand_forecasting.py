import pandas as pd

from src.demand_forecasting import FORECAST_MODELS, compare_forecast_models, evaluate_forecast_model
from src.demand_simulation import DEMAND_SCENARIOS, PLANNING_WINDOWS, simulate_demand_scenario


def test_simulate_demand_scenario_returns_positive_monthly_market_history():
    history = simulate_demand_scenario(
        scenario_key="growing_seasonal_market",
        history_months=36,
        random_seed=7,
    )

    assert len(history) == 36
    assert {"date", "period", "scenario", "scenario_label", "demand_tons"}.issubset(history.columns)
    assert history["demand_tons"].min() > 0
    assert history["scenario"].nunique() == 1
    assert set(DEMAND_SCENARIOS) == {
        "stable_market",
        "growing_market",
        "seasonal_market",
        "growing_seasonal_market",
    }
    assert set(PLANNING_WINDOWS).issuperset({"standard", "long"})


def test_evaluate_forecast_model_returns_holdout_metrics_and_intervals():
    history = simulate_demand_scenario(scenario_key="seasonal_market", history_months=36, random_seed=11)
    result = evaluate_forecast_model(
        history,
        model_key="holt_winters",
        test_periods=6,
        horizon_periods=6,
    )

    assert len(result.holdout_forecast) == 6
    assert len(result.future_forecast) == 6
    assert pd.to_datetime(result.future_forecast["date"]).min() > pd.to_datetime(history["date"]).max()
    assert (result.future_forecast["lower_95"] <= result.future_forecast["lower_80"]).all()
    assert (result.future_forecast["lower_80"] <= result.future_forecast["forecast_mean"]).all()
    assert (result.future_forecast["forecast_mean"] <= result.future_forecast["upper_80"]).all()
    assert (result.future_forecast["upper_80"] <= result.future_forecast["upper_95"]).all()
    assert {"me", "mad", "mse"}.issubset(result.metrics)
    assert result.metrics["mad"] >= 0
    assert result.metrics["mse"] >= 0
    assert result.summary["future_avg_demand_tons"] > 0


def test_compare_forecast_models_evaluates_course_methods():
    history = simulate_demand_scenario(scenario_key="stable_market", history_months=36, random_seed=13)
    comparison = compare_forecast_models(history, test_periods=6)

    assert len(comparison) == len(FORECAST_MODELS)
    assert comparison["MSE"].is_monotonic_increasing
    assert comparison["Model"].tolist()
    assert set(comparison["Model"]) == {
        "Simple Moving Average (SMA)",
        "Single Exponential Smoothing (SES)",
        "Double Exponential Smoothing (Holt's 2-Parameter)",
        "Triple Exponential Smoothing (Holt's 3-Parameter)",
    }
