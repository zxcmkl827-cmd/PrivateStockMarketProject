"""보유/관심종목의 최근 뉴스 수집 (Google News RSS)."""
import json
import sys
import urllib.parse
from pathlib import Path

import feedparser

from app.watchlist import load_watchlist

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "news"
PER_TICKER_LIMIT = 15

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


def _rss_url(ticker: str) -> str:
    company = COMPANY_NAMES.get(ticker, "")
    query = urllib.parse.quote(f"{ticker} {company} stock".strip())
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


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


def save_news(results: dict[str, list[dict]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for ticker, items in results.items():
        with open(DATA_DIR / f"{ticker}.json", "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)


def collect_and_save() -> list[str]:
    watchlist = load_watchlist()
    tickers = watchlist["holdings"] + watchlist["watch"]
    results, failed = fetch_news(tickers)
    save_news(results)
    if failed:
        print(f"[실패] 뉴스 수집 실패 티커: {failed}", file=sys.stderr)
    return failed


if __name__ == "__main__":
    collect_and_save()
