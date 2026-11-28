#!/usr/bin/env python3
"""날짜 폭탄 린트 — 테스트 픽스처의 '가까운 미래' 날짜 리터럴을 결정론적으로 막는다.

배경(실제로 두 번 CI를 물린 사고):
  테스트 픽스처에 `2026-12-31` 처럼 몇 달 뒤 날짜를 하드코딩하면, 그 날짜가 지나간 뒤에
  테스트가 조용히 깨진다. 산문에 적어둔 규칙은 안 지켜졌고, Codex/LLM은 실제 날짜 픽스처를
  습관적으로 쓴다. 그래서 검사로 만든다.

규칙: 테스트 파일의 날짜 리터럴은
  - far-future (>= FAR_FUTURE), 또는
  - 이미 지난 날짜 (<= 오늘)
이어야 한다. **앞으로 도래할 날짜만** 실패다.

왜 '이미 지난 날짜'는 통과시키는가(2026-11-28 정정):
  처음에는 `--since` 기본값을 "오늘−90일"로 두고 그 사이 구간도 위반으로 잡았다. 그런데 과거
  날짜는 앞으로도 계속 과거다 — 시간이 지나서 조용히 깨질 수가 없다(이미 깨졌다면 테스트가
  지금 실패해서 시끄럽다). 실측: contest-mcp 158건 중 136건이 이미 지난 날짜였고, 그 136건이
  진짜 폭탄 22건을 덮고 있었다. 게이트가 소음이 되면 아무도 안 본다.
  `--since DATE` 를 주면 그 날짜 이후(과거 포함)를 위반으로 잡는 **감사 모드**가 된다 —
  \"이미 만료된 픽스처를 찾을 때\" 쓴다.

사용:
    python3 gates/date_bomb.py <repo-or-dir> [<dir> ...]
    python3 gates/date_bomb.py . --since 2026-07-31 --json     # 감사 모드
    python3 gates/date_bomb.py . --allow-file tests/fixtures/legacy.json

종료 코드: 위반이 있으면 1, 없으면 0.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

FAR_FUTURE = dt.date(2099, 1, 1)

# 테스트로 간주하는 경로. **부분문자열이 아니라 경로 조각으로** 판정한다 —
# `contest-mcp/src/contest_mcp/util.py` 가 `test_` 를 포함한다고 테스트 파일로 분류돼
# 소스가 검사 대상이 된 오탐이 있었다(2026-11-28).
TEST_DIRS = frozenset(("test", "tests", "spec", "specs", "__tests__"))
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".archive"}
CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs"}

# 2026-12-31 / 2026/12/31  ('-' 와 '/' 만. '2026.12.31' 은 버전 문자열이 흔해서 제외)
RE_DASH = re.compile(r"(?<!\d)((?:19|20)\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])(?!\d)")
# 문자열 전체가 날짜(+선택적 시각)인 경우만: "20261231", "202608101000"
RE_COMPACT_WHOLE = re.compile(
    r"\A((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{0,6}\Z"
)
# datetime(2026, 12, 31) / date(2030, 1, 1)
RE_CTOR = re.compile(
    r"(?:datetime|date|timestamp|DateTime|Timestamp)\s*\(\s*((?:19|20)\d{2})\s*,\s*(0?[1-9]|1[0-2])\s*,\s*(0?[1-9]|[12]\d|3[01])"
)
# 한 줄 안의 문자열 리터럴 ('...' 또는 "...")
RE_STRING = re.compile(r"""(?:"([^"\n]*)"|'([^'\n]*)')""")


def is_test_path(path: str) -> bool:
    """경로 조각 기준 판정. 디렉터리가 `test(s)/spec(s)/__tests__` 이거나 파일명이 테스트 규약일 때만."""
    parts = path.replace(os.sep, "/").lower().split("/")
    if not parts:
        return False
    base = parts[-1]
    if any(seg in TEST_DIRS for seg in parts[:-1]):
        return True
    return (base.startswith("test_") or base.startswith("conftest")
            or "_test." in base or ".test." in base or ".spec." in base)


def classify(d: dt.date, historical_max: dt.date) -> str:
    if d >= FAR_FUTURE:
        return "far-future"
    if d <= historical_max:
        return "historical"
    return "near-future"


def scan_file(path: str, historical_max: dt.date) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                stripped = line.lstrip()
                if stripped.startswith(("#", "//")):
                    continue
                seen: set[str] = set()

                for m in RE_CTOR.finditer(line):
                    y, mo, da = (int(x) for x in m.group(1, 2, 3))
                    try:
                        d = dt.date(y, mo, da)
                    except ValueError:
                        continue
                    if classify(d, historical_max) == "near-future":
                        out.append(dict(file=path, line=lineno, date=d.isoformat(),
                                        kind="ctor", text=m.group(0)))
                    seen.add(m.group(0))

                for m in RE_DASH.finditer(line):
                    # URL 안의 날짜(yyyy-mm-dd를 경로/쿼리에 넣는 경우)는 픽스처 날짜가 아니다.
                    if re.search(r"https?://\S*$", line[: m.start()]):
                        continue
                    y, mo, da = (int(x) for x in m.group(1, 2, 3))
                    try:
                        d = dt.date(y, mo, da)
                    except ValueError:
                        continue
                    if classify(d, historical_max) == "near-future":
                        out.append(dict(file=path, line=lineno, date=d.isoformat(),
                                        kind="dash", text=m.group(0)))

                # 압축형은 '문자열 리터럴 전체가 날짜'일 때만 인정한다.
                # 그냥 8자리 숫자(PORT, ID)나 긴 hex/UUID 조각은 날짜로 오인하면 오탐이 된다.
                for sm in RE_STRING.finditer(line):
                    val = sm.group(1) if sm.group(1) is not None else sm.group(2)
                    if val is None:
                        continue
                    cm = RE_COMPACT_WHOLE.match(val.strip())
                    if not cm:
                        continue
                    y, mo, da = (int(x) for x in cm.group(1, 2, 3))
                    try:
                        d = dt.date(y, mo, da)
                    except ValueError:
                        continue
                    if classify(d, historical_max) == "near-future":
                        out.append(dict(file=path, line=lineno, date=d.isoformat(),
                                        kind="compact", text=val.strip()))
    except OSError as e:
        out.append(dict(file=path, line=0, date="", kind="io", text=str(e)))
    return out


def iter_files(roots: list[str], allow: set[str]) -> tuple[list[str], list[str]]:
    """(검사할 파일들, allow 로 제외된 파일들)을 돌려준다."""
    keep: list[str] = []
    skipped: list[str] = []
    for root in roots:
        if os.path.isfile(root):
            (skipped if os.path.abspath(root) in allow else keep).append(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() not in CODE_EXT:
                    continue
                p = os.path.join(dirpath, fn)
                (skipped if os.path.abspath(p) in allow else keep).append(p)
    return keep, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+", help="검사할 저장소/디렉터리/파일")
    ap.add_argument("--since", help="감사 모드: 이 날짜 이후(과거 포함)를 위반으로 잡는다 (YYYY-MM-DD)")
    ap.add_argument("--today", help="기준일 (YYYY-MM-DD). 기본: 오늘. 테스트가 시계에 의존하지 않게 한다")
    ap.add_argument("--all-files", action="store_true",
                    help="테스트 경로가 아닌 파일도 검사 (기본은 테스트 파일만)")
    ap.add_argument("--allow-file", action="append", default=[],
                    help="검사 제외할 파일 (반복 가능, 절대/상대 경로)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    # 기본: 앞으로 도래하는 날짜만 위반. --since 를 주면 그 날짜 이후 전부(과거 포함)를 위반으로 본다(감사 모드).
    historical_max = dt.date.fromisoformat(args.since) if args.since else today

    allow = {os.path.abspath(p) for p in args.allow_file}
    candidates, skipped = iter_files(args.roots, allow)
    violations: list[dict] = []
    scanned = 0
    for p in candidates:
        if not args.all_files and not is_test_path(p):
            continue
        scanned += 1
        violations.extend(scan_file(p, historical_max))

    if args.json:
        print(json.dumps(dict(today=today.isoformat(),
                              historical_max=historical_max.isoformat(),
                              audit_mode=bool(args.since),
                              far_future=FAR_FUTURE.isoformat(),
                              scanned_files=scanned,
                              skipped_files=len(skipped),
                              violations=violations), ensure_ascii=False, indent=2))
    else:
        for v in violations:
            print(f"[E] DAT001 {v['file']}:{v['line']}: 앞으로 도래할 날짜 {v['date']} "
                  f"({v['kind']}: {v['text']}) — 지난 날짜(<= {today}) 또는 "
                  f"far-future(>= {FAR_FUTURE}) 로 바꿔라")
        skip_note = f", allow 제외 {len(skipped)}파일" if skipped else ""
        mode = f"감사 모드(--since {args.since})" if args.since else f"기준일 {today}"
        print(f"\n검사 {scanned}파일{skip_note} · 위반 {len(violations)}건 "
              f"({mode} · 허용: <= {historical_max} 또는 >= {FAR_FUTURE})")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
