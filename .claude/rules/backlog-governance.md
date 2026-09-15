# 백로그 거버넌스 규칙

`.claude/rules/`는 Claude Code가 세션 시작 시 CLAUDE.md와 함께 자동 로드하는 프로젝트 규칙 디렉토리다. 이 파일은 `backuplog.json` 변경·상태 전이·코드 책임·문서 갱신에 대한 세부 규칙을 다룬다. 실행 순서 자체는 `CLAUDE.md`의 "작업 실행 순서" 절을 따른다.

## 1. 백로그 변경 주체
- `backuplog.json`을 바꿀 수 있는 유일한 경로는 `scripts/backlog_cli.py`의 `add` / `update` / `set-status`뿐이다. 세션이든 사용자든 예외 없다.
- 직접 Read/Grep/Glob/`cat`류로 여는 것은 `.claude/hooks/guard_backlog_read.py`가 차단한다(전체 프로젝트 넓은 검색은 막지 않음 — 정책적 가드이지 완전한 보안 경계는 아님).
- 각 변경 명령은 저장 전 `backlog_core.validate_structure()`로 스키마·참조·순환 의존성을 검증하고, 저장 직전 `.backlog-backups/`에 백업을 남기며, `--expect-hash`로 동시 변경 충돌을 감지한다. 검증 실패 시 원본은 그대로 보존된다.

## 2. 상태 전이 규칙
- 상태값은 `enums.status`에 정의된 값만 사용한다(`todo/in_progress/in_review/needs_info/blocked/done/cancelled`).
- `done`/`needs_info`/`blocked`로 전이할 때 `--note`(근거)를 CLI가 강제한다. 단, **그 근거가 실제로 해당 작업의 `done_when`을 충족하는지는 CLI가 판단하지 않는다** — 이 판단은 완료 처리 전에 세션(또는 사람)이 직접 확인해야 한다.
- 착수(`in_progress`) 전이 시 실제로 작업을 시작하는 시점에만 기록한다. `claimed_at`/시간·담당 정보를 실제 사실과 다르게 기재하지 않는다.
- 사람의 판단이 필요한 결정(수치 임계값, 정책적 기준 등)은 임의로 정하지 않고 `needs_info`로 전환한 뒤 `--note`에 확인 질문을 남긴다.

## 3. 코드 책임 분리
| 파일 | 책임 |
|---|---|
| `scripts/backlog_core.py` | 데이터 모델, 스키마 검증, 백업/원자적 쓰기 등 순수 I/O 유틸 |
| `scripts/backlog_read.py` | 읽기 전용 명령(`list/get/ready/validate`) |
| `scripts/backlog_commands.py` | 변경 명령(`add/update/set-status`) |
| `scripts/backlog_cli.py` | 인자 파싱과 진입점만 담당, 로직을 갖지 않는다 |
| `scripts/quality_check.py` | 코드 길이/lint/build(및 HTML 안전성) 검사 로직 |
| `.claude/hooks/*.py` | 각 훅은 정책 하나만 담당한다(가드/스키마검증/품질검사 등 혼합 금지). 새 정책이 필요하면 새 훅 파일을 추가하고 `.claude/settings.json`에 등록한다 |

## 4. 문서 갱신 시점·경로·조건
- 작업별 설명 문서는 `docs/backlog/<id>.md`이며, 해당 task의 `doc` 필드가 그 경로를 가리킨다.
- 갱신 시점: `backuplog.json`의 해당 task 필드(제목/summary/done_when/deps/parent/gate 등)가 **실제로 변경되었을 때만** 대응 문서를 최신 스냅샷 기준으로 다시 쓴다. 단순 재실행이나 타임스탬프만 바뀐 경우는 갱신하지 않는다.
- 경로/주체: 문서 작성·갱신은 항상 `backlog-explainer` 서브에이전트를 경유한다. 세션이 `docs/backlog/*.md`를 직접 임의로 고쳐 쓰지 않는다.
- 문서에는 근거로 삼은 `file_sha256`/`meta_updated`를 표기해 어느 버전 기준인지 추적 가능하게 한다.

## 5. 동시 실행 규칙
- `critical-reviewer`(읽기 전용)와 `backlog-explainer`(문서 작성 전용)를 병렬 실행하는 동안, 메인 세션은 `backuplog.json`을 변경하지 않는다 — 두 서브에이전트에게 전달한 입력 버전(`file_sha256`)을 고정한다.
- 두 서브에이전트는 `backuplog.json`을 직접 열지 않고 메인이 전달한 스냅샷만 근거로 삼는다(각 에이전트 정의에 명시, `guard_backlog_read.py`가 동일하게 적용됨).
- `backuplog.json` 변경은 오직 메인 세션만 수행한다. `backlog-explainer`의 도구는 `docs/backlog/*.md`만 쓰도록, `critical-reviewer`의 도구는 애초에 쓰기 도구가 없도록 구성되어 있어 둘 다 백로그 자체를 바꿀 수 없다.
- 리뷰 반영으로 `backuplog.json`이 실제로 바뀌면, 그 변경에 영향받은 문서·검토 결과는 새 `file_sha256` 기준으로 갱신 대상이 된다.

## 6. 완료(done) 근거로 인정하지 않는 것
다음 중 하나라도 해당하면 `done`으로 전이하지 않는다(대신 `todo`/`in_progress` 유지 또는 `needs_info`/`blocked`로 전환하고 사유 기록):
- 백로그 구조·내용에 영향을 주는 변경인데 `critical-reviewer` 검토를 아직 실행하지 않은 경우
- `quick_quality_check.py`/`stop_quality_gate.py`(즉 `quality_check.py`) 검사가 실패한 상태
- 필요한 검사가 애초에 구성되지 않아 건너뛴 경우(예: 대상 파일 없음으로 스킵되었거나 도구 미설치로 `NOT_CONFIGURED`인 경우)

## 7. 규칙 유형 분류
| 규칙 | 유형 | 강제 수단 |
|---|---|---|
| `backuplog.json`은 CLI로만 변경 | hook | `guard_backlog_read.py` + CLI 자체의 백업/`--expect-hash` |
| status/priority/category는 enums 값만 | hook | `validate_structure()`(저장 전) + `check_backuplog.py`(저장 후) |
| done/needs_info/blocked 전이 시 note 필수 | hook | `backlog_commands.cmd_set_status` |
| deps/parent는 실제 존재하는 id만, 순환 금지 | hook | `validate_structure()` + `check_backuplog.py` |
| 매니페스트 파일은 P0.1 done 전 생성 금지 | hook | `check_stack_decided.py` |
| 코드 길이/lint/build(및 HTML 안전 패턴) | hook | `quick_quality_check.py`(저장 시) / `stop_quality_gate.py`(세션 종료 시) |
| done 근거 충족 여부(§6) 판단 | 지침 | 자동 차단 없음 — 세션/사람이 직접 확인하고 기록 |
| 비판·문서화는 동일 스냅샷으로 병렬 실행(§5) | 지침 | 자동 차단 없음 — 세션 운영 관행 |
| 문서 갱신은 backlog-explainer 경유(§4) | 지침 | 자동 차단 없음 — 세션 운영 관행 |
| critical-reviewer 지적 반영 여부 판단 | 리뷰 | 에이전트 검토 결과를 세션이 근거 대조 후 채택/보류 |
| 수치·정책 결정은 임의 확정 금지, needs_info로 | 지침 | 자동 차단 없음 — 세션 운영 관행 |
