"""알림 메시지 포맷 (요구사항 5.6): 종목명·등급·판단 근거·행동 제안."""
from app.grading import GRADE_NONE, GRADE_REDUCE, GRADE_SELL, GRADE_WATCH

ACTION_MAP = {
    GRADE_WATCH: "특별한 조치 없이 계속 지켜보기",
    GRADE_REDUCE: "비중 축소를 검토해볼 것",
    GRADE_SELL: "매도를 적극 검토할 것",
    GRADE_NONE: "조치 불필요",
}

MARKET_CONTEXT_DESC = {
    "market_wide": "시장 전체 조정과 함께 하락 (종목 고유 문제로 단정하기 어려움)",
    "stock_specific": "시장 전체와 무관한 종목 고유 하락으로 보임",
    None: "시장 상황 판단 불가(가격 하락 신호 없음)",
}


def format_alert_message(
    ticker: str,
    grade: str,
    price_pct_change: float | None,
    market_context: str | None,
    negative_news_titles: list[str],
) -> str:
    """종목명·등급·가격추세·뉴스요약·시장상황·행동제안을 포함한 알림 메시지를 생성."""
    price_desc = (
        f"최근 10거래일 {price_pct_change:.1f}% 변동" if price_pct_change is not None else "가격 하락 신호 없음"
    )
    context_desc = MARKET_CONTEXT_DESC[market_context]
    news_desc = "; ".join(negative_news_titles[:2]) if negative_news_titles else "특이 부정 뉴스 없음"

    return (
        f"[{grade}] {ticker}\n"
        f"- 가격 추세: {price_desc}\n"
        f"- 시장 상황: {context_desc}\n"
        f"- 관련 뉴스: {news_desc}\n"
        f"- 행동 제안: {ACTION_MAP[grade]}"
    )
