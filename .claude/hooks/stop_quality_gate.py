"""Stop hook: 세션이 끝나기 전 전체 코드 길이/lint/build 검사를 강제한다.

이 버전(Claude Code 2.1.271)의 Stop hook 계약:
- exit 2 = 정지를 막고 stderr를 Claude에게 재작업 지시로 전달 (동기 실행, 신뢰 가능한 차단 방법)
- exit 0/1/3+ = 정지를 막지 않음 (exit 1도 비차단이므로 실패 시 반드시 exit 2를 써야 함)
- hook timeout이 지나면 fail-open(정지가 그냥 진행됨) — 그래서 내부 timeout을 hook timeout(60s)보다
  확실히 짧게(45s) 잡아 이 스크립트가 스스로 실패를 확정한다. 바깥 timeout에 기대지 않는다.
- stop_hook_active 필드는 알려진 버그(#54360)로 항상 false로 올 수 있어 완전히 신뢰하지 않는다.
  대신 실패 시그니처를 파일에 남겨 "직전과 같은 이유로 또 막혔는지"를 자체적으로 추정한다.
  단, 재진입/반복이라는 이유로 검사를 통과 처리하지는 않는다 — 실패면 항상 exit 2.
"""
import hashlib
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
QUALITY_CHECK = os.path.join(PROJECT_ROOT, "scripts", "quality_check.py")
STATE_FILE = os.path.join(SCRIPT_DIR, ".stop_quality_gate_state.json")
INNER_TIMEOUT = 45  # settings.json의 Stop hook timeout(60s)보다 짧게


def read_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 - 상태 파일이 없거나 깨져도 검사 자체는 계속되어야 함
        return {}


def write_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - hook은 임의의 stdin에도 절대 크래시하면 안 됨
        payload = {}
    stop_hook_active = bool(payload.get("stop_hook_active"))

    try:
        proc = subprocess.run(
            ["python3", QUALITY_CHECK, "--scope", "full", "--timeout", str(INNER_TIMEOUT - 15),
             "--fail-exit", "1", "--stderr-on-fail"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=INNER_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write(
            f"[품질 게이트] TIMEOUT({INNER_TIMEOUT}s 초과) — 전체 검사가 시간 내 끝나지 못했습니다. "
            "시간 초과는 통과 근거로 쓰지 않습니다. 검사 대상 파일 수나 무한 루프 여부를 확인한 뒤 다시 시도하세요.\n"
        )
        sys.exit(2)

    if proc.returncode == 0:
        write_state({})  # 통과 시 실패 이력 초기화
        sys.exit(0)

    detail = proc.stderr or proc.stdout or "(검사 스크립트가 상세 내용을 출력하지 않았습니다)"
    fail_hash = hashlib.sha256(detail.encode("utf-8")).hexdigest()
    prior = read_state()
    repeat_count = (prior.get("count", 0) + 1) if prior.get("hash") == fail_hash else 1
    write_state({"hash": fail_hash, "count": repeat_count})

    header = "[품질 게이트] 코드 길이/lint/build 검사 실패 — 작업을 완료 처리하지 않습니다.\n"
    if stop_hook_active or repeat_count >= 2:
        header += (
            "※ 같은 실패가 반복되고 있습니다(stop_hook_active="
            f"{stop_hook_active}, 동일 실패 {repeat_count}회 연속). 같은 수정을 무한 반복하지 말고, "
            "막힌 이유와 다음에 필요한 조치를 사용자에게 보고하세요. 재진입이라는 이유로 이 실패를 "
            "완료로 처리하지 마세요.\n"
        )
    sys.stderr.write(header + detail + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
