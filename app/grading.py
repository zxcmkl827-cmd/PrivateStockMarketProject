"""3단계 등급 판정 엔진 — 유지관찰/비중축소/매도 (요구사항 5.5, 5.8, 사용자 승인 기준).

'매도'의 가격신호+강한뉴스 동시확인 요건은 구조적 규칙으로 고정한다(가중치로 무력화 불가) —
이 등급은 사용자가 그대로 실행할 계획이라 정밀도가 최우선이며, 가중치 자동조정(app/feedback.py)의
드리프트로 이 안전장치가 흔들려서는 안 된다는 사용자 확인(2026-09-15)에 따른 설계다.
유지관찰/비중축소 경계는 근거 유형별 가중치(config/signal_weights.json) 기반 점수로 판정하며,
이 가중치만 피드백 결과에 따라 자동 조정 대상이 된다.
"""
import json
from pathlib import Path

from app.signals import load_thresholds

STRONG_NEWS_CATEGORIES = {"earnings_guidance", "regulatory_legal_political"}
WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "config" / "signal_weights.json"
REDUCE_SCORE_THRESHOLD = 2.0

GRADE_NONE = "없음"
GRADE_WATCH = "유지관찰"
GRADE_REDUCE = "비중축소"
GRADE_SELL = "매도"


def load_weights(path: Path = WEIGHTS_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def evaluate_signal(pct_change: float | None, news_items: list[dict], weights: dict | None = None) -> dict:
    """가격 하락률과 뉴스 분류 결과로 등급을 판정하고, 판정에 쓰인 근거(bases)를 함께 반환한다."""
    weights = weights if weights is not None else load_weights()
    thresholds = load_thresholds()
    watch_pct = thresholds["price_decline"]["decline_pct_threshold"]
    reduce_pct = thresholds["reduce_position"]["decline_pct_threshold"]

    price_signal = pct_change is not None and pct_change <= watch_pct
    strong_price_signal = pct_change is not None and pct_change <= reduce_pct

    negative_news = [n for n in news_items if n.get("sentiment") == "negative"]
    news_categories = sorted({n["category"] for n in negative_news if n.get("category")})
    strong_category_news = any(c in STRONG_NEWS_CATEGORIES for c in news_categories)

    bases = []
    if strong_price_signal:
        bases.append("price_decline_strong")
    elif price_signal:
        bases.append("price_decline")
    bases.extend(f"news_{c}" for c in news_categories)

    # 구조적 안전장치: 가격신호 + 강한뉴스 동시확인 시에만 '매도'. 가중치로 조정 불가.
    if price_signal and strong_category_news:
        grade = GRADE_SELL
        score = None
    else:
        score = sum(weights.get(b, 0.0) for b in bases)
        if score >= REDUCE_SCORE_THRESHOLD:
            grade = GRADE_REDUCE
        elif score > 0:
            grade = GRADE_WATCH
        else:
            grade = GRADE_NONE

    return {
        "grade": grade,
        "bases": bases,
        "score": score,
        "price_pct": pct_change,
        "matched_news": negative_news,
    }


def grade_signal(pct_change: float | None, news_items: list[dict]) -> str:
    """등급 문자열만 필요한 호출부를 위한 얇은 래퍼."""
    return evaluate_signal(pct_change, news_items)["grade"]
