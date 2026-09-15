"""추세 이탈 조기 감지 알림 시스템의 매일 자동 스캔 파이프라인 진입점."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.benchmark_data import BENCHMARK_TICKER, SECTOR_MAP
from app.benchmark_data import DATA_DIR as BENCH_DIR
from app.benchmark_data import collect_and_save as collect_benchmark
from app.grading import GRADE_NONE, grade_signal
from app.market_context import classify_market_context
from app.news_data import collect_and_save as collect_news
from app.news_signals import classify_ticker_news
from app.notifier import send_notification
from app.notify_format import format_alert_message
from app.price_data import DATA_DIR as PRICE_DIR
from app.price_data import collect_and_save as collect_prices
from app.signals import price_decline_pct
from app.watchlist import load_watchlist

sys.stdout.reconfigure(encoding="utf-8")

LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "logs" / "scan_log.jsonl"


def _grade_ticker(ticker: str, benchmark_close: pd.Series, failed_news: list[str]) -> tuple[str, str]:
    close = pd.read_csv(PRICE_DIR / f"{ticker}.csv", index_col=0)["Close"]
    pct_series = price_decline_pct(close)
    pct = pct_series.iloc[-1] if pd.notna(pct_series.iloc[-1]) else None
    price_signal_now = pct is not None and pct <= -5.0

    market_ctx = None
    if price_signal_now and ticker in SECTOR_MAP:
        sector_close = pd.read_csv(BENCH_DIR / f"{SECTOR_MAP[ticker]}.csv", index_col=0)["Close"]
        market_ctx = classify_market_context(benchmark_close, sector_close).iloc[-1]

    news_items = [] if ticker in failed_news else classify_ticker_news(ticker)
    grade = grade_signal(pct if price_signal_now else None, news_items)

    if grade != GRADE_NONE:
        neg_titles = [n["title"] for n in news_items if n["sentiment"] == "negative"]
        message = format_alert_message(ticker, grade, pct if price_signal_now else None, market_ctx, neg_titles)
        send_notification(message)

    return grade, ("sent" if grade != GRADE_NONE else "no_signal")


def run_scan() -> dict:
    watchlist = load_watchlist()
    tickers = watchlist["holdings"] + watchlist["watch"]

    failed_price = collect_prices()
    failed_news = collect_news()
    failed_benchmark = collect_benchmark()

    benchmark_close = pd.read_csv(BENCH_DIR / f"{BENCHMARK_TICKER.lstrip('^')}.csv", index_col=0)["Close"]

    grades: dict[str, str] = {}
    sent_count = 0
    for ticker in tickers:
        if ticker in failed_price:
            grades[ticker] = "데이터없음"
            continue
        grade, status = _grade_ticker(ticker, benchmark_close, failed_news)
        grades[ticker] = grade
        if status == "sent":
            sent_count += 1

    record = {
        "date": datetime.now().astimezone().date().isoformat(),
        "grades": grades,
        "notifications_sent": sent_count,
        "failed_tickers": {"price": failed_price, "news": failed_news, "benchmark": failed_benchmark},
    }

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def main() -> int:
    record = run_scan()
    print(f"스캔 완료: {record['date']} - 알림 {record['notifications_sent']}건 발송")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
