"""알림 판단 정확도 사후 검증 리포트 + 근거 가중치 자동 조정 (요구사항 5.8).

'매도'의 가격+강한뉴스 동시확인 구조 규칙(app/grading.py)은 이 자동조정 대상이 아니다 —
사용자 확인(2026-09-15)에 따라 유지관찰/비중축소 경계에 쓰이는 근거별 가중치만 조정한다.
안전장치: 근거당 최소 표본 수 미달 시 조정 안 함, 1회 조정 폭 제한, 가중치 상하한, 전체 변경 이력 로그.

1거래일 후 종가 판정("1day")은 리포트·알림 이력 표시 전용이다(2026-09-16 사용자 확정). 애초
가격 기반 근거(price_decline류)를 1일 판정으로 가중치 자동조정에도 넣으려 했으나,
critical-reviewer 검토로 이 근거가 원래 10거래일 누적 하락을 잡는 지표라 "바로 다음
거래일 -2% 추가하락"을 적중 기준으로 쓰면 구조적으로 적중률이 낮게 나와 가중치가 하한(0.2)에
수렴할 위험이 확인됨 — 자동조정은 근거 유형과 무관하게 여전히 1주/2주 판정만 사용한다.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

from app.grading import WEIGHTS_PATH, load_weights

SCAN_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "logs" / "scan_log.jsonl"
FEEDBACK_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "logs" / "feedback_report.jsonl"
WEIGHT_ADJUST_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "logs" / "weight_adjustments.jsonl"

EVAL_WINDOWS = {"1day": 1, "1week": 5, "2week": 10}  # 거래일 수. 1day는 리포트 전용(가중치 미반영)
HIT_THRESHOLD_PCT = -2.0
JUDGED_GRADES = {"유지관찰", "비중축소", "매도"}

MIN_SAMPLES = 10
STEP_UP, STEP_DOWN = 1.1, 0.9
MIN_WEIGHT, MAX_WEIGHT = 0.2, 3.0
HIT_RATE_HIGH, HIT_RATE_LOW = 0.6, 0.4


def _load_alerts() -> list[dict]:
    """scan_log.jsonl에서 판정 대상 알림을 모은다.

    하루에 스캔을 여러 번 재실행하면 같은 (date, ticker) 레코드가 중복 기록될 수 있는데,
    중복 제거 없이 집계하면 최소 표본(MIN_SAMPLES) 안전장치가 재실행 횟수만으로 무력화된다.
    그래서 (date, ticker)당 마지막 레코드만 남긴다.
    """
    by_key: dict[tuple[str, str], dict] = {}
    if not SCAN_LOG_PATH.exists():
        return []
    with open(SCAN_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            reasons = record.get("reasons", {})
            for ticker, grade in record["grades"].items():
                if grade in JUDGED_GRADES:
                    ticker_reasons = reasons.get(ticker, {})
                    # 스캔이 주말에도 매일 실행돼 "오늘" 날짜가 실제 거래일과 다를 수 있다
                    # (critical-reviewer 지적, 2026-09-16). price_as_of(실제 가격 기준 거래일)가
                    # 있으면 그것을 판정 기준일로 쓴다 — 금/토/일 재실행이 모두 같은 금요일
                    # 거래일을 기준으로 하면 하나의 키로 합쳐져 표본 중복도 함께 막는다.
                    effective_date = ticker_reasons.get("price_as_of") or record["date"]
                    by_key[(effective_date, ticker)] = {
                        "date": effective_date,
                        "ticker": ticker,
                        "grade": grade,
                        "bases": ticker_reasons.get("bases", []),
                        "score": ticker_reasons.get("score"),
                    }
    return list(by_key.values())


def _evaluate_alert(alert: dict) -> dict:
    ticker = alert["ticker"]
    close = yf.Ticker(ticker).history(start=alert["date"])["Close"]

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


def _resolved_outcome_with_window(result: dict) -> tuple[str | None, str | None]:
    """표시용 종합 판정과 그 판정이 어느 창(2week/1week/1day)에서 나왔는지 함께 반환한다.

    1일 판정은 가중치 자동조정에는 쓰지 않는 리포트 전용 값이라(_resolved_outcome_for_weighting
    참고), 이 폴백만으로 이력을 확정 표시하면 오해를 살 수 있다 — 창 라벨을 함께 노출해 구분한다
    (critical-reviewer 지적, 2026-09-16).
    """
    for label in ("2week", "1week", "1day"):
        if result.get(label) in ("적중", "과잉감지"):
            return result[label], label
    return None, None


def _resolved_outcome(result: dict) -> str | None:
    """표시용 종합 판정: 2주 → 1주 → 1일 순으로 먼저 확정된 것을 쓴다. 전부 대기중이면 None."""
    outcome, _window = _resolved_outcome_with_window(result)
    return outcome


def _resolved_outcome_for_weighting(result: dict) -> str | None:
    """가중치 자동조정 집계 전용 판정: 2주 → 1주만 쓴다(1일 판정은 절대 쓰지 않음).

    1일 판정을 가중치 조정에 넣으면 price_decline류(원래 10거래일 누적 하락 지표)가
    "바로 다음 거래일 -2% 추가하락" 기준으로 채점돼 구조적으로 적중률이 낮게 나오고
    가중치가 하한(0.2)에 수렴할 위험이 있다(critical-reviewer 지적, 2026-09-16 사용자 확정
    — 1일 판정은 리포트·이력 표시 전용으로만 쓴다).
    """
    for label in ("2week", "1week"):
        if result.get(label) in ("적중", "과잉감지"):
            return result[label]
    return None


def _aggregate_basis_stats(results: list[dict]) -> dict[str, dict]:
    """근거 유형별 적중률을 집계한다(1주/2주 판정만 사용, 근거 유형과 무관하게 동일).

    score가 None인 레코드는 '매도'의 가격+강한뉴스 구조적 규칙으로 발동된 것이라 가중치와
    무관하게 결정됐다. 이런 레코드를 그대로 집계하면 가중치를 전혀 쓰지 않은 판정 결과가
    news_* 가중치 조정에 섞여 들어가므로 제외한다.
    """
    stats: dict[str, dict] = {}
    for r in results:
        if r.get("score") is None:
            continue
        outcome = _resolved_outcome_for_weighting(r)
        if outcome is None:
            continue
        for basis in r.get("bases", []):
            s = stats.setdefault(basis, {"hits": 0, "total": 0})
            s["total"] += 1
            if outcome == "적중":
                s["hits"] += 1
    return stats


def _last_adjustment_sample_sizes() -> dict[str, int]:
    """근거별로 가장 최근 자동조정이 적용된 시점의 표본 수(sample_size)를 반환한다."""
    last: dict[str, int] = {}
    if not WEIGHT_ADJUST_LOG_PATH.exists():
        return last
    with open(WEIGHT_ADJUST_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            for change in json.loads(line).get("changes", []):
                last[change["basis"]] = change["sample_size"]
    return last


def adjust_weights(results: list[dict]) -> list[dict]:
    """근거 유형별 적중률을 기준으로 config/signal_weights.json을 조정하고 변경 이력을 남긴다.

    build_feedback_report()는 매일 실행되며 그때마다 누적된 전체 표본으로 이 함수를 다시 부른다.
    직전 조정 이후 새 표본이 최소표본(MIN_SAMPLES)만큼 더 쌓이지 않았으면 재조정을 건너뛴다 —
    이 가드가 없으면 같은 표본 풀이 매일 재평가되어 "1회 조정 폭 ±10%" 제한이 사실상 매일 복리로
    적용되는 것과 같아져 안전장치가 무력화된다(critical-reviewer 지적, 2026-09-16). 1일 단기 트랙은
    표본이 뉴스 기반 근거보다 훨씬 빨리 쌓이므로 이 가드가 특히 중요하다.
    """
    stats = _aggregate_basis_stats(results)
    weights = load_weights()
    last_adjusted = _last_adjustment_sample_sizes()
    changes = []

    for basis, s in stats.items():
        if s["total"] < MIN_SAMPLES or basis not in weights:
            continue
        if s["total"] < last_adjusted.get(basis, 0) + MIN_SAMPLES:
            continue
        hit_rate = s["hits"] / s["total"]
        old_weight = weights[basis]
        if hit_rate >= HIT_RATE_HIGH:
            new_weight = min(old_weight * STEP_UP, MAX_WEIGHT)
        elif hit_rate <= HIT_RATE_LOW:
            new_weight = max(old_weight * STEP_DOWN, MIN_WEIGHT)
        else:
            continue
        if abs(new_weight - old_weight) < 1e-9:
            continue
        weights[basis] = round(new_weight, 4)
        changes.append(
            {"basis": basis, "old_weight": old_weight, "new_weight": weights[basis],
             "hit_rate": round(hit_rate, 3), "sample_size": s["total"]}
        )

    if changes:
        with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
            json.dump(weights, f, ensure_ascii=False, indent=2)
        WEIGHT_ADJUST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {"date": datetime.now(timezone.utc).date().isoformat(), "changes": changes}
        with open(WEIGHT_ADJUST_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return changes


def load_ticker_history(ticker: str, before_date: str, limit: int = 3) -> dict:
    """feedback_report.jsonl에서 해당 티커의 과거 알림 판정 이력을 조회한다.

    오늘(before_date) 발생한 알림은 아직 사후 검증 대상이 아니므로 제외한다. 매일 자동 스캔은
    app/main.py 실행 후 app/feedback.py를 실행하는 순서라(CLAUDE.md 기술스택 절), 이 파일을 읽는
    시점에는 어제까지의 판정 결과만 반영돼 있다 — 오늘 새로 만든 알림 자체가 섞여 들어올 일은 없지만
    재실행 등 예외 상황에 대비해 방어적으로 제외한다.

    하락 추세 종목은 매일 연속으로 알림이 뜨는데, 날짜 최신순으로만 limit건을 자르면 발생 직후라
    아직 1주/2주가 안 지난 "대기중" 레코드만 계속 노출되고 실제 적중/과잉감지 실적은 영원히 안
    보일 수 있다(critical-reviewer 지적, 2026-09-16). 그래서 판정이 끝난(적중/과잉감지/데이터없음)
    레코드를 우선 최신순으로 최대 limit건 반환하고, 대기중 건수는 총량만 별도로 알려준다.
    """
    if not FEEDBACK_LOG_PATH.exists():
        return {"shown": [], "pending_count": 0}
    by_date: dict[str, dict] = {}
    with open(FEEDBACK_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("ticker") == ticker and record.get("date") < before_date:
                # 하루에 스캔을 여러 번 재실행하면 같은 (date, ticker)가 중복 기록될 수 있어
                # (_load_alerts와 동일한 문제), 날짜당 하나만 남긴다.
                outcome, window = _resolved_outcome_with_window(record)
                by_date[record["date"]] = {
                    "date": record["date"],
                    "grade": record.get("grade"),
                    "outcome": outcome or record.get("status") or "대기중",
                    "window": window,
                }
    all_records = sorted(by_date.values(), key=lambda r: r["date"], reverse=True)
    resolved = [r for r in all_records if r["outcome"] != "대기중"]
    pending = [r for r in all_records if r["outcome"] == "대기중"]
    return {"shown": resolved[:limit], "pending_count": len(pending)}


def build_feedback_report() -> list[dict]:
    """scan_log.jsonl의 모든 알림에 대해 근거 트랙별(가격=1일, 뉴스=1주/2주) 기준으로
    적중/과잉감지를 판정해 리포트로 저장하고, 근거별 적중률에 따라 가중치를 조정한다."""
    alerts = _load_alerts()
    results = [_evaluate_alert(a) for a in alerts]

    FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK_LOG_PATH, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in results)

    adjust_weights(results)
    return results


if __name__ == "__main__":
    report = build_feedback_report()
    judged = [r for r in report if _resolved_outcome(r) is not None]
    print(f"평가 대상 알림: {len(report)}건, 판정 가능: {len(judged)}건")
