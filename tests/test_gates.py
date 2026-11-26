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


# ------------------------------------------------------------------ date_bomb
def test_date_bomb(tmp: str) -> None:
    print("date_bomb")
    d = os.path.join(tmp, "repo")
    write(os.path.join(d, "tests", "test_true.py"), textwrap.dedent('''\
        from datetime import date, datetime
        A = "2026-12-31"
        B = "20261215"
        C = datetime(2030, 1, 1)
        D = date(2027, 5, 1)
    '''))
    dashes = run_gate("date_bomb.py", [d, "--since", "2026-07-31"])
    check("dash 형식을 잡는다", "2026-12-31" in dashes[1], dashes[1][:400])
    check("압축 형식을 잡는다", "2026-12-15" in dashes[1], dashes[1][:400])
    check("생성자 형식을 잡는다", "2030-01-01" in dashes[1], dashes[1][:400])
    check("date() 생성자도 잡는다", "2027-05-01" in dashes[1], dashes[1][:400])
    check("위반 있으면 exit 1", dashes[0] == 1, f"exit={dashes[0]}")

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
    code, outs = run_gate("date_bomb.py", [f, "--since", "2026-07-31"])
    check("버전 문자열은 오탐 없음", "2026.12.31" not in outs, outs[:400])
    check("맨 숫자(PORT/ID)는 오탐 없음", "도 20261231" not in outs, outs[:400])
    check("URL 쿼리 날짜는 오탐 없음", "d=2026-12-31" not in outs, outs[:400])
    check("hex 조각은 오탐 없음", "0x20261215" not in outs, outs[:400])
    check("존재하지 않는 날짜는 오탐 없음", "2026-02-31" not in outs, outs[:400])
    check("오탐만 있는 트리는 exit 0", code == 0, f"exit={code} {outs[:300]}")

    # --all-files 로 테스트 아닌 파일도 검사
    g = os.path.join(tmp, "allf")
    write(os.path.join(g, "src", "mod.py"), "X = '2027-01-01'\n")
    code_a, out_a = run_gate("date_bomb.py", [g, "--since", "2026-07-31"])
    code_b, out_b = run_gate("date_bomb.py", [g, "--since", "2026-07-31", "--all-files"])
    check("기본은 테스트 파일만", code_a == 0, f"exit={code_a}")
    check("--all-files 는 전체 검사", code_b == 1 and "2027-01-01" in out_b, out_b[:300])

    # --allow-file 제외
    code_c, out_c = run_gate("date_bomb.py",
                             [d, "--since", "2026-07-31", "--allow-file",
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


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="slopgate-tests-")
    try:
        test_skill_lint(tmp)
        test_memory_budget(tmp)
        test_cron_lint(tmp)
        test_date_bomb(tmp)
        test_runtime_check(tmp)
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
