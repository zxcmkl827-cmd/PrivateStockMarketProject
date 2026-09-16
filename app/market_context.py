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


def refine_with_common_news(price_context: str, common_news_negative: bool) -> str:
    """가격 데이터로는 'stock_specific'이지만 공통(시장 전체) 뉴스가 부정적이면 라벨을 보정한다.

    등급/점수는 건드리지 않고 알림에 표시되는 맥락 라벨만 보정한다(요구사항 5.4(2), 사용자 확인
    2026-09-16) — 'market_wide'(가격으로 확인됨)와 'market_wide_news'(뉴스로만 뒷받침됨)를 구분해
    근거 출처를 투명하게 남긴다.
    """
    if price_context == "stock_specific" and common_news_negative:
        return "market_wide_news"
    return price_context
