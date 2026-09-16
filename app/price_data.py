"""보유/관심종목의 일별 시가·종가·거래량 수집."""
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

from app.watchlist import load_watchlist

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "prices"
MIN_TRADING_DAYS = 20
FETCH_PERIOD = "2mo"  # 최근 20거래일 확보를 위한 여유 기간(주말/휴장일 포함)


def fetch_price_history(tickers: list[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """티커별 종가·거래량 이력을 수집한다. (성공 결과, 실패 티커 목록)을 반환."""
    results: dict[str, pd.DataFrame] = {}
    failed: list[str] = []

    for ticker in tickers:
        try:
            df = yf.Ticker(ticker).history(period=FETCH_PERIOD)[["Open", "Close", "Volume"]].dropna()
        except Exception:  # noqa: BLE001 - 개별 티커 실패가 전체 수집을 막아선 안 됨
            failed.append(ticker)
            continue

        if len(df) < MIN_TRADING_DAYS:
            failed.append(ticker)
            continue

        results[ticker] = df.tail(MIN_TRADING_DAYS)

    return results, failed


def save_price_history(results: dict[str, pd.DataFrame]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for ticker, df in results.items():
        df.to_csv(DATA_DIR / f"{ticker}.csv")


def collect_and_save() -> list[str]:
    watchlist = load_watchlist()
    tickers = watchlist["holdings"] + watchlist["watch"]
    results, failed = fetch_price_history(tickers)
    save_price_history(results)
    if failed:
        print(f"[실패] 가격 데이터 수집 실패 티커: {failed}", file=sys.stderr)
    return failed


if __name__ == "__main__":
    collect_and_save()
