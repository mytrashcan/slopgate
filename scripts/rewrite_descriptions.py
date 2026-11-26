#!/usr/bin/env python3
"""스킬 description 일괄 교체기 — 매핑 JSON을 받아 SKILL.md frontmatter만 바꾼다.

왜 필요한가: Hermes는 시스템 프롬프트 인덱스에서 설명을 60자로 자른다. 60자를 넘는 설명은
"언제 쓰는지"가 잘려 나가서, 그 스킬은 목록에서 선택되지 않는다(실측 855건). 하나씩 손으로
고치면 970개를 편집해야 하므로, 판단(문구 작성)과 적용(파일 쓰기)을 분리한다.

- 판단: 사람 또는 LLM이 매핑 파일을 만든다. {"<스킬 디렉터리 상대경로>": "<새 설명>"}
- 적용: 이 스크립트가 YAML 유효성·길이·본문 무변경을 검사하며 쓴다.

두 가지 모드:
  --mode replace (기본): 설명을 매핑 값으로 통째로 교체한다.
  --mode prefix: 기존 설명 앞에 트리거 문장을 붙인다. **원문 정보를 버리지 않으면서**
      시스템 프롬프트 인덱스(앞 60자)에 "언제 쓰는지"를 노출하는 방법이다.

사용:
    python3 scripts/rewrite_descriptions.py --map desc-map.json                  # 미리보기
    python3 scripts/rewrite_descriptions.py --map desc-map.json --write
    python3 scripts/rewrite_descriptions.py --map triggers.json --mode prefix --write

안전장치:
  - 60자 초과 설명은 거부(--max-chars 로 조정)
  - frontmatter 밖(본문)은 절대 건드리지 않는다
  - 쓰기 전후로 YAML 파싱이 성공해야 한다
  - --dry-run 이 기본 동작에 가깝게, 실제 쓰기는 플래그가 있어야 한다
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

SKILLS = Path.home() / ".hermes" / "skills"
MAX_CHARS = 60
MARKETING = ("comprehensive", "powerful", "seamless", "cutting-edge", "robust", "best-in-class")


def split_frontmatter(text: str) -> tuple[str, str, str] | None:
    """(여는 ---, frontmatter 본문, 나머지) 로 나눈다. frontmatter 가 없으면 None."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines(keepends=True)
    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            end = i
            break
    if end is None:
        return None
    return "".join(lines[:1]), "".join(lines[1:end]), "".join(lines[end:])


def _quote_state_open(line: str, state: str | None) -> str | None:
    """YAML 스칼라의 인용부호가 이 줄 끝에서 열려 있는지 추적한다.

    반환: None(닫힘) / "'" 또는 '"'(열림). YAML 관례상 ''는 이스케이프된 따옴표다.
    """
    i = 0
    while i < len(line):
        ch = line[i]
        if state is None:
            if ch in "'\"":
                state = ch
        elif ch == state:
            # '' 또는 "" 는 이스케이프 → 다음 글자가 같은 따옴표면 건너뛴다
            if i + 1 < len(line) and line[i + 1] == state:
                i += 1
            else:
                state = None
        i += 1
    return state


def replace_description(fm_body: str, new_desc: str) -> str:
    """frontmatter 안의 description 값을 한 줄 따옴표 스칼라로 교체한다.

    YAML 에서 한 값이 여러 줄에 걸치는 형태가 네 가지 있다:
      1) `description: >-` / `|` 같은 블록 스칼라 → 뒤따르는 들여쓴 줄
      2) `description: 'long text...` 처럼 따옴표가 다음 줄에서 닫히는 경우
      3) 1·2 가 **빈 줄**을 사이에 두는 경우 (YAML 은 빈 줄도 스칼라에 포함한다)
      4) 한 줄짜리
    첫 구현은 (1)만 알고 (2)·(3)에서 닫는 따옴표를 본문에 남겨 YAML 을 깨뜨렸다
    (실제로 100건이 YAML 파싱 실패로 거부됐다). 그래서 인용부호 상태를 추적한다.
    """
    lines = fm_body.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        line = lines[i]
        if not line.startswith("description:"):
            out.append(line)
            i += 1
            continue

        escaped = new_desc.replace("\\", "\\\\").replace('"', '\\"')
        out.append(f'description: "{escaped}"\n')
        rest = line[len("description:"):]
        state = _quote_state_open(rest, None)
        starts_block = bool(re.match(r"\s*[>|][+-]?\s*$", rest))
        i += 1
        if starts_block or state is not None:
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() == "":
                    # 빈 줄은 스칼라에 포함될 수 있다 → 다음 줄을 보고 판단
                    if i + 1 < len(lines) and (lines[i + 1].startswith((" ", "\t"))
                                               or _quote_state_open(lines[i + 1], state) is not None):
                        i += 1
                        continue
                    break
                if not nxt.startswith((" ", "\t")):
                    break  # 새 top-level 키
                if state is not None:
                    state = _quote_state_open(nxt, state)
                    i += 1
                    if state is None:
                        break
                    continue
                i += 1  # 블록 스칼라 본문
        replaced = True

    if not replaced:
        out.insert(0, f'description: "{new_desc}"\n')
    return "".join(out)


def validate(desc: str, max_chars: int) -> list[str]:
    problems = []
    if not desc.strip():
        problems.append("빈 설명")
    if len(desc) > max_chars:
        problems.append(f"{len(desc)}자 > 상한 {max_chars}자")
    if desc.split() and desc.strip().split()[0].lower() not in {"use", "analyze", "analyse", "build",
                                                              "create", "debug", "design", "write",
                                                              "review", "run", "set", "teach", "find"}:
        # 문장이 아니라 명사구로 시작하면 '언제 쓰는지'가 드러나기 어렵다
        problems.append("권고: 'Use when …' 처럼 트리거로 시작")
    low = desc.lower()
    for word in MARKETING:
        if word in low:
            problems.append(f"마케팅 단어: {word}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="매핑 JSON 경로")
    ap.add_argument("--skills-dir", default=str(SKILLS))
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    ap.add_argument("--mode", choices=("replace", "prefix"), default="replace")
    ap.add_argument("--write", action="store_true", help="실제로 파일을 쓴다 (없으면 dry-run)")
    ap.add_argument("--backup-dir", default=None, help="변경 전 SKILL.md 백업 위치")
    args = ap.parse_args()

    mapping = json.loads(Path(os.path.expanduser(args.map)).read_text(encoding="utf-8"))
    root = Path(os.path.expanduser(args.skills_dir))
    backup = Path(os.path.expanduser(args.backup_dir)) if args.backup_dir else root.parent / "state" / "slopgate" / "desc-backup"

    applied, skipped, rejected = [], [], []
    for rel, value in mapping.items():
        path = root / rel
        if not path.is_file():
            rejected.append((rel, "파일 없음"))
            continue
        text = path.read_text(encoding="utf-8")
        parts = split_frontmatter(text)
        if parts is None:
            rejected.append((rel, "frontmatter 없음"))
            continue
        opening, fm, rest = parts
        import yaml as _yaml
        current = str((_yaml.safe_load(fm) or {}).get("description", "") or "")
        if args.mode == "prefix":
            trigger = str(value).strip()
            if current.startswith(trigger):
                skipped.append((rel, "이미 트리거 있음"))
                continue
            desc = (trigger + " " + current).strip()
        else:
            desc = str(value).strip()
        problems = validate(desc, args.max_chars)
        if args.mode == "prefix":
            # prefix 모드는 전체 설명이 60자를 넘는 게 정상이다. 앞 60자만 검사한다.
            problems = validate(desc[:args.max_chars], args.max_chars)
        if problems:
            rejected.append((rel, "; ".join(problems)))
            continue
        new_text = opening + replace_description(fm, desc) + rest

        try:
            import yaml
            before = yaml.safe_load(fm) or {}
            after = yaml.safe_load(replace_description(fm, desc)) or {}
        except Exception as e:  # noqa: BLE001
            rejected.append((rel, f"YAML 파싱 실패: {e}"))
            continue
        if after.get("description") != desc:
            rejected.append((rel, "description 반영 확인 실패"))
            continue
        # name/다른 키는 그대로여야 한다
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        if changed - {"description"}:
            rejected.append((rel, f"다른 frontmatter 키가 바뀜: {sorted(changed - {'description'})}"))
            continue

        if text == new_text:
            skipped.append((rel, "이미 동일"))
            continue
        if not args.write:
            applied.append(rel)
            continue

        backup.mkdir(parents=True, exist_ok=True)
        dest = backup / (rel.replace("/", "__"))
        shutil.copy2(path, dest)
        path.write_text(new_text, encoding="utf-8")
        applied.append(rel)

    mode = "적용" if args.write else "미리보기"
    print(f"[{mode}] 변경 {len(applied)} · 이미동일 {len(skipped)} · 거부 {len(rejected)}")
    if rejected:
        print("\n거부 목록:")
        for rel, why in rejected[:20]:
            print(f"  - {rel}: {why}")
        if len(rejected) > 20:
            print(f"  …외 {len(rejected) - 20}건")
    if not args.write:
        print("\n실제 반영: --write 를 붙여 다시 실행")
    else:
        print(f"\n백업: {backup}")
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
