"""backuplog.json CLI 변경 명령 핸들러 (add/set-status/update). 읽기 전용 명령은 backlog_read.py 참고."""
import re

from backlog_core import (
    CliError,
    atomic_write,
    emit,
    load,
    make_backup,
    now_iso,
    sha256_of_file,
    today,
    validate_structure,
)
from backlog_read import (  # noqa: F401 - backlog_cli.py로 재노출
    cmd_get,
    cmd_list,
    cmd_ready,
    cmd_validate,
)

ID_PATTERN = re.compile(r"^P\d+(\.\d+)?$")

# ---------------- 변경 ----------------

def _validate_add_input(args, tasks, enums):
    id_set = {t.get("id") for t in tasks}
    missing = [flag for flag, val in (
        ("--id", args.id), ("--title", args.title),
        ("--category", args.category), ("--done-when", args.done_when),
    ) if not val]
    if missing:
        raise CliError("missing_fields", f"필수 입력이 없습니다: {', '.join(missing)}", {"missing_fields": missing})

    errors = []
    if not ID_PATTERN.match(args.id):
        errors.append(f"id 형식이 기존 규칙(예: P0, P0.1, P2.4 — ^P\\d+(\\.\\d+)?$)과 다릅니다: '{args.id}'")
    if args.id in id_set:
        errors.append(f"id '{args.id}'가 이미 존재합니다.")
    if args.category not in (enums.get("category") or []):
        errors.append(f"category '{args.category}'는 허용되지 않습니다. 허용값: {enums.get('category')}")
    if args.priority not in (enums.get("priority") or []):
        errors.append(f"priority '{args.priority}'는 허용되지 않습니다. 허용값: {enums.get('priority')}")
    status = args.status or "todo"
    if status not in (enums.get("status") or []):
        errors.append(f"status '{status}'는 허용되지 않습니다. 허용값: {enums.get('status')}")
    if args.parent is not None and args.parent not in id_set:
        errors.append(f"parent '{args.parent}'가 존재하지 않는 작업 id입니다.")
    deps = [d.strip() for d in args.deps.split(",") if d.strip()] if args.deps else []
    for d in deps:
        if d not in id_set:
            errors.append(f"deps에 존재하지 않는 id '{d}'가 있습니다.")
    if args.est_min is not None and args.est_min <= 0:
        errors.append("--est-min은 양의 정수여야 합니다.")
    if errors:
        raise CliError("validation_error", "입력값 검증 실패", {"errors": errors})
    return status, deps


def cmd_add(args):
    data, _ = load(args.file)
    tasks = data.get("tasks", []) or []
    enums = data.get("enums", {}) or {}

    status, deps = _validate_add_input(args, tasks, enums)

    if args.expect_hash:
        current_hash = sha256_of_file(args.file)
        if current_hash != args.expect_hash:
            raise CliError(
                "conflict",
                f"파일이 예상 버전과 다릅니다 (동시 변경 가능성). expected={args.expect_hash} actual={current_hash}",
                {"expected": args.expect_hash, "actual": current_hash},
            )

    warnings = []
    max_est = (data.get("meta") or {}).get("max_est_min")
    if args.est_min is not None and max_est and args.parent is not None and args.est_min > max_est:
        warnings.append(f"est-min({args.est_min})이 meta.max_est_min({max_est})을 초과합니다. 리프 작업이라면 분할을 검토하세요.")

    new_task = {
        "id": args.id,
        "status": status,
        "priority": args.priority,
        "category": args.category,
        "title": args.title,
        "summary": args.summary,
        "where": args.where,
        "parent": args.parent,
        "deps": deps,
        "doc": args.doc,
        "done_when": args.done_when,
        "est_min": args.est_min,
        "gate": args.gate,
        "owner": args.owner,
        "claimed_at": None,
        "updated_at": now_iso(),
        "log": [],
    }

    new_data = dict(data)
    new_data["tasks"] = tasks + [new_task]
    new_meta = dict(data.get("meta", {}) or {})
    new_meta["updated"] = today()
    new_data["meta"] = new_meta

    struct_errors = validate_structure(new_data)
    if struct_errors:
        raise CliError("validation_error", "추가 후 전체 구조 검증 실패 — 저장하지 않았습니다.", {"errors": struct_errors})

    old_hash = sha256_of_file(args.file)
    backup_path = make_backup(args.file)
    atomic_write(args.file, new_data)
    new_hash = sha256_of_file(args.file)

    emit(True, "add", args.file, data=new_task, extra={
        "warnings": warnings,
        "backup": backup_path,
        "old_file_sha256": old_hash,
        "new_file_sha256": new_hash,
    })


def _apply_status_change(tasks, target_id, new_status, note, owner):
    log_entry = {"at": now_iso(), "owner": owner, "status": new_status, "note": note or ""}
    new_tasks = []
    updated_task = None
    for t in tasks:
        if t.get("id") == target_id:
            nt = dict(t)
            nt["status"] = new_status
            if owner is not None:
                nt["owner"] = owner
            nt["updated_at"] = now_iso()
            nt["log"] = (t.get("log") or []) + [log_entry]
            updated_task = nt
            new_tasks.append(nt)
        else:
            new_tasks.append(t)
    return new_tasks, updated_task


_UPDATABLE_FIELDS = (
    "title", "summary", "where", "done_when", "gate", "doc",
    "est_min", "priority", "category", "parent", "deps",
)


def _validate_update_input(args, tasks, enums, task):
    id_set = {t.get("id") for t in tasks}
    changed = {}
    for field in _UPDATABLE_FIELDS:
        val = getattr(args, field)
        if val is None:
            continue
        if field == "deps":
            val = [d.strip() for d in val.split(",") if d.strip()]
        elif field == "est_min":
            val = int(val)
        changed[field] = val

    if not changed:
        raise CliError("no_changes", "변경할 필드가 하나도 지정되지 않았습니다. 최소 하나의 필드 플래그를 지정하세요.")

    errors = []
    if "category" in changed and changed["category"] not in (enums.get("category") or []):
        errors.append(f"category '{changed['category']}'는 허용되지 않습니다. 허용값: {enums.get('category')}")
    if "priority" in changed and changed["priority"] not in (enums.get("priority") or []):
        errors.append(f"priority '{changed['priority']}'는 허용되지 않습니다. 허용값: {enums.get('priority')}")
    if "parent" in changed and changed["parent"] not in id_set:
        errors.append(f"parent '{changed['parent']}'가 존재하지 않는 작업 id입니다.")
    if "deps" in changed:
        for d in changed["deps"]:
            if d == task.get("id"):
                errors.append("자기 자신을 deps로 지정할 수 없습니다.")
            elif d not in id_set:
                errors.append(f"deps에 존재하지 않는 id '{d}'가 있습니다.")
    if "est_min" in changed and changed["est_min"] <= 0:
        errors.append("--est-min은 양의 정수여야 합니다.")
    if errors:
        raise CliError("validation_error", "입력값 검증 실패", {"errors": errors})
    return changed


def cmd_update(args):
    data, _ = load(args.file)
    tasks = data.get("tasks", []) or []
    enums = data.get("enums", {}) or {}
    task = next((t for t in tasks if t.get("id") == args.id), None)
    if task is None:
        raise CliError("not_found", f"id '{args.id}'를 찾을 수 없습니다.")

    changed = _validate_update_input(args, tasks, enums, task)

    if args.expect_hash:
        current_hash = sha256_of_file(args.file)
        if current_hash != args.expect_hash:
            raise CliError(
                "conflict",
                f"파일이 예상 버전과 다릅니다 (동시 변경 가능성). expected={args.expect_hash} actual={current_hash}",
                {"expected": args.expect_hash, "actual": current_hash},
            )

    old_values = {k: task.get(k) for k in changed}

    new_tasks = []
    updated_task = None
    for t in tasks:
        if t.get("id") != args.id:
            new_tasks.append(t)
            continue
        nt = dict(t)
        nt.update(changed)
        nt["updated_at"] = now_iso()
        if args.note:
            log_entry = {"at": now_iso(), "owner": t.get("owner"), "status": t.get("status"), "note": f"[update] {args.note}"}
            nt["log"] = (t.get("log") or []) + [log_entry]
        updated_task = nt
        new_tasks.append(nt)

    new_data = dict(data)
    new_data["tasks"] = new_tasks
    new_meta = dict(data.get("meta", {}) or {})
    new_meta["updated"] = today()
    new_data["meta"] = new_meta

    struct_errors = validate_structure(new_data)
    if struct_errors:
        raise CliError("validation_error", "수정 후 전체 구조 검증 실패 — 저장하지 않았습니다.", {"errors": struct_errors})

    old_hash = sha256_of_file(args.file)
    backup_path = make_backup(args.file)
    atomic_write(args.file, new_data)
    new_hash = sha256_of_file(args.file)

    emit(True, "update", args.file, data=updated_task, extra={
        "changed_fields": sorted(changed.keys()),
        "old_values": old_values,
        "new_values": changed,
        "backup": backup_path,
        "old_file_sha256": old_hash,
        "new_file_sha256": new_hash,
    })


def cmd_set_status(args):
    data, _ = load(args.file)
    tasks = data.get("tasks", []) or []
    enums = data.get("enums", {}) or {}
    task = next((t for t in tasks if t.get("id") == args.id), None)
    if task is None:
        raise CliError("not_found", f"id '{args.id}'를 찾을 수 없습니다.")

    valid_status = enums.get("status") or []
    if args.status not in valid_status:
        raise CliError("validation_error", f"status '{args.status}'는 허용되지 않습니다. 허용값: {valid_status}")

    current_status = task.get("status")
    note = args.note
    if args.status in ("done", "needs_info", "blocked") and not (note and note.strip()):
        raise CliError(
            "missing_fields",
            f"status를 '{args.status}'로 바꾸려면 --note(근거/사유)가 필요합니다.",
            {"missing_fields": ["--note"], "done_when": task.get("done_when") if args.status == "done" else None},
        )

    if args.expect_hash:
        current_hash = sha256_of_file(args.file)
        if current_hash != args.expect_hash:
            raise CliError(
                "conflict",
                f"파일이 예상 버전과 다릅니다 (동시 변경 가능성). expected={args.expect_hash} actual={current_hash}",
                {"expected": args.expect_hash, "actual": current_hash},
            )

    owner = args.owner if args.owner is not None else task.get("owner")
    new_tasks, updated_task = _apply_status_change(tasks, args.id, args.status, note, owner)

    new_data = dict(data)
    new_data["tasks"] = new_tasks
    new_meta = dict(data.get("meta", {}) or {})
    new_meta["updated"] = today()
    new_data["meta"] = new_meta

    struct_errors = validate_structure(new_data)
    if struct_errors:
        raise CliError("validation_error", "상태 변경 후 전체 구조 검증 실패 — 저장하지 않았습니다.", {"errors": struct_errors})

    old_hash = sha256_of_file(args.file)
    backup_path = make_backup(args.file)
    atomic_write(args.file, new_data)
    new_hash = sha256_of_file(args.file)

    emit(True, "set-status", args.file, data=updated_task, extra={
        "previous_status": current_status,
        "backup": backup_path,
        "old_file_sha256": old_hash,
        "new_file_sha256": new_hash,
        "done_when": updated_task.get("done_when") if args.status == "done" else None,
    })
