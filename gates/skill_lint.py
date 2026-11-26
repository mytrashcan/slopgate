#!/usr/bin/env python3
"""스킬 린트 — 스킬 디렉터리를 결정론적으로 검사한다.

강연의 "교정을 코드로 바꾼다" 원칙을 스킬 계층에 적용한 게이트.
산문(AGENTS.md·스킬 본문)에 적어둔 규칙은 강제되지 않는다. 여기서는 스킬 파일 자체의
구조만 본다: frontmatter, 참조 파일 실존, 인덱스 크기, 본문 크기.

사용:
    python3 gates/skill_lint.py                    # ~/.hermes/skills 검사
    python3 gates/skill_lint.py --skills-dir DIR
    python3 gates/skill_lint.py --json             # 기계 판독용
    python3 gates/skill_lint.py --strict           # 경고도 실패로 처리

종료 코드: 오류(E)가 있으면 1, 없으면 0.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_SKILLS_DIR = Path.home() / ".hermes" / "skills"
# 스킬 인덱스(이름+설명)는 매 세션 컨텍스트에 주입된다. 예산은 토큰 비용 상한이다.
DEFAULT_INDEX_BUDGET = 60000      # characters
DESC_WARN_CHARS = 120             # 파일 기준 권고치 (skill_manage API의 60자 제한과 다름)
BODY_WARN_CHARS = 40000           # 한 스킬이 이보다 크면 분할 후보

REL_LINK = re.compile(r"`((?:references|templates|scripts|assets)/[^`\s]+\.[A-Za-z0-9]+)`")
FM = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """frontmatter 를 dict 로. YAML(`>-` 접기 블록 포함)을 우선 쓰고, 없으면 줄 단위로 떨어진다.

    766개 스킬이 `description: >-` 형태의 여러 줄 설명을 쓴다. 줄 단위 파서는 첫 줄만 읽어서
    인덱스 크기를 실제보다 작게 계산한다(실측: 118,877 vs 실제 295,194). 게이트가 비용을
    과소평가하면 예산 결정이 틀어지므로 YAML 을 먼저 시도한다.
    """
    m = FM.match(text)
    if not m:
        return {}, text
    body = text[m.end():]
    try:
        import yaml  # noqa: PLC0415
        loaded = yaml.safe_load(m.group(1))
        if isinstance(loaded, dict):
            return {str(k): "" if v is None else str(v) for k, v in loaded.items()}, body
    except Exception:
        pass
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


# Hermes 는 시스템 프롬프트 인덱스에서 설명을 60자로 자른다(agent/skill_utils.SKILL_PROMPT_DESC_LIMIT).
# 즉 60자를 넘는 부분은 매 세션 비용에 포함되지 않는다. 비용 지표는 '잘린 길이'로 계산해야 맞다.
PROMPT_DESC_LIMIT = 60
TRIGGER_CUE = re.compile(r"\b(use when|use for|whenever|when you|when an? |when the |use to|for tasks?)\b", re.I)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills-dir", default=str(DEFAULT_SKILLS_DIR))
    ap.add_argument("--index-budget", type=int, default=DEFAULT_INDEX_BUDGET)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--include-archive", action="store_true",
                    help=".archive/ 아래 스킬도 검사 (기본은 제외)")
    args = ap.parse_args()

    root = Path(os.path.expanduser(args.skills_dir))
    if not root.is_dir():
        print(f"skill_lint: skills dir not found: {root}", file=sys.stderr)
        return 2

    paths = sorted(root.rglob("SKILL.md"))
    if not args.include_archive:
        paths = [p for p in paths if ".archive" not in p.relative_to(root).parts]
    findings: list[dict] = []
    index_chars = 0     # 시스템 프롬프트에 실제로 들어가는 크기(설명 60자 클립 반영)
    raw_desc_chars = 0  # 원본 설명 총량 (참고용)
    no_trigger: list[str] = []  # 60자 클립에서 트리거가 사라지는 스킬

    for p in paths:
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, _ = parse_frontmatter(text)
        name, desc = fm.get("name", ""), fm.get("description", "")

        if not name:
            findings.append(dict(sev="E", id="SKL001", file=rel, msg="frontmatter name 없음"))
        if not desc:
            findings.append(dict(sev="E", id="SKL002", file=rel, msg="frontmatter description 없음"))

        # 인덱스에서 보이는 앞 60자에 "언제 쓰는지"가 없으면, 그 스킬은 목록에서 선택되지 않는다.
        # 889개 스킬이 60자를 넘는데, 그중 대부분은 트리거 문구가 잘려 나간 뒤에 있다(실측 869건).
        head = desc[:PROMPT_DESC_LIMIT]
        if len(desc) > PROMPT_DESC_LIMIT and not TRIGGER_CUE.search(head):
            no_trigger.append(rel)

        # 인덱스 비용은 실제로 프롬프트에 들어가는 '잘린' 길이로 센다.
        prompt_desc = desc if len(desc) <= PROMPT_DESC_LIMIT else desc[:PROMPT_DESC_LIMIT - 3] + "..."
        index_chars += len(name) + len(prompt_desc) + 6
        raw_desc_chars += len(desc)

        if len(desc) > DESC_WARN_CHARS:
            findings.append(dict(sev="W", id="SKL010", file=rel,
                                 msg=f"description {len(desc)}자 (권고 {DESC_WARN_CHARS}자 이하)"))
        if len(text) > BODY_WARN_CHARS:
            findings.append(dict(sev="W", id="SKL011", file=rel,
                                 msg=f"SKILL.md {len(text)}자 (분할 후보)"))

        # `references/`·`templates/`·`assets/` 는 스킬 로컬 규약이라 디렉터리가 없어도
        # '자기 것을 가리킨다'고 본다 → 디렉터리 부재도 위반으로 잡는다.
        # `scripts/` 만 예외: 프로젝트 저장소의 스크립트를 가리키는 서술이 흔해서,
        # 스킬이 자기 `scripts/` 를 갖고 있을 때만 검사한다.
        for ref in sorted(set(REL_LINK.findall(text))):
            if any(c in ref for c in "*<>"):
                continue  # glob/플레이스홀더 표기는 대상 아님
            group = ref.split("/", 1)[0]
            if group == "scripts" and not (p.parent / group).is_dir():
                continue
            if not (p.parent / ref).exists():
                findings.append(dict(sev="E", id="SKL003", file=rel, msg=f"참조 파일 없음: {ref}"))

    if no_trigger:
        findings.append(dict(sev="W", id="SKL021", file="(index)",
                             msg=f"{len(no_trigger)}개 스킬의 설명이 60자에서 잘려 '언제 쓰는지'가 "
                                 f"인덱스에서 사라진다 (예: {', '.join(no_trigger[:3])})"))
    if index_chars > args.index_budget:
        findings.append(dict(sev="W", id="SKL020", file="(index)",
                             msg=f"스킬 인덱스 {index_chars}자 > 예산 {args.index_budget}자"))

    errors = [f for f in findings if f["sev"] == "E"]
    warns = [f for f in findings if f["sev"] == "W"]
    summary = dict(skills=len(paths), index_chars=index_chars, index_budget=args.index_budget,
                   raw_desc_chars=raw_desc_chars, prompt_desc_limit=PROMPT_DESC_LIMIT,
                   errors=len(errors), warnings=len(warns))

    if args.json:
        print(json.dumps(dict(summary=summary, findings=findings), ensure_ascii=False, indent=2))
    else:
        # 같은 ID 가 수십 줄 쏟아지면 요약이 묻힌다 → ID 별로 5줄까지 보여주고 나머지는 개수로 접는다.
        seen: dict[str, int] = {}
        for f in findings:
            seen[f["id"]] = seen.get(f["id"], 0) + 1
            if seen[f["id"]] <= 5 or f["sev"] == "E":
                print(f"[{f['sev']}] {f['id']} {f['file']}: {f['msg']}")
        for fid, n in seen.items():
            if n > 5:
                print(f"[W] {fid} …외 {n - 5}건 (전체 목록은 --json)")
        print(f"\n스킬 {summary['skills']}개 · 인덱스 {index_chars}자 "
              f"(예산 {args.index_budget}자, 설명 {PROMPT_DESC_LIMIT}자 클립 반영; "
              f"원본 설명 {raw_desc_chars}자) · 오류 {len(errors)} · 경고 {len(warns)}")

    failed = bool(errors) or (args.strict and bool(warns))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
