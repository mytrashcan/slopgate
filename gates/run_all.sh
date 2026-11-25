#!/usr/bin/env bash
# 모든 게이트를 순서대로 실행하고 요약을 출력한다.
# 실패해도 나머지를 계속 돌려서 한 번에 전체 상태를 본다.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-/usr/local/bin/python3}"

fail=0
run() {
  echo "── $1"
  shift
  "$@"
  code=$?
  [ $code -ne 0 ] && fail=1
  echo
}

run "skill_lint"  "$PY" gates/skill_lint.py "$@"
run "memory_budget" "$PY" gates/memory_budget.py
run "cron_lint"   "$PY" gates/cron_lint.py

if [ $fail -eq 0 ]; then
  echo "결과: 통과"
else
  echo "결과: 실패 (위 오류 확인)"
fi
exit $fail
