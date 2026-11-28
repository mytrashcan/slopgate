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
parser_path = "none"   # "yaml" | "fallback" — 마지막 frontmatter 파싱에 쓰인 경로
DEFAULT_INDEX_BUDGET = 60000      # characters
DESC_WARN_CHARS = 120             # 파일 기준 권고치 (skill_manage API의 60자 제한과 다름)
BODY_WARN_CHARS = 40000           # 한 스킬이 이보다 크면 분할 후보

REL_LINK = re.compile(r"`((?:references|templates|scripts|assets)/[^`\s]+\.[A-Za-z0-9]+)`")
# 다른 스킬을 이름으로 부르는 참조: `some-skill/references/x.md`.
# REL_LINK 는 `references/` 로 '시작'하는 경로만 보므로 이 꼴을 통째로 놓친다.
# 실제 사례: agent-semantic-layer 가 `write-for-reader/references/의도_발굴.md` 를 지시했는데
# 그 스킬은 Hermes 에 없고 레포 안에만 있었다 — 에이전트는 읽을 파일을 못 찾는다.
CROSS_LINK = re.compile(r"`([a-z0-9][a-z0-9_-]*)/(references|templates|assets)/([^`\s]+\.[A-Za-z0-9]+)`")
# 카테고리를 붙인 형태도 검사한다 — `<cat>/<skill>/references/x.md`. 형식만 맞고 파일이 없으면
# 게이트의 안내를 따라 카테고리를 붙였는데도 여전히 못 여는 상태가 된다(2026-11-28).
CROSS_LINK_CAT = re.compile(
    r"`([a-z0-9][a-z0-9_-]*)/([a-z0-9][a-z0-9_-]*)/(references|templates|assets)/([^`\s]+\.[A-Za-z0-9]+)`")
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
    global parser_path
    try:
        import yaml  # noqa: PLC0415
        loaded = yaml.safe_load(m.group(1))
        if isinstance(loaded, dict):
            parser_path = "yaml"
            return {str(k): "" if v is None else str(v) for k, v in loaded.items()}, body
    except Exception:
        pass
    parser_path = "fallback"
    fm: dict[str, str] = {}
    key = None            # 들여쓴 뒷줄을 이어받는 키
    mode = None           # "block"(>·|) · "plain"(접히는 평문) · "quoted"(여러 줄 인용)
    buf: list[str] = []
    quote = None          # 여러 줄에 걸친 인용 문자열의 여는 따옴표

    def flush() -> None:
        nonlocal key, mode, buf, quote
        if key is not None:
            folded = fold_lines(buf)
            if mode == "quoted":
                inner, _ = unquote(folded, quote)
                fm[key] = inner if inner is not None else folded.lstrip(quote).strip()
            else:
                fm[key] = folded
        key, mode, buf, quote = None, None, [], None

    for line in m.group(1).splitlines():
        stripped = line.strip()
        if key is not None:
            if not stripped:
                buf.append("")          # 빈 줄은 fold_lines 가 개행으로 남긴다
                continue
            if line[:1].isspace():
                # 인용 문자열·블록 스칼라 안의 `#` 는 주석이 아니라 데이터다.
                if mode == "plain" and stripped.startswith("#"):
                    continue            # 평문 스칼라는 `#` 로 시작하는 줄을 값으로 가질 수 없다
                buf.append(stripped)
                if mode == "quoted":
                    inner, _ = unquote(fold_lines(buf), quote)
                    if inner is not None:
                        flush()
                continue
            flush()                     # 들여쓰기가 끝났다 = 앞 값 종료
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if is_block_marker(v):
            # 마커(`>-`, `|2-`, `>-  # note`)는 값이 아니라 블록 시작 표시다.
            key, mode, buf = k, "block", []
            continue
        if v[:1] in ("'", '\"'):
            inner, _ = unquote(v, v[0])
            if inner is not None:
                fm[k] = inner
            else:
                key, mode, quote, buf = k, "quoted", v[0], [v]
            continue
        if v in NULL_TOKENS:
            # YAML 의 null(`~`, `null`, `NULL`)은 빈 값이다. fallback 이 문자열로 읽으면
            # 같은 파일이 yaml 경로에서는 SKL002(설명 없음)로 실패하고 CI(무 yaml)에서는
            # 통과하는 판정 뒤집힘이 생긴다.
            fm[k] = ""
            continue
        # 인용 없는 평문도 다음 줄로 접힐 수 있다 — 지금 넣고, 뒷줄이 오면 이어 붙인다.
        # 단, 값이 `#` 로 시작하면 세 값이 모두 빈 값이다: `description: # 메모`, `description:`,
        # `description: ~`. yaml 경로가 그렇게 읽는데 fallback 이 `# 메모` 를 문자열로 삼키면
        # **같은 파일이 CI(무 yaml)에서만 통과**한다 — 판정 뒤집힘(2026-11-28).
        stripped_v = v.split("#", 1)[0].strip() if v.startswith("#") else v
        if not stripped_v:
            fm[k] = ""
            key = None
            continue
        fm[k] = stripped_v
        key, mode, buf = k, "plain", [stripped_v]
    flush()
    return fm, body


# YAML 이 null 로 읽는 스칼라. frontmatter 파서 두 경로가 같은 결론을 내야 한다.
NULL_TOKENS = frozenset({"~", "null", "Null", "NULL"})


# 블록 스칼라 마커: `>`, `|-`, `>2-`, `|+` 등. 뒤에 주석이 붙을 수 있다.
BLOCK_MARKER = re.compile(r"^[>|](?:[+-]?\d*|\d+[+-]?)$")


def is_block_marker(v: str) -> bool:
    """`>`, `|-`, `>2-`, `>-   # note` 처럼 블록 스칼라를 시작하는 표시인가."""
    return bool(BLOCK_MARKER.match(v.split("#", 1)[0].strip()))


DQ_ESCAPE = {"n": "\n", "t": "\t", "0": "\0", "/": "/"}


def unquote(v: str, q: str) -> tuple:
    """여는 따옴표로 시작하는 값 → (내용, 닫는 따옴표 뒤 나머지). 미종료면 (None, "").

    YAML 인용 규칙을 지켜야 한다. 단일 인용은 안쪽 따옴표를 `''` 로, 이중 인용은 `\\"` 로
    이스케이프한다. 이걸 모르면 `Aqua Security''s`, 이스케이프된 따옴표가 든 값이 첫
    이스케이프에서 "닫혔다"고 오판돼 뒷줄이 잘린다.
    """
    i = 1
    while i < len(v):
        c = v[i]
        if q == '"' and c == "\\":
            i += 2
            continue
        if c == q:
            if q == "'" and i + 1 < len(v) and v[i + 1] == q:
                i += 2
                continue
            inner = v[1:i]
            if q == "'":
                inner = inner.replace("''", "'")
            else:
                inner = re.sub(r"\\(.)", lambda mm: DQ_ESCAPE.get(mm.group(1), mm.group(1)), inner)
            return inner, v[i + 1:]
        i += 1
    return None, ""


def fold_lines(lines: list) -> str:
    """YAML 폴딩 규칙의 근사: 줄을 공백 하나로 잇고, 빈 줄은 개행으로 남긴다."""
    out: list = []
    for ln in lines:
        if not ln:
            out.append("\n")
        elif out and out[-1] != "\n":
            out.append(" " + ln)
        else:
            out.append(ln)
    return "".join(out).strip()


# Hermes 는 시스템 프롬프트 인덱스에서 설명을 60자로 자른다(agent/skill_utils.SKILL_PROMPT_DESC_LIMIT).
# 즉 60자를 넘는 부분은 매 세션 비용에 포함되지 않는다. 비용 지표는 '잘린 길이'로 계산해야 맞다.
PROMPT_DESC_LIMIT = 60
# 코드펜스 여는 줄. SKL023 이 짝을 세는데, `~~~` 가 ``` 를 닫거나 그 반대는 성립하지 않는다 —
# 구분자 종류와 여는 길이를 함께 추적해야 한다(4중 백틱 안의 3중 백틱은 리터럴이다).
FENCE_OPEN = re.compile(r"^(\s*)(`{3,}|~{3,})")


def orphan_fence(text: str) -> bool:
    """닫히지 않은 코드펜스가 있으면 True.

    줄 개수만 세면 두 가지를 동시에 틀린다: (a) `~~~` 로 연 펜스를 ``` 로 닫았다고 세어
    넘어가고(그 뒤 본문이 코드로 렌더된다) (b) 4중 백틱 안의 3중 백틱을 경계로 세어
    정상 문서를 위반으로 만든다. CommonMark 의 닫는 규칙과 같은 방식으로 추적한다.
    """
    open_ch = ""
    open_len = 0
    for line in text.splitlines():
        m = FENCE_OPEN.match(line)
        if not m:
            continue
        ch, n = m.group(2)[0], len(m.group(2))
        if not open_ch:                      # 열기
            open_ch, open_len = ch, n
        elif ch == open_ch and n >= open_len:  # 닫기: 같은 문자 + 같은 길이 이상
            open_ch, open_len = "", 0
    return bool(open_ch)
# 인덱스 60자 안에 "언제 쓰는지"가 있는지. `Use when` 만 인정하면 `Use before`·`Use on`·
# `Use after` 로 시작하는 정상 트리거를 놓친다(실측 3건 — 고쳐 놓고도 게이트가 계속 울렸다).
TRIGGER_CUE = re.compile(
    r"\b(use (?:when|for|before|after|on|in|during|to)|whenever|when you|when an? |when the |for tasks?)\b", re.I)

# SKL022 — 같은 트리거를 노리는 스킬 쌍.
#
# 실패 모드: 인덱스에 두 스킬이 거의 같은 문장으로 뜨면 에이전트는 둘 중 하나를 골라야 하고,
# 고르는 기준이 없다. 그러면 (a) 엉뚱한 것을 로드해 헛읽음하고 (b) 있는 지식을 못 찾는다.
# 판정은 **인덱스에 실제로 보이는 60자**로 한다 — 본문이 아무리 달라도 에이전트는 그 60자만 본다.
#
# 두 축을 함께 본다:
#   head_containment: 설명 앞 60자의 내용어가 얼마나 겹치는가 (작은 쪽 기준)
#   name_containment: 이름에서 선행 동사(analyzing-/building- …)를 뗀 주제어가 얼마나 겹치는가
# 둘 다 높아야 '같은 일을 하는 두 스킬'이다. 이름만 보면 `analyzing-*` 43쌍이 쏟아지고(오탐),
# 설명만 보면 도구만 다른 쌍(예: claude-code ↔ codex)이 걸린다. 실측 조합에서 10쌍이 나왔다.
OVERLAP_STOP = frozenset((
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "use", "used", "using",
    "when", "whenever", "this", "that", "these", "those", "your", "you", "it", "is", "are", "be",
    "can", "will", "from", "as", "at", "by", "not", "if", "then", "than", "into", "out", "up", "so",
    "we", "i", "via", "their", "its",
))
# 이름 선행 동사 — 이걸 떼야 `analyzing-x` 와 `auditing-x` 가 같은 주제로 비교된다.
OVERLAP_VERBS = frozenset((
    "analyzing", "auditing", "building", "collecting", "performing", "detecting", "implementing",
    "managing", "generating", "extracting", "assessing", "designing", "deploying", "monitoring",
    "correlating", "evaluating", "executing", "creating", "writing", "reviewing", "testing",
    "finding", "running", "making", "serving", "handling", "checking", "fixing", "shipping",
))
WORD = re.compile(r"[A-Za-z][A-Za-z0-9+]{1,}")
NAME_SPLIT = re.compile(r"[-_ ]")
# 이름에서 주제를 흐리는 일반어. 이걸 안 빼면 `analyzing-prefetch-files-for-execution-history` 와
# `analyzing-windows-prefetch-with-python`(같은 도구·같은 아티팩트)이 0.33으로 떨어져 놓친다 —
# 두 이름의 공통 주제어는 `prefetch` 하나뿐인데 일반어(files/python/windows)가 분모를 키운다.
NAME_GENERIC = frozenset((
    "files", "file", "windows", "linux", "macos", "artifacts", "logs", "data", "python",
    "analysis", "security", "incident", "events", "using", "based", "from",
))
OVERLAP_HEAD_MIN = 0.5
OVERLAP_NAME_MIN = 0.5


def _words(s: str) -> set:
    return {w.lower() for w in WORD.findall(s) if w.lower() not in OVERLAP_STOP}


def _subject(name: str) -> set:
    """이름에서 선행 동사·불용어·일반어를 뗀 주제어 집합."""
    parts = [w.lower() for w in NAME_SPLIT.split(name) if w]
    if parts and parts[0] in OVERLAP_VERBS:
        parts = parts[1:]
    return {w for w in parts if w not in OVERLAP_STOP and w not in NAME_GENERIC and len(w) > 2}


def _containment(a: set, b: set) -> float:
    small = min(len(a), len(b))
    return len(a & b) / small if small else 0.0


def _leading(head: str, n: int = 2) -> set:
    """인덱스 줄 앞머리의 내용어 n개. 에이전트는 줄을 왼쪽부터 읽으므로 '앞머리가 갈리면' 고를 수 있다."""
    out = []
    for w in WORD.findall(head):
        lw = w.lower()
        if lw in OVERLAP_STOP:
            continue
        out.append(lw)
        if len(out) >= n:
            break
    return set(out)


def overlap_pairs(entries: list) -> list:
    """(rel, name, head) 목록에서 '같은 트리거를 노리는' 쌍을 찾는다.

    앞머리(_leading)가 갈리면 보고하지 않는다 — `PECmd-based: …` 와 `windowsprefetch library: …` 처럼
    도구 이름이 앞에 있으면 에이전트는 첫 단어로 고를 수 있다. 이 예외가 없으면 설명을 실제로
    구분해 놓고도 게이트가 계속 울려서, 결국 무시된다.
    """
    out = []
    for i in range(len(entries)):
        rel_a, name_a, head_a = entries[i]
        wa, sa = _words(head_a), _subject(name_a)
        if len(wa) < 3 or len(sa) < 1:
            continue
        la = _leading(head_a)
        for j in range(i + 1, len(entries)):
            rel_b, name_b, head_b = entries[j]
            wb, sb = _words(head_b), _subject(name_b)
            if len(wb) < 3 or len(sb) < 1 or not (sa & sb):
                continue
            if la and _leading(head_b) and not (la & _leading(head_b)):
                continue
            hc = _containment(wa, wb)
            if hc < OVERLAP_HEAD_MIN:
                continue
            nc = _containment(sa, sb)
            if nc < OVERLAP_NAME_MIN:
                continue
            out.append(dict(hc=round(hc, 2), nc=round(nc, 2), a=name_a, b=name_b,
                            file=rel_a, other=rel_b, head=head_a))
    out.sort(key=lambda x: -(x["hc"] + x["nc"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills-dir", default=str(DEFAULT_SKILLS_DIR))
    ap.add_argument("--index-budget", type=int, default=DEFAULT_INDEX_BUDGET)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--include-archive", action="store_true",
                    help=".archive/ 아래 스킬도 검사 (기본은 제외)")
    ap.add_argument("--overlap-allow", default=None,
                    help="SKL022 예외 목록(JSON). 각 항목에 reason이 없으면 예외로 인정하지 않는다")
    args = ap.parse_args()

    root = Path(os.path.expanduser(args.skills_dir))
    if not root.is_dir():
        print(f"skill_lint: skills dir not found: {root}", file=sys.stderr)
        return 2

    # Hermes 는 디렉터리 심볼릭을 따라 스킬을 발견한다(skill_utils). 기본 rglob 도 따라가지만
    # 플랫폼/버전에 따라 다르므로 심볼릭 링크를 명시적으로 확장한다 — 안 그러면 링크된 스킬의
    # 깨진 참조가 조용히 검사 밖에 남는다.
    found = set(root.rglob("SKILL.md"))
    for link in root.rglob("*"):
        if link.is_dir() and link.is_symlink():
            try:
                found |= set(link.rglob("SKILL.md"))
            except OSError:
                continue
    paths = sorted(found)
    if not args.include_archive:
        paths = [p for p in paths if ".archive" not in p.relative_to(root).parts]
    findings: list[dict] = []
    index_chars = 0     # 시스템 프롬프트에 실제로 들어가는 크기(설명 60자 클립 반영)
    raw_desc_chars = 0  # 원본 설명 총량 (참고용)
    no_trigger: list[str] = []  # 60자 클립에서 트리거가 사라지는 스킬
    loaded: set[str] = set()    # 이번 실행에서 활성인 스킬 이름 (SKL004 교차검사용)
    index_rows: list[tuple] = []  # (rel, name, head) — SKL022 입력

    for p in paths:
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, _ = parse_frontmatter(text)
        name, desc = fm.get("name", ""), fm.get("description", "")

        if name:
            loaded.add(name)
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
        if name:
            index_rows.append((rel, name, prompt_desc))

        if len(desc) > DESC_WARN_CHARS:
            findings.append(dict(sev="W", id="SKL010", file=rel,
                                 msg=f"description {len(desc)}자 (권고 {DESC_WARN_CHARS}자 이하)"))
        if len(text) > BODY_WARN_CHARS:
            findings.append(dict(sev="W", id="SKL011", file=rel,
                                 msg=f"SKILL.md {len(text)}자 (분할 후보)"))

        # SKL023 — 코드펜스 짝. 닫히지 않으면 그 뒤 전체가 코드로 렌더돼 지시가 본문에서 사라진다.
        # 줄 개수만 세면 `~~~`/``` 혼용과 4중 백틱에서 틀린다 — orphan_fence 가 CommonMark 규칙대로 센다.
        if orphan_fence(text):
            findings.append(dict(sev="E", id="SKL023", file=rel,
                                 msg="코드펜스 짝이 안 맞는다 — 이 뒤 본문이 전부 코드로 렌더된다"))

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

    # SKL004 다른 스킬을 이름으로 부르는데 그 이름이 활성 집합에 없다.
    # 아카이브로 옮기면 호출자가 조용히 '스킬 없음'을 만난다 — 파일 참조(SKL003)와 다른 축이다.
    # 판정은 '아카이브 디렉터리에 그 이름이 있는가'로만 한다 — 아카이브 목록이 곧 허용 집합이라
    # 오탐이 구조적으로 불가능하다. 하이픈 개수 같은 휴리스틱을 넣으면 두 단어짜리 스킬을 놓친다
    # (실제로 retired-security-skill 이 그렇게 빠져 테스트가 실패했다).
    if not args.include_archive:
        # 판정 기준은 '길이'가 아니라 **그 자리에서 스킬을 부르는 형태인가**다.
        # 이름 길이만 보고 3자까지 넓히면 `github`(org 계정·토픽), `pdf`(일반명사),
        # `xurl`(CLI 도구), `p5js`(라이브러리)가 전부 '아카이브된 스킬 참조'로 오탐이 된다
        # (실측 8건). 반대로 7자 하한은 `docx`·`xurl`·`git` 같은 진짜 참조를 놓친다.
        # 그래서 **백틱 이름 + 스킬 동사/명사**가 같은 줄에 있을 때만 보고한다.
        # '스킬을 부르는 자리'의 표지. `see the \`pdf\` skill`·`use \`p5js\`` 는 참조지만
        # `\`github\` org account`·`topics like \`github\`` 는 일반명사다. 그래서 판정은
        # **백틱 바로 앞뒤의 두 단어**만 본다 — 줄 전체를 보면 뒤쪽에 우연히 있는 동사에 걸린다.
        BEFORE_CUE = re.compile(r"(?:\b(?:see|use|using|via|with|from|the|a)\s+)$", re.I)
        AFTER_CUE = re.compile(r"^\s*(?:skill|skills|CLI|tool)\b", re.I)
        # `\`name\` org` 처럼 소유격으로 이어지면 고유명사(조직·계정)다.
        # `\`github\` org account`·`\`github\` topic` 처럼 조직/일반명사로 이어지는 형태.
        OWNER_POSSESSIVE = re.compile(r"^\s*(?:'s\b|s'\b|org\b|account\b|topic\b)", re.I)
        names_re = re.compile(r"`([a-z0-9][a-z0-9-]{2,})`")
        for p in paths:
            rel = str(p.relative_to(root))
            text = p.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                for cand in sorted(set(names_re.findall(line))):
                    if cand in loaded or cand == p.parent.name:
                        continue
                    if not (root / ".archive" / cand).exists():
                        continue
                    idx = line.find(f"`{cand}`")
                    before, after = line[:idx], line[idx + len(cand) + 2:]
                    if OWNER_POSSESSIVE.match(after):
                        continue      # `\`github\` org account` — 조직 이름
                    if not (BEFORE_CUE.search(before) or AFTER_CUE.search(after)):
                        continue
                    findings.append(dict(sev="W", id="SKL004", file=rel,
                                         msg=f"아카이브된 스킬을 참조: {cand} (L{lineno})"))

    # SKL024 다른 스킬 디렉터리를 **상대경로로** 지시했을 때, 그 표기가 실제로 열리는 경로인지 본다.
    # 두 경우 모두 결함이다:
    #   ① 그 스킬이 이 설치본에 없다 (레포 전용 스킬을 Hermes 스킬처럼 부른 경우)
    #   ② 스킬은 있지만 `some-skill/references/x.md` 는 `~/.hermes/skills/` 기준 경로가 아니다 —
    #      실제 파일은 `<카테고리>/some-skill/references/x.md` 에 있다. `skill_view` 로도 못 열고,
    #      상대경로로도 못 연다. SKL003 은 `references/` 로 '시작'하는 자기 참조만 보므로 새어 나간다.
    for p in paths:
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8", errors="replace")
        for cand, sub, fname in sorted(set(CROSS_LINK.findall(text))):
            if cand == p.parent.name:
                continue
            if cand not in loaded:
                findings.append(dict(sev="W", id="SKL024", file=rel,
                                     msg=f"`{cand}/` 스킬을 참조하는데 이 설치본에 없다 — "
                                         f"레포 전용 스킬이면 경로를 `.claude/skills/` 로 명시하라"))
            elif not (root / cand / sub / fname).exists():
                # 카테고리를 붙여도 파일이 없으면 여전히 못 연다 — 경로 형식만 보면 놓친다.
                findings.append(dict(sev="W", id="SKL024", file=rel,
                                     msg=f"`{cand}/{sub}/{fname}` 는 `~/.hermes/skills/` 기준으로 "
                                         f"열리지 않는다 — 카테고리를 붙여도 파일이 없다"))
        for cat, cand, sub, fname in sorted(set(CROSS_LINK_CAT.findall(text))):
            if cand == p.parent.name:
                continue
            if not (root / cat / cand / sub / fname).exists():
                findings.append(dict(sev="W", id="SKL024", file=rel,
                                     msg=f"`{cat}/{cand}/{sub}/{fname}` 파일이 없다 — "
                                         f"카테고리까지 적었는데 경로가 틀린다"))

    if no_trigger:
        findings.append(dict(sev="W", id="SKL021", file="(index)",
                             msg=f"{len(no_trigger)}개 스킬의 설명이 60자에서 잘려 '언제 쓰는지'가 "
                                 f"인덱스에서 사라진다 (예: {', '.join(no_trigger[:3])})"))

    # SKL022 같은 트리거를 노리는 스킬 쌍. 예외는 reason 이 있는 항목만 인정한다 —
    # 이유 없는 예외는 다음 세션이 "왜 둘 다 있지"를 다시 묻게 만들 뿐이다.
    allow: set = set()
    if args.overlap_allow:
        try:
            raw = json.loads(Path(args.overlap_allow).read_text(encoding="utf-8"))
            for item in raw.get("allow", raw) if isinstance(raw, dict) else raw:
                if not isinstance(item, dict) or not str(item.get("reason", "")).strip():
                    continue
                allow.add(tuple(sorted((item["a"], item["b"]))))
        except (OSError, ValueError, KeyError, TypeError) as e:
            findings.append(dict(sev="W", id="SKL022", file=(args.overlap_allow or ""),
                                 msg=f"예외 목록을 읽지 못했다({type(e).__name__}) — 전부 보고한다"))
    overlaps = [o for o in overlap_pairs(index_rows)
                if tuple(sorted((o["a"], o["b"]))) not in allow]
    if overlaps:
        findings.append(dict(sev="W", id="SKL022", file="(index)",
                             msg=f"{len(overlaps)}쌍이 같은 트리거를 노린다 — 인덱스 60자가 거의 같아 "
                                 f"에이전트가 고를 기준이 없다 (예: {overlaps[0]['a']} ↔ {overlaps[0]['b']})"))
        for o in overlaps:
            findings.append(dict(sev="W", id="SKL022", file=o["file"],
                                 msg=f"같은 트리거: `{o['b']}` (head {o['hc']:.2f} · name {o['nc']:.2f})"))
    if index_chars > args.index_budget:
        findings.append(dict(sev="W", id="SKL020", file="(index)",
                             msg=f"스킬 인덱스 {index_chars}자 > 예산 {args.index_budget}자"))

    errors = [f for f in findings if f["sev"] == "E"]
    warns = [f for f in findings if f["sev"] == "W"]
    summary = dict(skills=len(paths), index_chars=index_chars, index_budget=args.index_budget,
                   raw_desc_chars=raw_desc_chars, prompt_desc_limit=PROMPT_DESC_LIMIT,
                   errors=len(errors), warnings=len(warns),
                   # 어느 파서가 이 수치를 냈는지 결과에 남긴다. 두 경로가 조용히 갈라지면
                   # 같은 트리가 환경마다 다른 판정을 내는데, 출력만 보면 구분할 수 없다.
                   parser=parser_path)

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
              f"원본 설명 {raw_desc_chars}자) · 오류 {len(errors)} · 경고 {len(warns)}"
              f" · 파서 {parser_path}")

    failed = bool(errors) or (args.strict and bool(warns))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
