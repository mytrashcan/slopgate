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
import re
import sys
from pathlib import Path

JOBS = Path.home() / ".hermes" / "cron" / "jobs.json"
SCRIPTS = Path.home() / ".hermes" / "scripts"
PROMPT_UPDATE_LIMIT = 9500     # 이보다 길면 cronjob_manage(update)가 실패한다
EFFECTIVE_PROMPT_LIMIT = 40000  # 프롬프트 + 첨부 스킬 본문. 회차마다 그대로 토큰이 된다
# 도구 이름 -> 그 도구가 사는 toolset 이름. 프롬프트/스킬이 이 도구를 지시하면 toolset이 켜져 있어야 한다.
TOOL_TOOLSET = {
    "skill_view": "skills", "skills_list": "skills", "skill_manage": "skills",
    "delegate_task": "delegation",
    "web_search": "web", "web_extract": "web",
    "read_file": "file", "write_file": "file", "patch": "file", "search_files": "file",
    "terminal": "terminal", "process_manage": "terminal",
    "execute_code": "code",
    "memory": "memory",
}


def required_toolsets(*texts: str) -> dict[str, str]:
    """도구 이름이 지시된 것을 찾아 {toolset: [tools]} 로. 코드블록·산문 모두 본다.

    실제 사고: 리뷰 크론의 `enabled_toolsets`가 ["terminal","file"]이라 `skill_view`가
    아예 없었는데, 런북은 `skill_view(name='hermaguard')`를 지시하고 있었다. 도구가 없으면
    호출은 조용히 실패하고 모델은 "스킬을 읽었다"고 착각한다. 설정 검사로는 안 잡힌다.
    """
    found: dict[str, list[str]] = {}
    for name, toolset in TOOL_TOOLSET.items():
        # `skill_view(` 또는 `skill_view (name=` 형태를 찾는다. 단어 경계로 오탐을 줄인다.
        if re.search(rf"\b{re.escape(name)}\s*\(", "\n".join(texts)):
            found.setdefault(toolset, []).append(name)
    return {k: v for k, v in found.items()}


def _exists_archived(skills_root: Path, name: str) -> bool:
    """이 이름이 .archive/ 에만 있는가 — 호출 시점엔 Hermes 가 발견하지 못하는 스킬이다."""
    arc = skills_root / ".archive" / name
    return arc.is_dir()


def _skill_path(skills_root: Path, name: str) -> Path | None:
    """스킬 본문 경로. **디렉터리는 돌려주지 않는다** — `SKILL.md` 라는 이름의 디렉터리가
    있으면 호출자의 read_text 가 IsADirectoryError 로 죽었다(2026-11-28)."""
    for p in sorted(skills_root.rglob(f"{name}/SKILL.md")):
        if p.is_file():
            return p
    return None


def skill_body_chars(skills_root: Path, name: str) -> int | None:
    """스킬 이름 → SKILL.md 본문 문자수. 없으면 None.

    첨부 스킬은 **본문 전체가 프롬프트에 들어간다**. 이걸 세지 않으면 회차 비용을 못 본다.
    """
    p = _skill_path(skills_root, name) if skills_root.exists() else None
    if p is None:
        return None
    try:
        return len(p.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default=str(JOBS))
    ap.add_argument("--scripts-dir", default=str(SCRIPTS))
    ap.add_argument("--skills-dir", default=str(Path.home() / ".hermes" / "skills"))
    ap.add_argument("--allow-unattended-agent", action="store_true",
                    help="게이트 없는 에이전트 크론 경고를 끈다")
    args = ap.parse_args()

    jp = Path(os.path.expanduser(args.jobs))
    if not jp.exists():
        print(f"cron_lint: jobs.json not found: {jp}", file=sys.stderr)
        return 2
    try:
        raw = json.loads(jp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        # 깨진 입력은 '위반 1건'이 아니라 '검사 불가'다. traceback으로 죽으면 호출자(크론 러너)가
        # 게이트 오류와 실제 위반을 구분하지 못하고, exit 1 이 '위반 있음'으로 오독된다.
        print(f"cron_lint: jobs.json 읽기/파싱 실패: {e}", file=sys.stderr)
        return 2
    jobs = raw.get("jobs", raw) if isinstance(raw, dict) else raw
    if not isinstance(jobs, list):
        # `{"jobs": {}}` 처럼 dict 면 아래 `for j in jobs` 가 키 문자열을 순회하며
        # `j.get` 에서 AttributeError 로 죽는다. 구조가 틀린 것도 검사 불가다.
        print(f"cron_lint: jobs.json 구조 오류 — jobs 가 배열이 아니다({type(jobs).__name__})",
              file=sys.stderr)
        return 2
    sdir = Path(os.path.expanduser(args.scripts_dir))
    skroot = Path(os.path.expanduser(args.skills_dir))

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
            if not f:
                continue
            target = sdir / f
            if not target.exists():
                print(f"[E] CRN002 {name}: {key}={f} 파일 없음")
                errors += 1
            elif target.is_dir():
                # 디렉터리는 실행할 수 없다 — 크론이 매 틱 실패하고 원인은 여기서 안 보인다.
                print(f"[E] CRN002 {name}: {key}={f} 가 디렉터리다 (실행 가능한 파일이어야 한다)")
                errors += 1
        # CRN011 실효 프롬프트: 프롬프트 + 첨부 스킬 본문. 회차마다 그대로 토큰이 된다.
        # `skill`(단수, legacy) 와 `skills`(배열) 둘 다 유효한 필드다. 하나만 읽으면
        # 나머지로 지정한 첨부가 비용 계산·도구 검사 양쪽에서 조용히 0으로 잡힌다.
        attached = list(j.get("skills") or [])
        if j.get("skill") and j["skill"] not in attached:
            attached.append(j["skill"])
        # 아카이브로 옮긴 스킬은 첨부해도 본문이 주입되지 않는다 — 발견되지 않기 때문이다.
        # 파일은 있으니 '찾았다'로 처리하면 실행 시점에 지시가 조용히 사라진다(2026-11-28).
        archived_attachments = [s for s in attached if skroot.exists() and _exists_archived(skroot, s)]
        for s in archived_attachments:
            print(f"[E] CRN012 {name}: 첨부 스킬 '{s}' 는 아카이브에만 있다 — 첨부해도 본문이 주입되지 않는다")
            errors += 1
        eff, unknown = plen, []
        for s in attached:
            n = skill_body_chars(skroot, s) if skroot.exists() else None
            if n is None:
                unknown.append(s)
            else:
                eff += n
        if attached and eff > EFFECTIVE_PROMPT_LIMIT:
            detail = f"프롬프트 {plen:,} + 첨부 {len(attached) - len(unknown)}개"
            print(f"[W] CRN011 {name}: 실효 프롬프트 {eff:,}자 > {EFFECTIVE_PROMPT_LIMIT:,}자 "
                  f"({detail}) — 판단에 기여하는 스킬만 남겨라")
            warns += 1
        if unknown:
            print(f"[W] CRN012 {name}: 첨부 스킬 본문을 못 찾음 {unknown}")
            warns += 1

        # CRN013 도구-toolset 불일치: 프롬프트·첨부 스킬이 지시하는 도구가 꺼져 있으면
        # 호출이 조용히 실패한다(모델은 성공한 줄 안다). no_agent 크론은 도구가 없으니 제외.
        if not j.get("no_agent"):
            allowed = j.get("enabled_toolsets")
            if allowed is not None:
                bodies = [j.get("prompt") or ""]
                bodies += [p.read_text(encoding="utf-8", errors="replace") if (p := _skill_path(skroot, s)) else ""
                           for s in attached]
                need = required_toolsets(*bodies)
                missing = {ts: t for ts, t in need.items() if ts not in allowed}
                for ts, tools in sorted(missing.items()):
                    print(f"[E] CRN013 {name}: {', '.join(sorted(tools))} 를 지시하는데 "
                          f"toolset '{ts}' 가 꺼져 있다 (enabled_toolsets={allowed}) — 호출이 조용히 실패한다")
                    errors += 1
        if not j.get("no_agent") and j.get("enabled") and plen == 0:
            print(f"[E] CRN003 {name}: 에이전트 크론인데 프롬프트가 비어 있음")
            errors += 1
        # CRN010: 후보 게이트 없이 매 주기 모델을 띄운다. 단 `script`가 수집한 값을 주입하는
        # 구조는 수집이 결정론적이므로 경고하지 않는다(주간 점검: script → 판단만).
        if (not j.get("no_agent") and j.get("enabled") and not j.get("monitor_script")
                and not j.get("script") and not args.allow_unattended_agent):
            print(f"[W] CRN010 {name}: 후보 게이트 없이 매 주기 모델을 띄운다")
            warns += 1

    print(f"\n크론 {len(jobs)}개(활성 {enabled}) · 오류 {errors} · 경고 {warns}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
