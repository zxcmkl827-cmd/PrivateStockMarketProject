"""모니터링 대상 종목(보유/관심) 설정 파일 로더."""
import json
import sys
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "watchlist.json"
MAX_TICKERS = 10


def load_watchlist(path: Path = DEFAULT_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    holdings = data.get("holdings", [])
    watch = data.get("watch", [])
    total = len(holdings) + len(watch)

    if total >= MAX_TICKERS:
        print(
            f"[경고] 모니터링 대상이 {total}개입니다. "
            f"소규모 모니터링 원칙(10개 미만)을 초과했습니다.",
            file=sys.stderr,
        )

    return {"holdings": holdings, "watch": watch}
