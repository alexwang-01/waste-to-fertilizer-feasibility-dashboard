import pandas as pd

from src.demand_forecasting import forecast_daily_waste
from src.demand_simulation import CUSTOMER_PROFILES, simulate_daily_waste


def test_simulate_daily_waste_returns_positive_daily_history():
    history = simulate_daily_waste(
        customer_type="Hotel",
        history_days=120,
        baseline_tons_per_day=35,
        random_seed=7,
    )

    assert len(history) == 120
    assert {"date", "customer_type", "waste_tons", "event_flag"}.issubset(history.columns)
    assert history["waste_tons"].min() > 0
    assert history["customer_type"].nunique() == 1
    assert set(CUSTOMER_PROFILES).issuperset({"Hotel", "Mall", "Food Court"})


def test_forecast_daily_waste_returns_intervals_and_summary():
    history = simulate_daily_waste(customer_type="Mall", history_days=365, random_seed=11)
    result = forecast_daily_waste(history, horizon_days=60)
    forecast = result.forecast

    assert len(forecast) == 60
    assert pd.to_datetime(forecast["date"]).min() > pd.to_datetime(history["date"]).max()
    assert (forecast["lower_95"] <= forecast["lower_80"]).all()
    assert (forecast["lower_80"] <= forecast["forecast_mean"]).all()
    assert (forecast["forecast_mean"] <= forecast["upper_80"]).all()
    assert (forecast["upper_80"] <= forecast["upper_95"]).all()
    assert result.summary["forecast_avg_waste_tons"] > 0
    assert result.summary["planning_p95_waste_tons"] >= result.summary["planning_p80_waste_tons"]
    assert len(result.weekly_pattern) == 7
    assert len(result.monthly_pattern) == 12