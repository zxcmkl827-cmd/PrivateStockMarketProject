"""벤치마크(S&P500)·섹터 지수 데이터 수집 및 종목→섹터 매핑."""
import json
import sys
from pathlib import Path

import yfinance as yf

from app.watchlist import load_watchlist

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "benchmark"
FETCH_PERIOD = "2mo"
BENCHMARK_TICKER = "^GSPC"  # S&P500 지수

# 종목 → 섹터 대표 ETF(SPDR Select Sector) 매핑. 신규 종목 추가 시 함께 갱신 필요.
SECTOR_MAP = {
    "GOOGL": "XLC",  # Communication Services
    "MSFT": "XLK",   # Information Technology
    "PEP": "XLP",    # Consumer Staples
    "COST": "XLP",   # Consumer Staples
    "TSLA": "XLY",   # Consumer Discretionary
    "AMD": "XLK",    # Information Technology
    "AMZN": "XLY",   # Consumer Discretionary
    "ORCL": "XLK",   # Information Technology
    "MCD": "XLY",    # Consumer Discretionary
}


def fetch_index(ticker: str):
    return yf.Ticker(ticker).history(period=FETCH_PERIOD)[["Close"]].dropna()


def collect_and_save() -> list[str]:
    watchlist = load_watchlist()
    tickers = watchlist["holdings"] + watchlist["watch"]

    index_tickers = {BENCHMARK_TICKER} | {SECTOR_MAP[t] for t in tickers if t in SECTOR_MAP}
    unmapped = [t for t in tickers if t not in SECTOR_MAP]
    if unmapped:
        print(f"[경고] 섹터 매핑 없는 종목: {unmapped}", file=sys.stderr)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    for index_ticker in sorted(index_tickers):
        try:
            df = fetch_index(index_ticker)
        except Exception:  # noqa: BLE001 - 개별 지수 실패가 전체 수집을 막아선 안 됨
            failed.append(index_ticker)
            continue
        if df.empty:
            failed.append(index_ticker)
            continue
        df.to_csv(DATA_DIR / f"{index_ticker.lstrip('^')}.csv")

    mapping = {t: {"sector_etf": SECTOR_MAP.get(t), "benchmark": BENCHMARK_TICKER} for t in tickers}
    with open(DATA_DIR / "ticker_sector_map.json", "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    if failed:
        print(f"[실패] 지수 수집 실패: {failed}", file=sys.stderr)
    return failed


if __name__ == "__main__":
    collect_and_save()
