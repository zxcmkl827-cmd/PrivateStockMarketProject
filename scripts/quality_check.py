#!/usr/bin/env python3
"""코드 길이 / lint / build 검사. .claude/hooks의 quick/stop 게이트가 이 스크립트를 호출한다.

두 스택을 함께 다룬다:
- scripts/, .claude/hooks/ 의 Python: '[build]'는 python3 -m py_compile로 구문 오류를 잡는 것으로 정의한다.
- 프로젝트 루트의 단일 HTML 대시보드(빌드 도구 없음): '[build]'는 html.parser로 태그 파싱
  가능 여부를 확인하는 것으로 정의하고, 별도로 읽기전용/무업로드/XSS 방지 원칙 위반 패턴을 검사한다.
"""
import argparse
import html.parser
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIRS = [
    os.path.join(PROJECT_ROOT, "scripts"),
    os.path.join(PROJECT_ROOT, ".claude", "hooks"),
    os.path.join(PROJECT_ROOT, "app"),
]
LINE_LIMIT = 300
HTML_LINE_LIMIT = 800  # 단일 파일에 구조·스타일·스크립트를 함께 담는 설계라 300줄 기준은 적용하지 않는다.
EXCLUDE_DIR_NAMES = {".backlog-backups", "__pycache__"}
BANNED_JS_PATTERNS = [
    "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write(",
    "eval(", "new Function(", "fetch(", "XMLHttpRequest", "WebSocket(",
]


def discover_py_files():
    files = []
    for base in CODE_DIRS:
        if not os.path.isdir(base):
            continue
        for root, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIR_NAMES]
            for name in names:
                if name.endswith(".py"):
                    files.append(os.path.join(root, name))
    return sorted(files)


def discover_html_files():
    if not os.path.isdir(PROJECT_ROOT):
        return []
    return sorted(
        os.path.join(PROJECT_ROOT, name) for name in os.listdir(PROJECT_ROOT)
        if name.endswith(".html")
    )


def check_line_count(files, limit):
    ok = True
    lines = [f"[코드 길이] limit={limit}"]
    if not files:
        lines.append("  (대상 파일 없음)")
        return ok, lines
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                n = sum(1 for _ in fh)
        except OSError as e:
            ok = False
            lines.append(f"  [FAIL] {os.path.relpath(f, PROJECT_ROOT)}: 읽기 실패 ({e})")
            continue
        status = "OK" if n <= limit else "FAIL"
        if status == "FAIL":
            ok = False
        lines.append(f"  [{status}] {os.path.relpath(f, PROJECT_ROOT)}: {n} lines (limit {limit})")
    return ok, lines


def check_html_safety(files):
    ok = True
    lines = [f"[html-safety] 금지 패턴: {', '.join(BANNED_JS_PATTERNS)}"]
    if not files:
        lines.append("  (대상 파일 없음)")
        return ok, lines
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            ok = False
            lines.append(f"  [FAIL] {os.path.relpath(f, PROJECT_ROOT)}: 읽기 실패 ({e})")
            continue
        hits = [p for p in BANNED_JS_PATTERNS if p in text]
        if hits:
            ok = False
            lines.append(
                f"  [FAIL] {os.path.relpath(f, PROJECT_ROOT)}: 금지 패턴 발견 {hits} "
                "(읽기전용/무업로드/XSS 방지 원칙 위반 — innerHTML 대신 textContent, "
                "fetch/XHR/WebSocket 등 네트워크 호출 금지)"
            )
        else:
            lines.append(f"  [OK] {os.path.relpath(f, PROJECT_ROOT)}: 금지 패턴 없음")
    return ok, lines


def check_html_parse(files):
    ok = True
    lines = ["[build: html.parser 파싱 검증] (이 스택엔 전통적 빌드 단계 없음 — 태그 파싱 가능 여부로 대체)"]
    if not files:
        lines.append("  (대상 파일 없음)")
        return ok, lines
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            ok = False
            lines.append(f"  [FAIL] {os.path.relpath(f, PROJECT_ROOT)}: 읽기 실패 ({e})")
            continue
        try:
            html.parser.HTMLParser().feed(text)
            lines.append(f"  [OK] {os.path.relpath(f, PROJECT_ROOT)}: 파싱 가능")
        except Exception as e:  # noqa: BLE001 - 어떤 파싱 실패든 보고 대상
            ok = False
            lines.append(f"  [FAIL] {os.path.relpath(f, PROJECT_ROOT)}: 파싱 실패 ({e})")
    return ok, lines


def run_cmd(cmd, timeout):
    try:
        p = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
        return p.returncode, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT ({timeout}s 초과) — 명령: {' '.join(cmd)}"
    except FileNotFoundError:
        return "NOT_CONFIGURED", f"명령을 찾을 수 없음: {' '.join(cmd)}"


def report_step(name, rc, out, extra_note=""):
    if rc == "NOT_CONFIGURED":
        return False, f"[{name}] NOT_CONFIGURED — {out}"
    if rc is None:
        return False, f"[{name}] TIMEOUT — {out} (시간 초과는 실패로 간주, 통과로 쓰지 않음)"
    status = "OK" if rc == 0 else "FAIL"
    line = f"[{name}] -> {status} (exit {rc}){extra_note}"
    if out.strip():
        line += "\n" + out.strip()
    return rc == 0, line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["file", "full"], required=True)
    ap.add_argument("--file", default=None)
    ap.add_argument("--timeout", type=int, default=20, help="외부 명령(ruff/py_compile) 1회당 timeout(초)")
    ap.add_argument("--fail-exit", type=int, default=1)
    ap.add_argument("--stderr-on-fail", action="store_true")
    args = ap.parse_args()

    if args.scope == "file":
        if not args.file or not os.path.exists(args.file):
            print("대상 없음(파일이 존재하지 않음) — 검사 생략")
            sys.exit(0)
        if args.file.endswith(".py"):
            py_targets, html_targets = [args.file], []
        elif args.file.endswith(".html"):
            py_targets, html_targets = [], [args.file]
        else:
            print("대상 없음(.py/.html 파일이 아님) — 검사 생략")
            sys.exit(0)
        check_py, check_html = bool(py_targets), bool(html_targets)
    else:
        py_targets = discover_py_files()
        html_targets = discover_html_files()
        check_py, check_html = True, True

    report = []
    overall_ok = True

    if check_py:
        ok, lines = check_line_count(py_targets, LINE_LIMIT)
        overall_ok &= ok
        report.extend(lines)

        rc, out = run_cmd(["python3", "-m", "ruff", "check", *py_targets], args.timeout) if py_targets else (0, "")
        ok, line = report_step("lint: python3 -m ruff check", rc, out)
        overall_ok &= ok
        report.append(line)

        rc2, out2 = run_cmd(["python3", "-m", "py_compile", *py_targets], args.timeout) if py_targets else (0, "")
        ok2, line2 = report_step(
            "build: python3 -m py_compile", rc2, out2,
            extra_note=" (이 스택엔 전통적 빌드 단계 없음 — 구문 컴파일 확인으로 대체)",
        )
        overall_ok &= ok2
        report.append(line2)

    if check_html:
        ok, lines = check_line_count(html_targets, HTML_LINE_LIMIT)
        overall_ok &= ok
        report.extend(lines)

        ok, lines = check_html_safety(html_targets)
        overall_ok &= ok
        report.extend(lines)

        ok, lines = check_html_parse(html_targets)
        overall_ok &= ok
        report.extend(lines)

    text = "\n".join(report)
    stream = sys.stderr if (args.stderr_on_fail and not overall_ok) else sys.stdout
    stream.write(text + "\n")

    sys.exit(0 if overall_ok else args.fail_exit)


if __name__ == "__main__":
    main()
