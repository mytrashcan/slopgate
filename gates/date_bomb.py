#!/usr/bin/env python3
"""날짜 폭탄 린트 — 테스트 픽스처의 '가까운 미래' 날짜 리터럴을 결정론적으로 막는다.

배경(실제로 두 번 CI를 물린 사고):
  테스트 픽스처에 `2026-12-31` 처럼 몇 달 뒤 날짜를 하드코딩하면, 그 날짜가 지나간 뒤에
  테스트가 조용히 깨진다. 산문에 적어둔 규칙은 안 지켜졌고, Codex/LLM은 실제 날짜 픽스처를
  습관적으로 쓴다. 그래서 검사로 만든다.

규칙: 테스트 파일의 날짜 리터럴은
  - far-future (>= FAR_FUTURE) 이거나
  - historical (<= HISTORICAL_MAX) 이어야 한다.
둘 사이의 '가까운 미래' 구간은 실패.

`--since` (기본: 90일 전) 를 HISTORICAL_MAX 로 쓴다. 즉 "이미 지난 날짜 또는 2099년 이후"만 허용.

사용:
    python3 gates/date_bomb.py <repo-or-dir> [<dir> ...]
    python3 gates/date_bomb.py . --since 2026-07-31 --json
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
DEFAULT_HISTORICAL_WINDOW_DAYS = 90

# 테스트로 간주하는 경로 (디렉터리 조각 또는 파일명 패턴)
TEST_HINTS = ("/test/", "/tests/", "/spec/", "/__tests__/", "test_", "_test.", ".test.", ".spec.")
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
    low = path.replace(os.sep, "/").lower()
    return any(h in low for h in TEST_HINTS)


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
    ap.add_argument("--since", help="historical 상한 (YYYY-MM-DD). 기본: 오늘-90일")
    ap.add_argument("--window", type=int, default=DEFAULT_HISTORICAL_WINDOW_DAYS,
                    help=f"--since 미지정 시 사용할 일수 (기본 {DEFAULT_HISTORICAL_WINDOW_DAYS})")
    ap.add_argument("--all-files", action="store_true",
                    help="테스트 경로가 아닌 파일도 검사 (기본은 테스트 파일만)")
    ap.add_argument("--allow-file", action="append", default=[],
                    help="검사 제외할 파일 (반복 가능, 절대/상대 경로)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.since:
        historical_max = dt.date.fromisoformat(args.since)
    else:
        historical_max = dt.date.today() - dt.timedelta(days=args.window)

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
        print(json.dumps(dict(historical_max=historical_max.isoformat(),
                              far_future=FAR_FUTURE.isoformat(),
                              scanned_files=scanned,
                              skipped_files=len(skipped),
                              violations=violations), ensure_ascii=False, indent=2))
    else:
        for v in violations:
            print(f"[E] DAT001 {v['file']}:{v['line']}: 가까운 미래 날짜 {v['date']} "
                  f"({v['kind']}: {v['text']}) — historical(<= {historical_max}) 또는 "
                  f"far-future(>= {FAR_FUTURE}) 로 바꿔라")
        skip_note = f", allow 제외 {len(skipped)}파일" if skipped else ""
        print(f"\n검사 {scanned}파일{skip_note} · 위반 {len(violations)}건 "
              f"(허용: <= {historical_max} 또는 >= {FAR_FUTURE})")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
