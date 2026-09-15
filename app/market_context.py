"""종목 하락이 시장 전체 조정과 함께 발생했는지 판단 (요구사항 5.4-(1) 맥락 정보)."""
import pandas as pd

from app.signals import load_thresholds


def classify_market_context(
    benchmark_close: pd.Series,
    sector_close: pd.Series,
    window_days: int | None = None,
    threshold_pct: float | None = None,
) -> pd.Series:
    """관측창 동안 벤치마크 또는 섹터 지수가 threshold_pct 이하로 하락했으면 'market_wide',
    아니면 'stock_specific'로 분류한 시리즈를 반환."""
    thresholds = load_thresholds()["market_context"]
    window_days = window_days if window_days is not None else thresholds["observation_window_days"]
    threshold_pct = threshold_pct if threshold_pct is not None else thresholds["decline_pct_threshold"]

    bench_chg = benchmark_close.pct_change(periods=window_days) * 100
    sector_chg = sector_close.pct_change(periods=window_days) * 100

    is_market_wide = (bench_chg <= threshold_pct) | (sector_chg <= threshold_pct)
    return is_market_wide.map({True: "market_wide", False: "stock_specific"})
