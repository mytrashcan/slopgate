#!/usr/bin/env bash
# 모든 게이트를 순서대로 실행하고 요약을 출력한다.
# 실패해도 나머지를 계속 돌려서 한 번에 전체 상태를 본다.
#
# 사용:
#   bash gates/run_all.sh                 # ~/.hermes 위생 게이트만
#   bash gates/run_all.sh --self-test     # 게이트 자체 테스트 포함
#   bash gates/run_all.sh --repos ~/Documents/contest-mcp   # 날짜 폭탄 검사까지
set -uo pipefail
# --repos 로 들어온 상대경로는 **호출자의 cwd 기준**이다. 아래에서 저장소 루트로 cd 하므로
# 여기서 먼저 절대경로로 고정하지 않으면, 게이트가 조용히 다른 곳(또는 없는 곳)을 검사한다.
# 실제로 `--repos contest-mcp` 가 '검사 0파일 · 위반 0건'으로 통과했다(2026-11-28).
repos_raw=()
self_test=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repos) shift; while [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; do repos_raw+=("$1"); shift; done ;;
    --self-test) self_test=1; shift ;;
    *) repos_raw+=("$1"); shift ;;
  esac
done
repos=()
missing=()
for r in "${repos_raw[@]+"${repos_raw[@]}"}"; do
  if [ -d "$r" ]; then
    repos+=("$(cd "$r" && pwd)")
  else
    missing+=("$r")
  fi
done
cd "$(dirname "$0")/.."
PY="${PYTHON:-/usr/local/bin/python3}"
if [ ${#missing[@]} -gt 0 ]; then
  # 없는 경로를 조용히 빼면 '검사 0파일 · 위반 0건'이 통과로 보고된다.
  echo "[E] run_all: --repos 경로가 디렉터리가 아니다: ${missing[*]}" >&2
  exit 2
fi

fail=0
run() {
  echo "── $1"
  shift
  "$@"
  code=$?
  [ $code -ne 0 ] && fail=1
  echo
}

run "skill_lint"    "$PY" gates/skill_lint.py
run "memory_budget" "$PY" gates/memory_budget.py
run "cron_lint"     "$PY" gates/cron_lint.py
run "runtime_check" "$PY" gates/runtime_check.py
run "docs_lint"     "$PY" gates/docs_lint.py

if [ ${#repos[@]} -gt 0 ]; then
  run "date_bomb" "$PY" gates/date_bomb.py "${repos[@]}"
fi

if [ "$self_test" -eq 1 ]; then
  run "self_test" "$PY" tests/test_gates.py
fi

if [ $fail -eq 0 ]; then
  echo "결과: 통과"
else
  echo "결과: 실패 (위 오류 확인)"
fi
exit $fail
