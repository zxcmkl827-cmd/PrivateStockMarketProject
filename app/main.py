"""추세 이탈 조기 감지 알림 시스템의 매일 자동 스캔 파이프라인 진입점."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.benchmark_data import BENCHMARK_TICKER, SECTOR_MAP
from app.benchmark_data import DATA_DIR as BENCH_DIR
from app.benchmark_data import collect_and_save as collect_benchmark
from app.feedback import load_ticker_history
from app.grading import GRADE_NONE, evaluate_signal
from app.market_context import classify_market_context, refine_with_common_news
from app.news_data import collect_and_save as collect_news
from app.news_signals import classify_common_news, classify_ticker_news
from app.notifier import refresh_kakao_access_token, send_email, send_kakao_memo
from app.notify_format import (
    format_alert_message,
    format_email_report,
    format_kakao_summary,
)
from app.price_data import DATA_DIR as PRICE_DIR
from app.price_data import collect_and_save as collect_prices
from app.signals import load_thresholds, price_decline_pct
from app.watchlist import load_watchlist

sys.stdout.reconfigure(encoding="utf-8")

LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "logs" / "scan_log.jsonl"
COMMON_NEWS_LIMIT = 2


def _read_close_series(path: Path) -> pd.Series | None:
    """벤치마크/섹터 지수 CSV를 읽되, 수집 실패로 파일이 없거나 손상된 경우 None을 반환한다.

    이 값은 시장상황(market_context) 판정에만 쓰이고 가격·뉴스 기반 등급 판정과는 무관하므로,
    읽기 실패가 그날 스캔 전체를 중단시켜서는 안 된다(요구사항: 한쪽 실패가 로그 기록을 막지 않음).
    """
    try:
        return pd.read_csv(path, index_col=0)["Close"]
    except (OSError, pd.errors.EmptyDataError, KeyError):
        return None


def _grade_ticker(
    ticker: str,
    benchmark_close: pd.Series | None,
    failed_news: list[str],
    common_news_negative: bool,
    today: str,
) -> dict:
    price_df = pd.read_csv(PRICE_DIR / f"{ticker}.csv", index_col=0)
    close = price_df["Close"]
    # 정상 파이프라인은 collect_prices()가 먼저 Open 포함 CSV로 덮어써서 항상 존재하지만,
    # 수집을 건너뛴 재실행이나 마이그레이션 이전 CSV가 남아있는 경우를 대비해 방어한다
    # (critical-reviewer 지적, 2026-09-16) — 없으면 표시용 부가 정보만 생략하고 등급 판정은 그대로 진행.
    prev_open = float(price_df["Open"].iloc[-1]) if "Open" in price_df.columns else None
    prev_close = float(close.iloc[-1])
    price_as_of = str(price_df.index[-1])[:10]
    pct_series = price_decline_pct(close)
    pct = pct_series.iloc[-1] if pd.notna(pct_series.iloc[-1]) else None
    watch_pct = load_thresholds()["price_decline"]["decline_pct_threshold"]
    price_signal_now = pct is not None and pct <= watch_pct

    market_ctx = None
    if price_signal_now and ticker in SECTOR_MAP and benchmark_close is not None:
        sector_close = _read_close_series(BENCH_DIR / f"{SECTOR_MAP[ticker]}.csv")
        if sector_close is not None:
            price_context = classify_market_context(benchmark_close, sector_close).iloc[-1]
            market_ctx = refine_with_common_news(price_context, common_news_negative)

    news_available = ticker not in failed_news
    news_items = classify_ticker_news(ticker) if news_available else []
    evaluation = evaluate_signal(pct if price_signal_now else None, news_items)
    grade = evaluation["grade"]

    reasons = {
        "price_pct": evaluation["price_pct"],
        "market_context": market_ctx,
        "bases": evaluation["bases"],
        "score": evaluation["score"],
        "matched_news": [
            {"title": n["title"], "category": n["category"], "sentiment": n["sentiment"]}
            for n in evaluation["matched_news"]
        ],
    }

    message = None
    if grade != GRADE_NONE:
        message = format_alert_message(
            ticker,
            grade,
            evaluation["price_pct"],
            market_ctx,
            evaluation["matched_news"],
            evaluation["bases"],
            evaluation["score"],
            news_available,
            prev_open=prev_open,
            prev_close=prev_close,
            price_as_of=price_as_of,
            judgment_history=load_ticker_history(ticker, today),
        )

    return {"grade": grade, "reasons": reasons, "message": message}


def _send_alerts(
    alert_summaries: list[tuple[str, str, float | None]],
    alert_details: list[tuple[str, str]],
    common_news_titles: list[str],
) -> dict:
    """카카오톡=짧은 요약, 이메일=상세 리포트로 채널을 분리해 발송한다.

    카카오톡 미리보기 길이 제한 때문에 상세 근거(뉴스 제목 등)를 카카오 하나로 다 보여줄 수 없어
    나뉜 구조다. 각 채널은 독립적으로 시도하며, 한쪽이 실패해도 다른 쪽 발송과 로그 기록을 막지 않는다.
    """
    kakao_sent = 0
    kakao_errors: list[str] = []
    kakao_messages = format_kakao_summary(alert_summaries) if alert_summaries else []
    if kakao_messages:
        if os.environ.get("KAKAO_REFRESH_TOKEN"):
            for message in kakao_messages:
                try:
                    token = refresh_kakao_access_token()
                    if send_kakao_memo(message, token):
                        kakao_sent += 1
                    else:
                        kakao_errors.append("카카오 응답 실패")
                except Exception as exc:  # noqa: BLE001 - 발송 실패해도 그날의 스캔 로그는 반드시 남겨야 한다
                    kakao_errors.append(str(exc))
        else:
            kakao_errors.append("카카오 미설정")

    email_sent = False
    email_error = None
    if alert_details:
        if os.environ.get("EMAIL_SENDER") and os.environ.get("EMAIL_APP_PASSWORD"):
            try:
                body = format_email_report(alert_details, common_news_titles)
                send_email("추세 이탈 알림 상세 리포트", body)
                email_sent = True
            except Exception as exc:  # noqa: BLE001 - 발송 실패해도 그날의 스캔 로그는 반드시 남겨야 한다
                email_error = str(exc)
        else:
            email_error = "이메일 미설정"

    return {
        "kakao_summary_sent": kakao_sent,
        "kakao_summary_total": len(kakao_messages),
        "kakao_error": "; ".join(kakao_errors) or None,
        "email_detail_sent": email_sent,
        "email_error": email_error,
    }


def run_scan() -> dict:
    today = datetime.now().astimezone().date().isoformat()
    watchlist = load_watchlist()
    tickers = watchlist["holdings"] + watchlist["watch"]

    failed_price = collect_prices()
    failed_news, failed_market_news = collect_news()
    failed_benchmark = collect_benchmark()

    benchmark_close = _read_close_series(BENCH_DIR / f"{BENCHMARK_TICKER.lstrip('^')}.csv")
    common_news = classify_common_news()
    negative_common_news = [n for n in common_news if n["sentiment"] == "negative"]
    # 공통 뉴스 검색어 특성상 부정 판정 기사가 흔해서, 1건이라도 있으면 True로 두면 거의 매일
    # market_context가 market_wide_news로 보정돼 라벨의 변별력이 사라진다. 과반수 이상일 때만
    # "시장 전체 부담"으로 본다(사용자 확인 2026-09-16).
    common_news_negative = bool(common_news) and len(negative_common_news) > len(common_news) / 2
    common_news_titles = [n["title"] for n in negative_common_news][:COMMON_NEWS_LIMIT]

    grades: dict[str, str] = {}
    reasons: dict[str, dict] = {}
    alert_details: list[tuple[str, str]] = []
    alert_summaries: list[tuple[str, str, float | None]] = []
    for ticker in tickers:
        if ticker in failed_price:
            grades[ticker] = "데이터없음"
            continue
        result = _grade_ticker(ticker, benchmark_close, failed_news, common_news_negative, today)
        grades[ticker] = result["grade"]
        reasons[ticker] = result["reasons"]
        if result["message"] is not None:
            alert_details.append((result["grade"], result["message"]))
            alert_summaries.append((result["grade"], ticker, result["reasons"]["price_pct"]))

    notification = _send_alerts(alert_summaries, alert_details, common_news_titles)

    record = {
        "date": today,
        "grades": grades,
        "reasons": reasons,
        "notifications_sent": len(alert_details),
        "common_news": common_news_titles,
        **notification,
        "failed_tickers": {
            "price": failed_price,
            "news": failed_news,
            "benchmark": failed_benchmark,
            "market_news": failed_market_news,
        },
    }

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def main() -> int:
    record = run_scan()
    sent = record["notifications_sent"]
    if sent == 0:
        kakao_detail = email_detail = "발송 없음"
    else:
        kakao_detail = (
            f"{record['kakao_summary_sent']}/{record['kakao_summary_total']}건 성공"
            if not record["kakao_error"]
            else f"실패({record['kakao_error']})"
        )
        email_detail = "발송 성공" if record["email_detail_sent"] else f"미발송({record['email_error']})"
    print(
        f"스캔 완료: {record['date']} - 알림 대상 {sent}건 "
        f"(카카오 요약: {kakao_detail}, 이메일 상세: {email_detail})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
