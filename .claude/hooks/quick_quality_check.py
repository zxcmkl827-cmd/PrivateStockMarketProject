"""PostToolUse(Write|Edit) 빠른 품질 검사: 방금 편집한 .py 파일 1개만 검사한다.
전체 검사는 Stop hook(stop_quality_gate.py)이 담당한다.

내부 timeout(INNER_TIMEOUT)은 이 hook의 settings.json timeout(25s)보다 짧게 잡아,
바깥 timeout에 기대지 않고 이 스크립트가 스스로 실패를 확정한다.
"""
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
QUALITY_CHECK = os.path.join(PROJECT_ROOT, "scripts", "quality_check.py")
INNER_TIMEOUT = 15


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - hook은 임의의 stdin에도 절대 크래시하면 안 됨
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not file_path.endswith((".py", ".html")):
        return 0

    try:
        proc = subprocess.run(
            ["python3", QUALITY_CHECK, "--scope", "file", "--file", file_path, "--timeout", str(INNER_TIMEOUT - 5)],
            cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=INNER_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return block(
            f"[빠른 품질 검사] TIMEOUT({INNER_TIMEOUT}s 초과) — {file_path} 검사가 시간 내 끝나지 않아 "
            "통과로 간주하지 않습니다. 파일 크기/무한 루프 여부를 확인하고 다시 시도하세요."
        )

    if proc.returncode == 0:
        return 0

    detail = proc.stdout or proc.stderr or "(상세 없음)"
    return block(f"[빠른 품질 검사] {file_path} 실패:\n{detail}")


sys.exit(main())
