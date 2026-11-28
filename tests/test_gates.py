#!/usr/bin/env python3
"""게이트 자체의 테스트 — 일부러 위반을 만들어 잡히는지, 정상 입력에 오탐이 없는지 확인한다.

게이트가 조용히 고장 나면(예: 정규식 오타로 아무것도 못 잡음) 아무도 모른다.
그래서 게이트에도 테스트를 붙인다. 외부 의존성 없이 표준 라이브러리만 쓴다.

실행:
    /usr/local/bin/python3 tests/test_gates.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATES = os.path.join(ROOT, "gates")
PY = sys.executable

_failures: list[str] = []
_checks = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {name}")
    else:
        _failures.append(f"{name}: {detail}")
        print(f"  FAIL {name}  {detail}")


def run_gate(script: str, args: list[str]) -> tuple[int, str]:
    p = subprocess.run([PY, os.path.join(GATES, script)] + args,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def run_tool(script: str, args: list[str]) -> tuple[int, str]:
    """`scripts/` 아래 도구 실행. 게이트가 아니므로 경로만 다르고 계약은 같다(exit 0/1 + stdout)."""
    p = subprocess.run([PY, os.path.join(ROOT, "scripts", script)] + args,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# PyYAML 이 없는 환경(CI 러너·최소 설치)을 재현하는 실행기. 게이트는 yaml 이 있으면 쓰고
# 없으면 자체 파서로 떨어지는데, 두 경로의 측정값이 달라지면 예산 판정이 환경마다 뒤집힌다.
NO_YAML_BOOT = textwrap.dedent("""
    import builtins, runpy, sys
    _real = builtins.__import__
    def _blocked(name, *a, **k):
        if name == "yaml":
            raise ImportError("yaml blocked for this test")
        return _real(name, *a, **k)
    builtins.__import__ = _blocked
    script, rest = sys.argv[1], sys.argv[2:]
    sys.argv = [script] + rest
    runpy.run_path(script, run_name="__main__")
""")


def run_gate_no_yaml(script: str, args: list[str]) -> tuple[int, str]:
    p = subprocess.run([PY, "-c", NO_YAML_BOOT, os.path.join(GATES, script)] + args,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ---------------------------------------------------------------- skill_lint
def test_skill_lint(tmp: str) -> None:
    print("skill_lint")
    d = os.path.join(tmp, "skills")

    write(os.path.join(d, "good", "SKILL.md"),
          "---\nname: good\ndescription: fine\n---\nsee `references/ok.md`\n")
    write(os.path.join(d, "good", "references", "ok.md"), "ok\n")

    write(os.path.join(d, "broken", "SKILL.md"),
          "---\nname: broken\ndescription: missing ref\n---\nsee `references/gone.md`\n")

    write(os.path.join(d, "nofm", "SKILL.md"), "---\nname: nofm\n---\nbody\n")

    # 다른 스킬 디렉터리를 가리키는 상대경로는 자기 디렉터리에 그 폴더가 없으면 무시돼야 한다
    write(os.path.join(d, "xrepo", "SKILL.md"),
          "---\nname: xrepo\ndescription: mentions another repo\n---\nrun `scripts/tool.py` in the project\n")

    # glob / 플레이스홀더 표기도 무시
    write(os.path.join(d, "glob", "SKILL.md"),
          "---\nname: glob\ndescription: placeholder\n---\nsee `references/*.md` and `templates/<name>.md`\n")

    # .archive 는 기본 제외
    write(os.path.join(d, ".archive", "old", "SKILL.md"),
          "---\nname: old\ndescription: archived\n---\nsee `references/nope.md`\n")

    code, out = run_gate("skill_lint.py", ["--skills-dir", d])
    check("깨진 참조를 잡는다", "SKL003 broken/SKILL.md" in out and "references/gone.md" in out, out[:400])
    check("정상 참조는 통과", "good/SKILL.md" not in out, out[:400])
    check("description 누락을 잡는다", "SKL002 nofm/SKILL.md" in out, out[:400])
    check("다른 레포 상대경로는 오탐 없음", "xrepo/SKILL.md" not in out, out[:400])
    check("glob/플레이스홀더는 오탐 없음", "glob/SKILL.md" not in out, out[:400])
    check(".archive 는 기본 제외", "old/SKILL.md" not in out, out[:400])
    check("위반 있으면 exit 1", code == 1, f"exit={code}")
    check("깨진 참조 1건 정확히", out.count("SKL003") == 1, f"count={out.count('SKL003')}")

    code2, out2 = run_gate("skill_lint.py", ["--skills-dir", os.path.join(d, "good")])
    check("정상 트리는 exit 0", code2 == 0, out2[:300])

    code3, _ = run_gate("skill_lint.py", ["--skills-dir", os.path.join(tmp, "does-not-exist")])
    check("없는 경로는 exit 2", code3 == 2, f"exit={code3}")

    code4, out4 = run_gate("skill_lint.py", ["--skills-dir", d, "--include-archive"])
    check("--include-archive 면 보관 스킬도 검사", "old/SKILL.md" in out4, out4[:300])

    # 인덱스 비용은 프롬프트에 실제로 들어가는 60자 클립 기준이어야 한다.
    d2 = os.path.join(tmp, "skills-index")
    long_desc = "Use when testing the clip. " + "padding " * 40
    write(os.path.join(d2, "long", "SKILL.md"),
          f"---\nname: long\ndescription: {long_desc}\n---\nbody\n")
    write(os.path.join(d2, "short", "SKILL.md"),
          "---\nname: short\ndescription: Use when short.\n---\nbody\n")
    c_json, o_json = run_gate("skill_lint.py", ["--skills-dir", d2, "--json"])
    import json as _json
    s = _json.loads(o_json)["summary"]
    check("원본 설명은 길다", s["raw_desc_chars"] > 300, str(s))
    check("인덱스는 60자 클립 기준", s["index_chars"] < 200, str(s))

    # 멀티라인(>- 접기) 설명도 온전히 읽어야 인덱스 크기가 맞다.
    d3 = os.path.join(tmp, "skills-multi")
    write(os.path.join(d3, "multi", "SKILL.md"),
          "---\nname: multi\ndescription: >-\n  Use when the description is folded across\n"
          "  several lines and must still be measured whole.\n---\nbody\n")
    c3, o3 = run_gate("skill_lint.py", ["--skills-dir", d3, "--json"])
    s3 = _json.loads(o3)["summary"]
    check("멀티라인 설명을 온전히 센다", s3["raw_desc_chars"] > 60, str(s3))

    # PyYAML 이 없는 환경(CI 러너)에서도 같은 값이 나와야 한다. fallback 파서가 `>-` 를
    # 값으로 읽으면 설명이 2자로 잡혀 인덱스 비용이 99% 과소평가된다(실측 2자 vs 89자).
    c4, o4 = run_gate_no_yaml("skill_lint.py", ["--skills-dir", d3, "--json"])
    s4 = _json.loads(o4)["summary"]
    check("yaml 없이도 멀티라인 설명을 센다", s4["raw_desc_chars"] == s3["raw_desc_chars"],
          f"yaml={s3['raw_desc_chars']} no-yaml={s4['raw_desc_chars']}")

    # 이어지는 들여쓴 줄(평문 접기)과 여러 줄 인용 문자열도 같은 값이어야 한다.
    d4 = os.path.join(tmp, "skills-fold")
    write(os.path.join(d4, "plain", "SKILL.md"),
          "---\nname: plain\ndescription: Build a chain using SHA-256 hashing\n"
          "  for tamper detection across entries.\n---\nbody\n")
    write(os.path.join(d4, "quoted", "SKILL.md"),
          "---\nname: quoted\ndescription: 'This skill covers Aqua Security''s integration\n"
          "  and keeps the whole sentence.'\n---\nbody\n")
    c5, o5 = run_gate("skill_lint.py", ["--skills-dir", d4, "--json"])
    s5 = _json.loads(o5)["summary"]
    c6, o6 = run_gate_no_yaml("skill_lint.py", ["--skills-dir", d4, "--json"])
    s6 = _json.loads(o6)["summary"]
    check("평문 접기·인용 문자열도 yaml 과 같은 길이",
          s6["raw_desc_chars"] == s5["raw_desc_chars"],
          f"yaml={s5['raw_desc_chars']} no-yaml={s6['raw_desc_chars']}")

    # 인용 스칼라의 이스케이프·블록 마커 변형·인용 안의 `#` 도 같은 값이어야 한다.
    # 여기서 어긋나면 설명이 임의 지점에서 잘려 인덱스 비용이 조용히 틀어진다.
    d5 = os.path.join(tmp, "skills-quirk")
    write(os.path.join(d5, "dq-escape", "SKILL.md"),
          '---\nname: dq-escape\ndescription: "line one \\"q\\"\n'
          '  line two"\n---\nbody\n')
    write(os.path.join(d5, "marker-indent", "SKILL.md"),
          "---\nname: marker-indent\ndescription: >2-   # folded\n"
          "  indented text here\n  more of it\n---\nbody\n")
    write(os.path.join(d5, "hash-in-quote", "SKILL.md"),
          "---\nname: hash-in-quote\ndescription: 'Use when x\n"
          "  # data not comment\n  tail here'\n---\nbody\n")
    c7, o7 = run_gate("skill_lint.py", ["--skills-dir", d5, "--json"])
    s7 = _json.loads(o7)["summary"]
    c8, o8 = run_gate_no_yaml("skill_lint.py", ["--skills-dir", d5, "--json"])
    s8 = _json.loads(o8)["summary"]
    check("이스케이프·마커 변형·인용 내 # 도 yaml 과 일치",
          s7["raw_desc_chars"] == s8["raw_desc_chars"],
          f"yaml={s7['raw_desc_chars']} no-yaml={s8['raw_desc_chars']}")

    # YAML 의 null(`~`·`null`)은 빈 값이다. fallback 이 문자열로 읽으면 같은 파일이
    # yaml 경로에서 SKL002(설명 없음)로 실패하고 CI(무 yaml)에서는 통과한다 — 판정 뒤집힘.
    d6 = os.path.join(tmp, "skills-null")
    write(os.path.join(d6, "tilde", "SKILL.md"), "---\nname: tilde\ndescription: ~\n---\nbody\n")
    c9, o9 = run_gate("skill_lint.py", ["--skills-dir", d6, "--json"])
    c10, o10 = run_gate_no_yaml("skill_lint.py", ["--skills-dir", d6, "--json"])
    ids9 = {(f["file"], f["id"]) for f in _json.loads(o9)["findings"]}
    ids10 = {(f["file"], f["id"]) for f in _json.loads(o10)["findings"]}
    check("null 설명은 두 경로 모두 SKL002 로 잡는다", ids9 == ids10,
          f"yaml={sorted(ids9)} no-yaml={sorted(ids10)}")

    # 결과에 어느 파서가 수치를 냈는지 남아야, 두 경로가 갈라졌을 때 출력만으로 알 수 있다.
    check("결과에 파서 경로를 남긴다",
          _json.loads(o9)["summary"].get("parser") == "yaml"
          and _json.loads(o10)["summary"].get("parser") == "fallback",
          f"yaml={_json.loads(o9)['summary'].get('parser')} "
          f"no-yaml={_json.loads(o10)['summary'].get('parser')}")


# ------------------------------------------------------------- memory_budget
def test_memory_budget(tmp: str) -> None:
    print("memory_budget")
    d = os.path.join(tmp, "mem-ok")
    write(os.path.join(d, "MEMORY.md"), "a" * 100)
    write(os.path.join(d, "USER.md"), "b" * 100)
    code, out = run_gate("memory_budget.py",
                         ["--memories-dir", d, "--memory-limit", "1000", "--user-limit", "1000"])
    check("한도 이내면 통과", code == 0 and "MEM003" not in out, out[:300])

    d2 = os.path.join(tmp, "mem-over")
    write(os.path.join(d2, "MEMORY.md"), "a" * 1200)
    write(os.path.join(d2, "USER.md"), "b" * 100)
    code2, out2 = run_gate("memory_budget.py",
                           ["--memories-dir", d2, "--memory-limit", "1000", "--user-limit", "1000"])
    check("한도 초과를 잡는다", code2 == 1 and "MEM002" in out2, out2[:300])

    d3 = os.path.join(tmp, "mem-warn")
    write(os.path.join(d3, "MEMORY.md"), "a" * 950)
    write(os.path.join(d3, "USER.md"), "b" * 100)
    code3, out3 = run_gate("memory_budget.py",
                           ["--memories-dir", d3, "--memory-limit", "1000", "--user-limit", "1000"])
    check("90% 이상이면 경고", code3 == 0 and "MEM003" in out3, out3[:300])

    d4 = os.path.join(tmp, "mem-empty")
    os.makedirs(d4, exist_ok=True)
    code4, out4 = run_gate("memory_budget.py", ["--memories-dir", d4])
    check("파일 없으면 오류", code4 == 1 and "MEM001" in out4, out4[:300])


# ------------------------------------------------------------------ cron_lint
def test_cron_lint(tmp: str) -> None:
    print("cron_lint")
    sdir = os.path.join(tmp, "scripts")
    write(os.path.join(sdir, "present.py"), "print('x')\n")
    jobs = os.path.join(tmp, "jobs.json")

    def job(**kw):
        base = dict(id="1", name="n", enabled=True, prompt="p", no_agent=False,
                    script=None, monitor_script=None)
        base.update(kw)
        return base

    payload = dict(jobs=[
        job(id="ok", name="ok", prompt="x" * 100, no_agent=True, script="present.py"),
        job(id="long", name="long", prompt="x" * 9600, monitor_script="present.py"),
        job(id="nofile", name="nofile", prompt="x" * 10, no_agent=True, script="gone.py"),
        job(id="empty", name="empty", prompt="", monitor_script="present.py"),
        job(id="nogate", name="nogate", prompt="x" * 10),
        job(id="disabled", name="disabled", enabled=False, prompt="x" * 9600, script="gone.py"),
    ])
    write(jobs, json.dumps(payload))

    code, out = run_gate("cron_lint.py", ["--jobs", jobs, "--scripts-dir", sdir])
    check("긴 프롬프트를 잡는다", "CRN001 long" in out, out[:500])
    check("없는 스크립트를 잡는다", "CRN002 nofile" in out, out[:500])
    check("빈 프롬프트를 잡는다", "CRN003 empty" in out, out[:500])
    check("게이트 없는 무인 실행은 경고", "CRN010 nogate" in out, out[:500])
    check("script 로 수집하는 무인 실행은 경고하지 않는다",
          "CRN010 ok" not in out and "CRN010" in out, out[:500])
    check("비활성 작업도 검사한다(재활성화 시 고칠 수 없는 프롬프트라서)", 
          "CRN001 disabled" in out, out[:500])
    check("비활성 작업은 CRN010(무인 실행) 경고에서 제외", "CRN010 disabled" not in out, out[:500])
    check("위반 있으면 exit 1", code == 1, f"exit={code}")

    code2, out2 = run_gate("cron_lint.py",
                           ["--jobs", jobs, "--scripts-dir", sdir, "--allow-unattended-agent"])
    check("--allow-unattended-agent 는 CRN010 만 끈다", "CRN010" not in out2 and "CRN001" in out2, out2[:400])

    clean = os.path.join(tmp, "jobs-clean.json")
    write(clean, json.dumps(dict(jobs=[job(id="c", name="c", prompt="x" * 50,
                                           monitor_script="present.py")])))
    code3, out3 = run_gate("cron_lint.py", ["--jobs", clean, "--scripts-dir", sdir])
    check("정상 작업만 있으면 exit 0", code3 == 0, out3[:300])

    code4, _ = run_gate("cron_lint.py", ["--jobs", os.path.join(tmp, "nope.json")])
    check("jobs.json 없으면 exit 2", code4 == 2, f"exit={code4}")

    # --- CRN011 실효 프롬프트: 첨부 스킬 본문도 프롬프트 비용이다
    skroot = os.path.join(tmp, "skills")
    write(os.path.join(skroot, "big", "SKILL.md"), "x" * 45000)
    write(os.path.join(skroot, "small", "SKILL.md"), "x" * 300)
    eff = os.path.join(tmp, "jobs-eff.json")
    write(eff, json.dumps(dict(jobs=[
        job(id="heavy", name="heavy", prompt="x" * 3000, monitor_script="present.py",
            skills=["big"]),
        job(id="light", name="light", prompt="x" * 3000, monitor_script="present.py",
            skills=["small"]),
        job(id="ghost", name="ghost", prompt="x" * 300, monitor_script="present.py",
            skills=["missing-skill"]),
    ])))
    code5, out5 = run_gate("cron_lint.py", ["--jobs", eff, "--scripts-dir", sdir,
                                            "--skills-dir", skroot])
    check("첨부 스킬 본문을 합산해 경고한다", "CRN011 heavy" in out5, out5[:600])
    check("본문이 작으면 경고 없음", "CRN011 light" not in out5, out5[:600])
    check("없는 첨부 스킬은 따로 잡는다", "CRN012 ghost" in out5, out5[:600])
    check("CRN011/012 는 경고라 exit 0", code5 == 0, f"exit={code5}")

    # --- CRN013 도구가 꺼진 toolset을 지시하면 호출이 조용히 실패한다
    write(os.path.join(skroot, "asks", "SKILL.md"),
          "Use skill_view(name='x') then delegate_task(goal='y').\n")
    tool = os.path.join(tmp, "jobs-tools.json")
    write(tool, json.dumps(dict(jobs=[
        job(id="gap", name="gap", prompt="x" * 100, monitor_script="present.py",
            skills=["asks"], enabled_toolsets=["terminal", "file"]),
        job(id="fine", name="fine", prompt="x" * 100, monitor_script="present.py",
            skills=["asks"], enabled_toolsets=["terminal", "file", "skills", "delegation"]),
        job(id="open", name="open", prompt="x" * 100, monitor_script="present.py",
            skills=["asks"], enabled_toolsets=None),
        job(id="script", name="script", prompt="x" * 100, no_agent=True,
            script="present.py", enabled_toolsets=["terminal"]),
    ])))
    code6, out6 = run_gate("cron_lint.py", ["--jobs", tool, "--scripts-dir", sdir,
                                            "--skills-dir", skroot])
    check("꺼진 toolset을 지시하면 오류", "CRN013 gap" in out6 and "toolset 'skills'" in out6, out6[:700])
    check("delegation 누락도 함께 잡는다", "toolset 'delegation'" in out6, out6[:700])
    check("toolset이 다 켜져 있으면 통과", "CRN013 fine" not in out6, out6[:700])
    check("enabled_toolsets 미지정(None)이면 검사 안 함", "CRN013 open" not in out6, out6[:700])
    check("no_agent 스크립트 크론은 제외", "CRN013 script" not in out6, out6[:700])
    check("CRN013 은 오류라 exit 1", code6 == 1, f"exit={code6}")


# ------------------------------------------------------------------ date_bomb
def test_date_bomb(tmp: str) -> None:
    print("date_bomb")
    d = os.path.join(tmp, "repo")
    write(os.path.join(d, "tests", "test_true.py"), textwrap.dedent('''\
        from datetime import date, datetime
        A = "2027-06-30"
        B = "20271215"
        C = datetime(2028, 1, 1)
        D = date(2027, 5, 1)
    '''))
    dashes = run_gate("date_bomb.py", [d, "--today", "2026-11-28"])
    check("dash 형식을 잡는다", "2027-06-30" in dashes[1], dashes[1][:400])
    check("압축 형식을 잡는다", "2027-12-15" in dashes[1], dashes[1][:400])
    check("생성자 형식을 잡는다", "2028-01-01" in dashes[1], dashes[1][:400])
    check("date() 생성자도 잡는다", "2027-05-01" in dashes[1], dashes[1][:400])
    check("위반 있으면 exit 1", dashes[0] == 1, f"exit={dashes[0]}")

    # 세 축: 지난 날짜는 통과, 앞으로 올 날짜는 위반, 2099+ 는 통과
    n = os.path.join(tmp, "near")
    write(os.path.join(n, "tests", "test_near.py"), textwrap.dedent('''\
        PAST = "2026-09-01"
        SOON = "2026-12-31"
        FAR = "2099-01-01"
    '''))
    code_n, out_n = run_gate("date_bomb.py", [n, "--today", "2026-11-28"])
    check("이미 지난 날짜는 통과", "2026-09-01" not in out_n, out_n[:400])
    check("앞으로 올 날짜는 잡는다", "2026-12-31" in out_n, out_n[:400])
    # 메시지 본문에 'far-future(>= 2099-01-01)'가 들어가므로 줄 번호로 확인한다.
    check("2099 이후는 통과", "test_near.py:3" not in out_n, out_n[:400])
    check("지난/미래/먼미래 중 하나만 위반", out_n.count("[E] DAT001") == 1, out_n[:400])

    # 감사 모드: --since 를 주면 이미 지난 날짜도 위반 (만료된 픽스처 찾기)
    code_s, out_s = run_gate("date_bomb.py", [n, "--since", "2026-07-31"])
    check("--since 감사 모드는 지난 날짜도 잡는다", "2026-09-01" in out_s, out_s[:400])
    check("감사 모드 표시", "감사 모드" in out_s, out_s[:400])

    f = os.path.join(tmp, "fp")
    write(os.path.join(f, "tests", "test_fp.py"), textwrap.dedent('''\
        VERSION = "2026.12.31"
        PORT = 20261231
        URL = "https://example.test/x?d=2026-12-31"
        HEX = "0x20261215"
        OK_FAR = "2099-01-01"
        OK_OLD = "2026-01-01"
        # comment 2026-12-31
        BAD_DATE = "2026-02-31"
    '''))
    code, outs = run_gate("date_bomb.py", [f, "--today", "2026-11-28"])
    check("버전 문자열은 오탐 없음", "2026.12.31" not in outs, outs[:400])
    check("맨 숫자(PORT/ID)는 오탐 없음", "도 20261231" not in outs, outs[:400])
    check("URL 쿼리 날짜는 오탐 없음", "d=2026-12-31" not in outs, outs[:400])
    check("hex 조각은 오탐 없음", "0x20261215" not in outs, outs[:400])
    check("존재하지 않는 날짜는 오탐 없음", "2026-02-31" not in outs, outs[:400])
    check("오탐만 있는 트리는 exit 0", code == 0, f"exit={code} {outs[:300]}")

    # 점 구분(2026.12.20)·한국어(2027년 3월 15일) 표기도 날짜다. 예전에는 점 구분을 통째로
    # 제외했는데("버전 문자열이 흔해서"), 한국 공고문 픽스처는 대부분 이 형식이라 진짜 폭탄이
    # 전부 미검출이었다(contest-mcp에 7건). CalVer(`VERSION = "2026.12.31"`)는 식별자로 구분한다.
    k = os.path.join(tmp, "dots")
    write(os.path.join(k, "tests", "test_dot.py"),
          'DEADLINE = "2027.03.15"\n'
          'KOREAN = "2027년 3월 15일"\n'
          'VERSION = "2026.12.31"\n'
          'APP_VERSION = "2030.1.1"\n'
          'PAST_DOT = "2025.03.15"\n'
          'SEMVER = "1.2.3"\n'
          'FOUR = "2026.12.31.1"\n')
    code_k, out_k = run_gate("date_bomb.py", [k, "--today", "2026-11-28"])
    check("점 구분 미래 날짜를 잡는다", "dot: 2027.03.15" in out_k, out_k[:500])
    check("한국어 날짜를 잡는다", "korean: 2027년 3월 15일" in out_k, out_k[:500])
    check("CalVer 버전 상수는 오탐 없음", "VERSION" not in out_k and "2030.1.1" not in out_k, out_k[:500])
    check("지난 점 구분 날짜는 통과", "2025.03.15" not in out_k, out_k[:500])
    check("semver·4절 버전은 오탐 없음", "1.2.3" not in out_k and "2026.12.31.1" not in out_k, out_k[:500])
    check("점/한국어 위반은 2건만", out_k.count("[E] DAT001") == 2, out_k[:500])

    # 경로 판정: 부분문자열이 아니라 경로 조각으로 본다 (contest_mcp 오탐 회귀 방지)
    v = os.path.join(tmp, "paths")
    write(os.path.join(v, "src", "contest_mcp", "util.py"), 'X = "2027-01-01"\n')
    write(os.path.join(v, "tests", "test_x.py"), 'Y = "2027-01-01"\n')
    code_p, out_p = run_gate("date_bomb.py", [v, "--today", "2026-11-28"])
    check("이름에 test_ 가 들어간 소스는 검사하지 않는다",
          "contest_mcp" not in out_p, out_p[:400])
    check("tests/ 아래 파일은 검사한다", "test_x.py" in out_p, out_p[:400])

    # --all-files 로 테스트 아닌 파일도 검사
    g = os.path.join(tmp, "allf")
    write(os.path.join(g, "src", "mod.py"), "X = '2027-01-01'\n")
    code_a, out_a = run_gate("date_bomb.py", [g, "--today", "2026-11-28"])
    code_b, out_b = run_gate("date_bomb.py", [g, "--today", "2026-11-28", "--all-files"])
    check("기본은 테스트 파일만", code_a == 0, f"exit={code_a}")
    check("--all-files 는 전체 검사", code_b == 1 and "2027-01-01" in out_b, out_b[:300])

    # --allow-file 제외
    code_c, out_c = run_gate("date_bomb.py",
                             [d, "--today", "2026-11-28", "--allow-file",
                              os.path.join(d, "tests", "test_true.py")])
    check("--allow-file 로 제외", code_c == 0, f"exit={code_c} {out_c[:200]}")


# ------------------------------------------------------------ runtime_check
def test_runtime_check(tmp: str) -> None:
    print("runtime_check")
    import datetime as _dt

    now = _dt.datetime(2026, 11, 26, 12, 0, tzinfo=_dt.timezone.utc)

    def job(**kw):
        base = dict(id="x", name="x", enabled=True, no_agent=True, prompt="p",
                    last_status="ok", failure_streak=0, state="scheduled",
                    next_run_at=(now + _dt.timedelta(minutes=5)).isoformat(),
                    last_run_at=(now - _dt.timedelta(minutes=5)).isoformat(),
                    schedule=dict(kind="interval", minutes=5))
        base.update(kw)
        return base

    def run(payload, now_iso):
        path = os.path.join(tmp, f"rt-{abs(hash(json.dumps(payload, default=str)))}.json")
        write(path, json.dumps(dict(jobs=payload), default=str))
        return run_gate("runtime_check.py", ["--jobs", path, "--now", now_iso])

    iso = now.isoformat()

    code, out = run([job(id="ok", name="ok")], iso)
    check("정상 작업은 exit 0", code == 0, out[:300])

    code2, out2 = run([job(id="f2", name="f2", failure_streak=2,
                           last_status="error", last_error="boom")], iso)
    check("연속 실패를 잡는다", code2 == 1 and "RT001 f2" in out2, out2[:300])

    code3, out3 = run([job(id="f1", name="f1", failure_streak=1, last_status="error",
                           last_error="once")], iso)
    check("단발 실패는 경고만", code3 == 0 and "RT002 f1" in out3, out3[:300])

    code4, out4 = run([job(id="stall", name="stall",
                           next_run_at=(now - _dt.timedelta(hours=68)).isoformat())], iso)
    check("스케줄러 정지를 잡는다", code4 == 1 and "RT003 stall" in out4, out4[:300])

    code5, out5 = run([job(id="dv", name="dv", last_delivery_error="403")], iso)
    check("배달 실패를 잡는다", code5 == 1 and "RT004 dv" in out5, out5[:300])

    code6, out6 = run([job(id="old", name="old",
                           last_run_at=(now - _dt.timedelta(hours=2)).isoformat())], iso)
    check("주기 대비 지연을 경고한다", code6 == 0 and "RT005 old" in out6, out6[:300])

    code7, out7 = run([job(id="off", name="off", enabled=False, failure_streak=9,
                           last_status="error")], iso)
    check("비활성 작업은 검사하지 않는다", code7 == 0 and "off" not in out7, out7[:300])

    code8, _ = run_gate("runtime_check.py", ["--jobs", os.path.join(tmp, "nope.json")])
    check("jobs.json 없으면 exit 2", code8 == 2, f"exit={code8}")

    # RT006 게이트 조회 실패가 '후보 없음'으로 위장되는 것
    gp = os.path.join(tmp, "gate-state.json")
    gjobs = os.path.join(tmp, "g9.json")
    write(gjobs, json.dumps(dict(jobs=[job(id="sw", name="Hermes-sweeper PR 자동 리뷰 봇")])))

    write(gp, json.dumps({"fetch_fail_streak": 5}))
    code10, out10 = run_gate("runtime_check.py", ["--jobs", gjobs, "--now", iso,
                                                 "--gate-state", gp])
    check("RT006: 게이트가 조회 실패 중이면 오류", "RT006" in out10 and code10 == 1, out10[:400])

    write(gp, json.dumps({"fetch_fail_streak": 0}))
    code11, out11 = run_gate("runtime_check.py", ["--jobs", gjobs, "--now", iso,
                                                 "--gate-state", gp])
    check("RT006: 회복되면 조용하다", "RT006" not in out11 and code11 == 0, out11[:400])

    code12, out12 = run_gate("runtime_check.py", ["--jobs", gjobs, "--now", iso,
                                                 "--gate-state", os.path.join(tmp, "none.json")])
    check("RT006: 상태 파일이 없으면 그냥 통과", code12 == 0, out12[:300])


# ---------------------------------------------------------------- skill_lint SKL004
def test_skill_lint_archived_refs(tmp: str) -> None:
    print("skill_lint (SKL004 아카이브 참조)")
    root = os.path.join(tmp, "skl4")
    os.makedirs(os.path.join(root, ".archive", "retired-security-skill"), exist_ok=True)
    write(os.path.join(root, ".archive", "retired-security-skill", "SKILL.md"),
          "---\nname: retired-security-skill\ndescription: old\n---\n")
    write(os.path.join(root, "live", "SKILL.md"),
          "---\nname: live\ndescription: Use when testing.\n---\n"
          "See `retired-security-skill` for details.\nAlso `live` and `not-a-skill-flag`.\n")
    write(os.path.join(root, "clean", "SKILL.md"),
          "---\nname: clean\ndescription: Use when testing.\n---\nNo references.\n")

    code, out = run_gate("skill_lint.py", ["--skills-dir", root])
    check("아카이브된 스킬 이름을 부르면 경고", "SKL004 live/SKILL.md" in out, out[:500])
    check("활성 스킬은 참조 위반 아님", "SKL004 clean" not in out, out[:500])
    check("SKL004 는 경고라 exit 0", code == 0, f"exit={code}")

    # --include-archive 로 전체를 검사하면 교차검사는 하지 않는다(아카이브된 것끼리 참조가 정상)
    code2, out2 = run_gate("skill_lint.py", ["--skills-dir", root, "--include-archive"])
    check("--include-archive 면 SKL004 를 끈다", "SKL004" not in out2, out2[:300])


# ----------------------------------------------------------------- docs_lint
def test_docs_lint(tmp: str) -> None:
    print("docs_lint")
    d = os.path.join(tmp, "docslint")
    os.makedirs(d, exist_ok=True)

    def run_docs(name: str, body: str):
        # 케이스마다 디렉터리를 분리한다 — 같은 디렉터리를 재사용하면 앞 케이스의 위반이 따라온다.
        dd = os.path.join(d, name.replace(".", "_"))
        os.makedirs(dd, exist_ok=True)
        path = os.path.join(dd, name)
        write(path, body)
        # --readme 는 없는 경로를 준다: 같은 파일이 docs-dir과 readme로 두 번 세지면
        # 경고 수 검증이 흔들린다.
        return run_gate("docs_lint.py", ["--docs-dir", dd, "--readme", os.path.join(dd, "none.md")])

    code, out = run_docs("a.md", "# t\n통과 39/39 이라고 썼다\n")
    check("통과 수를 박으면 잡는다", "DOC001" in out, out[:300])

    code2, out2 = run_docs("b.md", "# t\n스킬 970개\n")
    check("스킬 개수를 박으면 잡는다", "DOC001" in out2, out2[:300])

    code3, out3 = run_docs("c.md", "# t\n2026-11-27 실측: 오류 3 · 경고 5\n")
    check("날짜 붙은 실측은 허용", "DOC001" not in out3, out3[:300])

    code4, out4 = run_docs("d.md", "# t\n주의: 테스트 63개 <!-- docs-lint: fixed -->\n")
    check("고정 표시가 있으면 허용", "DOC001" not in out4, out4[:300])

    code5, out5 = run_docs("2026-11-26-snapshot.md", "# t\n테스트 54개\n")
    check("스냅샷 문서는 검사하지 않는다", "DOC001" not in out5, out5[:300])

    code6, out6 = run_docs("e.md", "# t\n## 기준선 (2026-11-26)\n- 스킬 970개\n## 다른 절\n- 스킬 970개\n")
    check("날짜 붙은 절 안은 허용", out6.count("DOC001") == 1, out6[:400])

    # DOC002: 제목이 "현재 …(날짜)"면 자기모순이다 — 날짜 면제가 취소되고, 아래 카운터가 다시 잡힌다.
    # 이 케이스가 없으면 같은 숫자를 다시 박고도 게이트가 조용해진다(실제로 그렇게 놓쳤다).
    code8, out8 = run_docs("g.md", "# t\n## 현재 기준선 (2026-11-26)\n- 스킬 970개\n")
    check("'현재'를 주장하며 날짜로 고정하면 DOC002", "DOC002" in out8, out8[:400])
    check("DOC002 면 그 절의 카운터도 다시 잡힌다", "DOC001" in out8, out8[:400])

    code9, out9 = run_docs("h.md", "# t\n## 과거 기준선 (2026-11-26)\n- 스킬 970개\n")
    check("과거 시점임을 밝힌 절은 허용", "DOC002" not in out9 and "DOC001" not in out9, out9[:400])

    # 진짜 스냅샷은 '현재'라고 주장하지 않으므로 그대로 면제된다.
    code10, out10 = run_docs("2026-11-26-snap2.md", "# t\n## 현재 상태\n- 스킬 970개\n")
    check("스냅샷 문서는 여전히 면제", "DOC001" not in out10 and "DOC002" not in out10, out10[:400])

    # 영어 표기도 같은 자기모순이다 — 문서를 영어로 쓰는 순간 게이트가 조용해지면 안 된다
    code11, out11 = run_docs("i.md", "# t\n## Current baseline (2026-11-26)\n- 970 skills\n")
    check("영어 'Current' + 날짜도 DOC002", "DOC002" in out11, out11[:400])

    code7, out7 = run_docs("f.md", "# t\n그냥 문서다\n")
    check("위반 없으면 조용하고 exit 0", "DOC001" not in out7 and code7 == 0, out7[:300])


def test_split_skill(tmp: str) -> None:
    """분할 도구 자체의 테스트 — 이관이 '한 글자도 안 바뀌는가'와 실패 시 복원을 확인한다.

    이 도구는 스킬 본문을 잘라 옮기므로, 조용히 내용이 사라지면 게이트(SKL011)는 좋아지는데
    지식은 없어진다. 그래서 옮긴 뒤 원문 재구성이 맞는지를 테스트로 못박는다.
    """
    print("split_skill")
    d = os.path.join(tmp, "split")
    sd = os.path.join(d, "sample-skill")
    os.makedirs(sd, exist_ok=True)
    head = "---\nname: sample-skill\ndescription: Use when sampling.\n---\n\n"
    sec_keep = "## Keep Me\n\nshort body\n\n"
    sec_a = "## Big A\n\n- one\n- two\n- three\n\n첫 문단 원문.\n\n"
    sec_b = "## Big B\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n둘째 절 원문.\n"
    write(os.path.join(sd, "SKILL.md"), head + sec_keep + sec_a + sec_b)

    plan = [{"skill": sd, "moves": [
        {"title": "Big A", "ref": "references/big-a.md", "pointer": "항목 {n}개 — A."},
        {"title": "Big B", "ref": "references/big-b.md", "pointer": "항목 {n}개 — B."},
    ]}]
    ppath = os.path.join(d, "plan.json")
    write(ppath, json.dumps(plan, ensure_ascii=False))

    code, out = run_tool("split_skill.py", [ppath])
    with open(os.path.join(sd, "SKILL.md"), encoding="utf-8") as fh:
        after_preview = fh.read()
    check("--apply 없이는 아무것도 쓰지 않는다", after_preview.count("## Big A") == 1 and code == 0, out[:300])

    code, out = run_tool("split_skill.py", [ppath, "--apply"])
    with open(os.path.join(sd, "SKILL.md"), encoding="utf-8") as fh:
        cur = fh.read()
    ref_a = open(os.path.join(sd, "references/big-a.md"), encoding="utf-8").read()
    ref_b = open(os.path.join(sd, "references/big-b.md"), encoding="utf-8").read()

    check("적용되면 성공 보고", code == 0 and "[OK]" in out, out[:300])
    check("frontmatter는 그대로", cur.startswith(head), cur[:80])
    check("남길 절은 그대로", sec_keep in cur, cur[:400])
    check("이관된 절 원문이 참조 파일에 그대로", sec_a.strip() in ref_a and sec_b.strip() in ref_b,
          f"{len(ref_a)}/{len(ref_b)}")
    check("SKILL.md 에 포인터가 남는다", "`references/big-a.md`" in cur and "`references/big-b.md`" in cur,
          cur[:500])
    check("포인터에 불릿 개수가 치환된다", "항목 3개" in cur, cur[:600])
    check("옮긴 절 본문은 SKILL.md 에서 사라진다", "첫 문단 원문" not in cur and "둘째 절 원문." not in cur,
          cur[:600])

    # 재구성 등식: 원본 = 현재 SKILL.md + Σ(이관 절 − 포인터)
    recon = len(cur)
    for title, blk, ref in (("Big A", sec_a, ref_a), ("Big B", sec_b, ref_b)):
        start = ref.index(f"## {title}")
        recon += len(ref[start:]) - len(cur[cur.index(f"## {title}"):].split("\n## ")[0]) - 1
    check("원문 재구성이 원본 길이와 맞는다", abs(recon - len(head + sec_keep + sec_a + sec_b)) <= 3,
          f"recon={recon} orig={len(head + sec_keep + sec_a + sec_b)}")

    # 잘못된 ref 는 쓰기 전에 거부한다(references/*.md 만 허용)
    bad = os.path.join(d, "bad")
    os.makedirs(bad, exist_ok=True)
    write(os.path.join(bad, "SKILL.md"), head + sec_keep + sec_a)
    bplan = os.path.join(d, "bad.json")
    write(bplan, json.dumps([{"skill": bad, "moves": [
        {"title": "Big A", "ref": "notes.md", "pointer": "항목 {n}개"}]}], ensure_ascii=False))
    code, out = run_tool("split_skill.py", [bplan, "--apply"])
    with open(os.path.join(bad, "SKILL.md"), encoding="utf-8") as fh:
        untouched = fh.read()
    check("ref 형식이 틀리면 쓰지 않고 거부", code == 1 and sec_a in untouched, out[:300])

    # 코드펜스 안의 `## ` 는 절 경계가 아니다. 이걸 경계로 착각하면 절이 펜스 중간에서
    # 잘려 두 파일 모두에 닫히지 않은 펜스가 생기고, 렌더러는 그 뒤를 전부 코드로 본다.
    # (실제로 research-paper-writing 이 이렇게 깨졌다: SKILL.md 펜스 11개=홀수.)
    fd = os.path.join(d, "fenced")
    fsd = os.path.join(fd, "fenced-skill")
    os.makedirs(fsd, exist_ok=True)
    fenced_body = (
        "## Real Section\n\n"
        "본문 앞.\n\n"
        "```markdown\n"
        "## This Heading Is Inside A Fence\n"
        "템플릿 내용\n"
        "```\n\n"
        "본문 뒤.\n\n"
        "## Second Section\n\n"
        "둘째.\n"
    )
    write(os.path.join(fsd, "SKILL.md"), head + fenced_body)
    fplan = os.path.join(fd, "fplan.json")
    write(fplan, json.dumps([{"skill": fsd, "moves": [
        {"title": "Real Section", "ref": "references/real.md", "pointer": "항목 {n}개"}]}], ensure_ascii=False))
    code, out = run_tool("split_skill.py", [fplan, "--apply"])
    fcur = open(os.path.join(fsd, "SKILL.md"), encoding="utf-8").read()
    fref = open(os.path.join(fsd, "references/real.md"), encoding="utf-8").read()

    def fences(t: str) -> int:
        return sum(1 for line in t.splitlines() if line.lstrip().startswith("```"))

    check("펜스 안 `## ` 를 절로 오인하지 않는다", code == 0 and fences(fcur) % 2 == 0,
          f"SKILL 펜스 {fences(fcur)} · {out[:200]}")
    check("이관 파일도 펜스가 짝을 이룬다", fences(fref) % 2 == 0, f"ref 펜스 {fences(fref)}")
    check("펜스 안 헤딩이 든 절이 통째로 이관된다",
          "## This Heading Is Inside A Fence" in fref and "본문 뒤." in fref, fref[:400])
    check("펜스 안 헤딩을 별도 절로 세지 않는다", "This Heading Is Inside A Fence" not in fcur, fcur[-300:])

    # {n} 없는 포인터도 거부 — 개수를 숨기면 열어야 할지 판단할 수 없다
    nplan = os.path.join(d, "noplan.json")
    write(nplan, json.dumps([{"skill": bad, "moves": [
        {"title": "Big A", "ref": "references/a.md", "pointer": "항목 참고"}]}], ensure_ascii=False))
    code, out = run_tool("split_skill.py", [nplan, "--apply"])
    check("{n} 없는 포인터는 거부", code == 1 and "{n}" in out, out[:300])

    # 없는 절 제목은 거부
    mplan = os.path.join(d, "mplan.json")
    write(mplan, json.dumps([{"skill": bad, "moves": [
        {"title": "Nope", "ref": "references/a.md", "pointer": "항목 {n}개"}]}], ensure_ascii=False))
    code, out = run_tool("split_skill.py", [mplan, "--apply"])
    check("없는 절 제목은 거부", code == 1 and "절 없음" in out, out[:300])


def test_skill_lint_overlap(tmp: str) -> None:
    """SKL022 — 같은 트리거를 노리는 스킬 쌍 탐지.

    이 게이트의 목적은 '설명을 예쁘게'가 아니라 '에이전트가 60자만 보고 고를 수 있는가'다.
    그래서 (a) 앞머리가 같은 쌍은 잡고 (b) 앞머리가 갈리는 쌍은 통과시키는지를 둘 다 확인한다.
    """
    print("skill_lint (SKL022 트리거 중복)")
    d = os.path.join(tmp, "skl22")
    root = os.path.join(d, "skills")
    base = "---\nname: {n}\ndescription: {d}\n---\n\nbody\n"

    def mk(name: str, desc: str) -> None:
        write(os.path.join(root, name, "SKILL.md"), base.format(n=name, d=desc))

    # ① 앞머리가 거의 같은 쌍 — 잡아야 한다
    mk("analyzing-certificate-transparency-for-phishing",
       "Monitor Certificate Transparency logs using crt.sh and Certstream to detect phishing domains.")
    mk("analyzing-certificate-transparency-logs-dup",
       "Monitor Certificate Transparency logs with crt.sh to detect rogue certificate issuance.")
    code, out = run_gate("skill_lint.py", ["--skills-dir", root])
    check("같은 트리거 쌍을 잡는다", "SKL022" in out and "analyzing-certificate-transparency-logs-dup" in out,
          out[:600])
    check("SKL022 는 경고라 exit 0", code == 0, f"exit={code}")

    # ② 도구 이름을 앞에 붙여 구분한 쌍 — 통과해야 한다(이게 이 게이트의 해법이다)
    root2 = os.path.join(d, "skills2")
    root = root2
    mk("parse-prefetch-with-pecmd",
       "PECmd-based: parse Windows Prefetch files to determine program execution history and run counts.")
    mk("parse-prefetch-with-python-lib",
       "windowsprefetch library: parse Windows Prefetch files in Python for execution artifacts.")
    code2, out2 = run_gate("skill_lint.py", ["--skills-dir", root2])
    check("앞머리를 구분하면 통과", "SKL022" not in out2, out2[:600])

    # ③ 이름 주제어가 아예 다르면 같은 동사로 시작해도 쌍이 아니다
    root3 = os.path.join(d, "skills3")
    mk("analyzing-network-traffic-for-incidents",
       "Analyzes network traffic captures and flow data to identify adversary activity.")
    mk("analyzing-windows-registry-for-artifacts",
       "Extract and analyze Windows Registry hives to uncover user activity and autostart entries.")
    code3, out3 = run_gate("skill_lint.py", ["--skills-dir", root3])
    check("주제어가 다르면 쌍이 아니다", "SKL022" not in out3, out3[:600])

    # ④ reason 없는 예외는 인정하지 않는다 — 이유 없는 예외는 다음 세션이 다시 묻는다
    allowpath = os.path.join(d, "allow.json")
    write(allowpath, json.dumps([
        {"a": "analyzing-certificate-transparency-for-phishing",
         "b": "analyzing-certificate-transparency-logs-dup", "reason": ""},
    ], ensure_ascii=False))
    code4, out4 = run_gate("skill_lint.py", ["--skills-dir", os.path.join(d, "skills"), "--overlap-allow", allowpath])
    check("reason 없는 예외는 무시하고 계속 보고", "SKL022" in out4, out4[:600])

    # ⑤ reason 이 있으면 그 쌍은 조용해진다
    write(allowpath, json.dumps([
        {"a": "analyzing-certificate-transparency-for-phishing",
         "b": "analyzing-certificate-transparency-logs-dup",
         "reason": "한쪽은 phishing 감시, 다른 쪽은 rogue cert 발급 감시 — 대상이 다르다"},
    ], ensure_ascii=False))
    code5, out5 = run_gate("skill_lint.py", ["--skills-dir", os.path.join(d, "skills"), "--overlap-allow", allowpath])
    check("reason 있는 예외는 인정", "SKL022" not in out5, out5[:600])


def test_skill_lint_fence(tmp: str) -> None:
    """SKL023 — 코드펜스 짝.

    왜 게이트인가: 펜스가 홀수면 그 뒤 본문 전체가 코드로 렌더돼 지시가 화면에서 사라진다.
    파일은 멀쩡해 보이고(글자는 다 있다) 아무 게이트도 울리지 않아서 조용히 지식이 죽는다.
    실제로 분할 도구가 펜스 안의 `## ` 를 절 경계로 착각해 이 모양을 만들었다.
    """
    print("skill_lint (SKL023 펜스 짝)")
    d = os.path.join(tmp, "skl23")
    root = os.path.join(d, "skills")
    head = "---\nname: {n}\ndescription: Use when testing fence parity.\n---\n\n"

    write(os.path.join(root, "odd-fence", "SKILL.md"),
          head.format(n="odd-fence") + "```bash\necho hi\n")
    code, out = run_gate("skill_lint.py", ["--skills-dir", root])
    check("홀수 펜스를 잡는다", "SKL023" in out and "odd-fence" in out, out[:500])
    check("SKL023 은 오류라 exit 1", code == 1, f"exit={code}")

    root2 = os.path.join(d, "skills2")
    write(os.path.join(root2, "even-fence", "SKILL.md"),
          head.format(n="even-fence") + "```bash\necho hi\n```\n\n```\nblock\n```\n")
    write(os.path.join(root2, "fence-in-list", "SKILL.md"),
          head.format(n="fence-in-list") + "1. step\n   ```bash\n   echo hi\n   ```\n")
    code2, out2 = run_gate("skill_lint.py", ["--skills-dir", root2])
    check("짝이 맞으면 조용하다(들여쓴 펜스 포함)", "SKL023" not in out2, out2[:500])

    # 펜스 '안'의 `## ` 는 절 경계가 아니다 — 이걸 절로 세면 분할이 펜스를 쪼갠다
    root3 = os.path.join(d, "skills3")
    write(os.path.join(root3, "fenced-heading", "SKILL.md"),
          head.format(n="fenced-heading")
          + "## Real\n\n```markdown\n## Inside The Fence\n```\n\n## After\n\nbody\n")
    code3, out3 = run_gate("skill_lint.py", ["--skills-dir", root3])
    check("펜스 안 헤딩이 있어도 짝만 맞으면 통과", "SKL023" not in out3, out3[:500])


def test_skill_lint_cross_ref(tmp: str) -> None:
    """SKL024 — 다른 스킬 디렉터리 파일을 상대경로로 지시했는데 그 스킬이 설치본에 없다.

    왜 게이트인가: `references/x.md`(자기 것)는 SKL003이 잡지만 `some-skill/references/x.md`
    (남의 것)는 정규식이 `references/` 로 '시작'하는 경로만 봐서 통째로 새어 나간다.
    실제 사례: agent-semantic-layer 가 `write-for-reader/references/의도_발굴.md` 를 지시했는데
    write-for-reader 는 레포 안에만 있었다 — 에이전트는 `skill_view` 로도, 파일로도 못 연다.
    """
    print("skill_lint (SKL024 크로스 스킬 참조)")
    d = os.path.join(tmp, "skl24")
    root = os.path.join(d, "skills")
    head = "---\nname: {n}\ndescription: Use when testing cross-skill refs.\n---\n\n"

    write(os.path.join(root, "caller", "SKILL.md"),
          head.format(n="caller") + "work `write-for-reader/references/의도_발굴.md` first.\n")
    code, out = run_gate("skill_lint.py", ["--skills-dir", root])
    check("없는 스킬의 참조 파일을 지시하면 SKL024", "SKL024" in out and "write-for-reader" in out, out[:500])

    # 레포 경로로 명시하면 통과 — 레포 전용 스킬을 가리키는 정당한 표기다
    root2 = os.path.join(d, "skills2")
    write(os.path.join(root2, "caller", "SKILL.md"),
          head.format(n="caller") + "read `.claude/skills/write-for-reader/references/의도_발굴.md`.\n")
    code2, out2 = run_gate("skill_lint.py", ["--skills-dir", root2])
    check("`.claude/skills/...` 로 명시하면 침묵", "SKL024" not in out2, out2[:500])

    # 실제로 존재하는 스킬을 가리키면 통과
    root3 = os.path.join(d, "skills3")
    write(os.path.join(root3, "target", "SKILL.md"), head.format(n="target") + "body\n")
    write(os.path.join(root3, "target", "references", "x.md"), "내용\n")
    write(os.path.join(root3, "caller", "SKILL.md"),
          head.format(n="caller") + "see `target/references/x.md` for details.\n")
    code3, out3 = run_gate("skill_lint.py", ["--skills-dir", root3])
    check("설치본에 있는 스킬 참조는 통과", "SKL024" not in out3, out3[:500])


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="slopgate-tests-")
    try:
        test_skill_lint(tmp)
        test_memory_budget(tmp)
        test_cron_lint(tmp)
        test_date_bomb(tmp)
        test_runtime_check(tmp)
        test_docs_lint(tmp)
        test_skill_lint_archived_refs(tmp)
        test_skill_lint_overlap(tmp)
        test_skill_lint_fence(tmp)
        test_skill_lint_cross_ref(tmp)
        test_split_skill(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if _failures:
        print(f"실패 {len(_failures)}/{_checks}")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print(f"통과 {_checks}/{_checks}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
