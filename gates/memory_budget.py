#!/usr/bin/env python3
"""메모리 예산 게이트 — 상시 주입되는 메모리가 예산을 넘지 않게 한다.

메모리는 모든 턴의 컨텍스트에 들어간다. 100%에 붙으면 새 사실을 저장할 때
기존 항목을 밀어내야 하고, 그러면 어떤 사실이 사라졌는지 아무도 모른다.
그래서 예산을 사람 눈이 아니라 게이트가 본다.

사용:
    python3 gates/memory_budget.py
    python3 gates/memory_budget.py --memory-limit 20000 --user-limit 8000 --warn-ratio 0.9
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MEM_DIR = Path.home() / ".hermes" / "memories"
DEFAULT_MEMORY_LIMIT = 20000   # ~/.hermes/config.yaml memory.memory_char_limit
DEFAULT_USER_LIMIT = 8000      # ~/.hermes/config.yaml memory.user_char_limit
LONG_ENTRY_WARN = 400          # 이보다 긴 항목은 스킬/참조 문서로 옮길 후보


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--memories-dir", default=str(MEM_DIR))
    ap.add_argument("--memory-limit", type=int, default=DEFAULT_MEMORY_LIMIT)
    ap.add_argument("--user-limit", type=int, default=DEFAULT_USER_LIMIT)
    ap.add_argument("--warn-ratio", type=float, default=0.9)
    args = ap.parse_args()

    root = Path(os.path.expanduser(args.memories_dir))
    targets = [("MEMORY.md", args.memory_limit), ("USER.md", args.user_limit)]
    problems, warns = 0, 0

    for fname, limit in targets:
        p = root / fname
        if not p.exists():
            print(f"[E] MEM001 {p} 없음")
            problems += 1
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        n = len(text)
        ratio = n / limit if limit else 0
        entries = [e for e in text.split("\n§\n") if e.strip()]
        flag = "[OK]"
        if n > limit:
            flag, problems = "[E] MEM002", problems + 1
        elif ratio >= args.warn_ratio:
            flag, warns = "[W] MEM003", warns + 1
        print(f"{flag} {fname}: {n}/{limit}자 ({ratio:.0%}) · 항목 {len(entries)}개")

        long_entries = [e for e in entries if len(e) > LONG_ENTRY_WARN]
        if long_entries:
            warns += len(long_entries)
            for e in long_entries:
                head = " ".join(e.strip().split())[:60]
                print(f"[W] MEM004 {fname}: {len(e)}자 항목 — 스킬/참조로 이관 후보: {head}...")

    print(f"\n오류 {problems} · 경고 {warns}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
