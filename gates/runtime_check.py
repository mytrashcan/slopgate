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
    raw = json.loads(jp.read_text(encoding="utf-8"))
    jobs = raw.get("jobs", raw) if isinstance(raw, dict) else raw
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
        health = gate_state if name and "sweeper" in str(name).lower() else None
        if health and health.exists():
            try:
                streak = int(json.loads(health.read_text()).get("fetch_fail_streak") or 0)
            except (OSError, ValueError):
                streak = 0
            if streak >= 3:
                findings.append(dict(sev="E", id="RT006", job=name,
                                     msg=f"게이트가 {streak}틱 연속 소스 조회 실패 — '후보 없음'이 아니라 '확인 못 함'이다"))

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
