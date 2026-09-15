"""backuplog.json CLI 읽기 전용 명령 핸들러 (list/get/ready/validate)."""
from backlog_core import compute_ready, emit, load, validate_structure


def cmd_list(args):
    data, _ = load(args.file)
    tasks = data.get("tasks", []) or []

    def match(t):
        if args.status and t.get("status") != args.status:
            return False
        if args.priority and t.get("priority") != args.priority:
            return False
        if args.category and t.get("category") != args.category:
            return False
        if args.parent and t.get("parent") != args.parent:
            return False
        return not (args.dep_on and args.dep_on not in (t.get("deps") or []))

    filtered = [t for t in tasks if match(t)]
    emit(True, "list", args.file, data=filtered, extra={
        "count": len(filtered),
        "total": len(tasks),
        "meta_updated": data.get("meta", {}).get("updated"),
    })


def cmd_get(args):
    data, _ = load(args.file)
    tasks = data.get("tasks", []) or []
    task = next((t for t in tasks if t.get("id") == args.id), None)
    if task is None:
        emit(False, "get", args.file, errors=[f"id '{args.id}'를 찾을 수 없습니다."], extra={"error_type": "not_found"})
        return
    emit(True, "get", args.file, data=task, extra={"meta_updated": data.get("meta", {}).get("updated")})


def cmd_ready(args):
    data, _ = load(args.file)
    ready, missing = compute_ready(data)
    emit(True, "ready", args.file, data=ready, extra={
        "count": len(ready),
        "excluded_missing_deps": missing,
        "meta_updated": data.get("meta", {}).get("updated"),
    })


def cmd_validate(args):
    data, _ = load(args.file)
    errors = validate_structure(data)
    emit(len(errors) == 0, "validate", args.file,
         data={"task_count": len(data.get("tasks", []) or [])},
         errors=errors if errors else None,
         extra={"meta_updated": data.get("meta", {}).get("updated")})
