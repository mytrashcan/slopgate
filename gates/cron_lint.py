#!/usr/bin/env python3
"""크론 린트 — 크론 작업이 조용히 망가지는 조건을 파일에서 직접 검사한다.

배경(실측으로 확인한 실패 모드):
  - 프롬프트가 ~9.5k자를 넘으면 cronjob update 호출 페이로드가 잘려 갱신이 실패한다.
  - script/monitor_script 경로가 사라져도 작업은 계속 스케줄에 남는다(조용한 실패).
  - 후보 게이트(monitor_script) 없는 에이전트 크론은 매 주기 무조건 모델을 띄운다.

사용:
    python3 gates/cron_lint.py [--jobs ~/.hermes/cron/jobs.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

JOBS = Path.home() / ".hermes" / "cron" / "jobs.json"
SCRIPTS = Path.home() / ".hermes" / "scripts"
PROMPT_UPDATE_LIMIT = 9500     # 이보다 길면 cronjob_manage(update)가 실패한다


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default=str(JOBS))
    ap.add_argument("--scripts-dir", default=str(SCRIPTS))
    ap.add_argument("--allow-unattended-agent", action="store_true",
                    help="게이트 없는 에이전트 크론 경고를 끈다")
    args = ap.parse_args()

    jp = Path(os.path.expanduser(args.jobs))
    if not jp.exists():
        print(f"cron_lint: jobs.json not found: {jp}", file=sys.stderr)
        return 2
    raw = json.loads(jp.read_text(encoding="utf-8"))
    jobs = raw.get("jobs", raw) if isinstance(raw, dict) else raw
    sdir = Path(os.path.expanduser(args.scripts_dir))

    errors, warns, enabled = 0, 0, 0
    for j in jobs:
        name = j.get("name") or j.get("id")
        if j.get("enabled"):
            enabled += 1
        plen = len(j.get("prompt") or "")
        if plen > PROMPT_UPDATE_LIMIT:
            print(f"[E] CRN001 {name}: 프롬프트 {plen}자 > {PROMPT_UPDATE_LIMIT}자 "
                  f"(cronjob update 실패 구간)")
            errors += 1
        for key in ("script", "monitor_script"):
            f = j.get(key)
            if f and not (sdir / f).exists():
                print(f"[E] CRN002 {name}: {key}={f} 파일 없음")
                errors += 1
        if not j.get("no_agent") and j.get("enabled") and plen == 0:
            print(f"[E] CRN003 {name}: 에이전트 크론인데 프롬프트가 비어 있음")
            errors += 1
        if (not j.get("no_agent") and j.get("enabled") and not j.get("monitor_script")
                and not args.allow_unattended_agent):
            print(f"[W] CRN010 {name}: 후보 게이트 없이 매 주기 모델을 띄운다")
            warns += 1

    print(f"\n크론 {len(jobs)}개(활성 {enabled}) · 오류 {errors} · 경고 {warns}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
