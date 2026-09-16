"""보유/관심종목의 최근 뉴스 수집 (Google News RSS)."""
import json
import sys
import urllib.parse
from pathlib import Path

import feedparser

from app.watchlist import load_watchlist

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "news"
PER_TICKER_LIMIT = 15
MARKET_NEWS_FILENAME = "_market.json"
MARKET_NEWS_LIMIT = 15
# 특정 종목에 국한되지 않는 공통(시장 전체/거시경제) 뉴스 — 등급 판정에는 쓰지 않고 참고 맥락으로만 사용.
MARKET_NEWS_QUERY = "stock market OR Fed interest rate OR inflation"

# RSS 검색 정확도를 높이기 위한 티커→회사명 매핑. 신규 종목 추가 시 함께 갱신 필요.
COMPANY_NAMES = {
    "GOOGL": "Alphabet",
    "MSFT": "Microsoft",
    "PEP": "PepsiCo",
    "COST": "Costco",
    "TSLA": "Tesla",
    "AMD": "AMD",
    "AMZN": "Amazon",
    "ORCL": "Oracle",
    "MCD": "McDonald's",
}


def _search_url(query: str) -> str:
    encoded = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


def _rss_url(ticker: str) -> str:
    company = COMPANY_NAMES.get(ticker, "")
    return _search_url(f"{ticker} {company} stock".strip())


def fetch_news(tickers: list[str]) -> tuple[dict[str, list[dict]], list[str]]:
    """티커별 최근 뉴스를 수집한다. (성공 결과, 실패 티커 목록)을 반환."""
    results: dict[str, list[dict]] = {}
    failed: list[str] = []

    for ticker in tickers:
        try:
            feed = feedparser.parse(_rss_url(ticker))
        except Exception:  # noqa: BLE001 - 개별 티커 실패가 전체 수집을 막아선 안 됨
            failed.append(ticker)
            continue

        entries = feed.entries[:PER_TICKER_LIMIT]
        if not entries:
            failed.append(ticker)
            continue

        results[ticker] = [
            {"title": e.get("title", ""), "link": e.get("link", ""), "published": e.get("published", "")}
            for e in entries
        ]

    return results, failed


def fetch_market_news() -> list[dict]:
    """종목에 국한되지 않는 공통(시장 전체/거시경제) 뉴스를 수집한다.

    등급 판정에는 쓰지 않는 참고 맥락용이라, 실패해도 빈 리스트를 반환해 스캔을 막지 않는다.
    """
    try:
        feed = feedparser.parse(_search_url(MARKET_NEWS_QUERY))
    except Exception:  # noqa: BLE001 - 참고 맥락용 데이터라 실패해도 스캔을 막지 않는다
        return []
    entries = feed.entries[:MARKET_NEWS_LIMIT]
    return [
        {"title": e.get("title", ""), "link": e.get("link", ""), "published": e.get("published", "")}
        for e in entries
    ]


def save_news(results: dict[str, list[dict]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for ticker, items in results.items():
        with open(DATA_DIR / f"{ticker}.json", "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)


def save_market_news(items: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / MARKET_NEWS_FILENAME, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def collect_and_save() -> tuple[list[str], bool]:
    """(종목별 뉴스 수집 실패 목록, 공통 시장 뉴스 수집 실패 여부)를 반환한다."""
    watchlist = load_watchlist()
    tickers = watchlist["holdings"] + watchlist["watch"]
    results, failed = fetch_news(tickers)
    save_news(results)

    market_items = fetch_market_news()
    market_failed = not market_items
    if not market_failed:
        save_market_news(market_items)  # 실패 시 직전 성공분을 그대로 남겨 일시 장애로 데이터가 사라지지 않게 한다

    if failed:
        print(f"[실패] 뉴스 수집 실패 티커: {failed}", file=sys.stderr)
    if market_failed:
        print("[실패] 공통 시장 뉴스 수집 실패(0건)", file=sys.stderr)
    return failed, market_failed


if __name__ == "__main__":
    collect_and_save()
