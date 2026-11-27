#!/usr/bin/env bash
# 모든 게이트를 순서대로 실행하고 요약을 출력한다.
# 실패해도 나머지를 계속 돌려서 한 번에 전체 상태를 본다.
#
# 사용:
#   bash gates/run_all.sh                 # ~/.hermes 위생 게이트만
#   bash gates/run_all.sh --self-test     # 게이트 자체 테스트 포함
#   bash gates/run_all.sh --repos ~/Documents/contest-mcp   # 날짜 폭탄 검사까지
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-/usr/local/bin/python3}"

repos=()
self_test=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repos) shift; while [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; do repos+=("$1"); shift; done ;;
    --self-test) self_test=1; shift ;;
    *) repos+=("$1"); shift ;;
  esac
done

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
