"""뉴스 부정성 판단 (요구사항 5.4-(2)) — 가격 신호와 독립적인 선행 트리거."""
import json
import re
from pathlib import Path

NEWS_DIR = Path(__file__).resolve().parent.parent / "data" / "news"
MARKET_NEWS_FILENAME = "_market.json"

CATEGORY_PATTERNS = {
    # analyst_rating을 먼저 검사한다 — earnings_guidance의 느슨한 패턴(revenue/outlook 등)이
    # "애널리스트가 실적 전망을 이유로 목표주가를 내렸다" 같은 기사까지 먼저 가로채면 뉴스 유형별
    # 근거 집계(app/feedback.py)가 analyst_rating 표본을 영원히 못 모으는 문제를 피하기 위함.
    "analyst_rating": re.compile(
        r"downgrades?\b.{0,20}(stock|shares|to (sell|underperform|hold|neutral|equal.?weight|underweight))|"
        r"(price target).{0,25}(cut|lower|reduc)|(cut|lower|reduc).{0,25}(price target)|"
        r"underweight rating|sell rating|"
        r"analyst.{0,20}(downgrades?|cuts?|lowers?).{0,20}(rating|price target|estimate)",
        re.IGNORECASE,
    ),
    "earnings_guidance": re.compile(
        r"earnings|guidance|revenue|forecast|outlook|q[1-4]\b|profit|beat|miss", re.IGNORECASE
    ),
    "regulatory_legal_political": re.compile(
        r"lawsuit|\bsue\b|sued|antitrust|regulat|investigat|probe|tariff|\bftc\b|"
        r"\bdoj\b|\bsec\b|\bban\b|\bfine\b|court|fraud|sanction", re.IGNORECASE
    ),
}

NEGATIVE_PATTERN = re.compile(
    r"miss|cut|downgrade|warn|weak|declin|drop|fall|lawsuit|\bsue\b|sued|fraud|"
    r"investigat|probe|antitrust|\bban\b|\bfine\b|recall|scandal|\bloss\b|plunge|slump|scrutiny",
    re.IGNORECASE,
)

# 종목 뉴스용 NEGATIVE_PATTERN은 거시경제 표현(금리 인상, 국채 금리 급등 등)을 거의 못 잡는다.
# 공통(시장 전체) 뉴스의 악재 여부 판단에는 이 패턴을 추가로 함께 쓴다.
MACRO_NEGATIVE_PATTERN = re.compile(
    r"hike|raises?.{0,20}rate|rate (rise|hike)|yield.*(high|surge|climb|jump|rise)|"
    r"inflation.*(persist|surge|concern|fear|worry|rise|hot)|recession|correction|sell-?off|\brout\b|"
    r"plunge|slump|volatil|downturn|bear market|contraction|tighten",
    re.IGNORECASE,
)


def classify_news_item(title: str) -> dict:
    category = "other"
    for name, pattern in CATEGORY_PATTERNS.items():
        if pattern.search(title):
            category = name
            break
    sentiment = "negative" if NEGATIVE_PATTERN.search(title) else "neutral"
    return {"title": title, "category": category, "sentiment": sentiment}


def classify_ticker_news(ticker: str, news_dir: Path = NEWS_DIR) -> list[dict]:
    path = news_dir / f"{ticker}.json"
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    return [classify_news_item(item["title"]) for item in items]


def classify_common_news(news_dir: Path = NEWS_DIR, filename: str = MARKET_NEWS_FILENAME) -> list[dict]:
    """특정 종목에 국한되지 않는 공통(시장 전체/거시경제) 뉴스를 분류한다.

    개별 종목의 등급을 직접 좌우하지 않고, (1) 이메일 리포트의 참고 맥락 (2) 시장 전체 조정
    여부(market_context) 판정의 보조 입력으로만 쓰인다. 파일이 없거나 손상돼도 스캔이 막히면
    안 되므로 빈 리스트를 반환한다.
    """
    path = news_dir / filename
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    results = []
    for item in items:
        title = item.get("title", "")
        classified = classify_news_item(title)
        if classified["sentiment"] == "neutral" and MACRO_NEGATIVE_PATTERN.search(title):
            classified["sentiment"] = "negative"
        results.append(classified)
    return results


def has_independent_news_signal(ticker: str, news_dir: Path = NEWS_DIR) -> bool:
    """가격 데이터 없이 뉴스만으로 부정 신호 여부를 판단(독립적 선행 트리거)."""
    classified = classify_ticker_news(ticker, news_dir)
    return any(c["category"] != "other" and c["sentiment"] == "negative" for c in classified)
