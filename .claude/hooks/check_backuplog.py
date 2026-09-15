import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - hook은 임의의 stdin에도 절대 크래시하면 안 됨
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    norm = file_path.replace("\\", "/")
    if not norm.endswith("backuplog.json"):
        return 0
    if not os.path.exists(file_path):
        return 0

    try:
        with open(file_path, encoding="utf-8") as f:
            blog = json.load(f)
    except Exception as e:  # noqa: BLE001 - 대상 파일이 어떻게 깨져도 차단 사유로만 보고
        print(json.dumps({
            "decision": "block",
            "reason": f"backuplog.json 파싱 실패: {e}. JSON 문법을 확인하고 다시 저장하세요.",
        }, ensure_ascii=False))
        return 0

    enums = blog.get("enums", {}) or {}
    valid_status = set(enums.get("status", []) or [])
    valid_priority = set(enums.get("priority", []) or [])
    valid_category = set(enums.get("category", []) or [])
    tasks = blog.get("tasks", []) or []
    ids = [t.get("id") for t in tasks]
    id_set = set(ids)

    errors = []

    if len(ids) != len(id_set):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        errors.append(f"중복된 작업 id: {dupes}")

    for t in tasks:
        tid = t.get("id", "?")
        if t.get("status") not in valid_status:
            errors.append(f"{tid}: 잘못된 status '{t.get('status')}' (허용값: {sorted(valid_status)})")
        if t.get("priority") not in valid_priority:
            errors.append(f"{tid}: 잘못된 priority '{t.get('priority')}' (허용값: {sorted([p for p in valid_priority if p is not None])})")
        if t.get("category") not in valid_category:
            errors.append(f"{tid}: 잘못된 category '{t.get('category')}' (허용값: {sorted(valid_category)})")

        parent = t.get("parent")
        if parent is not None and parent not in id_set:
            errors.append(f"{tid}: parent '{parent}'가 존재하지 않는 작업 id")

        for d in (t.get("deps") or []):
            if d not in id_set:
                errors.append(f"{tid}: deps에 존재하지 않는 작업 id '{d}'")

        if t.get("status") == "done":
            log = t.get("log") or []
            if not any(entry.get("status") == "done" for entry in log):
                errors.append(f"{tid}: status가 done인데 log에 done 기록이 없음")

    if errors:
        reason = (
            "backuplog.json 구조 검증 실패:\n- "
            + "\n- ".join(errors)
            + "\n\n수정 방법: enums에 정의된 값만 사용하고, deps/parent는 실제 존재하는 id만 참조하며, "
              "status를 done으로 바꿀 때는 log 배열에 status:'done' 항목을 함께 추가하세요."
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))

    return 0


sys.exit(main())
