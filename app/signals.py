"""절대 하락률 기반 가격 신호 계산 (요구사항 5.4-(1))."""
import json
from pathlib import Path

import pandas as pd

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "signal_thresholds.json"


def load_thresholds(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def price_decline_pct(close_prices: pd.Series, window_days: int | None = None) -> pd.Series:
    """관측창(window_days) 동안의 누적 등락률(%) 시리즈를 반환."""
    thresholds = load_thresholds()["price_decline"]
    window_days = window_days if window_days is not None else thresholds["observation_window_days"]
    return close_prices.pct_change(periods=window_days) * 100


def price_decline_signal(
    close_prices: pd.Series,
    window_days: int | None = None,
    threshold_pct: float | None = None,
) -> pd.Series:
    """관측창(window_days) 동안 누적 하락률이 threshold_pct 이하이면 True인 신호 시리즈를 반환."""
    thresholds = load_thresholds()["price_decline"]
    threshold_pct = threshold_pct if threshold_pct is not None else thresholds["decline_pct_threshold"]
    return price_decline_pct(close_prices, window_days) <= threshold_pct
