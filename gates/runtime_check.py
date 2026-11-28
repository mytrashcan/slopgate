#!/usr/bin/env python3
"""런타임 검증 — 자동화가 '설정이 맞는가'가 아니라 '실제로 돌았는가'를 본다.

기존 게이트(skill_lint·memory_budget·cron_lint)는 전부 **정적**이다. 파일이 규칙에 맞는지만 본다.
poteto 강연의 피라미드에서 그건 두 번째 층(정적 분석)이고, 그가 "가장 중요한 단계"라고 부른 것은
세 번째 층인 **검증**이다 — 에이전트(자동화)가 실제로 돌았고 결과가 나왔는지 확인하는 것.

이 게이트가 없어서 놓친 실제 사례: 주간 self-improvement 크론이 928초 모델 타임아웃으로
**두 번 연속 실패**하고 98시간 동안 방치됐다. 설정은 완벽했고 오류도 없어 보였다.
게이트는 jobs.json 의 **실행 기록**(last_status·failure_streak·next_run_at)을 본다.

사용:
    python3 gates/runtime_check.py [--jobs ~/.hermes/cron/jobs.json] [--json]

종료 코드: 오류가 있으면 1, 없으면 0, 입력 없음 2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

JOBS = Path.home() / ".hermes" / "cron" / "jobs.json"
STALL_GRACE = timedelta(minutes=10)   # next_run_at 이 이만큼 지났는데 안 돌았으면 스케줄러 정지
SWEEPER_STATE = Path.home() / ".hermes" / "scripts" / ".sweeper-gate-state.json"


def parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default=str(JOBS))
    ap.add_argument("--now", help="기준 시각 (ISO8601). 테스트용")
    ap.add_argument("--gate-state", default=None,
                    help="모니터 게이트 상태 파일 (RT006). 기본값은 SWEEPER_STATE")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    jp = Path(os.path.expanduser(args.jobs))
    if not jp.exists():
        print(f"runtime_check: jobs.json not found: {jp}", file=sys.stderr)
        return 2
    try:
        raw = json.loads(jp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        # 깨진 입력은 '위반 1건'도 '이상 없음'도 아니다 — 검사 불가다. traceback으로 죽으면
        # 호출자가 게이트 오류와 실제 위반을 구분하지 못한다(cron_lint 와 같은 계약).
        print(f"runtime_check: jobs.json 읽기/파싱 실패: {e}", file=sys.stderr)
        return 2
    jobs = raw.get("jobs", raw) if isinstance(raw, dict) else raw
    if not isinstance(jobs, list):
        # `{"jobs": {}}` 면 아래 루프가 키 문자열을 순회하며 조용히 0건으로 통과한다.
        print(f"runtime_check: jobs.json 구조 오류 — jobs 가 배열이 아니다({type(jobs).__name__})",
              file=sys.stderr)
        return 2
    gate_state = Path(os.path.expanduser(args.gate_state or SWEEPER_STATE))
    now = parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print("runtime_check: --now 형식 오류", file=sys.stderr)
        return 2

    findings: list[dict] = []
    enabled = 0
    for j in jobs:
        if not j.get("enabled"):
            continue
        enabled += 1
        name = j.get("name") or j.get("id")
        status = j.get("last_status")
        streak = int(j.get("failure_streak") or 0)
        err = j.get("last_error")
        next_run = parse_ts(j.get("next_run_at"))
        last_run = parse_ts(j.get("last_run_at"))
        interval = (j.get("schedule") or {}).get("minutes")

        # RT001 연속 실패: 자동화가 계속 실패하는데 아무도 모른다
        if streak >= 2:
            findings.append(dict(sev="E", id="RT001", job=name,
                                 msg=f"{streak}회 연속 실패 (마지막: {(err or '')[:90]})"))

        # RT002 단발 실패: 경고만. 일시적 타임아웃일 수 있다.
        elif status == "error":
            findings.append(dict(sev="W", id="RT002", job=name,
                                 msg=f"마지막 실행 실패 ({(err or '')[:90]})"))

        # RT003 스케줄러 정지: next_run_at 이 한참 지났는데 실행 흔적이 없다
        if next_run and now - next_run > STALL_GRACE:
            late_min = int((now - next_run).total_seconds() // 60)
            findings.append(dict(sev="E", id="RT003", job=name,
                                 msg=f"예정 시각에서 {late_min}분 지났는데 실행 없음 (스케줄러/게이트웨이 확인)"))

        # RT004 배달 실패: 돌긴 했는데 결과가 사용자에게 안 갔다
        if j.get("last_delivery_error"):
            findings.append(dict(sev="E", id="RT004", job=name,
                                 msg=f"배달 실패: {str(j['last_delivery_error'])[:90]}"))

        # RT006 게이트가 조회에 실패한 채 침묵: 후보 없음과 구분되지 않는다
        # 판정을 이름 문자열("sweeper")에 기대면 **잡지 이름을 바꾸는 순간 게이트가 죽는다** —
        # 게다가 `--gate-state` 로 명시한 파일까지 무시했다(2026-11-28). 명시 인자는 항상 존중하고,
        # 이름 매칭은 기본값일 때만 쓰는 약한 폴백으로 둔다.
        if args.gate_state:
            health: Path | None = gate_state
        else:
            health = SWEEPER_STATE if name and "sweeper" in str(name).lower() else None
        if health and health.exists():
            try:
                data = json.loads(health.read_text())
            except (OSError, ValueError):
                # 게이트 상태 파일을 못 읽었다. 이것을 streak=0('이상 없음')으로 처리하면
                # 정확히 이 게이트가 존재하는 이유를 뒤집는 셈이다 — 확인 못 한 것을 문제 없음으로
                # 보고하게 된다. 파일이 있는데 못 읽는 건 그 자체가 오류다.
                data = None
            if data is None:
                findings.append(dict(sev="E", id="RT006", job=name,
                                     msg=f"게이트 상태 파일을 읽지 못했다({health.name}) — "
                                         f"'후보 없음'인지 '확인 못 함'인지 판정 불가"))
            else:
                try:
                    if not isinstance(data, dict):
                        raise TypeError(f"dict 아님({type(data).__name__})")
                    streak = int(data.get("fetch_fail_streak") or 0)
                except (AttributeError, TypeError, ValueError):
                    # 구조가 틀린 상태 파일(dict 아님, 값이 숫자가 아님)도 '판정 불가'다.
                    streak = None
                if streak is None:
                    findings.append(dict(sev="E", id="RT006", job=name,
                                         msg=f"게이트 상태 파일 구조가 예상과 다르다({health.name}) — "
                                             f"fetch_fail_streak 를 읽을 수 없다"))
                elif streak >= 3:
                    findings.append(dict(sev="E", id="RT006", job=name,
                                         msg=f"게이트가 {streak}틱 연속 소스 조회 실패 — "
                                             f"'후보 없음'이 아니라 '확인 못 함'이다"))

        # RT005 주기 대비 지연: 인터벌 작업이 기대의 2배 넘게 안 돌았다
        if interval and last_run and j.get("state") == "scheduled":
            age_min = (now - last_run).total_seconds() / 60
            if age_min > interval * 2 + 10:
                findings.append(dict(sev="W", id="RT005", job=name,
                                     msg=f"마지막 실행이 {int(age_min)}분 전 ({interval}분 주기의 2배 초과)"))

    errors = [f for f in findings if f["sev"] == "E"]
    warns = [f for f in findings if f["sev"] == "W"]
    summary = dict(jobs=len(jobs), enabled=enabled, errors=len(errors), warnings=len(warns))

    if args.json:
        print(json.dumps(dict(summary=summary, findings=findings), ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"[{f['sev']}] {f['id']} {f['job']}: {f['msg']}")
        print(f"\n활성 크론 {enabled}개 · 오류 {len(errors)} · 경고 {len(warns)}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
