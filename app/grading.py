"""3단계 등급 판정 엔진 — 유지관찰/비중축소/매도 (요구사항 5.5, 사용자 승인 기준)."""
from app.signals import load_thresholds

STRONG_NEWS_CATEGORIES = {"earnings_guidance", "regulatory_legal_political"}

GRADE_NONE = "없음"
GRADE_WATCH = "유지관찰"
GRADE_REDUCE = "비중축소"
GRADE_SELL = "매도"


def grade_signal(pct_change: float | None, news_items: list[dict]) -> str:
    """가격 하락률(%, 신호 없으면 None)과 뉴스 분류 결과를 결합해 등급을 반환한다."""
    thresholds = load_thresholds()
    watch_pct = thresholds["price_decline"]["decline_pct_threshold"]
    reduce_pct = thresholds["reduce_position"]["decline_pct_threshold"]

    price_signal = pct_change is not None and pct_change <= watch_pct
    strong_price_signal = pct_change is not None and pct_change <= reduce_pct

    negative_news = [n for n in news_items if n.get("sentiment") == "negative"]
    news_signal = bool(negative_news)
    strong_category_news = any(n.get("category") in STRONG_NEWS_CATEGORIES for n in negative_news)
    other_category_news = any(n.get("category") == "other" for n in negative_news)

    if price_signal and strong_category_news:
        return GRADE_SELL
    if strong_price_signal or (price_signal and news_signal and other_category_news):
        return GRADE_REDUCE
    if price_signal or news_signal:
        return GRADE_WATCH
    return GRADE_NONE
