"""알림 판단 정확도 사후 검증 리포트 (요구사항 5.8) — 리포트 전용, 임계값 자동 조정 없음."""
import json
from pathlib import Path

import yfinance as yf

SCAN_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "logs" / "scan_log.jsonl"
FEEDBACK_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "logs" / "feedback_report.jsonl"

EVAL_WINDOWS = {"1week": 5, "2week": 10}  # 거래일 수
HIT_THRESHOLD_PCT = -2.0
JUDGED_GRADES = {"유지관찰", "비중축소", "매도"}


def _load_alerts() -> list[dict]:
    alerts = []
    if not SCAN_LOG_PATH.exists():
        return alerts
    with open(SCAN_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            for ticker, grade in record["grades"].items():
                if grade in JUDGED_GRADES:
                    alerts.append({"date": record["date"], "ticker": ticker, "grade": grade})
    return alerts


def _evaluate_alert(alert: dict) -> dict:
    ticker = alert["ticker"]
    alert_date = alert["date"]
    close = yf.Ticker(ticker).history(start=alert_date)["Close"]

    result = dict(alert)
    if close.empty:
        result["status"] = "데이터없음"
        return result

    baseline = close.iloc[0]
    result["baseline_close"] = round(float(baseline), 2)

    for label, trading_days in EVAL_WINDOWS.items():
        if len(close) > trading_days:
            future_close = close.iloc[trading_days]
            pct = (future_close - baseline) / baseline * 100
            result[label] = "적중" if pct <= HIT_THRESHOLD_PCT else "과잉감지"
            result[f"{label}_pct"] = round(float(pct), 2)
        else:
            result[label] = "대기중"

    return result


def build_feedback_report() -> list[dict]:
    """scan_log.jsonl의 모든 알림에 대해 1주/2주 후 종가 기준 적중/과잉감지를 판정해 리포트로 저장."""
    alerts = _load_alerts()
    results = [_evaluate_alert(a) for a in alerts]

    FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK_LOG_PATH, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in results)

    return results


if __name__ == "__main__":
    report = build_feedback_report()
    judged = [r for r in report if r.get("1week") in ("적중", "과잉감지") or r.get("2week") in ("적중", "과잉감지")]
    print(f"평가 대상 알림: {len(report)}건, 판정 가능: {len(judged)}건")
