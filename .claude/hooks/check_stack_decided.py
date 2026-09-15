import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

MANIFEST_BASENAMES = {
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "go.mod",
    "Cargo.toml",
    "composer.json",
    "Gemfile",
    "poetry.lock",
}


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - hook은 임의의 stdin에도 절대 크래시하면 안 됨
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    basename = os.path.basename(file_path)
    if basename not in MANIFEST_BASENAMES:
        return 0

    backlog_path = os.path.join(os.getcwd(), "backuplog.json")
    if not os.path.exists(backlog_path):
        return 0

    try:
        with open(backlog_path, encoding="utf-8") as f:
            blog = json.load(f)
    except Exception:  # noqa: BLE001 - 판단 근거를 못 읽으면 차단하지 않고 통과
        return 0

    p01 = next((t for t in (blog.get("tasks") or []) if t.get("id") == "P0.1"), None)
    if p01 is None:
        return 0
    if p01.get("status") == "done":
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"'{basename}' 생성이 차단되었습니다: backuplog.json의 P0.1(기술 스택 결정)이 아직 "
                f"'done'이 아닙니다 (현재: '{p01.get('status')}'). CLAUDE.md 규칙(임의로 스택을 정하지 않는다)"
                "에 따라, 먼저 사용자와 기술 스택을 확정하고 backuplog.json의 P0.1 status를 done으로 "
                "갱신한 뒤 다시 시도하세요."
            ),
        }
    }, ensure_ascii=False))
    return 0


sys.exit(main())
