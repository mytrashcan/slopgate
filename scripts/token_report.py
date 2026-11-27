#!/usr/bin/env python3
"""토큰 분포 측정 — 로드맵 2단계의 마지막 미완 항목.

`state.db`의 `session_model_usage`를 읽어 작업별·모델별 사용량을 집계한다.
에이전트를 띄우지 않으므로 토큰 비용은 0이다(순수 sqlite 읽기).

`task` 컬럼이 역할을 가른다: 빈 문자열이 메인 턴, 그 외는 aux 역할(압축·요약·제목 등).

사용:
    python3 scripts/token_report.py [--db ~/.hermes/state.db] [--days 7] [--top 10]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone


def q(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.expanduser("~/.hermes/state.db"))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    db = os.path.expanduser(args.db)
    if not os.path.exists(db):
        print(f"token_report: db 없음 {db}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(db)
    # last_seen/first_seen 은 ISO 문자열이 아니라 **epoch 초(float)** 다.
    # (실측: 1795786558.12 — 2026-11-27). ISO 로 비교하면 조용히 0건이 나온다.
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp()

    total = q(conn, """SELECT sum(api_call_count), sum(input_tokens), sum(output_tokens),
                              sum(cache_read_tokens), sum(cache_write_tokens),
                              sum(estimated_cost_usd)
                       FROM session_model_usage WHERE last_seen >= ?""", (since,))[0]
    calls, tin, tout, cread, cwrite, cost = (x or 0 for x in total)

    by_task = q(conn, """SELECT CASE WHEN task IS NULL OR task='' THEN '(main turn)' ELSE task END k,
                                sum(api_call_count), sum(input_tokens), sum(output_tokens),
                                sum(cache_read_tokens)
                         FROM session_model_usage WHERE last_seen >= ?
                         GROUP BY k ORDER BY sum(input_tokens) DESC""", (since,))
    by_model = q(conn, """SELECT model, sum(api_call_count), sum(input_tokens), sum(output_tokens)
                          FROM session_model_usage WHERE last_seen >= ?
                          GROUP BY model ORDER BY sum(input_tokens) DESC""", (since,))
    by_day = q(conn, """SELECT date(last_seen,'unixepoch') d, sum(input_tokens), sum(output_tokens),
                               sum(api_call_count)
                        FROM session_model_usage WHERE last_seen >= ?
                        GROUP BY d ORDER BY d DESC LIMIT 7""", (since,))

    def pct(part, whole):
        return f"{(part / whole * 100):.0f}%" if whole else "0%"

    if args.json:
        import json
        print(json.dumps(dict(days=args.days, calls=calls, input_tokens=tin, output_tokens=tout,
                              cache_read=cread, cache_write=cwrite, cost_usd=cost,
                              by_task=by_task, by_model=by_model, by_day=by_day),
                         ensure_ascii=False, indent=2))
        return 0

    priced = q(conn, """SELECT count(*) FROM session_model_usage
                        WHERE last_seen >= ? AND estimated_cost_usd > 0""", (since,))[0][0]
    print(f"## 토큰 사용 (최근 {args.days}일)")
    print(f"- API 호출 {calls:,} · 입력 {tin:,} · 출력 {tout:,} · 캐시읽기 {cread:,}")
    if priced:
        print(f"- 추정 비용 ${cost:.4f} (가격표가 있는 {priced}건 기준)")
    else:
        # 0달러를 '무료'로 읽지 않게 한다 — 가격표가 없는 모델이라 계산이 안 된 것이다.
        print("- 추정 비용: **계산 불가** (이 모델의 가격 정보가 state.db에 없다 · 토큰 수치는 유효)")
    print("\n### 작업별 (입력 토큰 기준)")
    for name, c, i, o, cr in by_task[: args.top]:
        print(f"- {str(name)[:34]:34s} 호출 {c:>6,} · 입력 {i:>10,} ({pct(i, tin)}) · "
              f"출력 {o:>8,} · 캐시 {cr:>10,}")
    print("\n### 모델별")
    for m, c, i, o in by_model[: args.top]:
        print(f"- {str(m)[:34]:34s} 호출 {c:>6,} · 입력 {i:>10,} ({pct(i, tin)}) · 출력 {o:>8,}")
    print("\n### 일별 (최근 7일)")
    for d, i, o, c in by_day:
        print(f"- {d}  호출 {c:>5,} · 입력 {i:>10,} · 출력 {o:>8,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
