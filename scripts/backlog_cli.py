#!/usr/bin/env python3
"""backuplog.json 조회/변경 CLI 진입점. 표준 라이브러리만 사용 (외부 의존성 없음).

실제 검증/저장 로직은 backlog_core.py, 명령 핸들러는 backlog_commands.py에 있다.
"""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from backlog_commands import (
    cmd_add,
    cmd_get,
    cmd_list,
    cmd_ready,
    cmd_set_status,
    cmd_update,
    cmd_validate,
)
from backlog_core import CliError, emit_error

PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_FILE = os.path.join(PROJECT_ROOT, "backuplog.json")


def build_parser():
    p = argparse.ArgumentParser(prog="backlog_cli.py", description="backuplog.json 조회/변경 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_file_arg(sp):
        sp.add_argument("--file", default=DEFAULT_FILE, help=f"대상 backuplog.json 경로 (기본값: {DEFAULT_FILE})")

    sp = sub.add_parser("list", help="작업 목록 조회 (필터 가능, 읽기 전용)")
    add_file_arg(sp)
    sp.add_argument("--status")
    sp.add_argument("--priority")
    sp.add_argument("--category")
    sp.add_argument("--parent")
    sp.add_argument("--dep-on", help="이 id를 deps에 포함한 작업만")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("get", help="id로 작업 상세 조회 (읽기 전용)")
    add_file_arg(sp)
    sp.add_argument("id")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("ready", help="의존성이 모두 done인 착수 후보 조회 (읽기 전용)")
    add_file_arg(sp)
    sp.set_defaults(func=cmd_ready)

    sp = sub.add_parser("validate", help="스키마/참조/순환 의존성 검증 (읽기 전용)")
    add_file_arg(sp)
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("add", help="새 작업 추가 (변경)")
    add_file_arg(sp)
    sp.add_argument("--id", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--category", required=True)
    sp.add_argument("--done-when", dest="done_when", required=True)
    sp.add_argument("--priority", default=None)
    sp.add_argument("--status", default=None)
    sp.add_argument("--summary", default=None)
    sp.add_argument("--where", default=None)
    sp.add_argument("--parent", default=None)
    sp.add_argument("--deps", default=None, help="쉼표로 구분된 id 목록")
    sp.add_argument("--doc", default=None)
    sp.add_argument("--est-min", dest="est_min", type=int, default=None)
    sp.add_argument("--gate", default=None)
    sp.add_argument("--owner", default=None)
    sp.add_argument("--expect-hash", dest="expect_hash", default=None, help="충돌 감지용 기대 file_sha256")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("update", help="기존 작업의 필드 수정 (변경, status/id/owner/log 제외)")
    add_file_arg(sp)
    sp.add_argument("--id", required=True)
    sp.add_argument("--title", default=None)
    sp.add_argument("--summary", default=None)
    sp.add_argument("--where", default=None)
    sp.add_argument("--done-when", dest="done_when", default=None)
    sp.add_argument("--gate", default=None)
    sp.add_argument("--doc", default=None)
    sp.add_argument("--est-min", dest="est_min", type=int, default=None)
    sp.add_argument("--priority", default=None)
    sp.add_argument("--category", default=None)
    sp.add_argument("--parent", default=None)
    sp.add_argument("--deps", default=None, help="쉼표로 구분된 id 목록 (전체 교체)")
    sp.add_argument("--note", default=None, help="수정 사유 (지정 시 log에 [update] 항목 기록)")
    sp.add_argument("--expect-hash", dest="expect_hash", default=None, help="충돌 감지용 기대 file_sha256")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("set-status", help="작업 상태 변경 (변경)")
    add_file_arg(sp)
    sp.add_argument("--id", required=True)
    sp.add_argument("--status", required=True)
    sp.add_argument("--note", default=None, help="done/needs_info/blocked로 갈 때 필수")
    sp.add_argument("--owner", default=None)
    sp.add_argument("--expect-hash", dest="expect_hash", default=None, help="충돌 감지용 기대 file_sha256")
    sp.set_defaults(func=cmd_set_status)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except CliError as e:
        emit_error(e.kind, e.message, file_path=getattr(args, "file", None), command=args.cmd, extra=e.extra)


if __name__ == "__main__":
    main()
