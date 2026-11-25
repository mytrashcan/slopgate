# 기준선 — 2026-11-25 실측

대상: `~/.hermes` (macOS, macOS 27.2.1)
측정: 이 저장소의 게이트 3개 + 몇 개의 `find`/`wc`.

## 요약

| 항목 | 값 | 게이트 | 판정 |
|---|---|---|---|
| 활성 스킬 | 968개 (보관 `.archive/` 129개 별도) | — | — |
| 스킬 지원 문서 | 1,986개 마크다운 | — | — |
| 스킬 디렉터리 용량 | 172MB | — | — |
| 스킬 인덱스(이름+설명) | **118,731자** ≈ 30k 토큰/세션 | `SKL020` | 경고 |
| frontmatter 누락 | 0건 | `SKL001/002` | 통과 |
| 참조 파일 깨짐 | **12건** | `SKL003` | **실패** |
| description 120자 초과 | 62건 | `SKL010` | 경고 |
| SKILL.md 40,000자 초과 | 8건 | `SKL011` | 경고 |
| MEMORY.md | **19,439 / 20,000자 (97%)**, 57항목 | `MEM003` | 경고 |
| MEMORY 장문 항목(>400자) | 21건 | `MEM004` | 경고 |
| USER.md | 4,803 / 8,000자 (60%), 29항목 | — | 통과 |
| 크론 작업 | 15개 (활성 8) | — | — |
| 크론 프롬프트 > 9,500자 | **1건 (9,531자)** | `CRN001` | **실패** |
| 크론 스크립트 경로 누락 | 0건 | `CRN002` | 통과 |
| 후보 게이트 없는 활성 에이전트 크론 | 1건 | `CRN010` | 경고 |

## 깨진 참조 12건

| 스킬 | 없는 파일 |
|---|---|
| `autonomous-ai-agents/hermes-agent` | `references/execute-code-sandbox-env-windows.md`, `references/prompt-builder-environment-hints.md` |
| `code-review-and-quality` | `references/performance-checklist.md`, `references/security-checklist.md` |
| `performance-optimization` | `references/performance-checklist.md` |
| `security-and-hardening` | `references/security-checklist.md` |
| `shipping-and-launch` | `references/accessibility-checklist.md`, `references/definition-of-done.md`, `references/performance-checklist.md`, `references/security-checklist.md` |
| `planning-and-task-breakdown`, `incremental-implementation`, `using-agent-skills` | `references/definition-of-done.md` |
| `mem0-verification-and-diagnostics` | `scripts/probe-provider-key.py` |
| `verifying-agent-written-code` | `references/delegated-agent-runs.md` |
| `research/mogef-ai-benchmark-challenge` | `scripts/{analyze,auto_resume,build_submission,run_benchmark}.py` |
| `research/korean-contest-proposal` | `scripts/fill_hwpx_cells.py` |

패턴이 보인다. `definition-of-done.md`, `security-checklist.md`, `performance-checklist.md`는 **여러 스킬이 같은 파일을 가정**하는데 실제로는 없다. 한 번 만들면 9건이 동시에 해결되는 구조다.

## 해석

1. **가장 큰 비용은 스킬 인덱스다.** 세션마다 30k 토큰이 설명 목록에 나간다. 강연의 "산문은 마지막 층에 소량"과 정면으로 어긋난 상태다. 다만 968개를 무작정 줄이면 스킬 선택 정확도가 떨어질 수 있다. 예산을 정하고 그 안에서 정리하는 순서가 맞다 (`docs/06-open-questions.md` Q2).
2. **깨진 참조는 조용히 실패한다.** 에이전트는 스킬을 믿고 `read_file`을 호출하고, 없으면 즉석에서 우회한다. 이때 우회 결과가 정상처럼 보이는 게 더 나쁘다. 12건은 30분이면 정리된다.
3. **메모리 97%는 이미 위험 구간이다.** 새 사실을 저장할 때 가장 오래된 항목이 밀려나는데, 무엇이 사라졌는지는 아무도 기록하지 않는다.
4. **크론 1건은 지금 깨져 있다.** 9,531자 프롬프트는 `cronjob_manage(update)`로 수정할 수 없다(페이로드 잘림). 이 저장소를 만든 계기 중 하나이기도 하다.

## 재현

```bash
bash gates/run_all.sh
python3 gates/skill_lint.py --json | jq '.summary'
python3 gates/memory_budget.py
python3 gates/cron_lint.py

# 인덱스 문자수는 SKL020이 출력한다. 토큰 근사는 4자/토큰으로 나눈 값.
```

## 남은 측정 (아직 안 함)

- 토큰 사용 분포: 생성 vs 검증 vs 리뷰 (`docs/05-metrics.md`)
- PR revert율 — 이 저장소 게이트와 무관하게 별도 측정 필요
- 스킬 인덱스의 실제 토크나이저 비용 (4자/토큰 근사는 ±15% 오차)
