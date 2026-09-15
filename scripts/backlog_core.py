"""backuplog.json 데이터 모델·검증·파일 I/O. CLI 인자 파싱과 명령 분기는 다루지 않는다."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone


class CliError(Exception):
    def __init__(self, kind, message, extra=None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.extra = extra or {}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def load(path):
    if not os.path.exists(path):
        raise CliError("file_not_found", f"파일이 없습니다: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise CliError("read_error", f"파일을 읽을 수 없습니다: {e}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CliError("parse_error", f"JSON 파싱 실패: {e}")
    if not isinstance(data, dict) or "tasks" not in data:
        raise CliError("schema_error", "최상위 구조에 'tasks'가 없습니다. 이 파일이 backuplog.json 형식이 맞는지 확인하세요.")
    return data, raw


def validate_structure(data):
    """스키마·enums·참조 무결성·순환 의존성 검사. 판단 없이 기계적으로 확인 가능한 것만 검사한다."""
    errors = []
    enums = data.get("enums", {}) or {}
    valid_status = set(enums.get("status", []) or [])
    valid_priority = set(enums.get("priority", []) or [])
    valid_category = set(enums.get("category", []) or [])
    tasks = data.get("tasks", []) or []
    ids = [t.get("id") for t in tasks]
    id_set = set(ids)

    if len(ids) != len(id_set):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        errors.append(f"중복된 작업 id: {dupes}")

    graph = {}
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

        deps = t.get("deps") or []
        for d in deps:
            if d not in id_set:
                errors.append(f"{tid}: deps에 존재하지 않는 작업 id '{d}'")
        graph[tid] = [d for d in deps if d in id_set]

        if t.get("status") == "done":
            log = t.get("log") or []
            if not any(entry.get("status") == "done" for entry in log):
                errors.append(f"{tid}: status가 done인데 log에 done 기록이 없음")

    # 순환 의존성 검사 (DFS)
    white, gray, black = 0, 1, 2
    color = {tid: white for tid in graph}
    cycles = []

    def dfs(u, stack):
        color[u] = gray
        stack.append(u)
        for v in graph.get(u, []):
            if color.get(v, white) == gray:
                idx = stack.index(v)
                cycles.append(stack[idx:] + [v])
            elif color.get(v, white) == white:
                dfs(v, stack)
        stack.pop()
        color[u] = black

    for tid in list(graph.keys()):
        if color[tid] == white:
            dfs(tid, [])
    for c in cycles:
        errors.append(f"순환 의존성 발견: {' -> '.join(c)}")

    return errors


def compute_ready(data):
    tasks = data.get("tasks", []) or []
    by_id = {t.get("id"): t for t in tasks}
    ready = []
    excluded_missing_dep = []
    for t in tasks:
        if t.get("status") != "todo":
            continue
        deps = t.get("deps") or []
        missing = [d for d in deps if d not in by_id]
        if missing:
            excluded_missing_dep.append({"id": t.get("id"), "missing_deps": missing})
            continue
        unmet = [d for d in deps if by_id[d].get("status") != "done"]
        if not unmet:
            ready.append(t)
    return ready, excluded_missing_dep


def make_backup(path):
    d = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    backup_dir = os.path.join(d, ".backlog-backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = os.path.join(backup_dir, f"{base}.{ts}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def atomic_write(path, data):
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-backlog-", suffix=".json", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def emit(ok, command, file_path, data=None, errors=None, extra=None):
    out = {"ok": ok, "command": command, "file": file_path}
    if os.path.exists(file_path):
        out["file_sha256"] = sha256_of_file(file_path)
    if extra:
        out.update(extra)
    if data is not None:
        out["data"] = data
    if errors is not None:
        out["errors"] = errors
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


def emit_error(kind, message, file_path=None, command=None, extra=None):
    out = {"ok": False, "command": command, "file": file_path, "error_type": kind, "errors": [message]}
    if extra:
        out.update(extra)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(1)
