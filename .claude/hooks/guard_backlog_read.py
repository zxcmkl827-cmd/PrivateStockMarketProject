"""
backuplog.json(기준 백로그) 직접 읽기를 막고 scripts/backlog_cli.py 경유를 유도하는 PreToolUse hook.

적용 범위(정직하게 명시):
- Read 도구: file_path가 대상 파일과 정확히 일치할 때만 차단.
- Grep/Glob 도구: path 인자가 대상 파일과 정확히 일치할 때만 차단. path가 디렉터리이거나
  생략된 넓은 범위 검색은 막지 않는다(전체 프로젝트 검색까지 막으면 다른 문서 검색이 방해받기 때문).
- Bash 도구: 명령 문자열에 cat/head/tail/less/more/type/Get-Content/gc 같은 "흔한 직접 읽기
  유틸리티" + 대상 파일명이 같이 등장할 때만 차단. 이 CLI(backlog_cli.py) 호출은 항상 허용한다.

이 hook은 임의의 셸 코드(python -c로 파일을 열거나, base64/xxd로 덤프하는 등)까지 전부 막는
보안 경계가 아니다. 흔히 쓰는 직접 읽기 경로만 막는 정책적 가드일 뿐이다.
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DEFAULT_TARGET = os.path.join(PROJECT_ROOT, "backuplog.json")
TARGET = os.environ.get("BACKLOG_GUARD_TARGET") or DEFAULT_TARGET

CLI_HINT_NAME = "backlog_cli.py"
DIRECT_READ_UTILS = re.compile(r"\b(cat|head|tail|less|more|type|Get-Content|gc)\b", re.IGNORECASE)


def normalize(path):
    if not path:
        return None
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    return os.path.normcase(os.path.normpath(path))


TARGET_NORM = normalize(TARGET)
TARGET_BASENAME = os.path.basename(TARGET)


def is_target(path):
    return normalize(path) == TARGET_NORM


def deny(reason_detail):
    reason = (
        f"{reason_detail}\n\n"
        f"'{TARGET_BASENAME}'는 기준 백로그(SSOT)라 직접 읽기 대신 조회 CLI를 쓰세요:\n"
        f"  python3 scripts/backlog_cli.py list\n"
        f"  python3 scripts/backlog_cli.py get <id>\n"
        f"  python3 scripts/backlog_cli.py ready\n"
        f"  python3 scripts/backlog_cli.py validate\n\n"
        "CLI 실행이 실패하면(예: python3 없음, 파일 손상) 오류 메시지를 그대로 사용자에게 보여주고 "
        "복구 방법을 안내하세요 — 직접 파일을 열어 우회하지 마세요.\n\n"
        "참고: 이 차단은 Read/Grep/Glob의 지정 경로와 Bash의 cat/head/tail/type/Get-Content 등 "
        "흔한 직접 읽기 명령만 막습니다. 임의의 셸 코드까지 전부 막는 보안 경계는 아닙니다."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    return 0


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - hook은 임의의 stdin에도 절대 크래시하면 안 됨
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}

    if tool_name == "Read":
        fp = tool_input.get("file_path") or ""
        if is_target(fp):
            return deny(f"Read 도구로 '{fp}'를 직접 읽으려는 시도가 차단되었습니다.")
        return 0

    if tool_name in ("Grep", "Glob"):
        p = tool_input.get("path") or ""
        if not p:
            return 0  # path 생략 = 넓은 범위 검색, 막지 않음
        resolved = p if os.path.isabs(p) else os.path.join(os.getcwd(), p)
        if os.path.isdir(resolved):
            return 0  # 디렉터리 대상 검색, 막지 않음
        if is_target(p):
            return deny(f"{tool_name} 도구로 '{p}'를 직접 조회하려는 시도가 차단되었습니다.")
        return 0

    if tool_name == "Bash":
        cmd = tool_input.get("command") or ""
        if CLI_HINT_NAME in cmd:
            return 0  # 검증된 CLI 경유 — 항상 허용
        if DIRECT_READ_UTILS.search(cmd) and TARGET_BASENAME.lower() in cmd.lower():
            return deny(f"Bash 명령에서 '{TARGET_BASENAME}'을 직접 읽으려는 시도가 감지되어 차단되었습니다: {cmd!r}")
        return 0

    return 0


sys.exit(main())
