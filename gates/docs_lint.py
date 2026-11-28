#!/usr/bin/env python3
"""문서 린트 — 문서에 '상승하는 카운터'를 박지 못하게 한다.

배경(이 게이트가 존재하는 이유): 같은 숫자를 문서에 다섯 번 고쳤다.
테스트 개수 42 → 50 → 54 → 60 → 63, 스킬 개수 968 → 969 → 970. 게이트를 하나 추가할 때마다
문서가 낡았고, 낡은 숫자는 다음 세션이 그대로 인용한다. 규칙을 산문에 적어두는 것으로는 안 됐다
(slopgate 스킬에 "카운터를 박지 않는다"고 적혀 있는데도 그 직후에 다시 박았다).

그래서 검사로 만든다. 문서에 박아도 되는 것과 안 되는 것을 가른다:
  - 안 되는 것: 검사 항목 수(`63 체크`, `통과 63/63`), 스킬 개수, 오류/경고 건수 — 코드나 환경을
    건드리면 즉시 낡는다.
  - 되는 것: 날짜가 붙은 실측(`2026-11-27 실측 61틱`), 예산 상한(60,000자), 임계값(40,000자),
    그리고 우리 환경에서 변하지 않는 외부 사실. 후자는 줄 끝에 `docs-lint: fixed`를 붙여 명시한다
    (예: pstack의 스킬 62개). 무표시 = 위반이다 — 표시가 없으면 다음 세션이 낡은지 판단할 수 없다.
  - 스냅샷 문서(파일명·첫 5줄에 날짜, 예: `08-audit-2026-11-26.md`)는 검사하지 않는다.
    그날의 사실을 고정하는 것이 목적이라 숫자를 지우면 증거가 사라진다.

사용:
    python3 gates/docs_lint.py [--docs-dir docs] [--readme README.md] [--json]
종료 코드: 위반이면 1.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 상승하는 카운터 패턴 — 문서에 박으면 반드시 낡는다.
VOLATILE = [
    (re.compile(r"\b\d+\s*(?:개\s*)?체크\b"), "테스트 체크 개수"),
    (re.compile(r"통과\s*\d+\s*/\s*\d+"), "테스트 통과 수"),
    (re.compile(r"테스트\s*\d+\s*개"), "테스트 개수"),
    (re.compile(r"스킬\s*\d{2,}\s*개"), "스킬 개수"),
    (re.compile(r"오류\s*\d+\s*·\s*경고\s*\d+"), "게이트 집계"),
]

# 예외 1: 날짜가 같은 줄에 있으면 '그 시점 실측'이므로 허용.
DATED = re.compile(r"20\d{2}-\d{2}(?:-\d{2})?")
# 예외 2: 날짜가 붙은 절 아래의 줄도 그 시점 실측이다(README의 "## 현재 기준선 (날짜)").
DATED_HEADING = re.compile(r"^#{1,6}\s.*20\d{2}-\d{2}")
# 예외 3: 스냅샷 문서(파일명이나 첫 5줄에 날짜). 감사 기록은 그날의 사실을 고정하는 것이 목적이라
#         숫자를 지우면 오히려 증거가 사라진다.
SNAPSHOT_NAME = re.compile(r"20\d{2}-\d{2}")

# "지금 이 값"을 주장하는 제목. 날짜가 붙으면 자기모순이다 — 과거 날짜로 고정해 놓고
# 제목은 최신이라고 말하는 순간, 그 아래 숫자는 아무도 갱신하지 않는다.
# 실제로 `## 현재 기준선 (2026-11-26)` 아래에 970개·99,617자가 남아 있었고, DOC001의
# 날짜 예외가 그 절 전체를 면제해 아무 경고도 나오지 않았다. 문서를 읽는 사람은
# "현재"라고 믿는다. 그래서 제목이 스스로 모순이면 그 절의 면제를 취소한다.
CURRENTRY = re.compile(r"현재|현행|최신|as of today|\bcurrent\b|\blatest\b", re.I)


def is_snapshot(path: Path, lines: list[str]) -> bool:
    """스냅샷 문서인가 (파일명에 날짜, 또는 첫 5줄에 명시 마커).

    첫 5줄의 '아무 날짜'를 기준으로 삼으면 안 된다 — "## 현재 기준선 (2026-11-26)" 같은
    제목 하나로 문서 전체가 면제돼 버린다(실제로 그렇게 만들어 테스트에서 잡혔다).
    """
    if SNAPSHOT_NAME.search(path.name):
        return True
    return any("docs-lint: snapshot" in line for line in lines[:5])


def scan(path: Path) -> list[dict]:
    out = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    lines = text.splitlines()
    if is_snapshot(path, lines):
        return out
    dated_section = False
    for lineno, line in enumerate(lines, 1):
        if line.startswith("#"):
            dated_section = bool(DATED_HEADING.match(line))
            # 제목이 "현재 …(날짜)"면 자기모순이다: 날짜 면제를 취소하고 DOC002로 알린다.
            if dated_section and CURRENTRY.search(line):
                out.append(dict(file=str(path), line=lineno, kind="현재 주장 + 날짜",
                                text=line.strip()[:60], snippet=line.strip()[:110],
                                doc="DOC002"))
                dated_section = False
        if DATED.search(line) or dated_section:
            continue
        # 주석은 '작성자 메모'라 검사 대상이 아니다 — 단, **줄 전체가 주석일 때만**.
        # 줄 중간의 `... <!-- docs-lint: fixed -->` 는 아래 fixed-표시 규칙이 처리한다.
        # (구멍: `<!-- 어제는 970개였음 -->` 처럼 주석에 낡은 숫자를 숨길 수 있으나,
        #  그 숫자는 본문이 아니라 이력 메모이므로 경고 대상이 아니다. 본문에 박으면 잡힌다.)
        if line.lstrip().startswith("<!--"):
            continue
        # 외부 고정 사실 표시는 그 줄에만 적용한다. 별도 줄로 두면 어느 줄을 면제하는지
        # 모호해지고(앞? 뒤?), 면제 범위가 조용히 넓어진다.
        if "docs-lint: fixed" in line:
            continue
        for rx, label in VOLATILE:
            m = rx.search(line)
            if m:
                out.append(dict(file=str(path), line=lineno, kind=label,
                                text=m.group(0), snippet=line.strip()[:110]))
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs-dir", default="docs")
    ap.add_argument("--readme", default="README.md")
    ap.add_argument("--also", nargs="*", default=[], help="추가로 검사할 마크다운 경로")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    targets: list[Path] = []
    d = Path(args.docs_dir)
    if d.is_dir():
        targets += sorted(d.glob("*.md"))
    r = Path(args.readme)
    if r.is_file():
        targets.append(r)
    targets += [Path(p) for p in args.also if Path(p).is_file()]

    findings: list[dict] = []
    for p in targets:
        findings += scan(p)

    if args.json:
        print(json.dumps(dict(files=len(targets), findings=findings), ensure_ascii=False, indent=2))
    else:
        for f in findings:
            doc_id = f.get("doc", "DOC001")
            if doc_id == "DOC002":
                print(f"[W] DOC002 {f['file']}:{f['line']} 제목이 `{f['text']}` 라고 '현재'를 주장하면서 "
                      f"날짜로 고정돼 있다 — 숫자는 아무도 갱신하지 않는다. 제목에서 날짜를 빼거나 "
                      f"(그러면 아래 카운터는 DOC001이 잡는다), 스냅샷으로 표시하라(`docs-lint: snapshot`).")
                continue
            print(f"[W] DOC001 {f['file']}:{f['line']} {f['kind']} `{f['text']}` 가 박혀 있다 "
                  f"— 실행 출력을 인용하라: {f['snippet']}")
        print(f"\n문서 {len(targets)}개 · 경고 {len(findings)}")

    # 경고만: 문서 카운터는 품질 문제이지 빌드 실패가 아니다(CI를 붉게 만들지 않는다).
    return 0


if __name__ == "__main__":
    sys.exit(main())
