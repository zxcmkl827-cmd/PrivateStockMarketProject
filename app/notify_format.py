"""알림 메시지 포맷 (요구사항 5.6): 종목명·등급·판단 근거·행동 제안."""
from app.grading import (
    GRADE_NONE,
    GRADE_REDUCE,
    GRADE_SELL,
    GRADE_WATCH,
    REDUCE_SCORE_THRESHOLD,
)

ACTION_MAP = {
    GRADE_WATCH: "특별한 조치 없이 계속 지켜보기",
    GRADE_REDUCE: "비중 축소를 검토해볼 것",
    GRADE_SELL: "매도를 적극 검토할 것",
    GRADE_NONE: "조치 불필요",
}

MARKET_CONTEXT_DESC = {
    "market_wide": "시장 전체 조정과 함께 하락 (종목 고유 문제로 단정하기 어려움)",
    "market_wide_news": "가격 데이터만으로는 종목 고유 하락으로 보이나, 공통 시장 뉴스(금리·인플레이션 등)가 시장 전체 부담을 시사함",
    "stock_specific": "시장 전체와 무관한 종목 고유 하락으로 보임",
    # None은 가격 하락 신호가 없을 때뿐 아니라, 하락 신호는 있어도 섹터 매핑이 없는 종목이라
    # market_context 자체를 계산하지 않은 경우에도 나온다 — "가격 하락 신호 없음"이라고 단정하지 않는다.
    None: "시장 상황 판단 불가",
}

NEWS_CATEGORY_LABELS = {
    "earnings_guidance": "실적/가이던스",
    "regulatory_legal_political": "규제/소송/정치",
    "analyst_rating": "애널리스트 하향",
    "other": "기타 부정 이슈",
}

# 200자는 카카오 미리보기(KAKAO_PREVIEW_SAFE_LENGTH)와 무관하게 사용자가 직접 요구한 상한이다
# (2026-09-16). 실제로는 뉴스 카테고리 4종 전부가 붙는 최악의 경우도 약 120자라 이 상한을 넘지
# 않지만, 문구가 늘어날 가능성에 대비해 안전장치로 남겨둔다.
COMMENT_MAX_CHARS = 200


def _build_reasoning_comment(
    grade: str,
    price_pct_change: float | None,
    market_context: str | None,
    bases: list[str],
    score: float | None,
    news_available: bool,
) -> str:
    """이 등급으로 판단한 근거를 200자 이내 서술로 요약한다(요구사항: 이메일 상세 리포트 보강).

    긍정/부정 판단에 실제로 쓰인 근거(bases)만 있는 그대로 서술한다 — evaluate_signal이
    계산하지 않는 별도의 '긍정 점수'는 만들어내지 않는다(부정 신호 부재 = 긍정으로 서술).
    단, 뉴스 수집 자체가 실패한 종목(news_available=False)은 '근거 없음'과 구분해야 한다 —
    수집 실패를 '문제 없음'으로 읽으면 실제 하락 신호를 놓칠 위험이 있다(recall 우선 원칙).
    """
    parts = []
    parts.append(f"가격 {price_pct_change:.1f}% 하락" if price_pct_change is not None else "가격 하락 신호는 없음")

    if not news_available:
        parts.append("뉴스 수집 실패로 뉴스 근거 확인 불가")
    else:
        news_cats = [b.removeprefix("news_") for b in bases if b.startswith("news_")]
        if news_cats:
            labels = ", ".join(NEWS_CATEGORY_LABELS.get(c, c) for c in news_cats)
            parts.append(f"부정 뉴스({labels}) 확인됨")
        else:
            parts.append("부정 뉴스 근거는 없음")

    if market_context == "market_wide":
        parts.append("시장 전체 조정 동반이라 종목 고유 문제로 단정하기 어려움")
    elif market_context == "market_wide_news":
        parts.append("공통 시장 뉴스가 전체 부담을 시사")
    elif market_context == "stock_specific":
        parts.append("종목 고유 하락으로 판단됨")

    if grade == GRADE_SELL:
        conclusion = "가격 하락과 강한 부정 뉴스가 동시 확인되어 매도로 판단"
    elif grade == GRADE_REDUCE:
        if score is None:
            conclusion = "복수 근거가 결합되어 비중축소로 판단"
        else:
            conclusion = f"근거 점수 {score:.1f}점(문턱 {REDUCE_SCORE_THRESHOLD})으로 비중축소 문턱을 넘어 비중축소로 판단"
    elif grade == GRADE_WATCH:
        conclusion = "가격·뉴스 중 일부 신호만 문턱 미만으로 확인돼 유지관찰로 판단"
    else:
        conclusion = "특이 신호가 확인되지 않음"

    comment = ". ".join(parts) + f". {conclusion}."
    if len(comment) > COMMENT_MAX_CHARS:
        comment = comment[: COMMENT_MAX_CHARS - 1].rstrip() + "…"
    return comment


def _format_prev_ohlc(prev_open: float | None, prev_close: float | None, price_as_of: str | None) -> str:
    """가격 데이터상 가장 최근 거래일의 시가/종가를 날짜와 함께 표시한다.

    자동 스캔은 22:00 UTC(미국 정규장 마감 이후)에 실행되어 이 값이 항상 "전일"이라고 단정할 수
    없다(critical-reviewer 지적, 2026-09-16) — 그래서 "전일"이라 부르지 않고 실제 거래일 날짜를
    함께 표시해 오독 여지를 없앤다.
    """
    if prev_open is None or prev_close is None:
        return "가격 데이터 없음"
    as_of = f"{price_as_of} " if price_as_of else ""
    return f"{as_of}시가 {prev_open:.2f} / 종가 {prev_close:.2f}"


_OUTCOME_LABELS = {"데이터없음": "판정불가"}


def _format_judgment_history(history: dict | None) -> str:
    """해당 종목의 과거 알림 중 판정이 끝난(적중/과잉감지) 건을 최신순으로 서술하고, 아직
    1주/2주가 안 지나 대기중인 건수는 별도로 붙인다(app/feedback.load_ticker_history 참고)."""
    history = history or {"shown": [], "pending_count": 0}
    shown = history.get("shown", [])
    pending = history.get("pending_count", 0)
    if not shown and not pending:
        return "과거 판단 이력 없음(첫 알림)"
    if shown:
        text = "; ".join(f"{h['date']} {h['grade']}→{_OUTCOME_LABELS.get(h['outcome'], h['outcome'])}" for h in shown)
    else:
        text = "판정 완료된 과거 이력 없음"
    if pending:
        text += f" (판정대기 {pending}건 별도)"
    return text


def format_alert_message(
    ticker: str,
    grade: str,
    price_pct_change: float | None,
    market_context: str | None,
    matched_news: list[dict],
    bases: list[str],
    score: float | None,
    news_available: bool = True,
    prev_open: float | None = None,
    prev_close: float | None = None,
    price_as_of: str | None = None,
    judgment_history: dict | None = None,
) -> str:
    """종목명·등급·가격추세·뉴스요약·시장상황·판단코멘트·행동제안을 포함한 알림 메시지를 생성(이메일 전용).

    prev_open/prev_close(가장 최근 거래일 시가/종가)와 judgment_history(과거 알림의 사후 검증 이력)는
    2026-09-16 사용자 요청으로 추가됨(요구사항 5.6) — 현재 등급 판단을 원자료 가격 수준 및
    과거 실적과 함께 볼 수 있도록 한다.
    """
    price_desc = (
        f"최근 10거래일 {price_pct_change:.1f}% 변동" if price_pct_change is not None else "가격 하락 신호 없음"
    )
    context_desc = MARKET_CONTEXT_DESC.get(market_context, "시장 상황 판단 불가")
    news_titles = [n["title"] for n in matched_news]
    if not news_available:
        news_desc = "뉴스 수집 실패로 확인 불가"
    else:
        news_desc = "; ".join(news_titles[:2]) if news_titles else "특이 부정 뉴스 없음"
    comment = _build_reasoning_comment(grade, price_pct_change, market_context, bases, score, news_available)

    return (
        f"[{grade}] {ticker}\n"
        f"- 최근 거래일 시가/종가: {_format_prev_ohlc(prev_open, prev_close, price_as_of)}\n"
        f"- 가격 추세: {price_desc}\n"
        f"- 시장 상황: {context_desc}\n"
        f"- 관련 뉴스: {news_desc}\n"
        f"- 판단 코멘트: {comment}\n"
        f"- 과거 판단 이력: {_format_judgment_history(judgment_history or [])}\n"
        f"- 행동 제안: {ACTION_MAP[grade]}"
    )


GRADE_PRIORITY = {GRADE_SELL: 0, GRADE_REDUCE: 1, GRADE_WATCH: 2}

# 카카오톡 "나에게 보내기" 기본 텍스트 템플릿은 미리보기에서 약 200자 내외만 노출하고, 초과분은
# "자세히 보기" 버튼(link.web_url)으로 연결된다(실측 확인, 2026-09-15). 이 프로젝트는 로컬 스크립트만
# 사용하고 별도 웹 호스팅이 없어 그 링크를 열어도 상세 내용을 볼 수 없다. 그래서 카카오톡에는 미리보기
# 안에서 전부 보이는 짧은 요약만 보내고, 뉴스 제목 등 상세 근거는 이메일로 분리해 보낸다.
KAKAO_PREVIEW_SAFE_LENGTH = 180


def _grade_breakdown(grades: list[str]) -> str:
    counts = {grade: sum(1 for g in grades if g == grade) for grade in (GRADE_SELL, GRADE_REDUCE, GRADE_WATCH)}
    return ", ".join(f"{grade} {n}건" for grade, n in counts.items() if n)


def format_kakao_summary(
    alerts: list[tuple[str, str, float | None]], max_chars: int = KAKAO_PREVIEW_SAFE_LENGTH
) -> list[str]:
    """카카오톡 미리보기 안에서 "자세히 보기" 없이 전체가 보이는 종목별 한 줄 요약을 만든다.

    (등급, 티커, 가격등락률)을 받아 매도>비중축소>유지관찰 순으로 정렬하고, 메시지가
    max_chars를 넘으면 등급 우선순위를 유지한 채 최소 건수로 나눈다 — 평소엔 1건.
    """
    ordered = sorted(alerts, key=lambda item: GRADE_PRIORITY.get(item[0], 99))
    total = len(alerts)
    breakdown = _grade_breakdown([grade for grade, _, _ in alerts])
    base_header = f"[추세 이탈 알림] 총 {total}건 ({breakdown})"
    body_budget = max(max_chars - len(base_header) - len(" - 9/9"), 30)

    lines = [
        f"[{grade}] {ticker} {f'{pct:+.1f}%' if pct is not None else '가격신호 없음'}" for grade, ticker, pct in ordered
    ]

    chunks: list[list[str]] = [[]]
    current_len = 0
    for line in lines:
        entry_len = len(line) + 1
        if current_len + entry_len > body_budget and chunks[-1]:
            chunks.append([])
            current_len = 0
        chunks[-1].append(line)
        current_len += entry_len

    total_parts = len(chunks)
    messages = []
    for i, chunk in enumerate(chunks, start=1):
        header = base_header + (f" - {i}/{total_parts}" if total_parts > 1 else "")
        messages.append("\n".join([header, *chunk]))
    return messages


def format_email_report(alerts: list[tuple[str, str]], common_news_titles: list[str] | None = None) -> str:
    """이메일 본문: 뉴스 제목·시장상황·행동제안을 포함한 상세 내용을 등급 우선순위로 정렬해 담는다.

    이메일은 카카오톡과 달리 미리보기 길이 제한이 없어 분할하지 않는다. 특정 종목에 국한되지
    않는 공통(시장 전체) 뉴스가 있으면 종목별 블록과 중복되지 않도록 상단에 한 번만 넣는다.
    """
    ordered = sorted(alerts, key=lambda item: GRADE_PRIORITY.get(item[0], 99))
    breakdown = _grade_breakdown([grade for grade, _ in alerts])
    sections = [f"[추세 이탈 알림 상세 리포트] 총 {len(alerts)}건 ({breakdown})"]
    if common_news_titles:
        sections.append("[오늘의 공통 시장 뉴스]\n" + "\n".join(f"- {t}" for t in common_news_titles))
    sections.extend(message for _, message in ordered)
    return "\n\n".join(sections)
