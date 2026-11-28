#!/usr/bin/env python3
"""스킬 분할 — SKILL.md의 큰 절을 `references/`로 원문 그대로 옮기고 포인터만 남긴다.

왜 도구인가: 40,000자 초과 스킬이 여럿 있고, 손으로 옮기면 (a) 내용이 조금씩 바뀌고
(b) 옮긴 뒤 원문이 온전한지 아무도 확인하지 않는다. 여기서는 옮긴 절이 참조 파일에
**한 글자도 다르지 않게** 들어갔는지를 문자열 포함으로 검증하고, 실패하면 전부 되돌린다.

원칙:
  - frontmatter(name/description)는 절대 건드리지 않는다.
  - 이동한 절은 제목 + 한 줄 포인터로 대체한다. **새 내용을 쓰지 않는다.**

사용:
    python3 scripts/split_skill.py plan.json              # 미리보기 (아무것도 쓰지 않음)
    python3 scripts/split_skill.py plan.json --apply      # 적용 + 검증 (실패 시 자동 복원)

plan.json:
    [{"skill": "/Users/kitae/.hermes/skills/research/korean-contest-sourcing",
      "moves": [{"title": "Pitfalls", "ref": "references/pitfalls.md",
                 "pointer": "항목 {n}개. 해당 항목만 열어 읽는다."}]}]

포인터의 `{n}`은 옮긴 절의 불릿 개수로 치환된다. 같은 `ref`를 여러 절이 쓰면 순서대로 덧붙는다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

FM = re.compile(r"^---\n.*?\n---\n", re.S)
FENCE_LINE = re.compile(r"^\s*(?:```|~~~)")


def _split_outside_fences(body: str) -> list[str]:
    """`## ` 경계로 자르되 **코드펜스 밖의 경계만** 인정한다.

    왜: 스킬 본문에는 ```markdown 예시 블록이 흔하고, 그 안에 `## 제목` 꼴 줄이 들어 있다.
    펜스 상태를 무시하면 그 줄을 진짜 절 경계로 착각해 절이 펜스 중간에서 잘린다 —
    옮긴 파일과 남은 파일 양쪽에 닫히지 않은 펜스가 생기고, 렌더러는 그 뒤를 전부 코드로 본다.
    """
    parts: list[str] = []
    cur: list[str] = []
    fence = False
    for line in body.splitlines(keepends=True):
        if FENCE_LINE.match(line):
            fence = not fence
            cur.append(line)
        elif not fence and line.startswith("## "):
            parts.append("".join(cur))
            cur = [line]
        else:
            cur.append(line)
    parts.append("".join(cur))
    return parts


def sections(text: str) -> tuple[str, str, list[tuple[str, str]]]:
    """(frontmatter, preamble, [(title, section_text)]) — 절은 코드펜스 **밖의** `## ` 경계로 자른다."""
    m = FM.match(text)
    head = m.group(0) if m else ""
    body = text[len(head):]
    parts = _split_outside_fences(body)
    pre, rest = parts[0], parts[1:]
    out = []
    for s in rest:
        mt = re.match(r"## (.+)", s)
        if not mt:
            continue
        out.append((mt.group(1).strip(), s))
    return head, pre, out


def unbalanced_fences(text: str) -> bool:
    """닫히지 않은 코드펜스가 있으면 True. 분할 결과 검증에 쓴다."""
    return sum(1 for line in text.splitlines() if FENCE_LINE.match(line)) % 2 == 1


def bullets(section: str) -> int:
    return len(re.findall(r"(?m)^\s*(?:[-*]|\d+\.)\s+\S", section))


def pointer_block(title: str, ref: str, pointer: str, n: int) -> str:
    return f"## {title}\n\n→ `{ref}` — {pointer.format(n=n)}\n\n"


def validate(text: str, moves: list[dict]) -> list[str]:
    _, _, secs = sections(text)
    titles = {t for t, _ in secs}
    missing = [m["title"] for m in moves if m["title"] not in titles]
    if missing:
        return [f"절 없음: {missing}"]
    # 같은 제목의 절이 둘 이상이면 by[title] 이 마지막 하나만 잡아 앞엣것이 조용히 사라진다.
    dup = sorted({t for t, _ in secs if [x for x, _ in secs].count(t) > 1} & {m["title"] for m in moves})
    if dup:
        return [f"제목이 중복된 절은 옮길 수 없다(내용 유실): {dup}"]
    errs = []
    for m in moves:
        if not m["ref"].startswith("references/") or not m["ref"].endswith(".md"):
            errs.append(f"ref 형식 위반: {m['ref']} (references/*.md 만)")
        if "{n}" not in m["pointer"]:
            errs.append(f"포인터에 {{n}} 없음: {m['title']} — 개수를 안 보여주면 열어야 할지 판단할 수 없다")
    return errs


def preview(item: dict) -> dict:
    sd = Path(item["skill"])
    text = (sd / "SKILL.md").read_text(encoding="utf-8")
    _, _, secs = sections(text)
    by = {t: s for t, s in secs}
    moves = item["moves"]
    errs = validate(text, moves)
    if errs:
        return dict(skill=sd.name, ok=False, error="; ".join(errs))
    moved = sum(len(by[m["title"]]) for m in moves)
    after = len(text) - moved + sum(
        len(pointer_block(m["title"], m["ref"], m["pointer"], bullets(by[m["title"]]))) for m in moves)
    return dict(skill=sd.name, ok=True, before=len(text), after=after,
                refs=[m["ref"] for m in moves], below_limit=after <= 40000)


def apply(item: dict) -> dict:
    sd = Path(item["skill"])
    path = sd / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    head, pre, secs = sections(text)
    by = {t: s for t, s in secs}
    moves = item["moves"]
    errs = validate(text, moves)
    if errs:
        return dict(skill=sd.name, ok=False, error="; ".join(errs))

    backup_path = sd / ".SKILL.md.split-bak"
    shutil.copy2(path, backup_path)
    ref_prev: dict[Path, str | None] = {}
    try:
        for m in moves:
            ref = sd / m["ref"]
            ref.parent.mkdir(parents=True, exist_ok=True)
            if ref not in ref_prev:
                ref_prev[ref] = ref.read_text(encoding="utf-8") if ref.exists() else None
            block = by[m["title"]]
            old = ref.read_text(encoding="utf-8") if ref.exists() else ""
            sep = "" if not old else ("" if old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n"))
            ref.write_text(old + sep + block.lstrip("\n"), encoding="utf-8")
            if block.strip() not in ref.read_text(encoding="utf-8"):
                raise RuntimeError(f"이관 검증 실패: {m['title']} → {m['ref']}")

        new_body = pre
        for title, block in secs:
            mv = next((m for m in moves if m["title"] == title), None)
            new_body += pointer_block(title, mv["ref"], mv["pointer"], bullets(block)) if mv else block
        new_text = head + new_body
        if not new_text.startswith(head):
            raise RuntimeError("frontmatter가 변했다")
        # 펜스 균형: 분할 전에는 짝수였는데 후에 홀수가 되면 절이 펜스 중간에서 잘린 것이다.
        if unbalanced_fences(new_text) and not unbalanced_fences(text):
            raise RuntimeError("SKILL.md 코드펜스가 짝이 안 맞는다 — 절이 펜스 중간에서 잘렸다")
        for m in moves:
            ref = sd / m["ref"]
            rt = ref.read_text(encoding="utf-8")
            if unbalanced_fences(rt):
                raise RuntimeError(f"{m['ref']} 코드펜스가 짝이 안 맞는다 — 이관 절 경계가 펜스 안이다")
        path.write_text(new_text, encoding="utf-8")

        # SKILL.md 에 `references/...` 목록이 있으면 새 파일을 등록한다(없으면 만들지 않는다).
        # 두 표기를 모두 지원한다: 불릿 목록(`- \`references/x.md\``)과 표 행(`| [references/x.md](...) |`).
        # 표만 지원하지 않으면 표 쓰는 스킬에서 새 파일이 어디에도 안 적혀 발견되지 않는다.
        bullet_reg = re.compile(r"(?m)^\s*[-*]\s*`references/([\w.\-]+\.md)`")
        table_reg = re.compile(r"(?m)^\s*\|.*\[references/([\w.\-]+\.md)\]")
        listed = {m.group(1) for m in bullet_reg.finditer(new_text)}
        listed |= {m.group(1) for m in table_reg.finditer(new_text)}
        added = []
        if listed:
            add = [Path(m["ref"]).name for m in moves if Path(m["ref"]).name not in listed]
            if add:
                first = bullet_reg.search(new_text)
                if first is not None:
                    line_end = new_text.index("\n", first.start())
                    ins = "".join(f"\n- `references/{n}` — 분할로 이관된 절" for n in add)
                    new_text = new_text[:line_end] + ins + new_text[line_end:]
                    path.write_text(new_text, encoding="utf-8")
                    added = add
                else:
                    row = table_reg.search(new_text)
                    if row is not None:
                        line_end = new_text.index("\n", row.start())
                        ins = "".join(
                            f"\n| [references/{n}](references/{n}) | 분할로 이관된 절 (포인터에서 연다) |"
                            for n in add)
                        new_text = new_text[:line_end] + ins + new_text[line_end:]
                        path.write_text(new_text, encoding="utf-8")
                        added = add

        after = len(path.read_text(encoding="utf-8"))
        return dict(skill=sd.name, ok=True, before=len(text), after=after,
                    refs=[Path(m["ref"]).name for m in moves], listed_added=added)
    except Exception as e:
        shutil.copy2(backup_path, path)
        for ref, prev in ref_prev.items():
            if prev is None:
                if ref.exists():
                    ref.unlink()
            else:
                ref.write_text(prev, encoding="utf-8")
        return dict(skill=sd.name, ok=False, error=f"{type(e).__name__}: {e} (전부 되돌림)")
    finally:
        if backup_path.exists():
            backup_path.unlink()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if isinstance(plan, dict):
        plan = plan["skills"]
    bad = 0
    for item in plan:
        r = apply(item) if args.apply else preview(item)
        if r.get("ok") is False:
            bad += 1
            print(f"[FAIL] {r['skill']}: {r['error']}")
        elif args.apply:
            extra = f" (목록 등록: {', '.join(r['listed_added'])})" if r.get("listed_added") else ""
            print(f"[OK]   {r['skill']}: {r['before']:,} → {r['after']:,}자 → {', '.join(r['refs'])}{extra}")
        else:
            flag = "" if r["below_limit"] else "  *** 아직 40,000자 초과 ***"
            print(f"[plan] {r['skill']}: {r['before']:,} → 약 {r['after']:,}자 → {', '.join(r['refs'])}{flag}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
