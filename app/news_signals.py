"""뉴스 부정성 판단 (요구사항 5.4-(2)) — 가격 신호와 독립적인 선행 트리거."""
import json
import re
from pathlib import Path

NEWS_DIR = Path(__file__).resolve().parent.parent / "data" / "news"

CATEGORY_PATTERNS = {
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


def has_independent_news_signal(ticker: str, news_dir: Path = NEWS_DIR) -> bool:
    """가격 데이터 없이 뉴스만으로 부정 신호 여부를 판단(독립적 선행 트리거)."""
    classified = classify_ticker_news(ticker, news_dir)
    return any(c["category"] != "other" and c["sentiment"] == "negative" for c in classified)
